from state import GameState
from loader import load_world
from engine import Engine
from commands import cmd_look, cmd_inv, cmd_go, cmd_use, cmd_talk, cmd_give

class Console:
    def read(self): return input("> ")
    def write_line(self, s): print(s)

def main():
    io = Console()
    world, eventbook = load_world(base="../data/beginner")
    state = GameState()
    engine = Engine(world, eventbook, io.write_line)

    io.write_line("文字冒險開始。輸入 look / inv / go / use / talk / give / quit")
    cmd_look(io, world, state, ())
    while True:
        raw = io.read().strip()
        if not raw: continue
        if raw.lower() in ("quit","exit"): break
        parts = raw.split()
        cmd, args = parts[0].lower(), parts[1:]
        if   cmd == "look": cmd_look(io, world, state, args)
        elif cmd == "inv":  cmd_inv(io, world, state, args)
        elif cmd == "go":   cmd_go(io, world, state, args)
        elif cmd == "use":  cmd_use(io, engine, state, args)
        elif cmd == "talk": cmd_talk(io, engine, state, args)
        elif cmd == "give": cmd_give(io, engine, state, args)
        else: io.write("不認識的指令。")

if __name__ == "__main__":
    main()
