"""Deterministic Lesson Invariant Linter.

Audits lesson rules against repository safety guidelines, tool contracts,
and defensive engineering standards without LLM token cost.

Detects:
1. Tool contract violations (e.g. "avoid using write_file")
2. Anti-safeguard and safety bypass guidance (e.g. "always disregard safeguards", "trap - ERR")
3. Test and verification subversion (e.g. "goal of unit tests is to generate a pass, not catch errors")
4. Destructive command and privilege escalation guidance (e.g. "rm -rf /", "git push --force")
5. Path sanitization and environment isolation violations (e.g. hardcoded /home/ paths)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LessonViolation:
    lesson_id: str
    suite: str
    severity: str  # "CRITICAL" or "WARNING"
    rule_name: str
    message: str
    matched_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "suite": self.suite,
            "severity": self.severity,
            "rule_name": self.rule_name,
            "message": self.message,
            "matched_text": self.matched_text,
        }


# Invariant Rule Definitions
# Each check is a tuple of:
# (suite, rule_name, severity, regex_pattern, failure_message)

INVARIANT_CHECKS = [
    # --------------------------------------------------------------------------
    # 1. Tool Contract & Inversion Suite
    # --------------------------------------------------------------------------
    (
        "TOOL_CONTRACT",
        "avoid_standard_tool",
        "CRITICAL",
        r"(?i)\b(avoid|do\s+not\s+use|never\s+use|refrain\s+from\s+using)\s+(?:using\s+)?(?:the\s+)?(write_file|read_file|execute_task|type|view)\b",
        "Directs agents to avoid or forgo authorized pipeline tools, breaking the multi-agent execution contract.",
    ),
    (
        "TOOL_CONTRACT",
        "embed_script_avoid_tool",
        "CRITICAL",
        r"(?i)\bdirectly\s+embed\s+(?:the\s+)?(?:script|code)\s+(?:content\s+)?(?:to\s+ensure|rather\s+than|instead\s+of|avoid)\b",
        "Directs agents to embed scripts manually instead of using the standardized write_file tool.",
    ),

    # --------------------------------------------------------------------------
    # 2. Anti-Safeguard & Bypass Suite
    # --------------------------------------------------------------------------
    (
        "ANTI_SAFEGUARD",
        "disregard_safeguards",
        "CRITICAL",
        r"(?i)\b(?:always\s+)?(disregard|ignore|bypass|disable|skip|override|circumvent)\s+(?:the\s+)?(safeguards?|safety|checks?|validation|gates?|assertions?|security)\b",
        "Instructs agents to disregard or bypass safety checks, gates, or assertions.",
    ),
    (
        "ANTI_SAFEGUARD",
        "skip_security_or_linters",
        "CRITICAL",
        r"(?i)\b(skip|ignore|bypass)\s+(?:the\s+)?(security\s+gate|stride|threat\s+modeling|shellcheck|ansible-lint|linters?)\b",
        "Advises skipping mandatory security modeling, ShellCheck, or linters.",
    ),
    (
        "ANTI_SAFEGUARD",
        "disable_errexit",
        "CRITICAL",
        r"\bset\s+\+e\b",
        "Disables strict error exit (set +e), violating AGENTS.md Rule 2 defensive bash requirements.",
    ),
    (
        "ANTI_SAFEGUARD",
        "strip_error_traps",
        "CRITICAL",
        r"(?i)\btrap\s+-\s+(ERR|EXIT)\b",
        "Removes ERR or EXIT traps, preventing error diagnostics and resource cleanup.",
    ),
    (
        "ANTI_SAFEGUARD",
        "unconditional_exit_zero",
        "CRITICAL",
        r"(?i)\bexit\s+0\s+(regardless|unconditionally|always)\b",
        "Forces exit 0 regardless of execution faults, masking script failures.",
    ),

    # --------------------------------------------------------------------------
    # 3. Test & Verification Subversion Suite
    # --------------------------------------------------------------------------
    (
        "TEST_SUBVERSION",
        "test_goal_pass_not_catch_errors",
        "CRITICAL",
        r"(?i)\b(goal|purpose|objective)\s+of\s+.*tests?\s+is\s+to\s+.*(generate\s+a\s+pass|pass|succeed).*(not\s+to\s+catch\s+errors?|regardless\s+of\s+errors?)\b",
        "Advocates false-positive test passes rather than catching faults, subverting testing rigor.",
    ),
    (
        "TEST_SUBVERSION",
        "avoid_catching_errors",
        "CRITICAL",
        r"(?i)\b(do\s+not|never|avoid)\s+(catch\s+errors?|fail\s+on\s+errors?|assert\s+failure)\b",
        "Discourages catching faults or asserting failure states in verification suites.",
    ),
    (
        "TEST_SUBVERSION",
        "fake_assertions",
        "CRITICAL",
        r"(?i)\b(mock|stub|fake)\s+.*to\s+(avoid\s+failure|ensure\s+pass|always\s+succeed|guarantee\s+success)\b",
        "Advocates stubbing tests specifically to bypass failure rather than asserting functional correctness.",
    ),

    # --------------------------------------------------------------------------
    # 4. Destructive Command & Privilege Suite
    # --------------------------------------------------------------------------
    (
        "DESTRUCTIVE_COMMAND",
        "unguarded_recursive_deletion",
        "CRITICAL",
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(/|~|\$HOME|\$\{?REPO_ROOT\}?|/\*)(?:\s|$|;|/|\.)",
        "Executes unguarded recursive file deletion against root, home, or repository root.",
    ),
    (
        "DESTRUCTIVE_COMMAND",
        "excessive_permissions",
        "CRITICAL",
        r"\bchmod\s+(777|ugo\+w|a\+rwx)\b",
        "Grants world-writable permissions (chmod 777), violating security hardening standards.",
    ),
    (
        "DESTRUCTIVE_COMMAND",
        "force_git_push",
        "CRITICAL",
        r"\bgit\s+(?:push\s+.*--force|reset\s+--hard)\b",
        "Executes destructive git operations (force push or hard reset), violating branch safety.",
    ),

    # --------------------------------------------------------------------------
    # 5. Environment & Path Standards Suite
    # --------------------------------------------------------------------------
    (
        "ENVIRONMENT",
        "hardcoded_user_home",
        "WARNING",
        r"/home/[a-zA-Z0-9_\.-]+/",
        "Hardcodes user home directory (/home/<user>). Use '~', '$HOME', or relative paths per AGENTS.md Rule 3.",
    ),
    (
        "ENVIRONMENT",
        "ambient_path_assumption",
        "WARNING",
        r"(?i)\bassume\s+(?:\$PATH|path)\b|\bdo\s+not\s+resolve\s+venv\b",
        "Advises relying on ambient $PATH instead of deterministically resolving virtual environments.",
    ),
    (
        "ENVIRONMENT",
        "sleep_polling_loop",
        "WARNING",
        r"(?i)\b(poll|loop)\s+with\s+sleep\b|\bsleep\s+in\s+a\s+loop\b",
        "Advocates sleep polling loops, violating AGENTS.md Rule 4 (No Polling).",
    ),
]


def lint_lesson(lesson: Dict[str, Any]) -> List[LessonViolation]:
    """Lint a single lesson against all deterministic invariant checks.

    Parameters:
        lesson: A lesson dictionary containing at least 'rule' (and optionally 'id', 'category', 'keywords').

    Returns:
        A list of LessonViolation objects detected in the rule text.
    """
    lesson_id = lesson.get("id") or lesson.get("lesson_id") or "unknown"
    rule_text = lesson.get("rule") or lesson.get("proposed_rule") or ""

    violations: List[LessonViolation] = []
    if not rule_text:
        return violations

    for suite, rule_name, severity, pattern, failure_message in INVARIANT_CHECKS:
        match = re.search(pattern, rule_text)
        if match:
            violations.append(
                LessonViolation(
                    lesson_id=lesson_id,
                    suite=suite,
                    severity=severity,
                    rule_name=rule_name,
                    message=failure_message,
                    matched_text=match.group(0),
                )
            )

    return violations


def lint_all_lessons(lessons: List[Dict[str, Any]]) -> Dict[str, List[LessonViolation]]:
    """Lint a collection of lessons and return violations grouped by lesson ID.

    Parameters:
        lessons: List of lesson dictionaries.

    Returns:
        Dictionary mapping lesson IDs to their detected LessonViolation list.
    """
    results: Dict[str, List[LessonViolation]] = {}
    for lesson in lessons:
        violations = lint_lesson(lesson)
        if violations:
            lid = lesson.get("id") or lesson.get("lesson_id") or "unknown"
            results[lid] = violations
    return results


def format_violation_report(violations_by_lesson: Dict[str, List[LessonViolation]]) -> str:
    """Format a human-readable, colorized terminal summary of lint violations."""
    if not violations_by_lesson:
        return "✅ [Lesson Invariant Linter] All inspected lessons comply with workspace rules & specs."

    total_violations = sum(len(v) for v in violations_by_lesson.values())
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🚨 [Lesson Invariant Linter] Found {total_violations} violation(s) across {len(violations_by_lesson)} lesson(s):",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for lid, violations in violations_by_lesson.items():
        critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
        warn_count = sum(1 for v in violations if v.severity == "WARNING")
        status_tag = "🔴 CRITICAL" if critical_count > 0 else "🟡 WARNING"
        lines.append(f"\n[{status_tag}] Lesson: {lid} ({critical_count} critical, {warn_count} warning)")

        for v in violations:
            icon = "❌" if v.severity == "CRITICAL" else "⚠️ "
            lines.append(f"  {icon} [{v.suite} / {v.rule_name}]: {v.message}")
            lines.append(f"     Matched text: \"{v.matched_text}\"")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
