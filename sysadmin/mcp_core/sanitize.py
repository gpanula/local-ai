"""Script sanitization helpers extracted from ``mcp_client.py``."""

import re
import textwrap


def sanitize_script_code(code: str) -> str:
    """Sanitizes extracted code block: unindents common leading indentation, strips pseudocode heredoc wrappers, and enforces column-0 heredoc delimiters."""
    dedented = textwrap.dedent(code).strip()

    # Unwrap if wrapped in pseudocode or heredocs (e.g. `write_file ... <<EOF\n#!/bin/bash\n...\nEOF` or `cat <<'EOF' > ...`)
    if not dedented.startswith("#!"):
        shebang_match = re.search(r"(#!/(?:usr/)?bin/(?:env\s+)?bash\b[\s\S]*)", dedented)
        if shebang_match:
            inner = shebang_match.group(1).strip()
            # Strip trailing closing heredoc delimiter or closing function brace if present
            inner = re.sub(r"\n\s*(?:EOF|EOT|ENDOFFILE|EOL|\})\s*$", "", inner)
            dedented = inner.strip()

    # Normalize indented closing delimiters for heredocs (e.g. '   EOF' -> 'EOF')
    sanitized = re.sub(r"^[ \t]+(EOF|EOT|ENDOFFILE|EOL)\b", r"\1", dedented, flags=re.MULTILINE)
    return sanitized
