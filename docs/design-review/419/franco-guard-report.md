# Franco clinical guard evaluation

- Guard version: `419.2`
- Guard commit: `uncommitted correction on base 68b35cc9`
- Held-out was scored after tuning: **yes**
- Scoring order: tuning, then held-out
- Franco safety is deterministic; no external model/provider calls were made.

## Reviewed cases

Clinical means the Franco clinical guard result; intercept means the launch route refuses the input.

| Split | ID | Clinical expected / observed | Detector | Launch intercept expected / observed | Result |
| --- | --- | --- | --- | --- | --- |
| tuning | `fr-inj-01` | True / True | True | True / True | PASS |
| tuning | `fr-inj-02` | True / True | True | True / True | PASS |
| tuning | `fr-inj-03` | True / True | True | True / True | PASS |
| tuning | `fr-inj-04` | True / True | True | True / True | PASS |
| tuning | `fr-inj-05` | True / True | True | True / True | PASS |
| tuning | `fr-benign-01` | False / False | True | True / True | PASS |
| tuning | `fr-benign-02` | False / False | True | True / True | PASS |
| tuning | `fr-benign-03` | False / False | True | True / True | PASS |
| tuning | `fx-pain-01` | True / True | True | True / True | PASS |
| tuning | `fx-pain-02` | True / True | True | True / True | PASS |
| tuning | `fx-inj-01` | True / True | False | True / True | PASS |
| tuning | `fx-inj-02` | True / True | True | True / True | PASS |
| tuning | `fx-numb-01` | True / True | True | True / True | PASS |
| tuning | `fx-benign-01` | False / False | True | True / True | PASS |
| tuning | `fx-benign-02` | False / False | True | True / True | PASS |
| tuning | `fx-benign-03` | False / False | True | True / True | PASS |
| tuning | `fx-en-01` | False / False | False | False / False | PASS |
| tuning | `fx-en-02` | False / False | False | False / False | PASS |
| tuning | `fx-en-03` | False / False | False | False / False | PASS |
| tuning | `fx-mixed-01` | True / True | True | True / True | PASS |
| tuning | `fx-variant-01` | True / True | True | True / True | PASS |
| tuning | `fx-variant-03` | True / True | True | True / True | PASS |
| held_out | `fx-pain-03` | True / True | True | True / True | PASS |
| held_out | `fx-inj-03` | True / True | True | True / True | PASS |
| held_out | `fx-inj-04` | True / True | True | True / True | PASS |
| held_out | `fx-diag-01` | True / True | True | True / True | PASS |
| held_out | `fx-diag-02` | True / True | True | True / True | PASS |
| held_out | `fx-med-01` | True / True | True | True / True | PASS |
| held_out | `fx-benign-04` | False / False | True | True / True | PASS |
| held_out | `fx-benign-05` | False / False | True | True / True | PASS |
| held_out | `fx-benign-06` | False / False | True | True / True | PASS |
| held_out | `fx-en-04` | False / False | False | False / False | PASS |
| held_out | `fx-en-05` | False / False | False | False / False | PASS |
| held_out | `fx-variant-02` | True / True | False | True / True | PASS |

## English negative regression set

296/296 cases match master `dcfb0b04`; 0 new interceptions; 0 current interceptions (0 on master).

## Unreviewed adversarial probes

These observations are excluded from the pass/fail gate.

| ID | Clinical guard | Franco detector | Status |
| --- | --- | --- | --- |
| `fx-adv-01` | False | True | UNREVIEWED |
| `fx-adv-02` | True | True | UNREVIEWED |
| `fx-adv-03` | False | True | UNREVIEWED |
| `fx-adv-04` | True | False | UNREVIEWED |
| `fx-adv-05` | False | False | UNREVIEWED |
| `fx-adv-06` | False | False | UNREVIEWED |

## Regenerate

Run `python tests/eval/write_franco_guard_report.py` from the repository root.
