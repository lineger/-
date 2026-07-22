from dataclasses import dataclass, field
from typing import List, Dict, Any

# ===== 核心型別 =====
@dataclass
class Intent:
    kind: str                 # "damage"|"heal"|"apply_status"|"cleanse"|"dispel"
    source_id: str
    target_id: str
    amount: int = 0
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

# ===== CombatLike：技能系統需要的 combat 介面 =====
# 任何物件只要具備下面這些方法（簽名對得上），
# 就自動符合 CombatLike，不需要繼承、不需要 import CombatEngine。
class CombatLike(Protocol):
    dmg: Any  # DamageModel 實例，之後可以再拆一個更細的 Protocol

    def _battle_view(self, state, actor_id: str) -> Any: ...
    def _actor_view(self, state, actor_id: str) -> Tuple[str, Any]: ...
    def say(self, msg: str) -> None: ...
    def in_battle(self, state) -> bool: ...
    def _name_of(self, state, actor_id: str) -> str: ...
    def calc_effective_mp_cost(self, state, caster_id: str, spec: dict) -> int: ...
    def _get_default_target(self, state) -> Any: ...

class SkillSpec:
    id: str = ""
    name: str = ""
    desc: str = ""
    cooldown: int = 0
    mp_cost: int = 0
    tags: List[str] = []
    def can_cast(self, combat: "CombatEngine", state, caster_id: str) -> bool: return True
    def make_intents(self, combat: "CombatEngine", state, caster_id: str, targets: List[str]) -> List[Intent]:
        raise NotImplementedError
