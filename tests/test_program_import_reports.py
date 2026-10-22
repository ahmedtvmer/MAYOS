"""Committed Program import evaluation reports stay bound to the current prompts.

Kept out of tests/test_program_import.py, which is the evaluation privacy suite:
re-recording a report after a prompt change must not depend on the stale report.
"""

import json
from pathlib import Path


def test_committed_sheet_report_and_prompt_hash_remain_valid():
    from service import program_import_ai

    report = json.loads((Path(__file__).parents[1] / "reports/program_import_eval.json").read_text(encoding="utf-8"))
    assert program_import_ai.prompt_version_hash() == "90613fbabe789c229d42bfb005c62219e214f7711647a53e45704aef0b02d216"
    assert program_import_ai.text_prompt_version_hash() == "5818fa6c815960187fa6bd65f542e1a8d28bdeae831bb1b53c1f3fccfedbb30a"
    assert program_import_ai.validate_report(report) == (True, [])
    text_report = json.loads((Path(__file__).parents[1] / "reports/program_import_text_eval.json").read_text(encoding="utf-8"))
    assert program_import_ai.validate_report(text_report) == (True, [])
