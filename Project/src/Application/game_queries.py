from __future__ import annotations

from typing import Any, Dict, List


def get_room_view(world: Dict[str, Any], state) -> Dict[str, Any]:
    """回傳目前房間的結構化顯示資料，不修改遊戲狀態。"""

    room_id = state.room_id
    room = (world.get("rooms") or {}).get(room_id, {})
    npcs = world.get("npcs") or {}

    return {
        "id": room_id,
        "name": room.get("name", room_id),
        "description": room.get("desc", ""),
        "npc_names": [
            (npcs.get(npc_id) or {}).get("name", npc_id)
            for npc_id in (room.get("npcs") or [])
        ],
        "exits": list((room.get("exits") or {}).keys()),
    }


def get_inventory_view(world: Dict[str, Any], state) -> List[Dict[str, str]]:
    """回傳背包物品的結構化顯示資料，不修改遊戲狀態。"""

    items = world.get("items") or {}
    inventory = getattr(getattr(state, "inventory", None), "items", []) or []

    return [
        {
            "id": item_id,
            "name": (items.get(item_id) or {}).get("name", item_id),
            "description": (items.get(item_id) or {}).get("desc", ""),
        }
        for item_id in inventory
    ]
