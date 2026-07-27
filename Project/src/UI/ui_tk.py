# 檔案：Project/src/UI/ui_tk.py (完整替換，已包含背景圖功能)

import math
import tkinter as tk
from tkinter import ttk
# 【注意】請確認這行導入是否正確，如果您的 menu2.py 在同一目錄下，可能需要改為：from .menu2 import ActionMenu
from UI.menu2 import ActionMenu 
# 【新增】 引入 CombatantProfile 型別提示
from Data.state import CombatantProfile 

_COMPASS = {
    "n": (0, -1), "north": (0, -1),
    "s": (0,  1), "south": (0,  1),
    "w": (-1, 0), "west":  (-1, 0),
    "e": ( 1, 0), "east":  ( 1, 0),
}

def _normalize_dir(s: str) -> str:
    return (s or "").strip().lower()

def compute_grid_positions(world):
    """
    從 rooms 的出口方向（n/s/e/w）推導每個房間的整數網格座標。
    沒有標準方位的出口會被忽略（不影響其他房間）。
    """
    rooms = world.get("rooms", {})
    if not rooms: return {}
    # 選個根：起始房或任意第一個
    root = "town_square" if "town_square" in rooms else next(iter(rooms.keys()))
    pos = {root: (0, 0)}
    q = [root]
    visited = {root}
    while q:
        r = q.pop(0)
        x, y = pos[r]
        for d, to in (rooms[r].get("exits") or {}).items():
            if to not in rooms: 
                continue
            v = _COMPASS.get(_normalize_dir(d))
            if not v:
                # 非方位字，如「小徑」「門口」→ 略過，不影響固定方位
                continue
            dx, dy = v
            nx, ny = x + dx, y + dy
            if to in pos:
                # 若已有座標，跳過；（可加一致性檢查）
                continue
            pos[to] = (nx, ny)
            if to not in visited:
                visited.add(to)
                q.append(to)
    return pos


class FixedMiniMap(ttk.Frame):
    #---固定方位小地圖：用 compute_grid_positions 的座標，整張圖縮放到畫布；高亮目前位置。---
    NODE_BASE = 10      # 節點基準半徑（像素），不隨地圖縮放 s 放大
    NODE_MIN  = 6       # 節點最小半徑
    NODE_MAX  = 12      # 節點最大半徑

    def __init__(self, master, world, state, on_click_neighbor=None, positions=None):
        super().__init__(master)
        self.world = world
        self.state = state
        self.on_click_neighbor = on_click_neighbor
        self.positions = positions or {}

        # 標題列 + 縮放
        bar = ttk.Frame(self); bar.pack(fill="x")
        ttk.Label(bar, text="小地圖", font=("Noto Sans CJK TC", 11, "bold")).pack(side="left")
        self.zoom = tk.DoubleVar(value=1.2)  # 預設略放大以避免字太小
        ttk.Scale(bar, from_=0.7, to=2.0, variable=self.zoom, command=lambda _=None: self.render(),
                  length=110).pack(side="right", padx=4)

        # 畫布（高度再加大一點，字較不擠）
        self.canvas = tk.Canvas(self, height=220, bg="#fafafa", highlightthickness=1, highlightbackground="#ddd")
        self.canvas.pack(fill="x", pady=(4, 0))
        self.canvas.bind("<Button-1>", self._on_click)

        self._last_xy = {}
        self._layout = self._last_xy  # 兼容 _hit_node

    def _world_bbox(self):
        xs = [x for (x, _) in self.positions.values()] or [0]
        ys = [y for (_, y) in self.positions.values()] or [0]
        return min(xs), min(ys), max(xs), max(ys)

    def _fit_transform(self, W, H, pad=20):
        # 取得世界座標外框
        xs = [x for (x, _) in self.positions.values()] or [0]
        ys = [y for (_, y) in self.positions.values()] or [0]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        w = max(1, x1 - x0 + 1)
        h = max(1, y1 - y0 + 1)

        # 等比縮放，並「置中」到畫布（解決偏左上）
        sx = (W - 2*pad) / w
        sy = (H - 2*pad) / h
        s = max(1, min(sx, sy)) * float(self.zoom.get())

        # 置中位移
        used_w = s * w
        used_h = s * h
        off_x = (W - used_w) / 2
        off_y = (H - used_h) / 2


        def to_px(x, y):
            px = off_x + (x - x0 + 0.5) * s
            py = off_y + (y - y0 + 0.5) * s
            return int(px), int(py), s
        return to_px

    def render(self):
        rooms = self.world.get("rooms", {})
        if not rooms:
            return
        W = int(self.canvas.winfo_width() or 280)
        H = int(self.canvas.winfo_height() or 220)
        to_px = self._fit_transform(W, H, pad=18)

        # 先算像素位置
        self._last_xy = {}
        any_s = 1.0
        for rid, grid in self.positions.items():
            px, py, s = to_px(*grid)
            self._last_xy[rid] = (px, py)
            any_s = s
        self._layout = self._last_xy

        self.canvas.delete("all")

        # 畫邊（只畫兩端都有座標的）
        for a, room in rooms.items():
            axy = self._last_xy.get(a)
            if not axy:
                continue
            ax, ay = axy
            for _, b in (room.get("exits") or {}).items():
                bxy = self._last_xy.get(b)
                if not bxy or a >= b:  # 避免重複
                    continue
                bx, by = bxy
                self.canvas.create_line(ax, ay, bx, by, fill="#c8c8c8")

        # ── 節點大小與字體：只跟 zoom 相關，跟 s (地圖縮放) 脫鉤 ──
        z = float(self.zoom.get())
        r_other = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 0.8)))
        r_nei   = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 0.95)))
        r_cur   = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 1.1)))
        # 字體也只做輕微調整，避免擠
        font_size = int(max(9, min(12, 9 + (z - 1.0) * 3)))

        cur = self.state.room_id
        visited = getattr(self.state, "visited_rooms", {cur})
        neighbor_set = set((self.world["rooms"].get(cur, {}).get("exits") or {}).values())

        for rid, (px, py) in self._last_xy.items():
            is_cur = (rid == cur)
            is_nei = (rid in neighbor_set)
            explored = (rid in visited)

            # ★ 依層級選半徑
            r = r_cur if is_cur else (r_nei if is_nei else r_other)

            fill = "#4a90e2" if is_cur else ("#444" if explored else "#cfcfcf")
            outline = "#1f5ea8" if is_cur else "#666"

            # 方形節點
            self.canvas.create_rectangle(px - r, py - r, px + r, py + r,
                                         fill=fill, outline=outline, width=2 if is_cur else 1,
                                         tags=(f"node:{rid}",))

            # 只給「當前＋相鄰」標籤；用短名避免擁擠
            if is_cur or is_nei:
                name  = self.world["rooms"][rid].get("short") or self.world["rooms"][rid].get("name", rid)
                label = name if len(name) <= 6 else name[:6]
                self.canvas.create_text(px, py - r - 8, text=label,
                                        font=("Noto Sans CJK TC", font_size),
                                        fill=("#222" if explored else "#999"))

    def _on_click(self, ev):
        # 只允許點擊「相鄰房」來移動（保持規則）
        rid = None; best=1e9
        
        # 【修正】 _on_click 之前有一個 bug，它在呼叫 _hit_node 之前
        # 引用了 self.NODE_R，但這個屬性並不存在。
        # 現在 _on_click 會正確呼叫 _hit_node 來進行點擊檢測。
        
        if not self._last_xy:
            return
        rid = self._hit_node(ev.x, ev.y)
        
        if not rid or rid == self.state.room_id:
            return
        cur_exits = (self.world["rooms"].get(self.state.room_id, {}).get("exits") or {})
        if rid in cur_exits.values() and callable(self.on_click_neighbor):
            self.on_click_neighbor(rid)

    def _hit_node(self, x, y):
        if not self._last_xy:
            return None
        # 跟 render 一樣的半徑邏輯（確保點擊圈不會過大）
        z = float(self.zoom.get())
        r_other = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 0.8)))
        r_nei   = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 0.95)))
        r_cur   = int(max(self.NODE_MIN, min(self.NODE_MAX, self.NODE_BASE * z * 1.1)))

        cur = self.state.room_id
        neighbor_set = set((self.world["rooms"].get(cur, {}).get("exits") or {}).values())

        best, bestd2 = None, 1e9
        for rid, (nx, ny) in self._last_xy.items():
            r = r_cur if rid == cur else (r_nei if rid in neighbor_set else r_other)
            pick_r = r + 6  # 點擊緩衝
            d2 = (nx - x) ** 2 + (ny - y) ** 2
            if d2 <= pick_r ** 2 and d2 < bestd2:
                best, bestd2 = rid, d2
        return best


class RosterPanel(ttk.Frame):
    """
    單一分層面板：第一層顯示玩家；左右切換可看每位隊友。
    新增「屬性/裝備/特性」分頁，可切換顯示。
    """
    # 定義可切換的分頁及其渲染函式
    VIEWS = [
        ("屬性 & 數值", "_render_stats_and_attr"), # 結合 HP/EXP 和 6 屬性
        ("裝備", "_render_equipment"),
        ("特性", "_render_tags"),
    ]

    def __init__(self, master, world, engine, state, on_refresh):
        super().__init__(master)
        self.world, self.engine, self.state, self.on_refresh = world, engine, state, on_refresh
        self.member_idx = 0  # 目前顯示哪一位（0 = 玩家）
        self.view_idx = 0    # 目前顯示哪個分頁（0 = 屬性&數值）

        # --- 1. 成員切換導航（頂部，固定）---
        hdr = ttk.Frame(self); hdr.pack(fill="x")
        self.title_var = tk.StringVar(value="角色")
        ttk.Label(hdr, textvariable=self.title_var, font=("Noto Sans CJK TC", 12, "bold")).pack(side="left")
        nav = ttk.Frame(hdr); nav.pack(side="right")
        ttk.Button(nav, text="←", width=3, command=self.prev_member).pack(side="left", padx=(0,4))
        ttk.Button(nav, text="→", width=3, command=self.next_member).pack(side="left")

        # --- 2. 角色基本資訊（固定）---
        # 包含：名稱、HP/EXP/金錢等
        self.fixed_info_frame = ttk.Frame(self); self.fixed_info_frame.pack(fill="x", pady=(6,0))

        # --- 3. 分頁切換導航（固定）---
        self.view_nav_frame = ttk.Frame(self); self.view_nav_frame.pack(fill="x", pady=(6,0))
        self.view_buttons = []
        for i, (label, _) in enumerate(self.VIEWS):
            btn = ttk.Button(self.view_nav_frame, text=label, 
                             command=lambda i=i: self._switch_view(i))
            btn.pack(side="left", padx=2, expand=True, fill="x")
            self.view_buttons.append(btn)

        # --- 4. 分頁內容區（可切換）---
        self.view_body = ttk.Frame(self, padding=4); self.view_body.pack(fill="x", pady=(6,0))
        
        # --- 5. 動作區（固定於底部，目前只用於 NPC 遣散）---
        self.action_frame = ttk.Frame(self); self.action_frame.pack(fill="x", pady=(6,0))

        self.render()

    # ---- Member Navigation ----
    def _members(self):
        return list((self.state.facts.get("_party_members") or []))

    def _roster_ids(self):
        return ["$player"] + self._members()

    def prev_member(self):
        ids = self._roster_ids()
        if not ids: return
        self.member_idx = (self.member_idx - 1) % len(ids)
        self.render()

    def next_member(self):
        ids = self._roster_ids()
        if not ids: return
        self.member_idx = (self.member_idx + 1) % len(ids)
        self.render()
        
    def _switch_view(self, idx):
        self.view_idx = idx
        self.render_view() # 只重新渲染分頁內容，加快速度

    def _clear(self, w):
        for c in w.winfo_children():
            c.destroy()

    # ---- Small Render Helpers ----
    def _rowgrid(self, parent, rows):
        """rows: [(label, value_str)]"""
        g = ttk.Frame(parent); g.pack(fill="x", pady=(0,4))
        for r, (k, v) in enumerate(rows):
            ttk.Label(g, text=k).grid(row=r, column=0, sticky="w")
            ttk.Label(g, text=v).grid(row=r, column=1, sticky="w", padx=(6,0))
    
    # ---- Data Retrieval Helpers ----
    def _get_current_data(self):
        """獲取當前選中角色的所有渲染資料"""
        ids = self._roster_ids()
        if not ids: return None
        if self.member_idx >= len(ids): self.member_idx = 0
        cur = ids[self.member_idx]
        
        data = {"id": cur, "title": "", "stats": {}, "attr": {}, "eq": {}, "tags": set(), "actions": {}}

        if cur == "$player":
            st = self.state
            data["title"] = getattr(getattr(st, "stats", None), "name", "玩家")
            # Stats / Derived
            data["stats"]["lvl"] = getattr(st.stats, "lvl", 1)
            data["stats"]["hp"] = int(getattr(st.stats, "hp", 0))
            data["stats"]["max_hp"] = int(getattr(st.derived, "max_hp", data["stats"]["hp"]) or data["stats"]["hp"])
            data["stats"]["exp"] = int(getattr(st.stats, "exp", 0))
            data["stats"]["gold"] = int(getattr(st.stats, "gold", 0))
            # Attr
            data["attr"] = {k: getattr(st.attr, k, None) for k in ("STR","INT","CON","DEX","CHA","LCK")}
            data["attr"] = {k:v for k,v in data["attr"].items() if v is not None}
            # Equipment
            data["eq"] = getattr(getattr(st, "inventory", None), "equipment", {}) or {}
            # Tags
            data["tags"] = getattr(st, "tags", set()) or []
            
        else: # NPC / Party Member
            # 【修改】 NPC 資料來源改為 state.npc_profiles
            npc = (self.state.npc_profiles or {}).get(cur, {})
            
            data["title"] = name = getattr(npc, "name", cur)
            
            # Stats (來自 profile)
            data["stats"]["lvl"] = getattr(npc, "lvl", 1)
            data["stats"]["hp"] = int(getattr(npc, "hp", 0))
            data["stats"]["max_hp"] = int(getattr(npc, "max_hp", data["stats"]["hp"]) or data["stats"]["hp"])
            data["stats"]["exp"] = getattr(npc, "exp", None) # exp/gold
            data["stats"]["gold"] = None # NPC 預設不顯示金錢
            
            # Attr (NPCProfile.attr 與玩家 state.attr 使用相同結構)
            npc_attr = getattr(npc, "attr", None)
            for k in ("STR","INT","CON","DEX","CHA","LCK"):
                data["attr"][k] = getattr(npc_attr, k, 0)

            # Equipment (來自 profile)
            data["eq"] = getattr(npc, "equipment", {}) or {}
            
            # Tags (從 world.npcs 讀取靜態標籤)
            data["tags"] = (self.world.get("npcs", {}).get(cur, {}) or {}).get("tags", [])
            
            # Actions
            if cur in (self.state.facts.get("_party_members") or []):
                data["actions"]["dismiss"] = cur

        return data

    # ---- Fixed Info Rendering (Always Visible) ----
    def _render_fixed_info(self, data: dict):
        self._clear(self.fixed_info_frame)
        
        st = data["stats"]
        name = data["title"]
        lvl = st.get("lvl")
        
        # 名稱/等級
        ttk.Label(self.fixed_info_frame, 
                  text=f"{name}{'' if lvl in (None, '') else f'（Lv.{lvl}）'}",
                  font=("Noto Sans CJK TC", 11, "bold")).pack(anchor="w")

        # HP / EXP / 金錢
        hp = st.get("hp", 0)
        max_hp = st.get("max_hp", hp)
        exp = st.get("exp")
        gold = st.get("gold")
        
        rows = []
        if lvl not in (None, "", 0): rows.append(("等級",str(lvl)))
        rows.append(("HP", f"{hp}/{max_hp}"))
        if exp is not None: rows.append(("EXP",str(exp)))
        if gold is not None: rows.append(("金錢",str(gold)))

        self._rowgrid(self.fixed_info_frame, rows)
        
    # ---- View Specific Rendering (Dynamic) ----
    
    def _render_stats_and_attr(self, data: dict):
        attr_map = data["attr"]
        if not attr_map: 
            ttk.Label(self.view_body, text="（無基礎屬性資料）").pack(anchor="w"); return

        # 這裡使用您想要的 3 行 2 列佈局
        g = ttk.Frame(self.view_body); g.pack(fill="x")
        keys = [("STR","力"),("INT","智"),("CON","體"),("DEX","敏"),("CHA","魅"),("LCK","運")]
        
        for i, (key, lab) in enumerate(keys):
            if key in attr_map:
                # 計算行數與欄位偏移
                row = i % 3 
                col_offset = 2 if i >= 3 else 0 

                # 屬性名稱
                ttk.Label(g, text=f"{lab}({key})").grid(
                    row=row, column=col_offset, sticky="w", 
                    padx=(0, 4) if col_offset == 0 else (12, 4)
                )
                
                # 屬性數值
                ttk.Label(g, text=str(attr_map[key]), width=4).grid(row=row, column=col_offset + 1, sticky="w")
        
        g.grid_columnconfigure(0, weight=1) 
        g.grid_columnconfigure(2, weight=1)

    def _render_equipment(self, data: dict):
        eq = data["eq"]
        items = self.world.get("items", {}) or {}
        
        def _iname(iid):
            if not iid: return "-"
            return items.get(iid, {}).get("name", iid)
            
        if not eq:
            ttk.Label(self.view_body, text="（無裝備）").pack(anchor="w"); return
            
        g = ttk.Frame(self.view_body); g.pack(fill="x")
        r = 0
        for slot, iid in eq.items():
            ttk.Label(g, text=slot).grid(row=r, column=0, sticky="w")
            ttk.Label(g, text=_iname(iid)).grid(row=r, column=1, sticky="w", padx=(6,0))
            r += 1

    def _render_tags(self, data: dict):
        tags = data["tags"]
        
        if isinstance(tags, (set, list, tuple)):
            txt = "、".join(map(str, tags))
        elif isinstance(tags, str):
            txt = tags
        else:
            txt = ""
            
        ttk.Label(self.view_body, text=(txt if txt else "（無特性/標籤）"), 
                  wraplength=220, justify="left").pack(anchor="w")

    def _render_actions(self, data: dict):
        self._clear(self.action_frame)
        actions = data["actions"]
        
        # 遣散隊友動作
        if "dismiss" in actions:
            nid = actions["dismiss"]
            def _dismiss(nid=nid):
                res = self.engine.fire("dismiss", self.state, target_id=nid)
                msg = (res or {}).get("text")
                if msg: self.engine.say(msg)
                self.on_refresh()
                
            ttk.Button(self.action_frame, text="請他回原本的地方", command=_dismiss).pack(anchor="w", pady=(6,0))


    # ---- Main Render Calls ----
    def render_view(self):
        """只渲染分頁內容區"""
        self._clear(self.view_body)
        data = self._get_current_data()
        if not data: return
        
        # 高亮當前分頁按鈕
        for i, btn in enumerate(self.view_buttons):
            style_name = 'TButton' if i != self.view_idx else 'Accent.TButton'
            btn.configure(style=style_name)

        # 呼叫對應的渲染函式
        _, method_name = self.VIEWS[self.view_idx]
        getattr(self, method_name)(data)

    def render(self):
        """渲染整個面板：成員導航、固定資訊、分頁導航、分頁內容"""
        data = self._get_current_data()
        
        if not data:
            self._clear(self.fixed_info_frame)
            self._clear(self.view_body)
            self._clear(self.action_frame)
            ttk.Label(self.fixed_info_frame, text="（沒有成員）").pack(anchor="w")
            return
            
        self.title_var.set(data["title"])
        
        # 渲染固定資訊 (名稱/HP/EXP...)
        self._render_fixed_info(data)
        
        # 渲染動作區
        self._render_actions(data)
        
        # 渲染分頁內容
        self.render_view()
        

# ------- 主視窗 -------
class TkApp(tk.Tk):
    def __init__(self, world, engine, state):
        super().__init__()

        # --- 【新增】 背景圖片載入與設定 ---
        try:
            # 1. 載入圖片檔案 (請確保 background.png 在同一目錄下)
            # 使用 self.bg_image 保持引用，防止被垃圾回收
            self.bg_image = tk.PhotoImage(file="background.png")

            # 2. 創建一個 Label 來顯示圖片
            background_label = tk.Label(self, image=self.bg_image)

            # 3. 使用 place 將圖片鋪滿整個視窗 (relwidth=1, relheight=1)
            background_label.place(x=0, y=0, relwidth=1, relheight=1)

            # 4. 將背景 Label 推到最底層，確保它在所有元件的下面
            background_label.lower()
            print("背景圖片 'background.png' 載入成功！")

        except Exception as e:
            # 如果找不到檔案或格式錯誤，印出訊息，但程式繼續執行（使用預設背景）
            print(f"背景圖片載入失敗 (將使用預設背景): {e}")
        # --- 【新增結束】 ---

        # --- 新增樣式設定 ---
        style = ttk.Style()
        # 定義一個用於選中分頁的高亮樣式
        style.configure('Accent.TButton', background='#4a90e2', foreground='white')
        style.map('Accent.TButton', background=[('active', '#3c79bd')])
        self.title("文字冒險（滑鼠點擊版）")
        self.geometry("1600x900")
        self.minsize(1600, 900)

        self.world = world
        self.engine = engine
        self.state  = state

        # I/O 綁定到 GUI
        self.engine.say = self.say
        self.engine.hub.attach_all(say=self.say, world=self.world, hub = self.engine.hub)
        
        # 傳更新函式給combat_engine
        self.engine.combat.set_ui_refresh(self.refresh_all)

        # 左側：標題/描述/輸出
        # 【修改】嘗試使用更接近舊紙張的顏色搭配，並利用邊框製造層次感
        
        # 定義顏色
        paper_bg = "#e8dcc5"     # 稍微帶點灰黃的舊紙色
        paper_border = "#8c7b6a" # 邊框顏色
        ink_fg = "#2b1e16"       # 墨水色
        heading_fg = "#4a3225"

        # 左側容器 Frame
        # 使用較粗的 highlightthickness 和特定的顏色來模擬紙張邊緣
        left = tk.Frame(self, bg=paper_bg, 
                        highlightbackground=paper_border, highlightcolor=paper_border, highlightthickness=3,
                        padx=12, pady=12)
        # 增加外部 pady，讓它離視窗頂部和底部遠一點，增加「浮現感」
        left.pack(side="left", fill="both", expand=True, padx=30, pady=(30, 50))

        # 房間標題 Label
        self.lbl_room = tk.Label(left, text="", font=("Noto Sans CJK TC", 18, "bold"),
                                 bg=paper_bg, fg=heading_fg)
        self.lbl_room.pack(anchor="w", pady=(0, 15))

        # 房間描述文字框
        # 這裡加回一點點 bd (邊框深度)，讓文字區微微下陷，增加立體感
        self.txt_desc = tk.Text(left, height=5, wrap="word", state="disabled",
                                bg=paper_bg, fg=ink_fg,
                                font=("Noto Sans CJK TC", 13),
                                bd=2, relief="sunken", # 微凹陷效果
                                padx=10, pady=10)
        self.txt_desc.pack(fill="x", pady=(0, 20))

        # 遊戲紀錄文字框
        self.txt_log = tk.Text(left, wrap="word", state="disabled",
                               bg=paper_bg, fg=ink_fg,
                               font=("Noto Sans CJK TC", 13),
                               bd=2, relief="sunken", # 微凹陷效果
                               padx=10, pady=10)
        self.txt_log.pack(fill="both", expand=True)

        # 右側：固定使用新版 ActionMenu
        self.right_col = ttk.Frame(self)
        self.right_col.pack(side="right", fill="y", padx=6, pady=6)

        # 1) 情境動作選單
        self.action_menu = ActionMenu(
            self.right_col,
            self,
            self.engine,
            self.world,
            self.state,
        )

        # 2) 隊伍狀態（永遠在按鍵列下面）
        self.roster = RosterPanel(
            self.right_col,
            self.world,
            self.engine,
            self.state,
            self.refresh_all,
        )
        self.roster.pack(fill="x", pady=(6, 6))

        # 3) 彈性空白：撐開讓地圖貼底
        ttk.Frame(self.right_col).pack(fill="both", expand=True)

        # 4) 右下角固定方位小地圖
        self.map_positions = compute_grid_positions(self.world)
        self.minimap = FixedMiniMap(
            self.right_col,
            self.world,
            self.state,
            on_click_neighbor=self._try_go_room,
            positions=self.map_positions,
        )
        self.minimap.pack(fill="x", side="bottom")
        
        # === 【修改】 戰鬥：敵人狀態 ===
        
        # enemy_frame 現在是動態容器，在 RosterPanel 之上
        self.enemy_frame = ttk.Frame(self.right_col, padding=(0, 6, 0, 0)) 
        
        # 【新增】 用一個字典來存放動態產生的敵人 UI 元件
        # 格式: { "enemy_combat_id": {"frame": widget, "hp_bar": widget, "hp_label": widget}, ... }
        self.enemy_widgets: Dict[str, Dict[str, Any]] = {}

        # --- 【移除】所有舊的單一敵人 tk.StringVar 和靜態 UI 元件 ---
        # (self.var_enemy_name, lbl_enemy_name, enemy_hp_bar, lbl_enemy_hp 等... 都移除)

        # 底部：快捷
        bottom = ttk.Frame(self)
        bottom.place(relx=0.5, rely=1.0, anchor="s")
        ttk.Button(bottom, text="重新整理", command=self.refresh_all).pack(side="left", padx=4)
        ttk.Button(bottom, text="退出", command=self.destroy).pack(side="left", padx=4)

        self.refresh_all()

    # --- I/O ---
    def _append_text(self, widget: tk.Text, text: str):
        widget.config(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.config(state="disabled")

    def say(self, s: str,*_):
        self._append_text(self.txt_log, s)

    # --- 房間渲染 ---
    def render_room(self):
        room = self.world["rooms"][self.state.room_id]
        self.lbl_room.configure(text=f"{room['name']}")
        self.txt_desc.config(state="normal")
        self.txt_desc.delete("1.0", "end")
        desc = f"{room['desc']}\n"
        if room.get("npcs"):
            names = [self.world["npcs"].get(nid, {}).get("name", nid) for nid in room["npcs"]]
            desc += "你看到：" + "、".join(names) + "\n"
        exits = room.get("exits", {})
        if exits:
            desc += "出口：" + "、".join(exits.keys())
        self.txt_desc.insert("end", desc)
        self.txt_desc.config(state="disabled")

    # --- 右側動作選單渲染 ---
    def render_menu(self):
        self.action_menu._populate_context()

    # 【移除】 render_status(self)
    # 這個函數的功能已經被 RosterPanel.render() 取代，
    # TkApp 不再需要自己管理玩家的 var_hp, var_exp 等變數。

    def _clear_enemy_widgets(self):
        """【新增】輔助函數：清除所有敵人的 UI 元件並清空追蹤字典"""
        for widgets in self.enemy_widgets.values():
            if widgets.get("frame"):
                widgets["frame"].destroy()
        self.enemy_widgets.clear()

    def render_enemy_status(self):
        """【完全重寫】以支援多敵人 UI"""
        cb = self.state.combat
        
        # 1. 戰鬥未開始：隱藏框架並清除所有舊元件
        if not cb.active or not cb.enemies:
            if self.enemy_frame.winfo_ismapped():
                self.enemy_frame.pack_forget()
            self._clear_enemy_widgets()
            return

        # 2. 戰鬥已開始：確保框架可見
        if not self.enemy_frame.winfo_ismapped():
            # 確保敵人框架顯示在 RosterPanel (隊伍面板) 的上方
            self.enemy_frame.pack(fill="x", padx=0, pady=(0,6), before=self.roster)

        current_enemy_ids = set(cb.enemies.keys())
        displayed_enemy_ids = set(self.enemy_widgets.keys())

        # 3. 移除已死亡/消失的敵人 UI
        ids_to_remove = displayed_enemy_ids - current_enemy_ids
        for enemy_id in ids_to_remove:
            widgets = self.enemy_widgets.pop(enemy_id, {})
            if widgets.get("frame"):
                widgets["frame"].destroy()

        # 4. 更新/新增 顯示的敵人 UI
        # (使用 enumerate 方便未來做 grid 佈局)
        for i, (enemy_id, profile) in enumerate(cb.enemies.items()):
            
            hp = int(profile.hp)
            hpmax = int(profile.max_hp if profile.max_hp else max(1, hp))

            if enemy_id not in self.enemy_widgets:
                # --- 4a. 建立新敵人的 UI ---
                
                # 每個敵人都用一個 frame 包起來
                e_frame = ttk.Frame(self.enemy_frame)
                e_frame.pack(fill="x", pady=(0, 4)) # 每個敵人佔一行

                # 名字標籤
                e_name_label = ttk.Label(e_frame, text=profile.name)
                e_name_label.grid(row=0, column=0, sticky="w")
                
                # (未來可在此加入等級標籤)
                
                # HP 標籤 (例如 "HP")
                ttk.Label(e_frame, text="HP").grid(row=1, column=0, sticky="w", pady=(0,2))
                
                # HP 血條
                e_hp_bar = ttk.Progressbar(e_frame, orient="horizontal", mode="determinate", length=180, maximum=hpmax, value=hp)
                e_hp_bar.grid(row=1, column=1, sticky="w", padx=(4,0), pady=(0,2))
                
                # HP 文字 (例如 "50/100")
                e_hp_label = ttk.Label(e_frame, text=f"{hp}/{hpmax}", width=8) # 設 width 避免變動
                e_hp_label.grid(row=1, column=2, sticky="w", padx=(6,0), pady=(0,2))
                
                # (未來可在此加入特性、裝備標籤)
                
                # 儲存 UI 元件以便更新
                self.enemy_widgets[enemy_id] = {
                    "frame": e_frame,
                    "name_label": e_name_label,
                    "hp_bar": e_hp_bar,
                    "hp_label": e_hp_label,
                }
                
            else:
                # --- 4b. 更新現有敵人的 UI ---
                widgets = self.enemy_widgets[enemy_id]
                widgets["hp_bar"].configure(maximum=hpmax, value=hp)
                widgets["hp_label"].configure(text=f"{hp}/{hpmax}")
                # (如果名字或特性會動態改變，也要在這裡更新)
                # widgets["name_label"].configure(text=profile.name)


    def refresh_all(self):
        self.render_room()
        self.render_menu()
        if hasattr(self, "roster"):
            self.roster.render()

        # 【移除】 舊的 self.render_status()
        
        self.render_enemy_status() # 【修改】呼叫新的多敵人版本

        if hasattr(self, "minimap"):
            self.minimap.render()
            
    # 給 ActionMenu 使用的移動 callback；遊戲規則由 NavigationSystem 處理。
    def on_go(self, direction: str):
        result = self.engine.fire(
            "go",
            self.state,
            direction=direction,
        )
        if isinstance(result, dict) and result.get("ok", False):
            self.refresh_all()

    # 供小地圖點擊：只允許相鄰房間（避免瞬移）。
    def _try_go_room(self, target_rid: str):
        exits = (
            self.world["rooms"]
            .get(self.state.room_id, {})
            .get("exits")
            or {}
        )
        direction = next(
            (name for name, room_id in exits.items() if room_id == target_rid),
            None,
        )
        if direction is None:
            self.say("（只能點擊相鄰房間移動）")
            return

        self.on_go(direction)
