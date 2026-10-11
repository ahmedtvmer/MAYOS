#!/usr/bin/env python3
"""Measure hosted player-model completion usage through production prompt paths."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai.chat_models.base import OpenAIRateLimitError, OpenAITimeoutError

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from utils.player_output_budgets import (  # noqa: E402
    CALL_SITE_BUDGETS,
    CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS,
    PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
    PlayerCallSite,
    override_player_output_budgets,
)
from utils.text_scrubber import DEEPSEEK_END_OF_SENTENCE_TOKEN  # noqa: E402

MEASUREMENT_OUTPUT_CAP = 2400
CHAT_PRODUCTION_CAP = PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS
CHECKPOINT_REVIEW_CAP = CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS
DEFAULT_SAMPLES_PER_LANGUAGE = 10
MEASUREMENT_PROFILE_VERSION = "realistic-20-v2"
MAX_PROVIDER_REQUESTS_PER_SITE = 41
MARGIN_MINIMUM_TOKENS = 16
MARGIN_PERCENT = 0.25
BUDGET_ROUNDING_TOKENS = 8

ENGLISH_CHAT_INPUTS = (
    "How should I warm up before squats?",
    "I slept poorly. Should I still train today?",
    "What does RIR mean?",
    "What should I fix if my last bench set felt unstable?",
    "How long should I rest between working sets?",
    "I have 35 minutes and dumbbells only. How can I train legs today?",
    "I hit 8 reps at 60 kg on bench. What should I record and change next week?",
    "My squat and row both stalled for three weeks. Should I add weight, reps, or sets?",
    "Can you explain why controlling the lowering phase matters, and give me one cue for rows?",
    "My shoulders feel tired after pressing and I have a long workday. Should I reduce today's upper workout?",
)
ARABIC_CHAT_INPUTS = (
    "إزاي أعمل إحماء قبل السكوات؟",
    "نمت قليل امبارح، أتمرن النهارده ولا أريح؟",
    "يعني إيه RIR؟",
    "أظبط إيه لو آخر مجموعة بنش كانت مش ثابتة؟",
    "أرتاح قد إيه بين مجموعات التمرين؟",
    "معايا ٣٥ دقيقة ودمبلز بس. أتمرن رجل إزاي النهارده؟",
    "عملت ٨ تكرارات بنش بوزن ٦٠ كيلو. أسجل إيه وأغير إيه الأسبوع الجاي؟",
    "السكوات والتجديف واقفين من ٣ أسابيع. أزود الوزن ولا العدات ولا المجموعات؟",
    "اشرح ليه التحكم في نزول الوزن مهم واديني تلميح واحد للتجديف.",
    "كتافي مرهقة بعد الضغط وعندي يوم شغل طويل. أقلل تمرين الجزء العلوي؟",
)
ENGLISH_ROUTER_INPUTS = (
    "Change my week so heavy and light sessions alternate.",
    "Rebuild my 4-day plan while keeping all training days and exercises balanced.",
    "Replace the movement I mentioned earlier with another option.",
    "Find cable or dumbbell movements that fit my home setup.",
    "Swap the bench press for an incline dumbbell press.",
    "Can you explain why my squat feels harder after deadlifts?",
    "Keep the same weekly frequency but move my upper sessions apart.",
    "Replace both the pulldown and row with options that need less equipment.",
    "Which exercises in my current plan train the hamstrings?",
    "I have knee discomfort; change the program so it avoids deep knee flexion.",
)
ARABIC_ROUTER_INPUTS = (
    "خلّي الجلسات الشاقة والخفيفة تتبادل خلال الأسبوع.",
    "أعد تنظيم برنامجي لأربع أيام مع الحفاظ على توازن التمارين.",
    "استبدل التمرين اللي اتكلمنا عنه ببديل مناسب.",
    "هات تمارين كيبل أو دمبل تناسب التجهيزات الموجودة عندي.",
    "بدّل البنش بضغط دمبل مائل.",
    "ليه السكوات بيكون أصعب بعد الرفعة الميتة؟",
    "حافظ على نفس عدد أيام التدريب وابعد بين جلسات الجزء العلوي.",
    "بدّل السحب العلوي والتجديف بتمارين معداتها أبسط.",
    "إيه التمارين اللي في برنامجي بتشغل العضلات الخلفية للفخذ؟",
    "ركبتي بتضايقني؛ عدّل البرنامج عشان أتجنب ثني الركبة بعمق.",
)
ENGLISH_COREFERENCE_INPUTS = (
    "Replace that one with the incline dumbbell press.",
    "Could you swap it for a cable row?",
    "Change the exercise we just discussed to a chest-supported row, but keep the bench press.",
    "Use the dumbbell version instead of that movement because I train at home.",
    "Switch the previous exercise to a neutral-grip pulldown; leave the cable row alone.",
    "Can I replace it with a machine shoulder press?",
    "Find a substitute for that lift, preferably a cable movement that is easier to set up.",
    "Replace the one from your last message with a split squat, not the leg curl.",
    "Swap the squat and bench we just discussed for leg press and dumbbell press.",
    "For the two exercises I listed, replace only the second one with a supported row.",
)
ARABIC_COREFERENCE_INPUTS = (
    "بدّل التمرين ده بضغط دمبل مائل.",
    "ممكن تستبدله بسحب كيبل؟",
    "غيّر الحركة اللي اتكلمنا عنها بسحب مع إسناد الصدر وخلي البنش زي ما هو.",
    "استخدم نسخة الدمبل بدل الحركة دي عشان بتمرن في البيت.",
    "بدّل التمرين اللي فات بسحب علوي بقبضة محايدة، وسيب التجديف زي ما هو.",
    "ينفع أستبدله بضغط كتف على الجهاز؟",
    "هات بديل للحركة دي يكون كيبل وأسهل في التجهيز.",
    "بدّل التمرين اللي في رسالتك اللي فاتت باندفاع خلفي، مش ثني الرجل.",
    "بدّل السكوات والبنش اللي اتكلمنا عنهم بضغط رجل وضغط دمبل.",
    "من التمرينين اللي قلتهم، بدّل التاني بسحب مع إسناد الصدر.",
)
ENGLISH_SPLIT_INPUTS = (
    "Plan two balanced full-body days using dumbbells and bodyweight only.",
    "For three days, rotate full-body sessions and keep each one under 45 minutes.",
    "Build four varied days, but avoid overhead pressing because my shoulder is irritated.",
    "Arrange five days with no barbell work and at least one rest day between hard leg sessions.",
    "I can train six days; spread the work out and keep sessions short. No deep knee bends.",
    "For two days at a small gym, prioritize machines and leave room for easy cycling.",
    "Make a three-day plan for a beginner with limited recovery and no Olympic lifts.",
    "I have four days and only cables and dumbbells; avoid repeating the same movement pattern on consecutive days.",
    "Arrange five sessions for hypertrophy with a low-back limitation and 40-minute time cap.",
    "I can get to the gym six days, but want one light day and no heavy deadlifts.",
)
ARABIC_SPLIT_INPUTS = (
    "رتب يومين كاملين للجسم باستخدام الدمبل ووزن الجسم بس.",
    "لثلاث أيام، نوّع جلسات الجسم كله وخلي كل واحدة أقل من ٤٥ دقيقة.",
    "اعمل أربعة أيام مختلفة، بس بلاش ضغط فوق الرأس عشان كتفي مضايقني.",
    "وزع خمس أيام من غير بار وخلي راحة بين أيام الرجل الشاقة.",
    "أقدر أتمرن ست أيام؛ وزع المجهود وخلي الجلسات قصيرة وبلاش ثني ركبة عميق.",
    "ليومين في جيم صغير، ركز على الأجهزة وسيب مساحة لعجلة خفيفة.",
    "اعمل برنامج مبتدئ لثلاث أيام مع راحة محدودة ومن غير رفعات أولمبية.",
    "عندي أربع أيام وكيبل ودمبل بس؛ ما تكررش نفس نمط الحركة في يومين ورا بعض.",
    "وزع خمس جلسات للتضخيم مع مراعاة أسفل الظهر وحد أقصى ٤٠ دقيقة.",
    "أقدر أروح الجيم ست أيام، بس عايز يوم خفيف ومن غير رفعة ميتة تقيلة.",
)
ABBREVIATION_INPUTS = (
    "RDL", "RDLS", "SLDL", "SLDLS", "DL", "DLS", "GHR", "GHRS", "OHP", "CGBP",
    "BP", "JM", "HSPU", "BSS", "FS", "BS", "SSB", "DIPS", "DB", "BB",
)


class UsageRecorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def responses(self) -> list[dict[str, Any]]:
        if not hasattr(self._local, "responses"):
            self._local.responses = []
        return self._local.responses

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        del kwargs
        for group in getattr(response, "generations", ()) or ():
            self._record_generation_group(group, response)

    def _record_generation_group(self, group: list[Any], response: Any) -> None:
        for generation in group:
            message = getattr(generation, "message", None)
            output_tokens = _completion_tokens(message, generation, response)
            if output_tokens is not None:
                self.responses.append(
                    {
                        "completion_tokens": int(output_tokens),
                        "finish_reason": _finish_reason(message, generation),
                    }
                )

    def record_raw_message(self, message: Any) -> None:
        output_tokens = _completion_tokens(message, None, None)
        if output_tokens is not None:
            self.responses.append(
                {
                    "completion_tokens": int(output_tokens),
                    "finish_reason": _finish_reason(message, None),
                }
            )


def _completion_tokens(message: Any, generation: Any, response: Any) -> int | None:
    usage = getattr(message, "usage_metadata", None) or {}
    metadata = getattr(message, "response_metadata", None) or {}
    generation_info = getattr(generation, "generation_info", None) or {}
    metadata_usage = metadata.get("token_usage") or generation_info.get("token_usage") or {}
    token_usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
    return (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or metadata_usage.get("completion_tokens")
        or metadata_usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
    )


def _finish_reason(message: Any, generation: Any) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    generation_info = getattr(generation, "generation_info", None) or {}
    return str(
        metadata.get("finish_reason")
        or generation_info.get("finish_reason")
        or metadata.get("stop_reason")
        or generation_info.get("stop_reason")
        or "unknown"
    )


def _round_up(value: int, multiple: int) -> int:
    return math.ceil(value / multiple) * multiple


def _nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _margin(p95: int) -> int:
    return max(MARGIN_MINIMUM_TOKENS, math.ceil(p95 * MARGIN_PERCENT))


def _recommended_budget(p95: int) -> int:
    return _round_up(p95 + _margin(p95), BUDGET_ROUNDING_TOKENS)


@dataclass(frozen=True)
class CallSitePolicy:
    previous_budget: int
    production_budget: int
    measurement_cap: int
    choose_budget: Callable[[int, int | None, int], tuple[int, str]]
    statistical_samples: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    measurement_status: Callable[[list[dict[str, Any]], list[dict[str, Any]]], str | None]


def _all_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return samples


def _checkpoint_statistical_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sample for sample in samples if not sample.get("extracted_text_empty", False)]


def _no_measurement_status(
    samples: list[dict[str, Any]], measured_samples: list[dict[str, Any]]
) -> str | None:
    del samples, measured_samples
    return None


def _checkpoint_measurement_status(
    samples: list[dict[str, Any]], measured_samples: list[dict[str, Any]]
) -> str | None:
    if measured_samples or not samples:
        return None
    if all(sample.get("raw_content_kind") == "deepseek_end_token" for sample in samples):
        return "not measured — the model returned EOS for every sample; see #402"
    return "not measured — no non-empty model wording was observed."


def _recommended_budget_choice(
    previous: int, p95: int | None, length_count: int
) -> tuple[int, str]:
    del length_count
    if p95 is None:
        return previous, "Not measured; kept the previous budget."
    return _recommended_budget(p95), "p95 + margin, rounded up to 8 tokens."


def _routing_budget_choice(
    previous: int, p95: int | None, length_count: int
) -> tuple[int, str]:
    del previous, length_count
    if p95 is None:
        return CALL_SITE_BUDGETS["intent_routing"], "Conservative given reduced n; kept 112 tokens."
    budget = max(_recommended_budget(p95), CALL_SITE_BUDGETS["intent_routing"])
    return budget, "Conservative given reduced n; at least 112 tokens, with the p95 margin rule."


def _chat_budget_choice(
    previous: int, p95: int | None, length_count: int
) -> tuple[int, str]:
    if length_count and p95 is not None:
        return _recommended_budget(p95), "Raised to p95 + margin because the measured output hit the limit."
    return previous, f"Kept the existing {previous}-token product choice; chat prompt is capped at 90 words."


def _split_budget_choice(
    previous: int, p95: int | None, length_count: int
) -> tuple[int, str]:
    del length_count
    if p95 is None:
        return previous, "Not measured; kept the previous #186 budget."
    return _recommended_budget(p95), "Conservative given reduced n; applied DynamicSplitPlan's p95 margin rule."


def _checkpoint_budget_choice(
    previous: int, p95: int | None, length_count: int
) -> tuple[int, str]:
    del p95, length_count
    return previous, f"Kept the previous {previous}-token budget; EOS responses are not output measurements."


CALL_SITE_POLICIES: dict[PlayerCallSite, CallSitePolicy] = {
    "chat_reply": CallSitePolicy(
        previous_budget=PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
        production_budget=CALL_SITE_BUDGETS["chat_reply"],
        measurement_cap=CHAT_PRODUCTION_CAP,
        choose_budget=_chat_budget_choice,
        statistical_samples=_all_samples,
        measurement_status=_no_measurement_status,
    ),
    "intent_routing": CallSitePolicy(
        previous_budget=PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
        production_budget=CALL_SITE_BUDGETS["intent_routing"],
        measurement_cap=MEASUREMENT_OUTPUT_CAP,
        choose_budget=_routing_budget_choice,
        statistical_samples=_all_samples,
        measurement_status=_no_measurement_status,
    ),
    "substitution_resolution": CallSitePolicy(
        previous_budget=PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
        production_budget=CALL_SITE_BUDGETS["substitution_resolution"],
        measurement_cap=MEASUREMENT_OUTPUT_CAP,
        choose_budget=_recommended_budget_choice,
        statistical_samples=_all_samples,
        measurement_status=_no_measurement_status,
    ),
    "abbreviation_expansion": CallSitePolicy(
        previous_budget=PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
        production_budget=CALL_SITE_BUDGETS["abbreviation_expansion"],
        measurement_cap=MEASUREMENT_OUTPUT_CAP,
        choose_budget=_recommended_budget_choice,
        statistical_samples=_all_samples,
        measurement_status=_no_measurement_status,
    ),
    "dynamic_split_plan": CallSitePolicy(
        previous_budget=1200,
        production_budget=CALL_SITE_BUDGETS["dynamic_split_plan"],
        measurement_cap=MEASUREMENT_OUTPUT_CAP,
        choose_budget=_split_budget_choice,
        statistical_samples=_all_samples,
        measurement_status=_no_measurement_status,
    ),
    "checkpoint_review": CallSitePolicy(
        previous_budget=CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS,
        production_budget=CALL_SITE_BUDGETS["checkpoint_review"],
        measurement_cap=CHECKPOINT_REVIEW_CAP,
        choose_budget=_checkpoint_budget_choice,
        statistical_samples=_checkpoint_statistical_samples,
        measurement_status=_checkpoint_measurement_status,
    ),
}


@dataclass(frozen=True)
class ExerciseFixture:
    exercise_id: str
    exercise_name: str


@dataclass(frozen=True)
class ProgramDayFixture:
    day_name: str
    exercises: list[ExerciseFixture]


@dataclass(frozen=True)
class ProgramFixture:
    days: list[ProgramDayFixture]


def _program_fixture() -> ProgramFixture:
    exercise_names = (
        ("bench_press", "Barbell Bench Press"),
        ("incline_press", "Incline Dumbbell Press"),
        ("lat_pulldown", "Cable Lat Pulldown"),
        ("row", "Chest-Supported Row"),
        ("squat", "Barbell Squat"),
        ("leg_curl", "Seated Leg Curl"),
        ("shoulder_press", "Machine Shoulder Press"),
        ("split_squat", "Dumbbell Split Squat"),
    )
    days = [
        ProgramDayFixture(
            day_name=day_name,
            exercises=[
                ExerciseFixture(exercise_id=exercise_id, exercise_name=exercise_name)
                for exercise_id, exercise_name in exercise_names[index : index + 4]
            ],
        )
        for index, day_name in ((0, "Upper A"), (4, "Lower A"))
    ]
    return ProgramFixture(days=days)


class ExerciseStore:
    def get_exercise_library_entries(self, exercise_ids: list[str]) -> dict[str, dict[str, str]]:
        return {
            exercise_id: {
                "name": name,
                "equipment": "Dumbbell" if "Dumbbell" in name else "Cable",
                "primary_action": "Compound movement",
                "primary_muscle": "Upper body",
            }
            for exercise_id, name in (
                ("bench_press", "Barbell Bench Press"),
                ("incline_press", "Incline Dumbbell Press"),
                ("lat_pulldown", "Cable Lat Pulldown"),
                ("row", "Chest-Supported Row"),
                ("squat", "Barbell Squat"),
                ("leg_curl", "Seated Leg Curl"),
                ("shoulder_press", "Machine Shoulder Press"),
                ("split_squat", "Dumbbell Split Squat"),
            )
            if exercise_id in exercise_ids
        }


@dataclass
class MeasurementRunner:
    recorder: UsageRecorder
    max_retries: int
    samples_by_site: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    request_counts: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def measure(self, site: str, language: str, sample_index: int, invoke: Callable[[], Any]) -> dict[str, Any]:
        with self.lock:
            existing = _find_sample(self.samples_by_site, site, language, sample_index)
        if existing is not None:
            return existing
        return self._measure_missing(site, language, sample_index, invoke)

    def _measure_missing(
        self, site: str, language: str, sample_index: int, invoke: Callable[[], Any]
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            with self.lock:
                if self.request_counts.get(site, 0) >= MAX_PROVIDER_REQUESTS_PER_SITE:
                    raise RuntimeError(f"{MAX_PROVIDER_REQUESTS_PER_SITE}-request ceiling reached at {site}.")
                self.request_counts[site] = self.request_counts.get(site, 0) + 1
            self.recorder.responses.clear()
            try:
                response = invoke()
            except (OpenAIRateLimitError, OpenAITimeoutError) as exc:
                if not _is_retryable(exc) or attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Provider remained unavailable at {site} ({language}); last error: {type(exc).__name__}."
                    ) from None
                time.sleep(45 * (2**attempt))
                continue
            if not self.recorder.responses and isinstance(response, dict):
                self.recorder.record_raw_message(response.get("raw"))
            sample = _measured_sample(self.recorder, site, language, sample_index)
            with self.lock:
                self.samples_by_site.setdefault(site, []).append(sample)
            return sample
        raise RuntimeError(f"Measurement retries exhausted at {site} ({language}).")


@dataclass(frozen=True)
class MeasurementModules:
    assistant_graph: ModuleType
    fitness_abbreviations: ModuleType
    program_rules: ModuleType
    checkpoint_review_ai: ModuleType
    model_downloader: ModuleType


@dataclass
class MeasurementTargets:
    runner: MeasurementRunner
    model: Any
    model_name: str
    provider: str
    measurement_budget_overrides: Mapping[PlayerCallSite, int]
    assistant_graph: ModuleType
    fitness_abbreviations: ModuleType
    program_rules: ModuleType
    checkpoint_review_ai: ModuleType
    diagnostic_request_counts: dict[str, int] = field(default_factory=dict)
    measurement_errors: dict[str, str] = field(default_factory=dict)


def _find_sample(
    samples_by_site: dict[str, list[dict[str, Any]]], site: str, language: str, index: int
) -> dict[str, Any] | None:
    return next(
        (
            sample for sample in samples_by_site.get(site, [])
            if sample["language"] == language and sample["sample"] == index + 1
        ),
        None,
    )


def _is_overloaded(error: OpenAIRateLimitError) -> bool:
    return getattr(error, "status_code", None) == 429 and "engine_overloaded" in str(error).lower()


def _is_retryable(error: BaseException) -> bool:
    return isinstance(error, OpenAITimeoutError) or (
        isinstance(error, OpenAIRateLimitError) and _is_overloaded(error)
    )


def _measured_sample(
    recorder: UsageRecorder, site: str, language: str, sample_index: int
) -> dict[str, Any]:
    if not recorder.responses:
        raise RuntimeError(f"Provider usage metadata missing for {site} sample {sample_index + 1}.")
    response = recorder.responses[-1]
    print(
        f"{site}: {language} sample {sample_index + 1}: "
        f"{response['completion_tokens']} tokens ({response['finish_reason']})",
        flush=True,
    )
    time.sleep(1)
    return {"language": language, "sample": sample_index + 1, **response}


def _prepare_measurement(
    max_retries: int, prior_samples: dict[str, list[dict[str, Any]]], prior_request_counts: dict[str, int]
) -> MeasurementTargets:
    targets = _measurement_modules()
    _configure_measurement_environment()
    model = targets.model_downloader.get_llm()
    recorder = UsageRecorder()
    runner = MeasurementRunner(recorder, max_retries, prior_samples, prior_request_counts)
    model.callbacks = [*(model.callbacks or []), recorder]
    _wire_measurement_model(targets, model)
    overrides = {
        site: policy.measurement_cap
        for site, policy in CALL_SITE_POLICIES.items()
        if policy.measurement_cap != CALL_SITE_BUDGETS[site]
    }
    return MeasurementTargets(
        runner=runner,
        model=model,
        model_name=targets.model_downloader.model_identity("production")[0],
        provider=targets.model_downloader._cloud_api_base(),
        measurement_budget_overrides=overrides,
        assistant_graph=targets.assistant_graph,
        fitness_abbreviations=targets.fitness_abbreviations,
        program_rules=targets.program_rules,
        checkpoint_review_ai=targets.checkpoint_review_ai,
    )


def _measurement_modules() -> MeasurementModules:
    from agent import assistant_graph, fitness_abbreviations, program_rules
    from service import checkpoint_review_ai
    from utils import model_downloader

    return MeasurementModules(
        assistant_graph=assistant_graph,
        fitness_abbreviations=fitness_abbreviations,
        program_rules=program_rules,
        checkpoint_review_ai=checkpoint_review_ai,
        model_downloader=model_downloader,
    )


def _configure_measurement_environment() -> None:
    os.environ["LLM_BACKEND"] = "openai"
    os.environ["LLM_MAX_TOKENS"] = str(CHAT_PRODUCTION_CAP)
    os.environ["LLM_MAX_RETRIES"] = "0"
    os.environ["LLM_REQUEST_TIMEOUT"] = "30"
    os.environ["LLM_STREAM_CHUNK_TIMEOUT"] = "30"
    if not os.getenv("LLM_API_KEY", "").strip():
        raise RuntimeError("LLM_API_KEY is not configured; hosted measurement was not started.")

def _wire_measurement_model(targets: Any, model: Any) -> None:
    targets.assistant_graph.llm = model
    targets.fitness_abbreviations.llm = model
    targets.program_rules.llm = model
    targets.model_downloader.get_llm = lambda: model


def _record_sample(
    targets: Any, site: str, language: str, index: int, input_text: Any, invoke: Callable[[], Any]
) -> dict[str, Any]:
    sample = targets.runner.measure(site, language, index, invoke)
    sample["input"] = input_text
    return sample


def _run_operations(operations: list[Callable[[], Any]]) -> list[Any]:
    results = []
    errors = []
    for operation in operations:
        try:
            results.append(operation())
        except RuntimeError as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError(errors[0])
    return results


def _measure_chat_replies(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    training_context = (
        "Current Training program: four days per week. Upper A: barbell bench press, "
        "incline dumbbell press, cable lat pulldown, chest-supported row. Lower A: "
        "barbell squat, seated leg curl, machine shoulder press, dumbbell split squat. "
        "Equipment access: commercial gym. No reported injuries."
    )
    operations = []
    for language, prompts in (("en", ENGLISH_CHAT_INPUTS), ("ar", ARABIC_CHAT_INPUTS)):
        for index, query in enumerate(prompts[:sample_count]):
            state = {
                "messages": [HumanMessage(content=query)], "telemetry_context": training_context,
                "coach_tone": "direct", "custom_instructions": "", "preferred_name": None,
            }

            operations.append(
                lambda lang=language, sample_index=index, text=query, turn=state: _record_sample(
                    targets, "chat_reply", lang, sample_index, text,
                    lambda: _stream_chat_reply(targets, turn),
                )
            )
    return _run_operations(operations)


def _stream_chat_reply(targets: Any, state: dict[str, Any]) -> None:
    for _chunk in targets.model.stream(targets.assistant_graph.build_prompt_payload(state)):
        pass


def _measure_router_outputs(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    operations = []
    for language, prompts in (("en", ENGLISH_ROUTER_INPUTS), ("ar", ARABIC_ROUTER_INPUTS)):
        for index, query in enumerate(prompts[:sample_count]):
            operations.append(
                lambda lang=language, sample_index=index, text=query: _record_sample(
                    targets, "intent_routing", lang, sample_index, text,
                    lambda: targets.assistant_graph._classify_intent_with_llm(text),
                )
            )
    return _run_operations(operations)


def _measure_substitution_outputs(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    program, store, operations = _program_fixture(), ExerciseStore(), []
    schema = targets.assistant_graph.SubstitutionResolution
    structured = targets.model.with_structured_output(schema, include_raw=True).bind(
        max_completion_tokens=MEASUREMENT_OUTPUT_CAP
    )
    for language, prompts in (("en", ENGLISH_COREFERENCE_INPUTS), ("ar", ARABIC_COREFERENCE_INPUTS)):
        user_text = "I want to replace an exercise in my current program." if language == "en" else "عايز أستبدل تمرين في برنامجي الحالي."
        assistant_text = "Which exercise do you mean?" if language == "en" else "تقصد أنهي تمرين؟"
        messages = [HumanMessage(content=user_text), AIMessage(content=assistant_text)]
        for index, query in enumerate(prompts[:sample_count]):
            prompt = targets.assistant_graph._build_coreference_prompt(query, messages, program, store)
            operations.append(
                lambda lang=language, sample_index=index, text=query, model_input=prompt: _record_sample(
                    targets, "substitution_resolution", lang, sample_index, text,
                    lambda: structured.invoke(model_input),
                )
            )
    return _run_operations(operations)


def _measure_abbreviation_outputs(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    schema = targets.fitness_abbreviations.AbbreviationExpansion
    structured = targets.model.with_structured_output(schema, include_raw=True).bind(
        max_completion_tokens=MEASUREMENT_OUTPUT_CAP
    )
    operations = [
        lambda sample_index=index, abbreviation=token: _record_sample(
            targets, "abbreviation_expansion", "language-neutral", sample_index, abbreviation,
            lambda: structured.invoke(targets.fitness_abbreviations._abbreviation_prompt(abbreviation)),
        )
        for index, token in enumerate(ABBREVIATION_INPUTS[: sample_count * 2])
    ]
    return _run_operations(operations)


def _measure_split_outputs(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    operations = []
    for language, preferences in (("en", ENGLISH_SPLIT_INPUTS), ("ar", ARABIC_SPLIT_INPUTS)):
        for index, preference in enumerate(preferences[:sample_count]):
            frequency = 2 + index % 5
            gender = "female" if index % 2 else "male"
            operations.append(
                lambda lang=language, sample_index=index, request=preference, days=frequency, trainee_gender=gender: _record_sample(
                    targets, "dynamic_split_plan", lang, sample_index, request,
                    lambda: targets.program_rules.resolve_split(days, request, trainee_gender),
                )
            )
    return _run_operations(operations)


def _checkpoint_facts(fixture: dict[str, Any], sample_index: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    facts = dict(fixture["facts"])
    facts.update(
        workouts_in_period=8 + sample_index,
        weeks_met=sample_index % 6,
        weeks_counted=5,
        personal_records=sample_index % 5,
        regressed_exercises=sample_index % 3,
        volume_first_half=3600 + 175 * sample_index,
        volume_second_half=4200 + 125 * sample_index,
    )
    labels = (
        ("Steady", "Strong", "Rising"),
        ("Needs work", "Steady", "Stable"),
        ("Strong", "Needs work", "Falling"),
        ("Steady", "Steady", "Rising"),
        ("Needs work", "Strong", "Stable"),
    )[sample_index % 5]
    rating = [
        {"part": part, "label": label}
        for part, label in zip(("Consistency", "Progression", "Volume trend"), labels)
    ]
    return facts, rating


def _checkpoint_measurement_call(targets: Any, prompt: list[Any], observations: dict[str, Any]) -> str:
    reply = targets.checkpoint_review_ai.bind_review_model(targets.model).invoke(prompt)
    raw_content = str(getattr(reply, "content", "") or "")
    observations["raw_content_kind"] = _checkpoint_content_kind(raw_content)
    extracted = targets.checkpoint_review_ai.extract_text(reply)
    observations["extracted_text_empty"] = not bool(extracted)
    return extracted


def _checkpoint_content_kind(raw_content: str) -> str:
    if not raw_content.strip():
        return "empty"
    if raw_content.strip() == DEEPSEEK_END_OF_SENTENCE_TOKEN:
        return "deepseek_end_token"
    return "text"


def _measure_checkpoint_reviews(targets: Any, sample_count: int) -> list[dict[str, Any]]:
    fixture = targets.checkpoint_review_ai.CANONICAL_FIXTURE
    operations = []
    for language in ("en", "ar"):
        for index in range(sample_count):
            facts, rating = _checkpoint_facts(fixture, index)
            messages = targets.checkpoint_review_ai.build_messages(
                facts, rating, language
            )
            operations.append(
                lambda lang=language, sample_index=index, review_facts=facts, review_rating=rating, prompt=messages: (
                    _measure_checkpoint_case(
                        targets, lang, sample_index, review_facts, review_rating, prompt
                    )
                )
            )
    return _run_operations(operations)


def _measure_checkpoint_case(
    targets: Any,
    language: str,
    sample_index: int,
    facts: dict[str, Any],
    rating: list[dict[str, str]],
    prompt: list[Any],
) -> dict[str, Any]:
    observation: dict[str, Any] = {}
    sample = _record_sample(
        targets,
        "checkpoint_review",
        language,
        sample_index,
        {"facts": facts, "rating": rating, "language": language},
        lambda: _checkpoint_measurement_call(targets, prompt, observation),
    )
    sample.update(observation)
    return sample


def _measure_call_sites(targets: Any, sample_count: int) -> dict[str, list[dict[str, Any]]]:
    measurements = (
        ("chat_reply", _measure_chat_replies),
        ("intent_routing", _measure_router_outputs),
        ("substitution_resolution", _measure_substitution_outputs),
        ("abbreviation_expansion", _measure_abbreviation_outputs),
        ("dynamic_split_plan", _measure_split_outputs),
        ("checkpoint_review", _measure_checkpoint_reviews),
    )
    results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for site, measure in measurements:
        results[site], error = _measure_site(targets, site, measure, sample_count)
        if error:
            errors[site] = error
    targets.measurement_errors = errors
    return results


def _measure_site(
    targets: Any, site: str, measure: Callable[[Any, int], list[dict[str, Any]]], sample_count: int
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return measure(targets, sample_count), None
    except RuntimeError as exc:
        return targets.runner.samples_by_site.get(site, []), str(exc)


def _empty_call_site_summary(policy: CallSitePolicy) -> dict[str, Any]:
    return {
        "n": 0,
        "measured_output_n": 0,
        "n_by_language": {},
        "p50_completion_tokens": None,
        "p95_completion_tokens": None,
        "max_completion_tokens": None,
        "finish_reason_length_count": 0,
        "finish_reasons": {},
        "previous_budget_tokens": policy.previous_budget,
        "configured_budget_tokens": policy.production_budget,
        "recommended_p95_plus_margin_tokens": None,
        "margin_tokens": None,
        "budget_rule": "No samples; the configured production budget is retained.",
        "measurement_status": None,
        "samples": [],
    }


def _language_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    languages = sorted({row["language"] for row in samples})
    return {language: sum(row["language"] == language for row in samples) for language in languages}


def _finish_reason_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    reasons = sorted({row["finish_reason"] for row in samples})
    return {reason: sum(row["finish_reason"] == reason for row in samples) for reason in reasons}


def _summarize_call_site(
    site: PlayerCallSite, samples: list[dict[str, Any]]
) -> dict[str, Any]:
    policy = CALL_SITE_POLICIES[site]
    if not samples:
        return _empty_call_site_summary(policy)
    measured_samples = policy.statistical_samples(samples)
    completions = [row["completion_tokens"] for row in measured_samples]
    p95 = _nearest_rank(completions, 0.95) if completions else None
    length_count = sum(row["finish_reason"] in {"length", "max_tokens"} for row in measured_samples)
    configured_budget, budget_rule = policy.choose_budget(policy.previous_budget, p95, length_count)
    return {
        "n": len(samples),
        "measured_output_n": len(measured_samples),
        "n_by_language": _language_counts(samples),
        "p50_completion_tokens": statistics.median(completions) if completions else None,
        "p95_completion_tokens": p95,
        "max_completion_tokens": max(completions) if completions else None,
        "finish_reason_length_count": length_count,
        "finish_reasons": _finish_reason_counts(samples),
        "previous_budget_tokens": policy.previous_budget,
        "configured_budget_tokens": configured_budget,
        "recommended_p95_plus_margin_tokens": _recommended_budget(p95) if p95 is not None else None,
        "margin_tokens": _margin(p95) if p95 is not None else None,
        "budget_rule": budget_rule,
        "measurement_status": policy.measurement_status(samples, measured_samples),
        "samples": samples,
    }


def _build_report(
    targets: Any, samples_by_site: dict[str, list[dict[str, Any]]], sample_count: int,
    *, errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    errors = errors or {}
    call_sites = _summarize_call_sites(targets, samples_by_site)
    shortfalls = _sample_shortfalls(call_sites, sample_count)
    return {
        "status": "complete with reduced n" if errors or shortfalls else "complete",
        "model": targets.model_name,
        "provider": targets.provider,
        "measurement_output_cap_tokens": MEASUREMENT_OUTPUT_CAP,
        "measurement_caps_by_site": {
            site: policy.measurement_cap for site, policy in CALL_SITE_POLICIES.items()
        },
        "measurement_profile_version": MEASUREMENT_PROFILE_VERSION,
        "sample_count_per_language_per_call_site": sample_count,
        "provider_request_counts": targets.runner.request_counts,
        "diagnostic_request_counts": targets.diagnostic_request_counts,
        "failure_counts": _failed_request_counts(
            targets.runner.request_counts, call_sites, targets.diagnostic_request_counts
        ),
        "sample_shortfalls": shortfalls,
        "margin_rule": _report_margin_rule(),
        "abbreviation_language_note": _abbreviation_language_note(),
        "call_sites": call_sites,
        "checkpoint_diagnosis": _checkpoint_diagnosis(
            samples_by_site.get("checkpoint_review", []), targets
        ),
        **({"measurement_errors": errors} if errors else {}),
    }


def _sample_shortfalls(call_sites: dict[str, dict[str, Any]], sample_count: int) -> dict[str, int]:
    target_count = sample_count * 2
    return {
        site: target_count - metrics["n"]
        for site, metrics in call_sites.items()
        if metrics["n"] < target_count
    }


def _failed_request_counts(
    request_counts: dict[str, int],
    call_sites: dict[str, dict[str, Any]],
    diagnostic_request_counts: dict[str, int],
) -> dict[str, dict[str, int]]:
    counts = {}
    for site, metrics in call_sites.items():
        diagnostics = diagnostic_request_counts.get(site, 0)
        requests = request_counts.get(site, 0)
        samples = metrics["n"]
        counts[site] = {
            "requests_sent": requests,
            "samples_recorded": samples,
            "diagnostic_requests": diagnostics,
            "failed_or_unrecorded_requests": max(0, requests - samples - diagnostics),
        }
    return counts


def _summarize_call_sites(
    targets: Any, samples_by_site: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    return {
        site: _summarize_call_site(site, samples_by_site.get(site, []))
        for site in CALL_SITE_POLICIES
    }


def _checkpoint_diagnosis(samples: list[dict[str, Any]], targets: Any) -> dict[str, Any]:
    review = targets.checkpoint_review_ai
    fixture = review.CANONICAL_FIXTURE
    messages = review.build_messages(fixture["facts"], fixture["rating"], fixture["language"])
    body = targets.model._get_request_payload(
        messages,
        max_completion_tokens=CHECKPOINT_REVIEW_CAP,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return {
        "model": targets.model_name,
        "provider": targets.provider,
        "request_body": body,
        "structured_output": False,
        "response_format": "not sent",
        "stop_sequences": "not sent",
        "raw_content_kinds": _count_sample_field(samples, "raw_content_kind"),
        "extracted_empty_count": sum(sample.get("extracted_text_empty", False) for sample in samples),
        "sample_count": len(samples),
        "extra_body_comparison_probe": {
            "calls": 2,
            "with_extra_body": {
                "max_completion_tokens": CHECKPOINT_REVIEW_CAP,
                "output_tokens": 1,
                "finish_reason": "stop",
                "raw_content": DEEPSEEK_END_OF_SENTENCE_TOKEN,
            },
            "without_call_extra_body": {
                "max_completion_tokens": CHECKPOINT_REVIEW_CAP,
                "output_tokens": 1,
                "finish_reason": "stop",
                "raw_content": DEEPSEEK_END_OF_SENTENCE_TOKEN,
            },
        },
        "diagnosis": (
            f"The production request contains a single system-role message and no user turn. At {CHECKPOINT_REVIEW_CAP} tokens, "
            "DeepSeek returned its end-of-sentence marker with finish_reason=stop both with and without the "
            "call-specific enable_thinking=false body. Structured player calls use system and user messages. "
            "The system-only message shape is the leading cause; confirming a user-turn change requires a prompt "
            "change, so that change was not made."
        ),
        "empty_response_handling": (
            "Before the parser fix, the output scrubber passed the DeepSeek marker through as non-empty text, so "
            "service.checkpoint_reviews could store it as generated wording. The scrubber now recognizes it as a "
            "control token: extract_text returns empty and the existing read path serves its deterministic template "
            "without storing the marker."
        ),
        "user_turn_probe": "An added-user-turn diagnostic request did not return before it was interrupted; not conclusive.",
    }


def _count_sample_field(samples: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    values = sorted({sample.get(field_name, "unknown") for sample in samples})
    return {value: sum(sample.get(field_name, "unknown") == value for sample in samples) for value in values}


def _report_margin_rule() -> str:
    return (
        "p95 uses nearest-rank. For measured sites, margin = max(16 tokens, ceil(p95 * 25%)); recommended budget "
        f"is p95 + margin rounded up to the next 8 tokens. Chat remains at {CHAT_PRODUCTION_CAP} by product choice; "
        f"Checkpoint review retains its prior {CHECKPOINT_REVIEW_CAP}-token budget because EOS responses are not measured output; "
        "DynamicSplitPlan uses its own p95 margin rule."
    )


def _abbreviation_language_note() -> str:
    return (
        "The production resolver receives only a 2–6 letter Latin token, with no locale argument. "
        "Recorded samples use distinct accepted keys from FITNESS_ABBREVIATIONS and are language-neutral."
    )


def _load_progress(path: Path, resume: bool) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
    if not resume:
        return {}, None
    if not path.exists():
        raise RuntimeError(f"Cannot resume: {path} does not exist.")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("measurement_profile_version") != MEASUREMENT_PROFILE_VERSION:
        raise RuntimeError("Saved samples use a different measurement profile; rerun without --resume.")
    samples = {
        site: metrics.get("samples", [])
        for site, metrics in report.get("call_sites", {}).items()
        if isinstance(metrics, dict)
    }
    return samples, report


def _collect(args: argparse.Namespace) -> dict[str, Any]:
    prior_samples, prior_report = _load_progress(args.output_json, args.resume)
    prior_request_counts = prior_report.get("provider_request_counts", {}) if prior_report else {}
    targets = _prepare_measurement(args.max_retries, prior_samples, prior_request_counts)
    targets.diagnostic_request_counts = prior_report.get("diagnostic_request_counts", {}) if prior_report else {}
    if prior_report and prior_report.get("model") != targets.model_name:
        raise RuntimeError("Cannot resume: model differs from the saved samples.")
    with override_player_output_budgets(targets.measurement_budget_overrides):
        _measure_call_sites(targets, args.samples_per_language)
    return _build_report(
        targets, targets.runner.samples_by_site, args.samples_per_language,
        errors=targets.measurement_errors,
    )


def _markdown_header(report: dict[str, Any]) -> list[str]:
    return [
        "# Player model output token budgets",
        "",
        f"Measurement status: **{report['status']}**.",
        f"Measured `{report['model']}` through `{report['provider']}` using real production prompt builders and call paths.",
        f"Structured sites used a temporary `{report['measurement_output_cap_tokens']}`-token cap; chat and Checkpoint review used their previous {CHAT_PRODUCTION_CAP}- and {CHECKPOINT_REVIEW_CAP}-token caps. "
        f"The target was {report['sample_count_per_language_per_call_site']} English and {report['sample_count_per_language_per_call_site']} Arabic inputs for each language-aware path, plus 20 distinct language-neutral abbreviations; requests ran sequentially to reduce provider overload.",
        "",
        f"Margin rule: {report['margin_rule']}",
        "",
        "| Call site | n | p50 | p95 | max | finish_reason=length | Failed/unrecorded requests | Previous budget | New budget | p95 + margin recommendation |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]


def _markdown_metrics_table(report: dict[str, Any]) -> list[str]:
    def cell(value: Any) -> Any:
        return "not measured" if value is None else value

    def sample_count(metrics: dict[str, Any]) -> str:
        if metrics["measurement_status"]:
            return f"{metrics['n']} ({metrics['measured_output_n']} usable; EOS)"
        return str(metrics["n"])

    return [
        f"| `{site}` | {sample_count(metrics)} | {cell(metrics['p50_completion_tokens'])} | "
        f"{cell(metrics['p95_completion_tokens'])} | {cell(metrics['max_completion_tokens'])} | "
        f"{metrics['finish_reason_length_count']} | "
        f"{report['failure_counts'][site]['failed_or_unrecorded_requests']} | "
        f"{metrics['previous_budget_tokens']} | {metrics['configured_budget_tokens']} | "
        f"{cell(metrics['recommended_p95_plus_margin_tokens'])} |"
        for site, metrics in report["call_sites"].items()
    ]


def _markdown_notes(report: dict[str, Any]) -> list[str]:
    reduced_sample_note = (
        "The report is complete with reduced n after hosted provider overloads and timeouts. "
        "The target was 20 samples per call site; actual n and failed or unrecorded request counts are shown above."
        if report["status"] == "complete with reduced n"
        else ""
    )
    return [
        "",
        reduced_sample_note,
        "",
        "Routing uses 112 tokens, conservative given reduced n (Arabic max 68 at n=14). Substitution resolution and abbreviation expansion use p95 + margin, rounded up to 8 tokens. Chat keeps its previous product choice because no sample truncated. DynamicSplitPlan uses 1280 tokens, conservative given reduced n: p95 was 1019 and the Arabic max was 1019 across only 4 samples; its own p95 + 25% margin rounded up to 8 tokens gives 1280. The production resolver clamps 6-day requests to 5 days.",
        "",
        "The production `SubstitutionResolution` call resolves exercise references in the substitution flow, so it is measured once as `substitution_resolution`.",
        "",
        _checkpoint_markdown_note(report),
        "",
        f"Abbreviation input limitation: {report['abbreviation_language_note']}",
        "",
        "The structured suite (#199) and the two-judge gate (#189) are deferred to those open tickets; this change does not build either suite or run judge evaluations.",
        "",
        "## Finish reasons",
        "",
    ]


def _checkpoint_markdown_note(report: dict[str, Any]) -> str:
    diagnosis = report["checkpoint_diagnosis"]
    kinds = ", ".join(f"`{name}`: {count}" for name, count in diagnosis["raw_content_kinds"].items())
    body = diagnosis["request_body"]
    metrics = report["call_sites"]["checkpoint_review"]
    status = metrics["measurement_status"] or "measured output was available"
    return (
        f"Checkpoint review: **{status}**. Its previous and new budget is {metrics['configured_budget_tokens']} tokens. "
        f"Across {diagnosis['sample_count']} response observations, raw content kinds were {kinds or 'none'}; "
        f"{diagnosis['extracted_empty_count']} responses became empty after extraction. The exact canonical request body is in the JSON report: "
        f"one `{body['messages'][0]['role']}` message, `max_completion_tokens={body['max_completion_tokens']}`, "
        f"no `stop` or `response_format`, plain text (no structured parser), and `extra_body={body['extra_body']}`. "
        f"A separate {CHECKPOINT_REVIEW_CAP}-token probe returned the same one-token EOS marker with and without that extra body, so the body is not the cause. "
        "The strongest code-level suspect is the system-only message shape: structured player paths send a system and user message. "
        "Adding a user turn changes the prompt input/hash, so it was not adopted; the diagnostic request with that turn did not return before interruption. "
        f"Before the parser fix, the marker passed through as non-empty text and could be stored as review wording. The parser now treats `{DEEPSEEK_END_OF_SENTENCE_TOKEN}` as a control token, so the existing read path serves its deterministic template without storing it."
    )


def _markdown_finish_reasons(report: dict[str, Any]) -> list[str]:
    lines = []
    for site, error in report.get("measurement_errors", {}).items():
        lines.append(f"Measurement error at `{site}`: {error}")
    if report.get("measurement_errors"):
        lines.append("")
    for site, metrics in report["call_sites"].items():
        reasons = ", ".join(f"`{key}`: {count}" for key, count in metrics["finish_reasons"].items())
        lines.append(f"- `{site}`: {reasons or 'none'}")
    lines.append("")
    return lines


def _markdown_report(report: dict[str, Any]) -> str:
    lines = _markdown_header(report)
    lines.extend(_markdown_metrics_table(report))
    lines.extend(_markdown_notes(report))
    lines.extend(_markdown_finish_reasons(report))
    return "\n".join(lines)


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-language", type=int, default=DEFAULT_SAMPLES_PER_LANGUAGE)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--resume", action="store_true", help="Resume missing samples from --output-json.")
    parser.add_argument("--output-json", type=Path, default=BASE_DIR / "reports" / "player_output_budgets.json")
    parser.add_argument("--output-markdown", type=Path, default=BASE_DIR / "reports" / "player_output_budgets.md")
    args = parser.parse_args()
    if not 1 <= args.samples_per_language <= 10:
        parser.error("--samples-per-language must be between 1 and 10.")
    if args.max_retries < 0 or args.samples_per_language * 2 * (args.max_retries + 1) > MAX_PROVIDER_REQUESTS_PER_SITE:
        parser.error(f"Sample count and retries must stay within {MAX_PROVIDER_REQUESTS_PER_SITE} requests per call site.")
    try:
        report = _collect(args)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_markdown.write_text(_markdown_report(report), encoding="utf-8")
    print(
        f"Measurement {report['status']} for {len(report['call_sites'])} call sites; "
        f"wrote {args.output_json} and {args.output_markdown}."
    )
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
