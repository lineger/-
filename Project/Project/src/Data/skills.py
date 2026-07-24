from typing import Dict, Any, List

# === 讀取技能（唯一來源） ===
def list_actor_skills(state, actor_id: str) -> List[str]:
    if actor_id == "$player":
        return list(getattr(state, "player_skills", []) or [])
    prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
    return list(getattr(prof, "skills", []) or []) if prof else []

# === 學習 / 忘記 ===
def learn_skill(state, actor_id: str, skill_id: str) -> bool:
    skills = list_actor_skills(state, actor_id)
    if skill_id in skills:
        return False
    skills.append(skill_id)
    if actor_id == "$player":
        state.player_skills = skills
    else:
        prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
        if not prof:
            # 沒 profile 就先建一個最小殼
            from Data.state import NPCProfile
            state.npc_profiles[actor_id] = NPCProfile()
            prof = state.npc_profiles[actor_id]
        prof.skills = skills
    return True

def forget_skill(state, actor_id: str, skill_id: str) -> bool:
    skills = list_actor_skills(state, actor_id)
    if skill_id not in skills:
        return False
    skills = [s for s in skills if s != skill_id]
    if actor_id == "$player":
        state.player_skills = skills
    else:
        prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
        if prof:
            prof.skills = skills
    return True

# === 學習條件（可選） ===
def meets_requirements(world: Dict[str, Any], state, actor_id: str, skill_id: str) -> bool:
    sk = (world.get("skills") or {}).get(skill_id) or {}
    req = sk.get("requires") or {}

    # 等級
    need_lvl = int(req.get("lvl", 0))
    if need_lvl > 0:
        lvl = _actor_lvl(state, actor_id)
        if lvl < need_lvl:
            return False

    # 屬性
    need_attr = req.get("attr") or {}
    if need_attr:
        attr = _actor_attr(state, actor_id)
        for k, v in need_attr.items():
            if getattr(attr, k, 0) < int(v):
                return False
    return True

# ---- helpers ----
def _actor_lvl(state, actor_id):
    if actor_id == "$player":
        return int(getattr(getattr(state, "stats", None), "lvl", 1))
    prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
    return int(getattr(prof, "lvl", 1) if prof else 1)

def _actor_attr(state, actor_id):
    if actor_id == "$player":
        return getattr(state, "attr", None)
    prof = (getattr(state, "npc_profiles", {}) or {}).get(actor_id)
    # 你的設計是把 NPC 的六圍直接平展在 profile 上（STR/INT/...）
    # 若想拿物件，也可以在建立 profile 時放一個 Attributes 物件；此處直接回傳 state.attr-like 的接口即可。
    class _AttrView:
        pass
    av = _AttrView()
    for k in ("STR","INT","CON","DEX","CHA","LCK"):
        setattr(av, k, int(getattr(prof, k, 0)) if prof else 0)
    return av
