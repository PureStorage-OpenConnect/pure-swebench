# Task card template

`card.md` is EMITTED by `prepare_task.write_card` -- this documents the shape; do not
hand-assemble one. The oracle enforces the flip; the card + `problem_statement.md`
carry what a human reviews before trusting a validated task.

```markdown
# <task_id> -- <fix commit subject>

- lang: py|web   issue: #<N>   tier: A|B|UNKNOWN
- fix: https://github.com/zulip/zulip/commit/<sha>
- f2p: <dotted backend targets or web test files, comma-joined>
- p2p: <targets, comma-joined, or "(none)">

## screen: suitability
{"verdict": "keep"|"drop", "task_type": "...", "reason": "..."}

## screen: coupling
{"verdict": "clean"|"coupled", "reason": "..."}

## screen: f2p_llm_fallback        <!-- present only when AST extraction found nothing -->
{"tests": ["..."], "reason": "..."}
```

Review checklist for a validated task:

- read `problem_statement.md` cold -- no issue/PR numbers, URLs, shas, author names,
  test names, or fix hints survived sanitization;
- the coupling verdict is sane: the hidden test asserts behavior through interfaces
  that pre-exist at base;
- f2p targets are the fix's tests; p2p targets are neighboring modules, not the fix.
