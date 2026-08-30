"""Multi-agent pipeline commands: build-and-run, pipeline-run.

The ``pipeline-run`` orchestration loop is extracted into ``revision_loop()``
and pure helper methods (``_extract_strategy``, ``_extract_stats``,
``_extract_tool_calls``) so the logic is independently unit-testable with a
mocked transport layer.
"""

import json
import logging
import os
import re

from mcp_core import transport
from mcp_core.attribution import attribute_lessons
from mcp_core.embeddings import get_embedding
from mcp_core.extraction import (
    extract_lesson_from_critique,
    extract_lesson_from_stuck_loop,
)
from mcp_core.injection import format_lessons_for_prompt
from mcp_core.memory import MemoryStore
from mcp_core.sanitize import sanitize_script_code
from mcp_core.trajectories import record_trajectory
from mcp_core.workspace import WORKSPACE_ROOT, validate_workspace_path
from mcp_cli.base import BaseCommand, command

logger = logging.getLogger(__name__)


@command
class BuildAndRunCommand(BaseCommand):
    name = "build-and-run"
    help = "Have Ollama generate code from a prompt file and execute it live in terminal-mcp"

    def register_args(self, parser):
        parser.add_argument("file", help="Path to prompt markdown/text file")
        parser.add_argument("--model", default="qwen3:8b", help="Model to use")
        parser.add_argument("--type", default="sysadmin", help="Task category")
        parser.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")

    def run(self, args):
        valid_path = validate_workspace_path(args.file, "prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            task_content = f.read()
        print(f"🤖 [Ollama {args.model}] Processing prompt from {args.file}...")
        plan = transport.call_mcp("ollama_task_agent", {
            "task": task_content,
            "model": args.model,
            "task_type": args.type,
        })
        print(f"✅ [Ollama {args.model}] Strategy & Commands Generated. Extracting execution block...")
        code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", plan)
        if not code_blocks:
            print("❌ No executable code blocks found in Ollama output. Raw plan:\n", plan)
        else:
            exec_cmd = sanitize_script_code(max(code_blocks, key=len))
            # Send status banner into terminal-mcp interactive window
            banner_cmd = f"echo '🤖 [Ollama {args.model}] Executing prompt: {args.file}'; {exec_cmd}"
            print(f"🚀 [Ollama {args.model}] Executing build & run commands live in terminal-mcp...")
            report = transport.call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Build & Execute task from {args.file}",
                "model": args.model,
                "timeout": args.timeout,
            })
            print(report)


@command
class PipelineRunCommand(BaseCommand):
    name = "pipeline-run"
    help = "Multi-agent pipeline: Author (qwen2.5-coder) -> Lint (Shellcheck) -> Review (qwen3) -> Live Execution"

    def register_args(self, parser):
        parser.add_argument("file", help="Path to prompt markdown/text file")
        parser.add_argument("--author", default="qwen2.5-coder:7b", help="Model to synthesize code (default: qwen2.5-coder:7b)")
        parser.add_argument("--reviewer", default="qwen3:8b", help="Model to review & verify code (default: qwen3:8b)")
        parser.add_argument("--no-lint", action="store_true", help="Skip pre-flight linting step")
        parser.add_argument("--bootstrap", action="store_true", help="Flag task as bootstrap (tolerates missing host tools before installation)")
        parser.add_argument("--max-retries", type=int, default=2, help="Max revision cycles if reviewer rejects (default: 2)")
        parser.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")
        parser.add_argument("--dry-run", action="store_true", help="Stop after review without executing")

    def run(self, args):
        valid_path = validate_workspace_path(args.file, "prompt file")
        with open(valid_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()

        result = self.revision_loop(prompt_content, args)

        # Phase 5: record retrieval + attribution telemetry (never blocks).
        self._apply_telemetry(result)

        # Stage a lesson in the pending queue if rework occurred (never blocks).
        self._stage_lesson_if_rework(result, prompt_content, args)

        # Phase 7.01: record a trajectory for multi-iteration runs (never blocks).
        self._record_trajectory_if_rework(result, prompt_content, args)

        if not result["approved"]:
            if result["abort_reason"]:
                transport.send_terminal_mcp(f"❌ [Pipeline Aborted] {result['abort_reason']}.")
            else:
                transport.send_terminal_mcp(f"❌ [Pipeline Failed] Maximum iterations ({args.max_retries}) reached without approval.")
            return

        if args.dry_run:
            transport.send_terminal_mcp("🏁 [Dry-Run] Pipeline completed verification. Skipping execution.")
            return

        self.execute(result, args)

    # --- testable pipeline internals ---

    def revision_loop(self, prompt_content, args):
        """Author → Lint → Review cycle.

        Returns a dict with keys: ``approved``, ``final_code_block``,
        ``abort_reason``, ``write_file_call``, ``iterations``.
        """
        current_prompt = prompt_content
        approved = False
        iteration = 0
        max_attempts = args.max_retries
        final_code_block = ""
        abort_reason = ""
        linter_history = []
        reviewer_history = []
        write_file_call = None
        injected_lessons = []
        injected_lesson_dicts = []
        # Phase 7.01: accumulate each iteration's script version (oldest->newest)
        # so trajectories can capture rejected/approved pairs.
        script_versions = []

        # Phase 6.05: prepend universal system rules to the Author prompt.
        # Never blocks the pipeline on failure (missing/empty file = no-op).
        rules_section = ""
        try:
            rules_section = self._load_system_rules()
            if rules_section:
                current_prompt = f"{rules_section}\n\n{current_prompt}"
        except Exception as exc:  # noqa: BLE001 - rules load must never block
            logger.warning("System rules load skipped: %s", exc)

        # Phase 4.04: enrich the Author prompt with relevant lessons from memory
        # before the first iteration. Never blocks the pipeline on failure.
        try:
            current_prompt, injected_lesson_dicts = self._inject_lessons(
                current_prompt, args
            )
            injected_lessons = [
                lesson.get("id") for lesson in injected_lesson_dicts if lesson.get("id")
            ]
        except Exception as exc:  # noqa: BLE001 - injection must never block
            logger.warning("Lesson injection skipped: %s", exc)

        while iteration < max_attempts and not approved:
            iteration += 1
            transport.send_terminal_mcp(
                f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 [Pipeline Iteration {iteration}/{max_attempts}] Authoring with `{args.author}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

            author_response = transport.call_mcp("ollama_task_agent", {
                "task": current_prompt,
                "model": args.author,
                "task_type": "coding",
            })

            # Extract and format Author Analysis & Strategy
            strategy_text = self._extract_strategy(author_response)
            if strategy_text:
                transport.send_terminal_mcp("─── [AUTHOR ANALYSIS & STRATEGY] ──────────────────────────")
                transport.send_terminal_mcp(strategy_text)
                author_stats = self._extract_stats(author_response)
                if author_stats:
                    transport.send_terminal_mcp(f"📊 {author_stats}")
                transport.send_terminal_mcp("──────────────────────────────────────────────────────────")

            tool_calls = self._extract_tool_calls(author_response)
            write_file_call = next(
                (tc for tc in tool_calls if tc.get("name") == "write_file" and tc.get("arguments", {}).get("content")),
                None,
            )

            final_code_block = ""
            if write_file_call:
                wf_args = write_file_call.get("arguments", {})
                target_path = wf_args.get("path", "")
                target_content = wf_args.get("content", "")
                is_exec = wf_args.get("make_executable", False)
                transport.send_terminal_mcp(f"🛠️ [Native Tool Call] write_file -> `{target_path}` ({len(target_content)} bytes, exec: {is_exec})")
                final_code_block = sanitize_script_code(target_content)
            else:
                code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", author_response)
                if not code_blocks:
                    transport.send_terminal_mcp(f"⚠️ [Format Error] No executable bash code block or write_file tool call extracted. Retrying `{args.author}`...")
                    current_prompt = (
                        f"{prompt_content}\n\n"
                        f"### Formatting Error:\nYour previous response did not contain a valid ```bash ... ``` code block. "
                        f"Please provide the complete synthesized Bash script inside a ```bash code block."
                    )
                    continue
                final_code_block = sanitize_script_code(max(code_blocks, key=len))
                preview_first_line = final_code_block.splitlines()[0] if final_code_block.splitlines() else ""
                transport.send_terminal_mcp(f"📝 Synthesized Script ({len(final_code_block)} bytes) - {preview_first_line}")

            # Phase 7.01: record this iteration's script version for trajectories.
            if final_code_block:
                script_versions.append(final_code_block)

            # Step 2: Pre-Flight Linting
            linter_output = "No linter run."
            linter_failed = False
            if not args.no_lint:
                raw_linter = transport.call_mcp("shellcheck_inspect", {"script": final_code_block})
                if "binary not found" in raw_linter:
                    if args.bootstrap:
                        linter_output = "ℹ️ Pre-flight shellcheck skipped (bootstrap in progress: shellcheck is not yet installed on host and will be installed by this script)."
                        transport.send_terminal_mcp("ℹ️ [Pre-Flight Linter] Shellcheck skipped (bootstrap task in progress)")
                    else:
                        linter_output = raw_linter
                        transport.send_terminal_mcp("⚠️ [Pre-Flight Linter] Host shellcheck binary not found.")
                else:
                    linter_output = raw_linter
                    first_line = linter_output.splitlines()[0] if linter_output.splitlines() else ''
                    transport.send_terminal_mcp(f"🔍 [Pre-Flight Linter] Output: {first_line}")
                    if "ShellCheck Analysis Findings (exit 1)" in raw_linter or "exit 1" in raw_linter:
                        linter_failed = True

            # Auto-reject on pre-flight linter failure (unless explicitly flagged as bootstrap task)
            if linter_failed:
                current_prompt, abort_reason = self._handle_linter_failure(
                    prompt_content, final_code_block, raw_linter, linter_history,
                    iteration, max_attempts, current_prompt, abort_reason,
                )
                if abort_reason:
                    break
                continue
            else:
                linter_history.append(None)

            # Step 3: Reviewer Evaluation
            review_verdict = self._review(
                args, prompt_content, final_code_block, linter_output, rules_section
            )
            approved, abort_reason, current_prompt, reviewer_history = self._handle_review(
                args, review_verdict, prompt_content, final_code_block,
                reviewer_history, iteration, max_attempts, current_prompt, approved, abort_reason,
            )
            if abort_reason:
                break

        # Capture the last non-empty reviewer critique for lesson extraction.
        last_critique = ""
        for sig in reversed(reviewer_history):
            if sig:
                if isinstance(sig, (list, tuple)):
                    last_critique = "\n".join(str(p) for p in sig)
                else:
                    last_critique = str(sig)
                break

        return {
            "approved": approved,
            "final_code_block": final_code_block,
            "abort_reason": abort_reason,
            "write_file_call": write_file_call,
            "iterations": iteration,
            "reviewer_history": reviewer_history,
            "last_critique": last_critique,
            "rework_occurred": iteration > 1,
            "lesson_type": None,
            "injected_lessons": injected_lessons,
            "injected_lesson_dicts": injected_lesson_dicts,
            "script_versions": script_versions,
        }

    # Path to the universal system rules store (relative to workspace root).
    SYSTEM_RULES_PATH = os.path.join(WORKSPACE_ROOT, "sysadmin", "prompts", "SYSTEM_RULES.md")

    @staticmethod
    def _load_system_rules(rules_path: str | None = None) -> str:
        """Read ``SYSTEM_RULES.md`` and render it as a ``### Universal System Rules`` section.

        Returns an empty string when the file is missing or empty (no-op, no
        regression). The rules text is wrapped in a markdown section header so it
        can be prepended to the Author prompt or appended to the Reviewer prompt.
        """
        path = rules_path or PipelineRunCommand.SYSTEM_RULES_PATH
        try:
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return ""
            return f"### Universal System Rules\n\n{content}"
        except OSError as exc:  # noqa: BLE001 - rules load must never block
            logger.warning("Could not read system rules at %s: %s", path, exc)
            return ""

    # Stop-words filtered out of the prompt-derived keyword query.
    _INJECTION_STOPWORDS = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "that", "this", "is", "are", "was", "were", "be", "been", "it", "as",
        "at", "by", "from", "your", "you", "please", "write", "using", "use",
        "script", "task", "file", "create", "make", "ensure", "must", "should",
    }

    def _inject_lessons(self, prompt_content: str, args) -> tuple:
        """Query memory for lessons relevant to the prompt and prepend them.

        Extracts significant keywords from the prompt and runs an FTS5 OR query
        (a strict phrase match would miss single-term relevance). Returns
        ``(enriched_prompt, injected_lessons)`` where ``injected_lessons`` is a
        list of lesson dicts (used for attribution). When no lessons match, the
        prompt is returned unchanged with an empty list (no banner).
        """
        keywords = self._build_injection_keywords(prompt_content)
        if not keywords:
            return prompt_content, []

        try:
            with MemoryStore() as store:
                lessons = self._search_by_keywords(store, keywords, top_k=3)
        except Exception as exc:  # noqa: BLE001 - injection must never block
            logger.warning("Lesson search failed: %s", exc)
            return prompt_content, []

        if not lessons:
            return prompt_content, []

        injected_section = format_lessons_for_prompt(lessons)
        enriched = f"{injected_section}\n\n{prompt_content}"
        transport.send_terminal_mcp(
            f"📚 Injected {len(lessons)} relevant lessons from memory"
        )
        return enriched, lessons

    @staticmethod
    def _build_injection_keywords(prompt_content: str) -> list:
        """Derive the significant keyword tokens from the prompt."""
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", prompt_content.lower())
        seen = []
        for tok in tokens:
            if tok in PipelineRunCommand._INJECTION_STOPWORDS or tok in seen:
                continue
            seen.append(tok)
        return seen

    @staticmethod
    def _search_by_keywords(store, keywords: list, top_k: int = 3) -> list:
        """Search lessons per-keyword and merge results, ranked by match count.

        ``search_lessons`` treats its query as a strict phrase, so a full-sentence
        prompt would rarely match. Searching each significant keyword individually
        and merging (deduped, ranked by how many keywords matched) recovers
        single-term relevance for injection.
        """
        scored: dict = {}
        for kw in keywords:
            for lesson in store.search_lessons(kw, top_k=top_k * 3):
                lesson_id = lesson.get("id")
                if lesson_id is None:
                    continue
                entry = scored.setdefault(lesson_id, {"lesson": lesson, "hits": 0})
                entry["hits"] += 1

        ranked = sorted(scored.values(), key=lambda e: e["hits"], reverse=True)
        return [e["lesson"] for e in ranked[:top_k]]

    def _apply_telemetry(self, result) -> None:
        """Record retrieval + attribution telemetry for injected lessons.

        Phase 5: increments ``retrieval_count`` for every injected lesson, then
        attributes each lesson (credited / blamed / innocent) based on the
        pipeline outcome and reviewer critique, updating the corresponding
        counter. Failures are logged but never block the pipeline.
        """
        injected_ids = result.get("injected_lessons", [])
        injected_dicts = result.get("injected_lesson_dicts", [])
        if not injected_ids:
            return

        try:
            with MemoryStore() as store:
                store.increment_retrieval_count(injected_ids)

                attribution = attribute_lessons(
                    injected_dicts,
                    result,
                    result.get("last_critique", ""),
                )
                for lesson_id, verdict in attribution.items():
                    if verdict == "credited":
                        store.update_telemetry(lesson_id, "prevented_rework_count")
                    elif verdict == "blamed":
                        store.update_telemetry(lesson_id, "ineffective_count")
                    # "innocent" -> no counter change.
        except Exception as exc:  # noqa: BLE001 - telemetry must never block
            logger.warning("Telemetry update failed: %s", exc)

    def _stage_lesson_if_rework(self, result, prompt_content, args) -> None:
        """Stage a lesson in the pending queue after a rework run.

        Exit-state mapping:
          - iterations == 1 AND approved  -> no-op
          - iterations > 1 AND approved   -> solved_pattern (LLM extraction)
          - iterations == max AND not approved AND no abort_reason -> hard_failure (LLM extraction)
          - abort_reason set              -> intractable_pattern (stuck-loop shortcut, no LLM)

        Staging failures are logged but never block the pipeline.
        """
        iterations = result.get("iterations", 0)
        approved = result.get("approved", False)
        abort_reason = result.get("abort_reason", "")
        task_file = getattr(args, "file", "")

        # Determine the exit state and lesson type.
        if abort_reason:
            lesson_type = "intractable_pattern"
        elif approved and iterations > 1:
            lesson_type = "solved_pattern"
        elif not approved and iterations >= args.max_retries:
            lesson_type = "hard_failure"
        else:
            # Pass on iteration 1 (or any other no-op state).
            result["lesson_type"] = None
            return

        result["lesson_type"] = lesson_type

        try:
            if lesson_type == "intractable_pattern":
                lesson = extract_lesson_from_stuck_loop(
                    result.get("reviewer_history", []),
                    abort_reason,
                    task_file,
                )
            else:
                lesson = extract_lesson_from_critique(
                    result.get("last_critique", ""),
                    task_file,
                    prompt_content,
                    args.reviewer,
                    lesson_type=lesson_type,
                    outcome="approved" if approved else "failed",
                )

            with MemoryStore() as store:
                store.stage_pending_lesson(lesson)
            transport.send_terminal_mcp(
                f"💡 1 new lesson staged in pending queue (type: {lesson_type})"
            )
        except Exception as exc:  # noqa: BLE001 - staging must never block the pipeline
            logger.warning("Failed to stage lesson (type=%s): %s", lesson_type, exc)

    def _record_trajectory_if_rework(self, result, prompt_content, args) -> None:
        """Record a trajectory entry for multi-iteration runs (Phase 7.01).

        Only records when ``iterations > 1`` (rework occurred). Iteration-1
        passes produce no trajectory. Failures are logged but never block the
        pipeline.
        """
        iterations = result.get("iterations", 0)
        if iterations <= 1:
            return
        try:
            record_trajectory(
                result,
                prompt_content,
                task_file=getattr(args, "file", ""),
            )
        except Exception as exc:  # noqa: BLE001 - trajectory must never block
            logger.warning("Failed to record trajectory: %s", exc)

    @staticmethod
    def _extract_strategy(author_response: str) -> str:
        """Extract the Author Analysis & Strategy preamble from the response."""
        strategy_text = ""
        if "### 1. Analysis & Strategy" in author_response or "### Analysis & Strategy" in author_response:
            parts = re.split(r"###\s*(?:2\.\s*)?Implementation", author_response, flags=re.IGNORECASE)
            strategy_text = parts[0].strip()
        elif "```" in author_response:
            strategy_text = author_response.split("```")[0].strip()
        else:
            strategy_text = author_response.strip()
        return strategy_text

    @staticmethod
    def _extract_stats(author_response: str) -> str:
        """Extract the '*Generated by `model`: N tokens in Xs (Y t/s)*' footer."""
        match = re.search(r"(\*Generated by `[^`]+`: \d+ tokens in [\d\.]+s \([\d\.]+ t/s\)\*)", author_response)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_tool_calls(author_response: str):
        """Extract structured tool calls (fenced code blocks or raw JSON lines)."""
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

        # Also inspect raw lines for un-fenced JSON tool calls
        for line in author_response.splitlines():
            line_str = line.strip()
            if line_str.startswith("{") and ("write_file" in line_str or "read_file" in line_str):
                try:
                    tc_obj = json.loads(line_str)
                    if isinstance(tc_obj, dict) and "name" in tc_obj:
                        tool_calls.append(tc_obj)
                except json.JSONDecodeError:
                    pass
        return tool_calls

    @staticmethod
    def _handle_linter_failure(prompt_content, final_code_block, raw_linter, linter_history,
                               iteration, max_attempts, current_prompt, abort_reason):
        """Process ShellCheck auto-reject: extract findings, detect stuck loops, build retry prompt."""
        sc_codes = re.findall(r"(SC\d{4})", raw_linter)
        finding_lines = []
        for line in raw_linter.splitlines():
            cleaned = line.strip()
            if cleaned.startswith("In - line") or "SC" in cleaned or cleaned.startswith("Did you mean:"):
                finding_lines.append(cleaned)

        sc_summary = f"SC codes: {', '.join(sorted(set(sc_codes)))}" if sc_codes else "Syntax/style issues"

        # Consecutive repeat counting for identical linter signatures
        current_sig = tuple(sorted(sc_codes)) if sc_codes else tuple(finding_lines[:2])
        consecutive_linter_repeats = 1
        for past_sig in reversed(linter_history):
            if past_sig == current_sig and current_sig is not None:
                consecutive_linter_repeats += 1
            else:
                break
        linter_history.append(current_sig)

        transport.send_terminal_mcp(f"⚠️ [Pre-Flight Linter Auto-Reject] ShellCheck findings ({sc_summary}) [Repeat: {consecutive_linter_repeats}/3]")
        for fl in finding_lines[:4]:
            transport.send_terminal_mcp(f"   ↳ {fl}")

        print(f"\n[Pre-Flight Linter Findings]:\n{raw_linter}\n")

        if consecutive_linter_repeats >= 3:
            abort_reason = f"Stuck in pre-flight linter loop ({sc_summary}) on iteration {iteration}/{max_attempts}"
            transport.send_terminal_mcp(f"🛑 [Stuck Loop Detected] Author repeated identical ShellCheck findings ({sc_summary}) for 3 consecutive iterations. Aborting pipeline early.")
            print(f"\n[Stuck Loop Abort]: Repeating findings {current_sig} (3 consecutive times)\n")
            return current_prompt, abort_reason

        current_prompt = (
            f"{prompt_content}\n\n"
            f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
            f"### Pre-Flight Linter (ShellCheck) Findings:\n{raw_linter}\n\n"
            f"Please rewrite the script, fixing ALL ShellCheck findings (e.g., properly quote variables, avoid SC2016 single quote expansion errors, and adhere to defensive standards)."
        )
        return current_prompt, abort_reason

    @staticmethod
    def _build_review_prompt(args, prompt_content, final_code_block, linter_output, rules_section: str = "") -> str:
        """Assemble the reviewer verification prompt for the script under review.

        ``rules_section`` (optional) is the ``### Universal System Rules`` block
        from Phase 6.05, appended as an additional verification reference. When
        empty, the prompt is unchanged (no regression).
        """
        rules_block = ""
        if rules_section:
            rules_block = f"\n\n### Universal System Rules (must also be satisfied):\n{rules_section}"
        return (
            f"You are the Lead Verification Engineer reviewing a script authored by `{args.author}`.\n\n"
            f"### Original Prompt Specification:\n{prompt_content}\n\n"
            f"### Synthesized Script Code:\n```bash\n{final_code_block}\n```\n\n"
            f"### Pre-Flight Linter Output:\n{linter_output}\n\n"
            f"### System & Environment Facts:\n"
            f"- Virtual Environment Isolation: All project tooling must be invoked via explicit paths (`${{VENV_DIR}}/bin/<binary>`). Never rely on bare ambient PATH binaries.\n"
            f"- Package Mapping: `shellcheck-py` installs the native CLI binary at `${{VENV_DIR}}/bin/shellcheck`. Testing `[ -x ${{VENV_DIR}}/bin/shellcheck ]` and `shellcheck --version` is the correct and expected verification.\n"
            f"- Library Mapping: `pyyaml` provides the `yaml` Python module tested via `python -c 'import yaml'`.\n\n"
            f"### Verification Checklist:\n"
            f"1. Requirements: Are all technical specifications and packages met?\n"
            f"2. Pre-Flight Linters: Are there zero unhandled ShellCheck errors or warnings?\n"
            f"3. Explicit Virtual Environment: Are binaries invoked explicitly via `${{VENV_DIR}}/bin/<tool>` rather than bare ambient PATH commands?\n"
            f"4. Defensive Standards: Are strict flags (`set -euo pipefail`), diagnostic `ERR` trap with line number, `EXIT` cleanup trap, binary existence assertions (`[ -x ...]`), and functional smoke tests implemented?\n"
            f"5. Temporary Directory Resilience: Does the script safely handle temporary directories without assuming $TMPDIR exists (e.g. ensuring `mkdir -p \"${{TMPDIR:-/tmp}}\"` or using `mktemp -d -p /tmp`)?\n"
            f"6. Sandbox & Safety: Does Ansible use a temporary directory in `/tmp` to avoid read-only permissions errors?\n"
            f"7. Success Gate: Is the final success message (`🎉 ...`) guarded so it cannot run if an earlier step fails?\n"
            f"8. Heredoc Delimiters: If shell heredocs are used, verify that delimiters are unindented on column 0.\n"
            f"9. Universal System Rules: Verify the script satisfies every rule in the Universal System Rules section below.{rules_block}\n\n"
            f"### Decision Rule:\n"
            f"Conclude your response with exactly `DECISION: APPROVED` if all criteria are satisfied, or `DECISION: REVISION_REQUESTED` followed by bullet points detailing the required fixes."
        )

    @staticmethod
    def _review(args, prompt_content, final_code_block, linter_output, rules_section: str = "") -> str:
        """Run the reviewer (ollama_chat) against the synthesized script.

        ``rules_section`` (optional) is the ``### Universal System Rules`` block
        from Phase 6.05, passed through to the review prompt as an additional
        verification reference.
        """
        transport.send_terminal_mcp(f"🧐 [Verifier `{args.reviewer}`] Evaluating script against prompt specifications...")
        review_prompt = PipelineRunCommand._build_review_prompt(
            args, prompt_content, final_code_block, linter_output, rules_section
        )
        return transport.call_mcp("ollama_chat", {
            "prompt": review_prompt,
            "model": args.reviewer,
            "system_prompt": "You are a strict, uncompromising code verifier and systems engineer.",
            "temperature": 0.1,
            "num_ctx": 4096,
        })

    @staticmethod
    def _handle_review(args, review_verdict, prompt_content, final_code_block, reviewer_history,
                       iteration, max_attempts, current_prompt, approved, abort_reason):
        """Process the reviewer verdict: detect stuck loops, update history and prompt."""
        review_stats = PipelineRunCommand._extract_stats(review_verdict)

        verdict_decision = "DECISION: APPROVED" if "DECISION: APPROVED" in review_verdict else "DECISION: REVISION_REQUESTED"
        transport.send_terminal_mcp(f"📋 [Reviewer Verdict ({args.reviewer})]: {verdict_decision}")
        if review_stats:
            transport.send_terminal_mcp(f"📊 {review_stats}")

        if "DECISION: REVISION_REQUESTED" in review_verdict:
            critique_points = []
            for line in review_verdict.splitlines():
                if line.strip().startswith("- ") or line.strip().startswith("* ") or line.strip().startswith("DECISION:"):
                    critique_points.append(line.strip())
            critique_summary = "\n".join(critique_points) if critique_points else review_verdict.strip()

            # Check for consecutive identical reviewer critiques
            critique_sig = tuple(critique_points) if critique_points else (review_verdict.strip(),)
            consecutive_rev_repeats = 1
            for past_rev in reversed(reviewer_history):
                if past_rev == critique_sig and critique_sig is not None:
                    consecutive_rev_repeats += 1
                else:
                    break
            reviewer_history.append(critique_sig)

            transport.send_terminal_mcp(f"─── [REVIEWER REQUIRED FIXES] [Repeat: {consecutive_rev_repeats}/3] ───────────────")
            transport.send_terminal_mcp(critique_summary)
            transport.send_terminal_mcp("──────────────────────────────────────────────────────────")

            if consecutive_rev_repeats >= 3:
                abort_reason = f"Stuck in reviewer revision loop on iteration {iteration}/{max_attempts}"
                transport.send_terminal_mcp("🛑 [Stuck Loop Detected] Reviewer issued identical critique for 3 consecutive iterations. Aborting pipeline early.")
                print(f"\n[Stuck Loop Abort]: Repeating reviewer critique 3 times\n")
                return approved, abort_reason, current_prompt, reviewer_history
        else:
            reviewer_history.append(None)

        print(f"\n{review_verdict}\n")

        if "DECISION: APPROVED" in review_verdict:
            approved = True
            transport.send_terminal_mcp(f"✅ [Pipeline Approved] Script passed all verification gates!")
        else:
            transport.send_terminal_mcp(f"⚠️ [Revision Requested] Feedback loop initiated for `{args.author}`...")
            current_prompt = (
                f"{prompt_content}\n\n"
                f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
                f"### Reviewer Feedback & Required Fixes:\n{review_verdict}\n\n"
                f"Please rewrite and fix the script addressing all reviewer critique points."
            )
        return approved, abort_reason, current_prompt, reviewer_history

    def execute(self, result, args):
        """Step 4: Live terminal execution of approved code."""
        final_code_block = result["final_code_block"]
        write_file_call = result.get("write_file_call")

        if write_file_call:
            wf_args = write_file_call.get("arguments", {})
            target_path = wf_args.get("path", "")
            is_exec = wf_args.get("make_executable", False)

            # 1. Execute write_file natively via MCP
            transport.send_terminal_mcp(f"📝 [Native Tool Execution] Writing `{target_path}` via MCP...")
            wf_res = transport.call_mcp("write_file", wf_args)
            transport.send_terminal_mcp(f"✅ {wf_res}")

            # 2. Run execution command in terminal-mcp
            exec_bin = f"./{target_path}" if is_exec else f"python3 {target_path}"
            transport.send_terminal_mcp(f"🚀 [Live Terminal Execution] Running `{exec_bin}` in terminal-mcp...")
            banner_cmd = f"echo '🤖 [Ollama Verified Pipeline] Executing: {exec_bin}'; {exec_bin}"
            report = transport.call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Verified execution of {target_path}",
                "cwd": WORKSPACE_ROOT,
                "model": args.reviewer,
                "timeout": args.timeout,
            })
            print(f"\n{report}")
        else:
            transport.send_terminal_mcp(f"🚀 [Live Terminal Execution] Running verified script in terminal-mcp...")
            banner_cmd = f"echo '🤖 [Ollama Verified Pipeline] Executing: {args.file}'; (\n{final_code_block}\n)"
            report = transport.call_mcp("ollama_execute_task", {
                "command": banner_cmd,
                "task_description": f"Verified pipeline execution of {args.file}",
                "cwd": WORKSPACE_ROOT,
                "model": args.reviewer,
                "timeout": args.timeout,
            })
            print(f"\n{report}")
