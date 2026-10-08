import re
from pathlib import Path

from service import intake, messages


def _intake_copy_codes_from_specs():
    codes = set()
    for field in intake.INTAKE_FIELDS:
        if field.explanation is not None:
            codes.add(f"intake.{field.name}.explanation.v1")
        if field.hint is not None:
            codes.add(f"intake.{field.name}.hint.v1")
        codes.update(
            f"intake.{field.name}.example.{index}.v1"
            for index, _ in enumerate(field.examples, start=1)
        )
        codes.update(
            f"intake.{field.name}.option.{intake._intake_option_slug(value)}.v1"
            for value in field.option_descriptions
        )
    return codes


def test_structured_message_codes_match_dart_resolver_and_server_allowlists():
    repository_root = Path(messages.__file__).resolve().parents[1]
    service_source = Path(messages.__file__).read_text(encoding="utf-8")
    resolver_path = repository_root / "mobile/lib/src/core/display_language/message_resolution.dart"
    resolver_source = resolver_path.read_text(encoding="utf-8")

    code_prefixes = (
        "coach_alert|http|ai_limit|chat|google|workout|auth|assignment|"
        "program_import|program|program_request|intake|coach|media|recovery|coach_invite|app"
    )
    service_codes = set(
        re.findall(rf'"((?:{code_prefixes})\.[^"]+)"', service_source)
    )
    service_codes.update(_intake_copy_codes_from_specs())
    server_allowlist_codes = set(messages.MESSAGE_PARAM_ALLOWLISTS)
    resolver_template_codes = set(
        re.findall(
            rf"^\s*'((?:{code_prefixes})\.[^']+)': _[A-Za-z][A-Za-z0-9]*,",
            resolver_source,
            flags=re.MULTILINE,
        )
    )
    resolver_param_codes = set(
        re.findall(
            rf"^\s*'((?:{code_prefixes})\.[^']+)': <String>\{{",
            resolver_source,
            flags=re.MULTILINE,
        )
    )
    resolver_params = {
        code: set(re.findall(r"'([^']+)'", fields))
        for code, fields in re.findall(
            rf"^\s*'((?:{code_prefixes})\.[^']+)': <String>\{{([^}}]*)\}}",
            resolver_source,
            flags=re.MULTILINE,
        )
    }

    assert service_codes == server_allowlist_codes
    assert resolver_param_codes == server_allowlist_codes
    assert server_allowlist_codes - resolver_template_codes <= {
        code
        for code in server_allowlist_codes
        if code.startswith(
            (
                "auth.",
                "assignment.",
                "program.",
                "program_request.",
                "intake.",
                "coach.",
                "media.",
                "google.",
                "recovery.",
                "coach_invite.",
            )
        )
    }
    assert resolver_params == {
        code: set(params) for code, params in messages.MESSAGE_PARAM_ALLOWLISTS.items()
    }


def test_untrusted_or_incomplete_message_params_are_rejected():
    invalid = messages.structured_message(
        "http.input_too_long.v1", {"limit": "password"}, "Safe fallback."
    )
    missing = messages.structured_message(
        "http.input_too_long.v1", {}, "Safe fallback."
    )
    malformed_type = messages.structured_message(
        "http.input_too_long.v1", {"limit": True}, "Safe fallback."
    )
    unexpected = messages.structured_message(
        "recovery.invalid_or_expired_code.v1",
        {"code": "123456"},
        "Safe fallback.",
    )

    assert invalid == {
        "message_code": None,
        "message_params": {},
        "message_fallback": "Safe fallback.",
    }
    assert missing == invalid
    assert malformed_type == invalid
    assert unexpected == invalid


def test_intake_message_codes_have_resolver_and_arabic_copy_entries():
    repository_root = Path(messages.__file__).resolve().parents[1]
    resolver_source = (
        repository_root / "mobile/lib/src/core/display_language/message_resolution.dart"
    ).read_text(encoding="utf-8")
    copy_source = (
        repository_root / "mobile/lib/src/core/display_language/intake_copy.dart"
    ).read_text(encoding="utf-8")
    generated_codes = _intake_copy_codes_from_specs()
    resolver_codes = set(
        re.findall(r"^\s*'(intake\.[^']+)': <String>\{", resolver_source, re.MULTILINE)
    )
    arabic_codes = set(
        re.findall(r"^\s*'(intake\.[^']+)':", copy_source, re.MULTILINE)
    )

    assert generated_codes == set(intake.INTAKE_COPY_MESSAGE_PARAM_ALLOWLISTS)
    assert generated_codes <= set(messages.MESSAGE_PARAM_ALLOWLISTS)
    assert generated_codes <= resolver_codes
    assert generated_codes <= arabic_codes
    program_message_code = "intake.program_generation_unavailable.v1"
    assert program_message_code in messages.MESSAGE_PARAM_ALLOWLISTS
    assert program_message_code in resolver_codes
    assert program_message_code in arabic_codes


def test_weight_trend_alert_message_contains_allowlisted_typed_values():
    message = messages.coach_alert_message(
        "weight_off_target_trend",
        {
            "distance_change_kg": 1.4,
            "target_weight_kg": 70,
            "window_days": 14,
            "threshold_kg": 1.0,
        },
    )

    assert message == {
        "message_code": "coach_alert.weight_off_target_trend.v1",
        "message_params": {
            "distance_change_kg": 1.4,
            "target_weight_kg": 70.0,
            "window_days": 14,
            "threshold_kg": 1.0,
        },
        "message_fallback": (
            "Weight moved away from the target by 1.4 kg over 14 days "
            "(alert threshold 1 kg; target 70 kg)."
        ),
    }
