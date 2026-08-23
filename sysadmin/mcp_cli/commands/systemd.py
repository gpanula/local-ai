"""systemd service inspection commands: service-status, journal-logs."""

from mcp_core import transport
from mcp_cli.base import BaseCommand, command


@command
class ServiceStatusCommand(BaseCommand):
    name = "service-status"
    help = "Inspect systemd service status"

    def register_args(self, parser):
        parser.add_argument("unit", nargs="?", default=None, help="Specific service unit to inspect")
        parser.add_argument("--failed", action="store_true", help="Only list failed units")

    def run(self, args):
        out = transport.call_mcp("service_status", {
            "unit": args.unit,
            "failed_only": args.failed,
        })
        print(out)


@command
class JournalLogsCommand(BaseCommand):
    name = "journal-logs"
    help = "Query bounded journalctl log entries"

    def register_args(self, parser):
        parser.add_argument("unit", nargs="?", default=None, help="Service unit to filter logs for")
        parser.add_argument("--lines", type=int, default=50, help="Number of recent log lines (default: 50)")
        parser.add_argument("--priority", default=None, help="Log priority filter (emerg, err, warning, info, etc.)")
        parser.add_argument("--since", default=None, help="Time window filter (e.g., '1 hour ago', 'today')")

    def run(self, args):
        out = transport.call_mcp("journal_logs", {
            "unit": args.unit,
            "lines": args.lines,
            "priority": args.priority,
            "since": args.since,
        })
        print(out)
