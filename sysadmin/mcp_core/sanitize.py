"""Script sanitization helpers extracted from ``mcp_client.py``."""

import re
import textwrap


def sanitize_script_code(code: str) -> str:
    """Sanitizes extracted code block: unindents common leading indentation and enforces column-0 heredoc delimiters."""
    dedented = textwrap.dedent(code).strip()
    # Normalize indented closing delimiters for heredocs (e.g. '   EOF' -> 'EOF')
    sanitized = re.sub(r"^[ \t]+(EOF|EOT|ENDOFFILE)\b", r"\1", dedented, flags=re.MULTILINE)
    return sanitized
