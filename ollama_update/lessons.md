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
