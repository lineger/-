from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from repository import CATEGORY_SPECS, ProjectDataRepository
from validators import DataValidationError, ValidationIssue


CATEGORY_LABELS = {
    "tags": "戰鬥 Tags",
    "roles": "社交 Roles",
    "items": "Items",
    "rooms": "Rooms",
    "npcs": "NPCs",
    "quests": "Quests",
}
LABEL_TO_CATEGORY = {label: key for key, label in CATEGORY_LABELS.items()}


CATEGORY_FILTERS = {
    "tags": (("全部", ""), ("倍率目標", "multiplier_target")),
    "roles": (("全部", ""),),
    "items": (("全部", ""), ("戰鬥 Tag", "tags"), ("種類 kind", "kind"), ("裝備欄 slot", "slot")),
    "rooms": (("全部", ""), ("環境標籤", "tags"), ("固定 NPC", "npcs")),
    "npcs": (("全部", ""), ("戰鬥 Tag", "tags"), ("社交 Role", "roles"), ("預設房間", "home_room")),
    "quests": (
        ("全部", ""),
        ("任務類型", "task_type"),
        ("目標道具", "target_item"),
        ("收件 Role", "target_role"),
        ("收件 NPC", "target_npc"),
    ),
}


KNOWN_FIELDS = {
    "tags": {"id", "name", "description", "multipliers", "on_hit_proc"},
    "roles": {"id", "name", "description"},
    "items": {"id", "name", "desc", "description", "kind", "slot", "tags", "bonuses", "simple_use", "uses"},
    "rooms": {"id", "name", "desc", "description", "exits", "npcs", "items", "tags", "encounters"},
    "npcs": {
        "id", "name", "description", "aliases", "recruitable", "home_room", "default_room",
        "faction", "job", "level", "lvl", "tags", "roles", "attr", "stats", "equipment",
        "combat", "skills", "topics", "gifts",
    },
    "quests": {"id", "name", "desc", "description", "tasks", "rewards"},
}


class DataEditorApp(tk.Tk):
    def __init__(self, data_dir: str | Path):
        super().__init__()
        self.title("遊戲 JSON 資料編輯器")
        self.geometry("1380x850")
        self.minsize(1080, 680)

        self.repo = ProjectDataRepository(data_dir)
        self.data = self.repo.load_all()
        self.current_category = "npcs"
        self.current_id: str | None = None
        self.current_entity: dict[str, Any] = {}
        self.is_new = False
        self.widgets: dict[str, Any] = {}
        self.vars: dict[str, tk.Variable] = {}

        self._build_ui()
        self._reload_categories(select="NPCs")
        self._refresh_entity_filters(reset=True)
        self._load_entity_list()
        self._set_status(f"資料目錄：{self.repo.data_dir}")

    # ---------- UI skeleton ----------
    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill="x")
        for text, command in (
            ("新增", self._new_entity),
            ("複製", self._duplicate_entity),
            ("儲存", self._save_entity),
            ("刪除", self._delete_entity),
            ("重新載入", self._reload_all),
            ("驗證全部", self._validate_all),
            ("格式化全部", self._format_all),
            ("更新預覽", self._update_preview),
            ("切換資料目錄", self._choose_data_dir),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=3)

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        category_frame = ttk.Labelframe(main, text="資料類型", padding=6)
        self.category_list = tk.Listbox(category_frame, exportselection=False, width=18)
        self.category_list.pack(fill="both", expand=True)
        self.category_list.bind("<<ListboxSelect>>", self._on_category_selected)
        main.add(category_frame, weight=0)

        entity_frame = ttk.Labelframe(main, text="項目", padding=6)

        filter_bar = ttk.Frame(entity_frame)
        filter_bar.pack(fill="x", pady=(0, 6))
        self.search_var = tk.StringVar(value="")
        self.filter_field_var = tk.StringVar(value="全部")
        self.filter_value_var = tk.StringVar(value="")
        ttk.Label(filter_bar, text="搜尋").grid(row=0, column=0, sticky="w")
        search_entry = ttk.Entry(filter_bar, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0))
        ttk.Label(filter_bar, text="篩選").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.filter_field_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_field_var,
            state="readonly",
            width=13,
        )
        self.filter_field_combo.grid(row=1, column=1, sticky="ew", padx=(4, 4), pady=(4, 0))
        self.filter_value_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_value_var,
        )
        self.filter_value_combo.grid(row=1, column=2, sticky="ew", pady=(4, 0))
        ttk.Button(filter_bar, text="清除", command=self._clear_entity_filters).grid(
            row=1, column=3, padx=(4, 0), pady=(4, 0)
        )
        filter_bar.columnconfigure(2, weight=1)

        self.entity_tree = ttk.Treeview(entity_frame, columns=("id", "name"), show="headings", selectmode="browse")
        self.entity_tree.heading("id", text="ID")
        self.entity_tree.heading("name", text="名稱")
        self.entity_tree.column("id", width=180, anchor="w")
        self.entity_tree.column("name", width=180, anchor="w")
        entity_scroll = ttk.Scrollbar(entity_frame, orient="vertical", command=self.entity_tree.yview)
        self.entity_tree.configure(yscrollcommand=entity_scroll.set)
        self.entity_tree.pack(side="left", fill="both", expand=True)
        entity_scroll.pack(side="right", fill="y")
        self.entity_tree.bind("<<TreeviewSelect>>", self._on_entity_selected)
        search_entry.bind("<KeyRelease>", lambda _event: self._load_entity_list())
        self.filter_field_combo.bind("<<ComboboxSelected>>", self._on_filter_field_changed)
        self.filter_value_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_entity_list())
        self.filter_value_combo.bind("<KeyRelease>", lambda _event: self._load_entity_list())
        main.add(entity_frame, weight=1)

        right = ttk.Panedwindow(main, orient="vertical")
        main.add(right, weight=4)

        editor_frame = ttk.Labelframe(right, text="編輯表單", padding=4)
        self.form_canvas = tk.Canvas(editor_frame, highlightthickness=0)
        form_scroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self.form_canvas.yview)
        self.form_canvas.configure(yscrollcommand=form_scroll.set)
        self.form_inner = ttk.Frame(self.form_canvas, padding=8)
        self.form_window = self.form_canvas.create_window((0, 0), window=self.form_inner, anchor="nw")
        self.form_inner.bind("<Configure>", lambda _e: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", lambda e: self.form_canvas.itemconfigure(self.form_window, width=e.width))
        self.form_canvas.pack(side="left", fill="both", expand=True)
        form_scroll.pack(side="right", fill="y")
        right.add(editor_frame, weight=4)

        bottom_notebook = ttk.Notebook(right)
        preview_frame = ttk.Frame(bottom_notebook)
        issues_frame = ttk.Frame(bottom_notebook)
        bottom_notebook.add(preview_frame, text="JSON 預覽")
        bottom_notebook.add(issues_frame, text="驗證訊息")

        self.preview_text = tk.Text(preview_frame, height=12, wrap="none", font=("TkFixedFont", 10))
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.configure(state="disabled")

        self.issues_text = tk.Text(issues_frame, height=10, wrap="word")
        self.issues_text.pack(fill="both", expand=True)
        self.issues_text.configure(state="disabled")
        right.add(bottom_notebook, weight=1)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(6, 3)).pack(fill="x")

    # ---------- selection / reload ----------
    def _reload_categories(self, *, select: str | None = None) -> None:
        self.category_list.delete(0, tk.END)
        labels = list(CATEGORY_LABELS.values())
        for label in labels:
            self.category_list.insert(tk.END, label)
        chosen = labels.index(select) if select in labels else list(CATEGORY_LABELS).index(self.current_category)
        self.category_list.selection_set(chosen)
        self.category_list.activate(chosen)

    def _on_category_selected(self, _event=None) -> None:
        selected = self.category_list.curselection()
        if not selected:
            return
        label = self.category_list.get(selected[0])
        self.current_category = LABEL_TO_CATEGORY[label]
        self.current_id = None
        self.current_entity = {}
        self.is_new = False
        self._clear_entity_filters(reload=False)
        self._refresh_entity_filters(reset=True)
        self._load_entity_list()
        self._clear_form("請選擇項目，或按「新增」。")

    def _load_entity_list(self, *, select_id: str | None = None) -> None:
        self.entity_tree.delete(*self.entity_tree.get_children())
        entities = self.data.get(self.current_category, {})
        for entity_id in sorted(entities):
            entity = entities[entity_id]
            if not self._entity_matches_filters(entity_id, entity):
                continue
            name = entity.get("name", "")
            self.entity_tree.insert("", "end", iid=entity_id, values=(entity_id, name))
        if select_id and self.entity_tree.exists(select_id):
            self.entity_tree.selection_set(select_id)
            self.entity_tree.focus(select_id)
            self.entity_tree.see(select_id)
            self._load_entity(select_id)

    def _clear_entity_filters(self, *, reload: bool = True) -> None:
        if hasattr(self, "search_var"):
            self.search_var.set("")
        if hasattr(self, "filter_field_var"):
            self.filter_field_var.set("全部")
        if hasattr(self, "filter_value_var"):
            self.filter_value_var.set("")
        if reload and hasattr(self, "entity_tree"):
            self._refresh_entity_filters(reset=True)
            self._load_entity_list()

    def _refresh_entity_filters(self, *, reset: bool = False) -> None:
        specs = CATEGORY_FILTERS.get(self.current_category, (("全部", ""),))
        labels = [label for label, _key in specs]
        self.filter_field_combo.configure(values=labels)
        if reset or self.filter_field_var.get() not in labels:
            self.filter_field_var.set(labels[0])
            self.filter_value_var.set("")
        self._refresh_filter_values()

    def _on_filter_field_changed(self, _event=None) -> None:
        self.filter_value_var.set("")
        self._refresh_filter_values()
        self._load_entity_list()

    def _selected_filter_key(self) -> str:
        label = self.filter_field_var.get()
        for option_label, key in CATEGORY_FILTERS.get(self.current_category, (("全部", ""),)):
            if option_label == label:
                return key
        return ""

    def _refresh_filter_values(self) -> None:
        key = self._selected_filter_key()
        values: set[str] = set()
        if key:
            for entity in self.data.get(self.current_category, {}).values():
                values.update(self._entity_filter_values(entity, key))
        self.filter_value_combo.configure(values=sorted(values))
        self.filter_value_combo.configure(state="normal" if key else "disabled")

    def _entity_filter_values(self, entity: dict[str, Any], key: str) -> set[str]:
        if key == "multiplier_target":
            return {str(value) for value in (entity.get("multipliers") or {})}
        if key in {"task_type", "target_item", "target_role", "target_npc"}:
            task_key = {
                "task_type": "type",
                "target_item": "target",
                "target_role": "target_role",
                "target_npc": "target_npc",
            }[key]
            return {
                str(task.get(task_key))
                for task in (entity.get("tasks") or [])
                if isinstance(task, dict) and task.get(task_key) not in (None, "")
            }
        value = entity.get(key)
        if key == "home_room":
            value = entity.get("home_room") or entity.get("default_room")
        if isinstance(value, list):
            return {str(item) for item in value}
        if value in (None, ""):
            return set()
        return {str(value)}

    def _entity_matches_filters(self, entity_id: str, entity: dict[str, Any]) -> bool:
        query = self.search_var.get().strip().casefold()
        if query:
            searchable = json.dumps(
                {"id": entity_id, **entity},
                ensure_ascii=False,
                sort_keys=True,
            ).casefold()
            if query not in searchable:
                return False

        key = self._selected_filter_key()
        expected = self.filter_value_var.get().strip()
        if key and expected:
            return expected in self._entity_filter_values(entity, key)
        return True

    def _on_entity_selected(self, _event=None) -> None:
        selected = self.entity_tree.selection()
        if selected:
            self._load_entity(selected[0])

    def _load_entity(self, entity_id: str) -> None:
        self.current_id = entity_id
        self.current_entity = deepcopy(self.data[self.current_category][entity_id])
        self.is_new = False
        self._build_form(self.current_entity, id_editable=False)
        self._update_preview()

    def _reload_all(self) -> None:
        self.data = self.repo.load_all()
        self._load_entity_list(select_id=self.current_id)
        self._set_status("已從磁碟重新載入全部資料。")

    def _choose_data_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.repo.data_dir, title="選擇 data/beginner 資料目錄")
        if not selected:
            return
        try:
            self.repo = ProjectDataRepository(selected)
            self.data = self.repo.load_all()
        except Exception as exc:
            messagebox.showerror("無法載入", str(exc), parent=self)
            return
        self.current_id = None
        self._load_entity_list()
        self._clear_form("已切換資料目錄，請選擇項目。")
        self._set_status(f"資料目錄：{self.repo.data_dir}")

    # ---------- form primitives ----------
    def _clear_form(self, message: str = "") -> None:
        for child in self.form_inner.winfo_children():
            child.destroy()
        self.widgets.clear()
        self.vars.clear()
        if message:
            ttk.Label(self.form_inner, text=message).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._set_preview({})

    def _build_form(self, entity: dict[str, Any], *, id_editable: bool) -> None:
        self._clear_form()
        self.form_inner.columnconfigure(1, weight=1)
        row = 0
        row = self._add_entry(row, "id", "ID", entity.get("id", ""), readonly=not id_editable)

        category = self.current_category
        if category in {"tags", "roles"}:
            row = self._add_entry(row, "name", "顯示名稱", entity.get("name", ""))
            row = self._add_text(row, "description", "說明", entity.get("description", ""), height=3)
            if category == "tags":
                row = self._add_json(row, "multipliers", "傷害倍率", entity.get("multipliers", {}), expected=dict, height=5)
                row = self._add_json(row, "on_hit_proc", "命中效果", entity.get("on_hit_proc", {}), expected=dict, height=5)

        elif category == "items":
            row = self._add_entry(row, "name", "名稱", entity.get("name", ""))
            row = self._add_text(row, "desc", "描述", entity.get("desc", entity.get("description", "")), height=3)
            row = self._add_entry(row, "kind", "種類 kind", entity.get("kind", ""))
            row = self._add_entry(row, "slot", "裝備欄 slot", entity.get("slot", ""))
            row = self._add_multiselect(row, "tags", "戰鬥 Tags", self.data["tags"], entity.get("tags", []), height=6)
            row = self._add_json(row, "bonuses", "裝備加成", entity.get("bonuses", {}), expected=dict, height=5)
            row = self._add_json(row, "simple_use", "直接使用規則", entity.get("simple_use", {}), expected=dict, height=6)
            row = self._add_json(row, "uses", "指定目標使用規則", entity.get("uses", {}), expected=dict, height=6)

        elif category == "rooms":
            row = self._add_entry(row, "name", "名稱", entity.get("name", ""))
            row = self._add_text(row, "desc", "描述", entity.get("desc", entity.get("description", "")), height=3)
            exits_text = "\n".join(f"{direction} = {room_id}" for direction, room_id in (entity.get("exits") or {}).items())
            row = self._add_text(row, "exits", "出口（每行 direction = room_id）", exits_text, height=7)
            row = self._add_csv(row, "tags", "環境標籤", entity.get("tags", []))
            row = self._add_multiselect(row, "npcs", "固定 NPC", self.data["npcs"], entity.get("npcs", []), height=7)
            row = self._add_multiselect(row, "items", "房間物品", self.data["items"], entity.get("items", []), height=7)
            row = self._add_json(row, "encounters", "遭遇設定", entity.get("encounters", {}), expected=dict, height=7)

        elif category == "npcs":
            row = self._add_entry(row, "name", "名稱", entity.get("name", ""))
            row = self._add_text(row, "description", "描述", entity.get("description", ""), height=3)
            row = self._add_csv(row, "aliases", "別名", entity.get("aliases", []))
            row = self._add_bool(row, "recruitable", "可招募", bool(entity.get("recruitable", False)))
            room_value = entity.get("home_room", entity.get("default_room", ""))
            row = self._add_combo(row, "home_room", "預設房間", self.data["rooms"], room_value, allow_empty=True)
            row = self._add_multiselect(row, "tags", "戰鬥 Tags", self.data["tags"], entity.get("tags", []), height=6)
            row = self._add_multiselect(row, "roles", "社交 Roles", self.data["roles"], entity.get("roles", []), height=7)
            row = self._add_entry(row, "faction", "陣營", entity.get("faction", "-"))
            row = self._add_entry(row, "job", "職稱", entity.get("job", "-"))
            row = self._add_entry(row, "level", "等級", entity.get("level", entity.get("lvl", 1)))
            row = self._add_json(row, "attr", "六圍 attr", entity.get("attr", {}), expected=dict, height=7)
            row = self._add_json(row, "stats", "永久數值 stats", entity.get("stats", {}), expected=dict, height=7)
            row = self._add_json(row, "equipment", "裝備", entity.get("equipment", {}), expected=dict, height=6)
            row = self._add_json(row, "combat", "戰鬥資料", entity.get("combat", {}), expected=dict, height=6)
            row = self._add_json(row, "skills", "技能 ID 陣列", entity.get("skills", []), expected=list, height=5)
            row = self._add_json(row, "topics", "對話 Topics", entity.get("topics", {}), expected=dict, height=10)
            row = self._add_json(row, "gifts", "送禮規則", entity.get("gifts", {}), expected=dict, height=9)
            ttk.Button(self.form_inner, text="＋ 新增送禮規則", command=self._add_gift_rule).grid(row=row, column=1, sticky="w", padx=4, pady=(0, 8))
            row += 1

        elif category == "quests":
            row = self._add_entry(row, "name", "名稱", entity.get("name", ""))
            row = self._add_text(row, "desc", "描述", entity.get("desc", entity.get("description", "")), height=4)
            row = self._add_json(row, "tasks", "任務目標", entity.get("tasks", []), expected=list, height=12)
            ttk.Button(self.form_inner, text="＋ 新增 deliver_item 目標", command=self._add_delivery_task).grid(row=row, column=1, sticky="w", padx=4, pady=(0, 8))
            row += 1
            row = self._add_json(row, "rewards", "任務獎勵", entity.get("rewards", []), expected=list, height=9)

        extra = {key: value for key, value in entity.items() if key not in KNOWN_FIELDS[category]}
        self._add_json(row, "__extra__", "其他／尚未表單化欄位", extra, expected=dict, height=7)

    def _add_entry(self, row: int, key: str, label: str, value: Any, *, readonly: bool = False) -> int:
        ttk.Label(self.form_inner, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        var = tk.StringVar(value="" if value is None else str(value))
        entry = ttk.Entry(self.form_inner, textvariable=var)
        if readonly:
            entry.configure(state="readonly")
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.vars[key] = var
        self.widgets[key] = entry
        return row + 1

    def _add_text(self, row: int, key: str, label: str, value: str, *, height: int) -> int:
        ttk.Label(self.form_inner, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        text = tk.Text(self.form_inner, height=height, wrap="word")
        text.insert("1.0", value or "")
        text.grid(row=row, column=1, sticky="nsew", padx=4, pady=4)
        self.widgets[key] = text
        return row + 1

    def _add_json(self, row: int, key: str, label: str, value: Any, *, expected: type, height: int) -> int:
        row = self._add_text(row, key, label, json.dumps(value, ensure_ascii=False, indent=2), height=height)
        self.widgets[key].expected_json_type = expected
        return row

    def _add_csv(self, row: int, key: str, label: str, values: list[str]) -> int:
        return self._add_entry(row, key, label + "（逗號分隔）", ", ".join(values or []))

    def _add_bool(self, row: int, key: str, label: str, value: bool) -> int:
        ttk.Label(self.form_inner, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        var = tk.BooleanVar(value=value)
        ttk.Checkbutton(self.form_inner, variable=var).grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.vars[key] = var
        return row + 1

    def _add_combo(
        self,
        row: int,
        key: str,
        label: str,
        choices: dict[str, dict[str, Any]],
        value: str,
        *,
        allow_empty: bool,
    ) -> int:
        ttk.Label(self.form_inner, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        values = ([""] if allow_empty else []) + sorted(choices)
        var = tk.StringVar(value=value or "")
        combo = ttk.Combobox(self.form_inner, textvariable=var, values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.vars[key] = var
        self.widgets[key] = combo
        return row + 1

    def _add_multiselect(
        self,
        row: int,
        key: str,
        label: str,
        choices: dict[str, dict[str, Any]],
        selected: list[str],
        *,
        height: int,
    ) -> int:
        ttk.Label(self.form_inner, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        frame = ttk.Frame(self.form_inner)
        frame.grid(row=row, column=1, sticky="nsew", padx=4, pady=4)

        filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(frame, textvariable=filter_var)
        filter_entry.pack(fill="x", pady=(0, 4))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(list_frame, selectmode="multiple", exportselection=False, height=height)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        all_ids = sorted(set(choices) | set(selected or []))
        listbox.all_choices = {choice_id: choices.get(choice_id, {}) for choice_id in all_ids}
        listbox.selected_ids = set(selected or [])
        listbox.choice_ids = []

        def sync_visible_selection(_event=None) -> None:
            visible_ids = set(listbox.choice_ids)
            listbox.selected_ids.difference_update(visible_ids)
            for index in listbox.curselection():
                listbox.selected_ids.add(listbox.choice_ids[index])

        def refresh_choices(_event=None) -> None:
            sync_visible_selection()
            query = filter_var.get().strip().casefold()
            visible: list[str] = []
            for choice_id in all_ids:
                choice = listbox.all_choices[choice_id]
                haystack = json.dumps(
                    {"id": choice_id, **choice},
                    ensure_ascii=False,
                    sort_keys=True,
                ).casefold()
                if query and query not in haystack:
                    continue
                visible.append(choice_id)

            listbox.delete(0, tk.END)
            listbox.choice_ids = visible
            for index, choice_id in enumerate(visible):
                choice = listbox.all_choices[choice_id]
                name = choice.get("name", "")
                if choice_id not in choices:
                    label_text = f"{choice_id} — ⚠ 未定義"
                else:
                    label_text = f"{choice_id} — {name}" if name else choice_id
                listbox.insert(tk.END, label_text)
                if choice_id in listbox.selected_ids:
                    listbox.selection_set(index)

        listbox.sync_selection = sync_visible_selection
        listbox.refresh_choices = refresh_choices
        listbox.filter_var = filter_var
        listbox.bind("<<ListboxSelect>>", sync_visible_selection)
        filter_entry.bind("<KeyRelease>", refresh_choices)
        refresh_choices()
        self.widgets[key] = listbox
        return row + 1

    # ---------- collect / preview ----------
    def _collect_entity(self) -> dict[str, Any]:
        category = self.current_category
        entity = deepcopy(self.current_entity) if not self.is_new else {}
        entity["id"] = self._string_var("id", required=True)

        if category in {"tags", "roles"}:
            self._set_optional(entity, "name", self._string_var("name"))
            self._set_optional(entity, "description", self._text("description"))
            if category == "tags":
                self._set_optional(entity, "multipliers", self._json("multipliers", dict))
                self._set_optional(entity, "on_hit_proc", self._json("on_hit_proc", dict))

        elif category == "items":
            self._set_optional(entity, "name", self._string_var("name"))
            self._set_optional(entity, "desc", self._text("desc"))
            entity.pop("description", None)
            self._set_optional(entity, "kind", self._string_var("kind"))
            self._set_optional(entity, "slot", self._string_var("slot"))
            self._set_optional(entity, "tags", self._multiselect("tags"))
            self._set_optional(entity, "bonuses", self._json("bonuses", dict))
            self._set_optional(entity, "simple_use", self._json("simple_use", dict))
            self._set_optional(entity, "uses", self._json("uses", dict))

        elif category == "rooms":
            self._set_optional(entity, "name", self._string_var("name"))
            self._set_optional(entity, "desc", self._text("desc"))
            entity.pop("description", None)
            self._set_optional(entity, "exits", self._parse_exits(self._text("exits")))
            self._set_optional(entity, "tags", self._csv("tags"))
            self._set_optional(entity, "npcs", self._multiselect("npcs"))
            self._set_optional(entity, "items", self._multiselect("items"))
            self._set_optional(entity, "encounters", self._json("encounters", dict))

        elif category == "npcs":
            self._set_optional(entity, "name", self._string_var("name"))
            self._set_optional(entity, "description", self._text("description"))
            self._set_optional(entity, "aliases", self._csv("aliases"))
            if bool(self.vars["recruitable"].get()):
                entity["recruitable"] = True
            else:
                entity.pop("recruitable", None)
            self._set_optional(entity, "home_room", self._string_var("home_room"))
            entity.pop("default_room", None)
            self._set_optional(entity, "tags", self._multiselect("tags"))
            self._set_optional(entity, "roles", self._multiselect("roles"))
            self._set_optional(entity, "faction", self._string_var("faction"))
            self._set_optional(entity, "job", self._string_var("job"))
            level_text = self._string_var("level")
            if level_text:
                try:
                    entity["level"] = int(level_text)
                    entity.pop("lvl", None)
                except ValueError as exc:
                    raise ValueError("等級必須是整數") from exc
            else:
                entity.pop("level", None)
            self._set_optional(entity, "attr", self._json("attr", dict))
            self._set_optional(entity, "stats", self._json("stats", dict))
            self._set_optional(entity, "equipment", self._json("equipment", dict))
            self._set_optional(entity, "combat", self._json("combat", dict))
            self._set_optional(entity, "skills", self._json("skills", list))
            self._set_optional(entity, "topics", self._json("topics", dict))
            self._set_optional(entity, "gifts", self._json("gifts", dict))

        elif category == "quests":
            self._set_optional(entity, "name", self._string_var("name"))
            self._set_optional(entity, "desc", self._text("desc"))
            entity.pop("description", None)
            entity["tasks"] = self._json("tasks", list)
            entity["rewards"] = self._json("rewards", list)

        # 保留未表單化欄位，但不允許它覆蓋 ID 與已知欄位。
        extra = self._json("__extra__", dict)
        for key, value in extra.items():
            if key not in KNOWN_FIELDS[category] and key != "id":
                entity[key] = value
        for key in list(entity):
            if key not in KNOWN_FIELDS[category] and key != "id" and key not in extra:
                entity.pop(key, None)
        return entity

    @staticmethod
    def _set_optional(entity: dict[str, Any], key: str, value: Any) -> None:
        if value in (None, "", [], {}):
            entity.pop(key, None)
        else:
            entity[key] = value

    def _string_var(self, key: str, *, required: bool = False) -> str:
        value = str(self.vars[key].get()).strip()
        if required and not value:
            raise ValueError(f"{key} 不可空白")
        return value

    def _text(self, key: str) -> str:
        return self.widgets[key].get("1.0", "end-1c").strip()

    def _json(self, key: str, expected: type) -> Any:
        raw = self._text(key)
        if not raw:
            return expected()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} JSON 錯誤：第 {exc.lineno} 行第 {exc.colno} 欄，{exc.msg}") from exc
        if not isinstance(value, expected):
            expected_name = "object" if expected is dict else "array"
            raise ValueError(f"{key} 必須是 JSON {expected_name}")
        return value

    def _csv(self, key: str) -> list[str]:
        return [part.strip() for part in self._string_var(key).replace("，", ",").split(",") if part.strip()]

    def _multiselect(self, key: str) -> list[str]:
        listbox = self.widgets[key]
        listbox.sync_selection()
        return [
            choice_id
            for choice_id in sorted(listbox.all_choices)
            if choice_id in listbox.selected_ids
        ]

    @staticmethod
    def _parse_exits(raw: str) -> dict[str, str]:
        exits: dict[str, str] = {}
        for line_no, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"exits 第 {line_no} 行缺少 '='")
            direction, room_id = (part.strip() for part in line.split("=", 1))
            if not direction or not room_id:
                raise ValueError(f"exits 第 {line_no} 行方向與房間都不可空白")
            if direction in exits:
                raise ValueError(f"exits 方向重複：{direction}")
            exits[direction] = room_id
        return exits

    def _update_preview(self) -> None:
        try:
            entity = self._collect_entity() if "id" in self.vars else {}
        except Exception as exc:
            self._set_preview({"preview_error": str(exc)})
            return
        self._set_preview(entity)

    def _set_preview(self, value: Any) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))
        self.preview_text.configure(state="disabled")

    # ---------- commands ----------
    def _new_entity(self) -> None:
        self.current_id = None
        self.current_entity = self._template_for(self.current_category)
        self.is_new = True
        self.entity_tree.selection_remove(self.entity_tree.selection())
        self._build_form(self.current_entity, id_editable=True)
        self._set_status(f"新增 {CATEGORY_LABELS[self.current_category]}：請先填寫 ID。")

    def _duplicate_entity(self) -> None:
        if not self.current_id:
            messagebox.showinfo("複製", "請先選擇一個項目。", parent=self)
            return
        entity = deepcopy(self.current_entity)
        entity["id"] = f"{self.current_id}_copy"
        self.current_id = None
        self.current_entity = entity
        self.is_new = True
        self._build_form(entity, id_editable=True)
        self._set_status("已建立複本；修改 ID 後儲存。")

    def _save_entity(self) -> None:
        try:
            entity = self._collect_entity()
            entity_id = entity["id"]
            if self.is_new and entity_id in self.data[self.current_category]:
                raise ValueError(f"ID 已存在：{entity_id}")
            path, issues = self.repo.save_entity(
                self.current_category,
                entity,
                original_id=None if self.is_new else self.current_id,
            )
        except DataValidationError as exc:
            self._show_issues(exc.issues)
            messagebox.showerror("驗證失敗", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("無法儲存", str(exc), parent=self)
            return

        self.data = self.repo.load_all()
        self.current_id = entity_id
        self.current_entity = deepcopy(self.data[self.current_category][entity_id])
        self.is_new = False
        self._load_entity_list(select_id=entity_id)
        self._show_issues(issues)
        self._set_status(f"已儲存：{path}")

    def _delete_entity(self) -> None:
        if not self.current_id or self.is_new:
            messagebox.showinfo("刪除", "請先選擇已儲存的項目。", parent=self)
            return
        if not messagebox.askyesno("確認刪除", f"刪除 {self.current_category}:{self.current_id}？\n仍被引用時會阻止刪除。", parent=self):
            return
        try:
            _paths, issues = self.repo.delete_entity(self.current_category, self.current_id)
        except DataValidationError as exc:
            self._show_issues(exc.issues)
            messagebox.showerror("無法刪除", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("無法刪除", str(exc), parent=self)
            return
        self.data = self.repo.load_all()
        self.current_id = None
        self.current_entity = {}
        self._load_entity_list()
        self._clear_form("項目已刪除。")
        self._show_issues(issues)
        self._set_status("刪除完成；原檔已備份。")

    def _validate_all(self) -> None:
        try:
            issues = self.repo.validate()
        except Exception as exc:
            messagebox.showerror("驗證失敗", str(exc), parent=self)
            return
        self._show_issues(issues)
        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        self._set_status(f"驗證完成：{errors} 個錯誤，{warnings} 個警告。")
        if not issues:
            messagebox.showinfo("驗證完成", "所有支援資料均通過驗證。", parent=self)

    def _format_all(self) -> None:
        if not messagebox.askyesno(
            "格式化全部",
            "將依語意欄位順序重寫支援的 JSON，並為每個舊檔建立備份。是否繼續？",
            parent=self,
        ):
            return
        try:
            paths, issues = self.repo.format_all()
        except DataValidationError as exc:
            self._show_issues(exc.issues)
            messagebox.showerror("格式化前驗證失敗", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("格式化失敗", str(exc), parent=self)
            return
        self.data = self.repo.load_all()
        self._load_entity_list(select_id=self.current_id)
        self._show_issues(issues)
        self._set_status(f"已格式化 {len(paths)} 個資料分類；舊檔保存在 .editor_backups。")

    # ---------- helper dialogs ----------
    def _add_delivery_task(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("新增交付目標")
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        item_var = tk.StringVar(value=next(iter(sorted(self.data["items"])), ""))
        count_var = tk.IntVar(value=1)
        mode_var = tk.StringVar(value="role")
        role_var = tk.StringVar(value=next(iter(sorted(self.data["roles"])), ""))
        npc_var = tk.StringVar(value=next(iter(sorted(self.data["npcs"])), ""))

        rows = [
            ("道具", ttk.Combobox(dialog, textvariable=item_var, values=sorted(self.data["items"]), state="readonly")),
            ("數量", ttk.Spinbox(dialog, from_=1, to=999, textvariable=count_var)),
        ]
        for row, (label, widget) in enumerate(rows):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=5)
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=5)

        recipient = ttk.Labelframe(dialog, text="收件條件", padding=6)
        recipient.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Radiobutton(recipient, text="指定 Role", variable=mode_var, value="role").grid(row=0, column=0, sticky="w")
        ttk.Combobox(recipient, textvariable=role_var, values=sorted(self.data["roles"]), state="readonly").grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Radiobutton(recipient, text="指定 NPC", variable=mode_var, value="npc").grid(row=1, column=0, sticky="w")
        ttk.Combobox(recipient, textvariable=npc_var, values=sorted(self.data["npcs"]), state="readonly").grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Radiobutton(recipient, text="任意 NPC", variable=mode_var, value="any").grid(row=2, column=0, sticky="w")
        recipient.columnconfigure(1, weight=1)

        def commit() -> None:
            task: dict[str, Any] = {"type": "deliver_item", "target": item_var.get(), "count": int(count_var.get())}
            if mode_var.get() == "role":
                task["target_role"] = role_var.get()
            elif mode_var.get() == "npc":
                task["target_npc"] = npc_var.get()
            try:
                tasks = self._json("tasks", list)
            except Exception as exc:
                messagebox.showerror("任務目標 JSON 錯誤", str(exc), parent=dialog)
                return
            tasks.append(task)
            self._replace_json_text("tasks", tasks)
            dialog.destroy()
            self._update_preview()

        ttk.Button(dialog, text="加入", command=commit).grid(row=3, column=0, padx=8, pady=8)
        ttk.Button(dialog, text="取消", command=dialog.destroy).grid(row=3, column=1, sticky="e", padx=8, pady=8)

    def _add_gift_rule(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("新增送禮規則")
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        item_var = tk.StringVar(value=next(iter(sorted(self.data["items"])), ""))
        reply_var = tk.StringVar(value="她收下了你的禮物。")
        consume_var = tk.BooleanVar(value=True)
        reward_var = tk.StringVar(value="")
        emotion_vars = {name: tk.IntVar(value=0) for name in ("joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation")}

        ttk.Label(dialog, text="禮物道具").grid(row=0, column=0, sticky="w", padx=8, pady=5)
        ttk.Combobox(dialog, textvariable=item_var, values=sorted(self.data["items"]), state="readonly").grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(dialog, text="回應").grid(row=1, column=0, sticky="w", padx=8, pady=5)
        ttk.Entry(dialog, textvariable=reply_var).grid(row=1, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(dialog, text="回禮（可空白）").grid(row=2, column=0, sticky="w", padx=8, pady=5)
        ttk.Combobox(dialog, textvariable=reward_var, values=[""] + sorted(self.data["items"]), state="readonly").grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Checkbutton(dialog, text="消耗禮物", variable=consume_var).grid(row=3, column=1, sticky="w", padx=8, pady=5)

        emotions = ttk.Labelframe(dialog, text="情緒變化（0 表示不寫入）", padding=6)
        emotions.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        for index, (name, var) in enumerate(emotion_vars.items()):
            ttk.Label(emotions, text=name).grid(row=index // 4, column=(index % 4) * 2, padx=(4, 2), pady=3)
            ttk.Spinbox(emotions, from_=-100, to=100, width=6, textvariable=var).grid(row=index // 4, column=(index % 4) * 2 + 1, padx=(0, 8), pady=3)

        def commit() -> None:
            try:
                gifts = self._json("gifts", dict)
            except Exception as exc:
                messagebox.showerror("送禮 JSON 錯誤", str(exc), parent=dialog)
                return
            item_id = item_var.get()
            if item_id in gifts and not messagebox.askyesno("覆蓋規則", f"{item_id} 已有規則，是否覆蓋？", parent=dialog):
                return
            rule: dict[str, Any] = {"reply": reply_var.get().strip(), "consume": bool(consume_var.get())}
            if reward_var.get():
                rule["reward_item"] = reward_var.get()
            for name, var in emotion_vars.items():
                value = int(var.get())
                if value:
                    rule[name] = value
            gifts[item_id] = rule
            self._replace_json_text("gifts", gifts)
            dialog.destroy()
            self._update_preview()

        ttk.Button(dialog, text="加入", command=commit).grid(row=5, column=0, padx=8, pady=8)
        ttk.Button(dialog, text="取消", command=dialog.destroy).grid(row=5, column=1, sticky="e", padx=8, pady=8)

    def _replace_json_text(self, key: str, value: Any) -> None:
        widget = self.widgets[key]
        widget.delete("1.0", tk.END)
        widget.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))

    # ---------- misc ----------
    def _show_issues(self, issues: list[ValidationIssue] | tuple[ValidationIssue, ...]) -> None:
        self.issues_text.configure(state="normal")
        self.issues_text.delete("1.0", tk.END)
        if issues:
            self.issues_text.insert("1.0", "\n".join(issue.render() for issue in issues))
        else:
            self.issues_text.insert("1.0", "✅ 沒有發現錯誤或警告。")
        self.issues_text.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    @staticmethod
    def _template_for(category: str) -> dict[str, Any]:
        templates = {
            "tags": {"id": "", "name": "", "description": ""},
            "roles": {"id": "", "name": "", "description": ""},
            "items": {"id": "", "name": "", "desc": ""},
            "rooms": {"id": "", "name": "", "desc": "", "exits": {}, "npcs": [], "items": [], "tags": []},
            "npcs": {"id": "", "name": "", "aliases": [], "roles": [], "tags": [], "topics": {}, "gifts": {}},
            "quests": {"id": "", "name": "", "desc": "", "tasks": [], "rewards": []},
        }
        return deepcopy(templates[category])
