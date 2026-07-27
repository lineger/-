import tkinter as tk
import time
from Application.game_queries import get_inventory_view, get_room_view
from System.combat_engine import CooldownBox
from Data.skills import list_actor_skills



class PollingTooltipManager:
    """輪詢式 Tooltip：每 poll_ms 檢查滑鼠下方是否有 tooltip_text。"""
    def __init__(self, container, delay_ms=600, wrap_px=300, poll_ms=120, topmost=True):
        self.container = container
        self.delay = delay_ms / 1000.0
        self.wrap = wrap_px
        self.poll = poll_ms
        self.topmost = topmost
        self._tip = None
        self._hover_widget = None
        self._hover_since = 0.0
        self._running = True
        container.bind("<Destroy>", self._on_destroy, add="+")
        self._tick()

    def reset(self):
        self._hover_widget = None
        self._hover_since = 0.0
        self._hide()

    def _on_destroy(self, _):
        self._running = False
        self._hide()

    def _same_toplevel(self, w):
        try:
            return w.winfo_toplevel() is self.container.winfo_toplevel()
        except tk.TclError:
            return False

    def _find_with_tooltip(self, w):
        while w and w is not self.container:
            if getattr(w, "tooltip_text", ""):
                return w
            w = getattr(w, "master", None)
        return None

    def _tick(self):
        if not self._running:
            return
        try:
            x, y = self.container.winfo_pointerx(), self.container.winfo_pointery()
            w = self.container.winfo_containing(x, y)
        except tk.TclError:
            w = None

        if not (w and self._same_toplevel(w)):
            self._hover_widget = None
            self._hover_since = 0.0
            self._hide()
        else:
            ww = self._find_with_tooltip(w)
            if ww is not self._hover_widget:
                self._hover_widget = ww
                self._hover_since = time.time() if ww else 0.0
                self._hide()
            else:
                if ww and (time.time() - self._hover_since) >= self.delay:
                    self._show_at(x, y, ww.tooltip_text)

        self.container.after(self.poll, self._tick)

    def _show_at(self, x_root, y_root, text):
        if self._tip or not text:
            return
        tip = tk.Toplevel(self.container)
        tip.wm_overrideredirect(True)
        if self.topmost:
            try: tip.attributes("-topmost", True)
            except tk.TclError: pass
        tip.wm_geometry(f"+{x_root+16}+{y_root+12}")
        tk.Label(
            tip, text=text, justify="left",
            relief="solid", borderwidth=1, padx=8, pady=6,
            background="#ffffe0", wraplength=self.wrap
        ).pack()
        self._tip = tip

    def _hide(self):
        if self._tip is not None:
            try: self._tip.destroy()
            except tk.TclError: pass
            self._tip = None


class ActionMenu:
    """
    一排動作（action bar） + 右側/下方的情境候選清單。
    流程：
      1) 點動作 -> 設定 pending_verb
      2) 根據 verb 與當前房間/背包，列出候選
      3) 點候選 -> 直接 fire 或進下一步（例如 Give 需要先選 NPC 再選物品）
    """
    def __init__(self, root, io, engine, world, state):
        self.root   = root
        self.io     = io
        self.engine = engine
        self.world  = world
        self.state  = state

        self.pending_verb   = None
        self.pending_target = None  # for give: 先選 NPC，再選 item
        self.pending_item_id = None # 【新增】用於儲存選擇的 skill_id

        # UI 容器
        self.bar  = tk.Frame(root)
        self.list = tk.Frame(root)

        self.bar.pack(fill="x")
        self.list.pack(fill="x")

        self._build_action_bar()
        self._bar_tooltip = PollingTooltipManager(self.bar, delay_ms=600, poll_ms=120)
        self._populate_context()  # 預設無動作 -> 清空

    # ---------- 一排動作 ----------
    def _build_action_bar(self):
        for w in self.bar.winfo_children(): w.destroy()
        if self.engine.combat.in_battle(self.state):          
            ACTIONS = [("攻擊","attack"),("施法","cast"),("防禦","defend"),("逃跑","flee"),("Status","status")]
        else:
            ACTIONS = [("前往","go"),("對話","talk_open"),("使用","use"),("給予","give"),("查看","look"),
                   ("背包 ","inv"),("突擊","ambush"),("裝備","equip"),("任務","quest_log"),("結束","quit")]
        tooltips = {
            "cast": "施放技能：打開右側技能清單，滑到技能可看說明。",
            "quest_log": "查看當前已接受和已完成的任務清單。",
        }

        for label, verb in ACTIONS:
            btn = tk.Button(
                self.bar,
                text=label,
                command=lambda v=verb: self._choose_action(v),
            )
            btn.pack(side="left", padx=4, pady=4)

            tooltip = tooltips.get(verb)
            if tooltip:
                btn.tooltip_text = tooltip

    def _choose_action(self, verb):
        self.pending_verb   = verb
        self.pending_target = None
        self.pending_item_id = None # 【新增】重置 pending_item_id
        self._populate_context()

    # ---------- 列出候選 ----------
    def _clear_list(self):
        for w in self.list.winfo_children():
            w.destroy()

    def _add_option(self, text, on_click, disabled=False, tooltip: str = ""):
        state = tk.DISABLED if disabled else tk.NORMAL
        b = tk.Button(self.list, text=text, command=on_click, anchor="w", state=state)
        b.pack(fill="x", padx=6, pady=2)
    
        if tooltip:
            b._tooltip = HoverTooltip(b, tooltip, delay=2000)  # ★ 保留引用！
        return b

    # 小工具：呼叫函式 → 自動刷新
    def _run_and_refresh(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        # after 需要一個「可呼叫物件」，不能在這裡就呼叫
        cb = self.io.refresh_all if hasattr(self.io, "refresh_all") else self.root.update
        self.root.after(0, cb)

    def _show_room_summary(self):
        view = get_room_view(self.world, self.state)
        self.io.say(f"{view['name']}：{view['description']}")
        if view["npc_names"]:
            self.io.say("你看到：" + "、".join(view["npc_names"]))
        self.io.say("出口：" + ("、".join(view["exits"]) if view["exits"] else "（無）"))

    def _show_inventory_summary(self):
        items = get_inventory_view(self.world, self.state)
        names = [item["name"] for item in items]
        self.io.say("背包：" + ("、".join(names) if names else "（空）"))

    def _select_skill_for_cast(self, skill_id: str):
        """
        【修改】不再自動對自己施放。
        無論什麼技能，都進入「選擇目標」階段，讓玩家有最大的自由度。
        """
        sk = self.engine.world["skills"].get(skill_id)
        if not sk: return
        self.pending_item_id = skill_id
        self._populate_context()

    def _list_combat_targets(self, action: str, item_id: str | None = None, scope: str = "all"):
        """
        【修改】列出戰鬥目標 (scope: "all", "enemies", "allies")
        """
        actor_id = self.state.combat.active_id
        targets_listed = False

        # 1. 列出敵人 (if scope allows)
        if scope in ("all", "enemies"):
            enemies_dict = self.state.combat.enemies
            for enemy_id, profile in enemies_dict.items():
                enemy_name = profile.name
                self._add_option(
                    f"-> {enemy_name} (敵人)",
                    lambda target=enemy_id: self._run_and_refresh(
                        self.engine.fire, "combat_act", self.state,
                        actor_id=actor_id, action=action, item_id=item_id, target_id=target
                    )
                )
                targets_listed = True
            
            if not enemies_dict and scope == "enemies":
                targets_listed = False # 強制顯示 "沒有可選目標"

        # 2. 列出盟友 (if scope allows)
        if scope in ("all", "allies"):
            allies = self.state.facts.get("_party_members", [])
            for ally_id in allies:
                if ally_id in self.state.combat.turn_queue: # 確保還在戰鬥中
                    ally_name = self.engine.combat._name_of(self.state, ally_id)
                    self._add_option(
                        f"-> {ally_name} (盟友)",
                        lambda target=ally_id: self._run_and_refresh(
                            self.engine.fire, "combat_act", self.state,
                            actor_id=actor_id, action=action, item_id=item_id, target_id=target
                        )
                    )
                    targets_listed = True

        # 3. 列出玩家自己 (if scope allows)
        if scope in ("all", "allies"):
            if "$player" in self.state.combat.turn_queue:
                player_name = self.engine.combat._name_of(self.state, "$player")
                self._add_option(
                    f"-> {player_name} (自己)",
                    lambda: self._run_and_refresh(
                        self.engine.fire, "combat_act", self.state,
                        actor_id=actor_id, action=action, item_id=item_id, target_id="$player"
                    )
                )
                targets_listed = True

        if not targets_listed:
            self._add_option("（沒有可選目標）", lambda: None, disabled=True)
        
        # 4. 返回按鈕
        if action == "cast" and item_id:
            self._add_option("← 返回選擇技能", lambda: self._choose_action("cast"))
        else:
            self._add_option("← 返回動作列", lambda: self._choose_action(None))

    def _populate_context(self):
        self._build_action_bar()
        self._clear_list()
        v = self.pending_verb

        # 沒選動作 -> 顯示提示
        if not v:
            self._add_option("請先選一個動作（Talk/Give/Use/Go/...）", lambda: None)
            return

        room = self.world["rooms"][self.state.room_id]

        if v == "quest_log":
            self._add_option("查看任務日誌", lambda: self.engine.fire("quest_log", self.state))
            return

        # ---- 非情境（立即執行）----
        if v == "look":
            self._add_option("查看四周", self._show_room_summary)
            return
        if v == "inv":
            self._add_option("查看背包", self._show_inventory_summary)
            return
        if v == "quit":
            self._add_option("離開遊戲", lambda: self.root.quit())
            return

        # ---- Talk：列出當前房間可交談的 NPC ----
        if v == "talk_open":
            had_any = False
            for nid in room.get("npcs", []):
                npc = self.world["npcs"].get(nid)
                if not npc:
                    continue
                if self.engine.can_fire("talk_open", self.state, target_id=nid):
                    had_any = True

                    def _open_and_list_topics(nid=nid):
                        # 1) 取 payload
                        payload = self.engine.fire("talk_open", self.state, target_id=nid)

                        # 2) 清空清單，先畫 NPC 面板
                        self._clear_list()
                        if isinstance(payload, dict):
                            name    = payload.get("name", nid)
                            level   = payload.get("level", 1)
                            faction = payload.get("faction", "-")
                            job     = payload.get("job", "-")
                            labels  = payload.get("attitudes", [])
                            primary = payload.get("primary_attitude", "-")

                            # 面板容器
                            panel = tk.Frame(self.list, bd=1, relief="groove")
                            panel.pack(fill="x", padx=6, pady=(4, 8))

                            # 標題：名字＋等級
                            tk.Label(panel, text=f"{name}（Lv.{level}）", anchor="w",
                                     font=("Microsoft JhengHei UI", 12, "bold")).pack(fill="x", padx=6, pady=(4,2))
                            # 基本資料行
                            tk.Label(panel, text=f"陣營：{faction}    職業：{job}", anchor="w").pack(fill="x", padx=6, pady=1)
                            # 態度行（主標籤＋前三個）
                            labline = "、".join(labels) if labels else "-"
                            tk.Label(panel, text=f"態度：{primary}（{labline}）", anchor="w").pack(fill="x", padx=6, pady=(0,6))

                            # 分隔標題：可聊話題
                            tk.Label(self.list, text="— 可聊話題 —", anchor="w").pack(fill="x", padx=6, pady=(0,4))

                        

                        # 3) 列出話題按鈕
                        opts = (payload or {}).get("options", []) if isinstance(payload, dict) else []
                        if not opts:
                            self._add_option("（目前沒有可聊的話題）", lambda: None)
                            self._add_option("← 返回 NPC 清單", lambda: self._choose_action("talk_open"))
                            return

                        for opt in opts:
                            topic_id = opt["id"]
                            label    = opt.get("text", topic_id)
                            self._add_option(
                                f"＞ {label}",
                                lambda t=topic_id, nid2=nid: self._run_and_refresh(
                                    self.engine.fire, "talk_say", self.state, topic_id=t, target_id=nid2
                                )
                            )

                        # 在 NPC 面板下方加「招募/請回」按鈕（依 can_fire 顯示）

                        def _do_recruit(nid=nid):
                            res = self.engine.fire("recruit", self.state, target_id=nid)
                            msg = (res or {}).get("text")
                            if msg: self.io.say(msg)
                            self._populate_context()  # 右欄重算
                            if hasattr(self.io, "refresh_all"): self.io.refresh_all()

                        def _do_dismiss(nid=nid):
                            res = self.engine.fire("dismiss", self.state, target_id=nid)
                            msg = (res or {}).get("text")
                            if msg: self.io.say(msg)
                            self._populate_context()
                            if hasattr(self.io, "refresh_all"): self.io.refresh_all()

                        if self.engine.can_fire("recruit", self.state, target_id=nid):
                            self._add_option("＞ 招募成隊友",lambda nid=nid: self._run_and_refresh(self.engine.fire, "recruit", self.state, target_id=nid))
                        if self.engine.can_fire("dismiss", self.state, target_id=nid):
                            self._add_option("＞ 請滾出去",lambda nid=nid: self._run_and_refresh(self.engine.fire, "dismiss", self.state, target_id=nid))


                        # 4) 返回 NPC 清單
                        self._add_option("← 返回 NPC 清單", lambda: self._choose_action("talk_open"))

                    # NPC 清單按鈕
                    self._add_option(f"和 {npc['name']} 說話", _open_and_list_topics)

            if not had_any:
                self._add_option("這裡沒有可以說話的人。", lambda: None)
            return
        
        # ---- Use：列出背包中目前可使用的物品 ----
        if v == "use":
            for item_id in self.state.inventory:
                if self.engine.can_fire("use", self.state, item_id=item_id):
                    it = self.world["items"].get(item_id, {"name": item_id})
                    self._add_option(f"使用 {it['name']}", lambda iid=item_id: self.engine.fire("use", self.state, item_id=iid))
            if not any(True for _ in self.list.winfo_children()):
                self._add_option("目前沒有可以使用的物品。", lambda: None)
            return

        # ---- Go：列出可前往的方向，實際移動統一交給 NavigationSystem ----
        if v == "go":
            for direction, to_rid in (room.get("exits") or {}).items():
                if not self.engine.can_fire(
                    "go",
                    self.state,
                    direction=direction,
                ):
                    continue

                to_room = self.world["rooms"].get(to_rid, {"name": to_rid})
                self._add_option(
                    f"往 {direction}（{to_room['name']}）",
                    lambda d=direction: self.io.on_go(d),
                )

            if not self.list.winfo_children():
                self._add_option("沒有可去的方向。", lambda: None)
            return

        # ---- Give：兩段式（先選 NPC，再選背包裡可交付的物品） ----
        if v == "give":
            # 尚未選 NPC -> 列 NPC
            if self.pending_target is None:
                for nid in room.get("npcs", []):
                    npc = self.world["npcs"].get(nid)
                    if not npc:
                        continue
                    # 檢查是否「存在某些禮物規則」即可（不在這一步看背包）
                    if npc.get("gifts"):
                        self._add_option(f"給予→ {npc['name']}", 
                                         lambda nid=nid: self._on_choose_give_target(nid))
                if not any(True for _ in self.list.winfo_children()):
                    self._add_option("這裡沒有適合給東西的人。", lambda: None)
                return
            # 已選 NPC -> 列玩家背包中「該 NPC 接受」的物品
            else:
                npc = self.world["npcs"].get(self.pending_target, {})
                gifts = npc.get("gifts", {})
                # 過濾玩家擁有 & NPC 接受
                had_any = False
                for item_id in self.state.inventory:
                    if item_id in gifts and self.engine.can_fire("give", self.state, item_id=item_id, target_id=self.pending_target):
                        it = self.world["items"].get(item_id, {"name": item_id})
                        self._add_option(f"交給 {npc.get('name', self.pending_target)}：{it['name']}",
                                         lambda iid=item_id: self.engine.fire("give", self.state, item_id=iid, target_id=self.pending_target))
                        had_any = True
                if not had_any:
                    self._add_option("你身上沒有對方想要的東西。", lambda: None)
                # 也放一個返回鍵
                self._add_option("← 返回選 NPC", lambda: self._choose_action("give"))
                return

        # ---裝備---
        if v == "equip":
        # 可裝備的物品（背包 → 有 slot 的裝備）
            for item_id in (getattr(getattr(self.state, "inventory", None), "items", []) or []):
               if self.engine.can_fire("equip", self.state, item_id=item_id):
                    it = self.world["items"].get(item_id, {"name": item_id})
                    # ⬇︎ 關鍵：用 run_and_refresh 包起來，裝備後一定刷新
                    self._add_option(
                        f"裝備 {it['name']}",
                        lambda iid=item_id: self._run_and_refresh(
                            self.engine.fire, "equip", self.state, item_id=iid
                        )
                    )
            if not any(True for _ in self.list.winfo_children()):
                self._add_option("目前沒有可以裝備的物品。", lambda: None)
                return

        # 可卸下的槽位
            for slot, cur in (getattr(getattr(self.state, "inventory", None), "equipment", {}) or {}).items():
                if cur and self.engine.can_fire("unequip", self.state, slot=slot):
                    name = self.world["items"].get(cur, {}).get("name", cur)
                    self._add_option(f"卸下 {slot}: {name}",
                        lambda _slot=slot: self.engine.fire("unequip", self.state, slot=_slot))
            return

        # ---突擊---
        if v == "ambush":
            if self.engine.can_fire("ambush", self.state):
                self._add_option("主動發起突擊！", lambda: self.engine.fire("ambush", self.state))
            else:
                self._add_option("這裡暫時沒有可以突擊的對手。", lambda: None)
            return

        

        # --- 戰鬥選單 ---
        if self.engine.combat.in_battle(self.state):
            cd_box = CooldownBox(self.state)
            actor_id = getattr(self.state.combat, "active_id", None)
            who_name = "你" if actor_id == "$player" else self.world.get("npcs", {}).get(actor_id, {}).get("name", actor_id or "-")
            
            # 顯示當前回合
            self._add_option(f"— 現在輪到：{who_name} —", lambda: None, disabled=True) # MODIFIED: disabled=True

            # 【新邏輯開始】
            
            # 情況 1：選擇 "攻擊 (attack)"
            if v == "attack":
                self._add_option(f"攻擊 (Attack) -> 選擇目標...", lambda: None, disabled=True)
                self._list_combat_targets(action="attack", scope="all")
                return # 結束

            # 情況 2：選擇 "施法 (cast)"
            if v == "cast":
                # 步驟 2.1：尚未選擇技能 (pending_item_id is None) -> 列出技能
                if self.pending_item_id is None:
                    self._add_option(f"施法 (Cast) -> 選擇技能...", lambda: None, disabled=True)
                    skill_ids = list_actor_skills(self.state, actor_id) #

                    if not skill_ids:
                        self._add_option("（沒有可用技能）", lambda: None)
                    else:
                        for sid in skill_ids:
                            sk = self.engine.world["skills"].get(sid)
                            cd_rem = int(cd_box.get(actor_id, sid) or 0)
                            name = getattr(sk, "name", (sk.get("name") if isinstance(sk, dict) else sid))
                            # ... (省略 desc 獲取)
                            
                            disabled = cd_rem > 0
                            label = f"施放：{name}"
                            if disabled:
                                label += f" (CD:{cd_rem})"
                            
                            # 【修改】點擊技能按鈕，不再是 fire，而是呼叫 _select_skill_for_cast
                            self._add_option(
                                label,
                                lambda skill=sid: self._select_skill_for_cast(skill), # MODIFIED
                                disabled=disabled, 
                                tooltip="" # (Tooltip 邏輯不變)
                            )
                    
                    self._add_option("← 返回動作列", lambda: self._choose_action(None))
                    return # 結束

                # 步驟 2.2：已經選擇技能 (pending_item_id is not None) -> 列出目標
                else:
                    skill_id = self.pending_item_id
                    sk = self.engine.world["skills"].get(skill_id)
                    skill_name = getattr(sk, "name", (sk.get("name") if isinstance(sk, dict) else skill_id))
                    
                    self._add_option(f"施放 [{skill_name}] -> 選擇目標...", lambda: None, disabled=True)
                    
                    
                    # 【關鍵修改】 不管技能定義的 target 是什麼，一律允許選擇所有目標 (all)
                    self._list_combat_targets(action="cast", item_id=skill_id, scope="all")
                    return # 結束
                
            # 情況 3：選擇 "防禦 (defend)" (無目標，立即執行)
            if v == "defend":
                self._add_option("架勢防禦",lambda a=actor_id: self._run_and_refresh(self.engine.fire, "combat_act", self.state,actor_id=a, action="defend"))
                return

            # 情況 4：選擇 "逃跑 (flee)" (無目標，立即執行)
            if v == "flee":
                self._add_option("嘗試逃跑",lambda a=actor_id: self._run_and_refresh(self.engine.fire, "combat_act", self.state,actor_id=a, action="flee"))
                return
            
            # 情況 5: 選擇 "Status" (無目標，立即執行)
            if v == "status":
                self._add_option("查看戰況", lambda: self.run_and_refresh(self.engine.combat.status, self.state))
                return

            # 情況 6：還沒選戰鬥動作
            if v is None or v not in ("attack","cast","defend","flee","status"):
                self._add_option("→ 請選擇戰鬥動作", lambda: None, disabled=True)
                return
        
        # ... (省略非戰鬥的 "else" 區塊)
        
        # 捕捉所有其他未處理的 verb
        self._add_option(f"[未支援] {v}", lambda: None)

    def _on_choose_give_target(self, nid):
        self.pending_target = nid
        self._populate_context()

    def _on_talk_open(self, npc_id: str):
        payload = self.engine.fire("talk_open", self.state, target_id=npc_id)
        # 失敗就顯示訊息並結束
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("text") if isinstance(payload, dict) else "她似乎不想談。"
            self.io.say(msg)
            return

        # 清掉右側子選單（名稱依你的 UI，沒有就略過）
        if hasattr(self, "_clear_submenu"):
            self._clear_submenu()

        # 用 options 建立話題按鈕
        options = payload.get("options", [])
        if not options:
            self._add_option("（目前沒有可聊的話題）", lambda: None)
            return

        for opt in options:
            topic_id = opt["id"]
            label    = opt.get("text", topic_id)
            # 這裡用默認 add_option 或你的子選單方法
            add = getattr(self, "_add_sub_option", self._add_option)
            add(f"＞ {label}", lambda t=topic_id, nid=npc_id: self._on_talk_say(nid, t))

        # 如果可送禮，也給一個入口（可先留著）
        if payload.get("giftable"):
            add = getattr(self, "_add_sub_option", self._add_option)
            add("🎁 送禮…", lambda nid=npc_id: self._on_talk_give_entry(nid))

    def _on_talk_say(self, npc_id: str, topic_id: str):
        res = self.engine.fire("talk_say", self.state, target_id=npc_id, topic_id=topic_id)
        # Engine.fire 已會把 res["text"] 自動 say；這裡只要重刷一次話題即可
        self._on_talk_open(npc_id)
