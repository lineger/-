from __future__ import annotations
from typing import List, Dict, Any
from System.Skill.skills_core import Intent, SkillSpec

# === 腳本登錄 ===
_SCRIPT_REG: Dict[str, Callable] = {}

def skill_script(name: str):
    """@skill_script('key') 註冊一個腳本技能原型（函式）。"""
    def deco(fn: Callable):
        _SCRIPT_REG[name] = fn
        return fn
    return deco

def get_script(name: str) -> Optional[Callable]:
    return _SCRIPT_REG.get(name)

# === 腳本技能殼：把行為交給對應腳本函式 ===
class ScriptedSkill(SkillSpec):
    def __init__(self, *, id, name, mp_cost=0, cooldown=0, tags=None, row=None):
        self.id=id; self.name=name; self.cooldown=int(cooldown); self.mp_cost=int(mp_cost)
        self.tags=list(tags or []); self.row=row or {}
    def make_intents(self, combat: "CombatEngine", state, caster_id: str, targets: List[str]) -> List[Intent]:
        fn = get_script(self.row.get("script"))
        if not fn:
            combat.say(f"技能腳本 {self.row.get('script')} 不存在。"); return []
        return fn(combat, state, caster_id, targets, self, self.row)

# === 參數化原型腳本（幾乎覆蓋大多數「特殊」）===

@skill_script("multi_hit")
def multi_hit(combat, state, caster_id, targets, spec_obj, row):
    t = targets[0]; p = row.get("params") or {}; hits = int(p.get("hits", 1)); base = int(p.get("base", 0))
    return [Intent("damage", caster_id, t, amount=base, tags=spec_obj.tags) for _ in range(max(1,hits))]

@skill_script("execute_by_threshold")
def execute_by_threshold(combat, state, caster_id, targets, spec_obj, row):
    t = targets[0]; p = row.get("params") or {}
    thresh = float(p.get("hp_pct", 0.3)); mult_low = float(p.get("mult_low", 2.0))
    mult_high = float(p.get("mult_high", 1.0)); base = int(p.get("base", 10))
    _, tres = combat._actor_view(state, t)
    ratio = max(0.0, min(1.0, tres.hp() / max(1, tres.max_hp())))
    amp = mult_low if ratio <= thresh else mult_high
    return [Intent("damage", caster_id, t, amount=int(base * amp), tags=spec_obj.tags, meta={"amp": amp})]

@skill_script("amp_by_negative_stacks")
def amp_by_negative_stacks(combat, state, caster_id, targets, spec_obj, row):
    t = targets[0]; p = row.get("params") or {}
    per = float(p.get("per_stack", 0.15)); cap = float(p.get("max_bonus", 0.6)); base = int(p.get("base", 10))
    box = getattr(state.combat, "status", {}).get(t, {}) or {}
    stacks = sum(1 for st in box.values() if (st.get("mods") or {}).get("negative", False))
    amp = 1.0 + min(cap, per * stacks)
    return [Intent("damage", caster_id, t, amount=int(base * amp), tags=spec_obj.tags, meta={"amp": amp})]

@skill_script("lifesteal")
def lifesteal(combat, state, caster_id, targets, spec_obj, row):
    t = targets[0]; p = row.get("params") or {}; base = int(p.get("base", 8)); ratio = float(p.get("ratio", 0.3))
    dmg = Intent("damage", caster_id, t, amount=base, tags=spec_obj.tags, meta={"lifesteal": ratio})
    heal = Intent("heal", caster_id, caster_id, amount=int(base * ratio))
    return [dmg, heal]

@skill_script("chain")
def chain(combat, state, caster_id, targets, spec_obj, row):
    p = row.get("params") or {}; hops = int(p.get("hops", 3)); base = int(p.get("base", 10)); decay = float(p.get("decay", 0.8))
    t = targets[0]; tags = spec_obj.tags; out = []; cur = base
    for _ in range(max(1, hops)):
        out.append(Intent("damage", caster_id, t, amount=int(cur), tags=tags))
        cur = max(1, int(cur * decay))
    return out

@skill_script("taunt")
def taunt(combat, state, caster_id, targets, spec_obj, row):
    spec = {"id":"Taunted","duration":3,"mods":{"ai_forced_target": caster_id}}
    return [Intent("apply_status", caster_id, targets[0], meta={"status_spec": spec})]
