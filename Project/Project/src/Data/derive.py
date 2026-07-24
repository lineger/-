from dataclasses import is_dataclass
from typing import Dict

from Data.state import GameState, Attributes

# --------- 裝備映射工具（玩家 / NPC 共用觀念） ---------
def _equip_map_player(state) -> Dict[str, str]:
    """玩家裝備映射：優先新版 state.inventory.equipment，回退舊 state.equipment"""
    eq = getattr(getattr(state, "inventory", None), "equipment", None)
    if isinstance(eq, dict):
        return eq
    eq_legacy = getattr(state, "equipment", None)
    return eq_legacy if isinstance(eq_legacy, dict) else {}

def _equip_map_npc(profile) -> Dict[str, str]:
    """NPC 裝備映射：profile.equipment（若有），否則空表"""
    eq = getattr(profile, "equipment", None)
    return eq if isinstance(eq, dict) else {}

# --------- 共同：由屬性算「基礎衍生」 ---------
def _base_from_attr(a: Attributes):
    # 和你玩家的一樣（完全沿用公式）
    d = {
        "max_hp": 20 + a.CON * 5 + a.STR * 1,
        "atk":    1  + a.STR * 2 + a.DEX * 1,
        "matk":   1  + a.INT * 2,
        "def_":   0  + a.CON * 1 + a.DEX * 1,
        "mdef":   0  + a.INT * 1 + a.CHA * 1,
        "speed":  5  + a.DEX * 2,
        "crit":   5  + a.LCK * 1,   # %
    }
    return d

def _sum_bonuses(items: Dict, equip_map: Dict[str, str]):
    bonus = {"max_hp":0,"atk":0,"matk":0,"def_":0,"mdef":0,"speed":0,"crit":0}
    for _, item_id in (equip_map or {}).items():
        if not item_id: 
            continue
        it = (items or {}).get(item_id)
        if not it:
            continue
        for k, v in (it.get("bonuses") or {}).items():
            if k in bonus:
                try:
                    bonus[k] += int(v)
                except Exception:
                    pass
    return bonus

# --------- 玩家：沿用你原本行為，但封裝成步驟 ---------
def _recompute_player(world, state: GameState):
    a: Attributes = state.attr
    d = state.derived  # 你現有的 DerivedStats 物件

    # 1) 基礎
    base = _base_from_attr(a)

    # 2) 裝備加成
    items = (world.get("items") or {}) if isinstance(world, dict) else {}
    bonus = _sum_bonuses(items, _equip_map_player(state))

    # 3) 寫回
    d.max_hp = base["max_hp"] + bonus["max_hp"]
    d.atk    = base["atk"]    + bonus["atk"]
    d.matk   = base["matk"]   + bonus["matk"]
    d.def_   = base["def_"]   + bonus["def_"]
    d.mdef   = base["mdef"]   + bonus["mdef"]
    d.speed  = base["speed"]  + bonus["speed"]
    d.crit   = base["crit"]   + bonus["crit"]

    # 4) 夾上限（玩家 HP 不超過上限）
    try:
        hp_now = int(getattr(state.stats, "hp", d.max_hp))
    except Exception:
        hp_now = d.max_hp
    state.stats.hp = min(hp_now, d.max_hp)

# --------- NPC：用「同一套通道」重算 ---------
def _recompute_npc(world, profile):
    """
    profile 來自 state.npc_profiles[nid]（內含 attr / hp / mp / equipment 等）
    直接改寫 profile 上的派生欄位：max_hp/atk/matk/def_/mdef/speed/crit
    並把 hp/mp 夾到（max_hp/max_mp）上限。
    """
    # 容錯：沒有 attr 就不處理
    a = getattr(profile, "attr", None)
    if a is None:
        return

    base = _base_from_attr(a)

    items = (world.get("items") or {}) if isinstance(world, dict) else {}
    bonus = _sum_bonuses(items, _equip_map_npc(profile))

    # 寫回（NPC 的衍生直接存在 profile 內）
    profile.max_hp = int(base["max_hp"] + bonus["max_hp"])
    profile.atk    = int(base["atk"]    + bonus["atk"])
    profile.matk   = int(base["matk"]   + bonus["matk"])
    profile.defense= int(base["def_"]   + bonus["def_"])  # 你的 NPC 用 defense 命名
    profile.mdef   = int(base["mdef"]   + bonus["mdef"])
    profile.speed  = int(base["speed"]  + bonus["speed"])
    profile.crit   = int(base["crit"]   + bonus["crit"])

    # HP/MP 對齊上限（MP 若 profile 有 max_mp 就夾，否則略過）
    try:
        profile.hp = max(0, min(int(getattr(profile, "hp", profile.max_hp)), profile.max_hp))
    except Exception:
        profile.hp = profile.max_hp

    if hasattr(profile, "max_mp"):
        try:
            profile.mp = max(0, min(int(getattr(profile, "mp", 0)), int(profile.max_mp)))
        except Exception:
            profile.mp = int(getattr(profile, "max_mp", 0))

# --------- 對外單一入口：玩家 + 全部 NPC ---------
def recompute_derived(world, state: GameState):
    """
    ★ 你之後只要繼續呼叫這一個函式即可（UI 也不用改）。
    它會：
      1) 重算玩家派生（沿用你的公式）
      2) 重算所有 npc_profiles 的派生（完全同一套通道/公式）
    """
    # 玩家
    _recompute_player(world, state)

    members = list(state.facts.get("_party_members") or [])
    profiles = getattr(state, "npc_profiles", {}) or {}
    for nid in members:
        prof = profiles.get(nid)
        if prof:
            _recompute_npc(world, prof)
