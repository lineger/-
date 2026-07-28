import os, json, glob
from typing import Dict, Any, List


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        start = max(0, e.pos - 60)
        end   = min(len(text), e.pos + 60)
        snippet = text[start:end].replace("\n", "\\n")
        print(f"[JSON ERROR] {path}:{e.lineno}:{e.colno} pos={e.pos}")
        print(f"...{snippet}...")
        raise

def _as_dict_by_id(data: Any, *, key_name: str | None = None) -> Dict[str, Any]:
    """
    把多種可能的格式轉成 {id: obj}：
    - { "<id>": {...}, ... }
    - [ {"id": "...", ...}, {"id":"...", ...} ]
    - { "<key_name>": { "<id>": {...} } }  (例如 {"rooms": {...}})
    - { "<key_name>": [ {"id": "..."} ] }
    """
    # 指定 key_name 時，先取子欄位
    if key_name and isinstance(data, dict) and key_name in data:
        data = data[key_name]

    # 已經是 {id: obj}
    if isinstance(data, dict):
        # 若每個 value 都有 id，就複製一份保證 id 存在
        if all(isinstance(v, dict) for v in data.values()):
            return {k: {**v, "id": v.get("id", k)} for k, v in data.items()}
        return data  # 其他情況就原樣回傳（容錯）

    # 若是 list，轉成 {id: obj}
    if isinstance(data, list):
        out: Dict[str, Any] = {}
        for obj in data:
            if not isinstance(obj, dict) or "id" not in obj:
                raise ValueError("列表中的物件缺少 'id' 欄位")
            out[obj["id"]] = obj
        return out

    raise ValueError("不支援的集合格式")

def _load_collection(path_or_dir: str, *, key_name: str | None = None) -> Dict[str, Any]:
    """
    兼容：
    - 目錄：讀取 *.json，逐檔轉 {id: obj} 後合併
    - 檔案：支援多種包裝（見 _as_dict_by_id）
    """
    if os.path.isdir(path_or_dir):
        out: Dict[str, Any] = {}
        for p in glob.glob(os.path.join(path_or_dir, "*.json")):
            data = _read_json(p)
            # 單檔可能是單一物件（包含 id）或小集合
            if isinstance(data, dict) and "id" in data:
                out[data["id"]] = data
            else:
                out.update(_as_dict_by_id(data, key_name=key_name))
        return out

    if os.path.isfile(path_or_dir):
        data = _read_json(path_or_dir)
        return _as_dict_by_id(data, key_name=key_name)

    raise FileNotFoundError(path_or_dir)

def _merge_events_dict(dst: Dict[str, Any], src: Any, *, key_name: str | None):
    """
    將不同格式的事件資料合併到 dst（最終要成為 {event_id: def}）。
    允許：
    - {"events": { "E1": {...}, ... }}
    - {"events": [ {"id":"E1", ...}, ... ]}
    - 直接 { "E1": {...}, ... }
    - 或 [ {"id":"E1", ...}, ... ]
    """
    # 若指定 key_name（通常是 "events"），先取子欄位
    if key_name and isinstance(src, dict) and key_name in src:
        src = src[key_name]

    # 直接是 dict（id: def）
    if isinstance(src, dict):
        # 若值沒有 id，也可直接用 key 當 id
        for k, v in src.items():
            if isinstance(v, dict) and "id" not in v:
                v = {**v, "id": k}
            dst[k] = v
        return

    # 是 list（每個元素需帶 id）
    if isinstance(src, list):
        for obj in src:
            if not isinstance(obj, dict) or "id" not in obj:
                raise ValueError("事件列表的元素缺少 'id'")
            dst[obj["id"]] = obj
        return

    raise ValueError("不支援的事件格式")

def _load_events(path_or_dir: str) -> Dict[str, Any]:
    """
    兼容：
    - 目錄：合併該目錄下的所有 *.json（每檔可含 "events" 或直接就是事件映射/列表）
    - 檔案：支援上面所有事件格式
    """
    merged: Dict[str, Any] = {}
    if os.path.isdir(path_or_dir):
        for p in glob.glob(os.path.join(path_or_dir, "*.json")):
            data = _read_json(p)
            _merge_events_dict(merged, data, key_name="events")
        return merged

    if os.path.isfile(path_or_dir):
        data = _read_json(path_or_dir)
        _merge_events_dict(merged, data, key_name="events")
        return merged

    raise FileNotFoundError(path_or_dir)



def _validate_role_references(roles: Dict[str, Any], npcs: Dict[str, Any], quests: Dict[str, Any]) -> None:
    """驗證社交 role 的集中定義與引用關係。"""
    for npc_id, npc in npcs.items():
        npc_roles = npc.get("roles", [])
        if not isinstance(npc_roles, list) or any(not isinstance(role_id, str) or not role_id for role_id in npc_roles):
            raise ValueError(f"NPC {npc_id!r} 的 roles 必須是非空字串列表")
        unknown = sorted(set(npc_roles) - set(roles))
        if unknown:
            raise ValueError(f"NPC {npc_id!r} 引用了未定義 role：{', '.join(unknown)}")

    for quest_id, quest in quests.items():
        for index, task in enumerate(quest.get("tasks", [])):
            if task.get("type") != "deliver_item":
                continue

            target_npc = task.get("target_npc")
            target_role = task.get("target_role")
            if target_npc and target_role:
                raise ValueError(
                    f"任務 {quest_id!r} 的第 {index + 1} 個 deliver_item "
                    "不能同時指定 target_npc 與 target_role"
                )
            if target_npc and target_npc not in npcs:
                raise ValueError(
                    f"任務 {quest_id!r} 引用了不存在的 target_npc：{target_npc!r}"
                )
            if target_role and target_role not in roles:
                raise ValueError(
                    f"任務 {quest_id!r} 引用了未定義 target_role：{target_role!r}"
                )


def _validate_item_indexes(
    item_kinds: Dict[str, Any],
    equipment_slots: Dict[str, Any],
    items: Dict[str, Any],
) -> None:
    """驗證物品 kind 契約、裝備 slot 與 Item 欄位的一致性。"""
    known_actions = {"equip", "use", "target_use", "gift", "deliver", "trade"}
    known_required_fields = {"slot", "bonuses", "simple_use", "uses", "tags", "max_stack"}

    for slot_id, slot in equipment_slots.items():
        order = slot.get("order")
        if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
            raise ValueError(f"equipment slot {slot_id!r} 的 order 必須是整數")

    for kind_id, kind in item_kinds.items():
        actions = kind.get("allowed_actions", [])
        required_fields = kind.get("required_fields", [])
        allowed_slots = kind.get("allowed_slots", [])
        if not isinstance(actions, list) or not all(isinstance(value, str) for value in actions):
            raise ValueError(f"Item kind {kind_id!r} 的 allowed_actions 必須是字串列表")
        if not isinstance(required_fields, list) or not all(isinstance(value, str) for value in required_fields):
            raise ValueError(f"Item kind {kind_id!r} 的 required_fields 必須是字串列表")
        if not isinstance(allowed_slots, list) or not all(isinstance(value, str) for value in allowed_slots):
            raise ValueError(f"Item kind {kind_id!r} 的 allowed_slots 必須是字串列表")
        unknown_actions = sorted(set(actions) - known_actions)
        if unknown_actions:
            raise ValueError(f"Item kind {kind_id!r} 含未知 allowed_actions：{', '.join(unknown_actions)}")
        unknown_fields = sorted(set(required_fields) - known_required_fields)
        if unknown_fields:
            raise ValueError(f"Item kind {kind_id!r} 含未知 required_fields：{', '.join(unknown_fields)}")
        unknown_slots = sorted(set(allowed_slots) - set(equipment_slots))
        if unknown_slots:
            raise ValueError(f"Item kind {kind_id!r} 引用了未定義 slot：{', '.join(unknown_slots)}")
        if allowed_slots and "equip" not in actions:
            raise ValueError(f"Item kind {kind_id!r} 設定 allowed_slots 時必須允許 equip")
        if set(required_fields).intersection({"slot", "bonuses"}) and "equip" not in actions:
            raise ValueError(f"Item kind {kind_id!r} 的裝備必填欄位需要允許 equip")
        if "simple_use" in required_fields and "use" not in actions:
            raise ValueError(f"Item kind {kind_id!r} 的 simple_use 必填欄位需要允許 use")
        if "uses" in required_fields and "target_use" not in actions:
            raise ValueError(f"Item kind {kind_id!r} 的 uses 必填欄位需要允許 target_use")
        stackable = kind.get("stackable", False)
        if not isinstance(stackable, bool):
            raise ValueError(f"Item kind {kind_id!r} 的 stackable 必須是布林值")
        default_max_stack = kind.get("default_max_stack")
        if default_max_stack is not None:
            if not isinstance(default_max_stack, int) or isinstance(default_max_stack, bool) or default_max_stack <= 0:
                raise ValueError(f"Item kind {kind_id!r} 的 default_max_stack 必須是正整數")
            if not stackable:
                raise ValueError(f"Item kind {kind_id!r} 不可堆疊時不能設定 default_max_stack")

    def has_value(item: Dict[str, Any], field_name: str) -> bool:
        if field_name not in item:
            return False
        value = item.get(field_name)
        if value is None or value == "":
            return False
        if isinstance(value, (list, dict, tuple, set)):
            return bool(value)
        return True

    for item_id, item in items.items():
        kind = item.get("kind")
        if kind and not isinstance(kind, str):
            raise ValueError(f"Item {item_id!r} 的 kind 必須是字串 ID")
        if kind and kind not in item_kinds:
            raise ValueError(f"Item {item_id!r} 引用了未定義 kind：{kind!r}")
        slot = item.get("slot")
        if slot and not isinstance(slot, str):
            raise ValueError(f"Item {item_id!r} 的 slot 必須是字串 ID")
        if slot and slot not in equipment_slots:
            raise ValueError(f"Item {item_id!r} 引用了未定義 equipment slot：{slot!r}")

        kind_meta = item_kinds.get(kind, {}) if isinstance(kind, str) else {}
        actions = set(kind_meta.get("allowed_actions", []))
        required_fields = set(kind_meta.get("required_fields", []))
        allowed_slots = set(kind_meta.get("allowed_slots", []))
        for field_name in required_fields:
            if not has_value(item, field_name):
                raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 要求欄位 {field_name!r}")
        if slot and "equip" not in actions:
            raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 未允許 equip，不能設定 slot")
        if item.get("bonuses") and "equip" not in actions:
            raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 未允許 equip，不能設定 bonuses")
        if item.get("simple_use") and "use" not in actions:
            raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 未允許 use，不能設定 simple_use")
        if item.get("uses") and "target_use" not in actions:
            raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 未允許 target_use，不能設定 uses")
        if slot and allowed_slots and slot not in allowed_slots:
            raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 不允許 slot {slot!r}")
        max_stack = item.get("max_stack")
        if max_stack is not None:
            if not isinstance(max_stack, int) or isinstance(max_stack, bool) or max_stack <= 0:
                raise ValueError(f"Item {item_id!r} 的 max_stack 必須是正整數")
            if not bool(kind_meta.get("stackable", False)):
                raise ValueError(f"Item {item_id!r} 的 kind {kind!r} 不可堆疊，不能設定 max_stack")


def load_world(base="../data/beginner"):
    """
    自動偵測兩種布局：
    1) 目錄多檔：base/rooms/*.json, base/npcs/*.json, base/items/*.json, base/events/*.json
    2) 單一合併檔：base/rooms.json, base/npcs.json, base/items.json, base/events.json 或 base/events/book.json
    """
    # matrix
    tags_path = os.path.join(base, "tags")
    if not os.path.exists(tags_path):
        tags_path = os.path.join(base, "tags.json")    
    tags = _load_collection(tags_path, key_name="tags")

    # social roles（與戰鬥 tags 平行，但資料與用途完全分離）
    roles_path = os.path.join(base, "roles")
    if not os.path.exists(roles_path):
        roles_path = os.path.join(base, "roles.json")
    roles = _load_collection(roles_path, key_name="roles")

    # item kinds 與 equipment slots：提供編輯器與裝備系統共用的資料索引
    item_kinds_path = os.path.join(base, "item_kinds")
    if not os.path.exists(item_kinds_path):
        item_kinds_path = os.path.join(base, "item_kinds.json")
    item_kinds = _load_collection(item_kinds_path, key_name="item_kinds")

    equipment_slots_path = os.path.join(base, "equipment_slots")
    if not os.path.exists(equipment_slots_path):
        equipment_slots_path = os.path.join(base, "equipment_slots.json")
    equipment_slots = _load_collection(equipment_slots_path, key_name="equipment_slots")

    # status_effects
    status_effects_path = os.path.join(base, "status_effects.json")
    status_effects = _read_json(status_effects_path).get("status_effects", {})

    # rooms
    rooms_path = os.path.join(base, "rooms")
    if not os.path.exists(rooms_path):
        rooms_path = os.path.join(base, "rooms.json")
    rooms = _load_collection(rooms_path, key_name="rooms")

    # npcs
    npcs_path = os.path.join(base, "npcs")
    if not os.path.exists(npcs_path):
        npcs_path = os.path.join(base, "npcs")
    npcs = _load_collection(npcs_path, key_name="npcs")

    # monsters
    monsters_path = os.path.join(base, "monsters")
    if not os.path.exists(monsters_path):
        monsters_path = os.path.join(base, "monsters.json")
    monsters = _load_collection(monsters_path, key_name="monsters")

    # items
    items_path = os.path.join(base, "items")
    if not os.path.exists(items_path):
        items_path = os.path.join(base, "items.json")
    items = _load_collection(items_path, key_name="items")

    # skills
    skills_path = os.path.join(base, "skills")
    if not os.path.exists(skills_path):
        skills_path = os.path.join(base, "skills.json")
    skills = _load_collection(skills_path, key_name="skills")

    # quests
    quests_path = os.path.join(base, "quests")
    if not os.path.exists(quests_path):
        quests_path = os.path.join(base, "quests.json")
    quests = _load_collection(quests_path, key_name="quests")
    

    # events
    events_path = os.path.join(base, "events")
    if not os.path.exists(events_path):
        # 允許 events.json 或 events/book.json
        alt = os.path.join(base, "events.json")
        events_path = alt if os.path.exists(alt) else os.path.join(base, "events", "book.json")
    events = _load_events(events_path)

    _validate_role_references(roles, npcs, quests)
    _validate_item_indexes(item_kinds, equipment_slots, items)

    return {
        "rooms": rooms,
        "npcs": npcs,
        "monsters": monsters,
        "items": items,
        "quests": quests,
        "skills": skills,
        "status_effects": status_effects,
        "tags": tags,
        "roles": roles,
        "item_kinds": item_kinds,
        "equipment_slots": equipment_slots,
    }, events
