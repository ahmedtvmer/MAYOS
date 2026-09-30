"""Probes every player-side production structured-output site in strict mode.

The production call sites are invoked directly. A harness-only adapter forces
LangChain's JSON Schema method with ``strict=True`` and records parse results;
no production module is edited.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from types import SimpleNamespace
from typing import Any

from _common import SPEND, body_manifest, configure_cloud_env, install_role_request_bodies, write_json


class StrictRunnable:
    def __init__(self, runnable: Any, site: str, schema: type, owner: "StrictLLM") -> None:
        self.runnable = runnable
        self.site = site
        self.schema = schema
        self.owner = owner

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            value = self.runnable.invoke(*args, **kwargs)
            if not isinstance(value, self.schema):
                raise TypeError(f"expected {self.schema.__name__}, got {type(value).__name__}")
            self.owner.record(self.site, self.schema, True, None, time.perf_counter() - started, value)
            return value
        except Exception as exc:
            self.owner.record(
                self.site, self.schema, False,
                f"{type(exc).__name__}: {str(exc)[:240]}", time.perf_counter() - started, None,
            )
            raise


class StrictLLM:
    def __init__(self, model: Any, site: str, records: list[dict[str, Any]]) -> None:
        self.model = model
        self.site = site
        self.records = records
        self.case_id = ""
        self.query_excerpt = ""

    def with_structured_output(self, schema: type, **_kwargs: Any) -> StrictRunnable:
        try:
            runnable = self.model.with_structured_output(schema, method="json_schema", strict=True)
        except Exception as exc:
            self.record(
                self.site, schema, False, f"{type(exc).__name__}: {str(exc)[:240]}", 0.0, None,
            )
            raise
        return StrictRunnable(runnable, self.site, schema, self)

    def record(
        self, site: str, schema: type, ok: bool, error: str | None, elapsed: float, parsed: Any,
    ) -> None:
        key = os.getenv("LLM_API_KEY", "")
        if error and key:
            error = error.replace(key, "[redacted]")
        self.records.append({
            "site": site,
            "case_id": self.case_id,
            "query_excerpt": self.query_excerpt[:180],
            "schema": schema.__name__,
            "method": "json_schema",
            "strict": True,
            "ok": ok,
            "error": error,
            "parsed": parsed.model_dump() if parsed is not None else None,
            "elapsed_s": round(elapsed, 4),
            "request_extra_body": getattr(self.model, "extra_body", None),
        })

    def begin(self, case_id: str, query: str) -> None:
        self.case_id = case_id
        self.query_excerpt = query


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    configure_cloud_env(player_model=args.model)

    temp = tempfile.TemporaryDirectory(prefix="mayos-structured-eval-")
    from utils.logger import MyosLogger

    MyosLogger(log_file=os.path.join(temp.name, "logs", "myos.log"))
    install_role_request_bodies(args.model)
    from utils import model_metering

    model_metering.set_recorder(
        lambda **kw: SPEND.add(
            kw["model"], int(kw["input_tokens"]), int(kw["output_tokens"]),
            estimated=bool(kw.get("estimated", False)),
        )
    )
    from utils.model_downloader import get_llm

    model = get_llm()
    records: list[dict[str, Any]] = []
    path_failures: list[dict[str, Any]] = []

    from agent import assistant_graph as graph
    from agent import fitness_abbreviations as abbreviations
    from agent import onboarding_graph as onboarding
    from agent import program_rules
    from langchain_core.messages import HumanMessage
    tag = args.model.split("/")[-1]
    output_name = f"player_structured_{tag}.json"

    site_wrappers = {
        "assistant_graph.intent_classification": StrictLLM(model, "assistant_graph.intent_classification", records),
        "assistant_graph.substitution_resolution": StrictLLM(model, "assistant_graph.substitution_resolution", records),
        "program_rules.dynamic_split_plan": StrictLLM(model, "program_rules.dynamic_split_plan", records),
        "onboarding_graph.step1_extraction": StrictLLM(model, "onboarding_graph.step1_extraction", records),
        "onboarding_graph.step2_extraction": StrictLLM(model, "onboarding_graph.step2_extraction", records),
        "onboarding_graph.step3_extraction": StrictLLM(model, "onboarding_graph.step3_extraction", records),
        "fitness_abbreviations.expansion": StrictLLM(model, "fitness_abbreviations.expansion", records),
    }
    graph.llm = site_wrappers["assistant_graph.intent_classification"]
    abbreviations.llm = site_wrappers["fitness_abbreviations.expansion"]
    program_rules.llm = site_wrappers["program_rules.dynamic_split_plan"]
    onboarding.llm = site_wrappers["onboarding_graph.step1_extraction"]
    # These extractors are module-level runnables in production, so the harness
    # reconstructs them with the same strict policy before calling intake_node.
    onboarding.step1_extractor = site_wrappers["onboarding_graph.step1_extraction"].with_structured_output(onboarding.Step1Extraction)
    onboarding.step2_extractor = site_wrappers["onboarding_graph.step2_extraction"].with_structured_output(onboarding.Step2Extraction)
    onboarding.step3_extractor = site_wrappers["onboarding_graph.step3_extraction"].with_structured_output(onboarding.Step3Extraction)

    def save_progress(status: str) -> None:
        by_site: dict[str, dict[str, int]] = {}
        for record in records:
            row = by_site.setdefault(record["site"], {"probes": 0, "passed": 0, "failed": 0})
            row["probes"] += 1
            row["passed" if record["ok"] else "failed"] += 1
        write_json(output_name, {
            "status": status,
            "model": args.model,
            "request_bodies": body_manifest(args.model),
            "method": "json_schema",
            "strict": True,
            "call_sites": by_site,
            "failures": [record for record in records if not record["ok"]],
            "path_failures": path_failures,
            "probes": records,
            "spend": SPEND.rows,
            "spend_usd": round(SPEND.total(), 6),
        })

    save_progress("RUNNING")

    def run_probe(site: str, case_id: str, query: str, call) -> None:
        wrapper = site_wrappers[site]
        wrapper.begin(case_id, query)
        before = len(records)
        outer_error = None
        try:
            call()
        except Exception as exc:
            outer_error = f"{type(exc).__name__}: {str(exc)[:240]}"
        emitted = records[before:]
        if not emitted:
            records.append({
                "site": site, "case_id": case_id, "query_excerpt": query[:180],
                "schema": None, "method": "json_schema", "strict": True,
                "ok": False, "error": outer_error or "production call path did not reach structured output",
                "parsed": None, "elapsed_s": None, "request_extra_body": getattr(model, "extra_body", None),
            })
        elif outer_error and all(record["ok"] for record in emitted):
            # A production-path failure after a valid strict parse is not a
            # structured-output failure; retain it separately for diagnosis.
            path_failures.append({
                "site": site, "case_id": case_id, "query_excerpt": query[:180],
                "error": outer_error,
            })
        save_progress("RUNNING")

    intent_cases = [
        "Reorganize the exercises in my program for a chest emphasis.",
        "Rearrange my weekly exercises to focus on back strength.",
    ]
    for index, query in enumerate(intent_cases, 1):
        run_probe(
            "assistant_graph.intent_classification", f"intent-{index:02d}", query,
            lambda query=query: graph.router_node({
                "messages": [HumanMessage(content=query)], "telemetry_context": "Upper/lower training plan",
                "coach_tone": "Direct", "custom_instructions": "",
            }, config={"configurable": {"ledger": None, "store": None}}),
        )

    program = SimpleNamespace(days=[SimpleNamespace(
        day_name="Upper", exercises=[SimpleNamespace(exercise_name="bench press"), SimpleNamespace(exercise_name="row")]
    )])
    substitution_cases = [
        "Replace it with an incline dumbbell press.",
        "Could I swap that movement for a machine chest press?",
    ]
    for index, query in enumerate(substitution_cases, 1):
        graph.llm = site_wrappers["assistant_graph.substitution_resolution"]
        run_probe(
            "assistant_graph.substitution_resolution", f"substitution-{index:02d}", query,
            lambda query=query: graph.resolve_coreference_with_llm(
                query, [HumanMessage(content="I want to change the bench press.")], program
            ),
        )
    graph.llm = site_wrappers["assistant_graph.intent_classification"]

    split_cases = [
        "Custom weekly arrangement with separate emphasis days for chest, back, and arms",
        "Unusual movement-focused split with a dedicated shoulders day",
    ]
    for index, preference in enumerate(split_cases, 1):
        run_probe(
            "program_rules.dynamic_split_plan", f"split-{index:02d}", preference,
            lambda preference=preference: program_rules.resolve_split(4, preference=preference),
        )

    onboarding_cases = [
        ("onboarding_graph.step1_extraction", 1, "I have longer legs than torso. I am a male, 30 years old, 80kg and 180cm tall."),
        ("onboarding_graph.step2_extraction", 2, "My current goal is muscle growth and long-term goal is strength. I can train four days weekly and have lifted for two years."),
        ("onboarding_graph.step3_extraction", 3, "I train in a commercial gym with barbells and cables. I sleep about seven hours and have no injuries."),
    ]
    eval_ledger = SimpleNamespace(upsert_player_profile=lambda _profile: None)
    for site, step, query in onboarding_cases:
        wrapper = site_wrappers[site]
        wrapper.begin(f"{site.rsplit('.', 1)[-1]}-01", query)
        run_probe(
            site, wrapper.case_id, query,
            lambda step=step, query=query: onboarding.intake_node({
                "messages": [HumanMessage(content=query)], "trainee_id": f"eval-{step}",
                "intake_step": step, "is_complete": False,
                "profile_data": ({"proportions": "balanced", "gender": "male", "age": 30,
                                  "weight_kg": 80.0, "height_cm": 180.0} if step == 2 else
                                 {"current_goal": "hypertrophy", "long_term_goal": "strength",
                                  "weekly_frequency": 4, "training_age_years": 2.0} if step == 3 else {}),
            }, config={"configurable": {"ledger": eval_ledger}}),
        )

    abbreviation_cases = ["XTR", "QZP"]
    for index, token in enumerate(abbreviation_cases, 1):
        run_probe(
            "fitness_abbreviations.expansion", f"abbreviation-{index:02d}", token,
            lambda token=token: abbreviations.resolve_unknown_abbreviation_with_llm(token),
        )

    save_progress("COMPLETE")
    SPEND.save(f"structured_{tag}")
    failed = sum(not row["ok"] for row in records)
    print(f"done {args.model}: structured failures={failed}/{len(records)} spend=${SPEND.total():.4f}")
    temp.cleanup()


if __name__ == "__main__":
    main()
