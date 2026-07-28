from __future__ import annotations

from copy import deepcopy
import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Mapping


PROPERTY_CATALOGS: dict[str, dict[str, dict[str, Any]]] = {
    "bonuses": {
        "max_hp": {"label": "最大 HP", "type": "int", "description": "裝備提供的最大生命值加成。"},
        "max_mp": {"label": "最大 MP", "type": "int", "description": "裝備提供的最大魔力值加成。"},
        "atk": {"label": "物理攻擊", "type": "int", "description": "裝備提供的物理攻擊加成。"},
        "matk": {"label": "魔法攻擊", "type": "int", "description": "裝備提供的魔法攻擊加成。"},
        "def_": {"label": "物理防禦", "type": "int", "description": "裝備提供的物理防禦加成。"},
        "mdef": {"label": "魔法防禦", "type": "int", "description": "裝備提供的魔法防禦加成。"},
        "speed": {"label": "速度", "type": "int", "description": "裝備提供的速度加成，可為負數。"},
        "crit": {"label": "暴擊率", "type": "int", "description": "裝備提供的暴擊率加成。"},
    },
    "simple_use": {
        "reply": {"label": "使用訊息", "type": "str", "description": "使用物品後顯示的文字。"},
        "hp_delta": {"label": "HP 變化", "type": "int", "description": "正數恢復 HP，負數扣除 HP。"},
        "mp_delta": {"label": "MP 變化", "type": "int", "description": "正數恢復 MP，負數扣除 MP。"},
        "gold_delta": {"label": "金錢變化", "type": "int", "description": "正數增加金錢，負數扣除金錢。"},
        "reward_item": {"label": "取得物品", "type": "str", "description": "使用後取得的 item ID。"},
        "consume": {"label": "是否消耗", "type": "bool", "description": "true 表示使用後從背包移除。"},
    },
    "attr": {
        "STR": {"label": "力量 STR", "type": "int", "description": "角色力量屬性。"},
        "INT": {"label": "智力 INT", "type": "int", "description": "角色智力屬性。"},
        "CON": {"label": "體質 CON", "type": "int", "description": "角色體質屬性。"},
        "DEX": {"label": "敏捷 DEX", "type": "int", "description": "角色敏捷屬性。"},
        "CHA": {"label": "魅力 CHA", "type": "int", "description": "角色魅力屬性。"},
        "LCK": {"label": "幸運 LCK", "type": "int", "description": "角色幸運屬性。"},
    },
    "stats": {
        "hp": {"label": "目前 HP", "type": "int", "description": "NPC 初始或永久生命值。"},
        "max_hp": {"label": "最大 HP", "type": "int", "description": "NPC 最大生命值。"},
        "mp": {"label": "目前 MP", "type": "int", "description": "NPC 初始或永久魔力值。"},
        "max_mp": {"label": "最大 MP", "type": "int", "description": "NPC 最大魔力值。"},
        "atk": {"label": "物理攻擊", "type": "int", "description": "NPC 永久物理攻擊。"},
        "def_": {"label": "物理防禦", "type": "int", "description": "NPC 永久物理防禦。"},
        "defense": {"label": "物理防禦（舊名）", "type": "int", "description": "NPCProfile 使用的防禦欄位名稱。"},
        "matk": {"label": "魔法攻擊", "type": "int", "description": "NPC 永久魔法攻擊。"},
        "mdef": {"label": "魔法防禦", "type": "int", "description": "NPC 永久魔法防禦。"},
        "speed": {"label": "速度", "type": "int", "description": "NPC 永久速度。"},
        "crit": {"label": "暴擊率", "type": "int", "description": "NPC 永久暴擊率。"},
        "exp": {"label": "經驗值", "type": "int", "description": "NPC 經驗值。"},
        "gold": {"label": "持有金錢", "type": "int", "description": "NPC 持有金錢。"},
    },
    "combat": {
        "hp": {"label": "戰鬥 HP", "type": "int", "description": "戰鬥設定中的生命值。"},
        "max_hp": {"label": "戰鬥最大 HP", "type": "int", "description": "戰鬥設定中的最大生命值。"},
        "mp": {"label": "戰鬥 MP", "type": "int", "description": "戰鬥設定中的魔力值。"},
        "max_mp": {"label": "戰鬥最大 MP", "type": "int", "description": "戰鬥設定中的最大魔力值。"},
        "atk": {"label": "戰鬥物攻", "type": "int", "description": "戰鬥設定中的物理攻擊。"},
        "def_": {"label": "戰鬥物防", "type": "int", "description": "戰鬥設定中的物理防禦。"},
        "matk": {"label": "戰鬥魔攻", "type": "int", "description": "戰鬥設定中的魔法攻擊。"},
        "mdef": {"label": "戰鬥魔防", "type": "int", "description": "戰鬥設定中的魔法防禦。"},
        "speed": {"label": "戰鬥速度", "type": "int", "description": "戰鬥設定中的速度。"},
        "crit": {"label": "戰鬥暴擊", "type": "int", "description": "戰鬥設定中的暴擊率。"},
    },
}


class SearchablePropertyEditor(ttk.Frame):
    """以可搜尋的欄位目錄編輯一層 JSON object，並保留未知自訂欄位。"""

    def __init__(
        self,
        master,
        *,
        value: Mapping[str, Any] | None,
        catalog: Mapping[str, Mapping[str, Any]],
        height: int = 6,
    ):
        super().__init__(master)
        self.catalog = {str(key): dict(spec) for key, spec in catalog.items()}
        self.value: dict[str, Any] = deepcopy(dict(value or {}))
        self.visible_property_ids: list[str] = []

        self.filter_var = tk.StringVar(value="")
        self.property_var = tk.StringVar(value="")
        self.value_var = tk.StringVar(value="")
        self.hint_var = tk.StringVar(value="可輸入目錄中的欄位，也可直接輸入自訂 key。")

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="篩選屬性").grid(row=0, column=0, sticky="w")
        filter_entry = ttk.Entry(top, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(top, text="屬性").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.property_combo = ttk.Combobox(top, textvariable=self.property_var, state="normal")
        self.property_combo.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 0))
        ttk.Label(top, text="值").grid(row=2, column=0, sticky="w", pady=(4, 0))
        value_entry = ttk.Entry(top, textvariable=self.value_var)
        value_entry.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(4, 0))
        top.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(4, 4))
        ttk.Button(buttons, text="設定／更新", command=self._set_property).pack(side="left")
        ttk.Button(buttons, text="移除", command=self._remove_property).pack(side="left", padx=(4, 0))
        ttk.Label(buttons, textvariable=self.hint_var).pack(side="left", padx=(10, 0))

        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("key", "label", "value"), show="headings", height=height)
        self.tree.heading("key", text="Key")
        self.tree.heading("label", text="說明")
        self.tree.heading("value", text="值")
        self.tree.column("key", width=130, anchor="w")
        self.tree.column("label", width=150, anchor="w")
        self.tree.column("value", width=220, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        filter_entry.bind("<KeyRelease>", self.refresh_catalog)
        self.property_combo.bind("<<ComboboxSelected>>", self._on_property_selected)
        self.property_combo.bind("<KeyRelease>", self._on_property_typed)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selected)
        self.tree.bind("<Double-1>", self._on_tree_selected)
        value_entry.bind("<Return>", lambda _event: self._set_property())

        self.refresh_catalog()
        self.refresh_tree()

    def get_value(self) -> dict[str, Any]:
        return deepcopy(self.value)

    def set_value(self, value: Mapping[str, Any] | None) -> None:
        self.value = deepcopy(dict(value or {}))
        self.refresh_tree()

    def refresh_catalog(self, _event=None) -> None:
        query = self.filter_var.get().strip().casefold()
        ids: list[str] = []
        labels: list[str] = []
        for property_id in sorted(self.catalog):
            spec = self.catalog[property_id]
            searchable = " ".join(
                (
                    property_id,
                    str(spec.get("label", "")),
                    str(spec.get("description", "")),
                )
            ).casefold()
            if query and query not in searchable:
                continue
            ids.append(property_id)
            labels.append(self._display_name(property_id))
        self.visible_property_ids = ids
        self.property_combo.configure(values=labels)

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        catalog_order = {property_id: index for index, property_id in enumerate(self.catalog)}
        keys = sorted(self.value, key=lambda key: (catalog_order.get(key, 10_000), key))
        for key in keys:
            spec = self.catalog.get(key, {})
            label = str(spec.get("label", "自訂屬性"))
            rendered = json.dumps(self.value[key], ensure_ascii=False)
            self.tree.insert("", "end", iid=key, values=(key, label, rendered))

    def select_property(self, property_id: str) -> None:
        self.property_var.set(self._display_name(property_id) if property_id in self.catalog else property_id)
        if property_id in self.value:
            self.value_var.set(self._render_input_value(self.value[property_id]))
        self._update_hint(property_id)

    def assign(self, property_id: str, raw_value: str) -> None:
        property_id = property_id.strip()
        if not property_id:
            raise ValueError("屬性 key 不可空白")
        self.value[property_id] = self._parse_value(property_id, raw_value)
        self.refresh_tree()
        self.select_property(property_id)

    def _set_property(self) -> None:
        property_id = self._property_id_from_display(self.property_var.get())
        try:
            self.assign(property_id, self.value_var.get())
        except ValueError as exc:
            messagebox.showerror("屬性值錯誤", str(exc), parent=self.winfo_toplevel())

    def _remove_property(self) -> None:
        selected = self.tree.selection()
        property_id = selected[0] if selected else self._property_id_from_display(self.property_var.get())
        if not property_id or property_id not in self.value:
            return
        del self.value[property_id]
        self.refresh_tree()
        self.value_var.set("")

    def _on_property_selected(self, _event=None) -> None:
        property_id = self._property_id_from_display(self.property_var.get())
        if property_id in self.value:
            self.value_var.set(self._render_input_value(self.value[property_id]))
        self._update_hint(property_id)

    def _on_property_typed(self, _event=None) -> None:
        self._update_hint(self._property_id_from_display(self.property_var.get()))

    def _on_tree_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.select_property(selected[0])

    def _display_name(self, property_id: str) -> str:
        label = self.catalog.get(property_id, {}).get("label")
        return f"{property_id} — {label}" if label else property_id

    def _property_id_from_display(self, display: str) -> str:
        value = display.strip()
        if " — " in value:
            candidate = value.split(" — ", 1)[0].strip()
            if candidate:
                return candidate
        return value

    def _update_hint(self, property_id: str) -> None:
        spec = self.catalog.get(property_id)
        if not spec:
            self.hint_var.set("自訂屬性：值會嘗試依 JSON scalar 解析。")
            return
        value_type = spec.get("type", "json")
        description = str(spec.get("description", ""))
        self.hint_var.set(f"{value_type}｜{description}")

    def _parse_value(self, property_id: str, raw_value: str) -> Any:
        raw = raw_value.strip()
        spec = self.catalog.get(property_id, {})
        value_type = spec.get("type", "json")
        if value_type == "str":
            return raw_value
        if value_type == "int":
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{property_id} 必須是整數") from exc
        if value_type == "float":
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(f"{property_id} 必須是數字") from exc
        if value_type == "bool":
            normalized = raw.casefold()
            if normalized in {"true", "1", "yes", "y", "是"}:
                return True
            if normalized in {"false", "0", "no", "n", "否"}:
                return False
            raise ValueError(f"{property_id} 必須輸入 true 或 false")
        if raw == "":
            return ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw_value

    @staticmethod
    def _render_input_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)
