from UI.ui_tk import TkApp
from Data.loader import load_world
from engine import Engine
from Data.state import GameState
from UI.menu import build_menu  # 舊版才用得到
from System.Skill.skill_runtime import register_skills_from_mapping # 技能物件載入

def main():
    world, eventbook = load_world(base="../data/beginner") 
    register_skills_from_mapping(world, world.get("skills"))
    engine = Engine(world, eventbook, say=print)  # say 會在 TkApp 內被覆蓋
    # 切換：True 用右側 ActionMenu；False 用舊版列表
    USE_ACTION_MENU = True
    app = TkApp(world, engine, state=GameState(),  # 你的建立 state 的方式
                build_menu_fn=(None if USE_ACTION_MENU else build_menu),
                use_action_menu=USE_ACTION_MENU)
    app.mainloop()

if __name__ == "__main__":
    main()
