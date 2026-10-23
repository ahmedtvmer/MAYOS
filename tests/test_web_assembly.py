import re
from pathlib import Path

import pytest

from scripts.assemble_web import assemble, parse_router_routes, render_redirects


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "mobile" / "lib" / "src" / "router.dart"


def _assembled_site(tmp_path):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    (flutter / "index.html").write_text(
        '<!doctype html><base href="/app/">', encoding="utf-8"
    )
    (flutter / "main.dart.js").write_text("js", encoding="utf-8")
    (flutter / "_redirects").write_text("/old /wrong 301", encoding="utf-8")
    (flutter / "_headers").write_text(
        "/assets/*\n  X-Asset: yes\n/canvaskit/*\n  X-Canvas: yes\n",
        encoding="utf-8",
    )
    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text("MYOS Log in", encoding="utf-8")
    (landing / "myos-logo.png").write_bytes(b"logo")
    output = tmp_path / "output"
    assemble(flutter, landing, output)
    return output


def test_assembly_layout_keeps_landing_and_flutter_separate(tmp_path):
    output = _assembled_site(tmp_path)

    assert (output / "index.html").read_text(encoding="utf-8") == "MYOS Log in"
    assert (output / "myos-logo.png").read_bytes() == b"logo"
    assert (output / "app" / "main.dart.js").read_text(encoding="utf-8") == "js"
    assert '<base href="/app/">' in (output / "app" / "index.html").read_text(
        encoding="utf-8"
    )
    assert not (output / "404.html").exists()


def test_critical_legacy_urls_redirect_to_same_app_path():
    rules = [line.split() for line in render_redirects(parse_router_routes(ROUTER.read_text()))]

    def normalize_params(path):
        return re.sub(r":[A-Za-z_]\w*", ":id", path)

    rule_map = {
        (normalize_params(source), status): normalize_params(target)
        for source, target, status in rules
    }
    cases = [
        ("/login", "/app/login", "301"),
        ("/register", "/app/register", "301"),
        ("/reset-password", "/app/reset-password", "301"),
        ("/reset-password/", "/app/reset-password/", "301"),
        ("/coach/roster", "/app/coach/roster", "301"),
        ("/coach/roster/:id", "/app/coach/roster/:id", "301"),
        ("/home", "/app/home", "301"),
        ("/update-required", "/app/update-required", "301"),
        ("/google-signup", "/app/google-signup", "301"),
    ]
    for source, target, status in cases:
        assert rule_map[(source, status)] == target
    assert ("/coach/roster/*", "301") not in rule_map
    for source, target, status in rules:
        if status == "301":
            assert re.findall(r":[A-Za-z_]\w*", source) == re.findall(
                r":[A-Za-z_]\w*", target
            )


def test_app_rewrites_cover_every_router_route_and_leave_assets_unshadowed():
    router = ROUTER.read_text(encoding="utf-8")
    routes = parse_router_routes(router)
    assert len(routes) == len(re.findall(r"\bGoRoute\s*\(", router))

    rules = [line.split() for line in render_redirects(routes)]
    rewrites = {(source, target, status) for source, target, status in rules if status == "200"}
    for route in routes:
        app_route = "/app" + route
        assert (app_route, "/app/", "200") in rewrites
        assert (app_route + "/", "/app/", "200") in rewrites
        for legacy_path in (route, route + "/"):
            assert [legacy_path, "/app" + legacy_path, "301"] in rules
    assert not any(source in ("/app/*", "/*") for source, _, _ in rules)


def test_redirects_have_static_before_dynamic_and_enforce_pages_limits():
    rules = render_redirects(parse_router_routes(ROUTER.read_text()))
    dynamic = [line for line in rules if re.search(r"/:[A-Za-z_][A-Za-z0-9_]*", line)]
    static = [line for line in rules if line not in dynamic]
    assert rules == static + dynamic

    with pytest.raises(ValueError, match="dynamic.*100"):
        render_redirects([f"/route-{index}/:id" for index in range(26)])
    with pytest.raises(ValueError, match="static.*2000"):
        render_redirects([f"/route-{index}" for index in range(501)])


def test_pages_headers_are_scoped_under_app_and_flutter_config_is_not_nested(tmp_path):
    output = _assembled_site(tmp_path)

    headers = (output / "_headers").read_text(encoding="utf-8")
    assert "/app/assets/*" in headers
    assert "/app/canvaskit/*" in headers
    assert "/assets/*" not in headers.splitlines()
    assert "/canvaskit/*" not in headers.splitlines()
    assert not (output / "app" / "_headers").exists()
    assert not (output / "app" / "_redirects").exists()


def test_router_parser_handles_inline_quoted_and_chained_constant_paths():
    source = '''
const String rootPath = "/root";
const String childBasePath = rootPath;
const String childPath = '$childBasePath/child';
GoRoute(path: '/inline', builder: build),
GoRoute(
  path: childPath,
  builder: build,
),
GoRoute(path: "/double-quoted", builder: build),
'''

    assert parse_router_routes(source) == [
        "/inline",
        "/root/child",
        "/double-quoted",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "GoRoute(builder: build),",
        "const String brokenPath = missingPath; GoRoute(path: brokenPath),",
        "GoRoute(path: '/unknown/$missingPath'),",
    ],
)
def test_router_parser_fails_loudly_on_unresolvable_routes(source):
    with pytest.raises(ValueError, match="GoRoute.*path|unresolved"):
        parse_router_routes(source)
