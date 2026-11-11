from pathlib import Path
import os
import re
import shutil
import subprocess
import textwrap

from scripts.assemble_web import assert_service_worker_safe
from scripts.assemble_web import assemble
import pytest


def test_generated_worker_precaches_document_but_not_api_or_cross_origin_data():
    api = "https://api.mayos.online"
    assert_service_worker_safe(
        'self.__WB_MANIFEST = [{"url":"main.dart.js"},{"url":"index.html"},'
        '{"url":"offline.html"}]', api
    )
    for worker in (
        f'self.__WB_MANIFEST = [{{"url":"{api}/v1/me"}}]',
        'self.__WB_MANIFEST = [{"url":"https://analytics.example/event"},'
        '{"url":"index.html"},{"url":"offline.html"}]',
        'self.__WB_MANIFEST = [{"url":"main.dart.js"}]',
    ):
        try:
            assert_service_worker_safe(worker, api)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe generated worker accepted")


def test_generated_precache_excludes_canvas_kit_symbols_and_notices():
    worker = (
        'precacheAndRoute([{url:"index.html"},{url:"offline.html"},'
        '{url:"main.dart.js"},'
        '{url:"canvaskit/canvaskit.js"},'
        '{url:"canvaskit/skwasm.js"},'
        '{url:"assets/example.symbols"},{url:"assets/NOTICES"}]);'
    )
    try:
        assert_service_worker_safe(worker, "https://api.mayos.online")
    except ValueError as error:
        assert "precache" in str(error)
    else:
        raise AssertionError("oversized precache entries were accepted")


def test_issue_708_generated_worker_falls_back_offline_and_assembles_manifest(
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
        "manifest.json", "favicon.png", "apple-touch-icon.png", "mayos-icon-192.png",
        "mayos-loading-wallpaper.jpg", "mayos-lockup-white.png", "safe_area.js",
        "posthog_init.js", "pwa_bridge.js",
        "offline.html", "offline.js", "canvaskit/canvaskit.js",
        "canvaskit/canvaskit.wasm", "canvaskit/chromium/canvaskit.js",
        "canvaskit/chromium/canvaskit.wasm", "canvaskit/skwasm.js",
        "canvaskit/skwasm.wasm", "canvaskit/skwasm_heavy.js", "canvaskit/wimp.js",
        "canvaskit/webparagraph/canvaskit.js", "canvaskit/canvaskit.js.symbols",
        "assets/AssetManifest.bin", "assets/AssetManifest.bin.json",
        "assets/FontManifest.json", "assets/fonts/app.ttf", "assets/images/app.png",
        "assets/NOTICES", "https://api.mayos.online/should-not-cache",
    ]
    for relative in files:
        destination = build / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        contents = (
            '<script src="safe_area.js"></script>'
            '<script src="posthog_init.js"></script>'
            '<script src="pwa_bridge.js"></script>'
            '<script src="flutter_bootstrap.js"></script>'
            if relative == "index.html" else "fixture"
        )
        destination.write_text(contents, encoding="utf-8")

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
        "index.html",
        "flutter_bootstrap.js",
        "main.dart.js",
        "safe_area.js",
        "posthog_init.js",
        "pwa_bridge.js",
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
        "skwasm" in url
        or "wimp" in url
        or "webparagraph" in url
        or url in ("flutter.js", "assets/AssetManifest.bin")
        or url.endswith(".symbols")
        or Path(url).name == "NOTICES"
        or "api.mayos.online" in url
        for url in urls
    )
    assert "NetworkOnly" in worker and "1e4" in worker and "AbortController" in worker
    assert "caches.keys()" in worker and "offline.html" in worker
    assert '"SKIP_WAITING"' in worker
    assert worker.index('"SKIP_WAITING"') < worker.index("self.skipWaiting()")

    harness = textwrap.dedent("""
      const fs = require('node:fs');
      const path = require('node:path');
      const vm = require('node:vm');
      const {URL} = require('node:url');
      const workerPath = process.env.SERVICE_WORKER_PATH;
      const workerSource = fs.readFileSync(workerPath, 'utf8');
      const moduleSpecifier = workerSource.match(/define\\(\\s*\\[\\s*['\"](\\.\\/workbox-[^'\"]+)['\"]/)?.[1];
      if (!moduleSpecifier) throw new Error('generated worker has no Workbox module dependency');
      const modulePath = path.resolve(path.dirname(workerPath), moduleSpecifier);
      const resolvedModulePath = fs.existsSync(modulePath) ? modulePath : `${modulePath}.js`;
      if (!fs.existsSync(resolvedModulePath)) throw new Error(`Workbox module is missing: ${moduleSpecifier}`);
      const origin = 'https://mayos.example';
      const scope = `${origin}/app/`;
      let fetchAttempts = 0;
      class ServiceWorkerRequest {
        constructor(input, options = {}) {
          const source = input instanceof ServiceWorkerRequest ? input : null;
          this.url = source ? source.url : new URL(input, scope).href;
          this.mode = options.mode || (source && source.mode) || 'navigate';
          this.method = options.method || (source && source.method) || 'GET';
          this.signal = options.signal || (source && source.signal);
          this.headers = options.headers || (source && source.headers) || {};
        }
      }
      class ServiceWorkerResponse {
        constructor(body) { this.body = body; this.status = 200; }
        clone() { return new ServiceWorkerResponse(this.body); }
        async text() { return this.body; }
      }
      const cacheEntries = new Map([
        [`${scope}index.html?__WB_REVISION__=abc`, new ServiceWorkerResponse('app document')],
        [`${scope}offline.html?__WB_REVISION__=def`, new ServiceWorkerResponse('offline page')],
      ]);
      const makeCache = entries => ({
        async match(request, options = {}) {
          const wanted = new URL(request.url || request, scope);
          for (const [key, response] of entries) {
            const cached = new URL(key);
            if (cached.href === wanted.href || (options.ignoreSearch && cached.origin === wanted.origin && cached.pathname === wanted.pathname)) {
              return response.clone();
            }
          }
          return undefined;
        },
      });
      const cacheStorage = new Map([
        ['runtime-cache', makeCache(new Map([[`${scope}index.html`, new ServiceWorkerResponse('wrong runtime copy')]]))],
        ['workbox-precache-v2-mayos', makeCache(cacheEntries)],
      ]);
      const sandbox = {
        URL,
        Request: ServiceWorkerRequest,
        Response: ServiceWorkerResponse,
        AbortController,
        setTimeout,
        clearTimeout,
        console,
        caches: {
          async keys() { return [...cacheStorage.keys()]; },
          async open(name) { return cacheStorage.get(name); },
        },
        async fetch() {
          fetchAttempts++;
          throw new TypeError('offline');
        },
        addEventListener() {},
        registration: {scope},
        location: {origin, href: scope},
        clients: {claim: async () => {}},
        skipWaiting: async () => {},
      };
      sandbox.self = sandbox;
      const context = vm.createContext(sandbox);
      context.self = context;
      let workboxModule;
      const moduleRegistry = new Map();
      context.define = (nameOrDependencies, dependenciesOrFactory, maybeFactory) => {
        let name = null;
        let dependencies = [];
        let factory;
        if (typeof nameOrDependencies === 'string') {
          name = nameOrDependencies;
          if (Array.isArray(dependenciesOrFactory)) {
            dependencies = dependenciesOrFactory;
            factory = maybeFactory;
          } else {
            factory = dependenciesOrFactory;
          }
        } else if (Array.isArray(nameOrDependencies)) {
          dependencies = nameOrDependencies;
          factory = dependenciesOrFactory;
        } else {
          factory = nameOrDependencies;
        }
        const moduleExports = {};
        const module = {exports: moduleExports};
        const imports = dependencies.map(dependency => {
          if (dependency === 'exports') return moduleExports;
          if (dependency === 'module') return module;
          if (dependency === 'require') return imported => moduleRegistry.get(imported);
          return moduleRegistry.get(dependency);
        });
        const exported = typeof factory === 'function' ? factory(...imports) : factory;
        workboxModule = exported === undefined ? module.exports : exported;
        if (name) moduleRegistry.set(name, workboxModule);
      };
      context.define.amd = {};
      vm.runInContext(fs.readFileSync(resolvedModulePath, 'utf8'), context, {filename: resolvedModulePath});
      if (!workboxModule) throw new Error('Workbox module did not export its runtime');

      const registrations = [];
      const overrides = {
        clientsClaim: () => {},
        cleanupOutdatedCaches: () => {},
        precacheAndRoute: () => {},
        setConfig: () => {},
        registerRoute: (matcher, strategy) => registrations.push({matcher, strategy}),
        NetworkOnly: class { constructor(options) { this.plugins = options.plugins; } },
      };
      const exposeWorkbox = module => new Proxy(module, {
        get(target, property) {
          if (Object.prototype.hasOwnProperty.call(overrides, property)) return overrides[property];
          const exported = Reflect.get(target, property, target);
          return exported && typeof exported === 'object' ? exposeWorkbox(exported) :
            typeof exported === 'function' ? exported.bind(target) : exported;
        },
      });
      context.define = (dependencies, factory) => {
        const imports = dependencies.map(dependency => {
          if (dependency !== moduleSpecifier) throw new Error(`unexpected generated dependency: ${dependency}`);
          return exposeWorkbox(workboxModule.default || workboxModule);
        });
        factory(...imports);
      };
      vm.runInContext(workerSource, context, {filename: workerPath});

      const runOfflineNavigation = async route => {
        const request = new ServiceWorkerRequest(new URL(route, origin), {mode: 'navigate'});
        const matchedRoute = registrations.find(({matcher}) => matcher({url: new URL(request.url), request}));
        if (!matchedRoute) throw new Error(`app route was not registered: ${route}`);
        let activeRequest = request;
        const state = {};
        for (const plugin of matchedRoute.strategy.plugins) {
          if (plugin.requestWillFetch) activeRequest = await plugin.requestWillFetch({request: activeRequest, state});
        }
        try {
          return await sandbox.fetch(activeRequest);
        } catch (error) {
          for (const plugin of matchedRoute.strategy.plugins) {
            if (plugin.fetchDidFail) await plugin.fetchDidFail({request: activeRequest, state, error});
          }
          for (const plugin of matchedRoute.strategy.plugins) {
            if (plugin.handlerDidError) {
              const fallback = await plugin.handlerDidError({request: activeRequest, state, error});
              if (fallback) return fallback;
            }
          }
          throw error;
        }
      };
      (async () => {
        for (const route of ['/landing/', 'https://api.mayos.online/v1/me']) {
          const request = new ServiceWorkerRequest(new URL(route, origin), {mode: 'navigate'});
          if (registrations.some(({matcher}) => matcher({url: new URL(request.url), request}))) {
            throw new Error(`non-app route was registered: ${route}`);
          }
        }
        for (const route of ['/app/', '/app/coach/players/12']) {
          const response = await runOfflineNavigation(route);
          if (await response.text() !== 'app document') throw new Error(`wrong offline response for ${route}`);
        }
        cacheEntries.delete(`${scope}index.html?__WB_REVISION__=abc`);
        const offlineResponse = await runOfflineNavigation('/app/coach/players/12');
        if (await offlineResponse.text() !== 'offline page') throw new Error('offline page was not returned when index.html was missing');
        if (fetchAttempts !== 3) throw new Error(`expected three failed network requests, got ${fetchAttempts}`);
      })().catch(error => { console.error(error); process.exitCode = 1; });
    """)
    env["SERVICE_WORKER_PATH"] = str(build / "service-worker.js")
    result = subprocess.run(
        [node, "-e", harness], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr

    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text("landing", encoding="utf-8")
    output = tmp_path / "pages"
    monkeypatch.setenv("MAYOS_API_BASE_URL", "https://api.mayos.online")
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
      const resolved = new URL(scriptPath, 'https://mayos.example/app/coach/players/12');
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
      window.addEventListener('mayos-update-waiting', () => states.push(window.MAYOS_UPDATE_WAITING));
      vm.runInNewContext(fs.readFileSync(process.env.BRIDGE_JS, 'utf8'), {window, navigator, location, Event: MockEvent});
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      (async () => {
        await tick();
        if (window.MAYOS_UPDATE_WAITING !== false || states.length !== 0) throw new Error('first install reported waiting');
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
        if (window.MAYOS_UPDATE_WAITING !== true || states.at(-1) !== true) throw new Error('waiting update not reported');

        registration.waiting = null;
        worker.state = 'activating';
        worker.dispatchEvent(new MockEvent('statechange'));
        if (window.MAYOS_UPDATE_WAITING !== false || states.at(-1) !== false) throw new Error('waiting state change did not clear waiting');
        serviceWorker.dispatchEvent(new MockEvent('controllerchange'));
        if (window.MAYOS_UPDATE_WAITING !== false || states.at(-1) !== false) throw new Error('other tab activation did not clear waiting');
        const listenerCount = serviceWorker.count('controllerchange');
        window.MAYOS_APPLY_UPDATE();
        await tick();
        if (worker.messages.length !== 0 || serviceWorker.count('controllerchange') !== listenerCount) throw new Error('apply armed without a waiting worker');

        registration.waiting = worker;
        worker.dispatchEvent(new MockEvent('statechange'));
        window.MAYOS_APPLY_UPDATE();
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
        if (window.MAYOS_UPDATE_WAITING !== true) {
          console.error('update installing at registration was not reported');
          process.exitCode = 1;
        }
      }, 0);
    """)
    env = os.environ.copy()
    env["BRIDGE_JS"] = str(bridge)
    result = subprocess.run([node, "-e", harness], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bridge_captures_and_prompts_for_install_before_flutter_boot():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the install bridge")
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
      const navigator = {};
      const events = [];
      window.addEventListener('mayos-install-state', () => events.push('state'));
      window.addEventListener('mayos-app-installed', () => events.push('installed'));
      vm.runInNewContext(fs.readFileSync(process.env.BRIDGE_JS, 'utf8'),
        {window, navigator, location: {}, Event: MockEvent});
      (async () => {
        let prevented = false;
        let prompted = false;
        const installEvent = new MockEvent('beforeinstallprompt');
        installEvent.preventDefault = () => { prevented = true; };
        installEvent.prompt = async () => { prompted = true; };
        installEvent.userChoice = Promise.resolve({outcome: 'accepted'});
        window.dispatchEvent(installEvent);
        if (!prevented || !window.MAYOS_INSTALL_PROMPT_AVAILABLE) throw new Error('prompt was not captured');
        if (await window.MAYOS_PROMPT_INSTALL() !== 'accepted' || !prompted) throw new Error('accepted outcome missing');
        if (window.MAYOS_INSTALL_PROMPT_AVAILABLE) throw new Error('prompt remained available');
        window.dispatchEvent(new MockEvent('appinstalled'));
        if (!events.includes('installed')) throw new Error('installed event missing');
        if (!window.MAYOS_APP_INSTALLED) throw new Error('installed state was not retained');
        if (!window.MAYOS_CONSUME_APP_INSTALLED()) throw new Error('installed state was not consumable');
        if (window.MAYOS_CONSUME_APP_INSTALLED()) throw new Error('installed state was not consumed once');
      })().catch(error => { console.error(error); process.exitCode = 1; });
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
        'precacheAndRoute([{url:"index.html"},{url:"offline.html"}]);'
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
