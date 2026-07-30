from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set


# === 基本能力與派生值 ===
@dataclass
class Attributes:
    STR: int = 5
    INT: int = 5
    CON: int = 20
    DEX: int = 5
    CHA: int = 5
    LCK: int = 5

@dataclass
class DerivedStats:
    max_hp: int = 0
    max_mp: int = 0
    atk: int = 0
    matk: int = 0
    def_: int = 0
    mdef: int = 0
    speed: int = 0
    crit: int = 0


# === 玩家狀態（資源 / 背包 / 裝備）===
@dataclass
class PlayerStats:
    lvl: int = 1
    exp: int = 0
    hp: int = 100
    mp: int = 10
    gold: int = 0

@dataclass
class InventoryState:
    items: List[str] = field(default_factory=lambda: ["key_bronze","coin","spear_basic","leather_armor"])
    equipment: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "weapon": None,
        "body": None,
        "offhand": None
    })

    def sync_equipment_slots(self, slot_definitions: Dict[str, Any] | None) -> None:
        """依資料索引補齊並排序裝備欄，同時保留存檔中的自訂欄位與既有裝備。"""
        definitions = slot_definitions or {}
        if not isinstance(definitions, dict) or not definitions:
            return
        current = dict(self.equipment or {})
        def slot_order(slot_id: str) -> tuple[int, str]:
            raw_order = (definitions.get(slot_id) or {}).get("order", 9999)
            try:
                order = int(raw_order)
            except (TypeError, ValueError):
                order = 9999
            return order, slot_id

        ordered_slots = sorted(definitions, key=slot_order)
        rebuilt: Dict[str, Optional[str]] = {
            slot_id: current.get(slot_id)
            for slot_id in ordered_slots
        }
        for slot_id, item_id in current.items():
            if slot_id not in rebuilt:
                rebuilt[slot_id] = item_id
        self.equipment = rebuilt

@dataclass
class NPCProfile:
    # 基礎數值（可從 world.npcs[...] 初始化一次，之後只改這裡）
    name: Optional[str] = None
    lvl: int = 1
    exp: int = 0

    hp: int = 10
    max_hp: int = 10
    mp: int = 0
    max_mp: int = 0

    atk: int = 5
    defense: int = 1
    matk: int = 0
    mdef: int = 0
    speed: int = 3
    crit: int = 0

    # 屬性六圍改成巢狀物件，跟玩家的 state.attr  同一種型別
    attr: Attributes = field(default_factory=Attributes)


    # 永久裝備（如你允許 NPC 也能換裝，就放在這裡）
    equipment: Dict[str, Optional[str]] = field(default_factory=dict)

    # 永久技能（和你先前的 state.known_skills 並存；下面第 3 步會改戰鬥優先讀這裡）
    skills: List[str] = field(default_factory=list)

    # 自身戰鬥標籤；種族 ID 會在初始化時一併加入。
    traits: List[str] = field(default_factory=list)

# === 隊伍系統 ===
@dataclass
class PartyState:
    members: List[str] = field(default_factory=list)   # 隊伍成員 npc_id，最多 3
    home: Dict[str, str] = field(default_factory=dict) # npc_id -> 原始招募點 room_id

# === 【新增】戰鬥者快照 ===
@dataclass
class CombatantProfile:
    """【新增】儲存戰鬥中每個單位的即時快照 (特別是敵人)"""
    id: str # 唯一的戰鬥 ID (例如 "slime_1")
    monster_id: str # 原始 ID (例如 "slime")
    name: str
    
    hp: int
    max_hp: int
    
    # 儲存從 monsters.json 來的基礎值
    base_stats: Dict[str, Any] = field(default_factory=dict)
    # 儲存裝備和特性
    traits: List[str] = field(default_factory=list)
    equipment: Dict[str, str] = field(default_factory=dict)

# === 【修改】戰鬥狀態 ===
@dataclass
class CombatState:
    active: bool = False
    
    # 改用字典存多個敵人：{ "slime_1": Profile(...), "wolf_1": Profile(...) }
    enemies: Dict[str, CombatantProfile] = field(default_factory=dict)

    # --- 佇列與狀態 ---
    turn_queue: list = field(default_factory=list)
    turn_index: int = 0
    active_id: str = "" # 仍儲存 "$player", "ally_id", "slime_1" 這樣的 ID
    ally_control: bool = True
    
    # --- 【修改】防禦狀態 (從 bool 改為 Dict) ---
    defending: Dict[str, bool] = field(default_factory=dict)


# === 任務系統 ===
@dataclass
class QuestState:
    active: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict) # 任務 ID -> 任務列表（每個任務是一個 Dict）
    completed: Set[str] = field(default_factory=set)
    


# === 情緒系統 ===
@dataclass
class EmotionState:
    emotions: Dict[str, Dict[str, int]] = field(default_factory=dict)   # NPC → 各情緒值
    labels: Dict[str, List[str]] = field(default_factory=dict)          # NPC → 快取標籤


# === 全域遊戲狀態 ===
@dataclass
class GameState:
    # 位置與探索
    room_id: str = "town_square"
    visited_rooms: Set[str] = field(default_factory=lambda: {"town_square"})

    # 能力
    attr: Attributes = field(default_factory=Attributes)
    derived: DerivedStats = field(default_factory=DerivedStats)

    # ★ 玩家技能（永久）
    player_skills: List[str] = field(default_factory=lambda: {"petrifying_gaze","strength","leg_shot","poison_dart"})

    # 玩家數值與物品
    stats: PlayerStats = field(default_factory=PlayerStats)
    inventory: InventoryState = field(default_factory=InventoryState)

    # ★ 每個 NPC 的永久成長檔（離隊也不清掉）
    npc_profiles: Dict[str, NPCProfile] = field(default_factory=dict)

    # 隊伍
    party: PartyState = field(default_factory=PartyState)

    # 戰鬥
    combat: CombatState = field(default_factory=CombatState)

    # 新增任務狀態 (在 party, combat, emotion 附近加入)
    quest: QuestState = field(default_factory=QuestState)

    # 情緒
    emotion: EmotionState = field(default_factory=EmotionState)

    # 其他旗標與事實
    facts: Dict[str, Any] = field(default_factory=lambda: {"world.alley.locked": True})
    tags: Set[str] = field(default_factory=lambda: {"fire"})
    flags: Set[str] = field(default_factory=set)
