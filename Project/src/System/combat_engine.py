import random
from typing import Any, Dict, Optional
from types import SimpleNamespace
from Data.state import GameState, CombatantProfile
from Data.derive import recompute_derived
from System.action_request import ActionRequest
from System.Skill.skill_runtime import SkillRuntime


# ───────────────────────────────────────────────────────────────────
# 抽出的小類：冷卻盒 / 狀態盒 / 傷害模型 / 回合流程 / 遭遇流程
# ───────────────────────────────────────────────────────────────────

class CooldownBox:
    """管理 per-actor 的技能冷卻（整數回合）。"""
    def __init__(self, state: GameState):
        self.state = state

    def _cds(self):
        cd = getattr(self.state.combat, "cooldowns", None)
        if cd is None:
            self.state.combat.cooldowns = {}
            cd = self.state.combat.cooldowns
        return cd

    def get(self, actor_id: str, skill_id: str) -> int:
        return int(self._cds().get(actor_id, {}).get(skill_id, 0))

    def set(self, actor_id: str, skill_id: str, v: int):
        self._cds().setdefault(actor_id, {})[skill_id] = max(0, int(v))

    def tick_all(self):
        for _, m in self._cds().items():
            for sid in list(m.keys()):
                m[sid] = max(0, int(m[sid]) - 1)


class StatusBox:
    """管理 per-actor 的暫時狀態（回合制持續與屬性修正匯總）。"""
    def __init__(self, state: GameState):
        self.state = state

    def _box(self):
        sb = getattr(self.state.combat, "status", None)
        if sb is None:
            self.state.combat.status = {}
            sb = self.state.combat.status
        return sb

    def has_status(self, actor_id: str, status_id: str) -> bool:
        """檢查指定 actor 是否擁有某個狀態"""
        return status_id in self._box().get(actor_id, {})

    def get_status(self, actor_id: str, status_id: str) -> Optional[Dict[str, Any]]:
        """獲取特定狀態的資料 (包含 duration 和 mods)"""
        return self._box().get(actor_id, {}).get(status_id)

    def remove_status(self, actor_id: str, status_id: str):
        """移除一個狀態"""
        m = self._box().get(actor_id, {})
        if status_id in m:
            del m[status_id]
            
    def get_all_mods(self, actor_id: str) -> Dict[str, Any]:
        """匯總一個 actor 身上的所有 mods"""
        total = {}
        for one in (self._box().get(actor_id, {}) or {}).values():
            for k, v in (one.get("mods") or {}).items():
                # 這裡使用相加，你也可以改成更複雜的疊加規則
                total[k] = int(total.get(k, 0)) + int(v)
        return total

    def apply(self, actor_id: str, status_id: str, duration: int, mods: dict, meta: dict = {}):
        """
        mods 例：{"atk": +3, "def_": -2}
        meta 例：{"stacking": True} (流血)
        
        【新邏輯】：
        - 預設行為 (Staggered, Poisoned, Focus...)：刷新持續時間，並用新的 mods 覆蓋舊的。
        - 疊加行為 (stacking: True)：刷新持續時間，並根據層數重新計算 mods。
        """
        box = self._box().setdefault(actor_id, {})

        is_stacking = meta.get("stacking", False)

        if is_stacking:
            # --- 1. 疊加邏輯 (例如 "Bleeding") ---
            cur = box.get(status_id, {"duration": 0, "mods": {}, "stacks": 0, "meta": {}})
            cur["meta"] = meta 
            
            stacks = cur.get("stacks", 0) + 1
            max_s = meta.get("max_stacks", 99)
            stacks = min(stacks, max_s)
            cur["stacks"] = stacks
            
            # 根據層數重新計算 mods
            mods_per_stack = meta.get("mods_per_stack", {})
            new_mods = {}
            for k, v in mods_per_stack.items():
                new_mods[k] = v * stacks
                
            cur["mods"] = new_mods # 覆蓋 mods
            cur["duration"] = max(int(cur.get("duration", 0)), int(duration)) # 刷新持續時間
            
            box[status_id] = cur
        else:
            # --- 2. 預設「刷新/覆蓋」邏輯 (例如 "Staggered", "Poisoned", "Strength") ---
            
            # 取得當前剩餘的持續時間
            cur_duration = box.get(status_id, {}).get("duration", 0)
            
            box[status_id] = {
                "duration": max(int(cur_duration), int(duration)), # 刷新持續時間 (取較長者)
                "mods": dict(mods),      # 【修正】直接使用新的 mods 覆蓋
                "stacks": 1,             # 層數重設為 1
                "meta": dict(meta)
            }

    def tick_all(self):
        box = self._box()
        for _, m in box.items():
            for sid in list(m.keys()):
                m[sid]["duration"] = int(m[sid].get("duration", 0)) - 1
                if m[sid]["duration"] <= 0:
                    del m[sid]


class DamageModel:
    """傷害結算（物攻路徑），支援 tag 相剋與暴擊；可注入 RNG 方便測試。"""
    def __init__(self, world: Dict[str, Any], *,
                 crit_multiplier: float = 2.0,
                 spread_min: int = -2,
                 spread_max: int = 2,
                 rng=None):
        self.world = world
        self.crit_multiplier = float(crit_multiplier)
        self.spread_min = int(spread_min)
        self.spread_max = int(spread_max)
        self.rng = rng or random

    def lookup_multiplier(self, atk_tags, def_tags) -> float:
        tags_table = self.world.get("tags") or {}
        atk_tags = set(atk_tags or [])
        def_tags = set(def_tags or [])

        mult = 1.0
        for attack_tag in atk_tags:
            tag_def = tags_table.get(attack_tag)
            if not tag_def:
                continue

            multipliers = tag_def.get("multipliers", {})
            for defense_tag in def_tags:
                mult *= float(multipliers.get(defense_tag, 1.0))
        return mult

    def apply_tag_multiplier(self, damage: int, atk_tags=None, def_tags=None) -> int:
        """將標籤相剋倍率套用到已算出的傷害，不改變原本的傷害公式。"""
        mult = self.lookup_multiplier(atk_tags, def_tags)
        return max(1, int(round(int(damage) * mult)))

    def calc_phys_damage(self, base_atk: int, base_def: int, crit_pct: int,
                         atk_tags=None, def_tags=None) -> tuple[int, bool]:
        base = max(1, int(base_atk) - int(base_def))
        spread = base + self.rng.randint(self.spread_min, self.spread_max)
        dmg = self.apply_tag_multiplier(spread, atk_tags, def_tags)
        is_crit = self.rng.randint(1, 100) <= max(0, int(crit_pct))
        if is_crit:
            dmg = int(dmg * self.crit_multiplier)
        return dmg, is_crit


class TurnFlow:
    """
    【修復版】統一回合推進
    """
    def __init__(self, engine):
        self.engine = engine

    def process_turn(self, state: GameState):
        # 安全閥：防止無窮迴圈
        loops = 0
        while self.engine.in_battle(state) and loops < 20:
            loops += 1
            
            active_id = getattr(state.combat, "active_id", None)
            if not active_id: 
                self.engine._next_turn(state)
                continue

            # --- A. 輪到玩家 ---
            if active_id == "$player":
                name = self.engine._name_of(state, active_id)
                self.engine.say(f"輪到 {name}。")
                
                # 1. 結算回合開始效果 (毒/血)
                self.engine._apply_turn_start_effects(state, active_id)
                if not self.engine.in_battle(state): break
                
                # 2. 檢查玩家是否被控場 (石化/暈眩)
                status_box = StatusBox(state)
                if status_box.has_status(active_id, "Petrified"):
                    self.engine.say(f"{name} 全身石化，無法動彈！")
                    self.engine._next_turn(state)
                    continue
                if status_box.has_status(active_id, "Stunned"):
                    self.engine.say(f"{name} 暈眩中，無法行動！")
                    self.engine._next_turn(state)
                    continue

                # 3. 一切正常，暫停迴圈，等待 UI 輸入
                return 

            # --- B. 輪到盟友 ---
            if active_id in (state.facts.get("_party_members") or []):
                self.engine.say(f"{self.engine._name_of(state, active_id)} (AI)...")
                self.engine._apply_turn_start_effects(state, active_id)
                if not self.engine.in_battle(state): break
                self.engine._next_turn(state)
                continue

            # --- C. 輪到敵人 ---
            if active_id in state.combat.enemies:
                self.engine.say(f"輪到 {self.engine._name_of(state, active_id)}！")
                self.engine._apply_turn_start_effects(state, active_id)
                
                # 如果死於 DoT，直接換下一位
                if active_id not in state.combat.enemies:
                    self.engine._next_turn(state)
                    continue
                    
                if not self.engine.in_battle(state): break

                try:
                    # 【關鍵】AI 執行動作，但不推進回合 (advance=False)
                    self.engine._enemy_ai_turn(state, active_id)
                except Exception as e:
                    print(f"[AI Error] {e}")
                    import traceback
                    traceback.print_exc()
                
                # 【關鍵】AI 執行完後，由這裡統一推進
                if self.engine.in_battle(state):
                    self.engine._next_turn(state)
                continue
            
            # --- D. Failsafe ---
            self.engine._next_turn(state)

    def advance_and_enemy_auto(self, state: GameState):
        """給玩家行動結束後呼叫的入口"""
        self.engine._next_turn(state)
        self.process_turn(state)


class Encounters:
    """遭遇相關：房內可戰 NPC、隨機遇敵、建立戰鬥快照、開戰。"""
    def __init__(self, engine: "CombatEngine"):
        self.engine = engine

    def combat_npcs_in_room(self, world: Dict[str, Any], state: GameState) -> list[str]:
        room = world["rooms"][state.room_id]
        out = []
        for nid in room.get("npcs", []):
            npc = world["npcs"].get(nid, {})
            if npc.get("combat"):
                out.append(nid)
        return out

    def roll_encounter_group(self, world: Dict[str, Any], state: GameState) -> list[str]:
        """【修改】直接硬編碼：每次遭遇 1~3 名敵人，不需要 min/max 參數"""
        room = world["rooms"][state.room_id]
        enc = room.get("encounters") or {}
        
        # Pool 模式
        pool = enc.get("pool")
        # ★ 硬編碼區：直接設定 1~3 ★
        count = random.randint(1, 3)
            
        ids = [p[0] for p in pool]
        wts = [p[1] for p in pool]
        if not ids: return []
        # 隨機抽出 count 個怪物
        return random.choices(ids, weights=wts, k=count)

    def check_room_encounter(self, state: GameState):
        """【新增】檢查房間是否觸發隨機遭遇"""
        if self.engine.in_battle(state): return False
        
        room = self.engine.world["rooms"][state.room_id]
        enc = room.get("encounters") or {}
        rate = float(enc.get("rate", 0.0))
        
        # 1. 擲骰
        if random.random() > rate:
            return False # 未觸發
            
        # 2. 決定怪物
        monster_group = self.roll_encounter_group(self.engine.world, state)
        if not monster_group:
            return False
            
        # 3. 觸發戰鬥
        self.engine.say("【！突發狀況！】")
        for mid in monster_group:
            self.engage(state, mid)
        self.start_combat(state)
        return True

    def _generate_unique_combat_id(self, state: GameState, monster_id: str) -> str:
        """產生唯一的戰鬥 ID，例如 "slime_1", "slime_2" """
        if monster_id not in state.combat.enemies:
            return monster_id
        i = 1
        while True:
            unique_id = f"{monster_id}_{i}"
            if unique_id not in state.combat.enemies:
                return unique_id
            i += 1
            
    def engage(self, state: GameState, enemy_id_to_add: str | None):
        """
        【修改】此函數現在負責「將一個敵人添加到戰鬥中」。
        它會建立 CombatantProfile 並放入 state.combat.enemies
        """
        eng = self.engine
        if not enemy_id_to_add:
            eng.say("這裡沒有可以戰鬥的對象。")
            return
            
        # 來源可能是 NPC 或 Monster
        npc = eng.world.get("npcs", {}).get(enemy_id_to_add, {})
        mon = eng.world.get("monsters", {}).get(enemy_id_to_add, {})
        src = npc if npc else mon
        
        if not src or not src.get("combat"):
            eng.say("這裡沒有可以戰鬥的對象。")
            return

        c = src["combat"]
        base_hp = int(c.get("hp", 10))
        
        # 產生唯一的戰鬥 ID
        combat_id = self._generate_unique_combat_id(state, enemy_id_to_add)
        name = src.get("name", enemy_id_to_add)
        if combat_id != enemy_id_to_add:
            # 如果是 "slime_1"，顯示為 "史萊姆 1"
            name = f"{name} {combat_id.split('_')[-1]}"

        # 建立戰鬥快照 (CombatantProfile)
        profile = CombatantProfile(
            id=combat_id,
            monster_id=enemy_id_to_add,
            name=name,
            hp=base_hp,
            max_hp=base_hp,
            traits=list(dict.fromkeys([
                *(src.get("traits") or src.get("tags") or []),
                *([src.get("species")] if src.get("species") else []),
            ])),
            equipment=dict(src.get("equipment") or {}),
            # 儲存基礎數值供 _battle_view 使用
            base_stats={
                "atk":   int(c.get("atk", 3)),
                "def_":  int(c.get("def", 1)),
                "matk":  int(c.get("matk", 0)),
                "mdef":  int(c.get("mdef", 0)),
                "speed": int(c.get("speed", 3)),
                "crit":  int(c.get("crit", 0)),
            }
        )

        # 將 Profile 存入新的 enemies 字典
        state.combat.enemies[combat_id] = profile
        
        # 第一次 engage 時，設定戰鬥為 active
        if not state.combat.active:
            state.combat.active = True

        eng.say(f"遭遇 {name}！")
        recompute_derived(eng.world, state)
        eng._notify_ui()

    def start_combat(self, state: GameState):
        """【修改】不再需要 enemy_id 參數，它從 state.combat.enemies 讀取"""
        eng = self.engine # eng 就是 CombatEngine 實例
        party = list(state.facts.get("_party_members", []))
        
        # 【修改】從 state.combat.enemies 獲取所有敵人的 ID
        enemy_ids = list(state.combat.enemies.keys())
        if not enemy_ids:
            eng.say("沒有敵人可以開始戰鬥。")
            return
        
        # 1. 建立初始佇列 (用於計算速度)
        state.combat.turn_queue = ["$player"] + party + enemy_ids
        
        # 2. 【修改】立刻呼叫 _rebuild_turn_queue 進行第一次排序
        new_queue = eng._rebuild_turn_queue(state)
        state.combat.turn_queue = new_queue
        
        # 3. 從排序後的第一位開始
        state.combat.turn_index = 0
        state.combat.active_id = state.combat.turn_queue[0]
        
        # 4. 初始化戰鬥狀態
        state.combat.defending = {aid: False for aid in new_queue}
        state.combat.cooldowns = {}
        state.combat.status = {}
        
        eng._notify_ui()

        # 6. 【重要】如果排序後第一位不是玩家，自動開始 AI 回合
        if state.combat.active_id != "$player":
            if hasattr(eng, "flow") and eng.flow:
             eng.flow.process_turn(state)
            else:
                 self.say("[ERROR] TurnFlow 未初始化")
                 

    def ambush(self, state: GameState):
        eng = self.engine
        if eng.in_battle(state):
            eng.say("你已在戰鬥中。")
            return
        
        # 1. 優先檢查房內是否有可戰鬥的 NPC
        npc_ids = self.combat_npcs_in_room(eng.world, state)
        if npc_ids:
            monster_group = [npc_ids[0]]
        else:
            # 2. 如果沒有 NPC，則隨機遭遇
            monster_group = self.roll_encounter_group(eng.world, state)
        
        if not monster_group:
            eng.say("這裡暫時沒有可突擊的對手。")
            return
            
        eng.say("你主動發起了突擊！")
        
        # ★★★ 關鍵修正：必須用迴圈將列表中的每隻怪物加入 ★★★
        for monster_id in monster_group:
            self.engage(state, monster_id)
            
        # 4. 所有敵人都加入後，才開始戰鬥
        if state.combat.active:
            self.start_combat(state)


class ActorRes:
    """統一封裝 玩家/NPC/敵人 的 HP/MP 存取與夾限邏輯。"""
    def __init__(self, *, kind: str, state, actor_id: str, derived):
        """
        kind: "player" | "ally" | "enemy"
        state: GameState
        derived: 衍生值來源（玩家: state.derived；NPC: profile；敵人: 臨時 base）
        """
        self.kind = kind
        self.state = state
        self.actor_id = actor_id
        self.derived = derived  # 需能取到 max_hp / max_mp

    # ---- 讀取目前值 ----
    def hp(self) -> int:
        if self.kind == "player":
            return int(self.state.stats.hp)
        if self.kind == "enemy":
            enemy_profile = self.state.combat.enemies.get(self.actor_id)
            return int(enemy_profile.hp) if enemy_profile else 0
        # ally
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        return int(getattr(prof, "hp", 0)) if prof else 0

    def mp(self) -> int:
        if self.kind == "player":
            return int(getattr(self.state.stats, "mp", 0))
        if self.kind == "enemy":
            return 0  # 預設敵人無 MP；若你要敵人有 MP 再擴充
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        return int(getattr(prof, "mp", 0)) if prof else 0

    # ---- 上限 ----
    def max_hp(self) -> int:
        if self.kind == "player":
            return int(getattr(self.state.derived, "max_hp", 0))
        # 【修改】從 enemies 字典中讀取
        if self.kind == "enemy":
            enemy_profile = self.state.combat.enemies.get(self.actor_id)
            return int(enemy_profile.max_hp) if enemy_profile else 0
        # ally
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        return int(getattr(prof, "max_hp", 0)) if prof else 0

    def max_mp(self) -> int:
        if self.kind == "player":
            return int(getattr(self.state.derived, "max_mp", 0))
        if self.kind == "enemy":
            return 0
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        return int(getattr(prof, "max_mp", 0)) if prof else 0

    # ---- 寫入（自動夾限）----
    def set_hp(self, v: int):
        v = max(0, min(int(v), self.max_hp()))
        if self.kind == "player":
            self.state.stats.hp = v; return
        # 【修改】寫入 enemies 字典
        if self.kind == "enemy":
            enemy_profile = self.state.combat.enemies.get(self.actor_id)
            if enemy_profile: enemy_profile.hp = v; return
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        if prof: setattr(prof, "hp", v)

    def set_mp(self, v: int):
        v = max(0, min(int(v), self.max_mp()))
        if self.kind == "player":
            self.state.stats.mp = v; return
        if self.kind == "enemy":
            return  # 預設忽略；要做敵人 MP 可在此寫 combat.enemy_mp
        prof = (getattr(self.state, "npc_profiles", {}) or {}).get(self.actor_id)
        if prof: setattr(prof, "mp", v)

    # ---- 便捷操作 ----
    def hp_add(self, dv: int) -> int:
        """回傳最終 HP 值。"""
        cur = self.hp()
        self.set_hp(cur + int(dv))
        return self.hp()

    def hp_sub(self, dv: int) -> int:
        return self.hp_add(-int(dv))

    def mp_add(self, dv: int) -> int:
        cur = self.mp()
        self.set_mp(cur + int(dv))
        return self.mp()

    def mp_sub(self, dv: int) -> int:
        return self.mp_add(-int(dv))

    # ---- 狀態判斷 ----
    def is_dead(self) -> bool:
        return self.hp() <= 0


# ───────────────────────────────────────────────────────────────────
# CombatEngine：外部介面完全相同；內部使用上面的小類
# ───────────────────────────────────────────────────────────────────

class CombatEngine:
    """
    插件式戰鬥引擎：統一使用 engage / ambush / combat_act。
    支援：玩家與 NPC 都能施法、防禦；防禦為獨立紀錄；技能可學習。
    """
    verbs = ("ambush", "engage", "combat_act")
    priority = 90

    def __init__(self):
        self.say = print
        self.world: Dict[str, Any] = {}
        self.on_ui_refresh = None
        # 子模組（attach 之後會注入 world）
        self.dmg: Optional[DamageModel] = None
        self.flow: Optional[TurnFlow] = None
        self.enc: Optional[Encounters] = None

        # 總表初始化
        self.STATUS_EFFECT_DEFINITIONS = {}

    # --- 注入 ---
    def attach(self, *, say, world, hub):
        self.say = say
        self.world = world
        self.hub = hub
        # 建立子模組（依附 world）
        self.dmg = DamageModel(self.world, rng=random)
        self.flow = TurnFlow(self)
        self.enc = Encounters(self)
        self.skills = SkillRuntime(self,cooldown_box=CooldownBox,
        status_box=StatusBox)

        self.STATUS_EFFECT_DEFINITIONS = self.world.get("status_effects", {})

    def set_ui_refresh(self, cb):
        self.on_ui_refresh = cb

    def _notify_ui(self):
        if callable(self.on_ui_refresh):
            self.on_ui_refresh()

    # --- 小工具 ---
    def _name_of(self, state, actor_id: str) -> str:
        if actor_id == "$player":
            return "你"
        # 【修改】 檢查 actor_id 是否在敵人字典中
        if actor_id in state.combat.enemies:
            return state.combat.enemies[actor_id].name
        # 盟友 / 其他 NPC
        return (self.world.get("npcs", {}).get(actor_id, {}) or {}).get("name", actor_id)

    # --- 狀態 ---
    def in_battle(self, state: GameState) -> bool:
        return bool(state.combat.active)

    # --- 【新增】輔助函數：獲取預設目標 ---
    def _get_default_target(self, state: GameState) -> Optional[str]:
        """獲取預設的敵方目標 (例如佇列中的第一個)"""
        if state.combat.enemies:
            # 返回第一個敵人的 combat_id
            return next(iter(state.combat.enemies))
        return None

    def check_encounter(self, state):
        """UI 呼叫此方法來檢查被動遭遇"""
        return self.enc.check_room_encounter(state)
    

    # --- Hub verbs ---
    def can_fire(self, request: ActionRequest, state: GameState) -> bool:
        if request.verb == "ambush":
            room = self.world["rooms"][state.room_id]
            return bool(self.enc.combat_npcs_in_room(self.world, state) or room.get("encounters"))
        if request.verb == "engage":
            if not request.target_id:
                return False
            npc = self.world["npcs"].get(request.target_id, {})
            return bool(npc.get("combat"))
        if request.verb == "combat_act":
            if not self.in_battle(state):
                return False
            actor = request.actor_id
            return bool(
                actor
                and actor == getattr(state.combat, "active_id", None)
                and (actor == "$player" or getattr(state.combat, "ally_control", True))
            )
        return False

    def fire(self, request: ActionRequest, state: GameState):
        if request.verb == "ambush":
            self.enc.ambush(state)
            return {"ok": True}
        if request.verb == "engage":
            self.enc.engage(state, request.target_id)
            if state.combat.active and not state.combat.turn_queue:
                self.enc.start_combat(state)
            return {"ok": True}
        if request.verb == "combat_act":
            return self._do_combat_act(
                state,
                actor_id=request.actor_id,
                action=request.action,
                item_id=request.item_id,
                target_id=request.target_id,
            )
        return None

    # --- 遭遇（保留公開 API，內部改呼叫 Encounters） ---
    def ambush(self, state: GameState):
        self.enc.ambush(state)

    def _engage(self, state: GameState, enemy_id: str | None):
        self.enc.engage(state, enemy_id)

    def start_combat(self, state: GameState, enemy_id: str):
        self.enc.start_combat(state, enemy_id)

    # --- 回合推進 ---
    def _next_turn(self, state: GameState):
        tq = getattr(state.combat, "turn_queue", [])
        if not (self.in_battle(state) and tq):
            return

        # 檢查是否輪到佇列的最後一人
        is_end_of_round = (state.combat.turn_index == len(tq) - 1)

        if is_end_of_round:
            
            # 1. 結算 Cooldowns 和 狀態持續時間
            CooldownBox(state).tick_all()
            StatusBox(state).tick_all()

            # 2. 根據當前速度重新排序下一回合
            new_queue = self._rebuild_turn_queue(state)
            
            # 檢查戰鬥是否應結束 (例如所有人都逃跑或死亡)
            if not new_queue:
                 if self.in_battle(state): self._end(state, win=False)
                 return
            if "$player" not in new_queue and not any(a in new_queue for a in (state.facts.get("_party_members") or [])):
                 if self.in_battle(state): self._end(state, win=False) # 玩家方全滅
                 return

            state.combat.turn_queue = new_queue
            state.combat.turn_index = 0
            state.combat.active_id = new_queue[0]
            
        else:
            # 還沒結束，推進到下一個人
            state.combat.turn_index += 1

        # 更新 active_id 為新指針的位置
        state.combat.active_id = state.combat.turn_queue[state.combat.turn_index]
        
        # 【重要】_next_turn 不再呼叫 _apply_turn_start_effects
        # 它只負責更新 UI 上的高亮
        self._notify_ui()


    def _rebuild_turn_queue(self, state: GameState) -> list[str]:
        """
        輔助函數：
        1. 抓取目前佇列中所有活著的單位。
        2. 獲取他們當前的最終速度 (包含狀態修正)。
        3. 回傳一個依速度排序 (高到低) 的新 ID 列表。
        """
        if not state.combat.turn_queue:
            return []
        
        # 1. 過濾掉死亡單位
        all_ids = []
        for actor_id in state.combat.turn_queue:
            _, res = self._actor_view(state, actor_id)
            if not res.is_dead():
                all_ids.append(actor_id)
        
        # 2. 獲取所有單位的當前速度
        speed_map = []
        for actor_id in all_ids:
            # _battle_view 會回傳包含「蹣跚」等狀態修正後的最終速度
            speed = self._battle_view(state, actor_id).speed
            speed_map.append( (actor_id, speed) )
            
        # 3. 排序 (高到低)。先隨機洗牌(shuffle)是為了讓同速時順序隨機。
        random.shuffle(speed_map)
        sorted_tuples = sorted(speed_map, key=lambda x: x[1], reverse=True)
        
        new_queue = [actor_id for actor_id, speed in sorted_tuples]
        return new_queue


    def _apply_turn_start_effects(self, state: GameState, actor_id: str):
        """
        【最精簡版】
        有多少個回合效果，就寫多少個 IF 檢查。
        所有邏輯都硬編碼 (Hard-coded)。
        """
        if not actor_id: 
            return
            
        status_box = StatusBox(state)
        if not status_box._box().get(actor_id):
            return

        name, res = self._actor_view(state, actor_id)
        if res.is_dead() or not self.in_battle(state):
            return

        # --- 1. 檢查中毒 ---
        poison_status = status_box.get_status(actor_id, "Poisoned")
        if poison_status:
            damage = poison_status.get("mods", {}).get("turn_damage", 0)
            if damage > 0:
                self.say(f"{name} 因為中毒受到了 {damage} 點真實傷害。")
                res.hp_sub(damage) 
                if res.is_dead():
                    # (處理死亡)
                    if actor_id == "$player" or actor_id in (state.facts.get("_party_members") or []):
                        self._end(state, win=False)
                    else:
                        # 【修改】 敵人中毒死亡
                        self._on_enemy_defeated(state, actor_id)
                    return # 死亡，停止後續效果

        # --- 2. 檢查流血 ---
        bleed_status = status_box.get_status(actor_id, "Bleeding")
        if bleed_status:
            # 硬編碼流血邏輯
            stacks = bleed_status.get("stacks", 1)
            pct_per_stack = 3 # (硬編碼：每層 3%)
            
            total_pct = pct_per_stack * stacks
            max_hp = res.max_hp()
            damage = int(max_hp * (total_pct / 100.0))
            damage = max(1, damage)
            
            self.say(f"{name} 因為流血受到了 {damage} 點傷害 ({stacks} 層)。")
            res.hp_sub(damage)
            if res.is_dead():
                # (處理死亡)
                if actor_id == "$player" or actor_id in (state.facts.get("_party_members") or []):
                    self._end(state, win=False)
                else:
                    # 【修改】 敵人流血死亡
                    self._on_enemy_defeated(state, actor_id)
                return # 死亡，停止後續效果

        # --- 3. 檢查腐蝕 ---
        corr_status = status_box.get_status(actor_id, "Corroded")
        if corr_status:
            # 硬編碼腐蝕邏輯
            mod_name = "def_pct"
            mod_val = -10
            mod_min = -100

            current_mod = corr_status.get("mods", {}).get(mod_name, 0)
            
            if current_mod > mod_min:
                new_mod = max(mod_min, current_mod + mod_val)
                corr_status["mods"][mod_name] = new_mod # 原地修改
                self.say(f"{name} 的防禦被腐蝕了 (目前: {new_mod}%)！")
                recompute_derived(self.world, state)
        

    def _actor_view(self, state, actor_id: str):
        """回傳 (display_name, res: ActorRes)；res 只管 HP/MP 存取與夾限。"""
        if actor_id == "$player":
            name = "你"
            res = ActorRes(kind="player", state=state, actor_id=actor_id, derived=state.derived)
            return name, res
        # 【修改】 檢查 actor_id 是否在敵人字典中
        if actor_id in state.combat.enemies:
            profile = state.combat.enemies[actor_id]
            name = profile.name
            # 敵人的上限從快照取
            temp = SimpleNamespace(max_hp=int(profile.max_hp), max_mp=0)
            res = ActorRes(kind="enemy", state=state, actor_id=actor_id, derived=temp)
            return name, res
        # 盟友
        prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
        if prof is None:
            raise RuntimeError(f"NPC profile missing for {actor_id}.")
        name = (self.world.get("npcs", {}) or {}).get(actor_id, {}).get("name", actor_id)
        res = ActorRes(kind="ally", state=state, actor_id=actor_id, derived=prof)
        return name, res

    def _battle_view(self, state, actor_id: str):
        """回傳臨時視圖（派生 + 狀態修正），不回寫 state。"""
        # 先準備基礎值
        if actor_id == "$player":
            base = {
                "atk": state.derived.atk,
                "def_": state.derived.def_,
                "matk": state.derived.matk,
                "mdef": state.derived.mdef,
                "speed": state.derived.speed,
                "crit": state.derived.crit,
            }
        # 【修改】 檢查 actor_id 是否在敵人字典中
        elif actor_id in state.combat.enemies:
            profile = state.combat.enemies[actor_id]
            eb = profile.base_stats or {} # 從 CombatantProfile 讀取
            base = {
                "atk":   int(eb.get("atk", 3)),
                "def_":  int(eb.get("def", 1)),
                "matk":  int(eb.get("matk", 0)),
                "mdef":  int(eb.get("mdef", 0)),
                "speed": int(eb.get("speed", 3)),
                "crit":  int(eb.get("crit", 0)),
            }
        else:
            prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
            if not prof:
                return SimpleNamespace(atk=1, def_=0, matk=0, mdef=0, speed=3, crit=0)
            base = {
                "atk": int(getattr(prof, "atk", 1)),
                "def_": int(getattr(prof, "defense", 0)),
                "matk": int(getattr(prof, "matk", 0)),
                "mdef": int(getattr(prof, "mdef", 0)),
                "speed": int(getattr(prof, "speed", 3)),
                "crit": int(getattr(prof, "crit", 0)),
            }

        # 匯總狀態修正
        total = {}
        for one in (getattr(state.combat, "status", {}).get(actor_id, {}) or {}).values():
            for k, v in (one.get("mods") or {}).items():
                total[k] = int(total.get(k, 0)) + int(v)

        for k, dv in total.items():
            if k in base:
                base[k] = int(base[k]) + int(dv)

        # 4. 【修改】動態套用「百分比」修正
        
        # 定義哪些屬性可以被百分比修改
        # (注意：max_hp 是由 ActorRes.max_hp() 獨立處理的，所以不在這裡)
        percent_modifiable_stats = ["atk", "matk", "def_", "mdef", "speed", "crit"]
        
        for stat_name in percent_modifiable_stats:
            # 動態產生 key, 例如 "atk_pct", "speed_pct"
            mod_key_pct = f"{stat_name}_pct" 
            
            if mod_key_pct in total:
                pct_mod = total.get(mod_key_pct, 0)
            else:
                continue # 沒有這個屬性的百分比修正，換下一個

            # 套用百分比計算
            current_val = base[stat_name]
            new_val = int(current_val * (1.0 + pct_mod / 100.0))
            
            
            # 確保下限
            if stat_name == "speed":
                new_val = max(1, new_val) # 速度至少 1
            elif stat_name in ["def_", "mdef", "atk", "matk"]:
                new_val = max(0, new_val) # 屬性至少 0
            
            base[stat_name] = new_val

        return SimpleNamespace(**base)


    def _get_actor_equipment(self, state: GameState, actor_id: str) -> dict:
        """取得戰鬥者目前裝備；不存在時回傳空字典。"""
        if actor_id == "$player":
            return dict(getattr(state.inventory, "equipment", {}) or {})

        if actor_id in state.combat.enemies:
            profile = state.combat.enemies.get(actor_id)
            return dict(getattr(profile, "equipment", {}) or {}) if profile else {}

        profile = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
        return dict(getattr(profile, "equipment", {}) or {}) if profile else {}

    def _get_actor_weapon_id(self, state: GameState, actor_id: str) -> Optional[str]:
        return self._get_actor_equipment(state, actor_id).get("weapon")

    def _get_equipment_tags(
        self,
        state: GameState,
        actor_id: str,
        *,
        slots=None,
    ) -> set[str]:
        tags: set[str] = set()
        items = self.world.get("items") or {}
        equipment = self._get_actor_equipment(state, actor_id)
        selected_slots = set(slots) if slots is not None else set(equipment)

        for slot, item_id in equipment.items():
            if slot not in selected_slots or not item_id:
                continue
            item_def = items.get(item_id) or {}
            tags.update(item_def.get("tags") or [])

        return tags

    def _get_intrinsic_tags(self, state: GameState, actor_id: str) -> set[str]:
        """取得角色自身的材質、護甲類型或種族等防禦標籤。"""
        if actor_id == "$player":
            return set(getattr(state, "tags", set()) or set())

        if actor_id in state.combat.enemies:
            profile = state.combat.enemies.get(actor_id)
            return set(getattr(profile, "traits", []) or []) if profile else set()

        profile = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
        profile_tags = getattr(profile, "traits", None) or getattr(profile, "tags", None)
        if profile_tags:
            return set(profile_tags)

        npc_def = (self.world.get("npcs") or {}).get(actor_id) or {}
        tags = set(npc_def.get("traits") or npc_def.get("tags") or [])
        if npc_def.get("species"):
            tags.add(npc_def["species"])
        return tags

    def _get_defense_tags(self, state: GameState, actor_id: str) -> set[str]:
        """防禦標籤＝角色自身標籤＋防具／副手裝備標籤。"""
        armor_tags = self._get_equipment_tags(
            state,
            actor_id,
            slots={"body", "offhand"},
        )
        return self._get_intrinsic_tags(state, actor_id) | armor_tags

    def _get_attack_tags(
        self,
        state: GameState,
        actor_id: str,
        action_tags=None,
        *,
        include_weapon: bool,
    ) -> set[str]:
        """
        取得本次攻擊標籤。

        普攻與物理技能可帶入武器標籤；魔法技能呼叫時應將
        include_weapon 設為 False，避免長槍讓火球獲得穿刺屬性。
        """
        tags = set(action_tags or [])
        if include_weapon:
            weapon_id = self._get_actor_weapon_id(state, actor_id)
            if weapon_id:
                weapon_def = (self.world.get("items") or {}).get(weapon_id) or {}
                tags.update(weapon_def.get("tags") or [])
        return tags

    def _handle_on_hit_procs(self, state: GameState, attacker_id: str, target_id: str):
        weapon_id = self._get_actor_weapon_id(state, attacker_id)
        if not weapon_id:
            return

        weapon_def = self.world.get("items", {}).get(weapon_id, {})
        proc_def = None # 觸發定義

        # 1. 優先檢查：武器是否自訂了 on_hit_proc (用於獨特武器)
        if "on_hit_proc" in weapon_def:
            proc_def = weapon_def.get("on_hit_proc")
        
        # 2. 如果沒有，才檢查：武器的 "tags" 是否符合「標籤總表」
        if not proc_def:
            weapon_tags = weapon_def.get("tags", [])
            tags_table = self.world.get("tags") or {}
            
            for tag in weapon_tags:
                tag_def = tags_table.get(tag)
                # 檢查 "pierce" 定義檔中是否有 "on_hit_proc" 欄位
                if tag_def and "on_hit_proc" in tag_def:
                    proc_def = tag_def.get("on_hit_proc")
                    break # 只取第一個命中的標籤規則

        # 3. 執行觸發 (如果 proc_def 有效)
        if not proc_def:
            return

        chance = int(proc_def.get("chance", 0))
        if random.randint(1, 100) <= chance:
            status_id = proc_def.get("status")
            if status_id:
                # 施加狀態...
                definition = self.STATUS_EFFECT_DEFINITIONS.get(status_id)
                if not definition: return
                dur = definition.get("duration", 3)
                mods = dict(definition.get("mods", {}))
                meta = dict(definition.get("meta", {}))
                StatusBox(state).apply(target_id, status_id, dur, mods, meta)
                
                atk_name = self._name_of(state, attacker_id)
                tgt_name = self._name_of(state, target_id)
                self.say(f"{atk_name} 的攻擊附加了 {status_id} 效果！")
                
                if status_id == "Bleeding":
                    recompute_derived(self.world, state)
    

    # === Hub: 行動 ===
    def _do_combat_act(self, state, *, actor_id: str, action: str, item_id: str | None = None, **kw): # MODIFIED:  changed **_ to **kw
        # 行動前重算一次（保守且簡單；如要最佳化可改事件點重算）
        recompute_derived(self.world, state)

        # 【新增】從 kwargs 獲取 target_id
        target_id = kw.get("target_id")

        # 【新增】在行動最一開始檢查石化
        if StatusBox(state).has_status(actor_id, "Petrified"):
            name, _ = self._actor_view(state, actor_id)
            self.say(f"{name} 處於石化狀態，無法行動！")
            self.flow.advance_and_enemy_auto(state) # 跳過回合
            return {"ok": True}

        if action == "attack":
            # 【修改】傳入 target_id
            return self._act_attack(state, actor_id, target_id, advance=True) 
        if action == "cast":
            if not item_id:
                self.say("沒有指定技能。"); return {"ok": False}
            # 【修改】傳入 target_id
            return self._act_cast(state, actor_id, item_id, target_id, advance=True)
        if action == "defend":
            return self._act_defend(state, actor_id, advance=True)
        if action == "flee":
            return self._act_flee(state, actor_id, advance=True)

        return {"ok": False}

    def _act_attack(self, state, actor_id: str, target_id: str | None, advance=True): # MODIFIED: Added target_id
        name, res_actor = self._actor_view(state, actor_id)
        v_atk = self._battle_view(state, actor_id)
        
        # 【修改】定義目標 ID
        if not target_id and actor_id == "$player":
            target_id = self._get_default_target(state)
            
        if not target_id:
            self.say("沒有可攻擊的目標！")
            return {"ok": False}

        v_def = self._battle_view(state, target_id)
        attack_tags = self._get_attack_tags(
            state, actor_id, include_weapon=True
        )
        defense_tags = self._get_defense_tags(state, target_id)
        dmg, is_crit = self.dmg.calc_phys_damage(
            v_atk.atk,
            v_def.def_,
            v_atk.crit,
            attack_tags,
            defense_tags,
        )

        # 【修正】消耗防禦狀態 (抵擋一次)
        if state.combat.defending.get(target_id, False):
            dmg = dmg // 2
            state.combat.defending[target_id] = False
        
        ename, res_enemy = self._actor_view(state, target_id) 
        res_enemy.hp_sub(dmg)
        # 【修改】確保顯示正確的目標名稱
        self.say(f"{name} 對 {ename} 造成 {dmg} 傷害" + ("（暴擊！）" if is_crit else ""))

        status_box = StatusBox(state)
        if status_box.has_status(target_id, "Petrified"):
            status_box.remove_status(target_id, "Petrified")
            self.say(f"{ename} 的石化狀態被解除了！")

        self._handle_on_hit_procs(state, actor_id, target_id)

        
        if res_enemy.is_dead():
            # 【修改】 呼叫新的敵人死亡處理函數
            self._on_enemy_defeated(state, target_id)
            # 敵人死亡，不需要再推進回合 (死亡函數會檢查勝利並結束)
            return {"ok": True}
        
        # 只有當 advance=True 時才推進 (玩家操作)
        if advance: self.flow.advance_and_enemy_auto(state)
        return {"ok": True}

    
    def _act_cast(self, state, actor_id: str, skill_id: str, target_id: str | None, advance=True): # MODIFIED: Added target_id
        sk = (self.world.get("skills") or {}).get(skill_id)
        if not sk:
            self.say("未知的技能。"); return {"ok": False}

        if hasattr(sk, "make_intents"):
            # 【修改】將 target_id 包裝成列表傳遞給 skills.cast
            # 如果 target_id 是 None，傳入空列表，SkillRuntime 會自動使用預設目標
            targets = [target_id] if target_id else []
            return self.skills.cast(state, actor_id, sk, targets, advance=advance)

        self.say("技能格式不支援。"); return {"ok": False}

    def _act_defend(self, state, actor_id: str, advance=True):
        # 【修改】 使用新的 defending 字典
        state.combat.defending[actor_id] = True

        name, *_ = self._actor_view(state, actor_id)
        self.say(f"{name} 架勢防禦。")

        if advance: self.flow.advance_and_enemy_auto(state)
        return {"ok": True}

    def _act_flee(self, state, actor_id: str, advance=True):
        # 【新增】檢查蹣跚
        # 我們需要 StatusBox，它也在這個檔案中
        if StatusBox(state).has_status(actor_id, "Staggered"):
            name, *_ = self._actor_view(state, actor_id)
            self.say(f"{name} 蹣跚著，無法逃跑！")
            
            # 逃跑失敗，消耗回合並輪到敵人
            if advance: self.flow.advance_and_enemy_auto(state)
            return {"ok": True}

        v_actor = self._battle_view(state, actor_id)
        
        # 【修改】 使用預設目標的敵人速度
        default_enemy_id = self._get_default_target(state)
        if default_enemy_id:
            v_enemy = self._battle_view(state, default_enemy_id)
            chance = 50 + (int(v_actor.speed) - int(v_enemy.speed)) * 10
        else:
            chance = 100 # 沒有敵人，必定成功
            
        chance = max(10, min(90, chance)) # 你的 clamp 邏輯

        if random.randint(1, 100) <= chance:
            self.say("你成功脫離戰鬥。")
            self._end(state, win=False)
        else:
            self.say("你試圖脫逃，但失敗了！")
            if advance: self.flow.advance_and_enemy_auto(state)
        return {"ok": True}

    # === 敵方回合（AI：智能 Buff 判斷 + 斬殺優先） ===
    def _enemy_ai_turn(self, state: GameState, enemy_id: str):
        # 1. 狀態檢查
        status_box = StatusBox(state)
        if status_box.has_status(enemy_id, "Petrified") or status_box.has_status(enemy_id, "Stunned"):
            self.say(f"{self._name_of(state, enemy_id)} 無法行動！")
            return
        
        recompute_derived(self.world, state)
        
        # 2. 準備資料
        me = state.combat.enemies.get(enemy_id)
        if not me: return
        
        pid = "$player"
        v_player = self._battle_view(state, pid)
        _, res_player = self._actor_view(state, pid)
        
        # 3. 獲取技能
        raw_monster = self.world.get("monsters", {}).get(me.monster_id) or \
                      self.world.get("monsters", {}).get("monsters", {}).get(me.monster_id) or {}
        skill_ids = raw_monster.get("skills", [])
        
        cd_box = CooldownBox(state)
        
        # 最佳行動候選
        best_action = {"skill_id": None, "target_id": pid, "score": 10}

        # 4. 技能評分
        for sid in skill_ids:
            if cd_box.get(enemy_id, sid) > 0: continue
            sk = self.world.get("skills", {}).get(sid)
            if not sk: continue
            
            kind = getattr(sk, "kind", "damage")
            tags = set(getattr(sk, "tags", []))
            
            # A. 攻擊類
            if kind in ("damage", "magic", "debuff", "control"):
                power = int(getattr(sk, "power", 0))
                v_me = self._battle_view(state, enemy_id)
                base_dmg = (v_me.matk if "magic" in tags else v_me.atk) + power
                
                attack_tags = self._get_attack_tags(
                    state,
                    enemy_id,
                    tags,
                    include_weapon="magic" not in tags,
                )
                player_tags = self._get_defense_tags(state, pid)
                mult = self.dmg.lookup_multiplier(attack_tags, player_tags)
                final_dmg = base_dmg * mult
                
                score = final_dmg
                if final_dmg >= res_player.hp(): score += 10000 # 斬殺
                
                if score > best_action["score"]:
                    best_action = {"skill_id": sid, "target_id": pid, "score": score}

            # B. 治療類
            elif kind == "heal":
                for ally_id, prof in state.combat.enemies.items():
                    hp_pct = prof.hp / max(1, prof.max_hp)
                    if hp_pct >= 1.0: continue
                    
                    score = (1.0 - hp_pct) * 200
                    if score > best_action["score"]:
                        best_action = {"skill_id": sid, "target_id": ally_id, "score": score}

            # C. 增益類 (Buff) - 【核心修正】
            elif kind in ("buff", "stance"):
                # 預先查出這個 Buff 到底加什麼屬性
                effects = getattr(sk, "effects", [])
                buff_type = "general" # 預設通用
                
                # 檢查 status_apply (簡單版) 或 effects (進階版)
                status_spec = getattr(sk, "status_spec", None) # 檢查 status_apply
                
                # 如果是 effects 列表形式，找第一個 apply_status
                if not status_spec and effects:
                    for eff in effects:
                        if eff.get("kind") == "apply_status":
                            status_spec = eff.get("status_spec")
                            break
                            
                # 深入檢查 Status Effect 的 mods
                if status_spec:
                    sid_ref = status_spec if isinstance(status_spec, str) else status_spec.get("id")
                    s_def = self.STATUS_EFFECT_DEFINITIONS.get(sid_ref, {})
                    mods = s_def.get("mods", {})
                    
                    if "atk" in mods or "atk_pct" in mods: buff_type = "physical"
                    elif "matk" in mods or "matk_pct" in mods: buff_type = "magic"
                
                # 掃描隊友，尋找最適合的人選
                for ally_id, prof in state.combat.enemies.items():
                    # 防止重複
                    if status_spec: 
                        sid_ref = status_spec if isinstance(status_spec, str) else status_spec.get("id")
                        if status_box.has_status(ally_id, sid_ref): continue

                    v_ally = self._battle_view(state, ally_id)
                    score = 0
                    
                    # 只有屬性對了才加分
                    if buff_type == "physical":
                        if v_ally.atk >= v_ally.matk: # 給物理角
                            score = 50 + v_ally.atk
                    elif buff_type == "magic":
                        if v_ally.matk > v_ally.atk: # 給魔法角
                            score = 50 + v_ally.matk
                    else:
                        score = 30 # 通用 Buff
                    
                    if score > best_action["score"]:
                        best_action = {"skill_id": sid, "target_id": ally_id, "score": score}

        # 5. 執行
        if best_action["skill_id"]:
            self._act_cast(state, enemy_id, best_action["skill_id"], best_action["target_id"], advance=False)
        else:
            # 普攻 fallback
            v_me = self._battle_view(state, enemy_id)
            v_target = self._battle_view(state, pid)
            attack_tags = self._get_attack_tags(
                state, enemy_id, include_weapon=True
            )
            defense_tags = self._get_defense_tags(state, pid)
            dmg, _ = self.dmg.calc_phys_damage(
                v_me.atk,
                v_target.def_,
                0,
                attack_tags,
                defense_tags,
            )
            if state.combat.defending.get(pid): dmg //= 2; state.combat.defending[pid] = False
            
            _, res_p = self._actor_view(state, pid)
            res_p.hp_sub(dmg)
            self.say(f"{self._name_of(state, enemy_id)} 對你造成 {dmg} 傷害。")
            
            if status_box.has_status(pid, "Petrified"):
                status_box.remove_status(pid, "Petrified"); self.say("你的石化解除！")
            self._handle_on_hit_procs(state, enemy_id, pid)
            if res_p.is_dead(): self._end(state, win=False)

    # ---- 戰鬥結束 ----
    def _on_enemy_defeated(self, state: GameState, defeated_id: str):
        """【新增】處理單一敵人被擊敗的邏輯"""
        
        # 1. 從 state.combat.enemies 中獲取 Profile
        profile = state.combat.enemies.get(defeated_id)
        if not profile:
            return # 已經被處理過了

        # 2. 獲取原始定義 (從 monsters 或 npcs)
        src = self.world.get("npcs", {}).get(profile.monster_id) or \
              self.world.get("monsters", {}).get(profile.monster_id) or {}
        
        # 3. 結算 EXP 和 Gold
        exp = int(src.get("exp", 0))
        state.stats.exp += exp
        gold = int((src.get("loot", {}) or {}).get("gold", 0))
        state.stats.gold += gold
        
        self.say(f"你擊敗了 {profile.name}！" + (f"獲得 EXP {exp}" if exp else "") + (f"、金幣 {gold}" if gold else ""))

        # 4. 從戰鬥中移除
        state.combat.enemies.pop(defeated_id, None)
        if defeated_id in state.combat.turn_queue:
            state.combat.turn_queue.remove(defeated_id)
            
        # 5. 通知 UI 刷新
        self._notify_ui()
        
        # 6. 檢查是否所有敵人都死了
        if not state.combat.enemies:
            self._win(state) # 呼叫勝利
            
    def _win(self, state: GameState):
        """【修改】簡化 _win，只負責宣告勝利並結束"""
        self.say(f"你獲得了勝利！")
        self._end(state, win=True)
        self._notify_ui()

    def _end(self, state: GameState, *, win: bool):
        state.combat.active = False
        # 【修改】 清空 enemies 字典
        state.combat.enemies = {}
        state.combat.turn_queue = []
        state.combat.active_id = None
        state.combat.defending = {}

        # 【建議新增的程式碼】
        # 清空所有戰鬥中狀態
        if hasattr(state.combat, "status"):
            state.combat.status = {}
        # 清空所有技能冷卻
        if hasattr(state.combat, "cooldowns"):
            state.combat.cooldowns = {}
        
        self._notify_ui()
