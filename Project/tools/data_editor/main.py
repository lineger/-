from __future__ import annotations

import argparse
from pathlib import Path
import sys

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from editor_app import DataEditorApp


def default_data_dir() -> Path:
    return TOOL_DIR.parents[1] / "data" / "beginner"


def main() -> None:
    parser = argparse.ArgumentParser(description="遊戲 JSON 資料編輯器")
    parser.add_argument("data_dir", nargs="?", default=str(default_data_dir()), help="資料目錄，預設為 Project/data/beginner")
    args = parser.parse_args()
    app = DataEditorApp(args.data_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
