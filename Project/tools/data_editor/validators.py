from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from kind_contracts import (
    ACTION_FIELD_HINTS,
    ITEM_ACTION_CATALOG,
    ITEM_FIELD_CATALOG,
    field_has_value,
    kind_actions,
    kind_allowed_slots,
    kind_required_fields,
)


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
    item_kinds = data.get("item_kinds", {})
    equipment_slots = data.get("equipment_slots", {})
    species = data.get("species", {})
    status_effects = data.get("status_effects", {})
    skills = data.get("skills", {})
    monsters = data.get("monsters", {})
    items = data.get("items", {})
    rooms = data.get("rooms", {})
    npcs = data.get("npcs", {})
    quests = data.get("quests", {})

    # 戰鬥 tag 定義中的交叉引用。
    for tag_id, tag in tags.items():
        multipliers = _require_mapping(issues, "tags", tag_id, tag.get("multipliers"), "multipliers")
        if multipliers is not None:
            for target_tag, value in multipliers.items():
                if target_tag not in tags and target_tag not in species:
                    _issue(issues, "warning", "tags", tag_id, f"multipliers 引用了未定義 tag/species：{target_tag}")
                if not isinstance(value, (int, float)):
                    _issue(issues, "error", "tags", tag_id, f"倍率 {target_tag} 必須是數字")
        proc = _require_mapping(issues, "tags", tag_id, tag.get("on_hit_proc"), "on_hit_proc")
        if proc:
            status_id = proc.get("status")
            if not isinstance(status_id, str) or status_id not in status_effects:
                _issue(issues, "error", "tags", tag_id, f"on_hit_proc.status 不存在：{status_id}")
            chance = proc.get("chance")
            if not isinstance(chance, int) or isinstance(chance, bool) or not 0 <= chance <= 100:
                _issue(issues, "error", "tags", tag_id, "on_hit_proc.chance 必須是 0–100 的整數")

    # 狀態效果基本結構。
    for status_id, status in status_effects.items():
        duration = status.get("duration")
        if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0):
            _issue(issues, "error", "status_effects", status_id, "duration 必須是正整數")
        _require_mapping(issues, "status_effects", status_id, status.get("mods"), "mods")
        _require_mapping(issues, "status_effects", status_id, status.get("meta"), "meta")

    # Skill 的戰鬥 tag 與狀態效果引用。
    for skill_id, skill in skills.items():
        for tag_id in _require_list(issues, "skills", skill_id, skill.get("tags"), "tags") or []:
            if tag_id not in tags:
                _issue(issues, "warning", "skills", skill_id, f"引用了未定義戰鬥 tag：{tag_id}")
        status_apply = skill.get("status_apply")
        if isinstance(status_apply, Mapping):
            status_id = status_apply.get("id")
            is_inline = "duration" in status_apply or "mods" in status_apply
            if status_id and status_id not in status_effects and not is_inline:
                _issue(issues, "error", "skills", skill_id, f"status_apply.id 不存在：{status_id}")
        effects = _require_list(issues, "skills", skill_id, skill.get("effects"), "effects") or []
        for index, effect in enumerate(effects, start=1):
            if not isinstance(effect, Mapping):
                _issue(issues, "error", "skills", skill_id, f"第 {index} 個 effect 必須是 object")
                continue
            if effect.get("kind") != "apply_status":
                continue
            spec = effect.get("status_spec")
            status_id = spec.get("id") if isinstance(spec, Mapping) else spec
            is_inline = isinstance(spec, Mapping) and ("duration" in spec or "mods" in spec)
            if not isinstance(status_id, str) or (status_id not in status_effects and not is_inline):
                _issue(issues, "error", "skills", skill_id, f"第 {index} 個 effect 引用不存在狀態：{status_id}")

    # Monster 的種族、tag 與技能引用。
    for monster_id, monster in monsters.items():
        species_id = monster.get("species")
        if species_id and species_id not in species:
            _issue(issues, "error", "monsters", monster_id, f"引用了未定義 species：{species_id}")
        for tag_id in _require_list(issues, "monsters", monster_id, monster.get("tags"), "tags") or []:
            if tag_id not in tags:
                _issue(issues, "error", "monsters", monster_id, f"引用了未定義戰鬥 tag：{tag_id}")
        for skill_id in _require_list(issues, "monsters", monster_id, monster.get("skills"), "skills") or []:
            if skill_id not in skills:
                _issue(issues, "error", "monsters", monster_id, f"引用了不存在 skill：{skill_id}")
        combat = _require_mapping(issues, "monsters", monster_id, monster.get("combat"), "combat")
        if combat is not None:
            for key, value in combat.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    _issue(issues, "error", "monsters", monster_id, f"combat.{key} 必須是數字")

    # 物品種類與裝備欄索引。
    for slot_id, slot in equipment_slots.items():
        order = slot.get("order")
        if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
            _issue(issues, "error", "equipment_slots", slot_id, "order 必須是整數")

    for kind_id, kind in item_kinds.items():
        actions_raw = _require_list(issues, "item_kinds", kind_id, kind.get("allowed_actions"), "allowed_actions")
        required_raw = _require_list(issues, "item_kinds", kind_id, kind.get("required_fields"), "required_fields")
        slots_raw = _require_list(issues, "item_kinds", kind_id, kind.get("allowed_slots"), "allowed_slots")

        actions: set[str] = set()
        for action in actions_raw or []:
            if not isinstance(action, str):
                _issue(issues, "error", "item_kinds", kind_id, "allowed_actions 只能包含字串 ID")
            elif action not in ITEM_ACTION_CATALOG:
                _issue(issues, "error", "item_kinds", kind_id, f"未知的允許操作：{action}")
            elif action in actions:
                _issue(issues, "warning", "item_kinds", kind_id, f"allowed_actions 重複：{action}")
            actions.add(action)

        required: set[str] = set()
        for field_name in required_raw or []:
            if not isinstance(field_name, str):
                _issue(issues, "error", "item_kinds", kind_id, "required_fields 只能包含字串 ID")
            elif field_name not in ITEM_FIELD_CATALOG:
                _issue(issues, "error", "item_kinds", kind_id, f"未知的必填 Item 欄位：{field_name}")
            elif field_name in required:
                _issue(issues, "warning", "item_kinds", kind_id, f"required_fields 重複：{field_name}")
            required.add(field_name)

        for action_id, fields in ACTION_FIELD_HINTS.items():
            conflicting = required.intersection(fields)
            if conflicting and action_id not in actions:
                _issue(
                    issues,
                    "error",
                    "item_kinds",
                    kind_id,
                    f"必填欄位 {', '.join(sorted(conflicting))} 需要允許操作 {action_id}",
                )

        allowed_slots: set[str] = set()
        for slot_id in slots_raw or []:
            if not isinstance(slot_id, str):
                _issue(issues, "error", "item_kinds", kind_id, "allowed_slots 只能包含字串 ID")
            elif slot_id not in equipment_slots:
                _issue(issues, "error", "item_kinds", kind_id, f"allowed_slots 引用了未定義 slot：{slot_id}")
            allowed_slots.add(str(slot_id))
        if allowed_slots and "equip" not in actions:
            _issue(issues, "error", "item_kinds", kind_id, "設定 allowed_slots 時必須允許 equip")

        stackable = kind.get("stackable", False)
        if not isinstance(stackable, bool):
            _issue(issues, "error", "item_kinds", kind_id, "stackable 必須是布林值")
        default_max_stack = kind.get("default_max_stack")
        if default_max_stack is not None:
            if not isinstance(default_max_stack, int) or isinstance(default_max_stack, bool) or default_max_stack <= 0:
                _issue(issues, "error", "item_kinds", kind_id, "default_max_stack 必須是正整數")
            if stackable is not True:
                _issue(issues, "error", "item_kinds", kind_id, "不可堆疊的 Kind 不能設定 default_max_stack")
        if stackable is True and default_max_stack is None:
            _issue(issues, "warning", "item_kinds", kind_id, "可堆疊 Kind 尚未設定 default_max_stack")

    # Item 的種類、裝備欄與戰鬥 tags。
    for item_id, item in items.items():
        kind = item.get("kind")
        if kind and not isinstance(kind, str):
            _issue(issues, "error", "items", item_id, "kind 必須是字串 ID")
        elif kind and kind not in item_kinds:
            _issue(issues, "error", "items", item_id, f"引用了未定義 kind：{kind}")
        slot = item.get("slot")
        if slot and not isinstance(slot, str):
            _issue(issues, "error", "items", item_id, "slot 必須是字串 ID")
        elif slot and slot not in equipment_slots:
            _issue(issues, "error", "items", item_id, f"引用了未定義 equipment slot：{slot}")

        kind_meta = item_kinds.get(kind, {}) if isinstance(kind, str) else {}
        actions = kind_actions(kind_meta)
        required_fields = kind_required_fields(kind_meta)
        allowed_slots = kind_allowed_slots(kind_meta)
        for field_name in sorted(required_fields):
            if not field_has_value(item, field_name):
                _issue(issues, "error", "items", item_id, f"Kind {kind!r} 要求必填欄位：{field_name}")
        if slot and "equip" not in actions:
            _issue(issues, "error", "items", item_id, f"Kind {kind!r} 未允許 equip，不能設定 slot")
        if item.get("bonuses") and "equip" not in actions:
            _issue(issues, "error", "items", item_id, f"Kind {kind!r} 未允許 equip，不能設定 bonuses")
        if item.get("simple_use") and "use" not in actions:
            _issue(issues, "error", "items", item_id, f"Kind {kind!r} 未允許 use，不能設定 simple_use")
        if item.get("uses") and "target_use" not in actions:
            _issue(issues, "error", "items", item_id, f"Kind {kind!r} 未允許 target_use，不能設定 uses")
        if slot and allowed_slots and slot not in allowed_slots:
            _issue(issues, "error", "items", item_id, f"Kind {kind!r} 不允許裝備於 slot：{slot}")

        max_stack = item.get("max_stack")
        if max_stack is not None:
            if not isinstance(max_stack, int) or isinstance(max_stack, bool) or max_stack <= 0:
                _issue(issues, "error", "items", item_id, "max_stack 必須是正整數")
            if not bool(kind_meta.get("stackable", False)):
                _issue(issues, "error", "items", item_id, f"Kind {kind!r} 不可堆疊，不能設定 max_stack")

        item_tags = _require_list(issues, "items", item_id, item.get("tags"), "tags")
        if item_tags is not None:
            for tag_id in item_tags:
                if not isinstance(tag_id, str):
                    _issue(issues, "error", "items", item_id, "tags 只能包含字串 ID")
                elif tag_id not in tags:
                    # 現有資料可能含尚未集中定義的裝備特徵；先警告，不鎖死編輯。
                    _issue(issues, "warning", "items", item_id, f"引用了未定義戰鬥 tag：{tag_id}")

        bonuses = _require_mapping(issues, "items", item_id, item.get("bonuses"), "bonuses")
        if bonuses is not None:
            for bonus_key, value in bonuses.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    _issue(issues, "error", "items", item_id, f"bonuses.{bonus_key} 必須是數字")

        simple_use = _require_mapping(issues, "items", item_id, item.get("simple_use"), "simple_use")
        if simple_use is not None:
            for delta_key in ("hp_delta", "mp_delta", "gold_delta"):
                value = simple_use.get(delta_key)
                if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                    _issue(issues, "error", "items", item_id, f"simple_use.{delta_key} 必須是整數")
            consume = simple_use.get("consume")
            if consume is not None and not isinstance(consume, bool):
                _issue(issues, "error", "items", item_id, "simple_use.consume 必須是布林值")
            reward_item = simple_use.get("reward_item")
            if reward_item and reward_item not in items:
                _issue(issues, "error", "items", item_id, f"simple_use.reward_item 不存在：{reward_item}")

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

        encounters = _require_mapping(issues, "rooms", room_id, room.get("encounters"), "encounters")
        if encounters:
            rate = encounters.get("rate")
            if rate is not None and (not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0 <= rate <= 1):
                _issue(issues, "error", "rooms", room_id, "encounters.rate 必須是 0–1 的數字")
            pool = _require_list(issues, "rooms", room_id, encounters.get("pool"), "encounters.pool") or []
            seen_monsters: set[str] = set()
            for index, entry in enumerate(pool, start=1):
                if not isinstance(entry, list) or len(entry) != 2:
                    _issue(issues, "error", "rooms", room_id, f"encounters.pool 第 {index} 筆必須是 [monster_id, weight]")
                    continue
                monster_id, weight = entry
                if monster_id not in monsters:
                    _issue(issues, "error", "rooms", room_id, f"encounters.pool 引用不存在 monster：{monster_id}")
                if monster_id in seen_monsters:
                    _issue(issues, "warning", "rooms", room_id, f"encounters.pool 重複 monster：{monster_id}")
                seen_monsters.add(str(monster_id))
                if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
                    _issue(issues, "error", "rooms", room_id, f"encounters.pool 第 {index} 筆權重必須是正整數")

    # NPC 社交、位置、送禮引用。
    for npc_id, npc in npcs.items():
        for role_id in _require_list(issues, "npcs", npc_id, npc.get("roles"), "roles") or []:
            if role_id not in roles:
                _issue(issues, "error", "npcs", npc_id, f"引用了未定義 role：{role_id}")
        for tag_id in _require_list(issues, "npcs", npc_id, npc.get("tags"), "tags") or []:
            if tag_id not in tags:
                _issue(issues, "warning", "npcs", npc_id, f"引用了未定義戰鬥 tag：{tag_id}")
        species_id = npc.get("species")
        if species_id and species_id not in species:
            _issue(issues, "error", "npcs", npc_id, f"引用了未定義 species：{species_id}")
        for skill_id in _require_list(issues, "npcs", npc_id, npc.get("skills"), "skills") or []:
            if skill_id not in skills:
                _issue(issues, "error", "npcs", npc_id, f"引用了不存在 skill：{skill_id}")

        topics = _require_mapping(issues, "npcs", npc_id, npc.get("topics"), "topics")
        if topics is not None:
            for topic_id, topic in topics.items():
                if not isinstance(topic, Mapping):
                    _issue(issues, "error", "npcs", npc_id, f"topics.{topic_id} 必須是 object")
                    continue
                effects = _require_list(issues, "npcs", npc_id, topic.get("effects"), f"topics.{topic_id}.effects") or []
                for index, effect in enumerate(effects, start=1):
                    if not isinstance(effect, Mapping):
                        _issue(issues, "error", "npcs", npc_id, f"topics.{topic_id}.effects 第 {index} 筆必須是 object")
                        continue
                    if effect.get("type") == "quest_accept":
                        quest_id = effect.get("quest_id")
                        if quest_id not in quests:
                            _issue(issues, "error", "npcs", npc_id, f"topics.{topic_id} 引用不存在 quest：{quest_id}")

        for field_name in ("attr", "stats", "combat"):
            values = _require_mapping(issues, "npcs", npc_id, npc.get(field_name), field_name)
            if values is not None:
                for key, value in values.items():
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        _issue(issues, "error", "npcs", npc_id, f"{field_name}.{key} 必須是數字")

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

    # Quest 前置條件、目標與獎勵。
    quest_requires: dict[str, list[str]] = {}
    for quest_id, quest in quests.items():
        requires = _require_list(issues, "quests", quest_id, quest.get("requires"), "requires") or []
        quest_requires[quest_id] = []
        for required_id in requires:
            if not isinstance(required_id, str):
                _issue(issues, "error", "quests", quest_id, "requires 只能包含字串 quest ID")
            elif required_id == quest_id:
                _issue(issues, "error", "quests", quest_id, "任務不能把自己設為前置任務")
            elif required_id not in quests:
                _issue(issues, "error", "quests", quest_id, f"requires 引用不存在 quest：{required_id}")
            else:
                quest_requires[quest_id].append(required_id)

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
            elif task_type == "defeat_monster":
                target = task.get("target")
                if target not in monsters:
                    _issue(issues, "error", "quests", quest_id, f"第 {index} 個討伐目標引用不存在 monster：{target}")

        rewards = _require_list(issues, "quests", quest_id, quest.get("rewards"), "rewards") or []
        for index, reward in enumerate(rewards, start=1):
            if not isinstance(reward, Mapping):
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個 reward 必須是 object")
                continue
            if reward.get("type") == "item" and reward.get("item_id") not in items:
                _issue(issues, "error", "quests", quest_id, f"第 {index} 個獎勵引用不存在 item：{reward.get('item_id')}")

    # 前置任務循環會造成永遠無法接受，視為錯誤。
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(quest_id: str, path: list[str]) -> None:
        if quest_id in visited:
            return
        if quest_id in visiting:
            cycle_start = path.index(quest_id) if quest_id in path else 0
            cycle = path[cycle_start:] + [quest_id]
            _issue(issues, "error", "quests", quest_id, "前置任務形成循環：" + " → ".join(cycle))
            return
        visiting.add(quest_id)
        path.append(quest_id)
        for required_id in quest_requires.get(quest_id, []):
            visit(required_id, path)
        path.pop()
        visiting.remove(quest_id)
        visited.add(quest_id)

    for quest_id in quests:
        visit(quest_id, [])

    return issues


def errors_only(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity == "error"]
