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
