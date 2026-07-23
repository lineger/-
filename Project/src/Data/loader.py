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

    return {"rooms": rooms, "npcs": npcs, "monsters": monsters, "items": items, "quests": quests, "skills": skills, "status_effects":status_effects, "tags": tags}, events
