#!/usr/bin/env python3
"""
Local Ollama MCP Server
Provides a Model Context Protocol (MCP) interface over stdio to delegate tasks,
chat, code generation, and model management to a local Ollama instance.
"""

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _validate_ollama_host(raw: str) -> str:
    """Validates that OLLAMA_HOST has an http/https scheme and is a loopback or private address."""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"OLLAMA_HOST must use http or https scheme, got: {raw!r}")
    hostname = parsed.hostname or ""
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        import ipaddress
        try:
            addr = ipaddress.ip_address(hostname)
            if not (addr.is_loopback or addr.is_private):
                raise ValueError(f"OLLAMA_HOST resolves to a non-private address: {hostname}")
        except ValueError:
            raise ValueError(f"OLLAMA_HOST hostname must be localhost/loopback or a private IP: {hostname}")
    return raw.rstrip("/")


OLLAMA_HOST = _validate_ollama_host(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
PROTOCOL_VERSION = "2024-11-05"
WORKSPACE_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _validate_workspace_path(path: str, purpose: str = "file") -> str:
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


def _http_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None, timeout: int = 300) -> Dict[str, Any]:
    url = f"{OLLAMA_HOST}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    
    body = json.dumps(data).encode("utf-8") if data is not None else None
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as response:
            res_body = response.read().decode("utf-8")
            if not res_body.strip():
                return {}
            try:
                return json.loads(res_body)
            except json.JSONDecodeError:
                # Multi-line JSON lines (NDJSON)
                lines = [json.loads(line) for line in res_body.strip().splitlines() if line.strip()]
                return {"lines": lines}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama API HTTP {e.code} ({url}): {e.reason} - {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to connect to Ollama at {url}: {e}")
    except Exception as e:
        raise RuntimeError(f"Ollama API request error ({url}): {e}")



def handle_list_models() -> str:
    """Lists all models installed in the local Ollama instance."""
    data = _http_request("/api/tags", method="GET")
    models = data.get("models", [])
    if not models:
        return "No models installed in local Ollama."
    
    result = ["Installed Ollama Models:"]
    for m in models:
        name = m.get("name", "unknown")
        size_gb = m.get("size", 0) / (1024 ** 3)
        details = m.get("details", {})
        family = details.get("family", "")
        quant = details.get("quantization_level", "")
        param_size = details.get("parameter_size", "")
        result.append(f"- **{name}** ({size_gb:.2f} GB) | Params: {param_size} | Family: {family} | Quant: {quant}")
    
    return "\n".join(result)


AVAILABLE_OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Writes or appends text content to a local file within the workspace with optional executable permissions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative workspace path to target file (e.g. 'sysadmin/hello_world.sh')."
                    },
                    "content": {
                        "type": "string",
                        "description": "The exact text content to write to the file."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "description": "Write mode: 'overwrite' (default) or 'append'."
                    },
                    "make_executable": {
                        "type": "boolean",
                        "description": "If true, sets executable permissions (chmod +x)."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Reads text content from a local file within the workspace with optional line range slicing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative workspace path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed starting line number."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed ending line number."
                    }
                },
                "required": ["path"]
            }
        }
    }
]


def handle_chat(
    model: str,
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.7,
    num_ctx: int = 4096
) -> str:
    """Sends a chat request to local Ollama with optional native tool definitions."""
    chat_messages = []
    if system_prompt:
        chat_messages.append({"role": "system", "content": system_prompt})
    
    if messages:
        chat_messages.extend(messages)
    elif prompt:
        chat_messages.append({"role": "user", "content": prompt})
    else:
        raise ValueError("Either 'prompt' or 'messages' must be provided.")
    
    payload = {
        "model": model,
        "messages": chat_messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx
        }
    }
    if tools:
        payload["tools"] = tools
    
    try:
        response = _http_request("/api/chat", method="POST", data=payload, timeout=300)
    except RuntimeError as e:
        if "does not support tools" in str(e) and "tools" in payload:
            del payload["tools"]
            response = _http_request("/api/chat", method="POST", data=payload, timeout=300)
        else:
            raise

    message = response.get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls", [])

    
    # Extract performance metrics if available
    eval_count = response.get("eval_count", 0)
    eval_duration = response.get("eval_duration", 0)
    tps = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0
    
    stats = f"\n\n---\n*Generated by `{model}`: {eval_count} tokens in {eval_duration/1e9:.2f}s ({tps:.1f} t/s)*"

    if tool_calls:
        tool_call_repr = ["### 🛠️ Structured Tool Calls:"]
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "unknown")
            args = func.get("arguments", {})
            tool_call_repr.append(f"```tool_call\n{json.dumps({'name': name, 'arguments': args}, indent=2)}\n```")
        formatted_calls = "\n\n".join(tool_call_repr)
        return (content + "\n\n" if content else "") + formatted_calls + stats

    return content + stats


def handle_task_agent(
    task: str,
    model: str = "qwen3:8b",
    context: Optional[str] = None,
    task_type: str = "general",
    enable_tools: bool = True,
    num_ctx: int = 4096
) -> str:
    """
    Executes a structured task delegation pass to a local Ollama model.
    Encourages structured step-by-step reasoning, tool execution, and self-verification.
    """
    system_prompt = (
        "You are an expert local AI agent and systems engineer. "
        "When given a task, follow this structured format:\n"
        "1. **Analysis & Strategy**: Deconstruct the problem and requirements.\n"
        "2. **Implementation / Solution**: Provide clean, idiomatic code or invoke available tools (like write_file) to write files safely.\n"
        "3. **Verification & Testing**: Explain how to test and verify the solution (idempotency, dry-run, syntax checks).\n"
        "4. **Risks & Edge Cases**: Detail any caveats or failure modes."
    )
    
    user_prompt = f"### Task Request ({task_type}):\n{task}"
    if context:
        user_prompt += f"\n\n### Workspace Context:\n{context}"
        
    tools_to_pass = AVAILABLE_OLLAMA_TOOLS if enable_tools else None
    return handle_chat(
        model=model,
        prompt=user_prompt,
        system_prompt=system_prompt,
        tools=tools_to_pass,
        temperature=0.2,
        num_ctx=num_ctx
    )



def handle_pull_model(model: str) -> str:
    """Triggers pulling a model into Ollama."""
    payload = {"name": model, "stream": False}
    _http_request("/api/pull", method="POST", data=payload, timeout=600)
    return f"Successfully pulled model `{model}` into local Ollama."


def _execute_in_terminal_mcp(command: str, cwd: Optional[str] = None, timeout: int = 180) -> Tuple[str, int, str]:
    """Executes a command inside the active terminal-mcp session and captures the terminal buffer."""
    import subprocess
    import time
    
    exec_command = f"cd {shlex.quote(cwd)} && (\n{command}\n)" if cwd else command

    try:
        p = subprocess.Popen(
            ["npx", "-y", "github:gpanula/terminal-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        init_req = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "ollama-mcp", "version": "1.0"}}
        }
        p.stdin.write(json.dumps(init_req) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        
        type_req = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "type", "arguments": {"text": exec_command.rstrip("\n") + "\n"}}
        }
        p.stdin.write(json.dumps(type_req) + "\n")
        p.stdin.flush()
        p.stdout.readline()
        
        start_time = time.time()
        last_text = ""
        req_id = 3
        
        time.sleep(1.5)
        while time.time() - start_time < timeout:
            get_req = {
                "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                "params": {"name": "getContent", "arguments": {"visibleOnly": False}}
            }
            req_id += 1
            try:
                p.stdin.write(json.dumps(get_req) + "\n")
                p.stdin.flush()
                res_line = p.stdout.readline()
                if not res_line:
                    break
                res = json.loads(res_line)
                last_text = res.get("result", {}).get("content", [{}])[0].get("text", "")
                lines = [l.strip() for l in last_text.strip().splitlines() if l.strip()]
                if lines and (lines[-1].endswith("$") or lines[-1].endswith("#") or "⚡ mcp" in lines[-1]):
                    if len(lines) > 1 and command.strip() not in lines[-1]:
                        break
            except (BrokenPipeError, OSError):
                break
            time.sleep(1.5)
            
        p.terminate()
        lines = last_text.strip().splitlines()
        tail = "\n".join(lines[-40:]) if len(lines) > 40 else last_text
        return tail, 0, "terminal-mcp PTY"
    except Exception as e:
        raise RuntimeError(f"terminal-mcp PTY execution failed: {e}") from e


def handle_execute_task(
    command: str,
    task_description: Optional[str] = None,
    cwd: Optional[str] = None,
    model: str = "qwen3:8b",
    timeout: int = 180
) -> str:
    """
    Executes a shell command on the host/sandbox (via active terminal-mcp or subprocess),
    captures output, and asks Ollama to verify and analyze the execution outcome.
    """
    import subprocess
    work_dir = os.path.expanduser(cwd) if cwd else os.getcwd()
    execution_target = "host subprocess"

    terminal_sock = os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")
    if _is_valid_mcp_socket(terminal_sock):
        stdout, exit_code, execution_target = _execute_in_terminal_mcp(command, cwd=work_dir, timeout=timeout)
        stderr = ""
    else:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            return f"❌ Command timed out after {timeout} seconds: `{command}`"
        except Exception as e:
            return f"❌ Execution error: {e}"

    # Prompt Ollama to analyze and verify the command run
    prompt = (
        f"A shell command was executed as part of the following task:\n"
        f"Task: {task_description or 'Shell Command Execution'}\n"
        f"Target: {execution_target}\n"
        f"Command: `{command}`\n"
        f"Exit Code: {exit_code}\n"
        f"Output:\n```\n{stdout}\n```\n"
        f"Stderr:\n```\n{stderr}\n```\n\n"
        f"Please verify if the command succeeded and provide a concise status summary."
    )

    ollama_analysis = handle_chat(
        model=model,
        prompt=prompt,
        system_prompt="You are a verification assistant. Analyze command outputs concisely.",
        temperature=0.1
    )

    report = [
        f"### 🖥️ Shell Command Execution ({execution_target})",
        f"- **Command**: `{command}`",
        f"- **Working Directory**: `{work_dir}`",
        f"- **Exit Code**: `{exit_code}`",
        f"\n**Output / Terminal Buffer:**",
        f"```",
        stdout.strip() if stdout.strip() else "(no stdout)",
        f"```"
    ]
    if stderr.strip():
        report.extend([
            f"\n**Stderr:**",
            f"```",
            stderr.strip(),
            f"```"
        ])
    report.extend([
        f"\n### 🤖 Ollama Verification ({model}):",
        ollama_analysis
    ])
    return "\n".join(report)


def _find_executable(name: str, venv_path: Optional[str] = None, bin_dir: Optional[str] = None) -> Optional[str]:
    """
    Tiered executable resolver with path containment verification:
    1. Explicit bin_dir or venv_path/bin argument
    2. Environment variable overrides ($TOOL_VENV, $ANSIBLE_VENV, $TOOL_BIN_DIR)
    3. Standard workspace search paths (sysadmin/venv/bin, test_venv/bin, .venv/bin, venv/bin)
    4. System $PATH
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    allowed_prefixes = [
        os.path.realpath(base_dir),
        "/usr/bin",
        "/bin",
        "/usr/local/bin"
    ]

    def _is_safe_candidate(cand_path: str) -> bool:
        real_cand = os.path.realpath(os.path.abspath(cand_path))
        return any(real_cand == p or real_cand.startswith(p + os.sep) for p in allowed_prefixes)

    # 1. Explicit arguments
    if bin_dir:
        candidate = os.path.join(os.path.expanduser(bin_dir), name)
        if _is_safe_candidate(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    if venv_path:
        candidate = os.path.join(os.path.expanduser(venv_path), "bin", name)
        if _is_safe_candidate(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # 2. Environment variables
    env_bin = os.environ.get("TOOL_BIN_DIR")
    if env_bin:
        candidate = os.path.join(os.path.expanduser(env_bin), name)
        if _is_safe_candidate(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    for env_var in ("TOOL_VENV", "ANSIBLE_VENV"):
        env_venv = os.environ.get(env_var)
        if env_venv:
            candidate = os.path.join(os.path.expanduser(env_venv), "bin", name)
            if _is_safe_candidate(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    # 3. Workspace standard search paths
    search_dirs = [
        os.path.join(base_dir, "sysadmin", "venv", "bin"),
        os.path.join(base_dir, "test_venv", "bin"),
        os.path.join(base_dir, ".venv", "bin"),
        os.path.join(base_dir, "venv", "bin"),
    ]
    for d in search_dirs:
        candidate = os.path.join(d, name)
        if _is_safe_candidate(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # 4. System PATH
    return shutil.which(name)


def handle_ansible_syntax_check(
    content: str,
    is_playbook: bool = True,
    venv_path: Optional[str] = None,
    bin_dir: Optional[str] = None
) -> str:
    """
    Validates Ansible playbook or task YAML syntax using ansible-playbook / pyyaml in an isolated temp environment.
    Guarantees 100% concurrency safety with ephemeral temporary directories.
    """
    import yaml
    
    # 1. First-pass YAML parsing validation
    try:
        parsed_yaml = list(yaml.safe_load_all(content))
        if not parsed_yaml or all(doc is None for doc in parsed_yaml):
            return "❌ Ansible Syntax Error: Content is empty or invalid YAML."
    except yaml.YAMLError as e:
        return f"❌ YAML Parsing Error:\n{str(e)}"

    ansible_bin = _find_executable("ansible-playbook", venv_path=venv_path, bin_dir=bin_dir)
    if not ansible_bin:
        return (
            f"⚠️ `ansible-playbook` binary not found. Fallback YAML validation passed (valid YAML structure).\n"
            f"To enable full Ansible syntax checking, install ansible into `sysadmin/venv` or specify `--venv`."
        )

    # 2. Ephemeral isolated execution
    with tempfile.TemporaryDirectory(prefix=f"ansible-syntax-{os.getpid()}-") as task_tmp:
        playbook_path = os.path.join(task_tmp, "playbook.yml")
        with open(playbook_path, "w", encoding="utf-8") as f:
            f.write(content)

        env = os.environ.copy()
        env["ANSIBLE_LOCAL_TEMP"] = task_tmp
        env["ANSIBLE_HOME"] = os.path.join(task_tmp, ".ansible")
        env["ANSIBLE_NOCOWS"] = "1"
        # Dummy inventory so syntax-check doesn't complain about hosts
        inventory_path = os.path.join(task_tmp, "hosts")
        with open(inventory_path, "w") as f:
            f.write("localhost ansible_connection=local\n")

        cmd = [ansible_bin, "--syntax-check", "-i", inventory_path, playbook_path]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                return f"✅ Ansible Playbook Syntax Check Passed:\n{proc.stdout.strip() or 'playbook: playbook.yml syntax OK'}"
            else:
                out = (proc.stdout + "\n" + proc.stderr).strip()
                clean_out = out.replace(task_tmp + "/", "")
                return f"❌ Ansible Syntax Verification Failed (exit {proc.returncode}):\n{clean_out}"
        except subprocess.TimeoutExpired:
            return "❌ Ansible syntax check timed out after 30 seconds."
        except Exception as e:
            return f"❌ Execution error during Ansible check: {str(e)}"


def handle_shellcheck_inspect(
    script: str,
    venv_path: Optional[str] = None,
    bin_dir: Optional[str] = None
) -> str:
    """
    Runs ShellCheck static analysis on a bash/sh script.
    """
    shellcheck_bin = _find_executable("shellcheck", venv_path=venv_path, bin_dir=bin_dir)
    if not shellcheck_bin:
        return (
            "❌ `shellcheck` binary not found.\n"
            "Please ensure `shellcheck-py` is installed in `sysadmin/venv` or specify `--venv`."
        )

    try:
        proc = subprocess.run(
            [shellcheck_bin, "-s", "bash", "-f", "tty", "-"],
            input=script,
            capture_output=True,
            text=True,
            timeout=30
        )
        if proc.returncode == 0:
            return "✅ ShellCheck: No syntax or style issues detected."
        else:
            output = proc.stdout.strip() or proc.stderr.strip()
            return f"⚠️ ShellCheck Analysis Findings (exit {proc.returncode}):\n\n{output}"
    except subprocess.TimeoutExpired:
        return "❌ ShellCheck timed out after 30 seconds."
    except Exception as e:
        return f"❌ ShellCheck execution error: {str(e)}"


def handle_service_status(
    unit: Optional[str] = None,
    failed_only: bool = False
) -> str:
    """
    Queries systemctl service status with bounded unpaged output.
    """
    systemctl_bin = _find_executable("systemctl") or "/usr/bin/systemctl"
    if not os.path.exists(systemctl_bin):
        return "❌ `systemctl` binary not found on this system."

    if failed_only:
        cmd = [systemctl_bin, "--failed", "--no-pager", "--no-legend"]
    elif unit:
        cmd = [systemctl_bin, "status", unit, "--no-pager", "-l"]
    else:
        cmd = [systemctl_bin, "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        raw_output = proc.stdout.strip() or proc.stderr.strip()
        if not raw_output and proc.returncode == 0:
            return "✅ No failed systemd units found." if failed_only else "✅ Service check completed (no output)."

        lines = raw_output.splitlines()
        bounded = "\n".join(lines[:60])
        if len(lines) > 60:
            bounded += f"\n... [truncated {len(lines) - 60} additional lines]"
        return bounded
    except subprocess.TimeoutExpired:
        return "❌ systemctl query timed out after 15 seconds."
    except Exception as e:
        return f"❌ systemctl execution error: {str(e)}"


def handle_journal_logs(
    unit: Optional[str] = None,
    lines: int = 50,
    priority: Optional[str] = None,
    since: Optional[str] = None
) -> str:
    """
    Queries bounded journalctl logs filtered by unit, priority, and lines.
    """
    journalctl_bin = _find_executable("journalctl") or "/usr/bin/journalctl"
    if not os.path.exists(journalctl_bin):
        return "❌ `journalctl` binary not found on this system."

    clamped_lines = max(1, min(int(lines), 200))
    cmd = [journalctl_bin, "-n", str(clamped_lines), "--no-pager"]
    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    if since:
        cmd.extend(["--since", since])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        output = proc.stdout.strip() or proc.stderr.strip()
        if not output and proc.returncode == 0:
            return f"ℹ️ No journal logs found for query ({' '.join(cmd[1:])})."
        return output
    except subprocess.TimeoutExpired:
        return "❌ journalctl query timed out after 20 seconds."
    except Exception as e:
        return f"❌ journalctl execution error: {str(e)}"


def handle_write_file(
    path: str,
    content: str,
    mode: str = "overwrite",
    make_executable: bool = False
) -> str:
    """
    Safely writes or appends text content to a file strictly confined within the workspace root.
    Optionally applies executable bit permissions.
    """
    if mode not in ("overwrite", "append"):
        raise ValueError(f"Invalid mode {mode!r}. Must be 'overwrite' or 'append'.")

    real_path = _validate_workspace_path(path, purpose="write_file")
    os.makedirs(os.path.dirname(real_path), exist_ok=True)

    file_mode = "a" if mode == "append" else "w"
    with open(real_path, file_mode, encoding="utf-8") as f:
        f.write(content)

    if make_executable:
        st = os.stat(real_path)
        os.chmod(real_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    rel_path = os.path.relpath(real_path, WORKSPACE_ROOT)
    byte_count = len(content.encode("utf-8"))
    exec_flag = ", executable (+x)" if make_executable else ""
    return f"✅ Successfully wrote {byte_count} bytes to `{rel_path}` (mode: {mode}{exec_flag})."


def handle_read_file(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_bytes: int = 65536
) -> str:
    """
    Reads bounded text content from a file strictly confined within the workspace root.
    Supports optional 1-indexed line number slicing.
    """
    real_path = _validate_workspace_path(path, purpose="read_file")
    if not os.path.exists(real_path):
        return f"❌ File not found: {path}"
    if not os.path.isfile(real_path):
        return f"❌ Path is not a regular file: {path}"

    clamped_max_bytes = max(1, min(int(max_bytes), 1024 * 1024))

    with open(real_path, "r", encoding="utf-8", errors="replace") as f:
        if start_line is not None or end_line is not None:
            lines = f.readlines()
            total_lines = len(lines)
            s = max(1, int(start_line)) if start_line is not None else 1
            e = min(total_lines, int(end_line)) if end_line is not None else total_lines
            if s > total_lines:
                return f"ℹ️ start_line ({s}) exceeds total lines ({total_lines}) in `{path}`."
            selected = lines[s - 1:e]
            rel_path = os.path.relpath(real_path, WORKSPACE_ROOT)
            header = f"### File: `{rel_path}` (Lines {s}-{e} of {total_lines})\n```\n"
            return header + "".join(selected) + "\n```"
        else:
            content = f.read(clamped_max_bytes)
            rel_path = os.path.relpath(real_path, WORKSPACE_ROOT)
            truncated = " [truncated]" if f.read(1) else ""
            return f"### File: `{rel_path}`{truncated}\n```\n{content}\n```"


# MCP Tool Definitions
TOOLS = [
    {
        "name": "write_file",
        "description": "Writes or appends text content to a local file within the workspace with optional executable permissions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or workspace-contained path to the target file."
                },
                "content": {
                    "type": "string",
                    "description": "The exact text content to write to the file."
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Write mode: 'overwrite' (default) or 'append'."
                },
                "make_executable": {
                    "type": "boolean",
                    "description": "If true, sets executable permissions (chmod +x) on the file."
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "read_file",
        "description": "Reads text content from a local file within the workspace with optional line range slicing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or workspace-contained path to the target file."
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-indexed starting line number."
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional 1-indexed ending line number."
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default: 65536, max: 1048576)."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "ollama_list_models",
        "description": "Lists all AI models currently installed in the local Ollama instance with their sizes, parameter counts, and quantization levels.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "ollama_chat",
        "description": "Send a prompt or chat messages to a local Ollama model (e.g. qwen3:8b, mistral-nemo:12b, qwen2.5-coder:7b) and receive the generated response.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "The name of the local Ollama model to use (e.g., 'qwen3:8b', 'mistral-nemo:12b', 'qwen2.5-coder:7b')."
                },
                "prompt": {
                    "type": "string",
                    "description": "The user prompt to generate a response for."
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt defining the persona or task constraints."
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (default: 0.7)."
                },
                "num_ctx": {
                    "type": "integer",
                    "description": "Context window size in tokens (default: 4096)."
                }
            },
            "required": ["model", "prompt"]
        }
    },
    {
        "name": "ollama_task_agent",
        "description": "Delegate a complex coding, sysadmin, or reasoning task to a local Ollama model with structured analysis, implementation, and verification output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task description or goal to solve."
                },
                "model": {
                    "type": "string",
                    "description": "Local model to use (defaults to 'qwen3:8b')."
                },
                "context": {
                    "type": "string",
                    "description": "Optional workspace context, file contents, or diagnostic logs."
                },
                "task_type": {
                    "type": "string",
                    "description": "Category of the task: 'sysadmin', 'ansible', 'coding', 'reasoning', or 'general'."
                },
                "num_ctx": {
                    "type": "integer",
                    "description": "Context length in tokens (default: 4096)."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "ollama_pull_model",
        "description": "Download and pull a new model from the Ollama library into the local instance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "The name/tag of the model to pull (e.g., 'qwen2.5-coder:7b', 'olmoe:7b-instruct')."
                }
            },
            "required": ["model"]
        }
    },
    {
        "name": "ollama_execute_task",
        "description": "Direct Ollama agent to execute a shell command/script, capture execution output, and verify the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command or script to execute."
                },
                "task_description": {
                    "type": "string",
                    "description": "Optional description of what the command is intended to accomplish."
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory in which to execute the command."
                },
                "model": {
                    "type": "string",
                    "description": "Local model to use for output analysis and verification (defaults to 'qwen3:8b')."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (default: 120)."
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "ansible_syntax_check",
        "description": "Validates Ansible playbook or task YAML syntax using ansible-playbook with isolated concurrency-safe temporary environments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The YAML playbook or task content to validate."
                },
                "is_playbook": {
                    "type": "boolean",
                    "description": "Whether the content is a full playbook (default: true) or a task list."
                },
                "venv_path": {
                    "type": "string",
                    "description": "Optional path to a Python virtual environment containing ansible (e.g., 'sysadmin/venv')."
                },
                "bin_dir": {
                    "type": "string",
                    "description": "Optional explicit directory containing the ansible-playbook binary."
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "shellcheck_inspect",
        "description": "Runs ShellCheck static analysis on bash/sh scripts to identify syntax errors, quoting bugs, and unhandled traps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The shell script code or snippet to inspect."
                },
                "venv_path": {
                    "type": "string",
                    "description": "Optional path to a Python virtual environment containing shellcheck (e.g., 'sysadmin/venv')."
                },
                "bin_dir": {
                    "type": "string",
                    "description": "Optional explicit directory containing the shellcheck binary."
                }
            },
            "required": ["script"]
        }
    },
    {
        "name": "service_status",
        "description": "Queries systemctl service status with bounded unpaged output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Optional systemd unit name to query (e.g. 'docker.service', 'sshd')."
                },
                "failed_only": {
                    "type": "boolean",
                    "description": "If true, lists only failed units (systemctl --failed)."
                }
            },
            "required": []
        }
    },
    {
        "name": "journal_logs",
        "description": "Queries bounded journalctl log entries filtered by unit, priority, and lines limit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Optional systemd unit name to filter logs for (e.g. 'ollama.service', 'sshd')."
                },
                "lines": {
                    "type": "integer",
                    "description": "Maximum number of recent log lines to return (default: 50, max: 200)."
                },
                "priority": {
                    "type": "string",
                    "description": "Optional log priority level ('emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug')."
                },
                "since": {
                    "type": "string",
                    "description": "Optional time filter (e.g., '1 hour ago', 'today', '2026-08-16 12:00:00')."
                }
            },
            "required": []
        }
    }
]


def process_jsonrpc(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Processes an incoming JSON-RPC 2.0 request."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "local-ollama-mcp",
                    "version": "1.0.0"
                }
            }
        }
    
    if method == "notifications/initialized":
        return None  # Notifications do not return responses
    
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }
    
    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        
        try:
            if tool_name == "write_file":
                text = handle_write_file(
                    path=args.get("path", ""),
                    content=args.get("content", ""),
                    mode=args.get("mode", "overwrite"),
                    make_executable=bool(args.get("make_executable", False))
                )
            elif tool_name == "read_file":
                text = handle_read_file(
                    path=args.get("path", ""),
                    start_line=args.get("start_line"),
                    end_line=args.get("end_line"),
                    max_bytes=int(args.get("max_bytes", 65536))
                )
            elif tool_name == "ollama_list_models":
                text = handle_list_models()
            elif tool_name == "ollama_chat":
                text = handle_chat(
                    model=args.get("model", "qwen3:8b"),
                    prompt=args.get("prompt"),
                    system_prompt=args.get("system_prompt"),
                    temperature=float(args.get("temperature", 0.7)),
                    num_ctx=int(args.get("num_ctx", 4096))
                )
            elif tool_name == "ollama_task_agent":
                text = handle_task_agent(
                    task=args.get("task", ""),
                    model=args.get("model", "qwen3:8b"),
                    context=args.get("context"),
                    task_type=args.get("task_type", "general"),
                    num_ctx=int(args.get("num_ctx", 4096))
                )
            elif tool_name == "ollama_pull_model":
                text = handle_pull_model(args.get("model", ""))
            elif tool_name == "ollama_execute_task":
                text = handle_execute_task(
                    command=args.get("command", ""),
                    task_description=args.get("task_description"),
                    cwd=args.get("cwd"),
                    model=args.get("model", "qwen3:8b"),
                    timeout=int(args.get("timeout", 120))
                )
            elif tool_name == "ansible_syntax_check":
                text = handle_ansible_syntax_check(
                    content=args.get("content", ""),
                    is_playbook=bool(args.get("is_playbook", True)),
                    venv_path=args.get("venv_path"),
                    bin_dir=args.get("bin_dir")
                )
            elif tool_name == "shellcheck_inspect":
                text = handle_shellcheck_inspect(
                    script=args.get("script", ""),
                    venv_path=args.get("venv_path"),
                    bin_dir=args.get("bin_dir")
                )
            elif tool_name == "service_status":
                text = handle_service_status(
                    unit=args.get("unit"),
                    failed_only=bool(args.get("failed_only", False))
                )
            elif tool_name == "journal_logs":
                text = handle_journal_logs(
                    unit=args.get("unit"),
                    lines=int(args.get("lines", 50)),
                    priority=args.get("priority"),
                    since=args.get("since")
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]
                    }
                }
                
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}]
                }
            }
        except Exception as e:
            sys.stderr.write(f"[ERROR] Tool execution failed for {tool_name}: {e}\n")
            sys.stderr.flush()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Error executing {tool_name}: An internal error occurred. Check server logs."}]
                }
            }
    
    # Method not found
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}"
        }
    }


def main():
    """Main stdio loop for MCP server."""
    # Ensure stdout/stderr encoding
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = process_jsonrpc(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            err_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }
            sys.stdout.write(json.dumps(err_response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Unexpected error in MCP loop: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
