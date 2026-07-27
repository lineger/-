from typing import Dict, List, Any, Callable
from System.action_request import ActionRequest
from System.systems_hub import SystemsHub
from System.combat_engine import CombatEngine
from System.equip_engine import EquipEngine
from System.simple_system import SimpleSystem
from System.talk_system import TalkSystem
from System.emotion_system import EmotionSystem
from System.team_system import TeamSystem
from System.quest_system import QuestSystem
from System.navigation_system import NavigationSystem
from Data.derive import recompute_derived
from Data.state import GameState


# =========================
# 條件 handlers
# =========================
CONDITION: Dict[str, Callable[[dict, dict], bool]] = {}

def _get_value(ctx, key, default=None):
    st: GameState = ctx["state"]

    # stats.*
    if key.startswith("stats."):
        sub = key.split(".", 1)[1]
        return getattr(st.stats, sub, default)

    # 直接寫 hp/mp/gold 也能取
    if key in ("hp", "mp", "gold", "max_hp", "max_mp", "lvl", "exp"):
        return getattr(st.stats, key, default)

    # 其他一律當 facts
    return st.facts.get(key, default)

def cond_fact_is_true(ctx, c):
    v = _get_value(ctx, c["key"], False)
    return bool(v)

def cond_fact_is_false(ctx, c):
    v = _get_value(ctx, c["key"], False)
    return not bool(v)

def cond_fact_at_least(ctx, c):
    v = int(_get_value(ctx, c["key"], 0) or 0)
    return v >= int(c.get("min", 0))

def cond_room_tag_any(ctx, c):
    rid = ctx["state"].room_id
    tags = set(t.lower() for t in ctx["world"]["rooms"][rid].get("tags", []))
    need = set(t.lower() for t in c.get("tags", []))
    return bool(tags & need)

def cond_target_is(ctx, c):
    return ctx.get("target_id", "").lower() == c.get("id", "").lower()

def cond_all(ctx, c):
    return all(_eval_cond(ctx, sub) for sub in c.get("conds", []))

def cond_any(ctx, c):
    return any(_eval_cond(ctx, sub) for sub in c.get("conds", []))

def cond_not(ctx, c):
    return not _eval_cond(ctx, c["cond"])

for k, v in {
    "fact_is_true":  cond_fact_is_true,
    "fact_is_false": cond_fact_is_false,
    "fact_at_least": cond_fact_at_least,
    "room_tag_any":  cond_room_tag_any,
    "target_is":     cond_target_is,
    "all":           cond_all,
    "any":           cond_any,
    "not":           cond_not,
}.items():
    CONDITION[k] = v


def _eval_cond(ctx: dict, cond: dict) -> bool:
    t = cond.get("type")
    fn = CONDITION.get(t)
    if not fn:
        ctx["say"](f"[WARN] 未支援條件: {t}")
        return False
    try:
        return bool(fn(ctx, cond))
    except Exception as ex:
        ctx["say"](f"[ERR] 條件執行失敗 {t}: {ex}")
        return False

def _conds_ok(conds: List[dict], ctx: dict) -> bool:
    return all(_eval_cond(ctx, c) for c in (conds or []))


# =========================
# 效果 handlers
# =========================
EFFECT: Dict[str, Callable[[dict, dict], None]] = {}

def eff_message(ctx, e):
    ctx["say"](e.get("text", ""))

def eff_set_fact(ctx, e):
    ctx["state"].facts[e["key"]] = e.get("value", True)

def eff_give_item(ctx, e):
    if e.get("to", "actor") == "actor":
        ctx["state"].inventory.items.append(e["item"])

def eff_consume_item(ctx, e):
    item = (e.get("item") or ctx.get("item_id", "")).lower()
    inv = ctx["state"].inventory.items
    for i, it in enumerate(inv):
        if it.lower() == item:
            del inv[i]
            break

def eff_add_exit(ctx, e):
    rid = e.get("from_room", "$here")
    if rid == "$here":
        rid = ctx["state"].room_id
    room = ctx["world"]["rooms"].get(rid)
    if not room:
        ctx["say"](f"[WARN] add_exit: 房間不存在: {rid}")
        return
    direction = e.get("dir") or e.get("direction")
    to_room   = e.get("to_room") or e.get("to")
    if not direction or not to_room:
        ctx["say"]("[WARN] add_exit: 需要 dir/direction 與 to/to_room")
        return
    room.setdefault("exits", {})[direction] = to_room

def _clamp(v, lo, hi): 
    return max(lo, min(hi, v))

def eff_add_gold(ctx, e):
    delta = int(e.get("amount", 0))
    ctx["state"].stats.gold = max(0, ctx["state"].stats.gold + delta)

def eff_spend_gold(ctx, e):
    delta = int(e.get("amount", 0))
    if ctx["state"].stats.gold < delta:
        (ctx.get("say") or (lambda msg: None))("你的金錢不足。")
        return
    ctx["state"].stats.gold -= delta

def eff_heal_hp(ctx, e):
    amt = int(e.get("amount", 0))
    st = ctx["state"].stats
    st.hp = _clamp(st.hp + amt, 0, getattr(st, "max_hp", st.hp))

def eff_use_mp(ctx, e):
    amt = int(e.get("amount", 0))
    st = ctx["state"].stats
    st.mp = _clamp(st.mp - amt, 0, getattr(st, "max_mp", st.mp))

def eff_damage_hp(ctx, e):
    amt = int(e.get("amount", 0))
    st = ctx["state"].stats
    st.hp = max(0, st.hp - amt)
    if st.hp <= 0:
        (ctx.get("say") or (lambda msg: None))("你倒下了……")

def eff_quest_accept(ctx, e):
    qid = e.get("quest_id")
    if not qid: return
    # 效果層已持有 hub，直接送入通過驗證的請求物件。
    if ctx["hub"]:
        request = ActionRequest.build("quest_accept", quest_id=qid)
        ctx["hub"].fire(request, ctx["state"])


for k, v in {
    "message":      eff_message,
    "set_fact":     eff_set_fact,
    "give_item":    eff_give_item,
    "consume_item": eff_consume_item,
    "add_exit":     eff_add_exit,
    "add_gold":     eff_add_gold,
    "spend_gold":   eff_spend_gold,
    "heal_hp":      eff_heal_hp,
    "use_mp":       eff_use_mp,
    "damage_hp":    eff_damage_hp,
    "quest_accept": eff_quest_accept
}.items():
    EFFECT[k] = v


# =========================
# 引擎
# =========================
class Engine:
    def __init__(self, world: Dict[str, Any], eventbook: Dict[str, Any], say):
        self.world = world
        self.events = eventbook
        self.say = say
        
        self.hub = SystemsHub()
        # 讓其他系統可以回調 Engine 的方法
        self.hub.engine = self

        
        self.combat = CombatEngine()
        self.equip = EquipEngine()
        self.simple = SimpleSystem()
        self.emotion = EmotionSystem()
        self.talk = TalkSystem()
        self.team = TeamSystem()
        self.quest = QuestSystem()
        self.navigation = NavigationSystem()

        
        self.hub.register(self.combat)
        self.hub.register(self.equip)
        self.hub.register(self.simple)
        self.hub.register(self.emotion)
        self.hub.register(self.talk)
        self.hub.register(self.team)
        self.hub.register(self.quest)
        self.hub.register(self.navigation)
        

        self.hub.attach_all(say=self.say, world=self.world, hub=self.hub)

    def _apply(self, effects: List[dict], ctx: dict) -> None:
        for e in effects or []:
            fn = EFFECT.get(e.get("type"))
            if fn:
                try:
                    # 傳入 hub 以便調用 eff_quest_accept
                    ctx["hub"] = self.hub
                    fn(ctx, e)
                except Exception as ex:
                    ctx["say"](f"[ERR] 效果執行失敗 {e.get('type')}: {ex}")
            else:
                ctx["say"](f"[WARN] 未支援效果: {e}")

    def _collect_event_defs(self, request: ActionRequest, state) -> List[dict]:
        ev_ids: List[str] = []
        if request.verb == "use" and request.item_id:
            ev_ids = self.world["items"].get(request.item_id, {}).get("events", {}).get("use", [])
        elif request.verb == "talk" and request.target_id:
            ev_ids = self.world["npcs"].get(request.target_id, {}).get("events", {}).get("talk", [])
        elif request.verb == "give" and request.item_id:
            ev_ids = self.world["items"].get(request.item_id, {}).get("events", {}).get("give", [])
        elif request.verb == "enter":
            room_id = state.room_id
            ev_ids = self.world["rooms"].get(room_id, {}).get("events", {}).get("enter", [])
        return [self.events[event_id] for event_id in ev_ids if event_id in self.events]

    def _event_context(self, request: ActionRequest, state) -> dict:
        return {
            "world": self.world,
            "state": state,
            "item_id": request.item_id,
            "target_id": request.target_id,
            "say": self.say,
        }

    def _events_can_fire(self, request: ActionRequest, state) -> bool:
        ctx = self._event_context(request, state)
        for event in self._collect_event_defs(request, state):
            if _conds_ok(event.get("when", []), ctx):
                return True
        return False

    def _try_fire_events(self, request: ActionRequest, state) -> bool:
        ctx = self._event_context(request, state)
        best = None
        for event in self._collect_event_defs(request, state):
            if _conds_ok(event.get("when", []), ctx):
                if best is None or int(event.get("priority", 0)) > int(best.get("priority", 0)):
                    best = event
        if best:
            self._apply(best.get("do", []), ctx)
            return True
        return False

    @staticmethod
    def _result_info(result) -> tuple[bool, str | None]:
        if isinstance(result, dict):
            return bool(result.get("ok", True)), result.get("text")
        if isinstance(result, bool):
            return result, None
        if result is None:
            return False, None
        return True, None

    def can_fire(self, verb: str, state, **params) -> bool:
        request = ActionRequest.build(verb, **params)
        if self._events_can_fire(request, state):
            return True
        return self.hub.can_fire(request, state)

    def fire(self, verb: str, state, **params):
        request = ActionRequest.build(verb, **params)

        # 1. 執行核心系統動作
        result = self.hub.fire(request, state)
        success, text = self._result_info(result)

        # 2. 執行事件系統（如果沒有被核心系統攔截）
        event_fired = self._try_fire_events(request, state)
        if event_fired:
            pass
        elif success:
            if text:
                try:
                    self.say(text)
                except Exception:
                    pass
        else:
            self.say("沒有發生什麼事。")

        action_succeeded = success or event_fired

        # 3. 只有成功的動作才更新任務，避免失敗嘗試誤算進度。
        if (
            action_succeeded
            and hasattr(self, "quest")
            and hasattr(self.quest, "quest_check")
        ):
            self.quest.quest_check(state, request)

        # 4. 只有真的完成移動，才處理新房間的 enter 事件。
        if request.verb == "go" and success:
            self._try_fire_events(ActionRequest.build("enter"), state)

        return result
