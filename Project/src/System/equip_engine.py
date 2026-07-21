from typing import Any, Dict, Optional
from Data.derive import recompute_derived
from Data.state import GameState


class EquipEngine:
    verbs = ("equip", "unequip")
    priority = 20

    def __init__(self):
        self.say = print
        self.world: Dict[str, Any] = {}
        self.on_ui_refresh = None

    # 與 combat 同風格
    def attach(self, *, say, world, hub):
        self.say = say
        self.world = world
        self.hub = hub

    def set_ui_refresh(self, cb):  # 可選
        self.on_ui_refresh = cb

    def _notify_ui(self):
        if callable(self.on_ui_refresh):
            self.on_ui_refresh()

    # ---- 判斷 ----
    def can_fire(self, verb: str, state: GameState, *, item_id: Optional[str] = None, slot: Optional[str] = None, **_) -> bool:
        if verb == "equip":
            if not item_id: 
                return False
            it = self.world.get("items", {}).get(item_id)
            if not it: 
                return False
            if item_id not in state.inventory.items: 
                return False
            sl = it.get("slot")
            if not sl or sl not in state.inventory.equipment: 
                return False
            # 規則：戰鬥中不可換裝
            if state.combat.active: 
                return False
            return True

        if verb == "unequip":
            if not slot or slot not in state.inventory.equipment: 
                return {"ok": False}
            if not state.inventory.equipment.get(slot): 
                return {"ok": False}
            if state.combat.active: 
                return {"ok": False}
            return {"ok": True}

        return False  # 只管 equip/unequip

    # ---- 執行 ----
    def fire(self, verb: str, state: GameState, *, item_id: Optional[str] = None, slot: Optional[str] = None, **_):
        if verb == "equip":
            if not self.can_fire("equip", state, item_id=item_id): 
                self.say("現在無法裝備。"); return {"ok": False}
            it = self.world["items"][item_id]
            sl = it["slot"]
            prev = state.inventory.equipment.get(sl)
            state.inventory.equipment[sl] = item_id
            if prev and prev not in state.inventory.items:  # 舊裝備回背包
                state.inventory.items.append(prev)
            recompute_derived(self.world, state)
            self.say(f"已裝備：{it.get('name', item_id)}")
            self._notify_ui()
            return {"ok": True}

        if verb == "unequip":
            if not self.can_fire("unequip", state, slot=slot):
                self.say("現在無法卸下。"); return {"ok": False}
            cur = state.inventory.equipment.get(slot)
            if cur:
                state.inventory.equipment[slot] = None
                if cur not in state.inventory.items:
                    state.inventory.items.append(cur)
                recompute_derived(self.world, state)
                name = self.world["items"].get(cur, {}).get("name", cur)
                self.say(f"已卸下：{name}")
                self._notify_ui()
            return {"ok": True}
