from __future__ import annotations
from typing import List, Dict, Any
from System.Skill.skills_core import Intent, SkillSpec, CombatLike

class GenericSkill(SkillSpec):
    """
    資料化技能（強化版）
    支援：
      - kind: "damage" | "heal" | "buff" | "debuff"
      - repeat: int（多段）
      - target: "enemy" | "self"
      - effects: [ {kind, amount?, tags?, status_spec?, scale?} ]
        * kind: "damage"|"heal"|"apply_status"
        * amount: 基礎量
        * tags: 覆寫/附加標籤（影響路徑/相剋）
        * status_spec: {id,duration,mods:{...}}
        * scale: {"by":"atk|matk|def_|mdef|speed|crit", "k":1.0}  # 量化加成
    """
    def __init__(self, *, id, name, kind, power=0, mp_cost=0, cooldown=0, tags=None,
                 status_spec=None, repeat=1, target="enemy", effects=None):
        self.id=id; self.name=name; self.cooldown=int(cooldown); self.mp_cost=int(mp_cost)
        self.tags=list(tags or []); self.kind=kind; self.power=int(power)
        self.status_spec=status_spec; self.repeat=int(repeat); self.target=target
        self.effects = list(effects or [])
        if self.kind=="magic" and "magic" not in self.tags:
            self.tags.append("magic")

    def _resolve_target(self, caster_id, targets, default_enemy):
        # 1. 優先看是否有指定目標 (UI/AI 傳入)
        if targets and targets[0]:
            return targets[0]

        # 2. 沒指定時，看 JSON 設定
        # ★ 關鍵在這裡 ★
        if self.target == "self" or self.target == "$player":
            return caster_id  # 回傳「施法者 ID」

        return default_enemy

    def _scaled_amount(self, combat, state, actor_id, base: int, scale: Dict[str, Any]|None):
        amt = int(base or 0)
        if scale:
            v = combat._battle_view(state, actor_id)
            stat = str(scale.get("by",""))
            k = float(scale.get("k", 1.0))
            val = int(getattr(v, stat, 0))
            amt += int(round(k * val))
        return amt

    def make_intents(self, combat: CombatLike, state, caster_id: str, targets: List[str]) -> List[Intent]:
        t = self._resolve_target(caster_id, targets, getattr(state.combat, "enemy_id", None))
        out: List[Intent] = []

        # --- 簡單模式 (無 effects 列表) ---
        if not self.effects:
            # 【修改】不再強制鎖定 caster_id，全部統一對 t 施放
            # 這樣你就可以對敵人補血，或對自己造成傷害
            if self.kind == "heal":
                out.append(Intent("heal", caster_id, t, amount=self.power))
            elif self.kind in ("buff","debuff") and self.status_spec:
                out.append(Intent("apply_status", caster_id, t, meta={"status_spec": self.status_spec}))
            else:
                # damage
                out.append(Intent("damage", caster_id, t, amount=self.power, tags=self.tags))
            return out * max(1, self.repeat)

        # --- 進階模式 (有 effects 列表) ---
        for e in self.effects:
            ek = e.get("kind", "damage")
            tags = list(e.get("tags") or self.tags)
            
            if ek == "damage":
                amt = self._scaled_amount(combat, state, caster_id, int(e.get("amount", self.power)), e.get("scale"))
                out.append(Intent("damage", caster_id, t, amount=int(amt), tags=tags))
            
            elif ek == "heal":
                amt = self._scaled_amount(combat, state, caster_id, int(e.get("amount", self.power)), e.get("scale"))
                # 【修改】這裡原本就是 t，保持不變 (正確)
                out.append(Intent("heal", caster_id, t, amount=int(amt)))
            
            elif ek == "apply_status":
                spec = e.get("status_spec") or self.status_spec or {}
                # 【修改】這裡原本就是 t，保持不變 (正確)
                out.append(Intent("apply_status", caster_id, t, meta={"status_spec": spec}))

        return out * max(1, self.repeat)
