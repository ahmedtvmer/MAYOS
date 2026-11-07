# Catalog fixture provenance

`catalog_exercises.csv` is a source manifest, not an export of an exercise
library. `tests/catalog.py` resolves the names using only the sources below.
No ignored exercise dataset is opened by this builder.

| Manifest source | Entries | Tracked origin of id and name |
| --- | ---: | --- |
| `curation` / `curation-display` | 139 | `data/exercise_curation.csv`: 137 direct ids; 2 `duplicate_of` targets |
| `mock` | 3 | `tests/fixtures/mock_exercises.csv`: ids `1`, `5`, `10`, their existing names and tags |
| `program-import` | 1 | `tests/eval/datasets/program_import/01_english_strength_week.json`: `expected_exercise_id` and `exercise_name` for `652` |
| `substitution-test` | 1 | `tests/test_substitution_resolution.py`: existing `STIFF_LEG_DEADLIFT` id `432` and its name comment |
| `invented` | 26 | New `fixture-001` through `fixture-026`, with new names beginning `Fixture ` |
| **Total** | **170** | |

The two curation references are `360 -> 361` and `1289 -> 1281`. Their ids occur
in the tracked `duplicate_of` column; their names and muscles come from those
same explicitly related records. The loader checks the relationship rather than
guessing a name for the kept id.

The `curation-display` entry for `576` uses the tracked display name, rather
than the source name it shares with `577`. This keeps the fixture's exact
`machine chest press` lookup unambiguous. The extra mechanics-test ids `116`
and `1638` also resolve their names and muscles from tracked curation.

For curation entries, body part and target are test categories derived from
`primary_muscle`. Equipment comes from a word in the tracked source name or the
tracked machine `load_type`. A name without an equipment word uses an invented
`body weight` default. Explicit equipment overrides for `818` and `248` are
invented test values. The program-import and substitution-test entries also have
explicit invented muscle/equipment values in the manifest. Invented entries have
explicit invented muscle/equipment values; the same category mapping is applied.

Only mock entries reuse existing tracked fixture tags. Every generated media
path and instruction is invented. The builder does not copy instructions,
secondary muscles or media from the name sources.

The manifest's `primary_action` values are invented test metadata. Twenty-four
invented entries have complete action/muscle signatures; the two scapular warmup
entries intentionally have none. `write_exercise_curation` combines those records
with tracked curation in a temporary file. Catalog copies reopen with that file,
and the curation fixture preserves these support records while replacing the
real-row curation supplied by a test. This matters because generation selects
Staples and signature matches, not arbitrary uncurated name matches. The added
bodyweight variants cover presses, curls, triceps extensions, rows, calves and
adductors without inventing licensed ids. No bodyweight forearm, side-delt,
rear-delt, shrug or hamstring-hinge rows were added.

`fixture-025` (Fixture Zinnia incline press) and `fixture-026` (Fixture Zephyr
pullover) are wholly invented bodyweight rows. Their action/muscle pairs are
Shoulder Horizontal Adduction / Upper Chest and Shoulder Extension / Lats,
respectively, so each fills its own direct slot signature. The incline row's
name avoids the slot's fly and push-up exclusions; the pullover avoids its
stretch exclusion. Neither signature matches flat press, chest fly, horizontal
row or vertical pull. Commercial gym excludes their equipment, and Home gym's
existing incline-press and pullover Staples keep priority over them. These rows
also satisfy the blueprint test's all-slot check, which cannot use a fallback
that has only signature matches and no Staple.

Non-invented manifest entries leave `name` empty so the builder must read it from
the cited source. Unsupported source labels, invented numeric ids, mismatched
source ids and invalid curation duplicate references raise errors. Source edits
therefore cannot silently fall back to a remembered library row.
