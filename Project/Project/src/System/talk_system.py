from typing import List, Tuple, Optional, Dict, Any
import traceback, time
from System.action_request import ActionRequest
from System.systems_hub import BaseSystem

class TalkSystem(BaseSystem):
    # 讓 Hub 快篩；保持與你的路由介面一致
    verbs: tuple[str, ...] = ("talk_open", "talk_say", "talk_give")
    priority: int = 0  # 需要的話可調高

    # 避免在 __init__ 時調用 _emo 導致 RuntimeError
    _emo_cached: Any = None

    def __init__(self, *, say=print, world: Optional[Dict[str, Any]] = None):
        self.say = say
        self.world = world or {}
        # self.hub 會在 SystemsHub.attach_all() 後被設置：s.hub = hub
        

    def attach(self, *, say=print, world=None, hub=None):
        self.say   = say or (lambda *_: None)
        self.world = world or {}
        self.hub   = hub
        # 在 attach 時，如果 _emo_cached 還沒設，就嘗試查找
        if self._emo_cached is None:
            self._emo_cached = self._find_emo_system(hub)


    def _find_emo_system(self, hub):
        """僅在 attach 時調用，避免在 __init__ 時觸發 RuntimeError"""
        for sys in getattr(hub, "systems", []):
            if hasattr(sys, "attitudes") and hasattr(sys, "add"):
                return sys
    

    # ========== Hub 標準介面 ==========
    def can_fire(self, request: ActionRequest, state) -> bool:
        if request.verb == "talk_open":
            return request.target_id is not None
        if request.verb == "talk_say":
            return request.target_id is not None and request.topic_id is not None
        if request.verb == "talk_give":
            return (
                request.target_id is not None
                and request.item_id is not None
                and request.item_id in getattr(state.inventory, "items", [])
            )
        return False

    def fire(self, request: ActionRequest, state):
        if request.verb == "talk_open":
            return self.open(state, request.target_id)
        if request.verb == "talk_say":
            return self.say_topic(state, request.target_id, request.topic_id)
        if request.verb == "talk_give":
            return self.give(state, request.target_id, request.item_id)
        return {"ok": False, "text": f"TalkSystem 不支援 verb={request.verb}"}

    # ========== 外部 API ==========
    def open(self, state, npc_id: str) -> dict:
        npc = (self.world.get("npcs") or {}).get(npc_id, {})
        name    = npc.get("name", npc_id)
        faction = npc.get("faction", "-")
        job     = npc.get("job", "-")
        level   = int(npc.get("level", 1))

        # 這裡改用 self._emo_cached
        emo = self._emo_cached if self._emo_cached is not None else self._find_emo_system(self.hub)
        labels  = self._emo().attitudes(state, npc_id, max_labels=3)
        primary = labels[0] if labels else "reserved"

        options = self._collect_topics_for_ui(state, npc_id, npc)
        giftable = bool(npc.get("gifts")) or True  # 你要更嚴格可自行調整

        return {
            "ok": True,
            "npc_id": npc_id,
            "name": name, "faction": faction, "job": job, "level": level,
            "attitudes": labels, "primary_attitude": primary,
            "options": options, "giftable": giftable,
        }

    def say_topic(self, state, npc_id: str, topic_id: str) -> dict:
        npc  = (self.world.get("npcs") or {}).get(npc_id, {})
        tdef = ((npc.get("topics") or {}).get(topic_id)) or {}
        if not tdef:
            return {"ok": False, "text": "她似乎不想談這個。"}

        ok, msg = self._check_requires(state, npc_id, tdef.get("requires") or {})
        if not ok:
            return {"ok": False, "text": msg or "現在不是談這個的時候。"}

        reply = tdef.get("reply")
        if isinstance(reply, list):
            text = reply[0] if reply else "……"
        else:
            text = reply or "……"

        self._apply_effects(state, npc_id, tdef.get("effects") or [])

        # once: 設 flag，讓之後不再顯示
        if tdef.get("once"):
            state.flags.add(f"talk.once.{npc_id}.{topic_id}")

        return {"ok": True, "text": text}

    def give(self, state, npc_id: str, item_id: str) -> dict:
        npc   = (self.world.get("npcs") or {}).get(npc_id, {})
        gifts = npc.get("gifts", {})  # {item_id: {"joy":+x, "trust":+y, "reply":"...", "reward_item": "...", "consume": true}}
        rule  = gifts.get(item_id)
        if not rule:
            return {"ok": False, "text": "看來她對這個不太感興趣。"}

        # 扣背包（若需要消耗）——新版：state.inventory.items
        if rule.get("consume", True):
            try:
                state.inventory.items.remove(item_id)
            except (ValueError, AttributeError):
                return {"ok": False, "text": "你沒有這個東西。"}

        # 情感變化（支援 joy/trust/fear/surprise/sadness/disgust/anger/anticipation）
        for emo, d in rule.items():
            if emo in ("joy","trust","fear","surprise","sadness","disgust","anger","anticipation"):
                self._emo().add(state, npc_id, emo, int(d), silent=True)

        # 發放獎勵（新版沒有 inventory.add，就直接 append 到 items）
        reward = rule.get("reward_item")
        if reward:
            try:
                # 優先走自定 add（若你之後實作了）
                if hasattr(state.inventory, "add") and callable(getattr(state.inventory, "add")):
                    state.inventory.add(reward)
                else:
                    state.inventory.items.append(reward)
            except Exception:
                pass

        msg = rule.get("reply", "她收下了你的禮物。")
        return {"ok": True, "text": msg}

    # ========== 內部 ==========
    def _collect_topics_for_ui(self, state, npc_id: str, npc: dict) -> List[dict]:
        out: List[dict] = []
        topics = npc.get("topics") or {}
        for tid, tdef in topics.items():
            requires = tdef.get("requires") or {}
            # once: 若已看過，略過
            if tdef.get("once") and f"talk.once.{npc_id}.{tid}" in state.flags:
                continue
            ok, _ = self._check_requires(state, npc_id, requires)
            if ok:
                out.append({"id": tid, "text": tdef.get("label", tid)})
        # 若 NPC 沒定義任何 topic，提供預設 greet
        if not topics:
            out.append({"id": "greet", "text": "打招呼"})
        return out

    def _check_requires(self, state, npc_id: str, req: dict) -> Tuple[bool, Optional[str]]:
        if not req:
            return True, None
        # 態度標籤（由 EmotionSystem 提供）
        if "attitudes_any" in req:
            labels = set(self._emo().attitudes(state, npc_id, max_labels=5))
            if not (labels & set(req["attitudes_any"])):
                return False, "她對你仍保持距離。"
        if "attitudes_all" in req:
            labels = set(self._emo().attitudes(state, npc_id, max_labels=5))
            if not set(req["attitudes_all"]).issubset(labels):
                return False, "或許再多培養一下關係。"

        # 旗標（你專案已有 state.flags: set[str]）
        if "flags_all" in req:
            if not set(req["flags_all"]).issubset(state.flags):
                return False, None
        if "flags_any" in req:
            if not (set(req["flags_any"]) & state.flags):
                return False, None
        if "flags_all_not" in req:
            if set(req["flags_all_not"]) & state.flags:
                return False, None
        return True, None

    def _apply_effects(self, state, npc_id: str, effs: List[dict]):
        # 這裡不再重複實作效果，而是調用 Engine 的 _apply
        # Engine 的 _apply 已經被修改，會檢查並執行 quest_accept
        if self.hub and hasattr(self.hub, "engine") and hasattr(self.hub.engine, "_apply"):
            # 需要提供 context
            ctx = {"state": state, "world": self.world, "say": self.say, "hub": self.hub}
            self.hub.engine._apply(effs, ctx)
        else:
            # 如果沒有 Engine 實體，則退回舊版的情感/旗標邏輯
            for eff in effs:
                if "emotion_add" in eff:
                    delta_map = eff["emotion_add"]
                    for emo, d in delta_map.items():
                        self._emo().add(state, npc_id, emo, int(d), silent=True)
                elif "flag_add" in eff:
                    state.flags.add(eff["flag_add"])
                elif "flag_del" in eff:
                    try:
                        state.flags.remove(eff["flag_del"])
                    except KeyError:
                        pass
                # quest_accept 無法執行
                

    # EmotionSystem 掃描與快取（不 import；只依賴 hub）
    def _emo(self):
        # 已快取
        if hasattr(self, "_emo_cached"):
            if self._emo_cached is None:
                raise RuntimeError("TalkSystem 找不到 EmotionSystem：請先在 Hub 註冊並 attach_all。")
            return self._emo_cached

        emo = None
        for sys in getattr(getattr(self, "hub", None), "systems", []):
            # 以介面辨識：擁有 attitudes() 與 add() 的系統
            if hasattr(sys, "attitudes") and hasattr(sys, "add"):
                emo = sys
                break
        self._emo_cached = emo
        if emo is None:
            raise RuntimeError("TalkSystem 找不到 EmotionSystem：請先在 Hub 註冊並 attach_all。")
        return emo


