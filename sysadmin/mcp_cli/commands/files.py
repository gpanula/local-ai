"""Local file read/write commands: write-file, read-file."""

import sys

from mcp_core import transport
from mcp_cli.base import BaseCommand, command


@command
class WriteFileCommand(BaseCommand):
    name = "write-file"
    help = "Write or append content to a local file within the workspace"

    def register_args(self, parser):
        parser.add_argument("path", help="Path to target file (relative to workspace root)")
        parser.add_argument("content", nargs="?", default=None, help="Text content to write (or pass via stdin / --file)")
        parser.add_argument("--file", "-f", default=None, help="Source file to read content from")
        parser.add_argument("--append", "-a", action="store_true", help="Append content instead of overwriting")
        parser.add_argument("--exec", "-x", action="store_true", help="Make file executable (chmod +x)")

    def run(self, args):
        content = args.content
        if args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        elif content is None:
            if not sys.stdin.isatty():
                content = sys.stdin.read()
            else:
                raise ValueError("No content provided. Specify content argument, --file, or pipe via stdin.")
        out = transport.call_mcp("write_file", {
            "path": args.path,
            "content": content,
            "mode": "append" if args.append else "overwrite",
            "make_executable": args.exec,
        })
        print(out)


@command
class ReadFileCommand(BaseCommand):
    name = "read-file"
    help = "Read bounded content from a local file within the workspace"

    def register_args(self, parser):
        parser.add_argument("path", help="Path to file to read")
        parser.add_argument("--start-line", type=int, default=None, help="1-indexed starting line number")
        parser.add_argument("--end-line", type=int, default=None, help="1-indexed ending line number")
        parser.add_argument("--max-bytes", type=int, default=65536, help="Maximum bytes to read (default: 65536)")

    def run(self, args):
        out = transport.call_mcp("read_file", {
            "path": args.path,
            "start_line": args.start_line,
            "end_line": args.end_line,
            "max_bytes": args.max_bytes,
        })
        print(out)
