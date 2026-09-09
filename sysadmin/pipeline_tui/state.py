"""State container for PipelineWatch TUI.

Consumes events from live event streams or trajectory replay, maintaining
reactive state for all widgets across iterations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


STAGE_ORDER = ["architect", "orchestrator", "reviewer", "security", "coder", "sysadmin"]


def normalize_stage(stage: str) -> str:
    """Normalize alias and role names to standard 6-stage pipeline keys."""
    s = (stage or "").lower().strip()
    aliases = {
        "orchestrate": "orchestrator",
        "author": "coder",
        "lint": "reviewer",
        "review": "reviewer",
        "execute": "sysadmin",
        "execution": "sysadmin",
        "dispatch": "coder",
    }
    return aliases.get(s, s)


class IterationState:
    """State for a single iteration cycle."""

    def __init__(self, iteration_num: int):
        self.iteration = iteration_num
        self.context_window: Dict[str, Any] = {}
        self.stage_contexts: Dict[str, Dict[str, Any]] = {
            "architect": {},
            "orchestrator": {},
            "reviewer": {},
            "security": {},
            "coder": {},
            "sysadmin": {},
            "dispatch": {},
            "orchestrate": {},
            "author": {},
            "lint": {},
            "review": {},
            "execute": {},
        }
        self.thinking: str = ""
        self.stage_thinking: Dict[str, str] = {
            "architect": "",
            "orchestrator": "",
            "reviewer": "",
            "security": "",
            "coder": "",
            "sysadmin": "",
            "dispatch": "",
            "orchestrate": "",
            "author": "",
            "lint": "",
            "review": "",
            "execute": "",
        }
        self.stage_models: Dict[str, str] = {
            "architect": "",
            "orchestrator": "",
            "reviewer": "",
            "security": "",
            "coder": "qwen2.5-coder:7b",
            "sysadmin": "qwen2.5-coder:7b",
            "dispatch": "sandbox",
            "orchestrate": "",
            "author": "",
            "lint": "shellcheck",
            "review": "",
            "execute": "sandbox",
        }
        self.reasoning: Dict[str, Any] = {}
        self.stage_reasoning: Dict[str, Dict[str, Any]] = {
            "architect": {},
            "orchestrator": {},
            "reviewer": {},
            "security": {},
            "coder": {},
            "sysadmin": {},
            "dispatch": {},
            "orchestrate": {},
            "author": {},
            "lint": {},
            "review": {},
            "execute": {},
        }
        self.code: str = ""
        self.script_name: Optional[str] = None
        self.stats: Dict[str, Any] = {}
        self.linter: Dict[str, Any] = {}
        self.review: Dict[str, Any] = {}


class PipelineState:
    """Complete state for a monitored pipeline run."""

    def __init__(self):
        self.run_id: str = ""
        self.start_time: str = ""
        self.task_file: str = ""
        self.prompt: str = ""
        self.tier: str = "8gb"
        self.models: Dict[str, str] = {}
        self.max_retries: int = 3
        self.current_stage: str = "idle"
        self.selected_stage: str = "architect"
        self.active_iteration_idx: int = 1
        self.iterations: Dict[int, IterationState] = {}
        self.terminal_lines: List[str] = []
        self.outcome: str = "in_progress"
        self.abort_reason: str = ""
        self.duration_sec: float = 0.0
        self.elapsed_sec: float = 0.0

    def prev_stage(self) -> str:
        """Step left to previous stage in STAGE_ORDER."""
        cur = normalize_stage(self.selected_stage)
        idx = STAGE_ORDER.index(cur) if cur in STAGE_ORDER else 0
        new_idx = max(0, idx - 1)
        self.selected_stage = STAGE_ORDER[new_idx]
        return self.selected_stage

    def next_stage(self) -> str:
        """Step right to next stage in STAGE_ORDER."""
        cur = normalize_stage(self.selected_stage)
        idx = STAGE_ORDER.index(cur) if cur in STAGE_ORDER else 0
        new_idx = min(len(STAGE_ORDER) - 1, idx + 1)
        self.selected_stage = STAGE_ORDER[new_idx]
        return self.selected_stage

    def get_iteration(self, num: int) -> IterationState:
        if num not in self.iterations:
            self.iterations[num] = IterationState(num)
        return self.iterations[num]

    def current_iteration(self) -> IterationState:
        return self.get_iteration(self.active_iteration_idx)

    def get_stage_model(self, stage: str) -> str:
        """Resolve the model or tool name associated with a stage."""
        norm_st = normalize_stage(stage)
        cur_it = self.current_iteration()
        m = cur_it.stage_models.get(norm_st) or cur_it.stage_models.get(stage)
        if m:
            return m
        if norm_st == "architect":
            return self.models.get("architect") or self.models.get("default") or "winter-prime:latest"
        elif norm_st == "orchestrator":
            return self.models.get("orchestrator") or self.models.get("author") or self.models.get("default") or "winter-prime:latest"
        elif norm_st == "reviewer":
            return self.models.get("reviewer") or self.models.get("default") or "winter-prime:latest"
        elif norm_st == "security":
            return self.models.get("security") or self.models.get("default") or "winter-prime:latest"
        elif norm_st == "coder":
            return self.models.get("coder") or "qwen2.5-coder:7b"
        elif norm_st in ("sysadmin", "dispatch", "execute"):
            return self.models.get("sysadmin") or "sandbox / sysadmin"
        return ""

    def get_stage_thinking(self, stage: str) -> str:
        """Retrieve deliberation or raw CoT for a specific stage."""
        norm_st = normalize_stage(stage)
        cur_it = self.current_iteration()
        t = cur_it.stage_thinking.get(norm_st) or cur_it.stage_thinking.get(stage, "")
        if t:
            return t
        sr = getattr(cur_it, "stage_reasoning", {}).get(norm_st) or getattr(cur_it, "stage_reasoning", {}).get(stage)
        if sr and isinstance(sr, dict) and any(sr.values()):
            parts = []
            if sr.get("strategy"):
                parts.append(f"🧠 [Pillar 1: Analysis & Strategy]\n{sr['strategy']}")
            if sr.get("risks"):
                parts.append(f"⚠️ [Pillar 2: Risks & Edge Cases]\n{sr['risks']}")
            if sr.get("solution"):
                parts.append(f"🛠️ [Pillar 3: Solution & Decisions]\n{sr['solution']}")
            if sr.get("verification_plan") or sr.get("verification"):
                parts.append(f"🧪 [Pillar 4: Verification & Testing]\n{sr.get('verification_plan') or sr.get('verification')}")
            if parts:
                return "\n\n".join(parts)
        roles = cur_it.review.get("roles") or {}
        if norm_st == "architect":
            arch = roles.get("architect") or roles.get("coder") or {}
            cot = arch.get("chain_of_thought") or arch.get("analysis") or ""
            return cot or cur_it.thinking
        elif norm_st == "orchestrator":
            orch = roles.get("orchestrator") or {}
            cot = orch.get("chain_of_thought") or orch.get("analysis") or ""
            return cot or cur_it.thinking
        elif norm_st == "reviewer":
            rev = roles.get("reviewer") or {}
            cot = rev.get("chain_of_thought") or ""
            if cot:
                return cot
            if cur_it.review:
                v = cur_it.review.get("verdict", "")
                c = cur_it.review.get("critique", "")
                return f"Reviewer Gate Evaluation:\nVerdict: {v}\n\nCritique:\n{c}"
        elif norm_st == "security":
            sec = roles.get("security") or {}
            cot = sec.get("chain_of_thought") or sec.get("analysis") or ""
            return cot
        elif norm_st == "coder":
            cdr = roles.get("coder") or roles.get("author") or {}
            cot = cdr.get("chain_of_thought") or cdr.get("analysis") or ""
            return cot or cur_it.thinking
        elif norm_st in ("sysadmin", "dispatch", "execute") and self.terminal_lines:
            return "\n".join(self.terminal_lines[-50:])
        return ""

    def get_stage_context(self, stage: str) -> Dict[str, Any]:
        """Resolve the context window for a given stage/role."""
        norm_st = normalize_stage(stage)
        cur_it = self.current_iteration()
        ctx = cur_it.stage_contexts.get(norm_st) or cur_it.stage_contexts.get(stage)
        if ctx and (ctx.get("system_rules") or ctx.get("token_breakdown")):
            if not ctx.get("lessons"):
                try:
                    import json
                    up = json.loads(ctx.get("user_prompt", "{}"))
                    if isinstance(up, dict) and up.get("injected_lessons"):
                        ctx["lessons"] = up["injected_lessons"]
                        if "token_breakdown" in ctx:
                            tb = ctx["token_breakdown"]
                            if tb.get("lessons", 0) == 0:
                                lessons_tk = len(json.dumps(ctx["lessons"])) // 4
                                tb["lessons"] = lessons_tk
                                tb["total"] = tb.get("total", 0) + lessons_tk
                except Exception:
                    pass
            return ctx
        return self._derive_stage_context(stage, cur_it)

    def _derive_stage_context(self, stage: str, it: IterationState) -> Dict[str, Any]:
        """Synthesize a structured context window for stages lacking explicit events."""
        norm_st = normalize_stage(stage)
        base_ctx = it.context_window or {}
        task_prompt = self.prompt or base_ctx.get("user_prompt", "")
        script_code = it.code or ""
        injected_lessons = base_ctx.get("lessons") or []
        if not injected_lessons and base_ctx.get("user_prompt"):
            try:
                import json
                up = json.loads(base_ctx.get("user_prompt", "{}"))
                if isinstance(up, dict) and up.get("injected_lessons"):
                    injected_lessons = up["injected_lessons"]
            except Exception:
                pass

        def est(t: str) -> int:
            return max(1, len(t) // 4) if t else 0

        if norm_st == "architect":
            arch_rules = (
                "Winter Architect Planning & Architecture Standard:\n"
                "- Decompose task requirements into concrete Implementation Plan.\n"
                "- Constraint: DO NOT WRITE CODE. Architecture and strategy only.\n"
                "- Structure into: 1. Analysis & Strategy, 2. Risks & Constraints, 3. Architecture & Plan, 4. Acceptance Gates."
            )
            rework_fb = it.stage_thinking.get("architect", "") if it.iteration > 1 else ""
            rules_tk = est(arch_rules)
            prompt_tk = est(task_prompt)
            fb_tk = est(rework_fb)
            return {
                "stage": "architect",
                "system_rules": arch_rules,
                "tools": [],
                "lessons": injected_lessons,
                "user_prompt": task_prompt,
                "rework_feedback": rework_fb or "(Initial architectural planning pass)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 0,
                    "lessons": len(injected_lessons) * 200,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + prompt_tk + fb_tk + (len(injected_lessons) * 200),
                    "limit": 8192,
                },
            }

        elif norm_st == "orchestrator":
            orch_rules = (
                "Winter Orchestrator Scheduling & Task DAG Standard:\n"
                "- Convert high-level architectural plan into discrete executable sub-tasks.\n"
                "- Define strict dependencies, expected outputs, and acceptance criteria per task.\n"
                "- Role assignments: coder (synthesis), sysadmin (execution & verification)."
            )
            rework_fb = it.stage_thinking.get("orchestrator", "") if it.iteration > 1 else ""
            rules_tk = est(orch_rules)
            prompt_tk = est(task_prompt)
            fb_tk = est(rework_fb)
            return {
                "stage": "orchestrator",
                "system_rules": orch_rules,
                "tools": [],
                "lessons": injected_lessons,
                "user_prompt": task_prompt,
                "rework_feedback": rework_fb or "(Initial orchestration pass)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 0,
                    "lessons": len(injected_lessons) * 200,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + prompt_tk + fb_tk + (len(injected_lessons) * 200),
                    "limit": 8192,
                },
            }

        elif norm_st == "reviewer":
            rev_rules = (
                "Reviewer Gate Verification Rubric:\n"
                "- Validate strict bash headers (set -euo pipefail) and ERR trap handlers.\n"
                "- Verify deterministic binary and venv path resolution (no ambient $PATH).\n"
                "- Zero tolerance for hardcoded /home/<user> or unquoted variable expansions.\n"
                "- Output explicit verdict: APPROVED or REJECTED with critique."
            )
            rev_prompt = f"### Task Prompt:\n{task_prompt}\n\n### Candidate Script:\n```bash\n{script_code}\n```"
            rev_fb = it.review.get("critique", "") if it.review else ""
            rules_tk = est(rev_rules)
            prompt_tk = est(rev_prompt)
            fb_tk = est(rev_fb)
            return {
                "stage": "reviewer",
                "system_rules": rev_rules,
                "tools": [{"name": "verdict", "description": "APPROVED or REJECTED schema"}],
                "lessons": injected_lessons,
                "user_prompt": rev_prompt,
                "rework_feedback": rev_fb or "(Reviewer deliberation pending)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 150,
                    "lessons": len(injected_lessons) * 200,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + 150 + (len(injected_lessons) * 200) + prompt_tk + fb_tk,
                    "limit": 8192,
                },
            }

        elif norm_st == "security":
            sec_rules = (
                "Security Gate Policy & STRIDE Analysis:\n"
                "- Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege.\n"
                "- Verify parameter sanitization and injection guards.\n"
                "- Enforce least privilege and scrub credentials/secrets."
            )
            sec_fb = it.stage_thinking.get("security", "")
            rules_tk = est(sec_rules)
            prompt_tk = est(script_code or task_prompt)
            fb_tk = est(sec_fb)
            return {
                "stage": "security",
                "system_rules": sec_rules,
                "tools": [{"name": "security_audit", "description": "STRIDE threat modeler"}],
                "lessons": [],
                "user_prompt": script_code or task_prompt,
                "rework_feedback": sec_fb or "(Security evaluation pending)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 100,
                    "lessons": 0,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + 100 + prompt_tk + fb_tk,
                    "limit": 8192,
                },
            }

        elif norm_st == "coder":
            coder_rules = (
                "Winter Coder Code Authorship & Lint Standard:\n"
                "- Author defensive bash scripts or python modules per task spec.\n"
                "- Constraint: Pure code output only; must satisfy ShellCheck and pytest.\n"
                "- Follow AGENTS.md standards: set -euo pipefail, explicit traps, no hardcoded /home."
            )
            rules_tk = est(coder_rules)
            prompt_tk = est(task_prompt)
            fb_tk = est(it.code)
            return {
                "stage": "coder",
                "system_rules": coder_rules,
                "tools": [
                    {"name": "write_file", "description": "Write authored code or script to filesystem"},
                    {"name": "read_file", "description": "Inspect existing files and dependencies"},
                    {"name": "run_bash", "description": "Run linters (ShellCheck, pytest)"},
                ],
                "lessons": injected_lessons,
                "user_prompt": task_prompt,
                "rework_feedback": it.code or "(Code synthesis pending)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 150,
                    "lessons": 0,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + 150 + prompt_tk + fb_tk,
                    "limit": 8192,
                },
            }

        elif norm_st in ("sysadmin", "dispatch", "execute"):
            exec_rules = (
                "Sandbox Execution Policy:\n"
                "- Isolated subshell execution with strict environment variables.\n"
                "- Execution timeout and memory bounds enforced.\n"
                "- Auto-cleanup of temporary scratch files on exit trap."
            )
            term_text = "\n".join(self.terminal_lines[-30:]) if self.terminal_lines else ""
            rules_tk = est(exec_rules)
            prompt_tk = est(script_code)
            fb_tk = est(term_text)
            return {
                "stage": "sysadmin",
                "system_rules": exec_rules,
                "tools": [{"name": "bash", "description": "Linux execution subshell"}],
                "lessons": [],
                "user_prompt": script_code or "(No script available to execute)",
                "rework_feedback": term_text or "(Execution pending reviewer approval)",
                "token_breakdown": {
                    "rules": rules_tk,
                    "tools": 50,
                    "lessons": 0,
                    "prompt": prompt_tk,
                    "feedback": fb_tk,
                    "total": rules_tk + 50 + prompt_tk + fb_tk,
                    "limit": 8192,
                },
            }

        return base_ctx

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Apply an incoming event dictionary to update state."""
        etype = event.get("type")
        data = event.get("data", {})
        self.run_id = event.get("run_id") or self.run_id

        if etype == "pipeline_start":
            self.task_file = data.get("task_file", "")
            self.prompt = data.get("prompt", "")
            self.tier = data.get("tier") or "8gb"
            self.models = data.get("models", {})
            self.max_retries = data.get("max_retries", 3)
            self.start_time = event.get("timestamp", "")
            self.current_stage = "start"

        elif etype == "stage_transition":
            raw_stage = data.get("stage", self.current_stage)
            st = normalize_stage(raw_stage)
            self.current_stage = st
            if st in STAGE_ORDER:
                self.selected_stage = st
            iter_num = data.get("iteration", 1)
            self.active_iteration_idx = iter_num
            self.get_iteration(iter_num)

        elif etype == "context_window":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            raw_stage = data.get("stage") or self.current_stage
            st = normalize_stage(raw_stage)
            it.stage_contexts[st] = data
            it.stage_contexts[raw_stage] = data
            if not it.context_window or st == self.selected_stage:
                it.context_window = data

        elif etype == "thinking_chunk":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            chunk = data.get("chunk", "")
            raw_stage = data.get("stage") or self.current_stage
            st = normalize_stage(raw_stage)
            if st not in STAGE_ORDER:
                st = self.selected_stage if self.selected_stage in STAGE_ORDER else "architect"
            if chunk:
                if it.stage_thinking.get(st):
                    it.stage_thinking[st] += f"\n{chunk}"
                else:
                    it.stage_thinking[st] = chunk
                it.stage_thinking[raw_stage] = it.stage_thinking[st]
                it.stage_models[st] = data.get("model", "")
                it.stage_models[raw_stage] = data.get("model", "")
                if it.thinking:
                    it.thinking += f"\n{chunk}"
                else:
                    it.thinking = chunk

        elif etype == "reasoning_chunk":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            raw_stage = data.get("stage") or self.current_stage
            st = normalize_stage(raw_stage)
            r_dict = data.get("reasoning", {})
            it.reasoning.update(r_dict)
            it.stage_reasoning[st] = r_dict
            it.stage_reasoning[raw_stage] = r_dict
            it.stage_models[st] = data.get("model", "")
            it.stage_models[raw_stage] = data.get("model", "")
            if not it.stage_thinking.get(st) and r_dict:
                parts = []
                if r_dict.get("strategy"):
                    parts.append(f"🧠 [Pillar 1: Analysis & Strategy]\n{r_dict['strategy']}")
                if r_dict.get("risks"):
                    parts.append(f"⚠️ [Pillar 2: Risks & Edge Cases]\n{r_dict['risks']}")
                if r_dict.get("solution"):
                    parts.append(f"🛠️ [Pillar 3: Solution & Decisions]\n{r_dict['solution']}")
                if r_dict.get("verification_plan") or r_dict.get("verification"):
                    parts.append(f"🧪 [Pillar 4: Verification & Testing]\n{r_dict.get('verification_plan') or r_dict.get('verification')}")
                if parts:
                    it.stage_thinking[st] = "\n\n".join(parts)
                    it.stage_thinking[raw_stage] = it.stage_thinking[st]

        elif etype == "code_synthesized":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.code = data.get("code", "")
            it.script_name = data.get("script_name")
            it.stats = data.get("stats", {})

        elif etype == "linter_result":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.linter = data
            out = data.get("output", "")
            it.stage_thinking["lint"] = f"Pre-Flight Linter (ShellCheck) Findings:\n{out}"
            it.stage_models["lint"] = "shellcheck"

        elif etype == "review_result":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.review = data
            v = data.get("verdict", "")
            c = data.get("critique", "")
            it.stage_thinking["reviewer"] = f"Reviewer Gate Evaluation:\nVerdict: {v}\n\nCritique:\n{c}"
            it.stage_thinking["review"] = it.stage_thinking["reviewer"]
            it.stage_models["reviewer"] = data.get("reviewer_model") or self.models.get("reviewer", "")
            it.stage_models["review"] = it.stage_models["reviewer"]

        elif etype == "terminal_chunk":
            text = data.get("text", "")
            if text:
                self.terminal_lines.append(text)
                cur_it = self.current_iteration()
                for key in ("dispatch", "execute"):
                    if cur_it.stage_thinking.get(key):
                        cur_it.stage_thinking[key] += f"\n{text}"
                    else:
                        cur_it.stage_thinking[key] = text

        elif etype == "pipeline_end":
            self.outcome = data.get("outcome", "unknown")
            self.duration_sec = data.get("duration_sec", 0.0)
            self.abort_reason = data.get("abort_reason", "")
            self.current_stage = "finished"
