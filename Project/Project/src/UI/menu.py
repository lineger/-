def build_menu(io_like, engine, world, state):
    opts = []

    room = world["rooms"][state.room_id]

    # Look
    def _look():
        txt = f"{room['name']}：{room['desc']}"
        if room.get("npcs"):
            names = [world["npcs"][nid]["name"] for nid in room["npcs"]]
            txt += "\n你看到：" + "、".join(names)
        txt += "\n出口：" + "、".join(room.get("exits", {}).keys())
        io_like.say(txt)
    opts.append(("環顧四周（Look）", _look))

    # Go
    for d, to in room.get("exits", {}).items():
        def _go(dir=d):
            state.room_id = room["exits"][dir]
            _look()
        opts.append((f"往 {d} 前進（Go）", _go))

    # Talk（只列可觸發）
    for nid in room.get("npcs", []):
        npc_name = world["npcs"][nid]["name"]
        if engine.can_fire("talk", state, target_id=nid):
            def _talk(target_id=nid):
                engine.fire("talk", state, target_id=target_id)
            opts.append((f"和 {npc_name} 說話（Talk）", _talk))

    # Use（只列可觸發）
    inventory = list(state.inventory)
    for it in inventory:
        if engine.can_fire("use", state, item_id=it):
            def _use(item_id=it):
                engine.fire("use", state, item_id=item_id)
            opts.append((f"使用 {it}（Use）", _use))

    # Give（只列可觸發）
    for nid in room.get("npcs", []):
        npc_name = world["npcs"][nid]["name"]
        for it in inventory:
            if engine.can_fire("give", state, item_id=it, target_id=nid):
                def _give(item_id=it, target_id=nid):
                    engine.fire("give", state, item_id=item_id, target_id=target_id)
                opts.append((f"把 {it} 交給 {npc_name}（Give）", _give))

    # Inventory
    def _inv():
        s = ", ".join(state.inventory) if state.inventory else "（空）"
        io_like.say("背包：" + s)
    opts.append(("查看背包（Inventory）", _inv))

    return opts
