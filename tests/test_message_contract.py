import re
from pathlib import Path

from service import messages


def test_coach_alert_message_codes_match_dart_resolver_and_server_allowlists():
    repository_root = Path(messages.__file__).resolve().parents[1]
    service_source = Path(messages.__file__).read_text(encoding="utf-8")
    resolver_path = (
        repository_root
        / "mobile/lib/src/core/display_language/message_resolver.dart"
    )
    resolver_source = resolver_path.read_text(encoding="utf-8")

    service_codes = set(re.findall(r'"(coach_alert\.[^"]+)"', service_source))
    server_allowlist_codes = set(messages.COACH_ALERT_MESSAGE_PARAM_ALLOWLISTS)
    resolver_codes = set(
        re.findall(
            r"^\s*'(coach_alert\.[^']+)': _[A-Za-z][A-Za-z0-9]*,",
            resolver_source,
            flags=re.MULTILINE,
        )
    )

    assert service_codes == server_allowlist_codes
    assert resolver_codes == server_allowlist_codes
