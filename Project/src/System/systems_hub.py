from __future__ import annotations

from typing import Any, List

from System.action_request import ActionRequest


class BaseSystem:
    verbs: tuple[str, ...] = ()
    priority: int = 0  # 越大越先處理

    def attach(self, *, say, world, hub=None):
        self.say = say
        self.world = world
        self.hub = hub

    def can_fire(self, request: ActionRequest, state) -> bool:
        return False

    def fire(self, request: ActionRequest, state) -> Any:
        return False


class SystemsHub:
    def __init__(self):
        self.systems: List[BaseSystem] = []

    def register(self, system: BaseSystem):
        self.systems.append(system)
        self.systems.sort(key=lambda s: s.priority, reverse=True)

    def attach_all(self, *, say, world, hub=None):
        actual_hub = hub or self
        for system in self.systems:
            system.attach(say=say, world=world, hub=actual_hub)

    @staticmethod
    def _ensure_request(request: ActionRequest) -> None:
        if not isinstance(request, ActionRequest):
            raise TypeError(
                "SystemsHub 只接受 ActionRequest；"
                "請由 Engine.fire()/can_fire() 建立請求"
            )

    @staticmethod
    def _ensure_can_fire_result(system: BaseSystem, result: Any) -> bool:
        if type(result) is not bool:
            raise TypeError(
                f"{type(system).__name__}.can_fire() 必須回傳 bool，"
                f"實際為 {type(result).__name__}"
            )
        return result

    def can_fire(self, request: ActionRequest, state) -> bool:
        self._ensure_request(request)

        for system in self.systems:
            if system.verbs and request.verb not in system.verbs:
                continue

            allowed = self._ensure_can_fire_result(
                system,
                system.can_fire(request, state),
            )
            if allowed:
                return True

        return False

    def fire(self, request: ActionRequest, state) -> Any:
        self._ensure_request(request)

        for system in self.systems:
            if system.verbs and request.verb not in system.verbs:
                continue

            allowed = self._ensure_can_fire_result(
                system,
                system.can_fire(request, state),
            )
            if allowed:
                return system.fire(request, state)

        return False
