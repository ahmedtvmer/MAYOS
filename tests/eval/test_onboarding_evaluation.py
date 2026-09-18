import ast
import json
from pathlib import Path
from typing import Any
import unittest


EVAL_DIR = Path(__file__).resolve().parent
source = ast.parse((EVAL_DIR / "run_evaluation.py").read_text(encoding="utf-8"))
function = next(
    node for node in source.body
    if isinstance(node, ast.FunctionDef) and node.name == "onboarding_delta_profile"
)
namespace = {"Any": Any}
exec(compile(ast.Module(body=[function], type_ignores=[]), "run_evaluation.py", "exec"), namespace)
onboarding_delta_profile = namespace["onboarding_delta_profile"]


class OnboardingDeltaProfileTests(unittest.TestCase):
    def test_generalization_default_is_not_extraction(self):
        dataset = json.loads((EVAL_DIR / "datasets" / "generalization_cases.json").read_text(encoding="utf-8"))
        case = next(case for case in dataset["onboarding"] if case["id"] == "gen_onboard_03")
        extracted = {
            "current_goal": "building a wider back taper and beefing up forearms",
            "long_term_goal": "hitting a 200kg squat safely without injury",
            "weekly_frequency": 3,
            "training_age_years": 4.5,
        }
        profile = {"age": 25, **extracted, "rep_preference": "balanced"}
        original = dict(profile)
        self.assertEqual(onboarding_delta_profile(profile, case), extracted)
        self.assertEqual(profile, original)
        self.assertEqual(case["expected_action"], "advance")

    def test_explicit_preferences_remain_judgeable(self):
        for preference in ("balanced", "low", "high"):
            with self.subTest(preference=preference):
                profile = {"rep_preference": preference}
                case = {"step": 2, "rep_preference_provided": True}
                self.assertEqual(onboarding_delta_profile(profile, case), profile)

    def test_unknown_provenance_is_not_filtered(self):
        profile = {"rep_preference": "balanced"}
        self.assertEqual(onboarding_delta_profile(profile, {"step": 2}), profile)

    def test_unsupported_nondefault_preferences_remain_judgeable(self):
        for preference in ("low", "high", None, "invalid"):
            with self.subTest(preference=preference):
                profile = {"rep_preference": preference}
                case = {"step": 2, "rep_preference_provided": False}
                self.assertEqual(onboarding_delta_profile(profile, case), profile)

    def test_other_unstated_fields_are_not_hidden(self):
        profile = {"current_goal": "invented", "rep_preference": "balanced"}
        case = {"step": 2, "rep_preference_provided": False}
        self.assertEqual(onboarding_delta_profile(profile, case), {"current_goal": "invented"})

    def test_other_steps_keep_their_fields(self):
        for step, profile in ((1, {"proportions": "balanced"}), (3, {"stress_and_sleep": "poor"})):
            with self.subTest(step=step):
                case = {"step": step, "rep_preference_provided": False}
                self.assertEqual(onboarding_delta_profile(profile, case), profile)

    def test_missing_default_is_not_inserted(self):
        self.assertEqual(
            onboarding_delta_profile({}, {"step": 2, "rep_preference_provided": False}), {}
        )
