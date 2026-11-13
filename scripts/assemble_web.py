#!/usr/bin/env python3
"""Assemble Cloudflare Pages output from the landing site and Flutter build."""

import html
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "mobile" / "lib" / "src" / "router.dart"
MAX_STATIC_RULES = 2000
MAX_DYNAMIC_RULES = 100


def _read_quoted(source: str, start: int) -> tuple[str, int]:
    quote = source[start]
    cursor = start + 1
    content: list[str] = []
    while cursor < len(source):
        char = source[cursor]
        if char == "\\" and cursor + 1 < len(source):
            content.extend((char, source[cursor + 1]))
            cursor += 2
            continue
        if char == quote:
            return "".join(content), cursor + 1
        content.append(char)
        cursor += 1
    raise ValueError("unterminated quoted string in GoRoute path")


def _path_expression(source: str, start: int) -> tuple[str, bool]:
    cursor = start
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    if cursor < len(source) and source[cursor] in "'\"":
        value, _end = _read_quoted(source, cursor)
        return value, True
    match = re.match(r"[A-Za-z_]\w*", source[cursor:])
    if match:
        return match.group(0), False
    raise ValueError("unsupported GoRoute path expression")


def _expand_constant_refs(value: str, definitions: dict[str, str],
                          resolved: dict[str, str], resolving: set[str]) -> str:
    return re.sub(
        r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)",
        lambda match: _resolve_constant(
            match.group(1) or match.group(2), definitions, resolved, resolving
        ),
        value,
    )


def _resolve_constant(name: str, definitions: dict[str, str],
                      resolved: dict[str, str], resolving: set[str]) -> str:
    if name in resolved:
        return resolved[name]
    if name in resolving:
        raise ValueError(f"cyclic route constant {name}")
    if name not in definitions:
        raise ValueError(f"unresolved route constant {name}")
    resolving.add(name)
    expression = definitions[name].strip()
    if expression[:1] in ("'", '"'):
        value, end = _read_quoted(expression, 0)
        if expression[end:].strip():
            raise ValueError(f"unsupported route constant expression {name}")
        value = _expand_constant_refs(value, definitions, resolved, resolving)
    elif re.fullmatch(r"[A-Za-z_]\w*", expression):
        value = _resolve_constant(expression, definitions, resolved, resolving)
    else:
        raise ValueError(f"unsupported route constant expression {name}")
    resolving.remove(name)
    resolved[name] = value
    return value


def _resolve_constants(source: str) -> dict[str, str]:
    definitions = dict(re.findall(r"\bconst\s+String\s+(\w+)\s*=\s*([^;]+);", source))
    resolved: dict[str, str] = {}
    resolving: set[str] = set()
    for name in definitions:
        _resolve_constant(name, definitions, resolved, resolving)
    return resolved


def _route_path_expression(segment: str, index: int, constants: dict[str, str]) -> str:
    path_match = re.search(r"\bpath\s*:", segment)
    if path_match is None:
        raise ValueError(f"GoRoute #{index} has no resolvable path")
    try:
        expression, is_literal = _path_expression(segment, path_match.end())
        if not is_literal:
            return constants[expression]
        return _expand_constant_refs(expression, constants, constants, set())
    except (KeyError, ValueError) as error:
        raise ValueError(f"GoRoute #{index} path cannot be resolved: {error}") from error


def _join_route_path(route_path: str, indent: int,
                     route_stack: list[tuple[int, str]], index: int) -> str:
    while route_stack and route_stack[-1][0] >= indent:
        route_stack.pop()
    if not route_path.startswith("/"):
        parent_path = route_stack[-1][1] if route_stack else ""
        route_path = f"{parent_path}/{route_path}" if parent_path else f"/{route_path}"
    if "//" in route_path:
        raise ValueError(f"GoRoute #{index} has invalid path {route_path!r}")
    return route_path


def parse_router_routes(source: str) -> list[str]:
    constants = _resolve_constants(source)
    declarations = list(re.finditer(r"\bGoRoute\s*\(", source))
    routes: list[str] = []
    route_stack: list[tuple[int, str]] = []
    for index, declaration in enumerate(declarations):
        segment_end = (
            declarations[index + 1].start()
            if index + 1 < len(declarations)
            else len(source)
        )
        segment = source[declaration.end() : segment_end]
        route_path = _route_path_expression(segment, index + 1, constants)
        line_start = source.rfind("\n", 0, declaration.start()) + 1
        indent = len(re.match(r"\s*", source[line_start:declaration.start()]).group())
        route_path = _join_route_path(route_path, indent, route_stack, index + 1)
        routes.append(route_path)
        route_stack.append((indent, route_path))
    return routes


def render_redirects(routes: list[str]) -> list[str]:
    rules: set[tuple[str, str, str]] = set()
    for route in routes:
        route = route.rstrip("/") if route != "/" else route
        legacy_forms = (route, route + "/") if route != "/" else (route,)
        for legacy_path in legacy_forms:
            rules.add((legacy_path, "/app" + legacy_path, "301"))
        app_forms = tuple("/app" + path for path in legacy_forms)
        for app_path in app_forms:
            rules.add((app_path, "/app/", "200"))

    dynamic_rules = sorted(rule for rule in rules if re.search(r"/:[A-Za-z_]\w*", rule[0]))
    static_rules = sorted(rule for rule in rules if rule not in dynamic_rules)
    if len(dynamic_rules) > MAX_DYNAMIC_RULES:
        raise ValueError(
            f"Cloudflare Pages dynamic redirect/rewrite rule limit exceeded: "
            f"{len(dynamic_rules)} > {MAX_DYNAMIC_RULES}"
        )
    if len(static_rules) > MAX_STATIC_RULES:
        raise ValueError(
            f"Cloudflare Pages static redirect/rewrite rule limit exceeded: "
            f"{len(static_rules)} > {MAX_STATIC_RULES}"
        )
    return ["{} {} {}".format(*rule) for rule in static_rules + dynamic_rules]


def _scoped_headers(headers: Path) -> str:
    content = headers.read_text(encoding="utf-8")
    content = re.sub(
        r"(?m)^(\s*)/(assets|canvaskit)/(\*)(\s*)$",
        r"\1/app/\2/\3\4",
        content,
    )
    return re.sub(r"(?m)^(\s*)/(service-worker\.js|offline\.html)(\s*)$",
                  r"\1/app/\2\3", content)


def _precache_urls(worker_source: str) -> list[str]:
    return re.findall(r"[\"']?url[\"']?\s*:\s*[\"']([^\"']+)", worker_source)


def _assert_local_precache_urls(entries: list[str]) -> None:
    for url in entries:
        parsed_url = urlsplit(url)
        relative_path = PurePosixPath(unquote(parsed_url.path))
        if (parsed_url.scheme or parsed_url.netloc or relative_path.is_absolute()
                or ".." in relative_path.parts):
            raise ValueError("generated service worker precaches a non-local URL")


def _assert_precached_navigation_documents(entries: list[str]) -> None:
    cached_urls = {unquote(urlsplit(url).path) for url in entries}
    missing_urls = {"index.html", "offline.html"} - cached_urls
    if missing_urls:
        missing_list = ", ".join(sorted(missing_urls))
        raise ValueError(f"generated service worker does not precache {missing_list}")


def _assert_app_scripts_precached(entries: list[str], app_document: str) -> None:
    cached_urls = {unquote(urlsplit(url).path).lstrip("/") for url in entries}
    for script_src in re.findall(
        r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']",
        app_document,
        flags=re.IGNORECASE,
    ):
        script_url = urlsplit(script_src)
        if script_url.scheme or script_url.netloc:
            continue
        script_path = unquote(script_url.path).lstrip("/")
        if script_path not in cached_urls:
            raise ValueError(
                f"generated service worker does not precache app script {script_path}"
            )


def assert_service_worker_safe(worker_source: str, api_origin: str,
                               app_document: str | None = None) -> None:
    """Require the app document and reject cross-origin or account/API precache."""
    parsed_api = urlsplit(api_origin)
    origin = f"{parsed_api.scheme}://{parsed_api.netloc}" if parsed_api.netloc else api_origin.rstrip("/")
    if origin and origin in worker_source:
        raise ValueError("generated service worker references the API origin")
    entries = _precache_urls(worker_source)
    _assert_local_precache_urls(entries)
    _assert_precached_navigation_documents(entries)
    if any(
        urlsplit(url).path.lower().startswith(("canvaskit/skwasm", "canvaskit/wimp", "canvaskit/webparagraph/"))
        or urlsplit(url).path.lower().endswith(".symbols")
        or PurePosixPath(urlsplit(url).path).name.lower() == "notices"
        for url in entries
    ):
        raise ValueError("generated service worker precaches excluded CanvasKit or debug assets")
    if app_document is not None:
        _assert_app_scripts_precached(entries, app_document)


def assert_assembled_precache_unchanged(worker_source: str, build: Path,
                                        assembled_app: Path) -> None:
    """Ensure assembly copies every generated precache entry byte for byte."""
    for url in _precache_urls(worker_source):
        relative_path = PurePosixPath(unquote(urlsplit(url).path))
        build_file = build.joinpath(*relative_path.parts)
        assembled_file = assembled_app.joinpath(*relative_path.parts)
        if not build_file.is_file() or not assembled_file.is_file():
            raise ValueError(f"assembly is missing precached file {relative_path}")
        if build_file.read_bytes() != assembled_file.read_bytes():
            raise ValueError(f"assembly changed precached file {relative_path}")


def assemble(flutter_build: Path, landing: Path, output: Path) -> None:
    worker = flutter_build / "service-worker.js"
    worker_source = None
    if worker.exists():
        worker_source = worker.read_text(encoding="utf-8")
        assert_service_worker_safe(
            worker_source,
            os.environ.get("MAYOS_API_BASE_URL", "https://api.mayos.online"),
            (flutter_build / "index.html").read_text(encoding="utf-8"),
        )
    routes = parse_router_routes(ROUTER.read_text(encoding="utf-8"))
    redirects = render_redirects(routes)
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(landing, output)
    config = {
        "apiBaseUrl": os.environ.get("MAYOS_API_BASE_URL", "https://api.mayos.online"),
        "posthogKey": os.environ.get("POSTHOG_CLIENT_KEY", ""),
        "businessEmail": "ahmedtamerhejazi@gmail.com",
        "instagramHandle": "mayosapp",
        "tiktokHandle": "mayosapp",
    }
    landing_html = output / "index.html"
    landing_source = landing_html.read_text(encoding="utf-8")
    for template_marker, configured_value in {
        "@@BUSINESS_EMAIL@@": config["businessEmail"],
        "@@INSTAGRAM_HANDLE@@": config["instagramHandle"],
        "@@TIKTOK_HANDLE@@": config["tiktokHandle"],
        "@@API_BASE_URL@@": config["apiBaseUrl"].rstrip("/"),
    }.items():
        landing_source = landing_source.replace(
            template_marker, html.escape(configured_value, quote=True)
        )
    landing_html.write_text(landing_source, encoding="utf-8")
    runtime_config = {"posthogKey": config["posthogKey"]}
    (output / "landing-config.js").write_text(
        "window.MAYOS_LANDING = " + json.dumps(runtime_config, ensure_ascii=True) + ";\n",
        encoding="utf-8",
    )
    shutil.copytree(
        flutter_build,
        output / "app",
        ignore=shutil.ignore_patterns("_headers", "_redirects"),
    )
    if worker_source is not None:
        assert_assembled_precache_unchanged(worker_source, flutter_build, output / "app")
    flutter_headers = flutter_build / "_headers"
    if flutter_headers.exists():
        (output / "_headers").write_text(_scoped_headers(flutter_headers), encoding="utf-8")
    (output / "_redirects").write_text("\n".join(redirects) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: assemble_web.py FLUTTER_BUILD LANDING OUTPUT")
    assemble(*(Path(value) for value in sys.argv[1:]))
