from __future__ import annotations

from typing import Any, Mapping


ITEM_ACTION_CATALOG: dict[str, dict[str, str]] = {
    "equip": {
        "label": "裝備",
        "description": "允許物品使用裝備欄與裝備加成欄位。",
    },
    "use": {
        "label": "直接使用",
        "description": "允許物品使用 simple_use 即時效果。",
    },
    "target_use": {
        "label": "指定目標使用",
        "description": "允許物品使用 uses 指定目標規則。",
    },
    "gift": {
        "label": "送禮",
        "description": "此 Kind 可被納入 NPC 送禮設計；是否接受仍由 NPC gifts 規則決定。",
    },
    "deliver": {
        "label": "任務交付",
        "description": "此 Kind 可被任務當成交付物；是否成立仍由 Quest 目標決定。",
    },
    "trade": {
        "label": "交易",
        "description": "保留給未來交易系統使用；目前不會自動建立價格規則。",
    },
}


ITEM_FIELD_CATALOG: dict[str, dict[str, str]] = {
    "slot": {
        "label": "裝備欄 slot",
        "description": "物品可裝備時使用的 equipment slot ID。",
    },
    "bonuses": {
        "label": "裝備加成 bonuses",
        "description": "裝備後提供的數值加成。",
    },
    "simple_use": {
        "label": "直接使用 simple_use",
        "description": "不需指定目標的使用效果，例如 hp_delta。",
    },
    "uses": {
        "label": "指定目標 uses",
        "description": "需要指定房間物件或其他目標的使用規則。",
    },
    "tags": {
        "label": "戰鬥 Tags",
        "description": "物品攜帶的戰鬥標籤。",
    },
    "max_stack": {
        "label": "堆疊上限 max_stack",
        "description": "覆寫 Kind 的預設堆疊上限；目前作為資料契約，背包尚未強制限制。",
    },
}


ACTION_FIELD_HINTS: dict[str, frozenset[str]] = {
    "equip": frozenset({"slot", "bonuses"}),
    "use": frozenset({"simple_use"}),
    "target_use": frozenset({"uses"}),
}


def normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry]


def kind_actions(kind: Mapping[str, Any] | None) -> set[str]:
    return set(normalized_string_list((kind or {}).get("allowed_actions")))


def kind_required_fields(kind: Mapping[str, Any] | None) -> set[str]:
    return set(normalized_string_list((kind or {}).get("required_fields")))


def kind_allowed_slots(kind: Mapping[str, Any] | None) -> list[str]:
    return normalized_string_list((kind or {}).get("allowed_slots"))


def field_has_value(item: Mapping[str, Any], field_name: str) -> bool:
    if field_name not in item:
        return False
    value = item.get(field_name)
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def kind_contract_summary(kind_id: str, kind: Mapping[str, Any] | None) -> str:
    if not kind:
        return f"Kind {kind_id or '(未選擇)'} 尚無定義。"

    actions = kind_actions(kind)
    required = kind_required_fields(kind)
    slots = kind_allowed_slots(kind)
    action_labels = [ITEM_ACTION_CATALOG.get(action, {}).get("label", action) for action in sorted(actions)]
    field_labels = [ITEM_FIELD_CATALOG.get(field, {}).get("label", field) for field in sorted(required)]

    lines = [f"Kind：{kind_id} — {kind.get('name', '')}".rstrip(" —")]
    lines.append("允許操作：" + ("、".join(action_labels) if action_labels else "未設定"))
    lines.append("必填欄位：" + ("、".join(field_labels) if field_labels else "無"))
    if bool(kind.get("stackable", False)):
        default_max = kind.get("default_max_stack")
        lines.append(f"可堆疊：是（預設上限 {default_max if default_max is not None else '未設定'}）")
    else:
        lines.append("可堆疊：否")
    if slots:
        lines.append("可用裝備欄：" + "、".join(slots))
    return "\n".join(lines)
