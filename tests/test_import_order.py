import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", ["agent.program_rules", "agent.program_generator"])
def test_agent_module_imports_first_in_a_fresh_interpreter(module):
    # The service package imports agent.program_generator; an agent module that
    # imports service at load time breaks when it is the first import (#275).
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
