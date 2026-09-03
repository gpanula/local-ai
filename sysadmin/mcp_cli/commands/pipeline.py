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
    extract_lesson_from_success,
)
from mcp_core.hardware import get_default_model, get_hardware_tier
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
        default_model = get_default_model("sysadmin")
        parser.add_argument("file", help="Path to prompt markdown/text file")
        parser.add_argument("--model", default=default_model, help=f"Model to use (default: {default_model})")
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
        print(f"✅ [Ollama {args.model}] Strategy & Commands Generated:")
        print(f"\n{plan}\n")
        tool_calls = PipelineRunCommand._extract_tool_calls(plan)
        write_file_call = next(
            (tc for tc in tool_calls if tc.get("name") == "write_file"),
            None,
        )
        target_path = None
        if write_file_call:
            wf_args = write_file_call.get("arguments", {})
            if isinstance(wf_args, str):
                try:
                    wf_args = json.loads(wf_args)
                except Exception:
                    wf_args = {}
            target_path = wf_args.get("path")
            target_content = wf_args.get("content")
            is_exec = wf_args.get("make_executable", True)
            if target_path and target_content:
                print(f"📝 Writing `{target_path}` via native MCP tool call...")
                wf_res = transport.call_mcp("write_file", {
                    "path": target_path,
                    "content": target_content,
                    "make_executable": is_exec,
                })
                print(f"✅ {wf_res}")

        code_blocks = re.findall(r"```(?:bash|sh)\s*\n([\s\S]*?)```", plan)
        if target_path:
            exec_cmd = f"./{target_path}"
        elif code_blocks:
            exec_cmd = sanitize_script_code(max(code_blocks, key=len))
        else:
            print("❌ No executable code blocks or tool calls found in Ollama output. Raw plan:\n", plan)
            return

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

        # Record trajectory with full reasoning for future CoT training
        try:
            reasoning = PipelineRunCommand._extract_reasoning_bundle(plan)
            author_stats = PipelineRunCommand._extract_stats(plan)
            roles = {
                "coder": {
                    "model": args.model,
                    "strategy": reasoning.get("strategy", ""),
                    "risks": reasoning.get("risks", ""),
                    "solution": exec_cmd,
                    "verification": reasoning.get("verification_plan", ""),
                }
            }
            record_trajectory(
                {
                    "approved": True,
                    "final_code_block": exec_cmd,
                    "iterations": 1,
                    "script_versions": [exec_cmd],
                    "reasoning": reasoning,
                    "roles": roles,
                    "author_model": args.model,
                    "author_stats": author_stats,
                },
                task_content,
                task_file=args.file,
            )
        except Exception as exc:
            logger.warning("Trajectory recording skipped in build-and-run: %s", exc)


@command
class PipelineRunCommand(BaseCommand):
    name = "pipeline-run"
    help = "Multi-agent pipeline: Author (qwen2.5-coder) -> Lint (Shellcheck) -> Review (qwen3) -> Live Execution"

    def register_args(self, parser):
        default_orchestrator = get_default_model("orchestrator")
        default_author = get_default_model("coder")
        default_reviewer = get_default_model("reviewer")
        parser.add_argument("file", help="Path to prompt markdown/text file")
        parser.add_argument("--orchestrator", default=default_orchestrator, help=f"Model to plan & deconstruct task (default: {default_orchestrator})")
        parser.add_argument("--author", default=default_author, help=f"Model to synthesize code (default: {default_author})")
        parser.add_argument("--reviewer", default=default_reviewer, help=f"Model to review & verify code (default: {default_reviewer})")
        parser.add_argument("--tier", choices=["8gb", "16gb", "24gb"], default=None, help="Model hardware tier to use for all roles (8gb, 16gb, 24gb)")
        parser.add_argument("--keep-models", "--no-unload", dest="keep_models", action="store_true", default=False, help="Keep models loaded in VRAM between stages (defaults to true for 8gb tier)")
        parser.add_argument("--unload-models", action="store_true", default=False, help="Force unloading models between stages (recommended for 24gb/32b models)")
        parser.add_argument("--no-orchestrate", action="store_true", help="Skip the initial Orchestrator planning phase")
        parser.add_argument("--no-lint", action="store_true", help="Skip pre-flight linting step")
        parser.add_argument("--bootstrap", action="store_true", help="Flag task as bootstrap (tolerates missing host tools before installation)")
        parser.add_argument("--max-retries", type=int, default=3, help="Max revision cycles if reviewer rejects (default: 3)")
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
        if getattr(args, "tier", None):
            args.orchestrator = get_default_model("orchestrator", tier=args.tier)
            args.author = get_default_model("coder", tier=args.tier)
            args.reviewer = get_default_model("reviewer", tier=args.tier)
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
        reasoning = {}
        author_stats = ""

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

        roles: dict[str, Any] = {}

        # Step 0: Orchestrator Phase (Decompose high-level prompt into concrete implementation plan)
        if not getattr(args, "no_orchestrate", False):
            try:
                current_prompt = self._orchestrate(current_prompt, args, roles=roles)
            except Exception as exc:  # noqa: BLE001 - orchestration must never block pipeline
                logger.warning("Orchestration pass skipped on error: %s", exc)

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
            reasoning = self._extract_reasoning_bundle(author_response)
            strategy_text = self._extract_strategy(author_response)
            author_stats = self._extract_stats(author_response)
            if strategy_text:
                strategy_body = self._strip_stats(strategy_text)
                if strategy_body:
                    transport.send_terminal_mcp("─── [AUTHOR ANALYSIS & STRATEGY] ──────────────────────────")
                    transport.send_terminal_mcp(strategy_body)
                    transport.send_terminal_mcp("──────────────────────────────────────────────────────────")
            if reasoning.get("risks"):
                transport.send_terminal_mcp("─── [AUTHOR RISKS & EDGE CASES] ──────────────────────────")
                transport.send_terminal_mcp(reasoning["risks"])
                transport.send_terminal_mcp("──────────────────────────────────────────────────────────")
            if reasoning.get("verification_plan"):
                transport.send_terminal_mcp("─── [AUTHOR VERIFICATION PLAN] ───────────────────────────")
                transport.send_terminal_mcp(reasoning["verification_plan"])
                transport.send_terminal_mcp("──────────────────────────────────────────────────────────")
            if author_stats:
                transport.send_terminal_mcp(f"📊 {PipelineRunCommand._format_telemetry(author_stats)}")

            roles["coder"] = self._extract_role_bundle(author_response, "coder")
            roles["coder"]["model"] = getattr(args, "author", "")

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
            if args.author != args.reviewer and PipelineRunCommand._should_unload(args):
                transport.call_mcp("ollama_unload_model", {"model": args.author})

            review_verdict = self._review(
                args, prompt_content, final_code_block, linter_output, rules_section
            )
            approved, abort_reason, current_prompt, reviewer_history = self._handle_review(
                args, review_verdict, prompt_content, final_code_block,
                reviewer_history, iteration, max_attempts, current_prompt, approved, abort_reason,
                roles=roles,
            )
            if abort_reason:
                break

            if not approved and iteration < max_attempts and args.reviewer != args.author and PipelineRunCommand._should_unload(args):
                transport.call_mcp("ollama_unload_model", {"model": args.reviewer})

        # Capture the last non-empty reviewer critique or linter findings for lesson extraction.
        last_critique = ""
        for sig in reversed(reviewer_history):
            if sig:
                if isinstance(sig, (list, tuple)):
                    last_critique = "\n".join(str(p) for p in sig)
                else:
                    last_critique = str(sig)
                break

        if not last_critique:
            for sig in reversed(linter_history):
                if sig:
                    if isinstance(sig, (list, tuple)):
                        last_critique = f"ShellCheck linter findings: {', '.join(str(p) for p in sig)}"
                    else:
                        last_critique = f"ShellCheck linter findings: {sig}"
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
            "reasoning": reasoning,
            "roles": roles,
            "author_model": getattr(args, "author", ""),
            "author_stats": author_stats,
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

    @staticmethod
    def _orchestrate(prompt_content: str, args, roles: dict | None = None) -> str:
        """Run an initial task decomposition pass using the orchestrator model."""
        orchestrator_model = getattr(args, "orchestrator", None)
        if not orchestrator_model:
            return prompt_content

        transport.send_terminal_mcp(
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 [Orchestrator Planning] Decomposing task with `{orchestrator_model}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        system_prompt = (
            "You are Winter Orchestrator, an autonomous task planning and multi-agent workflow coordinator.\n"
            "Your goal is to produce a structured, high-level Implementation Plan and Architecture Guide for the Coder agent.\n\n"
            "CRITICAL CONSTRAINT: DO NOT WRITE CODE. DO NOT write bash scripts, shell code, '#!/bin/bash', heredocs, or write_file snippets. The Coder agent writes the code; you design the architecture and strategy.\n\n"
            "Structure your response into exactly these sections:\n"
            "### 1. Analysis & Strategy\n"
            "- Detail your step-by-step thinking: How did you analyze the prompt's requirements, edge cases, and constraints?\n"
            "- Explain your design rationale, architectural tradeoffs, and how you incorporated Injected Lessons from Memory and Universal System Rules.\n"
            "### 2. Risks & Constraints\n"
            "- Detail potential threat models, environment traps, dependency deadlocks, or side-effects.\n"
            "### 3. Architecture & Plan\n"
            "- Specify deterministic path resolution requirements, required binary checks, and step-by-step roadmap.\n"
            "- Target file path (e.g. sysadmin/verify_code_quality_toolchain.sh) and instruction for Coder.\n"
            "### 4. Acceptance Gates & Tests\n"
            "- Describe the exact valid and invalid test cases, strict mode flags, trap handlers, cleanup requirements, and success conditions.\n\n"
            "Respond with ONLY the markdown architectural plan and analysis."
        )

        plan = transport.call_mcp("ollama_chat", {
            "prompt": (
                f"### High-Level Task Specification:\n{prompt_content}\n\n"
                f"Deconstruct this specification into a concrete, robust Implementation Plan for the Coder agent. Outline your cognitive reasoning, architectural specs, and test case definitions. DO NOT output executable script code."
            ),
            "model": orchestrator_model,
            "system_prompt": system_prompt,
            "temperature": 0.2,
        })

        stats = PipelineRunCommand._extract_stats(plan)
        plan_body = PipelineRunCommand._strip_stats(plan)
        transport.send_terminal_mcp("─── [ORCHESTRATOR PLANNING & ARCHITECTURE GUIDE] ───")
        transport.send_terminal_mcp(plan_body)
        if stats:
            transport.send_terminal_mcp(f"📊 {PipelineRunCommand._format_telemetry(stats)}")
        transport.send_terminal_mcp("───────────────────────────────────────────────────")

        if roles is not None:
            roles["orchestrator"] = PipelineRunCommand._extract_role_bundle(plan_body, "orchestrator")
            roles["orchestrator"]["model"] = orchestrator_model

        # Free VRAM if authoring model is different from orchestrator
        if orchestrator_model != args.author and PipelineRunCommand._should_unload(args):
            transport.call_mcp("ollama_unload_model", {"model": orchestrator_model})

        return (
            f"{prompt_content}\n\n"
            f"### Orchestrator Implementation Plan (Follow this strategy):\n"
            f"{plan_body}"
        )

    @staticmethod
    def _reorchestrate(prompt_content: str, current_prompt: str, final_code_block: str,
                       critique: str, args, roles: dict | None = None) -> str:
        """Re-evaluate and revise the Implementation Plan when a reviewer rejects code."""
        orchestrator_model = getattr(args, "orchestrator", None)
        if not orchestrator_model:
            return current_prompt

        transport.send_terminal_mcp(
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 [Orchestrator Plan Revision] Updating plan with `{orchestrator_model}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        system_prompt = (
            "You are Winter Orchestrator, an autonomous task planning and multi-agent workflow coordinator.\n"
            "An implementation attempt failed verification or review. Your goal is to diagnose the failure in the previous plan and generate a revised, concrete Implementation Plan for the Coder agent.\n\n"
            "CRITICAL CONSTRAINT: DO NOT WRITE CODE. DO NOT write bash scripts, shell code, '#!/bin/bash', heredocs, or write_file snippets. Focus on diagnosing root cause and refining the test specifications.\n\n"
            "Structure your revised plan into exactly these sections:\n"
            "### 1. Analysis & Strategy\n"
            "- Root cause analysis: Why did the previous plan or code fail? Where was the misunderstanding, oversight, or mismatch with specifications?\n"
            "- What principles or lessons from memory apply to permanently prevent this failure mode?\n"
            "### 2. Risks & Constraints\n"
            "- Identify regressions to avoid during the fix.\n"
            "### 3. Architecture & Plan\n"
            "- Corrective architecture, target file path, and updated implementation instructions.\n"
            "### 4. Acceptance Gates & Tests\n"
            "- Updated verification requirements and acceptance criteria for passing the next review.\n\n"
            "Respond with ONLY the markdown Revised Implementation Plan."
        )

        revised_plan = transport.call_mcp("ollama_chat", {
            "prompt": (
                f"### High-Level Task Specification:\n{prompt_content}\n\n"
                f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
                f"### Reviewer Critique & Diagnostic Findings:\n{critique}\n\n"
                "Diagnose the failure, articulate your cognitive root-cause analysis, and provide a revised, corrected Implementation Plan for the Coder. DO NOT output executable script code."
            ),
            "model": orchestrator_model,
            "system_prompt": system_prompt,
            "temperature": 0.2,
        })

        stats = PipelineRunCommand._extract_stats(revised_plan)
        revised_plan_body = PipelineRunCommand._strip_stats(revised_plan)
        transport.send_terminal_mcp("─── [REVISED ORCHESTRATOR DIAGNOSIS & PLAN] ───")
        transport.send_terminal_mcp(revised_plan_body)
        if stats:
            transport.send_terminal_mcp(f"📊 {PipelineRunCommand._format_telemetry(stats)}")
        transport.send_terminal_mcp("───────────────────────────────────────────────")

        if roles is not None:
            roles["orchestrator"] = PipelineRunCommand._extract_role_bundle(revised_plan_body, "orchestrator")
            roles["orchestrator"]["model"] = orchestrator_model

        return (
            f"{prompt_content}\n\n"
            f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
            f"### Reviewer Critique & Diagnostics:\n{critique}\n\n"
            f"### Revised Orchestrator Implementation Plan (Follow this corrected strategy):\n"
            f"{revised_plan_body}"
        )

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
            if approved and iterations == 1:
                self._stage_positive_lesson_if_applicable(result, prompt_content, args)
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

    def _stage_positive_lesson_if_applicable(self, result, prompt_content, args) -> None:
        """Stage a pre_emptive_defense lesson if iteration 1 identified proactive risks."""
        reasoning = result.get("reasoning") or {}
        risks = reasoning.get("risks", "")
        strategy = reasoning.get("strategy", "")
        if not risks:
            return
        task_file = getattr(args, "file", "")
        try:
            lesson = extract_lesson_from_success(
                strategy=strategy,
                risks=risks,
                task_file=task_file,
                prompt_content=prompt_content,
                model=getattr(args, "reviewer", "qwen3:8b"),
            )
            if lesson:
                with MemoryStore() as store:
                    store.stage_pending_lesson(lesson)
                result["lesson_type"] = lesson["lesson_type"]
                transport.send_terminal_mcp(
                    f"💡 1 proactive defense lesson staged in pending queue (type: {lesson['lesson_type']})"
                )
        except Exception as exc:  # noqa: BLE001 - staging must never block the pipeline
            logger.warning("Failed to stage positive lesson: %s", exc)

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
    def _extract_section(text: str, patterns: list) -> str:
        """Extract content under a markdown heading matching any regex pattern."""
        for pattern in patterns:
            regex = rf"###\s*(?:\d+\.\s*)?{pattern}\s*\n([\s\S]*?)(?=###|\*Generated by|\Z)"
            match = re.search(regex, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_role_bundle(text: str, role: str) -> dict:
        """Extract the 4 standardized cognitive pillars for any of the 6 roles."""
        clean_text = PipelineRunCommand._strip_stats(text or "")
        bundle = {}

        if role in ("coder", "architect"):
            bundle["strategy"] = PipelineRunCommand._extract_section(
                clean_text, [r"Analysis\s*&\s*Strategy", r"Planning\s*Analysis"]
            )
            bundle["risks"] = PipelineRunCommand._extract_section(
                clean_text, [r"Risks\s*(?:&|and)\s*Edge\s*Cases", r"Risks\s*(?:&|and)\s*Constraints"]
            )
            if role == "coder":
                code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", clean_text)
                bundle["solution"] = code_blocks[0].strip() if code_blocks else ""
                bundle["verification"] = PipelineRunCommand._extract_section(
                    clean_text, [r"Verification\s*(?:&|and)\s*Testing"]
                )
            else:
                bundle["design"] = PipelineRunCommand._extract_section(
                    clean_text, [r"Architecture\s*(?:&|and)\s*Design\s*Specification", r"Architecture\s*(?:&|and)\s*Plan"]
                )
                bundle["acceptance"] = PipelineRunCommand._extract_section(
                    clean_text, [r"Acceptance\s*Criteria\s*(?:&|and)\s*Verification", r"Acceptance\s*Gates\s*(?:&|and)\s*Tests"]
                )

        elif role == "orchestrator":
            bundle["strategy"] = PipelineRunCommand._extract_section(
                clean_text, [r"Analysis\s*&\s*Strategy", r"Planning\s*Analysis", r"Root\s*Cause\s*Analysis"]
            )
            bundle["risks"] = PipelineRunCommand._extract_section(
                clean_text, [r"Risks\s*(?:&|and)\s*Constraints", r"Risks\s*(?:&|and)\s*Edge\s*Cases"]
            )
            bundle["plan"] = PipelineRunCommand._extract_section(
                clean_text, [r"Architecture\s*(?:&|and)\s*Plan", r"Architectural\s*Strategy", r"Workflow\s*(?:&|and)\s*Task"]
            )
            bundle["gates"] = PipelineRunCommand._extract_section(
                clean_text, [r"Acceptance\s*Gates\s*(?:&|and)\s*Tests", r"Functional\s*Test\s*Suite", r"Defensive\s*Standards"]
            )

        elif role == "reviewer":
            bundle["audit"] = PipelineRunCommand._extract_section(
                clean_text, [r"Verification\s*Audit", r"Verification\s*Audit\s*(?:&|and)\s*Cognitive\s*Analysis"]
            )
            bundle["risks"] = PipelineRunCommand._extract_section(
                clean_text, [r"Risk\s*(?:&|and)\s*Regression\s*Check", r"Risks\s*(?:&|and)\s*Edge\s*Cases"]
            )
            bundle["decision"] = "APPROVED" if "DECISION: APPROVED" in clean_text else "REVISION_REQUESTED"
            decision_part = clean_text.split("DECISION:", 1)[-1] if "DECISION:" in clean_text else clean_text
            critique_lines = [
                line.strip() for line in decision_part.splitlines()
                if line.strip().startswith(("- ", "* "))
            ]
            bundle["fixes"] = "\n".join(critique_lines)
            bundle["evidence"] = PipelineRunCommand._extract_section(
                clean_text, [r"Validation\s*Evidence"]
            )

        elif role == "security":
            bundle["threat_model"] = PipelineRunCommand._extract_section(
                clean_text, [r"Threat\s*Modeling\s*(?:&|and)\s*Attack\s*Surface"]
            )
            bundle["vulnerabilities"] = PipelineRunCommand._extract_section(
                clean_text, [r"Vulnerabilities\s*(?:&|and)\s*Exploit\s*Scenarios"]
            )
            bundle["remediation"] = PipelineRunCommand._extract_section(
                clean_text, [r"Security\s*Remediation\s*(?:&|and)\s*Hardening"]
            )
            bundle["proof"] = PipelineRunCommand._extract_section(
                clean_text, [r"Security\s*Audit\s*(?:&|and)\s*Compliance\s*Proof"]
            )

        elif role == "sysadmin":
            bundle["state_analysis"] = PipelineRunCommand._extract_section(
                clean_text, [r"System\s*State\s*(?:&|and)\s*Root\s*Cause\s*Analysis"]
            )
            bundle["blast_radius"] = PipelineRunCommand._extract_section(
                clean_text, [r"Operational\s*Risks\s*(?:&|and)\s*Blast\s*Radius"]
            )
            bundle["remediation"] = PipelineRunCommand._extract_section(
                clean_text, [r"Automation\s*(?:&|and)\s*Remediation\s*Action"]
            )
            bundle["verification"] = PipelineRunCommand._extract_section(
                clean_text, [r"Operational\s*Verification\s*(?:&|and)\s*Telemetry"]
            )

        return bundle

    @staticmethod
    def _extract_risks(author_response: str) -> str:
        """Extract the '### Risks & Edge Cases' section from the model's response."""
        return PipelineRunCommand._extract_section(
            author_response, [r"Risks\s*(?:&|and)\s*Edge\s*Cases"]
        )

    @staticmethod
    def _extract_verification(author_response: str) -> str:
        """Extract the '### Verification & Testing' section from the model's response."""
        return PipelineRunCommand._extract_section(
            author_response, [r"Verification\s*(?:&|and)\s*Testing"]
        )

    @staticmethod
    def _extract_reasoning_bundle(author_response: str) -> dict:
        """Extract strategy, risks, and verification_plan into a structured dictionary."""
        coder_bundle = PipelineRunCommand._extract_role_bundle(author_response, "coder")
        return {
            "strategy": coder_bundle.get("strategy", ""),
            "risks": coder_bundle.get("risks", ""),
            "verification_plan": coder_bundle.get("verification", ""),
        }

    @staticmethod
    def _extract_stats(author_response: str) -> str:
        """Extract the '*Generated by `model`: N tokens in Xs (Y t/s) | Context: ...*' footer."""
        match = re.search(r"(\*Generated by `[^`]+`: [^*]+\*)", author_response)
        return match.group(1) if match else ""

    @staticmethod
    def _strip_stats(text: str) -> str:
        """Strips the trailing '--- \n*Generated by ...*' footer from response text."""
        return re.sub(r"\n*---\s*\n\*Generated by `[^`]+`: [^*]+\*\s*$", "", text).strip()

    @staticmethod
    def _format_telemetry(raw_stats: str) -> str:
        """Formats raw telemetry with threshold alerts for low TPS, high context window usage, and model residency."""
        if not raw_stats:
            return ""
        pattern = (
            r"\*Generated by `(?P<model>[^`]+)`: (?P<tokens>\d+) tokens in (?P<duration>[\d\.]+)s \((?P<tps>[\d\.]+) t/s\)(?: \[(?P<residency>[^\]]+)\])?"
            r" \| Context: (?P<ctx_used>[\d,]+) / (?P<ctx_max>[\d,]+) tokens \((?P<pct>[\d\.]+)%\)\*"
        )
        match = re.search(pattern, raw_stats)
        if not match:
            return raw_stats

        model = match.group("model")
        tokens = match.group("tokens")
        duration = match.group("duration")
        tps = float(match.group("tps"))
        residency = match.group("residency") or ""
        ctx_used = match.group("ctx_used")
        ctx_max = match.group("ctx_max")
        pct = float(match.group("pct"))

        # TPS formatting (< 26 critical alert, < 51 warning, >= 51 normal)
        if tps < 26.0:
            tps_str = f"🚨 {tps:.1f} t/s (CRITICAL LOW)"
        elif tps < 51.0:
            tps_str = f"⚠️ {tps:.1f} t/s"
        else:
            tps_str = f"{tps:.1f} t/s"

        # Context formatting (> 82% critical alert, > 55% warning, <= 55% normal)
        if pct > 82.0:
            ctx_str = f"🚨 Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}% - HIGH USAGE)"
        elif pct > 55.0:
            ctx_str = f"⚠️ Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}%)"
        else:
            ctx_str = f"Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}%)"

        # Format residency badge
        if residency == "resident":
            res_str = " [⚡ resident]"
        elif "cold load" in residency:
            res_str = f" [⏳ {residency}]"
        else:
            res_str = ""

        return (
            f"*Generated by `{model}`: {tokens} tokens in {duration}s ({tps_str}){res_str}"
            f" | {ctx_str}*"
        )

    @staticmethod
    def _should_unload(args) -> bool:
        """Determine whether models should be purged from VRAM between stage transitions."""
        if getattr(args, "unload_models", False):
            return True
        if getattr(args, "keep_models", False):
            return False
        # If all configured models are 8gb tier, keep in memory by default for speed
        models = [getattr(args, "orchestrator", ""), getattr(args, "author", ""), getattr(args, "reviewer", "")]
        all_small = all((":8gb" in m or ":7b" in m or ":8b" in m or "olmoe" in m) for m in models if m)
        if all_small:
            return False
        return True

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

        # Also inspect for un-fenced JSON objects (single-line or multi-line)
        if not tool_calls:
            matches = list(re.finditer(r'\{\s*"name"\s*:\s*"(?:write_file|read_file)"', author_response))
            decoder = json.JSONDecoder()
            for m in matches:
                try:
                    tc_obj, _ = decoder.raw_decode(author_response[m.start():])
                    if isinstance(tc_obj, dict) and "name" in tc_obj:
                        if "arguments" not in tc_obj:
                            tc_obj = {"name": tc_obj["name"], "arguments": tc_obj}
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
            f"- Virtual Environment Resolution: Resolve REPO_ROOT and default VENV_DIR to `${{REPO_ROOT}}/sysadmin/venv`.\n"
            f"- Package Mapping: `shellcheck-py` installs the native CLI binary at `${{VENV_DIR}}/bin/shellcheck`. Testing `[ -x ${{VENV_DIR}}/bin/shellcheck ]` and `shellcheck --version` is the correct and expected verification.\n"
            f"- Library Mapping: `pyyaml` provides the `yaml` Python module tested via `python -c 'import yaml'`. `ast` is a built-in Python standard library module and must NEVER be installed via pip.\n\n"
            f"### Verification Checklist:\n"
            f"1. Requirements: Are all technical specifications and packages met?\n"
            f"2. Pre-Flight Linters: Are there zero unhandled ShellCheck errors or warnings?\n"
            f"3. Explicit Virtual Environment: Are binaries invoked explicitly via `${{VENV_DIR}}/bin/<tool>` with VENV_DIR defaulting to `${{REPO_ROOT}}/sysadmin/venv`?\n"
            f"4. Defensive Standards: Are strict flags (`set -euo pipefail`), diagnostic `ERR` trap with line number, `EXIT` cleanup trap, binary existence assertions (`[ -x ...]`), and functional smoke tests implemented?\n"
            f"5. Temporary Directory Resilience: Does the script safely handle temporary directories without assuming $TMPDIR exists (e.g. ensuring `mkdir -p \"${{TMPDIR:-/tmp}}\"` or using `mktemp -d -p /tmp`)?\n"
            f"6. Sandbox & Safety: Does Ansible use a temporary directory in `/tmp` to avoid read-only permissions errors?\n"
            f"7. Success Gate: Is the final success message (`🎉 ...`) guarded so it cannot run if an earlier step fails?\n"
            f"8. Heredoc Delimiters: If shell heredocs are used, verify that delimiters are unindented on column 0.\n"
            f"9. Universal System Rules: Verify the script satisfies every rule in the Universal System Rules section below.{rules_block}\n\n"
            f"### Response Structure:\n"
            f"Structure your response into exactly these sections:\n"
            f"### 1. Verification Audit\n"
            f"- Detail your step-by-step thinking as you audit the script against each checklist item and prompt requirements.\n"
            f"- State the evidence found in the script (or what is missing) and analyze the reasoning behind your assessment.\n\n"
            f"### 2. Risk & Regression Check\n"
            f"- Evaluate potential side-effects, anti-patterns, or subtle bugs.\n\n"
            f"### 3. Decision & Required Fixes\n"
            f"Conclude with exactly `DECISION: APPROVED` if all criteria are satisfied, or `DECISION: REVISION_REQUESTED` followed by bullet points detailing the required fixes.\n\n"
            f"### 4. Validation Evidence\n"
            f"- Note specific line numbers and code references supporting your decision."
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
        })

    @staticmethod
    def _handle_review(args, review_verdict, prompt_content, final_code_block, reviewer_history,
                       iteration, max_attempts, current_prompt, approved, abort_reason,
                       roles: dict | None = None):
        """Process the reviewer verdict: detect stuck loops, update history and prompt."""
        review_stats = PipelineRunCommand._extract_stats(review_verdict)

        # Extract and stream Reviewer Verification Audit & Cognitive Analysis
        clean_verdict = PipelineRunCommand._strip_stats(review_verdict)
        audit_match = re.search(
            r"###\s*(?:1\.\s*)?Verification\s*Audit(?:\s*&\s*Cognitive\s*Analysis)?\s*\n([\s\S]*?)(?=###\s*(?:2\.|3\.)|DECISION:|\Z)",
            clean_verdict,
            re.IGNORECASE,
        )
        audit_text = audit_match.group(1).strip() if audit_match else ""
        if not audit_text and "DECISION:" in clean_verdict:
            parts = clean_verdict.split("DECISION:", 1)
            candidate = parts[0].strip()
            if len(candidate) > 40:
                audit_text = candidate

        if audit_text:
            transport.send_terminal_mcp("─── [REVIEWER VERIFICATION AUDIT & REASONING] ────────────")
            transport.send_terminal_mcp(audit_text)
            transport.send_terminal_mcp("──────────────────────────────────────────────────────────")

        if roles is not None:
            roles["reviewer"] = PipelineRunCommand._extract_role_bundle(clean_verdict, "reviewer")
            roles["reviewer"]["model"] = args.reviewer

        verdict_decision = "DECISION: APPROVED" if "DECISION: APPROVED" in review_verdict else "DECISION: REVISION_REQUESTED"
        transport.send_terminal_mcp(f"📋 [Reviewer Verdict ({args.reviewer})]: {verdict_decision}")
        if review_stats:
            transport.send_terminal_mcp(f"📊 {PipelineRunCommand._format_telemetry(review_stats)}")

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
            if not getattr(args, "no_orchestrate", False) and getattr(args, "orchestrator", None):
                try:
                    current_prompt = PipelineRunCommand._reorchestrate(
                        prompt_content, current_prompt, final_code_block, review_verdict, args, roles=roles
                    )
                except Exception as exc:  # noqa: BLE001 - reorchestration must never block
                    logger.warning("Re-orchestration pass skipped on error: %s", exc)
                    current_prompt = (
                        f"{prompt_content}\n\n"
                        f"### Previous Implementation Attempt:\n```bash\n{final_code_block}\n```\n\n"
                        f"### Reviewer Feedback & Required Fixes:\n{review_verdict}\n\n"
                        f"Please rewrite and fix the script addressing all reviewer critique points."
                    )
            else:
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

        target_path = ""
        is_exec = True
        if write_file_call:
            wf_args = write_file_call.get("arguments", {})
            target_path = wf_args.get("path", "")
            is_exec = wf_args.get("make_executable", True)
        else:
            prompt_file = getattr(args, "file", "")
            if "prompts/" in prompt_file and prompt_file.endswith(".md"):
                target_path = prompt_file.replace("prompts/", "").replace(".md", ".sh")
            elif prompt_file.endswith(".md"):
                target_path = prompt_file.replace(".md", ".sh")

        if target_path:
            # 1. Execute write_file natively via MCP
            transport.send_terminal_mcp(f"📝 [Native Tool Execution] Writing `{target_path}` via MCP...")
            wf_res = transport.call_mcp("write_file", {
                "path": target_path,
                "content": final_code_block,
                "make_executable": is_exec,
            })
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

        # Cleanly release GPU VRAM on pipeline completion if unloading enabled
        if PipelineRunCommand._should_unload(args):
            transport.call_mcp("ollama_unload_model", {})
