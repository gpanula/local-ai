#!/usr/bin/env python3
"""
Lightweight CLI Client for Local Ollama MCP Server
Enables running clean, readable MCP requests from the terminal.
"""

import argparse
import json
import logging
import os
import stat
import subprocess
import sys

SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_ollama", "server.py")
WORKSPACE_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))


def _validate_workspace_path(path: str, purpose: str = "file") -> str:
    """Resolve and assert path lies within the workspace root. Returns realpath."""
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if not (resolved == WORKSPACE_ROOT or resolved.startswith(WORKSPACE_ROOT + os.sep)):
        raise ValueError(f"Rejected {purpose} path outside workspace: {path!r}")
    return resolved


def _is_valid_mcp_socket(path: str) -> bool:
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


def call_mcp(tool_name: str, arguments: dict) -> str:
    """Sends a JSON-RPC tools/call request to server.py and returns the output text."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    proc = subprocess.run(
        [sys.executable, SERVER_PATH],
        input=json.dumps(req) + "\n",
        capture_output=True,
        text=True
    )
    
    if proc.returncode != 0:
        raise RuntimeError(f"Server error (exit {proc.returncode}): {proc.stderr}")
    
    try:
        res = json.loads(proc.stdout.strip())
        if "error" in res:
            raise RuntimeError(f"JSON-RPC Error: {res['error']}\nServer stderr:\n{proc.stderr}")
        result = res.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"Tool Error: {result.get('content', [{}])[0].get('text')}\nServer stderr:\n{proc.stderr}")
        return result.get("content", [{}])[0].get("text", "")
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON received from MCP server: {proc.stdout}\nServer stderr:\n{proc.stderr}")


def send_terminal_mcp(text: str):
    """Prints to local stdout and streams clean formatted comment banners directly into the active terminal-mcp PTY."""
    print(text)
    terminal_sock = os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")
    if not _is_valid_mcp_socket(terminal_sock):
        return
    try:
        p = subprocess.Popen(
            ["npx", "-y", "github:gpanula/terminal-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "client", "version": "1.0"}}}) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        
        clean_text = text.replace("\r", "")
        formatted_lines = []
        for line in clean_text.splitlines():
            if not line.strip():
                formatted_lines.append("#")
            elif line.strip().startswith("#"):
                formatted_lines.append(line.strip())
            else:
                formatted_lines.append(f"# {line}")
        cmd = "\n".join(formatted_lines) + "\n"
        
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "type", "arguments": {"text": cmd}}}) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        p.terminate()
    except Exception as e:
        logging.debug("send_terminal_mcp: stream error (non-fatal): %s", e)


def _sanitize_script_code(code: str) -> str:
    """Sanitizes extracted code block: unindents common leading indentation and enforces column-0 heredoc delimiters."""
    import re
    import textwrap
    dedented = textwrap.dedent(code).strip()
    # Normalize indented closing delimiters for heredocs (e.g. '   EOF' -> 'EOF')
    sanitized = re.sub(r"^[ \t]+(EOF|EOT|ENDOFFILE)\b", r"\1", dedented, flags=re.MULTILINE)
    return sanitized


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ollama MCP Client CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list-models
    subparsers.add_parser("list-models", help="List installed models")

    # pull
    pull_p = subparsers.add_parser("pull", help="Pull a model into Ollama")
    pull_p.add_argument("model", help="Model name/tag (e.g. qwen2.5-coder:7b)")

    # chat
    chat_p = subparsers.add_parser("chat", help="Send chat prompt")
    chat_p.add_argument("prompt", help="Prompt text")
    chat_p.add_argument("--model", default="qwen3:8b", help="Model to use")
    chat_p.add_argument("--system", default=None, help="System prompt")

    # task
    task_p = subparsers.add_parser("task", help="Execute task agent prompt")
    task_p.add_argument("task", help="Task description")
    task_p.add_argument("--model", default="qwen3:8b", help="Model to use")
    task_p.add_argument("--context", default=None, help="Context string")
    task_p.add_argument("--type", default="sysadmin", help="Task category")

    # task-file
    task_file_p = subparsers.add_parser("task-file", help="Execute task from a prompt file")
    task_file_p.add_argument("file", help="Path to prompt markdown/text file")
    task_file_p.add_argument("--model", default="qwen3:8b", help="Model to use")
    task_file_p.add_argument("--type", default="sysadmin", help="Task category")

    # exec
    exec_p = subparsers.add_parser("exec", help="Direct Ollama agent to execute a command/script and report verification")
    exec_p.add_argument("cmd", help="Command or script to execute")
    exec_p.add_argument("--desc", default=None, help="Task description")
    exec_p.add_argument("--cwd", default=None, help="Working directory")
    exec_p.add_argument("--model", default="qwen3:8b", help="Model to use for verification")

    # build-and-run
    bar_p = subparsers.add_parser("build-and-run", help="Have Ollama generate code from a prompt file and execute it live in terminal-mcp")
    bar_p.add_argument("file", help="Path to prompt markdown/text file")
    bar_p.add_argument("--model", default="qwen3:8b", help="Model to use")
    bar_p.add_argument("--type", default="sysadmin", help="Task category")
    bar_p.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")

    # pipeline-run (Author -> Lint -> Review -> Execute)
    pip_p = subparsers.add_parser("pipeline-run", help="Multi-agent pipeline: Author (qwen2.5-coder) -> Lint (Shellcheck) -> Review (qwen3) -> Live Execution")
    pip_p.add_argument("file", help="Path to prompt markdown/text file")
    pip_p.add_argument("--author", default="qwen2.5-coder:7b", help="Model to synthesize code (default: qwen2.5-coder:7b)")
    pip_p.add_argument("--reviewer", default="qwen3:8b", help="Model to review & verify code (default: qwen3:8b)")
    pip_p.add_argument("--no-lint", action="store_true", help="Skip pre-flight linting step")
    pip_p.add_argument("--max-retries", type=int, default=2, help="Max revision cycles if reviewer rejects (default: 2)")
    pip_p.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")
    pip_p.add_argument("--dry-run", action="store_true", help="Stop after review without executing")

    # type (send command into active terminal-mcp session)
    type_p = subparsers.add_parser("type", help="Type a command into the active terminal-mcp interactive window")
    type_p.add_argument("text", help="Text/command to send to the terminal")

    # view (inspect current terminal-mcp viewport)
    view_p = subparsers.add_parser("view", help="View current terminal-mcp screen buffer")
    view_p.add_argument("--visible-only", action="store_true", help="Only show visible viewport")

    # ansible-check
    ac_p = subparsers.add_parser("ansible-check", help="Validate Ansible playbook/task YAML syntax")
    ac_p.add_argument("input", help="Path to YAML file or raw YAML string")
    ac_p.add_argument("--venv", default=None, help="Path to virtual environment (e.g. sysadmin/venv)")
    ac_p.add_argument("--bin-dir", default=None, help="Path to bin directory containing ansible-playbook")
    ac_p.add_argument("--task", action="store_true", help="Validate as task list instead of full playbook")

    # shellcheck
    sc_p = subparsers.add_parser("shellcheck", help="Run ShellCheck static analysis on bash script/file")
    sc_p.add_argument("input", help="Path to shell script or raw bash snippet")
    sc_p.add_argument("--venv", default=None, help="Path to virtual environment (e.g. sysadmin/venv)")
    sc_p.add_argument("--bin-dir", default=None, help="Path to bin directory containing shellcheck")

    # service-status
    ss_p = subparsers.add_parser("service-status", help="Inspect systemd service status")
    ss_p.add_argument("unit", nargs="?", default=None, help="Specific service unit to inspect")
    ss_p.add_argument("--failed", action="store_true", help="Only list failed units")

    # journal-logs
    jl_p = subparsers.add_parser("journal-logs", help="Query bounded journalctl log entries")
    jl_p.add_argument("unit", nargs="?", default=None, help="Service unit to filter logs for")
    jl_p.add_argument("--lines", type=int, default=50, help="Number of recent log lines (default: 50)")
    jl_p.add_argument("--priority", default=None, help="Log priority filter (emerg, err, warning, info, etc.)")
    jl_p.add_argument("--since", default=None, help="Time window filter (e.g., '1 hour ago', 'today')")

    # write-file
    wf_p = subparsers.add_parser("write-file", help="Write or append content to a local file within the workspace")
    wf_p.add_argument("path", help="Path to target file (relative to workspace root)")
    wf_p.add_argument("content", nargs="?", default=None, help="Text content to write (or pass via stdin / --file)")
    wf_p.add_argument("--file", "-f", default=None, help="Source file to read content from")
    wf_p.add_argument("--append", "-a", action="store_true", help="Append content instead of overwriting")
    wf_p.add_argument("--exec", "-x", action="store_true", help="Make file executable (chmod +x)")

    # read-file
    rf_p = subparsers.add_parser("read-file", help="Read bounded content from a local file within the workspace")
    rf_p.add_argument("path", help="Path to file to read")
    rf_p.add_argument("--start-line", type=int, default=None, help="1-indexed starting line number")
    rf_p.add_argument("--end-line", type=int, default=None, help="1-indexed ending line number")
    rf_p.add_argument("--max-bytes", type=int, default=65536, help="Maximum bytes to read (default: 65536)")

    args = parser.parse_args()

    if args.command == "list-models":
        out = call_mcp("ollama_list_models", {})
        print(out)
    elif args.command == "pull":
        print(f"📥 Requesting Ollama to retrieve model `{args.model}`...")
        out = call_mcp("ollama_pull_model", {"model": args.model})
        print(out)
    elif args.command == "chat":
        out = call_mcp("ollama_chat", {
            "prompt": args.prompt,
            "model": args.model,
            "system_prompt": args.system
        })
        print(out)
    elif args.command == "task":
        out = call_mcp("ollama_task_agent", {
            "task": args.task,
            "model": args.model,
            "context": args.context,
            "task_type": args.type
        })
        print(out)
    elif args.command == "task-file":
        valid_path = _validate_workspace_path(args.file, "task prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            task_content = f.read()
        out = call_mcp("ollama_task_agent", {
            "task": task_content,
            "model": args.model,
            "task_type": args.type
        })
        print(out)
    elif args.command == "build-and-run":
        import re
        valid_path = _validate_workspace_path(args.file, "prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            task_content = f.read()
        print(f"🤖 [Ollama {args.model}] Processing prompt from {args.file}...")
        plan = call_mcp("ollama_task_agent", {
            "task": task_content,
            "model": args.model,
            "task_type": args.type
        })
        print(f"✅ [Ollama {args.model}] Strategy & Commands Generated. Extracting execution block...")
        code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", plan)
        if not code_blocks:
            print("❌ No executable code blocks found in Ollama output. Raw plan:\n", plan)
        else:
            exec_cmd = _sanitize_script_code(max(code_blocks, key=len))
            # Send status banner into terminal-mcp interactive window
            banner_cmd = f"echo '🤖 [Ollama {args.model}] Executing prompt: {args.file}'; {exec_cmd}"
            print(f"🚀 [Ollama {args.model}] Executing build & run commands live in terminal-mcp...")
            report = call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Build & Execute task from {args.file}",
                "model": args.model,
                "timeout": args.timeout
            })
            print(report)
    elif args.command == "pipeline-run":
        import re
        valid_path = _validate_workspace_path(args.file, "prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()

        current_prompt = prompt_content
        approved = False
        iteration = 0
        final_code_block = ""

        while iteration <= args.max_retries and not approved:
            iteration += 1
            send_terminal_mcp(f"🤖 [Pipeline Iteration {iteration}] Authoring with `{args.author}`...")
            
            author_response = call_mcp("ollama_task_agent", {
                "task": current_prompt,
                "model": args.author,
                "task_type": "coding"
            })
            
            # Extract and format Author Analysis & Strategy
            strategy_text = ""
            if "### 1. Analysis & Strategy" in author_response or "### Analysis & Strategy" in author_response:
                parts = re.split(r"###\s*(?:2\.\s*)?Implementation", author_response, flags=re.IGNORECASE)
                strategy_text = parts[0].strip()
            elif "```" in author_response:
                strategy_text = author_response.split("```")[0].strip()
            else:
                strategy_text = author_response.strip()

            author_stats_match = re.search(r"(\*Generated by `[^`]+`: \d+ tokens in [\d\.]+s \([\d\.]+ t/s\)\*)", author_response)
            author_stats = author_stats_match.group(1) if author_stats_match else ""

            if strategy_text:
                send_terminal_mcp("─── [AUTHOR ANALYSIS & STRATEGY] ──────────────────────────")
                send_terminal_mcp(strategy_text)
                if author_stats:
                    send_terminal_mcp(f"📊 {author_stats}")
                send_terminal_mcp("──────────────────────────────────────────────────────────")
            
            # Check for structured tool calls first (tool_call or json code blocks)
            tool_calls = []
            tool_call_blocks = re.findall(r"```(?:tool_call|json)?\s*\n([\s\S]*?)```", author_response)
            for tc_str in tool_call_blocks:
                try:
                    tc_obj = json.loads(tc_str.strip())
                    if isinstance(tc_obj, dict):
                        if "name" in tc_obj and "arguments" in tc_obj:
                            tool_calls.append(tc_obj)
                        elif "name" in tc_obj and tc_obj.get("name") in ("write_file", "read_file"):
                            tool_calls.append({"name": tc_obj["name"], "arguments": tc_obj})
                        elif "tool" in tc_obj:
                            tool_calls.append({"name": tc_obj["tool"], "arguments": tc_obj.get("arguments", tc_obj)})
                except json.JSONDecodeError:
                    pass


            write_file_call = next((tc for tc in tool_calls if tc.get("name") == "write_file"), None)
            
            final_code_block = ""
            if write_file_call:
                wf_args = write_file_call.get("arguments", {})
                target_path = wf_args.get("path", "")
                target_content = wf_args.get("content", "")
                is_exec = wf_args.get("make_executable", False)
                send_terminal_mcp(f"🛠️ [Native Tool Call] write_file -> `{target_path}` ({len(target_content)} bytes, exec: {is_exec})")
                final_code_block = target_content
            else:
                code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", author_response)
                if not code_blocks:
                    send_terminal_mcp("❌ No executable code block or tool call extracted from author response.")
                    break
                final_code_block = _sanitize_script_code(max(code_blocks, key=len))
                preview_first_line = final_code_block.splitlines()[0] if final_code_block.splitlines() else ""
                send_terminal_mcp(f"📝 Synthesized Script ({len(final_code_block)} bytes) - {preview_first_line}")

            # Step 2: Pre-Flight Linting
            linter_output = "No linter run."
            if not args.no_lint:
                raw_linter = call_mcp("shellcheck_inspect", {"script": final_code_block})
                if "binary not found" in raw_linter:
                    linter_output = "ℹ️ Pre-flight shellcheck skipped (bootstrap in progress: shellcheck is not yet installed on host and will be installed by this script)."
                    send_terminal_mcp("ℹ️ [Pre-Flight Linter] Shellcheck skipped (bootstrap task in progress)")
                else:
                    linter_output = raw_linter
                    send_terminal_mcp(f"🔍 [Pre-Flight Linter] Output: {linter_output.splitlines()[0] if linter_output.splitlines() else ''}")

            # Step 3: Reviewer Evaluation (qwen3:8b)
            send_terminal_mcp(f"🧐 [Verifier `{args.reviewer}`] Evaluating script against prompt specifications...")
            review_prompt = (
                f"You are the Lead Verification Engineer reviewing a script authored by `{args.author}`.\n\n"
                f"### Original Prompt Specification:\n{prompt_content}\n\n"
                f"### Synthesized Script Code:\n```bash\n{final_code_block}\n```\n\n"
                f"### Pre-Flight Linter Output:\n{linter_output}\n\n"
                f"### System & Environment Facts:\n"
                f"- Bootstrap Task Context: This is the initial bootstrapping task. The virtual environment and binaries (including shellcheck) do NOT exist yet on the host; this script installs them. Do NOT fail the script because shellcheck is not yet present.\n"
                f"- Package Mapping: `shellcheck-py` installs the native CLI binary at `${{VENV_DIR}}/bin/shellcheck`. Testing `[ -x ${{VENV_DIR}}/bin/shellcheck ]` and `shellcheck --version` is the correct and expected verification.\n"
                f"- Library Mapping: `pyyaml` provides the `yaml` Python module tested via `python -c 'import yaml'`.\n\n"
                f"### Verification Checklist:\n"
                f"1. Requirements: Are all technical specifications and packages met?\n"
                f"2. Defensive Standards: Are strict flags (`set -euo pipefail`), diagnostic `ERR` trap with line number, `EXIT` cleanup trap, binary existence assertions (`[ -x ...]`), and functional smoke tests implemented?\n"
                f"3. Temporary Directory Resilience: Does the script safely handle temporary directories without assuming $TMPDIR exists (e.g. ensuring `mkdir -p \"${{TMPDIR:-/tmp}}\"` or using `mktemp -d -p /tmp`)?\n"
                f"4. Sandbox & Safety: Does Ansible use a temporary directory in `/tmp` to avoid read-only permissions errors?\n"
                f"5. Success Gate: Is the final success message (`🎉 ...`) guarded so it cannot run if an earlier step fails?\n"
                f"6. Heredoc Delimiters: If shell heredocs are used, verify that delimiters are unindented on column 0.\n\n"
                f"### Decision Rule:\n"
                f"Conclude your response with exactly `DECISION: APPROVED` if all criteria are satisfied, or `DECISION: REVISION_REQUESTED` followed by bullet points detailing the required fixes."
            )
            
            review_verdict = call_mcp("ollama_chat", {
                "prompt": review_prompt,
                "model": args.reviewer,
                "system_prompt": "You are a strict, uncompromising code verifier and systems engineer.",
                "temperature": 0.1,
                "num_ctx": 4096
            })
            
            review_stats_match = re.search(r"(\*Generated by `[^`]+`: \d+ tokens in [\d\.]+s \([\d\.]+ t/s\)\*)", review_verdict)
            review_stats = review_stats_match.group(1) if review_stats_match else ""
            
            verdict_decision = "DECISION: APPROVED" if "DECISION: APPROVED" in review_verdict else "DECISION: REVISION_REQUESTED"
            send_terminal_mcp(f"📋 [Reviewer Verdict ({args.reviewer})]: {verdict_decision}")
            if review_stats:
                send_terminal_mcp(f"📊 {review_stats}")
            
            if "DECISION: REVISION_REQUESTED" in review_verdict:
                critique_points = []
                for line in review_verdict.splitlines():
                    if line.strip().startswith("- ") or line.strip().startswith("* ") or line.strip().startswith("DECISION:"):
                        critique_points.append(line.strip())
                critique_summary = "\n".join(critique_points) if critique_points else review_verdict.strip()
                send_terminal_mcp("─── [REVIEWER REQUIRED FIXES] ─────────────────────────────")
                send_terminal_mcp(critique_summary)
                send_terminal_mcp("──────────────────────────────────────────────────────────")
            print(f"\n{review_verdict}\n")

            if "DECISION: APPROVED" in review_verdict:
                approved = True
                send_terminal_mcp(f"✅ [Pipeline Approved] Script passed all verification gates!")
            else:
                send_terminal_mcp(f"⚠️ [Revision Requested] Feedback loop initiated for `{args.author}`...")
                current_prompt = (
                    f"{prompt_content}\n\n"
                    f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
                    f"### Reviewer Feedback & Required Fixes:\n{review_verdict}\n\n"
                    f"Please rewrite and fix the script addressing all reviewer critique points."
                )

        if not approved:
            send_terminal_mcp(f"❌ [Pipeline Failed] Maximum review retries ({args.max_retries}) reached without approval.")
            return

        if args.dry_run:
            send_terminal_mcp("🏁 [Dry-Run] Pipeline completed verification. Skipping execution.")
            return

        # Step 4: Execution
        if write_file_call:
            wf_args = write_file_call.get("arguments", {})
            target_path = wf_args.get("path", "")
            is_exec = wf_args.get("make_executable", False)
            
            # 1. Execute write_file natively via MCP
            send_terminal_mcp(f"📝 [Native Tool Execution] Writing `{target_path}` via MCP...")
            wf_res = call_mcp("write_file", wf_args)
            send_terminal_mcp(f"✅ {wf_res}")
            
            # 2. Run execution command in terminal-mcp
            exec_bin = f"./{target_path}" if is_exec else f"python3 {target_path}"
            send_terminal_mcp(f"🚀 [Live Terminal Execution] Running `{exec_bin}` in terminal-mcp...")
            banner_cmd = f"echo '🤖 [Ollama Verified Pipeline] Executing: {exec_bin}'; {exec_bin}"
            report = call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Verified execution of {target_path}",
                "cwd": WORKSPACE_ROOT,
                "model": args.reviewer,
                "timeout": args.timeout
            })
            print(f"\n{report}")
        else:
            send_terminal_mcp(f"🚀 [Live Terminal Execution] Running verified script in terminal-mcp...")
            banner_cmd = f"echo '🤖 [Ollama Verified Pipeline] Executing: {args.file}'; (\n{final_code_block}\n)"
            report = call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Verified pipeline execution of {args.file}",
                "cwd": WORKSPACE_ROOT,
                "model": args.reviewer,
                "timeout": args.timeout
            })
            print(f"\n{report}")
    elif args.command == "exec":
        out = call_mcp("ollama_execute_task", {
            "command": args.cmd,
            "task_description": args.desc,
            "cwd": args.cwd,
            "model": args.model
        })
        print(out)
    elif args.command == "type":
        import time
        p = subprocess.Popen(["npx", "-y", "github:gpanula/terminal-mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "client", "version": "1.0"}}}) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "type", "arguments": {"text": args.text.rstrip("\n") + "\n"}}}) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        p.terminate()
        print(f"Typed into terminal-mcp: {args.text}")
    elif args.command == "view":
        p = subprocess.Popen(["npx", "-y", "github:gpanula/terminal-mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "client", "version": "1.0"}}}) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "getContent", "arguments": {"visibleOnly": args.visible_only}}}) + "\n")
        p.stdin.flush()
        res = json.loads(p.stdout.readline())
        p.terminate()
        print(res.get("result", {}).get("content", [{}])[0].get("text", ""))
    elif args.command == "ansible-check":
        content = args.input
        if os.path.isfile(args.input):
            valid_path = _validate_workspace_path(args.input, "ansible input file")
            with open(valid_path, "r", encoding="utf-8") as f:
                content = f.read()
        out = call_mcp("ansible_syntax_check", {
            "content": content,
            "is_playbook": not args.task,
            "venv_path": args.venv,
            "bin_dir": args.bin_dir
        })
        print(out)
    elif args.command == "shellcheck":
        script = args.input
        if os.path.isfile(args.input):
            valid_path = _validate_workspace_path(args.input, "shell script file")
            with open(valid_path, "r", encoding="utf-8") as f:
                script = f.read()
        out = call_mcp("shellcheck_inspect", {
            "script": script,
            "venv_path": args.venv,
            "bin_dir": args.bin_dir
        })
        print(out)
    elif args.command == "service-status":
        out = call_mcp("service_status", {
            "unit": args.unit,
            "failed_only": args.failed
        })
        print(out)
    elif args.command == "journal-logs":
        out = call_mcp("journal_logs", {
            "unit": args.unit,
            "lines": args.lines,
            "priority": args.priority,
            "since": args.since
        })
        print(out)
    elif args.command == "write-file":
        content = args.content
        if args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        elif content is None:
            if not sys.stdin.isatty():
                content = sys.stdin.read()
            else:
                raise ValueError("No content provided. Specify content argument, --file, or pipe via stdin.")
        out = call_mcp("write_file", {
            "path": args.path,
            "content": content,
            "mode": "append" if args.append else "overwrite",
            "make_executable": args.exec
        })
        print(out)
    elif args.command == "read-file":
        out = call_mcp("read_file", {
            "path": args.path,
            "start_line": args.start_line,
            "end_line": args.end_line,
            "max_bytes": args.max_bytes
        })
        print(out)



if __name__ == "__main__":
    main()
