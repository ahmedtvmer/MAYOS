import subprocess
import sys
from pathlib import Path

import pytest

from deploy.rollback_guard import rollback_is_safe


@pytest.mark.parametrize(("running", "target"), [(26, 26), ("26", "27")])
def test_equal_or_newer_target_schema_allows_rollback(running, target):
    assert rollback_is_safe(running, target)


@pytest.mark.parametrize(
    ("running", "target"),
    [(27, 26), (None, 26), (26, None), ("26x", "26"), ("26", "not-a-version")],
)
def test_older_or_invalid_target_schema_refuses_rollback(running, target):
    assert not rollback_is_safe(running, target)


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [(("26", "26"), 0), (("27", "26"), 1), ((), 2)],
)
def test_guard_cli_exit_codes(arguments, expected_code):
    guard = Path(__file__).parents[1] / "deploy" / "rollback_guard.py"
    result = subprocess.run(
        [sys.executable, str(guard), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == expected_code


def test_deploy_script_resolves_guard_path_from_another_working_directory(tmp_path):
    script = Path(__file__).parents[1] / "deploy" / "deploy_hetzner.sh"
    result = subprocess.run(
        [str(script), "__selftest-paths"],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        text=True,
    )

    assert result.returncode == 0
    guard_path = Path(result.stdout.strip())
    assert guard_path == script.parent / "rollback_guard.py"
    assert guard_path.is_file()
