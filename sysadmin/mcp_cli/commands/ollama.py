"""Ollama model commands: list-models, pull, chat, task, task-file, exec."""

from mcp_core import transport
from mcp_core.workspace import validate_workspace_path
from mcp_cli.base import BaseCommand, command


@command
class ListModelsCommand(BaseCommand):
    name = "list-models"
    help = "List installed models"

    def register_args(self, parser):
        pass

    def run(self, args):
        out = transport.call_mcp("ollama_list_models", {})
        print(out)


@command
class PullCommand(BaseCommand):
    name = "pull"
    help = "Pull a model into Ollama"

    def register_args(self, parser):
        parser.add_argument("model", help="Model name/tag (e.g. qwen2.5-coder:7b)")

    def run(self, args):
        print(f"📥 Requesting Ollama to retrieve model `{args.model}`...")
        out = transport.call_mcp("ollama_pull_model", {"model": args.model})
        print(out)


@command
class ChatCommand(BaseCommand):
    name = "chat"
    help = "Send chat prompt"

    def register_args(self, parser):
        parser.add_argument("prompt", help="Prompt text")
        parser.add_argument("--model", default="qwen3:8b", help="Model to use")
        parser.add_argument("--system", default=None, help="System prompt")

    def run(self, args):
        out = transport.call_mcp("ollama_chat", {
            "prompt": args.prompt,
            "model": args.model,
            "system_prompt": args.system,
        })
        print(out)


@command
class TaskCommand(BaseCommand):
    name = "task"
    help = "Execute task agent prompt"

    def register_args(self, parser):
        parser.add_argument("task", help="Task description")
        parser.add_argument("--model", default="qwen3:8b", help="Model to use")
        parser.add_argument("--context", default=None, help="Context string")
        parser.add_argument("--type", default="sysadmin", help="Task category")

    def run(self, args):
        out = transport.call_mcp("ollama_task_agent", {
            "task": args.task,
            "model": args.model,
            "context": args.context,
            "task_type": args.type,
        })
        print(out)


@command
class TaskFileCommand(BaseCommand):
    name = "task-file"
    help = "Execute task from a prompt file"

    def register_args(self, parser):
        parser.add_argument("file", help="Path to prompt markdown/text file")
        parser.add_argument("--model", default="qwen3:8b", help="Model to use")
        parser.add_argument("--type", default="sysadmin", help="Task category")

    def run(self, args):
        valid_path = validate_workspace_path(args.file, "task prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            task_content = f.read()
        out = transport.call_mcp("ollama_task_agent", {
            "task": task_content,
            "model": args.model,
            "task_type": args.type,
        })
        print(out)


@command
class ExecCommand(BaseCommand):
    name = "exec"
    help = "Direct Ollama agent to execute a command/script and report verification"

    def register_args(self, parser):
        parser.add_argument("cmd", help="Command or script to execute")
        parser.add_argument("--desc", default=None, help="Task description")
        parser.add_argument("--cwd", default=None, help="Working directory")
        parser.add_argument("--model", default="qwen3:8b", help="Model to use for verification")

    def run(self, args):
        out = transport.call_mcp("ollama_execute_task", {
            "command": args.cmd,
            "task_description": args.desc,
            "cwd": args.cwd,
            "model": args.model,
        })
        print(out)
