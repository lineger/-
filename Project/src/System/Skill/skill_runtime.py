from __future__ import annotations
from dataclasses import replace
from typing import List, Dict, Any
from System.Skill.skills_core import Intent, SkillSpec, CombatLike
from System.Skill.skills_simple import GenericSkill
from System.Skill.skills_scripts import ScriptedSkill
from Data.derive import recompute_derived




# ===== 執行器（唯一施放入口）=====
class SkillRuntime:
    """檢查→扣 MP（含動態折扣）→產 Intents→交給 Combat 決算→設冷卻→推回合"""
    def __init__(self, combat_engine:CombatLike, cooldown_box, status_box):
        self.combat = combat_engine
        self._cooldown_box = cooldown_box
        self._status_box   = status_box

    def _mp_cost_eff(self, state, caster_id: str, spec: SkillSpec) -> int:
        if hasattr(self.combat, "calc_effective_mp_cost"):
            return self.combat.calc_effective_mp_cost(
                state, caster_id, {"mp_cost": spec.mp_cost, "tags": list(spec.tags or [])}
            )
        return int(spec.mp_cost)

    def _cds(self, state):
        return self._cooldown_box(state)  # 由你的工程提供

    def can_cast_now(self, state, caster_id: str, spec: SkillSpec, targets: List[str]) -> bool:
        if not spec.can_cast(self.combat, state, caster_id): return False
        if self._cds(state).get(caster_id, spec.id) > 0:     return False
        _, res = self.combat._actor_view(state, actor_id=caster_id)  # 你的 _actor_view 回傳 (name,res)
        return res.mp() >= self._mp_cost_eff(state, caster_id, spec)

    def cast(self, state, caster_id: str, spec: SkillSpec, targets: List[str], advance: bool = True) -> dict:
        if not self.can_cast_now(state, caster_id, spec, targets):
            self.combat.say("現在無法施放。"); return {"ok": False}

        _, res = self.combat._actor_view(state, actor_id=caster_id)
        res.mp_sub(self._mp_cost_eff(state, caster_id, spec))

        # 【修改】 如果 targets 列表為空，嘗試獲取預設目標
        final_targets = targets
        if not final_targets:
            default_target = self.combat._get_default_target(state)
            if default_target:
                final_targets = [default_target]

        intents = spec.make_intents(self.combat, state, caster_id, final_targets)
    
        # 施放開始時快照敵人 ID，用來辨識哪些 intent 原本是敵方目標。
        # 原目標倒下後，後續攻擊段會改鎖定另一名存活敵人；
        # 原本附著在舊目標上的狀態等非傷害效果則直接略過。
        enemy_ids_at_cast = set(state.combat.enemies)
        retargeted_enemies: dict[str, str] = {}

        for it in intents:
            if not self.combat.in_battle(state):
                break

            resolved_intent = it
            target_was_enemy = it.target_id in enemy_ids_at_cast
            target_is_gone = (
                target_was_enemy
                and it.target_id not in state.combat.enemies
            )

            if target_is_gone:
                if it.kind != "damage":
                    continue

                new_target = retargeted_enemies.get(it.target_id)
                if new_target not in state.combat.enemies:
                    new_target = self._choose_retarget_enemy(state)
                    if new_target is None:
                        break
                    retargeted_enemies[it.target_id] = new_target
                    self.combat.say(
                        f"（原目標已倒下，技能轉向 "
                        f"{self.combat._name_of(state, new_target)}）"
                    )

                resolved_intent = replace(it, target_id=new_target)

            self._apply_intent(state, resolved_intent)

        cd = int(spec.cooldown or 0)
        if cd > 0: self._cds(state).set(caster_id, spec.id, cd)

        if advance and self.combat.in_battle(state):
            self.combat.flow.advance_and_enemy_auto(state)

            
        return {"ok": True}

    def _choose_retarget_enemy(self, state) -> str | None:
        candidates = list(state.combat.enemies)
        if not candidates:
            return None

        rng = getattr(getattr(self.combat, "dmg", None), "rng", None)
        choose = getattr(rng, "choice", None)
        if callable(choose):
            return choose(candidates)

        return candidates[0]

    # === Intent → Combat 決算 ===
    def _apply_intent(self, state, it: Intent):
        from System.combat_engine import StatusBox

        
        src_name = self.combat._name_of(state, it.source_id)
        tgt_name = self.combat._name_of(state, it.target_id)

        # 【新增】 檢查目標是否存在
        try:
            _, t_res = self.combat._actor_view(state, it.target_id)
        except (RuntimeError, KeyError):
            self.combat.say(f"（{tgt_name} 已經消失，技能中斷）")
            return
        
        if it.kind == "damage":
            v_atk = self.combat._battle_view(state, it.source_id)
            v_def = self.combat._battle_view(state, it.target_id)

            # 【修改點】在這裡初始化 is_crit
            is_crit = False

            
            is_magic = "magic" in it.tags
            attack_tags = self.combat._get_attack_tags(
                state,
                it.source_id,
                it.tags,
                include_weapon=not is_magic,
            )
            defense_tags = self.combat._get_defense_tags(state, it.target_id)

            if is_magic:
                raw_damage = max(
                    1,
                    int(it.amount) + int(v_atk.matk) - int(v_def.mdef),
                )
                dmg = self.combat.dmg.apply_tag_multiplier(
                    raw_damage,
                    attack_tags,
                    defense_tags,
                )
            else:
                dmg, is_crit = self.combat.dmg.calc_phys_damage(
                    v_atk.atk,
                    v_def.def_,
                    v_atk.crit,
                    attack_tags,
                    defense_tags,
                )

            self.combat.say(f"{src_name} 對 {tgt_name} 造成 {dmg} 傷害" + ("（暴擊！）" if is_crit else ""))

            _, t_res = self.combat._actor_view(state, it.target_id)
            t_res.hp_sub(dmg)

            # 【新增】檢查並解除石化
            status_box = self._status_box(state)
            if status_box.has_status(it.target_id, "Petrified"):
                status_box.remove_status(it.target_id, "Petrified")
                self.combat.say(f"{tgt_name} 的石化狀態被解除了！")
            
            if t_res.is_dead():
                # 【修改】 呼叫 _on_enemy_defeated
                if it.target_id in state.combat.enemies:
                    self.combat._on_enemy_defeated(state, it.target_id)
                elif it.target_id == "$player": # 玩家死亡
                    self.combat._end(state, win=False)
                # (盟友死亡暫不處理結束)

        elif it.kind == "heal":
            _, t_res = self.combat._actor_view(state, it.target_id)
            before = t_res.hp(); t_res.hp_add(int(it.amount)); healed = t_res.hp() - before
            self.combat.say(f"{src_name} 治療了 {tgt_name} {healed} 點。")

        elif it.kind == "apply_status":
            spec = it.meta.get("status_spec") or {}
            sid = None
            mods = {}
            dur = 3 # 預設持續時間
            meta = {} # 狀態的元資料 (例如 'stacking')

            if isinstance(spec, str):
                # ----------------------------------------------------
                # 【新邏輯】 "寶可夢" 模式 (spec 是 "Staggered")
                # ----------------------------------------------------
                sid = spec 
                
                # 從 CombatEngine 上的總表查詢
                definition = self.combat.STATUS_EFFECT_DEFINITIONS.get(sid)
                
                if not definition:
                    self.combat.say(f"[WARN] 未知的狀態效果: {sid}")
                    return
                
                dur = definition.get("duration", 3)
                mods = dict(definition.get("mods", {})) # 複製一份，避免汙染總表
                meta = dict(definition.get("meta", {})) # 複製一份

                # 【特殊處理：中毒】
                if sid == "Poisoned":
                    # 傷害是動態計算的，取決於施法者
                    v_atk = self.combat._battle_view(state, it.source_id)
                    # 你的公式：每回合固定真實傷害（依中毒時的能力值加成）
                    # 範例公式：5 + 20% 施法者魔攻 (你可以修改)
                    poison_dmg = 5 + int(v_atk.matk * 0.2) 
                    mods["turn_damage"] = poison_dmg # 把計算好的傷害存入 mods

            elif isinstance(spec, dict):
                # ----------------------------------------------------
                # 【舊邏輯】 向下相容 (spec 是 {"id": "focus_up", ...})
                # ----------------------------------------------------
                sid = spec.get("id") or "status"
                dur = int(spec.get("duration", 3))
                mods = dict(spec.get("mods", {}))
                
                # 向下相容 "Bleeding" (流血) 的疊加
                if spec.get("stacking", False):
                    meta = {
                        "stacking": True,
                        "max_stacks": spec.get("max_stacks", 6),
                        "mods_per_stack": spec.get("mods_per_stack", {})
                    }
            
            if not sid:
                return # 無效的狀態

            # 呼叫更新後的 StatusBox.apply
            StatusBox(state).apply(it.target_id, sid, dur, mods, meta)
            
            self.combat.say(f"{src_name} 對 {tgt_name} 施加狀態：{sid}（{dur} 回合）。")
            recompute_derived(self.combat.world, state) # 重算

        elif it.kind == "cleanse":
            pass
        elif it.kind == "dispel":
            pass

# ===== Factory / Registrar（用你的 loader）=====
def make_skill(sid: str, row: Dict[str, Any]) -> SkillSpec:
    """你的 loader 把 JSON 讀成 dict 後，對每個 (sid,row) 呼叫這個工廠即可。"""
    row = dict(row); row.setdefault("name", sid); row.setdefault("tags", [])
    if "script" in row:
        return ScriptedSkill(id=sid, name=row["name"],
                             mp_cost=row.get("mp_cost",0), cooldown=row.get("cooldown",0),
                             tags=row.get("tags",[]), row=row)
    else:
        return GenericSkill(id=sid, name=row["name"],
                            kind=row.get("kind","damage"), power=row.get("power",0),
                            mp_cost=row.get("mp_cost",0), cooldown=row.get("cooldown",0),
                            tags=row.get("tags",[]), status_spec=row.get("status_spec"),
                            repeat=row.get("repeat", 1), target=row.get("target","enemy"),
                            effects=row.get("effects"))

def register_skills_from_mapping(world: Dict[str, Any], mapping: Dict[str, Dict[str, Any]]):
    world.setdefault("skills", {})
    for sid, row in (mapping or {}).items():
        world["skills"][sid] = make_skill(sid, row)
