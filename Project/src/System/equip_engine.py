from typing import Any, Dict, Optional
from Data.derive import recompute_derived
from System.action_request import ActionRequest
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
    def can_fire(self, request: ActionRequest, state: GameState) -> bool:
        if request.verb == "equip":
            item_id = request.item_id
            if not item_id:
                return False
            item = self.world.get("items", {}).get(item_id)
            if not item:
                return False
            if item_id not in state.inventory.items:
                return False
            slot = item.get("slot")
            known_slots = self.world.get("equipment_slots", {}) or state.inventory.equipment
            if not slot or slot not in known_slots:
                return False
            return not state.combat.active

        if request.verb == "unequip":
            slot = request.slot
            if not slot or slot not in state.inventory.equipment:
                return False
            if not state.inventory.equipment.get(slot):
                return False
            return not state.combat.active

        return False

    # ---- 執行 ----
    def fire(self, request: ActionRequest, state: GameState):
        if request.verb == "equip":
            if not self.can_fire(request, state):
                self.say("現在無法裝備。")
                return {"ok": False}

            item_id = request.item_id
            item = self.world["items"][item_id]
            slot = item["slot"]
            state.inventory.equipment.setdefault(slot, None)
            previous = state.inventory.equipment.get(slot)
            state.inventory.equipment[slot] = item_id
            if previous and previous not in state.inventory.items:
                state.inventory.items.append(previous)
            recompute_derived(self.world, state)
            self.say(f"已裝備：{item.get('name', item_id)}")
            self._notify_ui()
            return {"ok": True}

        if request.verb == "unequip":
            if not self.can_fire(request, state):
                self.say("現在無法卸下。")
                return {"ok": False}

            slot = request.slot
            current = state.inventory.equipment.get(slot)
            if current:
                state.inventory.equipment[slot] = None
                if current not in state.inventory.items:
                    state.inventory.items.append(current)
                recompute_derived(self.world, state)
                name = self.world["items"].get(current, {}).get("name", current)
                self.say(f"已卸下：{name}")
                self._notify_ui()
            return {"ok": True}

        return {"ok": False}
