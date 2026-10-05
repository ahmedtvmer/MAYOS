import re
from pathlib import Path

from service import messages


def test_structured_message_codes_match_dart_resolver_and_server_allowlists():
    repository_root = Path(messages.__file__).resolve().parents[1]
    service_source = Path(messages.__file__).read_text(encoding="utf-8")
    resolver_path = (
        repository_root
        / "mobile/lib/src/core/display_language/message_resolver.dart"
    )
    resolver_source = resolver_path.read_text(encoding="utf-8")

    code_prefixes = (
        "coach_alert|http|ai_limit|chat|google|workout|auth|assignment|"
        "program|program_request|intake|coach|media|recovery|coach_invite"
    )
    service_codes = set(
        re.findall(rf'"((?:{code_prefixes})\.[^"]+)"', service_source)
    )
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
