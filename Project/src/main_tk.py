from UI.ui_tk import TkApp
from Data.loader import load_world
from engine import Engine
from Data.state import GameState
from System.Skill.skill_runtime import register_skills_from_mapping # 技能物件載入

def main():
    world, eventbook = load_world(base="../data/beginner") 
    register_skills_from_mapping(world, world.get("skills"))
    engine = Engine(world, eventbook, say=print)  # say 會在 TkApp 內被覆蓋
    app = TkApp(
        world,
        engine,
        state=GameState(),
    )
    app.mainloop()

if __name__ == "__main__":
    main()
