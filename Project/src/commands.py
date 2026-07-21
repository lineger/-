def cmd_look(io, world, state, _):
    room = world["rooms"][state.room_id]
    io.say(f"{room['name']}：{room['desc']}")
    if room.get("npcs"):
        names = [world["npcs"][nid]["name"] for nid in room["npcs"]]
        io.say("你看到：" + "、".join(names))
    io.say("出口：" + "、".join(room["exits"].keys()))

def cmd_inv(io, _world, state, _):
    bag = getattr(getattr(state, "inventory", None), "items", []) or []
    io.say("背包：" + (", ".join(bag) if bag else "（空）"))

def cmd_go(io, world, state, args):
    if not args:
        return io.write_line("用法：go <方向>")
    d = args[0].lower()
    room = world["rooms"][state.room_id]
    to = room["exits"].get(d)
    if not to:
        return io.write_line("那邊走不通。")
    state.room_id = to
    cmd_look(io, world, state, ())
    _maybe_monster_ambush(io, state)
