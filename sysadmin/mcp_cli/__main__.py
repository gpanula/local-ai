"""Enable ``python -m mcp_cli`` as an alternative entry point.

Requires ``sysadmin/`` on ``sys.path`` (run from within ``sysadmin/`` or set
``PYTHONPATH=sysadmin``).
"""

from mcp_cli.cli import main

if __name__ == "__main__":
    main()
