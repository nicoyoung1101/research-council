# Usage comparison — prepared, not authorized to run

This script defaults to dry-run. Preparing this harness does **not** authorize paid
measurements. Review the model configuration and manifest, then obtain explicit user
confirmation before using `--execute`. There is no model or effort fallback.

```sh
python3 scripts/compare_usage.py --config scripts/comparison.example.json --output work/comparison-plan --dry-run
# ONLY after separate confirmation, using a fresh output directory:
python3 scripts/compare_usage.py --config scripts/comparison.example.json --output work/comparison-approved --execute
```

The example preserves the currently selected Claude Opus 5.5 / Codex GPT-6.1 Sol,
both High. Edit explicit configuration only at the user's direction. Three repetitions
produce 18 workflows and at least 48 model invocations: each provider's native single
versus Council single (12 workflows), plus manual dual versus Council dual (6). Each
member gets an independent answer and one follow-up/review. There are no automatic
extra debate rounds, title, tracking or Scribe calls in this measurement.

**Scope:** native CLI protocol transports with plain user task prompts versus the real
`Council.answer` native adapter with its context/receipt protocol. The manual dual
baseline simulates copying published peer answers between two independent native
sessions. This is not GUI driving, a comparison to Claude.ai web chat, or a measurement
of the GUI's separate restricted ordinary-question path. Both sides use the same chosen
model/effort, fixture bytes, permissions, stage order and requested follow-up interval.
The baseline does not paste a member's own answer back into its native history.

Each pair runs next to its counterpart; order alternates by repetition to reduce
warm-cache order bias. Sessions/workspaces are isolated per workflow and copied from
the same hashed synthetic fixture. Requested sleep and actual per-agent follow-up gaps
are recorded: different response durations, especially sequential dual reviews, mean
actual gaps still differ. Do not treat the experiment as perfectly cache-controlled.

`report.json` contains per-call token observations, input/cache/output/thinking fields,
tool counts, failed-call usage, raw answers, effective model, timing and per-provider
sample means. Reasoning is part of output and cached input is part of total input.
Unknown observations are null, never zero. Subscription percentages are not compared.
Effective-model mismatches invalidate an unqualified efficiency comparison. Native CLI
permissions are handled interactively; non-interactive runs fail rather than auto-approve.

Quality is evaluated independently of usage: the fixture checks paired means and a
non-empty limitations field. It does not grade scientific reasoning quality. Human
review of correctness, evidence boundaries and substantive disagreement remains pending;
a cheaper but failed answer is not an efficiency win. The harness is tested with fake
clients only; no real measurement has been performed as part of this change.

Council state and fixture files are confined to the selected output directory.
The official CLIs may additionally write their ordinary native session logs in their
own standard state directories. The harness never copies or edits the user's research directory.
