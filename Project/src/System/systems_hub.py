from typing import List, Optional
import traceback

class BaseSystem:
    verbs: tuple[str, ...] = ()
    priority: int = 0  # 越大越先處理

    def attach(self, *, say, world):
        self.say, self.world, self.hub = say, world

    def can_fire(self, verb, state, *, item_id=None, target_id=None) -> bool:
        return False

    def fire(self, verb, state, *, item_id=None, target_id=None) -> bool:
        return False

class SystemsHub:
    def __init__(self):
        self.systems: List[BaseSystem] = []

    def register(self, sys: BaseSystem):
        self.systems.append(sys)
        self.systems.sort(key=lambda s: s.priority, reverse=True)  # 依優先序排序

    def attach_all(self, *, say, world, hub = None): 
        for s in self.systems:
            s.attach(say=say, world=world, hub=hub)


    def can_fire(self, verb, state, *, item_id=None, target_id=None) -> bool:
        for s in self.systems:
            # 可選：若該系統宣告 verbs，先做快速過濾
            if s.verbs and verb not in s.verbs: 
                continue
            if s.can_fire(verb, state, item_id=item_id, target_id=target_id):
                return True
        return False

    def fire(self, verb, state, *, item_id=None, target_id=None) -> bool:
        for s in self.systems:
            if s.verbs and verb not in s.verbs:
                continue
            if s.can_fire(verb, state, item_id=item_id, target_id=target_id):
                res = s.fire(verb, state, item_id=item_id, target_id=target_id)
                return res     # ★ 原樣回傳
        return False
