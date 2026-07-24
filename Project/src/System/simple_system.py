from __future__ import annotations
from typing import Optional

from System.action_request import ActionRequest


class SimpleSystem:
    """
    最小可跑版：
    - 支援 verbs: talk / give / use（先從 talk 打通 UI）
    - can_fire：讓 UI 能判斷有哪些行為可做
    - fire：目前只做極簡回饋（不動狀態），之後再逐步充實

    ※ 等幅改版說明：
      - 原本 state.inventory 為 list，改為 state.inventory.items（list）
      - 原本 state.stats 為 dict，改為 dataclass：state.stats.hp / mp / gold
      - 上限值以 state.derived.max_hp（與可選的 max_mp）做鉗制
    """
    verbs = ("talk", "give", "use")
    priority = 10

    def __init__(self, world=None, say=None):
        self.world = world
        self.say = say

    # SystemsHub 會呼叫，讓 Hub 統一注入引用
    def attach(self, *, say, world, hub):
        self.world = world
        self.say = say
        self.hub = hub

    def can_fire(self, request: ActionRequest, state) -> bool:
        verb = request.verb
        item_id = request.item_id
        target_id = request.target_id
        w = self.world or {}

        if verb == "give":
            # 要有目標、物品存在於世界，且玩家背包有該物品
            return bool(target_id and item_id) and \
                   (item_id in (w.get("items") or {})) and \
                   (item_id in state.inventory.items)

        if verb == "use":
            if not item_id:
                return False
            it = (w.get("items") or {}).get(item_id)
            if not it:
                return False
            if target_id:
                # 目標使用：需要有對應規則，且玩家背包有此物品
                rule = (it.get("uses") or {}).get(target_id)
                return bool(rule) and (item_id in state.inventory.items)
            # 自用：需要有 simple_use，且玩家背包有此物品
            return bool(it.get("simple_use")) and (item_id in state.inventory.items)

        return False

    def fire(self, request: ActionRequest, state) -> bool:
        verb = request.verb
        item_id = request.item_id
        target_id = request.target_id
        say = self.say or (lambda *_: None)
        w = self.world or {}

        if verb == "talk" and target_id:
            npc = (w.get("npcs") or {}).get(target_id, {})
            name = npc.get("name", target_id)
            dls = npc.get("dialogues") or []
            msg = dls[0] if dls else None
            say(msg or f"{name}：……")
            return True

        if verb == "give" and target_id and item_id:
            if item_id not in state.inventory.items:
                say("你沒有那個物品。"); return True
            #（最小版：先只回饋，不做禮物規則與好感，之後再接）
            npc = (w.get("npcs") or {}).get(target_id, {})
            name = npc.get("name", target_id)
            say(f"你遞出了 {item_id} 給 {name}。")
            return True

        if verb == "use" and item_id:
            it = (w.get("items") or {}).get(item_id, {"name": item_id})
            if item_id not in state.inventory.items:
                say("你身上沒有這樣東西。"); return True

            # 1) 目標使用（若有 target，先判斷這種）
            if target_id:
                rule = (it.get("uses") or {}).get(target_id)
                if not rule:
                    return False
                # consume
                if rule.get("consume", False):
                    try:
                        state.inventory.items.remove(item_id)
                    except ValueError:
                        pass
                # 獎勵
                if (reward := rule.get("reward_item")):
                    state.inventory.items.append(reward)
                # 數值變動（等幅轉寫：hp/mp/gold）
                # hp：以 derived.max_hp 鉗制
                if "hp_delta" in rule:
                    max_hp = getattr(state.derived, "max_hp", state.stats.hp)
                    state.stats.hp = max(0, min(max_hp, state.stats.hp + int(rule["hp_delta"])))
                # mp：若有 derived.max_mp 就用；否則以當前 mp 作上限
                if "mp_delta" in rule:
                    max_mp = getattr(state.derived, "max_mp", state.stats.mp)
                    state.stats.mp = max(0, min(max_mp, state.stats.mp + int(rule["mp_delta"])))
                # gold：不可為負
                if "gold_delta" in rule:
                    state.stats.gold = max(0, state.stats.gold + int(rule["gold_delta"]))
                if (msg := rule.get("reply")):
                    say(msg)
                return True

            # 2) 自用（沒有 target）
            rule = it.get("simple_use")
            if not rule:
                return False
            if rule.get("consume", False):
                try:
                    state.inventory.items.remove(item_id)
                except ValueError:
                    pass
            if (reward := rule.get("reward_item")):
                state.inventory.items.append(reward)
            # 數值變動（等幅轉寫：hp/mp/gold）
            if "hp_delta" in rule:
                max_hp = getattr(state.derived, "max_hp", state.stats.hp)
                state.stats.hp = max(0, min(max_hp, state.stats.hp + int(rule["hp_delta"])))
            if "mp_delta" in rule:
                max_mp = getattr(state.derived, "max_mp", state.stats.mp)
                state.stats.mp = max(0, min(max_mp, state.stats.mp + int(rule["mp_delta"])))
            if "gold_delta" in rule:
                state.stats.gold = max(0, state.stats.gold + int(rule["gold_delta"]))
            if (msg := rule.get("reply")):
                say(msg)
            return True

        return False
