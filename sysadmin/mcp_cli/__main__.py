import os
import sys

# Deterministic Virtual Environment Bootstrap (Rule 2 AGENTS.md)
_this_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
_venv_dir = os.path.join(_this_dir, "venv")
_venv_python = os.path.join(_venv_dir, "bin", "python3")
if os.path.exists(_venv_python) and sys.prefix != _venv_dir:
    os.execv(_venv_python, [_venv_python] + sys.argv)

if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

from mcp_cli.cli import main

if __name__ == "__main__":
    main()
