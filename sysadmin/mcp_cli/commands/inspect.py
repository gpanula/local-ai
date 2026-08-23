"""Static-analysis / lint inspection commands: shellcheck, ansible-check."""

import os

from mcp_core import transport
from mcp_core.workspace import validate_workspace_path
from mcp_cli.base import BaseCommand, command


@command
class AnsibleCheckCommand(BaseCommand):
    name = "ansible-check"
    help = "Validate Ansible playbook/task YAML syntax"

    def register_args(self, parser):
        parser.add_argument("input", help="Path to YAML file or raw YAML string")
        parser.add_argument("--venv", default=None, help="Path to virtual environment (e.g. sysadmin/venv)")
        parser.add_argument("--bin-dir", default=None, help="Path to bin directory containing ansible-playbook")
        parser.add_argument("--task", action="store_true", help="Validate as task list instead of full playbook")

    def run(self, args):
        content = args.input
        if os.path.isfile(args.input):
            valid_path = validate_workspace_path(args.input, "ansible input file")
            with open(valid_path, "r", encoding="utf-8") as f:
                content = f.read()
        out = transport.call_mcp("ansible_syntax_check", {
            "content": content,
            "is_playbook": not args.task,
            "venv_path": args.venv,
            "bin_dir": args.bin_dir,
        })
        print(out)


@command
class ShellcheckCommand(BaseCommand):
    name = "shellcheck"
    help = "Run ShellCheck static analysis on bash script/file"

    def register_args(self, parser):
        parser.add_argument("input", help="Path to shell script or raw bash snippet")
        parser.add_argument("--venv", default=None, help="Path to virtual environment (e.g. sysadmin/venv)")
        parser.add_argument("--bin-dir", default=None, help="Path to bin directory containing shellcheck")

    def run(self, args):
        script = args.input
        if os.path.isfile(args.input):
            valid_path = validate_workspace_path(args.input, "shell script file")
            with open(valid_path, "r", encoding="utf-8") as f:
                script = f.read()
        out = transport.call_mcp("shellcheck_inspect", {
            "script": script,
            "venv_path": args.venv,
            "bin_dir": args.bin_dir,
        })
        print(out)
