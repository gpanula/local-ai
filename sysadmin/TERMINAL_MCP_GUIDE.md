# Terminal MCP Integration & Sandbox Guide (`gpanula/terminal-mcp`)

**Reference**: [gpanula/terminal-mcp on GitHub](https://github.com/gpanula/terminal-mcp)

`terminal-mcp` exposes an interactive VT100/ANSI pseudo-terminal (PTY) via the Model Context Protocol (MCP). It allows orchestrators (Antigravity IDE) and local models (Ollama) to execute shell operations while giving the human developer live visibility and sandbox boundaries.

---

## 🧠 Architecture: Host vs. Model Inference

It is important to understand the division of responsibilities:

* **Antigravity IDE (The MCP Host / Client)**:
  * Manages connections to MCP servers via `~/.gemini/config/mcp_config.json`.
  * Discovers tools from `local-ollama`, `github`, and `terminal`.
  * Bridges high-level requests between the human, Ollama models, and the terminal PTY.
* **Ollama (The Inference Server)**:
  * Serves local LLMs (`qwen3:8b`, `qwen2.5-coder:7b`, etc.) over HTTP at `http://127.0.0.1:11434`.
  * Generates plans, code, and structured tool calls when prompted by the host.

```
┌────────────────────────────────────────────────────────┐
│               MCP Host (The Orchestrator)              │
│       (Antigravity IDE / Local AI Overseer)            │
└──────────────┬──────────────────────────┬──────────────┘
               │ 1. Discovers tools       │ 2. Sends prompt + tools
               ▼                          ▼
   ┌───────────────────────┐   ┌─────────────────────────┐
   │ Terminal MCP Server   │   │     Ollama Service      │
   │ (gpanula/terminal-mcp)│   │  (qwen3:8b, qwen2.5)    │
   └───────────┬───────────┘   └──────────┬──────────────┘
               │                          │ 3. Model decides to call:
               │                          │    "type: ansible --version"
               │ 4. Host executes tool    │
               ◄──────────────────────────┘
```

---

## 🛡️ Sandbox Configuration (`sysadmin/terminal_sandbox.json`)

To prevent accidental modifications outside the workspace and protect sensitive credentials, `terminal-mcp` can be launched in **Sandbox Mode**.

### Prerequisites & Dependencies
When running in `--sandbox` mode, `terminal-mcp` requires Linux sandboxing and inspection tools:
* **Bubblewrap (`bwrap`)**: Unprivileged sandboxing engine.
* **Socat (`socat`)**: Socket relay and IPC communication.
* **Ripgrep (`rg`)**: Fast regex and filesystem inspection.

**Installation**:
* **Debian / Ubuntu / Linux Mint**:
  ```bash
  sudo apt install -y bubblewrap socat ripgrep
  ```
* **Arch Linux**:
  ```bash
  sudo pacman -S bubblewrap socat ripgrep
  ```
* **macOS (Homebrew)**:
  ```bash
  brew install ripgrep
  ```

### 1. Filesystem Restrictions
* **Read/Write**: Dynamically scoped to the repository workspace (resolving physical and symlinked paths), `/tmp`, and user development caches (`~/.cache`, `~/.local`, `~/.npm`, `~/.direnv`).
* **Read-Only**: System binaries and shared libraries (`/usr`, `/bin`, `/lib`, `/etc/ssl`).
* **Blocked / Denied**: Sensitive credential paths (`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/gh`, `/root`).

### 2. Command Whitelist
Only safe, necessary development and sysadmin commands are permitted:
* **Version Control**: `git`, `gh`
* **Python & Environments**: `python3`, `python3.12`, `python3.10`, `python`, `pip`, `pip3`, `direnv`
* **Ansible Suite**: `ansible`, `ansible-core`, `ansible-playbook`, `ansible-lint`, `ansible-galaxy`, `ansible-doc`
* **Hardware & Local AI**: `nvidia-smi`, `ollama`
* **Network / Download**: `curl`, `wget`
* **Core Inspection & File Tools**: `ls`, `cat`, `head`, `tail`, `grep`, `find`, `sed`, `awk`, `mkdir`, `rm`, `cp`, `mv`, `chmod`, `touch`, `tree`, `diff`, `echo`, `which`, `pwd`, `env`

---

## ⚙️ Antigravity IDE Configuration (`mcp_config.json`)

In `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "local-ollama": {
      "command": "python3",
      "args": [
        "${HOME}/Projects/local-ai/sysadmin/mcp_ollama/server.py"
      ],
      "env": {
        "OLLAMA_HOST": "http://127.0.0.1:11434"
      }
    },
    "github": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "<BOT_TOKEN>"
      }
    },
    "terminal": {
      "command": "npx",
      "args": [
        "-y",
        "github:gpanula/terminal-mcp",
        "--record",
        "always",
        "--record-dir",
        "~/Projects/local-ai/recordings",
        "--inactivity-timeout",
        "900",
        "--max-duration",
        "14400"
      ]
    }
  }
}
```

---

## 🎥 Automatic Session Recording

Terminal MCP is configured to **always record** all sessions:
* **Record Mode**: `always` (records every session)
* **Storage Path (`--record-dir`)**: `~/Projects/local-ai/recordings/` (git-ignored)
* **Inactivity Timeout**: `900s` (15 minutes of silence before stopping idle recording)
* **Max Duration**: `14400s` (4 hours maximum per recording session)
* **Format & Playback Tool**: Recordings are saved in `.cast` format and played back using **[asciinema](https://asciinema.org/)**:
  * **Linux Install**: `sudo apt install -y asciinema`
  * **macOS Install**: `brew install asciinema`
  * **Playback**: `asciinema play ~/Projects/local-ai/recordings/<session-id>.cast`

---

## 🚀 Quick Launch Script & Shell Aliases

### 1. Direct Script Launch
Run the launcher script from anywhere in the workspace:
```bash
./sysadmin/start_terminal_mcp.sh
```

### 2. Cross-Platform Shell Aliases (`sysadmin/shell_aliases.sh`)
To enable handy terminal commands across your shell sessions on **Linux or macOS**:

#### For Zsh (macOS Default & Linux Zsh):
```zsh
# Source temporarily in your current session:
source ~/Projects/local-ai/sysadmin/shell_aliases.sh

# Or add permanently to ~/.zshrc:
echo 'source ~/Projects/local-ai/sysadmin/shell_aliases.sh' >> ~/.zshrc
```

#### For Bash (Linux & macOS Bash):
```bash
# Source temporarily in your current session:
source ~/Projects/local-ai/sysadmin/shell_aliases.sh

# Or add permanently to ~/.bashrc:
echo 'source ~/Projects/local-ai/sysadmin/shell_aliases.sh' >> ~/.bashrc
```

**Available Aliases & Commands**:
* `localai-term` — Launches sandboxed `terminal-mcp` with automatic recording.
* `localai-term-raw` — Launches unrestricted `terminal-mcp` with automatic recording.
* `localai-recordings` — Lists all `.cast` recording files in `recordings/`.
* `localai-replay-latest` — Plays back the most recent session using `asciinema`.
* `localai-replay <file>` — Plays back a specific recording file.
* `localai-models` — Lists installed local Ollama models and quantization tags.
* `localai-gpu` — Cross-platform hardware monitor (`nvidia-smi` on Linux, Metal / Displays on macOS).
* `localai-mcp-config` — Views current Antigravity MCP server definitions.
* `localai-lessons` — Interactively reviews staged pending lessons (Keep / Modify / Discard / Skip).
* `localai-audit` — Clusters related lessons and promotes recurring patterns to `SYSTEM_RULES.md`.
* `localai-wiki` — Compiles the human-readable memory-health wiki (`index.md`, `dashboard.md`, `log.md`).

---


## ⚠️ Known Gotchas & Troubleshooting

### 1. Network Sandboxing & Proxy Allowlist (`X-Proxy-Error: blocked-by-allowlist`)
* **Symptom**: Outbound network requests (`curl`, `pip`, `wget`) inside the sandboxed terminal fail with `HTTP 403 Forbidden` (`X-Proxy-Error: blocked-by-allowlist`), and direct DNS lookups fail with `socket(): Operation not permitted` or `connection refused to 127.0.0.53#53`.
* **Root Cause**:
  1. Bubblewrap isolates the network namespace (`bwrap --unshare-net`) and seccomp blocks raw UDP/DNS sockets from within the container.
  2. All external web traffic is funneled through `@anthropic-ai/sandbox-runtime`'s local proxy on `localhost:3128`.
  3. **Gotcha**: Setting `"network": { "mode": "all" }` in `terminal_sandbox.json` fails to forward domain permissions to the proxy on Linux, resulting in the proxy defaulting to an empty allowlist.
* **Resolution**:
  Explicitly configure `network.mode` as `"allowlist"` and provide the `allowedDomains` array in `sysadmin/terminal_sandbox.json`:
  ```json
  "network": {
    "mode": "allowlist",
    "allowedDomains": [
      "github.com",
      "api.github.com",
      "raw.githubusercontent.com",
      "objects.githubusercontent.com",
      "pypi.org",
      "pypi.python.org",
      "files.pythonhosted.org",
      "bootstrap.pypa.io"
    ]
  }
  ```

---

## 📌 Upstream Contribution Roadmap & To-Do List

* [ ] **PR to `gpanula/terminal-mcp` / Upstream (`elleryfamilia/terminal-mcp`)**:
  * **Repository**: [https://github.com/gpanula/terminal-mcp](https://github.com/gpanula/terminal-mcp) (fork of `elleryfamilia/terminal-mcp`)
  * **Title**: `fix(sandbox): properly forward unrestricted mode: "all" to sandbox-runtime proxy on Linux`
  * **Details**: Ensure that when `network.mode: "all"` is configured in `terminal-mcp-sandbox.json`, the sandbox proxy disables domain filtering or passes a wildcard `*` allowlist to `@anthropic-ai/sandbox-runtime` rather than defaulting to blocking all outbound traffic.

