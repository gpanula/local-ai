# Lessons Learned — Episodic Memory Store

> **Purpose**: Git-canonical store of approved episodic lessons, promoted from the
> pending review queue via the `review-lessons` CLI. Each lesson is a YAML-frontmatter
> block followed by the rule text.
>
> **Format** (see `ai_memory_summary.md` §Canonical File Formats):
>
> ```markdown
> ---
> id: lesson-YYYYMMDD-NN
> category: <category>
> keywords: [kw1, kw2, kw3]
> created: YYYY-MM-DD
> source_task: <path/to/prompt.md>
> ---
> **Rule**: <rule text>
> ```

<!-- Lessons are appended below this line by the review-lessons promotion flow. -->

---
id: lesson-20260830-01
category: Defensive Bash Scripting
keywords: [bash, bash scripting, binary existence assertions, cleanup trap, conditional success message, defensive programming, deterministic resolution, diagnostic trap, dynamic resolution, environment variables, err handling, error handling, exit codes, hardcoded paths, quoting, required output, resources management, script structure, self-creation, standalone script, success message, venv_dir resolution, write_file]
created: 2026-08-30
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Avoid using write_file to create the script; directly embed the script content to ensure it's standalone and compliant with defensive standards. Verify file existence with [ -x ...] and resolve VENV_DIR explicitly as required by universal system rules.

---
id: lesson-20260830-03
category: Binary Isolation
keywords: [ansible, ansible sandbox isolation, bash, bash scripting, binary assertions, binary existence check, binary isolation, code quality, functional test suites, linters, pre-execution assertions, pre-flight linters, python, python syntax validation, virtual environment, yaml, yaml parsing]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: When developing a standalone, portable Bash verification script for code quality and pre-flight linters toolchain, ensure that the script resolves the virtual environment path deterministically and safely. Also, explicitly invoke all required binaries from the virtual environment's bin directory to maintain binary isolation. Before executing functional test suites, assert that all required binaries exist and are executable.

---
id: lesson-20260830-13
category: ShellCheck
keywords: [codes, linter, loop, pre-flight, sc1003, sc1009, sc1050, sc1064, sc1065, sc1072, sc1073, sc1078, sc1079, sc2034, shellcheck, stuck, styleguidelines, variablenaming]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: Ensure that all ShellCheck linter findings (SC1003, SC1009, SC1050, SC1064, SC1065, SC1072, SC1073, SC1078, SC1079) are addressed in the `sysadmin/prompts/verify_code_quality_toolchain.sh` script before deployment.

---
id: lesson-20260830-14
category: Docker Orchestration
keywords: [docker, compose]
created: 2026-08-30
source_task: 
---
**Rule**: Always check docker daemon health before running compose.
