# Project/src/System/quest_system.py

from typing import List, Dict, Any, Set
from System.action_request import ActionRequest
from System.systems_hub import BaseSystem
from Data.state import GameState # 假設 GameState 已經有 quest 屬性

class QuestSystem(BaseSystem):
    """
    任務系統：管理任務狀態、進度更新、完成與獎勵發放。
    
    Hub Verb:
    - quest_log: 檢視任務日誌
    - quest_accept: 接受任務（通常由 TalkSystem/Events 呼叫）
    - deliver: 將任務物品交給符合 NPC id 或 social role 的收件者
    - quest_check: 檢查其他行動造成的進度與完成（由 Engine 呼叫）
    """
    # 高優先級，確保在其他系統處理動作後，任務能及時檢查進度。
    verbs: tuple[str, ...] = ("quest_log", "quest_accept", "deliver")
    priority: int = 80 
    
    def __init__(self, **_):
        self.say = print
        self.world: Dict[str, Any] = {}
        self.hub = None

    def attach(self, *, say, world, hub):
        self.say = say
        self.world = world
        self.hub = hub
        # 假設 loader 會將任務資料載入到 world["quests"]     
        self.quests = self.world.get("quests")

    # --- 內部輔助函數 ---
    def _apply_rewards(self, state: GameState, rewards: List[Dict[str, Any]]):
        """套用獎勵（使用類似 SimpleSystem 的直接修改邏輯）"""
        for reward in rewards:
            if reward.get("type") == "gold":
                amount = int(reward.get("amount", 0))
                state.stats.gold = max(0, state.stats.gold + amount)
                self.say(f"你獲得了 {amount} 金幣。")
            elif reward.get("type") == "item":
                item_id = reward.get("item_id")
                if item_id:
                    state.inventory.items.append(item_id)
                    item_name = self.world.get("items", {}).get(item_id, {}).get("name", item_id)
                    self.say(f"你獲得了物品：{item_name}。")
            elif reward.get("type") == "exp":
                amount = int(reward.get("amount", 0))
                state.stats.exp += amount
                self.say(f"你獲得了 {amount} 經驗值。")
            elif reward.get("type") == "set_fact":
                key = reward.get("key")
                value = reward.get("value", True)
                if key:
                    state.facts[key] = value
                    self.say(f"世界狀態 [ {key} ] 已更新。")


    def _check_completion(self, state: GameState, quest_id: str):
        """檢查任務是否已完成所有任務並發放獎勵"""
        qdef = self.quests.get(quest_id)
        if not qdef: return
        
        # 任務列表 (tasks 是 List[Dict]，每個 dict 包含 progress, count)
        tasks = state.quest.active.get(quest_id)
        if tasks is None: return

        if all(t.get("progress", 0) >= t.get("count", 1) for t in tasks):
            # 任務完成
            state.quest.active.pop(quest_id, None)
            state.quest.completed.add(quest_id)
            
            self.say(f"★ 任務完成：{qdef.get('name', quest_id)}")
            self._apply_rewards(state, qdef.get("rewards", []))
            
            # 通知 UI 刷新
            if self.hub and hasattr(self.hub, "engine") and hasattr(self.hub.engine, "_notify_ui"):
                 self.hub.engine._notify_ui()


    # --- Hub 介面實作：供外部系統呼叫 ---
    
    def _missing_requirements(self, state: GameState, quest_id: str | None) -> list[str]:
        if not quest_id or quest_id not in self.quests:
            return []
        required = self.quests[quest_id].get("requires", []) or []
        return [required_id for required_id in required if required_id not in state.quest.completed]

    def _can_accept(self, state: GameState, quest_id: str | None) -> bool:
        return bool(
            quest_id
            and quest_id in self.quests
            and quest_id not in state.quest.active
            and quest_id not in state.quest.completed
            and not self._missing_requirements(state, quest_id)
        )

    def _recipient_matches(
        self,
        state: GameState,
        task: Dict[str, Any],
        npc_id: str | None,
    ) -> bool:
        if not npc_id:
            return False

        npc = (self.world.get("npcs") or {}).get(npc_id)
        if not npc:
            return False

        room = (self.world.get("rooms") or {}).get(state.room_id, {})
        if npc_id not in (room.get("npcs") or []):
            return False

        target_npc = task.get("target_npc")
        if target_npc is not None:
            return npc_id == target_npc

        target_role = task.get("target_role")
        if target_role is not None:
            return target_role in set(npc.get("roles") or [])

        return True

    def _find_delivery_task(
        self,
        state: GameState,
        quest_id: str | None,
        item_id: str | None,
        npc_id: str | None,
    ) -> tuple[int, Dict[str, Any]] | None:
        if not quest_id or not item_id or not npc_id:
            return None
        if item_id not in getattr(state.inventory, "items", []):
            return None

        tasks = state.quest.active.get(quest_id)
        if not tasks:
            return None

        for index, task in enumerate(tasks):
            if task.get("type") != "deliver_item":
                continue
            if task.get("target") != item_id:
                continue
            if int(task.get("progress", 0)) >= int(task.get("count", 1)):
                continue
            if not self._recipient_matches(state, task, npc_id):
                continue
            return index, task
        return None

    def _can_deliver(
        self,
        state: GameState,
        quest_id: str | None,
        item_id: str | None,
        npc_id: str | None,
    ) -> bool:
        return self._find_delivery_task(state, quest_id, item_id, npc_id) is not None

    def list_deliveries(self, state: GameState, npc_id: str) -> List[Dict[str, Any]]:
        """列出玩家目前能交給指定 NPC 的任務物品；供 UI 顯示，不修改狀態。"""
        out: List[Dict[str, Any]] = []
        inventory = getattr(state.inventory, "items", [])
        if not inventory:
            return out

        for quest_id, tasks in state.quest.active.items():
            qdef = self.quests.get(quest_id, {})
            for task in tasks:
                item_id = task.get("target")
                if (
                    task.get("type") != "deliver_item"
                    or not item_id
                    or item_id not in inventory
                    or int(task.get("progress", 0)) >= int(task.get("count", 1))
                    or not self._recipient_matches(state, task, npc_id)
                ):
                    continue

                item = (self.world.get("items") or {}).get(item_id, {})
                out.append({
                    "quest_id": quest_id,
                    "quest_name": qdef.get("name", quest_id),
                    "item_id": item_id,
                    "item_name": item.get("name", item_id),
                    "remaining": max(
                        0,
                        int(task.get("count", 1)) - int(task.get("progress", 0)),
                    ),
                })
        return out

    def can_fire(self, request: ActionRequest, state) -> bool:
        if request.verb == "quest_log":
            return True
        if request.verb == "quest_accept":
            return self._can_accept(state, request.quest_id)
        if request.verb == "deliver":
            return self._can_deliver(
                state,
                request.quest_id,
                request.item_id,
                request.target_id,
            )
        return False

    def fire(self, request: ActionRequest, state):
        if request.verb == "quest_log":
            return self._fire_log(state)
        if request.verb == "quest_accept":
            return self._fire_accept(state, request.quest_id)
        if request.verb == "deliver":
            return self._fire_deliver(
                state,
                request.quest_id,
                request.item_id,
                request.target_id,
            )
        return {"ok": False}
        
    def _fire_log(self, state: GameState):
        qs = state.quest
        log = ["--- 任務日誌 (quest log) ---"]

        
        # 活躍任務
        if qs.active:
            log.append("▶ 活躍中:")
            for qid, tasks in qs.active.items():
                qdef = self.quests.get(qid, {"name": qid, "desc": "（未知任務）"})
                log.append(f"  [{qdef['name']}] - {qdef.get('desc', '（無描述）')}")
                for t in tasks:
                    progress_text = ""
                    current = t.get("progress", 0)
                    total = t.get("count", 1)
                    target = t.get("target", "-")
                    t_type = t.get("type", "-")
                    
                    
                    if t_type == "collect_item":
                        item_name = self.world.get("items", {}).get(target, {}).get("name", target)
                        progress_text = f"    - 收集物品 {item_name}: {current}/{total}"
                    elif t_type == "deliver_item":
                        item_name = self.world.get("items", {}).get(target, {}).get("name", target)
                        if t.get("target_npc"):
                            recipient = self.world.get("npcs", {}).get(
                                t["target_npc"], {}
                            ).get("name", t["target_npc"])
                        elif t.get("target_role"):
                            recipient = self.world.get("roles", {}).get(
                                t["target_role"], {}
                            ).get("name", t["target_role"])
                        else:
                            recipient = "任意對象"
                        progress_text = (
                            f"    - 將 {item_name} 交給 {recipient}: "
                            f"{current}/{total}"
                        )
                    elif t_type == "talk_to_npc":
                        npc_name = self.world.get("npcs", {}).get(target, {}).get("name", target)
                        topic_id = t.get("item_id")
                        topic_name = topic_id or "任意話題"
                        progress_text = f"    - 與 {npc_name} 對話 (主題: {topic_name}): {'已完成' if current >= total else f'{current}/{total}'}"
                    elif t_type == "go_to_room":
                        room_name = self.world.get("rooms", {}).get(target, {}).get("name", target)
                        progress_text = f"    - 到達地點 {room_name}: {'已完成' if current >= total else '未完成'}"
                    elif t_type == "defeat_monster":
                        monster_name = self.world.get("monsters", {}).get(target, {}).get("name", target)
                        progress_text = f"    - 擊敗 {monster_name}: {current}/{total}"
                        
                    if progress_text:
                         log.append(progress_text)
        else:
            log.append("（目前沒有活躍任務）")
        
        # 完成任務
        if qs.completed:
            log.append("▶ 已完成任務:")
            for qid in qs.completed:
                qdef = self.quests.get(qid, {"name": qid})
                log.append(f"  [{qdef['name']}]")
        
        self.say("\n".join(log))
        return {"ok": True}

    def _fire_deliver(
        self,
        state: GameState,
        quest_id: str,
        item_id: str,
        npc_id: str,
    ):
        found = self._find_delivery_task(state, quest_id, item_id, npc_id)
        if found is None:
            return {"ok": False, "text": "這件物品目前不能交給對方。"}

        _, task = found
        try:
            state.inventory.items.remove(item_id)
        except (AttributeError, ValueError):
            return {"ok": False, "text": "你沒有這件物品。"}

        current = int(task.get("progress", 0))
        total = int(task.get("count", 1))
        new_progress = min(total, current + 1)
        task["progress"] = new_progress

        item_name = self.world.get("items", {}).get(item_id, {}).get("name", item_id)
        npc_name = self.world.get("npcs", {}).get(npc_id, {}).get("name", npc_id)
        quest_name = self.quests.get(quest_id, {}).get("name", quest_id)

        self.say(f"你把 {item_name} 交給了 {npc_name}。")
        self.say(f"任務 [{quest_name}] 進度更新：{new_progress}/{total}")
        self._check_completion(state, quest_id)

        return {
            "ok": True,
            "quest_id": quest_id,
            "item_id": item_id,
            "target_id": npc_id,
            "progress": new_progress,
            "count": total,
        }

    def _fire_accept(self, state: GameState, quest_id: str):
        if not self._can_accept(state, quest_id):
            missing = self._missing_requirements(state, quest_id)
            if missing:
                names = [self.quests.get(required_id, {}).get("name", required_id) for required_id in missing]
                return {"ok": False, "text": "尚未完成前置任務：" + "、".join(names)}
            return {"ok": False, "text": "無法接受此任務 (已完成、已活躍或任務不存在)。"}
            
        qdef = self.quests.get(quest_id)
        
        if not qdef: return {"ok": False, "text": "任務資料不存在。"}
            
        # 轉換任務定義為內部狀態（加上 progress）
        tasks_state = [
            {**tdef, "progress": 0}
            for tdef in qdef.get("tasks", [])
        ]
            
        if not tasks_state:
            return {"ok": False, "text": "任務沒有定義任何目標。"}
            
        state.quest.active[quest_id] = tasks_state
        self.say(f"★ 接受新任務：{qdef['name']}")
        return {"ok": True, "text": f"你接受了任務：{qdef['name']}。請記得查看任務日誌 (quest log)！"}

    # --- 外部鉤子：用於 Engine 在每次玩家行動後呼叫 ---
    def quest_check(self, state: GameState, request: ActionRequest):
        """在每次動作後，依同一個 ActionRequest 更新任務進度。"""
        verb = request.verb
        target_id = request.target_id
        item_id = request.topic_id if verb == "talk_say" else request.item_id
        qs = state.quest
        updated_quests: Set[str] = set()

        for qid, tasks in list(qs.active.items()):
            for task in tasks:
                progress_change = 0
                current_progress = task.get("progress", 0)
                target_count = task.get("count", 1)
                
                if current_progress >= target_count:
                    continue 

                # 1. 到達房間 (go_to_room)
                if verb == "go" and task.get("type") == "go_to_room" and state.room_id == task.get("target"):
                    progress_change = target_count 
                    
                # 2. 與NPC對話 (talk_to_npc)
                elif verb == "talk_say" and task.get("type") == "talk_to_npc" and target_id == task.get("target"):
                    if task.get("item_id") is None or task.get("item_id") == item_id:
                        progress_change = target_count 
                
                # 3. 擊敗怪物 (defeat_monster) - 需與 Combat 整合
                # 假設 CombatEngine 在敵人死亡時呼叫 quest_check(..., "combat_end", enemy_id=enemy_id)
                # elif verb == "combat_end" and task.get("type") == "defeat_monster" and target_id == task.get("target"):
                #     progress_change = 1
                
                # 更新進度
                if progress_change > 0:
                    old_progress = current_progress
                    new_progress = min(target_count, current_progress + progress_change)
                    task["progress"] = new_progress
                    
                    if new_progress > old_progress:
                        updated_quests.add(qid)
                        qdef = self.quests.get(qid)
                        if qdef:
                           self.say(f"任務 [{qdef.get('name', qid)}] 進度更新：{new_progress}/{target_count}")

        # 檢查更新過的任務是否完成
        for qid in updated_quests:
            self._check_completion(state, qid)
