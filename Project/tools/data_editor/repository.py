from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from validators import DataValidationError, errors_only, validate_database


@dataclass(frozen=True, slots=True)
class CategorySpec:
    path: str
    wrapper: str | None
    per_file: bool = False


CATEGORY_SPECS: dict[str, CategorySpec] = {
    "tags": CategorySpec("tags.json", "tags"),
    "roles": CategorySpec("roles.json", "roles"),
    "item_kinds": CategorySpec("item_kinds.json", "item_kinds"),
    "equipment_slots": CategorySpec("equipment_slots.json", "equipment_slots"),
    "items": CategorySpec("items.json", None),
    "rooms": CategorySpec("rooms.json", None),
    "npcs": CategorySpec("npcs", None, per_file=True),
    "quests": CategorySpec("quests.json", "quests"),
}

FIELD_ORDER: dict[str, tuple[str, ...]] = {
    "tags": ("id", "name", "description", "multipliers", "on_hit_proc"),
    "roles": ("id", "name", "description"),
    "item_kinds": (
        "id", "name", "description", "allowed_actions", "required_fields",
        "stackable", "default_max_stack", "allowed_slots",
    ),
    "equipment_slots": ("id", "name", "description", "order"),
    "items": (
        "id", "name", "desc", "description", "kind", "slot", "bonuses", "tags",
        "max_stack", "simple_use", "uses", "events", "value",
    ),
    "rooms": (
        "id", "name", "desc", "description", "exits", "objects", "npcs", "items",
        "tags", "encounters", "events",
    ),
    "npcs": (
        "id", "name", "description", "aliases", "recruitable", "home_room", "default_room",
        "roles", "tags", "faction", "job", "level", "lvl", "attr", "stats", "equipment",
        "combat", "skills", "topics", "gifts", "trades", "schedule", "events",
    ),
    "quests": ("id", "name", "desc", "description", "tasks", "rewards"),
}

NESTED_ORDER: dict[str, tuple[str, ...]] = {
    "attr": ("STR", "INT", "CON", "DEX", "CHA", "LCK"),
    "stats": ("hp", "max_hp", "mp", "max_mp", "atk", "def", "def_", "matk", "mdef", "speed", "crit", "exp", "gold"),
    "combat": ("hp", "max_hp", "mp", "max_mp", "atk", "def", "def_", "matk", "mdef", "speed", "crit"),
    "equipment": ("weapon", "body", "offhand"),
    "bonuses": ("atk", "def", "def_", "matk", "mdef", "speed", "crit", "max_hp", "max_mp"),
    "simple_use": ("reply", "hp_delta", "mp_delta", "gold_delta", "reward_item", "consume"),
    "on_hit_proc": ("status", "chance"),
}

SET_LIKE_LIST_FIELDS = {"tags", "roles", "allowed_actions", "required_fields", "allowed_slots"}
SORTED_MAPPING_FIELDS = {"gifts", "multipliers"}


class ProjectDataRepository:
    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir).resolve()
        if not self.data_dir.is_dir():
            raise FileNotFoundError(f"資料目錄不存在：{self.data_dir}")

    def load_all(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {category: self.load_category(category) for category in CATEGORY_SPECS}

    def load_category(self, category: str) -> dict[str, dict[str, Any]]:
        spec = CATEGORY_SPECS[category]
        path = self.data_dir / spec.path
        if spec.per_file:
            out: dict[str, dict[str, Any]] = {}
            if not path.exists():
                return out
            for file_path in sorted(path.glob("*.json")):
                value = self._read_json(file_path)
                if not isinstance(value, dict) or not value.get("id"):
                    raise ValueError(f"NPC 檔案缺少 id：{file_path}")
                entity = deepcopy(value)
                out[str(entity["id"])] = entity
            return out

        raw = self._read_json(path)
        if spec.wrapper is not None:
            raw = raw.get(spec.wrapper, {}) if isinstance(raw, dict) else {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path} 必須是 object")

        out = {}
        for entity_id, entity in raw.items():
            if not isinstance(entity, dict):
                raise ValueError(f"{category}:{entity_id} 必須是 object")
            out[str(entity_id)] = {**deepcopy(entity), "id": entity.get("id", entity_id)}
        return out

    def validate(self, data: Mapping[str, Mapping[str, Any]] | None = None):
        return validate_database(data or self.load_all())

    def save_entity(
        self,
        category: str,
        entity: Mapping[str, Any],
        *,
        original_id: str | None = None,
    ) -> tuple[Path, list]:
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id:
            raise ValueError("ID 不可空白")
        if original_id and original_id != entity_id:
            raise ValueError("既有資料的 ID 不可直接改名；請使用複製建立新 ID，再刪除舊項目")

        data = self.load_all()
        category_data = data[category]
        category_data[entity_id] = deepcopy(dict(entity))
        issues = validate_database(data)
        errors = errors_only(issues)
        if errors:
            raise DataValidationError(errors)

        spec = CATEGORY_SPECS[category]
        if spec.per_file:
            path = self.data_dir / spec.path / f"{entity_id}.json"
            ordered = self._ordered_entity(category, category_data[entity_id], keep_id=True)
            self._atomic_write(path, ordered)
        else:
            path = self._write_category(category, category_data)
        return path, issues

    def delete_entity(self, category: str, entity_id: str) -> tuple[list[Path], list]:
        data = self.load_all()
        if entity_id not in data[category]:
            raise KeyError(entity_id)
        del data[category][entity_id]
        issues = validate_database(data)
        errors = errors_only(issues)
        if errors:
            raise DataValidationError(errors)

        paths: list[Path] = []
        spec = CATEGORY_SPECS[category]
        if spec.per_file:
            target = self.data_dir / spec.path / f"{entity_id}.json"
            if target.exists():
                self._backup_file(target)
                target.unlink()
                paths.append(target)
        else:
            paths.append(self._write_category(category, data[category]))
        return paths, issues

    def format_all(self) -> tuple[list[Path], list]:
        data = self.load_all()
        issues = validate_database(data)
        errors = errors_only(issues)
        if errors:
            raise DataValidationError(errors)
        paths = [self._write_category(category, entities) for category, entities in data.items()]
        return paths, issues

    def _write_category(self, category: str, entities: Mapping[str, Mapping[str, Any]]) -> Path:
        spec = CATEGORY_SPECS[category]
        path = self.data_dir / spec.path
        if spec.per_file:
            path.mkdir(parents=True, exist_ok=True)
            for entity_id in sorted(entities):
                entity = self._ordered_entity(category, entities[entity_id], keep_id=True)
                self._atomic_write(path / f"{entity_id}.json", entity)
            return path

        collection: OrderedDict[str, Any] = OrderedDict()
        for entity_id in sorted(entities):
            entity = self._ordered_entity(category, entities[entity_id], keep_id=False)
            collection[entity_id] = entity
        payload: Any = OrderedDict([(spec.wrapper, collection)]) if spec.wrapper else collection
        self._atomic_write(path, payload)
        return path

    def _ordered_entity(self, category: str, entity: Mapping[str, Any], *, keep_id: bool) -> OrderedDict:
        source = deepcopy(dict(entity))
        if not keep_id:
            source.pop("id", None)
        ordered = self._order_mapping(source, FIELD_ORDER.get(category, ()), parent_key=category)
        if keep_id and "id" not in ordered:
            ordered = OrderedDict([("id", entity.get("id")) , *ordered.items()])
        return ordered

    def _order_mapping(
        self,
        value: Mapping[str, Any],
        field_order: tuple[str, ...] = (),
        *,
        parent_key: str = "",
    ) -> OrderedDict:
        result: OrderedDict[str, Any] = OrderedDict()
        seen: set[str] = set()
        for key in field_order:
            if key in value:
                result[key] = self._normalize_value(key, value[key])
                seen.add(key)
        for key in value:
            if key in seen:
                continue
            result[key] = self._normalize_value(key, value[key])
        return result

    def _normalize_value(self, key: str, value: Any) -> Any:
        if isinstance(value, Mapping):
            keys = list(value.keys())
            if key in SORTED_MAPPING_FIELDS:
                keys = sorted(keys)
            order = NESTED_ORDER.get(key, ())
            if order:
                return self._order_mapping(value, order, parent_key=key)
            return OrderedDict((child_key, self._normalize_value(child_key, value[child_key])) for child_key in keys)
        if isinstance(value, list):
            normalized = [self._normalize_value(key, item) for item in value]
            if key in SET_LIKE_LIST_FIELDS and all(isinstance(item, str) for item in normalized):
                return sorted(dict.fromkeys(normalized))
            return normalized
        return value

    def _atomic_write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._backup_file(path)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        try:
            # 寫後再讀一次，確保生成內容仍是合法 JSON。
            json.loads(temp_path.read_text(encoding="utf-8"))
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _backup_file(self, path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        relative = path.relative_to(self.data_dir)
        backup = self.data_dir / ".editor_backups" / stamp / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        return backup

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
