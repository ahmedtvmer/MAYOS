# Paired trial usage workload (#262)

Status: **owner reviewed by Thomas on 2026-10-13**.

The synthetic Arabic prompts and the provisional ordinary-day profile are in
[`tests/eval/datasets/trial_usage_workloads_262.json`](../../tests/eval/datasets/trial_usage_workloads_262.json).
Each pair uses the same task and seeded facts. The fixture covers short
questions, long conversation history, Arabic/English mixing, a Program action,
and Coach analysis. Its Arabic wording has not been owner reviewed.

The ordinary-day profile is a reproducible measurement assumption only. It is
not a launch workload forecast or an accepted request count. The proposed
Free 5 / Pro 30 request counts remain unaccepted. Arabic quality and privacy
remain separate gates and are not decided by token usage.

Do not change the fixture's review status or record a reviewer until the owner
has reviewed the Arabic wording and workload assumptions.
