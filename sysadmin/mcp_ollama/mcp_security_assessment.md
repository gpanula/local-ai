# Security Vulnerability Assessment & Implementation Plan

**Files Reviewed:**
- `sysadmin/mcp_client.py`
- `sysadmin/mcp_ollama/server.py`
- `sysadmin/start_terminal_mcp.sh`

*(Note: Shell execution injection vectors are considered core functionality for this AI-driven pipeline and are excluded from this report.)*

---

## Summary

| Severity | Count | Description |
|---|---|---|
| 🔴 Critical | 0 | - |
| 🟠 High | 3 | Arbitrary file read, socket symlink attack, unsafe fallback execution |
| 🟡 Medium | 4 | Silent exception swallowing, SSRF, path traversal, error info leak |
| 🔵 Low | 2 | OLLAMA_HOST validation, sandbox config hardening |

---

## 🟠 HIGH

### VULN-01: Arbitrary File Read via Unvalidated File Path (mcp_client.py L200, L210, L236)

**Location:** `mcp_client.py`

**Description:** The `task-file`, `build-and-run`, and `pipeline-run` subcommands accept a user-provided `file` argument and open it without validating that it lies within the expected workspace directory:

```python
with open(args.file, "r", encoding="utf-8") as f:
    prompt_content = f.read()
```

An attacker (or misconfigured automation) could pass paths like `../../.ssh/id_rsa`, `/etc/passwd`, or any other file readable by the current user.

**Fix:** After `os.path.realpath(args.file)`, assert that the resolved path starts with the expected workspace root (`PROJECT_ROOT`). Reject paths that escape the workspace.

---

### VULN-02: Socket Symlink Attack on TERMINAL_MCP_SOCKET (mcp_client.py L53, server.py L233)

**Location:** `mcp_client.py` L53-L55, `server.py` L233-L234

**Description:** The code uses `os.path.exists("/tmp/terminal-mcp.sock")` as a signal to route execution into the interactive terminal. If an attacker creates a symlink at `/tmp/terminal-mcp.sock` pointing to another socket or a regular file before the server starts, they can redirect all pipeline output and commands into an attacker-controlled socket.

**Fix:**
1. Use `os.stat(terminal_sock).st_mode` and `stat.S_ISSOCK()` to assert the path is a real Unix domain socket, not a symlink or regular file.
2. Verify the socket's owning UID matches `os.getuid()` before connecting.

---

### VULN-03: Unsafe `shell=True` Fallback in `_execute_in_terminal_mcp` (server.py L213)

**Location:** `server.py` L212-L215

**Description:** The exception fallback path in `_execute_in_terminal_mcp` uses `subprocess.run(command, shell=True, ...)`. If the PTY path fails for any reason, execution silently falls back to direct `shell=True` host execution with no sandboxing.

```python
except Exception:
    proc = subprocess.run(command, shell=True, ...)  # DANGEROUS fallback
```

**Fix:** Remove the silent `shell=True` fallback entirely. If PTY execution fails, raise a `RuntimeError` and surface it explicitly to the caller instead of silently downgrading to unsafe host execution.

---

## 🟡 MEDIUM

### VULN-04: Silent Exception Swallowing in `send_terminal_mcp` (mcp_client.py L84)

**Location:** `mcp_client.py` L84-L85

**Description:** The entire `send_terminal_mcp` function catches all exceptions with a bare `except Exception: pass`. This means that any failure is silently discarded, making it impossible to detect if the terminal stream is broken during a live pipeline run.

**Fix:** Replace `except Exception: pass` with `except Exception as e: logging.debug("send_terminal_mcp failed: %s", e)`.

---

### VULN-05: SSRF via User-Controlled OLLAMA_HOST (server.py L18)

**Location:** `server.py` L18

**Description:** `OLLAMA_HOST` is taken verbatim from the environment with no validation:

```python
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
```

If `OLLAMA_HOST` is set to an attacker-controlled URL, all Ollama API requests are forwarded to that URL — a Server-Side Request Forgery (SSRF) vulnerability.

**Fix:** Validate `OLLAMA_HOST` against an allowlist of schemes (`http`, `https`) and require it to resolve to a loopback or LAN address.

---

### VULN-06: Path Traversal in `_find_executable` (server.py L308-L313)

**Location:** `server.py` L307-L328

**Description:** `_find_executable` joins user-supplied `bin_dir` and `venv_path` arguments with the tool name using `os.path.join` without normalizing the result. An attacker passing `bin_dir=../../usr/bin` could traverse outside the intended workspace.

**Fix:** After constructing the candidate path, use `os.path.realpath(candidate)` and assert the resolved path begins with an expected workspace prefix.

---

### VULN-07: Error Message Information Leakage (server.py L835, mcp_client.py L36)

**Location:** `server.py` L835, `mcp_client.py` L36

**Description:** Raw Python exception messages including stack frames and full file paths are returned directly in JSON-RPC error responses, which can expose internal details to untrusted callers.

**Fix:** Log the full exception to stderr but return only a sanitized error message (e.g., `"An internal error occurred executing <tool_name>."`) in the JSON-RPC response.

---

## 🔵 LOW

### VULN-08: No Validation of OLLAMA_HOST URL Scheme (server.py L18)

**Location:** `server.py` L18

**Description:** There is no check that `OLLAMA_HOST` uses `http://` or `https://`. A `file://` or `ftp://` scheme would be passed directly to `urllib.request.urlopen`.

**Fix:** Parse `OLLAMA_HOST` with `urllib.parse.urlparse` and assert `scheme in ("http", "https")`. Raise a `ValueError` at startup if the scheme is invalid.

---

### VULN-09: Sandbox Config Not Validated Before Use (start_terminal_mcp.sh L14, L54-57)

**Location:** `start_terminal_mcp.sh` L14

**Description:** `SANDBOX_CONFIG` is assembled from `${SCRIPT_DIR}` and passed to `--sandbox-config` without verifying the file exists, is a regular file (not a symlink), and is not world-writable.

**Fix:**
1. Assert `[ -f "${SANDBOX_CONFIG}" ]` before use.
2. Assert `[ ! -L "${SANDBOX_CONFIG}" ]` (not a symlink).
3. Assert the file is not world-writable: `[[ "$(stat -c '%a' "${SANDBOX_CONFIG}")" != *[67]* ]]`

---

## Implementation Plan

> [!IMPORTANT]
> This plan is ordered by severity. Apply fixes in order.

### Phase 1: High — Validation & Fallback Fixes

#### Task 1.1 — Fix VULN-01: Workspace-Bound File Path Validation

**Files to modify:** `sysadmin/mcp_client.py`

**What to do:**
Add a helper function near the top of `mcp_client.py`:
```python
def _validate_workspace_path(path: str, purpose: str = "file") -> str:
    """Resolve and assert path lies within the workspace. Returns realpath."""
    workspace_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    resolved = os.path.realpath(os.path.abspath(path))
    if not resolved.startswith(workspace_root + os.sep):
        raise ValueError(f"Rejected {purpose} path outside workspace: {path!r}")
    return resolved
```
Call `_validate_workspace_path(args.file, "prompt")` at the top of each command handler that opens `args.file`.

#### Task 1.2 — Fix VULN-02: Validate Terminal Socket Type and Ownership

**Files to modify:** `sysadmin/mcp_client.py` L53-L55, `sysadmin/mcp_ollama/server.py` L233-L234

**What to do:**
Replace `os.path.exists(terminal_sock)` with a helper:
```python
import stat as _stat

def _is_valid_mcp_socket(path: str) -> bool:
    try:
        st = os.stat(path, follow_symlinks=False)
        return (
            _stat.S_ISSOCK(st.st_mode) and       # Must be a socket
            not _stat.S_ISLNK(st.st_mode) and    # Must not be a symlink
            st.st_uid == os.getuid()              # Must be owned by current user
        )
    except OSError:
        return False
```
Replace all `os.path.exists(terminal_sock)` checks in both files with `_is_valid_mcp_socket(terminal_sock)`.

#### Task 1.3 — Fix VULN-03: Remove `shell=True` Fallback in `_execute_in_terminal_mcp`

**Files to modify:** `sysadmin/mcp_ollama/server.py`

**What to do:**
Replace the entire `except Exception` block in `_execute_in_terminal_mcp` with:
```python
except Exception as e:
    raise RuntimeError(f"terminal-mcp PTY execution failed: {e}") from e
```
Remove the `shell=True` fallback subprocess call entirely.

---

### Phase 2: Medium — Hardening Fixes

#### Task 2.1 — Fix VULN-04: Surface Errors from `send_terminal_mcp`

**Files to modify:** `sysadmin/mcp_client.py`

**What to do:**
Replace `except Exception: pass` with:
```python
import logging
except Exception as e:
    logging.debug("send_terminal_mcp: stream error (non-fatal): %s", e)
```
Add `logging.basicConfig(level=logging.WARNING)` near the top of `main()`.

#### Task 2.2 — Fix VULN-05 & VULN-08: Validate OLLAMA_HOST at Startup

**Files to modify:** `sysadmin/mcp_ollama/server.py` L18

**What to do:**
Replace the bare environment read with a validated version using `urllib.parse` to ensure the scheme is `http/https` and it resolves to a loopback/private address.

#### Task 2.3 — Fix VULN-06: Path Traversal in `_find_executable`

**Files to modify:** `sysadmin/mcp_ollama/server.py`

**What to do:**
After constructing each `candidate` path in `_find_executable`, add a realpath check before the `os.access` test to assert the resolved path begins with the workspace root.

#### Task 2.4 — Fix VULN-07: Sanitize Exception Messages in JSON-RPC Responses

**Files to modify:** `sysadmin/mcp_ollama/server.py`

**What to do:**
In the `except Exception as e` handler in `process_jsonrpc`:
1. Log the full exception to stderr: `sys.stderr.write(f"[ERROR] tool={tool_name}: {e}\n")`
2. Return only the sanitized message in the JSON-RPC response.

---

### Phase 3: Low — Final Hardening

#### Task 3.1 — Fix VULN-09: Harden Sandbox Config Loading in `start_terminal_mcp.sh`

**Files to modify:** `sysadmin/start_terminal_mcp.sh`

**What to do:**
After the `SANDBOX_CONFIG` variable is set, add assertions to ensure it exists, is not a symlink, and is not world-writable (`chmod 644`).
