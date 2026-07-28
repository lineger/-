from __future__ import annotations

from pathlib import Path
import runpy


if __name__ == "__main__":
    tool = Path(__file__).resolve().parent / "tools" / "data_editor" / "main.py"
    runpy.run_path(str(tool), run_name="__main__")
