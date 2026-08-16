# Commit Message Style Guide & Gitmoji Standards

To ensure a clean, readable, and structured Git history, all commit messages in this repository must begin with a **[Gitmoji](https://gitmoji.dev/)** (either the Unicode emoji or shortcode format).

---

## 📌 Commit Message Format

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

## 🎨 Common Gitmojis for Local AI & Infrastructure

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

## ⚙️ Automated Enforcement

Commit messages are validated automatically:
1. **CI Pipeline**: [`.github/workflows/gitmoji-check.yml`](file:///.github/workflows/gitmoji-check.yml) validates all incoming commits on pushes and pull requests.
2. **Local Git Hook**: Developers and AI agents can enable the local commit hook:
   ```bash
   git config core.hooksPath .githooks
   ```
