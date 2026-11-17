#!/usr/bin/env python3
"""Where the scripts will find tesseract and soffice (lib/tesseract.py,
lib/office.py), for check_env.sh.

    find_tools.py tesseract|soffice   print that tool's path, nothing if missing
    find_tools.py                     write runs/env.json and print its path
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import office  # noqa: E402
import tesseract as tesseract_lib  # noqa: E402

ENV_JSON = Path("runs") / "env.json"


def main() -> None:
    tools = {"tesseract": tesseract_lib.find_tesseract(), "soffice": office.find_soffice()}
    if len(sys.argv) > 1:
        print(tools[sys.argv[1]] or "", end="")  # no newline: sh's $(...) would keep a Windows \r
        return
    ENV_JSON.parent.mkdir(parents=True, exist_ok=True)
    ENV_JSON.write_text(json.dumps(tools, indent=2) + "\n", encoding="utf-8")
    print(ENV_JSON.as_posix(), end="")


if __name__ == "__main__":
    main()
