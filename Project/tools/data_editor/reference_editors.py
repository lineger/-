from __future__ import annotations

from copy import deepcopy
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Mapping


class EncounterPoolEditor(ttk.Frame):
    """結構化編輯 rooms.encounters，避免手寫 monster ID。"""

    def __init__(
        self,
        master,
        *,
        value: Mapping[str, Any] | None,
        monsters: Mapping[str, Mapping[str, Any]],
        height: int = 6,
    ):
        super().__init__(master)
        source = deepcopy(dict(value or {}))
        self.extra = {key: val for key, val in source.items() if key not in {"rate", "pool"}}
        self.monsters = {str(key): dict(val) for key, val in monsters.items()}
        self.entries: list[tuple[str, int]] = []
        for raw in source.get("pool", []) or []:
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                try:
                    self.entries.append((str(raw[0]), int(raw[1])))
                except (TypeError, ValueError):
                    pass

        self.rate_var = tk.StringVar(value=str(source.get("rate", "")))
        self.monster_var = tk.StringVar(value=next(iter(sorted(self.monsters)), ""))
        self.weight_var = tk.IntVar(value=1)

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="遭遇率（0–1）").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.rate_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 14))
        ttk.Label(top, text="怪物").grid(row=0, column=2, sticky="w")
        self.monster_combo = ttk.Combobox(
            top,
            textvariable=self.monster_var,
            values=sorted(self.monsters),
            state="readonly",
            width=24,
        )
        self.monster_combo.grid(row=0, column=3, sticky="ew", padx=(6, 14))
        ttk.Label(top, text="權重").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(top, from_=1, to=999999, textvariable=self.weight_var, width=8).grid(
            row=0, column=5, sticky="w", padx=(6, 0)
        )
        top.columnconfigure(3, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(0, 4))
        ttk.Button(buttons, text="加入／更新", command=self._upsert).pack(side="left")
        ttk.Button(buttons, text="移除", command=self._remove).pack(side="left", padx=(4, 0))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("id", "name", "weight"), show="headings", height=height)
        self.tree.heading("id", text="Monster ID")
        self.tree.heading("name", text="名稱")
        self.tree.heading("weight", text="權重")
        self.tree.column("id", width=180, anchor="w")
        self.tree.column("name", width=180, anchor="w")
        self.tree.column("weight", width=80, anchor="e")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._select)
        self._refresh()

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, (monster_id, weight) in enumerate(self.entries):
            meta = self.monsters.get(monster_id, {})
            name = meta.get("name", "⚠ 未定義")
            self.tree.insert("", "end", iid=str(index), values=(monster_id, name, weight))

    def _select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        monster_id, weight = self.entries[index]
        self.monster_var.set(monster_id)
        self.weight_var.set(weight)

    def _upsert(self) -> None:
        monster_id = self.monster_var.get().strip()
        if not monster_id:
            messagebox.showerror("遭遇設定", "請選擇怪物。", parent=self.winfo_toplevel())
            return
        try:
            weight = int(self.weight_var.get())
        except (TypeError, ValueError):
            weight = 0
        if weight <= 0:
            messagebox.showerror("遭遇設定", "權重必須是正整數。", parent=self.winfo_toplevel())
            return
        for index, (current_id, _current_weight) in enumerate(self.entries):
            if current_id == monster_id:
                self.entries[index] = (monster_id, weight)
                break
        else:
            self.entries.append((monster_id, weight))
        self._refresh()

    def _remove(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        del self.entries[int(selected[0])]
        self._refresh()

    def get_value(self) -> dict[str, Any]:
        out = deepcopy(self.extra)
        raw_rate = self.rate_var.get().strip()
        if raw_rate:
            try:
                rate = float(raw_rate)
            except ValueError as exc:
                raise ValueError("遭遇率必須是數字") from exc
            if not 0 <= rate <= 1:
                raise ValueError("遭遇率必須介於 0 與 1 之間")
            out["rate"] = rate
        if self.entries:
            out["pool"] = [[monster_id, weight] for monster_id, weight in self.entries]
        return out
