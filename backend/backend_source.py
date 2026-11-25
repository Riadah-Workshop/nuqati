"""Test support: the backend source as ONE text, whichever module a piece of code lives in.

`app/main.py` only assembles the API; the code lives in `app/api_app.py` and `app/features/*.py`.
Several contract tests assert on code text, so they read it through `read_backend_source()` instead of
hard-coding a file. Order: api_app, the feature modules in the order `main.py` imports them, any other
feature module (sorted), then main.py. Text ranges between two markers therefore keep working.
"""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent / "app"


def backend_source_files():
    main = (APP / "main.py").read_text(encoding="utf-8")
    ordered = re.findall(r"^from \.features import (\w+)", main, flags=re.M)
    on_disk = sorted(p.stem for p in (APP / "features").glob("*.py") if p.stem != "__init__")
    names = ordered + [n for n in on_disk if n not in ordered]
    return [APP / "api_app.py"] + [APP / "features" / f"{n}.py" for n in names] + [APP / "main.py"]


def read_backend_source():
    return "\n".join(p.read_text(encoding="utf-8") for p in backend_source_files())
