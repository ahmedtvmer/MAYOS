from pathlib import Path
import os
import re
import shutil
import subprocess
import textwrap

from scripts.assemble_web import assert_service_worker_safe
from scripts.assemble_web import assemble
import pytest


def test_generated_worker_must_not_precache_api_origin_or_document():
    api = "https://mayos-api.fly.dev"
    assert_service_worker_safe('self.__WB_MANIFEST = [{"url":"main.dart.js"}]', api)
    for worker in (
        f'self.__WB_MANIFEST = [{{"url":"{api}/v1/me"}}]',
        'self.__WB_MANIFEST = [{"url":"index.html"}]',
    ):
        try:
            assert_service_worker_safe(worker, api)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe generated worker accepted")


def test_generated_precache_excludes_canvas_kit_symbols_and_notices():
    worker = (
        'precacheAndRoute([{url:"main.dart.js"},{url:"canvaskit/canvaskit.js"},'
        '{url:"canvaskit/skwasm.js"},'
        '{url:"assets/example.symbols"},{url:"assets/NOTICES"}]);'
    )
    try:
        assert_service_worker_safe(worker, "https://mayos-api.fly.dev")
    except ValueError as error:
        assert "precache" in str(error)
    else:
        raise AssertionError("oversized precache entries were accepted")


def test_workbox_generated_and_assembled_manifest_has_required_assets_and_routes(
    tmp_path, monkeypatch
):
    node = shutil.which("node")
    npx = shutil.which("npx")
    if not node or not npx:
        pytest.skip("Node.js and npx are required to exercise the pinned Workbox build")

    repo = Path(__file__).parents[1]
    mobile = tmp_path / "mobile"
    web = mobile / "web"
    build = mobile / "build" / "web"
    web.mkdir(parents=True)
    build.mkdir(parents=True)
    shutil.copy2(repo / "mobile/web/workbox-config.cjs", web / "workbox-config.cjs")
    files = [
        "index.html", "flutter.js", "flutter_bootstrap.js", "main.dart.js",
        "manifest.json", "favicon.png", "apple-touch-icon.png", "myos-icon-192.png",
        "myos-loading-wallpaper.jpg", "myos-lockup-white.png", "pwa_bridge.js",
        "offline.html", "offline.js", "canvaskit/canvaskit.js",
        "canvaskit/canvaskit.wasm", "canvaskit/chromium/canvaskit.js",
        "canvaskit/chromium/canvaskit.wasm", "canvaskit/skwasm.js",
        "canvaskit/skwasm.wasm", "canvaskit/skwasm_heavy.js", "canvaskit/wimp.js",
        "canvaskit/webparagraph/canvaskit.js", "canvaskit/canvaskit.js.symbols",
        "assets/AssetManifest.bin", "assets/AssetManifest.bin.json",
        "assets/FontManifest.json", "assets/fonts/app.ttf", "assets/images/app.png",
        "assets/NOTICES", "https://mayos-api.fly.dev/should-not-cache",
    ]
    for relative in files:
        destination = build / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("fixture", encoding="utf-8")

    env = os.environ.copy()
    env.setdefault("NPM_CONFIG_CACHE", str(tmp_path / "npm-cache"))
    result = subprocess.run(
        [npx, "--yes", "workbox-cli@7.3.0", "generateSW", "web/workbox-config.cjs"],
        cwd=mobile,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode and any(
        marker in result.stderr.lower()
        for marker in (
            "npm error code econnreset",
            "npm error code enotfound",
            "npm error code eai_again",
            "npm error code etimedout",
            "npm error code etarget",
            "network is unreachable",
        )
    ):
        pytest.skip(f"pinned Workbox unavailable in this environment: {result.stderr[-500:]}")
    assert result.returncode == 0, result.stdout + result.stderr

    worker = (build / "service-worker.js").read_text(encoding="utf-8")
    urls = re.findall(r'''["']?url["']?\s*:\s*["']([^"']+)''', worker)
    assert {
        "flutter_bootstrap.js",
        "main.dart.js",
        "manifest.json",
        "apple-touch-icon.png",
        "offline.html",
        "offline.js",
        "assets/AssetManifest.bin.json",
        "assets/FontManifest.json",
        "assets/fonts/app.ttf",
        "assets/images/app.png",
    }.issubset(urls)
    assert {
        "canvaskit/canvaskit.js",
        "canvaskit/canvaskit.wasm",
        "canvaskit/chromium/canvaskit.js",
        "canvaskit/chromium/canvaskit.wasm",
    }.issubset(urls)
    assert not any(
        "index.html" in url
        or "skwasm" in url
        or "wimp" in url
        or "webparagraph" in url
        or url in ("flutter.js", "assets/AssetManifest.bin")
        or url.endswith(".symbols")
        or Path(url).name == "NOTICES"
        or "mayos-api.fly.dev" in url
        for url in urls
    )
    assert "NetworkOnly" in worker and "1e4" in worker and "AbortController" in worker
    assert "fallbackURL:\"offline.html\"" in worker
    assert '"SKIP_WAITING"' in worker
    assert worker.index('"SKIP_WAITING"') < worker.index("self.skipWaiting()")

    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text("landing", encoding="utf-8")
    output = tmp_path / "pages"
    monkeypatch.setenv("MAYOS_API_BASE_URL", "https://mayos-api.fly.dev")
    assemble(build, landing, output)
    assembled_worker = (output / "app/service-worker.js").read_text(encoding="utf-8")
    assembled_urls = re.findall(
        r'''["']?url["']?\s*:\s*["']([^"']+)''', assembled_worker
    )
    assert assembled_urls == urls
    assert (output / "app/offline.js").is_file()


def test_offline_deep_route_runs_arabic_copy_and_retry():
    web = Path(__file__).parents[1] / "mobile/web"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the offline page script")
    harness = textwrap.dedent("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      const {URL} = require('node:url');
      const html = fs.readFileSync(process.env.OFFLINE_HTML, 'utf8');
      const scriptPath = html.match(/<script src="([^"]+)"><\\/script>/)[1];
      const resolved = new URL(scriptPath, 'https://myos.example/app/coach/players/12');
      if (resolved.pathname !== '/app/offline.js') throw new Error(`bad script URL: ${resolved}`);
      const attrs = {};
      const elements = {
        message: {textContent: ''},
        retry: {textContent: '', addEventListener: (name, callback) => { elements.retry.click = callback; }},
      };
      let reloads = 0;
      const context = {
        document: {documentElement: {set lang(value) { attrs.lang = value; }, set dir(value) { attrs.dir = value; }}, getElementById: id => elements[id]},
        localStorage: {getItem: key => key === 'mayos.display_language' ? 'ar' : null},
        navigator: {language: 'en-US'},
        location: {reload: () => reloads++},
      };
      vm.runInNewContext(fs.readFileSync(process.env.OFFLINE_JS, 'utf8'), context);
      if (attrs.lang !== 'ar' || attrs.dir !== 'rtl') throw new Error('Arabic RTL not applied');
      if (elements.retry.textContent !== 'إعادة المحاولة' || !elements.message.textContent.includes('اتصال')) throw new Error('Arabic copy missing');
      elements.retry.click();
      if (reloads !== 1) throw new Error('Retry did not reload');
    """)
    env = os.environ.copy()
    env["OFFLINE_HTML"] = str(web / "offline.html")
    env["OFFLINE_JS"] = str(web / "offline.js")
    result = subprocess.run([node, "-e", harness], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bridge_reconciles_cross_tab_updates_and_only_reloads_after_apply():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the service worker bridge")
    bridge = Path(__file__).parents[1] / "mobile/web/pwa_bridge.js"
    harness = textwrap.dedent("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      class Target {
        constructor() { this.listeners = new Map(); }
        addEventListener(name, callback, options = {}) {
          const listeners = this.listeners.get(name) || [];
          listeners.push({callback, once: options.once === true});
          this.listeners.set(name, listeners);
        }
        dispatchEvent(event) {
          const listeners = this.listeners.get(event.type) || [];
          this.listeners.set(event.type, listeners.filter(listener => !listener.once));
          for (const listener of listeners) listener.callback(event);
        }
        count(name) { return (this.listeners.get(name) || []).length; }
      }
      class MockEvent { constructor(type) { this.type = type; } }
      const window = new Target();
      const serviceWorker = new Target();
      const registration = new Target();
      registration.waiting = null;
      registration.installing = null;
      serviceWorker.controller = null;
      serviceWorker.register = async () => registration;
      serviceWorker.getRegistration = async () => registration;
      const navigator = {serviceWorker};
      let reloads = 0;
      const location = {reload: () => reloads++};
      const states = [];
      window.addEventListener('myos-update-waiting', () => states.push(window.MYOS_UPDATE_WAITING));
      vm.runInNewContext(fs.readFileSync(process.env.BRIDGE_JS, 'utf8'), {window, navigator, location, Event: MockEvent});
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      (async () => {
        await tick();
        if (window.MYOS_UPDATE_WAITING !== false || states.length !== 0) throw new Error('first install reported waiting');
        serviceWorker.controller = {};
        const worker = new Target();
        worker.state = 'installing';
        worker.messages = [];
        worker.postMessage = message => worker.messages.push(message);
        registration.installing = worker;
        registration.dispatchEvent(new MockEvent('updatefound'));
        registration.waiting = worker;
        worker.state = 'installed';
        worker.dispatchEvent(new MockEvent('statechange'));
        if (window.MYOS_UPDATE_WAITING !== true || states.at(-1) !== true) throw new Error('waiting update not reported');

        registration.waiting = null;
        worker.state = 'activating';
        worker.dispatchEvent(new MockEvent('statechange'));
        if (window.MYOS_UPDATE_WAITING !== false || states.at(-1) !== false) throw new Error('waiting state change did not clear waiting');
        serviceWorker.dispatchEvent(new MockEvent('controllerchange'));
        if (window.MYOS_UPDATE_WAITING !== false || states.at(-1) !== false) throw new Error('other tab activation did not clear waiting');
        const listenerCount = serviceWorker.count('controllerchange');
        window.MYOS_APPLY_UPDATE();
        await tick();
        if (worker.messages.length !== 0 || serviceWorker.count('controllerchange') !== listenerCount) throw new Error('apply armed without a waiting worker');

        registration.waiting = worker;
        worker.dispatchEvent(new MockEvent('statechange'));
        window.MYOS_APPLY_UPDATE();
        await tick();
        if (worker.messages.length !== 1 || worker.messages[0].type !== 'SKIP_WAITING') throw new Error('apply did not message the waiting worker');
        serviceWorker.dispatchEvent(new MockEvent('controllerchange'));
        serviceWorker.dispatchEvent(new MockEvent('controllerchange'));
        if (reloads !== 1) throw new Error(`expected one reload, got ${reloads}`);
      })().catch(error => { console.error(error); process.exitCode = 1; });
    """)
    env = os.environ.copy()
    env["BRIDGE_JS"] = str(bridge)
    result = subprocess.run([node, "-e", harness], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bridge_reports_update_already_installing_when_registration_resolves():
    # Debate review #454: updatefound can fire before register() resolves.
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the service worker bridge")
    bridge = Path(__file__).parents[1] / "mobile/web/pwa_bridge.js"
    harness = textwrap.dedent("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      class Target {
        constructor() { this.listeners = new Map(); }
        addEventListener(name, callback) {
          this.listeners.set(name, [...(this.listeners.get(name) || []), callback]);
        }
        dispatchEvent(event) {
          for (const callback of this.listeners.get(event.type) || []) callback(event);
        }
      }
      class MockEvent { constructor(type) { this.type = type; } }
      const window = new Target();
      const serviceWorker = new Target();
      const registration = new Target();
      const worker = new Target();
      worker.state = 'installing';
      registration.installing = worker;
      registration.waiting = null;
      serviceWorker.controller = {};
      serviceWorker.register = async () => registration;
      const navigator = {serviceWorker};
      vm.runInNewContext(fs.readFileSync(process.env.BRIDGE_JS, 'utf8'),
        {window, navigator, location: {reload() {}}, Event: MockEvent});
      setTimeout(() => {
        registration.installing = null;
        registration.waiting = worker;
        worker.state = 'installed';
        worker.dispatchEvent(new MockEvent('statechange'));
        if (window.MYOS_UPDATE_WAITING !== true) {
          console.error('update installing at registration was not reported');
          process.exitCode = 1;
        }
      }, 0);
    """)
    env = os.environ.copy()
    env["BRIDGE_JS"] = str(bridge)
    result = subprocess.run([node, "-e", harness], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_assembly_serves_worker_and_offline_fallback_under_app_with_no_cache(tmp_path):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    (flutter / "index.html").write_text('<base href="/app/">')
    (flutter / "service-worker.js").write_text(
        'precacheAndRoute([{url:"main.dart.js"}]);'
    )
    (flutter / "offline.html").write_text("offline")
    (flutter / "_headers").write_text(
        "/*\n  Content-Security-Policy: worker-src 'self'\n"
        "/service-worker.js\n  Cache-Control: no-cache\n"
        "/offline.html\n  Cache-Control: no-cache\n"
    )
    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text("landing")
    output = tmp_path / "output"
    assemble(flutter, landing, output)
    assert (output / "app/service-worker.js").is_file()
    assert (output / "app/offline.html").read_text() == "offline"
    headers = (output / "_headers").read_text()
    assert "worker-src 'self'" in headers
    assert "/app/service-worker.js\n  Cache-Control: no-cache" in headers
    assert "/app/offline.html\n  Cache-Control: no-cache" in headers
    assert (output / "index.html").read_text() == "landing"
