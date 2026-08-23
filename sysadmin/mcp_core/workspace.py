"""Workspace path resolution and validation shared across MCP tooling.

Canonicalized from ``mcp_ollama/server.py`` semantics: empty/whitespace paths are
rejected and relative paths resolve against ``WORKSPACE_ROOT`` (stricter and safer
than resolving against the caller's current working directory).
"""

import os
import stat

# Repository root (sysadmin/mcp_core/ -> ../../)
WORKSPACE_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def validate_workspace_path(path: str, purpose: str = "file") -> str:
    """Resolve and assert path lies within the workspace root. Returns realpath."""
    if not path or not path.strip():
        raise ValueError(f"Path cannot be empty for {purpose}")
    expanded = os.path.expanduser(path.strip())
    if not os.path.isabs(expanded):
        resolved = os.path.realpath(os.path.join(WORKSPACE_ROOT, expanded))
    else:
        resolved = os.path.realpath(expanded)

    if not (resolved == WORKSPACE_ROOT or resolved.startswith(WORKSPACE_ROOT + os.sep)):
        raise ValueError(f"Rejected {purpose} path outside workspace: {path!r}")
    return resolved


def is_valid_mcp_socket(path: str) -> bool:
    """Verify that the socket exists, is a Unix domain socket, not a symlink, and owned by current user."""
    try:
        st = os.stat(path, follow_symlinks=False)
        return (
            stat.S_ISSOCK(st.st_mode) and
            not stat.S_ISLNK(st.st_mode) and
            st.st_uid == os.getuid()
        )
    except OSError:
        return False
