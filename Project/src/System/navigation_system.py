from __future__ import annotations

from typing import Any, Dict

from Data.state import GameState
from System.action_request import ActionRequest


class NavigationSystem:
    """處理房間之間的移動，以及移動後的被動遭遇檢查。"""

    verbs = ("go",)
    priority = 50

    def __init__(self) -> None:
        self.say = print
        self.world: Dict[str, Any] = {}
        self.hub = None

    def attach(self, *, say, world, hub=None) -> None:
        self.say = say or (lambda *_: None)
        self.world = world or {}
        self.hub = hub

    def _destination(self, state: GameState, direction: str | None) -> str | None:
        if not direction:
            return None
        room = (self.world.get("rooms") or {}).get(state.room_id, {})
        return (room.get("exits") or {}).get(direction)

    def can_fire(self, request: ActionRequest, state: GameState) -> bool:
        if request.verb != "go" or state.combat.active:
            return False

        target_room_id = self._destination(state, request.direction)
        return bool(
            target_room_id
            and target_room_id in (self.world.get("rooms") or {})
        )

    def fire(self, request: ActionRequest, state: GameState):
        if not self.can_fire(request, state):
            return {"ok": False}

        source_room_id = state.room_id
        target_room_id = self._destination(state, request.direction)
        assert target_room_id is not None  # can_fire 已保證存在

        state.room_id = target_room_id
        state.visited_rooms.add(target_room_id)

        encounter_started = False
        engine = getattr(self.hub, "engine", None)
        combat = getattr(engine, "combat", None)
        check_encounter = getattr(combat, "check_encounter", None)
        if callable(check_encounter):
            encounter_started = bool(check_encounter(state))

        room = (self.world.get("rooms") or {}).get(target_room_id, {})
        room_name = room.get("name", target_room_id)

        return {
            "ok": True,
            "text": f"你前往「{room_name}」。",
            "from_room_id": source_room_id,
            "room_id": target_room_id,
            "direction": request.direction,
            "encounter_started": encounter_started,
        }
