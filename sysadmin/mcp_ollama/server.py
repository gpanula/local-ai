#!/usr/bin/env python3
"""
Local Ollama MCP Server
Provides a Model Context Protocol (MCP) interface over stdio to delegate tasks,
chat, code generation, and model management to a local Ollama instance.
"""

import contextlib
import datetime
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

MCP_LOG_FILE = os.environ.get("MCP_LOG_FILE", "/tmp/mcp_ollama_wire.log")
ACTIVE_PIPELINE_RUNS: Dict[str, Dict[str, Any]] = {}
_MCP_STDOUT = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout



def _wire_log(msg: str) -> None:
    try:
        ts = datetime.datetime.now().isoformat()
        with open(MCP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [PID {os.getpid()}] {msg}\n")
    except Exception:
        pass


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
# Make `mcp_core` importable when server.py runs as a standalone script (it is
# invoked via subprocess by mcp_core.transport.call_mcp), then share the canonical
# workspace helpers instead of redefining them locally.
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))
# Ensure the sysadmin virtual environment site-packages are resolvable even if invoked from system python
_venv_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "venv"))
if os.path.isdir(_venv_dir):
    import site
    _py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    _site_pkg = os.path.join(_venv_dir, "lib", _py_ver, "site-packages")
    if os.path.isdir(_site_pkg) and _site_pkg not in sys.path:
        site.addsitedir(_site_pkg)

from mcp_core.workspace import WORKSPACE_ROOT, validate_workspace_path, is_valid_mcp_socket
from mcp_core.hardware import get_default_model

# Alias to the historical private names so existing call sites remain unchanged.
_validate_workspace_path = validate_workspace_path
_is_valid_mcp_socket = is_valid_mcp_socket


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


def get_installed_model_names() -> List[str]:
    """Returns a list of all model names currently installed in local Ollama."""
    try:
        data = _http_request("/api/tags", method="GET")
        models = data.get("models", [])
        names = []
        for m in models:
            name = m.get("name", "")
            if name:
                names.append(name)
                if name.endswith(":latest"):
                    names.append(name[:-7])
        return names
    except Exception as e:
        _wire_log(f"Failed to query installed models: {e}")
        return []


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


_MODEL_CONTEXT_CACHE: Dict[str, int] = {}


def _get_model_context_length(model: str) -> int:
    """Inspect the model via /api/show to determine its configured context window size."""
    if model in _MODEL_CONTEXT_CACHE:
        return _MODEL_CONTEXT_CACHE[model]
    
    ctx_len = 24576
    try:
        data = _http_request("/api/show", method="POST", data={"name": model})
        # 1. Check parameters string
        params_str = data.get("parameters", "")
        for line in params_str.splitlines():
            if "num_ctx" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ctx_len = int(parts[1])
                    _MODEL_CONTEXT_CACHE[model] = ctx_len
                    return ctx_len
        # 2. Check modelfile string
        modelfile = data.get("modelfile", "")
        for line in modelfile.splitlines():
            if "num_ctx" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ctx_len = int(parts[-1])
                    _MODEL_CONTEXT_CACHE[model] = ctx_len
                    return ctx_len
        # 3. Check model_info dict
        model_info = data.get("model_info", {})
        for k, v in model_info.items():
            if "context_length" in k:
                ctx_len = int(v)
                _MODEL_CONTEXT_CACHE[model] = ctx_len
                return ctx_len
    except Exception:
        pass
    
    _MODEL_CONTEXT_CACHE[model] = ctx_len
    return ctx_len


def handle_chat(
    model: str,
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.7,
    top_p: Optional[float] = None,
    num_ctx: Optional[int] = None
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
    
    options: Dict[str, Any] = {"temperature": temperature}
    if top_p is not None:
        options["top_p"] = top_p
    if num_ctx is not None and num_ctx > 0:
        options["num_ctx"] = num_ctx

    payload = {
        "model": model,
        "messages": chat_messages,
        "stream": False,
        "options": options
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

    # Extract performance, residency, and context window metrics if available
    prompt_eval_count = response.get("prompt_eval_count", 0)
    eval_count = response.get("eval_count", 0)
    eval_duration = response.get("eval_duration", 0)
    load_duration = response.get("load_duration", 0)
    total_tokens = prompt_eval_count + eval_count

    effective_ctx = num_ctx if (num_ctx and num_ctx > 0) else _get_model_context_length(model)
    percent_used = (total_tokens / effective_ctx * 100) if effective_ctx > 0 else 0.0
    tps = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0.0

    # Model residency: cold load from disk (>0.5s) vs hot resident in VRAM
    residency_str = f"cold load ({load_duration/1e9:.2f}s)" if load_duration > 500_000_000 else "resident"

    stats = (
        f"\n\n---\n*Generated by `{model}`: {eval_count} tokens in {eval_duration/1e9:.2f}s ({tps:.1f} t/s) [{residency_str}] | "
        f"Context: {total_tokens:,} / {effective_ctx:,} tokens ({percent_used:.1f}%)*"
    )

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
    num_ctx: Optional[int] = None
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


def handle_unload_model(model: Optional[str] = None) -> str:
    """Immediately unloads a model (or all currently loaded models) from VRAM."""
    if model:
        _http_request("/api/generate", method="POST", data={"model": model, "keep_alive": 0})
        return f"Successfully unloaded model `{model}` from VRAM."
    
    ps_data = _http_request("/api/ps", method="GET")
    unloaded = []
    for m in ps_data.get("models", []):
        m_name = m.get("name") or m.get("model")
        if m_name:
            _http_request("/api/generate", method="POST", data={"model": m_name, "keep_alive": 0})
            unloaded.append(m_name)
    if unloaded:
        return f"Successfully unloaded {len(unloaded)} model(s) from VRAM: {', '.join(unloaded)}."
    return "No models were loaded in VRAM."


def _execute_in_terminal_mcp(command: str, cwd: Optional[str] = None, timeout: int = 180, socket_path: Optional[str] = None) -> Tuple[str, int, str]:
    """Executes a command inside the active terminal-mcp session via Unix socket and captures the terminal buffer."""
    import socket
    import time

    sock_path = socket_path or os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")
    inner_cmd = f"cd {shlex.quote(cwd)} && (\n{command}\n)" if cwd else f"(\n{command}\n)"
    exec_command = f"{inner_cmd}; __LOCALAI_EC=$?; echo \"__LOCALAI_EXIT:${{__LOCALAI_EC}}__\""

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(sock_path)
        s_file = s.makefile("r", encoding="utf-8")

        # Send type command directly to terminal-mcp tool proxy
        type_req = {"id": 1, "method": "type", "params": {"text": exec_command.rstrip("\n") + "\n"}}
        s.sendall(json.dumps(type_req).encode("utf-8") + b"\n")
        s_file.readline()

        start_time = time.time()
        last_text = ""
        req_id = 2

        time.sleep(1.0)
        while time.time() - start_time < timeout:
            get_req = {"id": req_id, "method": "getContent", "params": {"visibleOnly": False}}
            req_id += 1
            s.sendall(json.dumps(get_req).encode("utf-8") + b"\n")
            res_line = s_file.readline()
            if not res_line:
                break
            try:
                res = json.loads(res_line)
                last_text = res.get("result", {}).get("content", [{}])[0].get("text", "")
                lines = [l.strip() for l in last_text.strip().splitlines() if l.strip()]
                if lines and (lines[-1].endswith("$") or lines[-1].endswith("#") or "⚡ mcp" in lines[-1]):
                    if len(lines) > 1 and command.strip() not in lines[-1]:
                        break
            except json.JSONDecodeError:
                pass
            time.sleep(1.0)

        s.close()

        # Extract exit code from marker (use last match to avoid stale scrollback markers)
        ec_matches = re.findall(r"__LOCALAI_EXIT:(\d+)__", last_text)
        if ec_matches:
            exit_code = int(ec_matches[-1])
        else:
            exit_code = 0

        # Scope error indicator inspection to current command execution output
        eval_text = last_text
        if inner_cmd in last_text:
            eval_text = last_text.rsplit(inner_cmd, 1)[-1]
        elif command.strip() in last_text:
            eval_text = last_text.rsplit(command.strip(), 1)[-1]

        # Safety override (AGENTS.md Rule 2): Never rely solely on exit 0.
        # Inspect buffer for hidden tracebacks, syntax errors, or permission faults.
        error_indicators = [
            "❌ [ERROR]",
            "Traceback (most recent call last)",
            "command not found",
            "No such file or directory",
            "SyntaxError:",
            "Permission denied",
        ]
        if exit_code == 0 and any(err in eval_text for err in error_indicators):
            exit_code = 1

        cleaned_text = re.sub(r"__LOCALAI_EXIT:\d+__\r?\n?", "", last_text)
        lines = cleaned_text.strip().splitlines()
        tail = "\n".join(lines[-40:]) if len(lines) > 40 else cleaned_text
        return tail, exit_code, "terminal-mcp PTY"
    except Exception as e:
        try:
            s.close()
        except Exception:
            pass
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
    work_dir = os.path.expanduser(cwd) if cwd else WORKSPACE_ROOT
    execution_target = "host subprocess"

    terminal_sock = os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")
    used_socket = False
    if _is_valid_mcp_socket(terminal_sock):
        try:
            stdout, exit_code, execution_target = _execute_in_terminal_mcp(command, cwd=work_dir, timeout=timeout)
            stderr = ""
            used_socket = True
        except Exception:
            used_socket = False

    if not used_socket:
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


PIPELINE_PARAMETER_HELP: Dict[str, str] = {
    "prompt": (
        "### Parameter: `prompt`\n"
        "- **Type**: `string` (required unless `resume` is specified)\n"
        "- **Description**: Task prompt text or workspace-relative path to a Markdown prompt specification file.\n"
        "- **Behavior**: If the value matches an existing file (e.g. 'sysadmin/prompts/task.md'), the file contents are automatically read and supplied to the pipeline. Otherwise, raw text is treated as the direct prompt.\n"
        "- **Role Handling**: Passed to the Architect for problem decomposition, risk assessment, and DAG synthesis.\n"
        "- **Example**: `prompt='sysadmin/prompts/verify_code_quality_toolchain.md'`"
    ),
    "model": (
        "### Parameter: `model`\n"
        "- **Type**: `string` (optional, default: 'winter-prime:latest' or 'winter-prime:16gb')\n"
        "- **Description**: Primary Ollama model used for Builder roles (Architect, Orchestrator, Coder, Sysadmin).\n"
        "- **Residency Resolution**: When `dual_model=True` or `dynamic_auditor=True`, this defaults to 'winter-prime:16gb' to preserve 24GB VRAM residency alongside the auditor model.\n"
        "- **Example**: `model='winter-prime:16gb'`"
    ),
    "auditor_model": (
        "### Parameter: `auditor_model`\n"
        "- **Type**: `string` (optional, default: 'qwen3:8b' in dual-model mode, or dynamically chosen)\n"
        "- **Description**: Secondary Critic/Auditor model for Reviewer Gate, Security Gate, and Code Review.\n"
        "- **Anti-Self-Review Invariant**: Enforces Check 10 by ensuring plans and code are audited by an independent model instance rather than the authoring Builder model.\n"
        "- **Example**: `auditor_model='qwen3:8b'`"
    ),
    "dual_model": (
        "### Parameter: `dual_model`\n"
        "- **Type**: `boolean` (optional, default: false)\n"
        "- **Description**: Enables 24GB dual-model residency (Builder: 'winter-prime:16gb', Auditor: 'qwen3:8b').\n"
        "- **VRAM & Lifecycle**: Activates the 24GB hardware tier which disables inter-stage model unloading (`state.unload_models = False`). Both models stay resident in VRAM for zero-reload transition speed.\n"
        "- **Example**: `dual_model=True`"
    ),
    "dynamic_auditor": (
        "### Parameter: `dynamic_auditor`\n"
        "- **Type**: `boolean` (optional, default: false)\n"
        "- **Description**: Enables dynamic Auditor selection by the Orchestrator/Architect based on task domain tags and risk vectors.\n"
        "- **Specialization**: Selects reasoning models (e.g. `deepseek-r1:8b`) for logic/math, `qwen3:8b` for architecture/sysadmin, or `codestral` for polyglot code.\n"
        "- **VRAM & Lifecycle**: Activates 24GB residency tier with model unloading disabled (`state.unload_models = False`).\n"
        "- **Example**: `dynamic_auditor=True`"
    ),
    "keep_models": (
        "### Parameter: `keep_models`\n"
        "- **Type**: `boolean` (optional, default: false)\n"
        "- **Description**: Explicitly forces models to remain loaded in GPU VRAM across all stages without unloading.\n"
        "- **Behavioral Mapping**: Overrides tier-based auto-unloading (such as the default 8GB tier laptop behavior which unloads models between stages to conserve memory). Setting `keep_models=True` prevents all unloading calls to Ollama, eliminating cold-load latency.\n"
        "- **Example**: `keep_models=True`"
    ),
    "retry_budget": (
        "### Parameter: `retry_budget`\n"
        "- **Type**: `integer` (optional, default: 3, range: 1 to 15)\n"
        "- **Description**: Configurable maximum retry attempts per cognitive stage (Architect, Orchestrator, Coder, Sysadmin) upon failed validation checks, linter errors, or gate rejections.\n"
        "- **Example**: `retry_budget=5`"
    ),
    "resume": (
        "### Parameter: `resume`\n"
        "- **Type**: `string` (optional, default: None)\n"
        "- **Description**: Existing Run ID (e.g. 'run-20260924-051544-1db8b9') used to resume an aborted run from its checkpoint in `runs/<run_id>/state.json`.\n"
        "- **Example**: `resume='run-20260924-051544-1db8b9'`"
    ),
    "async_run": (
        "### Parameter: `async_run`\n"
        "- **Type**: `boolean` (optional, default: false)\n"
        "- **Description**: Executes the pipeline asynchronously in a background thread and immediately returns a JSON response containing `status: 'started'` and the `run_id`.\n"
        "- **Client Protection**: Prevents client-side JSON-RPC / MCP stdio timeouts on long-running multi-agent runs (5-15 mins). Progress streams live to `terminal-mcp` and can be checked via `pipeline_status(run_id=...)`.\n"
        "- **Example**: `async_run=True`"
    ),
    "help": (
        "### Parameter: `help`\n"
        "- **Type**: `string` or `boolean` (optional, default: None)\n"
        "- **Description**: Request verbose self-documenting help directly from the server.\n"
        "- **Usage Modes**:\n"
        "  - `help=True` or `help='all'`: Full documentation of the pipeline runner and all parameters.\n"
        "  - `help='<param_name>'` (e.g. `help='keep_models'`, `help='dual_model'`): In-depth help, VRAM implications, and examples for that specific parameter.\n"
        "- **Examples**:\n"
        "  - `run_pipeline(help=True)`\n"
        "  - `run_pipeline(help='keep_models')`"
    ),
}


def get_pipeline_help(param: Optional[Union[bool, str]] = None) -> str:
    """Generates comprehensive or parameter-specific verbose documentation."""
    if isinstance(param, str):
        key = param.strip().lower()
        if key in PIPELINE_PARAMETER_HELP:
            return PIPELINE_PARAMETER_HELP[key]
        for k, text in PIPELINE_PARAMETER_HELP.items():
            if key == k or key in k:
                return text

    overview = [
        "### Arc-Orc-Rev Multi-Agent Pipeline Runner (`run_pipeline` / `process_prompt`)\n",
        "Executes the autonomous 6-role multi-agent pipeline:",
        "Architect ➔ Orchestrator ➔ Reviewer Gate ➔ Security Gate ➔ Coder ➔ Sysadmin (Live PTY) ➔ Continuous Memory Persistence.\n",
        "**Available Parameters:**\n",
    ]
    for param_name in [
        "prompt", "model", "auditor_model", "dual_model", "dynamic_auditor",
        "keep_models", "retry_budget", "resume", "async_run", "help"
    ]:
        if param_name in PIPELINE_PARAMETER_HELP:
            overview.append(f"{PIPELINE_PARAMETER_HELP[param_name]}\n")

    overview.append(
        "\n**Parameter Deep-Dive Query:**\n"
        "To view deep-dive help for a single parameter, pass `help='<parameter_name>'`, e.g.:\n"
        "- `run_pipeline(help='keep_models')`\n"
        "- `run_pipeline(help='dual_model')`\n"
        "- `run_pipeline(help='dynamic_auditor')`\n\n"
        "**Execution Examples:**\n"
        "- `run_pipeline(prompt='sysadmin/prompts/task.md', dual_model=True, dynamic_auditor=True, keep_models=True, async_run=True)`\n"
        "- `run_pipeline(prompt='sysadmin/prompts/task.md', retry_budget=5, async_run=True)`\n"
        "- `run_pipeline(resume='run-20260907-...')`"
    )
    return "\n".join(overview)


def handle_run_pipeline(
    prompt: str = "",
    model: Optional[str] = None,
    resume: Optional[str] = None,
    auditor_model: Optional[str] = None,
    dual_model: bool = False,
    dynamic_auditor: bool = False,
    keep_models: bool = False,
    retry_budget: Optional[int] = None,
    async_run: bool = False,
    help: Optional[Union[bool, str]] = None,
) -> str:
    """
    Executes the full Arc-Orc-Rev multi-agent pipeline (Architect -> Orchestrator ->
    Reviewer Gate -> Security Gate -> Multi-Tier Code Verification -> Live PTY Execution ->
    Continuous Memory & Trajectory Persistence). Supports synchronous and asynchronous background execution.
    """
    prompt_raw = (prompt or "").strip()
    resume_raw = (resume or "").strip()

    if help is not None and help is not False:
        return get_pipeline_help(help)

    if prompt_raw.lower() in ("--help", "-h", "help"):
        return get_pipeline_help(True)

    if not resume_raw and not prompt_raw:
        raise ValueError("A non-empty 'prompt' (or prompt file path) or a 'resume' Run ID is required (or pass 'help=True').")

    prompt_content = prompt_raw
    if prompt_content:
        target_path = os.path.join(WORKSPACE_ROOT, prompt_content) if not os.path.isabs(prompt_content) else prompt_content
        if os.path.isfile(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                prompt_content = f.read().strip()
        elif os.path.isfile(prompt_content):
            with open(prompt_content, "r", encoding="utf-8") as f:
                prompt_content = f.read().strip()

    if dynamic_auditor:
        selected_model = model or "winter-prime:16gb"
        selected_auditor = auditor_model
    elif dual_model:
        selected_model = model or "winter-prime:16gb"
        selected_auditor = auditor_model or "qwen3:8b"
    else:
        selected_model = model or "winter-prime:latest"
        selected_auditor = auditor_model

    kwargs = {"model": selected_model}
    if selected_auditor:
        kwargs["auditor_model"] = selected_auditor
    if dynamic_auditor:
        kwargs["dynamic_auditor"] = True
    if keep_models:
        kwargs["keep_models"] = True
    if retry_budget is not None:
        kwargs["retry_budget"] = int(retry_budget)

    from pipeline import run_pipeline, resume_pipeline, generate_run_id

    if async_run:
        target_run_id = resume_raw if resume_raw else generate_run_id()
        record = {
            "run_id": target_run_id,
            "status": "running",
            "started_at": datetime.datetime.now().isoformat(),
            "prompt_preview": prompt_content[:200],
            "builder_model": selected_model,
            "auditor_model": selected_auditor,
            "keep_models": keep_models,
            "error": None,
            "result": None,
        }
        ACTIVE_PIPELINE_RUNS[target_run_id] = record

        def _worker():
            try:
                if resume_raw:
                    res = resume_pipeline(resume_raw, **kwargs)
                else:
                    res = run_pipeline(prompt_content, run_id=target_run_id, **kwargs)
                record["status"] = "complete"
                record["result"] = res
                _wire_log(f"Async pipeline worker completed for {target_run_id}")
            except Exception as ex:
                record["status"] = "failed"
                record["error"] = str(ex)
                _wire_log(f"Async pipeline worker failed for {target_run_id}: {ex}\n{traceback.format_exc()}")

        thread = threading.Thread(target=_worker, name=f"pipeline-{target_run_id}", daemon=False)
        thread.start()
        record["thread"] = thread

        return json.dumps({
            "status": "started",
            "run_id": target_run_id,
            "async": True,
            "message": f"Pipeline run {target_run_id} launched in background thread. Track progress via 'pipeline_status' tool or terminal-mcp.",
            "builder_model": selected_model,
            "auditor_model": selected_auditor,
            "keep_models": keep_models,
            "tier": "24gb" if (dual_model or dynamic_auditor) else "latest",
        }, indent=2)

    if resume_raw:
        result = resume_pipeline(resume_raw, **kwargs)
    else:
        result = run_pipeline(prompt_content, **kwargs)

    return json.dumps(result, indent=2)


def handle_pipeline_status(run_id: Optional[str] = None, verbose: bool = False, **kwargs) -> str:
    """
    Queries execution status, phase, events, and task outcomes for a pipeline run.
    If verbose=True or diagnostic flags are passed, delegates to handle_inspect_pipeline_run.
    """
    if verbose or kwargs.get("diagnostics") or kwargs.get("inspect"):
        return handle_inspect_pipeline_run(run_id=run_id, **kwargs)

    from mcp_core.context_store import ContextStore
    store = ContextStore()

    target_run_id = (run_id or "").strip()
    if not target_run_id:
        if ACTIVE_PIPELINE_RUNS:
            target_run_id = list(ACTIVE_PIPELINE_RUNS.keys())[-1]
        else:
            candidates = []
            if os.path.isdir(store.runs_dir):
                for item in os.listdir(store.runs_dir):
                    if item.startswith("run-"):
                        p = os.path.join(store.runs_dir, item)
                        mtime = os.path.getmtime(p)
                        clean_id = item[:-8] if item.endswith(".tar.zst") else (item[:-4] if item.endswith(".tar") else item)
                        candidates.append((mtime, clean_id))
            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                target_run_id = candidates[0][1]

    if not target_run_id:
        return json.dumps({"error": "No pipeline runs found and no run_id specified."}, indent=2)

    mem_record = ACTIVE_PIPELINE_RUNS.get(target_run_id, {})
    is_thread_alive = False
    if mem_record and "thread" in mem_record:
        is_thread_alive = mem_record["thread"].is_alive()

    try:
        state_dict = store.load(f"runs/{target_run_id}/state.json")
        status = state_dict.get("status", "unknown")
        if is_thread_alive and status != "complete":
            status = "running"

        events = state_dict.get("events", [])
        recent_events = events[-5:] if len(events) > 5 else events

        out = {
            "run_id": target_run_id,
            "status": status,
            "current_phase": state_dict.get("current_phase", "unknown"),
            "builder_model": state_dict.get("builder_model"),
            "auditor_model": state_dict.get("auditor_model"),
            "tasks": state_dict.get("tasks", {}),
            "recent_events": recent_events,
            "thread_alive": is_thread_alive,
        }
        if mem_record.get("error"):
            out["error"] = mem_record["error"]

        return json.dumps(out, indent=2)
    except FileNotFoundError:
        if is_thread_alive:
            return json.dumps({
                "run_id": target_run_id,
                "status": "running",
                "current_phase": "initializing",
                "message": "Pipeline background thread is active; state.json is being initialized.",
                "thread_alive": True,
            }, indent=2)
        return json.dumps({
            "run_id": target_run_id,
            "status": "not_found",
            "error": f"Run '{target_run_id}' state.json could not be located.",
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "run_id": target_run_id,
            "status": "error",
            "error": f"Error inspecting run: {e}",
        }, indent=2)


def handle_inspect_pipeline_run(
    run_id: Optional[str] = None,
    tail_events: int = 50,
    include_failures: bool = True,
    include_tasks: bool = True,
    include_messages: bool = True,
    include_terminal_output: bool = True,
) -> str:
    """
    Deep-dive inspection of a pipeline run, returning comprehensive diagnostic details:
    status, failure chronology (linter rejections, shellcheck findings, review critiques),
    model escalations, terminal PTY execution outputs, task progress, and milestone events.
    """
    from mcp_core.context_store import ContextStore
    store = ContextStore()

    target_run_id = (run_id or "").strip()
    if not target_run_id:
        if ACTIVE_PIPELINE_RUNS:
            target_run_id = list(ACTIVE_PIPELINE_RUNS.keys())[-1]
        else:
            candidates = []
            if os.path.isdir(store.runs_dir):
                for item in os.listdir(store.runs_dir):
                    if item.startswith("run-"):
                        p = os.path.join(store.runs_dir, item)
                        mtime = os.path.getmtime(p)
                        clean_id = item[:-8] if item.endswith(".tar.zst") else (item[:-4] if item.endswith(".tar") else item)
                        candidates.append((mtime, clean_id))
            localai_runs = os.path.join(WORKSPACE_ROOT, ".localai", "runs")
            if os.path.isdir(localai_runs):
                for item in os.listdir(localai_runs):
                    if item.startswith("run-") and item.endswith(".jsonl"):
                        clean_id = item[:-6]
                        p = os.path.join(localai_runs, item)
                        mtime = os.path.getmtime(p)
                        candidates.append((mtime, clean_id))
            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                target_run_id = candidates[0][1]

    if not target_run_id:
        return json.dumps({"error": "No pipeline runs found and no run_id specified."}, indent=2)

    mem_record = ACTIVE_PIPELINE_RUNS.get(target_run_id, {})
    is_thread_alive = False
    if mem_record and "thread" in mem_record:
        is_thread_alive = mem_record["thread"].is_alive()

    diagnostics: Dict[str, Any] = {
        "run_id": target_run_id,
        "status": "unknown",
        "current_phase": "unknown",
        "outcome": None,
        "abort_reason": None,
        "thread_alive": is_thread_alive,
        "models": {},
        "tasks": {},
        "failure_chronology": [],
        "escalations": [],
        "terminal_execution": None,
        "recent_events": [],
    }

    try:
        state_dict = store.load(f"runs/{target_run_id}/state.json")
        diagnostics["status"] = state_dict.get("status", "unknown")
        diagnostics["current_phase"] = state_dict.get("current_phase", "unknown")
        diagnostics["models"]["builder"] = state_dict.get("builder_model")
        diagnostics["models"]["auditor"] = state_dict.get("auditor_model")
        if include_tasks:
            diagnostics["tasks"] = state_dict.get("tasks", {})
        events = state_dict.get("events", [])
        diagnostics["recent_events"] = events[-tail_events:] if len(events) > tail_events else events
    except Exception:
        pass

    if is_thread_alive and diagnostics["status"] != "complete":
        diagnostics["status"] = "running"

    jsonl_path = os.path.join(WORKSPACE_ROOT, ".localai", "runs", f"{target_run_id}.jsonl")
    if os.path.isfile(jsonl_path):
        diagnostics["log_file"] = os.path.relpath(jsonl_path, WORKSPACE_ROOT)
        current_stage = "unknown"
        current_attempt = 1
        current_model = diagnostics["models"].get("builder") or "unknown"
        terminal_chunks: List[str] = []

        try:
            with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = entry.get("type")
                    edata = entry.get("data", {})
                    ts = entry.get("timestamp", "")

                    if etype == "pipeline_start":
                        diagnostics["models"].update(edata.get("models", {}))
                        diagnostics["tier"] = edata.get("tier")
                        diagnostics["max_retries"] = edata.get("max_retries")
                        prompt_str = edata.get("prompt", "")
                        if prompt_str:
                            diagnostics["prompt_summary"] = prompt_str[:300] + ("..." if len(prompt_str) > 300 else "")
                    elif etype == "stage_transition":
                        current_stage = edata.get("stage", current_stage)
                        current_attempt = edata.get("iteration", current_attempt)
                    elif etype in ("model_escalated_secondary", "model_escalated_algorithmic"):
                        escalation_info = {
                            "timestamp": ts,
                            "task_id": edata.get("task_id"),
                            "prior_model": edata.get("prior_model"),
                            "escalated_model": edata.get("secondary_model") or edata.get("target_model"),
                            "attempt": edata.get("attempt"),
                            "tier": edata.get("tier"),
                            "type": etype,
                        }
                        diagnostics["escalations"].append(escalation_info)
                        current_model = escalation_info["escalated_model"]
                    elif etype == "linter_result":
                        passed = edata.get("passed", True)
                        if not passed and include_failures:
                            diagnostics["failure_chronology"].append({
                                "timestamp": ts,
                                "type": "linter_rejection",
                                "stage": current_stage,
                                "attempt": edata.get("iteration", current_attempt),
                                "model": current_model,
                                "returncode": edata.get("returncode"),
                                "output": edata.get("output", "")
                            })
                    elif etype == "review_result":
                        verdict = edata.get("verdict")
                        if verdict and verdict != "approved" and include_failures:
                            diagnostics["failure_chronology"].append({
                                "timestamp": ts,
                                "type": "review_rejection",
                                "stage": "reviewer",
                                "attempt": edata.get("iteration", current_attempt),
                                "reviewer_model": edata.get("reviewer_model"),
                                "verdict": verdict,
                                "critique": edata.get("critique", "")
                            })
                    elif etype == "code_security_verdict":
                        verdict = edata.get("verdict")
                        if verdict and verdict != "cleared" and include_failures:
                            diagnostics["failure_chronology"].append({
                                "timestamp": ts,
                                "type": "security_rejection",
                                "stage": "security",
                                "verdict": verdict,
                                "threats": edata.get("threats", []),
                                "behavioral_summary": edata.get("behavioral_summary", "")
                            })
                    elif etype == "terminal_chunk" and include_terminal_output:
                        text = edata.get("text", "")
                        if any(marker in text for marker in ("### 🖥️ Shell Command Execution", "❌", "Exit Code:", "🚨", "FAILED")):
                            terminal_chunks.append(text)
                    elif etype == "pipeline_end":
                        diagnostics["outcome"] = edata.get("outcome")
                        diagnostics["abort_reason"] = edata.get("abort_reason")
                        diagnostics["iterations"] = edata.get("iterations")
                        diagnostics["duration_sec"] = edata.get("duration_sec")
        except Exception as e:
            diagnostics["log_parse_error"] = str(e)

        if terminal_chunks and include_terminal_output:
            diagnostics["terminal_execution"] = "\n".join(terminal_chunks[-5:])

    if include_messages:
        try:
            plan = store.load(f"runs/{target_run_id}/messages/plan.json")
            diagnostics["plan_goal"] = plan.get("goal_summary")
        except Exception:
            pass

    return json.dumps(diagnostics, indent=2)



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
                    "description": "The name of the local Ollama model to use (e.g., 'qwen3:8b', 'mistral-nemo:12b', 'qwen2.5-coder:7b'). Defaults to system coder model."
                },
                "prompt": {
                    "type": "string",
                    "description": "The user prompt to generate a response for."
                },
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object"
                    },
                    "description": "Optional list of chat messages [{'role': 'user', 'content': '...'}, ...] for multi-turn conversation."
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt defining the persona or task constraints."
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (default: 0.7)."
                },
                "top_p": {
                    "type": "number",
                    "description": "Optional nucleus sampling parameter (top_p)."
                },
                "num_ctx": {
                    "type": "integer",
                    "description": "Context window size in tokens (default: 4096)."
                }
            },
            "required": []
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
                "enable_tools": {
                    "type": "boolean",
                    "description": "If true, enables native file editing/reading tools for the task agent (default: true)."
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
        "name": "ollama_unload_model",
        "description": "Immediately unloads a model (or all currently loaded models) from VRAM to free GPU memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Optional model name to unload. If omitted, unloads all active models in VRAM."
                }
            },
            "required": []
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
                    "description": "Execution timeout in seconds (default: 180)."
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
    },
    {
        "name": "run_pipeline",
        "description": "Executes the Arc-Orc-Rev multi-agent pipeline (Architect -> Orchestrator -> Reviewer Gate -> Security Gate -> Multi-Tier Code Verification -> Live PTY Execution -> Memory & Trajectory Persistence) on a task prompt or prompt file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task prompt text or path to a markdown prompt file (e.g., 'sysadmin/prompts/verify_code_quality_toolchain.md'). Required unless 'resume' is specified."
                },
                "model": {
                    "type": "string",
                    "description": "Optional local Ollama model to use for Builder roles (default: 'winter-prime:latest', or 'winter-prime:16gb' when dual_model/dynamic_auditor is enabled)."
                },
                "auditor_model": {
                    "type": "string",
                    "description": "Optional secondary Auditor model for Reviewer Gate, Security Gate, and Code Review (e.g., 'qwen3:8b', 'deepseek-r1:8b', 'codestral')."
                },
                "dual_model": {
                    "type": "boolean",
                    "description": "Optional flag enabling 24GB dual-model residency (Builder: winter-prime:16gb, Auditor: qwen3:8b). Sets 24GB tier and disables model unloading between stages."
                },
                "dynamic_auditor": {
                    "type": "boolean",
                    "description": "Optional flag enabling dynamic Auditor model selection by the Orchestrator based on task domain tags and risk vectors. Sets 24GB tier and disables model unloading between stages."
                },
                "keep_models": {
                    "type": "boolean",
                    "description": "Optional flag to explicitly keep models loaded in GPU VRAM between stages without unloading, eliminating cold-load latency across any tier."
                },
                "retry_budget": {
                    "type": "integer",
                    "description": "Configurable maximum retry attempts per cognitive stage upon failed validation, lint, or gate checks (range: 1 to 15, default: 3)."
                },
                "resume": {
                    "type": "string",
                    "description": "Optional Run ID (e.g., 'run-20260924-051544-1db8b9') to resume an aborted run from state.json."
                },
                "async_run": {
                    "type": "boolean",
                    "description": "Optional flag to execute the pipeline asynchronously in a background thread to prevent client RPC timeouts (default: false). Streams output to terminal-mcp."
                },
                "help": {
                    "type": "string",
                    "description": "Optional self-documentation query. Pass true or 'all' for full documentation, or pass a specific parameter name (e.g., 'keep_models', 'dual_model', 'dynamic_auditor') for deep-dive verbose documentation."
                }
            },
            "required": []
        }
    },
    {
        "name": "process_prompt",
        "description": "Alias for run_pipeline: processes a task prompt through the autonomous Arc-Orc-Rev multi-agent pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task prompt text or path to a markdown prompt file (e.g., 'sysadmin/prompts/verify_code_quality_toolchain.md'). Required unless 'resume' is specified."
                },
                "model": {
                    "type": "string",
                    "description": "Optional local Ollama model to use for Builder roles (default: 'winter-prime:latest', or 'winter-prime:16gb' when dual_model/dynamic_auditor is enabled)."
                },
                "auditor_model": {
                    "type": "string",
                    "description": "Optional secondary Auditor model for Reviewer Gate, Security Gate, and Code Review (e.g., 'qwen3:8b', 'deepseek-r1:8b', 'codestral')."
                },
                "dual_model": {
                    "type": "boolean",
                    "description": "Optional flag enabling 24GB dual-model residency (Builder: winter-prime:16gb, Auditor: qwen3:8b). Sets 24GB tier and disables model unloading between stages."
                },
                "dynamic_auditor": {
                    "type": "boolean",
                    "description": "Optional flag enabling dynamic Auditor model selection by the Orchestrator based on task domain tags and risk vectors. Sets 24GB tier and disables model unloading between stages."
                },
                "keep_models": {
                    "type": "boolean",
                    "description": "Optional flag to explicitly keep models loaded in GPU VRAM between stages without unloading, eliminating cold-load latency across any tier."
                },
                "retry_budget": {
                    "type": "integer",
                    "description": "Configurable maximum retry attempts per cognitive stage upon failed validation, lint, or gate checks (range: 1 to 15, default: 3)."
                },
                "resume": {
                    "type": "string",
                    "description": "Optional Run ID (e.g., 'run-20260924-051544-1db8b9') to resume an aborted run from state.json."
                },
                "async_run": {
                    "type": "boolean",
                    "description": "Optional flag to execute the pipeline asynchronously in a background thread to prevent client RPC timeouts (default: false). Streams output to terminal-mcp."
                },
                "help": {
                    "type": "string",
                    "description": "Optional self-documentation query. Pass true or 'all' for full documentation, or pass a specific parameter name (e.g., 'keep_models', 'dual_model', 'dynamic_auditor') for deep-dive verbose documentation."
                }
            },
            "required": []
        }
    },
    {
        "name": "pipeline_status",
        "description": "Inspects the status, current phase, task progress, and recent milestone events of a local Ollama multi-agent pipeline run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Optional Run ID to inspect (e.g. 'run-20260924-051544-1db8b9'). If omitted, defaults to the latest active or completed run."
                }
            },
            "required": []
        }
    },
    {
        "name": "inspect_pipeline_run",
        "description": "Performs deep-dive diagnostic inspection of a pipeline run, retrieving failure chronology, linter critiques, ShellCheck findings, model escalations, terminal PTY execution outputs, and task progress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Optional Run ID to inspect (e.g. 'run-20260930-031018-495040'). If omitted, defaults to the latest active or completed run."
                },
                "tail_events": {
                    "type": "integer",
                    "description": "Number of recent milestone events to return (default: 50)."
                },
                "include_failures": {
                    "type": "boolean",
                    "description": "Whether to extract and structure all failure events, linter rejections, and critiques (default: true)."
                },
                "include_tasks": {
                    "type": "boolean",
                    "description": "Whether to include task breakdown and attempt counts (default: true)."
                },
                "include_messages": {
                    "type": "boolean",
                    "description": "Whether to inspect stored messages like plan and verdicts (default: true)."
                },
                "include_terminal_output": {
                    "type": "boolean",
                    "description": "Whether to capture terminal PTY execution logs and exit codes (default: true)."
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
    _wire_log(f"process_jsonrpc: method={method} req_id={req_id} params_keys={list(params.keys()) if isinstance(params, dict) else type(params)}")
    
    # JSON-RPC 2.0 Specification:
    # A Notification is a Request object without an 'id' member (req_id is None).
    # The server MUST NOT reply to a Notification under any circumstances.
    # Replying with {"id": null} causes Go's net/rpc/jsonrpc client in CORTEX
    # to throw 'invalid request' and abruptly drop the connection.
    if req_id is None:
        _wire_log(f"NOTIFICATION (suppressing response): method={method}")
        return None
    
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
    
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}
    
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
    
    if method == "logging/setLevel":
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
        _wire_log(f"tools/call: tool_name={tool_name} args={json.dumps(args)[:300]}")
        
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
                default_chat_model = get_default_model("coder")
                text = handle_chat(
                    model=args.get("model") or default_chat_model,
                    prompt=args.get("prompt"),
                    messages=args.get("messages"),
                    system_prompt=args.get("system_prompt"),
                    temperature=float(args.get("temperature", 0.7)),
                    top_p=float(args["top_p"]) if ("top_p" in args and args["top_p"] is not None) else None,
                    num_ctx=int(args["num_ctx"]) if ("num_ctx" in args and args["num_ctx"]) else None
                )
            elif tool_name == "ollama_task_agent":
                default_task_model = get_default_model("sysadmin")
                text = handle_task_agent(
                    task=args.get("task", ""),
                    model=args.get("model") or default_task_model,
                    context=args.get("context"),
                    task_type=args.get("task_type", "general"),
                    enable_tools=bool(args.get("enable_tools", True)),
                    num_ctx=int(args["num_ctx"]) if ("num_ctx" in args and args["num_ctx"]) else None
                )
            elif tool_name == "ollama_pull_model":
                text = handle_pull_model(args.get("model", ""))
            elif tool_name == "ollama_unload_model":
                text = handle_unload_model(args.get("model"))
            elif tool_name == "ollama_execute_task":
                default_exec_model = get_default_model("sysadmin")
                text = handle_execute_task(
                    command=args.get("command", ""),
                    task_description=args.get("task_description"),
                    cwd=args.get("cwd"),
                    model=args.get("model") or default_exec_model,
                    timeout=int(args.get("timeout", 180))
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
            elif tool_name in ("run_pipeline", "process_prompt", "ollama_run_pipeline"):
                text = handle_run_pipeline(
                    prompt=args.get("prompt", ""),
                    model=args.get("model"),
                    resume=args.get("resume"),
                    auditor_model=args.get("auditor_model"),
                    dual_model=bool(args.get("dual_model", False)),
                    dynamic_auditor=bool(args.get("dynamic_auditor", False)),
                    keep_models=bool(args.get("keep_models", False)),
                    retry_budget=args.get("retry_budget"),
                    async_run=bool(args.get("async_run", False)),
                    help=args.get("help"),
                )
            elif tool_name in ("pipeline_status", "get_pipeline_status"):
                text = handle_pipeline_status(
                    run_id=args.get("run_id"),
                    verbose=bool(args.get("verbose", False) or args.get("diagnostics", False) or args.get("inspect", False)),
                    tail_events=int(args.get("tail_events", 50)),
                    include_failures=bool(args.get("include_failures", True)),
                    include_tasks=bool(args.get("include_tasks", True)),
                    include_messages=bool(args.get("include_messages", True)),
                    include_terminal_output=bool(args.get("include_terminal_output", True)),
                )
            elif tool_name in ("inspect_pipeline_run", "inspect_run", "pipeline_inspect", "pipeline_diagnostics"):
                text = handle_inspect_pipeline_run(
                    run_id=args.get("run_id"),
                    tail_events=int(args.get("tail_events", 50)),
                    include_failures=bool(args.get("include_failures", True)),
                    include_tasks=bool(args.get("include_tasks", True)),
                    include_messages=bool(args.get("include_messages", True)),
                    include_terminal_output=bool(args.get("include_terminal_output", True)),
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
            tb = traceback.format_exc()
            _wire_log(f"[ERROR] Tool execution failed for {tool_name}: {e}\n{tb}")
            sys.stderr.write(f"[ERROR] Tool execution failed for {tool_name}: {e}\n")
            sys.stderr.flush()
            err_msg = str(e) if str(e).strip() else f"{type(e).__name__}: An error occurred during execution."
            full_error_text = f"Error executing {tool_name}: {err_msg}\n\n=== Traceback ===\n{tb}"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": full_error_text}]
                }
            }
    
    # Method not found
    _wire_log(f"METHOD NOT FOUND: method={method} req_id={req_id}")
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
            "data": {
                "requested_method": method,
                "supported_methods": [
                    "initialize",
                    "ping",
                    "tools/list",
                    "tools/call",
                    "resources/list",
                    "prompts/list",
                    "logging/setLevel"
                ]
            }
        }
    }



def main():
    """Main stdio loop for MCP server."""
    _wire_log(f"MCP server process started: PID={os.getpid()} PPID={os.getppid()} argv={sys.argv}")
    # Decouple process stdout from MCP protocol stdout:
    # Route generic sys.stdout to sys.stderr so background threads and libraries
    # writing or printing to stdout never corrupt or intercept the JSON-RPC wire.
    sys.stdout = sys.stderr
    try:
        for line in sys.stdin:
            line_clean = line.strip()
            if not line_clean:
                continue
            _wire_log(f"RECV RAW ({len(line_clean)} bytes): {line_clean[:300]}")
            try:
                request = json.loads(line_clean)
                response = process_jsonrpc(request)
                if response is not None:
                    resp_str = json.dumps(response)
                    _wire_log(f"SEND (id={response.get('id')} len={len(resp_str)}): {resp_str[:300]}")
                    _MCP_STDOUT.write(resp_str + "\n")
                    _MCP_STDOUT.flush()
            except json.JSONDecodeError as jde:
                _wire_log(f"JSONDecodeError: {jde} for: {line_clean[:200]}")
                sys.stderr.write(f"JSONDecodeError in MCP server: {jde}\n")
                sys.stderr.flush()
            except Exception as e:
                tb = traceback.format_exc()
                _wire_log(f"Unexpected error in MCP loop: {e}\n{tb}")
                sys.stderr.write(f"Unexpected error in MCP loop: {e}\n")
                sys.stderr.flush()
    except Exception as e:
        tb = traceback.format_exc()
        _wire_log(f"Fatal exception reading stdin: {e}\n{tb}")
    finally:
        _wire_log(f"MCP server process exiting: PID={os.getpid()}")




if __name__ == "__main__":
    main()
