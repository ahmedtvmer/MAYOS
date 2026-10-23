import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.assemble_web import assemble


ROOT = Path(__file__).resolve().parents[1]


def test_assembled_app_manifest_and_ios_shell_support_installation(tmp_path):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    (flutter / "index.html").write_text(
        (ROOT / "mobile" / "web" / "index.html").read_text(encoding="utf-8").replace(
            "$FLUTTER_BASE_HREF", "/app/"
        ),
        encoding="utf-8",
    )
    (flutter / "manifest.json").write_text(
        (ROOT / "mobile" / "web" / "manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    shutil.copyfile(ROOT / "mobile" / "web" / "safe_area.js", flutter / "safe_area.js")
    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text("landing", encoding="utf-8")
    output = tmp_path / "output"
    assemble(flutter, landing, output)

    manifest = json.loads((output / "app" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["start_url"] == "/app/"
    assert manifest["scope"] == "/app/"
    assert manifest["name"] == manifest["short_name"] == "MYOS"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == manifest["background_color"] == "#0A1422"
    assert {(icon["sizes"], icon.get("purpose")) for icon in manifest["icons"]} == {
        ("192x192", None),
        ("512x512", None),
        ("512x512", "maskable"),
    }

    host = (output / "app" / "index.html").read_text(encoding="utf-8")
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in host
    assert '<meta name="apple-mobile-web-app-title" content="MYOS">' in host
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in host
    assert '<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">' in host
    assert 'name="viewport"' in host
    assert "viewport-fit=cover" not in host
    assert '<script src="safe_area.js"></script>' in host
    assert (output / "app" / "safe_area.js").is_file()
    assert (output / "index.html").read_text(encoding="utf-8") == "landing"


def test_safe_area_script_only_enables_viewport_fit_in_standalone():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; cannot execute safe_area.js behavior")

    harness = r'''
const fs = require('fs');
const vm = require('vm');
const script = fs.readFileSync(process.argv[1], 'utf8');
const standalone = process.argv[2] === 'standalone';
const metas = [];
function viewportMeta(content) {
  const attributes = {name: 'viewport', content};
  return {
    getAttribute(name) { return attributes[name] || null; },
    setAttribute(name, value) { attributes[name] = value; },
    content() { return attributes.content; }
  };
}
metas.push(viewportMeta('width=device-width, initial-scale=1.0'));
let observerCallback;
class MutationObserver {
  constructor(callback) { observerCallback = callback; }
  observe() {}
}
const context = {
  document: {
    head: {},
    querySelectorAll() { return metas; }
  },
  window: {matchMedia() { return {matches: standalone}; }},
  navigator: {standalone: false},
  MutationObserver
};
vm.runInNewContext(script, context);
metas[0] = viewportMeta(
  'width=device-width, initial-scale=1.0, maximum-scale=5.0'
);
observerCallback();
console.log(metas[0].content());
'''
    script_path = ROOT / "mobile" / "web" / "safe_area.js"
    standalone = subprocess.run(
        [node, "-e", harness, str(script_path), "standalone"],
        check=True,
        capture_output=True,
        text=True,
    )
    browser = subprocess.run(
        [node, "-e", harness, str(script_path), "browser"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert standalone.stdout.strip() == (
        "width=device-width, initial-scale=1.0, maximum-scale=5.0, "
        "viewport-fit=cover"
    )
    assert browser.stdout.strip() == (
        "width=device-width, initial-scale=1.0, maximum-scale=5.0"
    )
