"""terminal-mcp interactive commands: type, view."""

from mcp_core import transport
from mcp_cli.base import BaseCommand, command


@command
class TypeCommand(BaseCommand):
    name = "type"
    help = "Type a command into the active terminal-mcp interactive window"

    def register_args(self, parser):
        parser.add_argument("text", help="Text/command to send to the terminal")

    def run(self, args):
        with transport.TerminalMCPSession() as session:
            if session.is_available:
                session.type(args.text)
        print(f"Typed into terminal-mcp: {args.text}")


@command
class ViewCommand(BaseCommand):
    name = "view"
    help = "View current terminal-mcp screen buffer"

    def register_args(self, parser):
        parser.add_argument("--visible-only", action="store_true", help="Only show visible viewport")

    def run(self, args):
        with transport.TerminalMCPSession() as session:
            if session.is_available:
                print(session.get_content(visible_only=args.visible_only))
