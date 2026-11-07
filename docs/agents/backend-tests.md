# Backend tests from a clean clone

Run the suite from the repository root with Python 3.12. Do not copy a developer
`db/catalog.db`, ledgers, exercise dumps or USDA downloads into the checkout.
The normal test catalog is built once per process from
`tests/fixtures/catalog_exercises.csv`, the tracked MAYOS exercise curation and
authored exercises, and the synthetic food/portion fixtures from the image smoke
test (#587). Each test gets an isolated copy. Default test reseeding uses those
same synthetic inputs; explicit seed paths in a test are preserved.

The exercise CSV is a provenance manifest. Retained ids and names come only from
tracked curation, fixtures or a hard-coded test; other ids and names use the
`fixture-` namespace. Body part, target and equipment are derived from tracked
metadata or explicitly invented. Instructions and media paths are invented.
See [the source inventory](../../tests/fixtures/catalog_exercises.sources.md) for
the 170-entry breakdown and derivation rules. Keep real datasets git-ignored;
never consult them to add a test row.

## Production API image on the server

Use a disposable clean checkout and the same `mayos-api:<tag>` image being
verified. The checkout supplies test and source files omitted by the production
build context, including Flutter source and deployment documentation. The image
supplies production dependencies and cached ONNX models. Install only pytest in
the disposable container; no Git, compiler or other development tools are needed
for the normal backend suite.

```sh
tag=YOUR_IMAGE_TAG
docker run --rm --ulimit nofile=1024:1024 \
  --env TESTING=1 --env SKIP_LLM_LOAD=true --env HF_HUB_OFFLINE=1 \
  --mount "type=bind,src=$PWD,dst=/workspace" --workdir /workspace \
  --entrypoint /bin/sh "mayos-api:$tag" -c \
  'uv pip install --system "pytest>=8,<9" && python -m pytest -ra --durations=30 tests'
```

The mount is writable for logs and pytest caches. Do not mount production data
or pass production secrets. Installing pytest requires package-index access (or
an equivalent preloaded wheel). This changes only the disposable container.
The `1024` limit is deliberate: increasing it would hide the regression in #580.

## Clean Linux host or CI runner

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt 'pytest>=8,<9'
.venv/bin/python -c 'from core.embeddings import download_model_files, download_arabic_model_files; download_model_files(); download_arabic_model_files()'
ulimit -n 1024
TESTING=1 SKIP_LLM_LOAD=true HF_HUB_OFFLINE=1 \
  .venv/bin/python -m pytest -ra --durations=30 tests
```

The initial model download needs network access. Keep the resulting Hugging Face
cache for subsequent offline runs. The suite uses scripted chat models; the
embedding models still run locally. Test environment pins in `tests/conftest.py`
disable hosted chat credentials, analytics delivery and outbound SMTP.

## Resource regression and splitting runs

`tests/test_fixture_resources.py` runs 32 separate pytest cases, then compares
Linux `/proc/self/fd` counts after function-fixture teardown. It covers both the
convenience ledger and explicit handles, plus additional stores. It does not
force garbage collection. The shared lifecycle fixture closes ledger, catalog
and deletion-journal connections after each test, including partially
initialized stores.

Measure on the target server with `--durations=30`; no timings were measured on
the implementation PC. Start with these large matrix/evaluation files when
splitting the slowest work: `tests/test_program_blueprints.py`,
`tests/test_coach_pattern_rubric.py`, `tests/test_program_signatures.py`,
`tests/test_model_metering.py`, `tests/test_eval_gate.py`, and
`tests/eval/test_program_import_evaluation.py` plus
`tests/eval/test_program_import_text_evaluation.py`. These are split candidates,
not a measured ranking. For example, pass this disjoint partition to pytest
inside the container above:

```sh
python -m pytest -ra --durations=30 tests/test_program_blueprints.py tests/test_coach_pattern_rubric.py tests/test_program_signatures.py
python -m pytest -ra --durations=30 tests --ignore=tests/test_program_blueprints.py --ignore=tests/test_coach_pattern_rubric.py --ignore=tests/test_program_signatures.py
```

Each invocation builds its own synthetic seed. Run the full suite at least once
under the 1,024 limit as well, so a split cannot conceal cumulative resource use.

## Expected skips

Always keep `-ra` so missing optional inputs are visible in the report.

| Missing prerequisite | Tests skipped |
| --- | --- |
| `git` executable or checkout `.git` metadata | `test_deploy_script_attributes.py` and `test_no_ovh_references.py` Git-index assertions |
| `git` executable | Server-pull integration cases using `_pull_fixture` in `test_deploy_remote_bash.py` |
| `data/processed_exercises.csv` | Exact full-library snapshots in `test_coach_pattern_rubric.py` and `test_program_signatures.py`, and the full curation-id coverage check in `test_exercise_library_names.py` |
| `data/processed_exercises.csv` | Exact bodyweight ham-curl id coverage, home/bodyweight staple rubric cases, home/bodyweight warmup id cases, and the two Kelso look-alike checks; their missing names/relationships cannot be reconstructed from permitted tracked sources |
| `data/processed_exercises.csv` | All three equipment cases of `test_no_staple_suggestions_follow_replace_ranking_and_access`, which assert the complete library's exact ranking and absence of alternatives |
| `data/food_library.csv` or `data/food_portions.csv` | Real USDA-row filtering coverage in `test_food_library_builder.py` and owner-draft USDA coverage in `test_food_curation_draft.py` |
| Linux `/proc/self/fd` | The descriptor sample in `test_fixture_resources.py` |

Existing browser/tool/media integration tests may also skip when their optional
Node tooling or local media directories are absent; their own reasons appear in
the summary. Assertion failures and malformed available data remain failures.
The standalone `scripts/dataset_handler.py` reads raw `data/exercises.csv` and
`data/exercises.json`; pytest does not import that dataset-building script.
