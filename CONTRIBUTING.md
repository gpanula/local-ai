# Development Standards & Contributing Guide

To maintain a clean, stable, and bisectable repository, all contributors and AI agents follow structured branch hygiene and the **[Gitmoji](https://gitmoji.dev/)** commit standard.

---

## 🌿 1. Branching & PR Workflow

### Branch Rules
* **Direct commits to `main` are prohibited.** All work must be developed on a dedicated branch and merged via Pull Request.
* A local `.githooks/pre-commit` hook guards against accidental commits on `main`.

### Branch Naming Conventions
Use descriptive prefixes for all branch names:
* `feat/<topic>` — New features, configurations, or modules (e.g., `feat/loom-ollama-routing`)
* `fix/<topic>` — Bug fixes, syntax corrections, or troubleshooting (e.g., `fix/ansible-module-idempotency`)
* `docs/<topic>` — Documentation, roadmaps, or architecture notes (e.g., `docs/moe-benchmarks`)
* `exp/<topic>` — Experiments, prototypes, or benchmark scripts (e.g., `exp/olmoe-throughput`)

---

## 📌 2. Commit Message Format

Every commit message must begin with a valid **Gitmoji** (either the Unicode emoji or shortcode format):

```text
<gitmoji> [optional scope]: <description>
```

### Examples
* `✨ (loom): add Ollama provider routing for planner and verifier roles`
* `📝 (roadmap): document Mixture of Experts exploration tracks`
* `🔧 (sysadmin): configure passwordless sudo rule for Ollama service`
* `🐛 (fincept): fix DCF sensitivity matrix calculation error`
* `🚀 (models): benchmark throughput on Quadro P4200`
* `♻️ (scripts): refactor Ansible module test harness`

---

## 🎨 3. Common Gitmojis

| Gitmoji | Shortcode | Meaning / Use Case |
| :--- | :--- | :--- |
| ✨ | `:sparkles:` | Introduce new features, modules, or tools |
| 🐛 | `:bug:` | Fix a bug or logic error |
| 📝 | `:memo:` | Add or update documentation / roadmaps / READMEs |
| 🚀 | `:rocket:` | Performance improvements, speedups, or benchmark scripts |
| 🔧 | `:wrench:` | Configuration, tooling, or environment changes |
| 🧱 | `:bricks:` | Infrastructure, hardware, or system architecture updates |
| 🧠 | `:brain:` | Model integrations, prompt engineering, or MoE experiments |
| 🔒 | `:lock:` | Security fixes, credential handling, or permission updates |
| ♻️ | `:recycle:` | Refactoring code without altering external behavior |
| 🧪 | `:test_tube:` | Adding tests, validation harnesses, or verification suites |
| 🚧 | `:construction:` | Work in progress |
| 🎨 | `:art:` | Improving structure, formatting, or UI/TUI layout |
| 🗑️ | `:wastebasket:` | Deprecating or removing code/files |
| ➕ | `:heavy_plus_sign:` | Adding new dependencies |
| ➖ | `:heavy_minus_sign:` | Removing dependencies |

---

## ⚙️ 4. Automated Verification

* **Pre-commit Hook**: Blocks direct commits on `main` (`.githooks/pre-commit`).
* **Commit-msg Hook**: Validates Gitmoji prefix format on every commit (`.githooks/commit-msg`).
* **GitHub Actions CI**: Validates all incoming PRs and commits against the Gitmoji standard (`.github/workflows/gitmoji-check.yml`).
