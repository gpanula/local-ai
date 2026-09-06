# Local AI Engineering & Autonomous Agent Workspace

A self-hosted, offline-first local AI engineering workspace running on consumer/workstation hardware (Ollama, Python 3.12, CUDA/NVIDIA Quadro P4200). This repository houses autonomous multi-agent toolchains, systems administration automation, cognitive memory and fine-tuning loops, and codebase knowledge graph navigation.

---

## 🏗️ Workspace Pillars

* **[`sysadmin/`](sysadmin/README.md)**: Autonomous multi-agent pipeline, cognitive memory (`MemoryStore`), PTY terminal execution (`terminal-mcp`), SFT/DPO dataset export, and Linux sysadmin automation.
* **[`graphify-out/`](graphify-out/) & Knowledge Graph**: Automated codebase architecture mapping, AST dependency graphs, call flows, and agent navigation powered by [Graphify](https://github.com/Graphify-Labs/graphify).
* **[`loom/`](loom/README.md)**: Multi-step task execution harness with role-based routing and verification passes.
* **[`moe/`](moe/README.md)**: Sparse Mixture-of-Experts (MoE) routing, parameter offloading, and latency benchmarking.
* **[`fincept/`](fincept/README.md)**: Quantitative financial analytics terminal auditing and validation models.

---

## 🗺️ Codebase Knowledge Graph (Graphify)

We use **[Graphify](https://github.com/Graphify-Labs/graphify)** to construct a deterministic, persistent knowledge graph of the entire repository. This allows developers and AI agents (Antigravity, Claude Code, Ollama agents) to query module dependencies, shortest paths, and architectural call-flows without re-reading raw files or relying on lossy vector searches.

### Key Outputs (`graphify-out/`)
* **`graph.html`**: Interactive 2D/3D browser visualization of all modules, classes, and call edges.
* **`GRAPH_TREE.html`**: Collapsible D3 hierarchy of the project layout.
* **`local-ai-callflow.html`**: Mermaid architecture diagrams and cross-component call tables.
* **`GRAPH_REPORT.md`**: Summary of central community hubs, god nodes, and cross-cutting dependencies.
* **`obsidian/`**: 900+ Markdown notes formatted as an Obsidian wiki vault.
* **`wiki/index.md`**: Wikipedia-style articles indexed for AI agent navigation.

---

## 🚀 Setting Up Graphify

Per our project standards in [`AGENTS.md`](AGENTS.md), all tooling is isolated inside the project virtual environment (`sysadmin/venv`) without relying on ambient `$PATH` or requiring external package managers like `uv`.

### 1. Automated Installation
Run the dedicated setup script:

```bash
./sysadmin/setup_graphify.sh
```

This script:
1. Resolves `sysadmin/venv` (creates it with Python 3.12 if missing).
2. Upgrades `pip`, `setuptools`, and `wheel`.
3. Installs `graphifyy` alongside `networkx`, `numpy`, and 25+ `tree-sitter` language grammars.
4. Validates the binary executable at `sysadmin/venv/bin/graphify` and tests module importability.

### 2. Shell Aliases
To enable convenient CLI shortcuts, source the project aliases:

```bash
source sysadmin/shell_aliases.sh

# Now available:
localai-graphify --help
```

### 3. Mapping the Codebase
Extract AST relationships across the repository (local, instant, zero API cost):

```bash
# Headless AST extraction on code files
./sysadmin/venv/bin/graphify extract . --code-only

# Generate visual HTML maps and collapsible trees
./sysadmin/venv/bin/graphify export html
./sysadmin/venv/bin/graphify tree
./sysadmin/venv/bin/graphify export callflow-html

# Generate Obsidian vault & Agent Wiki
./sysadmin/venv/bin/graphify export obsidian
./sysadmin/venv/bin/graphify export wiki

# Cluster and produce GRAPH_REPORT.md
./sysadmin/venv/bin/graphify cluster-only .
```

### 4. Querying the Knowledge Graph
```bash
# Query specific symbols, concepts, or lessons
./sysadmin/venv/bin/graphify query "extract_lesson"

# Find the shortest relationship path between two files/modules
./sysadmin/venv/bin/graphify path "pipeline.py" "hardware.py"

# Open visual representations in your default browser
xdg-open graphify-out/graph.html
xdg-open graphify-out/GRAPH_TREE.html
xdg-open graphify-out/local-ai-callflow.html
```

### 5. Keeping the Graph Fresh
After adding or modifying code, run an incremental AST update:

```bash
./sysadmin/venv/bin/graphify update .
```

---

## 🤖 Agent Integration

Graphify rules and workflows are installed in `.agents/`:
* **Rule**: [`.agents/rules/graphify.md`](.agents/rules/graphify.md) instructs AI agents to query `graphify-out/graph.json` or `graphify-out/wiki/index.md` before answering architecture questions.
* **Workflow / Skill**: [`.agents/workflows/graphify.md`](.agents/workflows/graphify.md) and [`.agents/skills/graphify/SKILL.md`](.agents/skills/graphify/SKILL.md) allow running `/graphify` in supported agent environments.
