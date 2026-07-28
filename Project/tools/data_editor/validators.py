from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping


ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    category: str
    entity_id: str
    message: str

    def render(self) -> str:
        icon = "❌" if self.severity == "error" else "⚠"
        return f"{icon} [{self.category}:{self.entity_id}] {self.message}"


class DataValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("\n".join(issue.render() for issue in self.issues))


def _issue(
    out: list[ValidationIssue],
    severity: str,
    category: str,
    entity_id: str,
    message: str,
) -> None:
    out.append(ValidationIssue(severity, category, entity_id, message))


def _require_mapping(
    out: list[ValidationIssue],
    category: str,
    entity_id: str,
    value: Any,
    field_name: str,
) -> Mapping[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _issue(out, "error", category, entity_id, f"{field_name} 必須是 JSON object")
        return None
    return value


def _require_list(
    out: list[ValidationIssue],
    category: str,
    entity_id: str,
    value: Any,
    field_name: str,
) -> list[Any] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        _issue(out, "error", category, entity_id, f"{field_name} 必須是 JSON array")
        return None
    return value


def _validate_ids(data: Mapping[str, Mapping[str, Any]], out: list[ValidationIssue]) -> None:
    for category, entities in data.items():
        if not isinstance(entities, Mapping):
            _issue(out, "error", category, "*", "分類資料必須是 id → object 的映射")
            continue
        for entity_id, entity in entities.items():
            if not isinstance(entity_id, str) or not ID_PATTERN.fullmatch(entity_id):
                _issue(out, "error", category, str(entity_id), "ID 只能使用英數、底線、句點與連字號")
            if not isinstance(entity, Mapping):
                _issue(out, "error", category, entity_id, "資料項目必須是 JSON object")
                continue
            internal_id = entity.get("id")
            if internal_id not in (None, entity_id):
                _issue(out, "error", category, entity_id, f"內部 id={internal_id!r} 與索引 ID 不一致")


def validate_database(data: Mapping[str, Mapping[str, Any]]) -> list[ValidationIssue]:
    """跨檔驗證編輯器支援的資料。錯誤阻止儲存，警告只提示。"""
    issues: list[ValidationIssue] = []
    _validate_ids(data, issues)

    tags = data.get("tags", {})
    roles = data.get("roles", {})
    items = data.get("items", {})
    rooms = data.get("rooms", {})
    npcs = data.get("npcs", {})
    quests = data.get("quests", {})

    # 戰鬥 tag 定義中的交叉引用。
    for tag_id, tag in tags.items():
        multipliers = _require_mapping(issues, "tags", tag_id, tag.get("multipliers"), "multipliers")
        if multipliers is not None:
            for target_tag, value in multipliers.items():
                if target_tag not in tags:
                    _issue(issues, "warning", "tags", tag_id, f"multipliers 引用了未定義 tag：{target_tag}")
                if not isinstance(value, (int, float)):
                    _issue(issues, "error", "tags", tag_id, f"倍率 {target_tag} 必須是數字")

    # Item 的戰鬥 tags。
    for item_id, item in items.items():
        item_tags = _require_list(issues, "items", item_id, item.get("tags"), "tags")
        if item_tags is not None:
            for tag_id in item_tags:
                if not isinstance(tag_id, str):
                    _issue(issues, "error", "items", item_id, "tags 只能包含字串 ID")
                elif tag_id not in tags:
                    # 現有資料可能含尚未集中定義的裝備特徵；先警告，不鎖死編輯。
                    _issue(issues, "warning", "items", item_id, f"引用了未定義戰鬥 tag：{tag_id}")

    # Room 引用。
    for room_id, room in rooms.items():
        exits = _require_mapping(issues, "rooms", room_id, room.get("exits"), "exits")
        if exits is not None:
            for direction, target_room in exits.items():
                if not isinstance(direction, str) or not direction.strip():
                    _issue(issues, "error", "rooms", room_id, "出口方向不可空白")
                if target_room not in rooms:
                    _issue(issues, "error", "rooms", room_id, f"出口 {direction!r} 指向不存在房間：{target_room!r}")

        for npc_id in _require_list(issues, "rooms", room_id, room.get("npcs"), "npcs") or []:
            if npc_id not in npcs:
                _issue(issues, "error", "rooms", room_id, f"引用了不存在 NPC：{npc_id}")
        for item_id in _require_list(issues, "rooms", room_id, room.get("items"), "items") or []:
            if item_id not in items:
                _issue(issues, "error", "rooms", room_id, f"引用了不存在 item：{item_id}")

    # NPC 社交、位置、送禮引用。
    for npc_id, npc in npcs.items():
        for role_id in _require_list(issues, "npcs", npc_id, npc.get("roles"), "roles") or []:
            if role_id not in roles:
                _issue(issues, "error", "npcs", npc_id, f"引用了未定義 role：{role_id}")
        for tag_id in _require_list(issues, "npcs", npc_id, npc.get("tags"), "tags") or []:
            if tag_id not in tags:
                _issue(issues, "warning", "npcs", npc_id, f"引用了未定義戰鬥 tag：{tag_id}")

        home_room = npc.get("home_room") or npc.get("default_room")
        if home_room and home_room not in rooms:
            _issue(issues, "error", "npcs", npc_id, f"預設房間不存在：{home_room}")

        gifts = _require_mapping(issues, "npcs", npc_id, npc.get("gifts"), "gifts")
        if gifts is not None:
            for gift_item, rule in gifts.items():
                if gift_item not in items:
                    _issue(issues, "error", "npcs", npc_id, f"送禮規則引用不存在 item：{gift_item}")
                if not isinstance(rule, Mapping):
                    _issue(issues, "error", "npcs", npc_id, f"禮物 {gift_item} 的規則必須是 object")
                    continue
                reward = rule.get("reward_item")
                if reward and reward not in items:
                    _issue(issues, "error", "npcs", npc_id, f"禮物 {gift_item} 回禮不存在：{reward}")

    # Quest 目標與獎勵。
    for quest_id, quest in quests.items():
        tasks = _require_list(issues, "quests", quest_id, quest.get("tasks"), "tasks") or []
        for index, task in enumerate(tasks, start=1):
            if not isinstance(task, Mapping):
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個 task 必須是 object")
                continue
            task_type = task.get("type")
            count = task.get("count", 1)
            if not isinstance(count, int) or count <= 0:
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個 task 的 count 必須是正整數")

            if task_type == "deliver_item":
                item_id = task.get("target")
                if item_id not in items:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個交付目標引用不存在 item：{item_id}")
                target_npc = task.get("target_npc")
                target_role = task.get("target_role")
                if target_npc and target_role:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個交付目標不可同時指定 NPC 與 role")
                if target_npc and target_npc not in npcs:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個交付目標引用不存在 NPC：{target_npc}")
                if target_role and target_role not in roles:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個交付目標引用不存在 role：{target_role}")
            elif task_type == "go_to_room":
                target = task.get("target")
                if target not in rooms:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個移動目標引用不存在 room：{target}")
            elif task_type == "talk_to_npc":
                target = task.get("target")
                if target not in npcs:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個對話目標引用不存在 NPC：{target}")

        rewards = _require_list(issues, "quests", quest_id, quest.get("rewards"), "rewards") or []
        for index, reward in enumerate(rewards, start=1):
            if not isinstance(reward, Mapping):
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個 reward 必須是 object")
                continue
            if reward.get("type") == "item" and reward.get("item_id") not in items:
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個獎勵引用不存在 item：{reward.get('item_id')}")

    return issues


def errors_only(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity == "error"]
