"""Black-box checks for the static landing site in the assembled Pages folder."""

import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.assemble_web import assemble


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "web_landing"


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []
        self.links = []
        self.copy = []
        self.checks = []
        self.icons = []
        self.screens = []
        self.lazy = set()
        self.tracks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "img", "link"):
            key = "src" if tag in ("script", "img") else "href"
            if attrs.get(key):
                self.resources.append(attrs[key])
                if attrs.get("loading") == "lazy":
                    self.lazy.add(attrs[key])
        if tag == "img" and attrs.get("data-alt-en"):
            self.screens.append(attrs)
        if tag == "a":
            self.links.append(attrs)
        if attrs.get("data-copy"):
            self.copy.append(attrs)
        if tag == "li" and attrs.get("data-copy", "").startswith(("lifter_", "coach_")):
            self.checks.append(attrs)
        if tag == "svg" or "icon" in attrs.get("class", "").split():
            self.icons.append(attrs)
        if attrs.get("data-track"):
            self.tracks.append(attrs["data-track"])


def _assembled(tmp_path):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    (flutter / "index.html").write_text('<base href="/app/">', encoding="utf-8")
    shutil.copyfile(ROOT / "mobile" / "web" / "posthog_init.js", flutter / "posthog_init.js")
    output = tmp_path / "pages"
    assemble(flutter, LANDING, output)
    return output


def _parse_page(output, name="index.html"):
    html = (output / name).read_text(encoding="utf-8")
    parser = LandingParser()
    parser.feed(html)
    return html, parser


def _parse(output):
    return _parse_page(output)


def test_assembled_page_has_working_destinations(tmp_path):
    output = _assembled(tmp_path)
    _html, parser = _parse(output)
    by_id = {link.get("id"): link for link in parser.links if link.get("id")}
    by_contact = {link.get("data-contact"): link for link in parser.links if link.get("data-contact")}
    instagram_links = [link for link in parser.links if link.get("data-contact") == "instagram"]

    assert by_id["login"]["href"] == "/app/login"
    assert by_id["start-free"]["href"] == "/app/register"
    assert by_id["coach-contact-en"]["href"] == "mailto:founders@mayos.online?subject=MAYOS%20coach%20request"
    assert by_id["coach-contact-ar"]["href"] == (
        "mailto:founders@mayos.online?subject=%D8%B7%D9%84%D8%A8%20"
        "%D8%A7%D9%86%D8%B6%D9%85%D8%A7%D9%85%20%D9%85%D8%AF%D8%B1%D8%A8%20%D8%A5%D9%84%D9%89%20%D9%85%D9%8A%D9%88%D8%B3"
    )
    assert len(instagram_links) == 2
    assert all(link["href"] == "https://www.instagram.com/mayosapp" for link in instagram_links)
    assert by_contact["instagram"]["aria-label"] == "Instagram @mayosapp"
    assert by_contact["instagram"]["title"] == "Instagram @mayosapp"
    assert by_contact["tiktok"]["href"] == "https://www.tiktok.com/@mayosapp"
    assert by_contact["tiktok"]["aria-label"] == "TikTok @mayosapp"
    assert by_contact["tiktok"]["title"] == "TikTok @mayosapp"
    assert by_contact["email"]["href"] == "mailto:founders@mayos.online"
    assert by_id["privacy-link"]["href"] == "https://api.mayos.online/privacy"
    assert by_id["deletion-link"]["href"] == "/account-deletion"


def test_assembled_page_has_expected_copy_in_both_languages(tmp_path):
    _output = _assembled(tmp_path)
    _html, parser = _parse(_output)
    english = {slot["data-copy"]: slot.get("data-en", "") for slot in parser.copy}
    arabic = {slot["data-copy"]: slot.get("data-ar", "") for slot in parser.copy}
    expected_english = {
        "page_title": "MAYOS — Your training. Engineered.",
        "page_description": (
            "MAYOS uses AI to build your training program around your goal, "
            "schedule and equipment. Log every set and watch your strength grow."
        ),
        "nav_lifters": "For lifters", "nav_coaches": "For coaches",
        "login": "Log in", "language_toggle": "العربية", "eyebrow": "AI-built training programs",
        "hero_title_1": "Your training.", "hero_title_2": "Engineered.",
        "hero_line": "MAYOS uses AI to build your training program around your goal, schedule and equipment. Log every set and watch your strength grow. Free to start on the web.",
        "start_free": "Start free",
        "benefit_1_title": "AI-built plans", "benefit_1": "Sets, reps and rest planned for your goal.",
        "benefit_2_title": "Log every set", "benefit_2": "Weight, reps and reps in reserve, as you train.",
        "benefit_3_title": "See your progress", "benefit_3": "Estimated 1RM, weekly volume and records.",
        "audience_title": "Built for lifters and the coaches who train them.",
        "audience_line": "Train on your own, or coach your players, with the same tools.",
        "lifters_label": "For lifters", "lifters_title": "A plan built around you.",
        "lifter_1": "An AI-built program for your goal and equipment", "lifter_2": "Log every set, rep and RIR",
        "lifter_3": "Track your estimated 1RM over time", "lifter_4": "Offline logging in the Android app",
        "lifters_cta": "Build your free program",
        "coaches_label": "For coaches", "coaches_title": "Your players, in one place.",
        "coach_1": "Manage your players in one roster", "coach_2": "Write and assign programs",
        "coach_3": "Alerts when a player misses sessions", "coach_4": "An AI assistant that drafts programs with you",
        "coach_action": "Request coach access", "coach_instagram": "or message us on Instagram",
        "cta_title": "Start your progress today.", "cta_line": "Free to start on the web. Built for lifters and coaches.",
        "contact_heading": "Contact", "privacy": "Privacy policy",
        "deletion": "Delete account",
    }
    expected_arabic = {
        "page_title": "MAYOS — تمرينك. مدروس.",
        "page_description": (
            "يبني ميوس برنامج تمرينك بالذكاء الاصطناعي حسب هدفك ووقتك والأدوات "
            "المتاحة لك. سجّل كل مجموعة وتابع قوتك وهي تزيد."
        ),
        "nav_lifters": "للاعبين", "nav_coaches": "للمدربين",
        "login": "تسجيل الدخول", "language_toggle": "English", "eyebrow": "برامج تمرين بالذكاء الاصطناعي",
        "hero_title_1": "تمرينك.", "hero_title_2": "مدروس.",
        "hero_line": "يبني ميوس برنامج تمرينك بالذكاء الاصطناعي حسب هدفك ووقتك والأدوات المتاحة لك. سجّل كل مجموعة وتابع قوتك وهي تزيد. ابدأ مجانًا على الويب.",
        "start_free": "ابدأ مجانًا",
        "benefit_1_title": "خطط بالذكاء الاصطناعي", "benefit_1": "المجموعات والتكرارات والراحة حسب هدفك.",
        "benefit_2_title": "سجّل كل مجموعة", "benefit_2": "الوزن والتكرارات والتكرارات المتبقية أثناء التمرين.",
        "benefit_3_title": "تابع تقدّمك", "benefit_3": "الحد الأقصى التقديري والحجم الأسبوعي والأرقام القياسية.",
        "audience_title": "مصمّم للاعبين وللمدربين الذين يدرّبونهم.",
        "audience_line": "تمرّن بنفسك، أو درّب لاعبيك، بالأدوات نفسها.",
        "lifters_label": "للاعبين", "lifters_title": "برنامج مبني عليك.",
        "lifter_1": "برنامج بالذكاء الاصطناعي لهدفك وأدواتك", "lifter_2": "سجّل كل مجموعة وتكرار والتكرارات المتبقية",
        "lifter_3": "تابع الحد الأقصى التقديري مع الوقت", "lifter_4": "تسجيل بدون إنترنت في تطبيق أندرويد",
        "lifters_cta": "ابنِ برنامجك المجاني",
        "coaches_label": "للمدربين", "coaches_title": "لاعبوك في مكان واحد.",
        "coach_1": "أدِر لاعبيك في قائمة واحدة", "coach_2": "اكتب البرامج وخصّصها للاعبيك",
        "coach_3": "تنبيهات عندما يفوّت اللاعب جلساته", "coach_4": "مساعد ذكي يكتب مسودات البرامج معك",
        "coach_action": "اطلب حساب مدرب", "coach_instagram": "أو راسلنا على إنستغرام",
        "cta_title": "ابدأ تقدّمك اليوم.", "cta_line": "مجاني للبدء على الويب. مصمّم للاعبين والمدربين.",
        "contact_heading": "تواصل معنا", "privacy": "سياسة الخصوصية",
        "deletion": "حذف الحساب",
    }
    assert english == expected_english
    assert arabic == expected_arabic


def test_assembled_page_tracks_the_three_conversion_events_without_store_badges(tmp_path):
    output = _assembled(tmp_path)
    html, parser = _parse(output)

    assert set(parser.tracks) == {"landing_start_free", "landing_login", "landing_coach_contact"}
    assert "data-store-badge" not in html
    assert not any(resource.endswith((".svg", ".png")) for resource in parser.resources)


def test_page_shows_real_app_screens_with_localized_alt_text(tmp_path):
    output = _assembled(tmp_path)
    html, parser = _parse(output)
    screens = {screen["src"]: screen for screen in parser.screens}
    assert set(screens) == {
        "/screen-logger.webp", "/screen-home.webp", "/screen-progress.webp",
        "/screen-program.webp", "/screen-coach.webp",
    }
    for src, screen in screens.items():
        assert (output / src.lstrip("/")).is_file()
        assert screen["data-alt-en"] and screen["data-alt-ar"]
        assert screen["alt"] == screen["data-alt-ar"]
    assert {"/screen-program.webp", "/screen-progress.webp", "/screen-coach.webp"} <= parser.lazy
    assert len(parser.checks) == 8
    assert all(icon.get("aria-hidden") == "true" for icon in parser.icons)
    footer = re.search(r'<footer\b.*?</footer>', html, re.S).group(0)
    assert 'id="privacy-link"' in footer
    assert 'id="deletion-link"' in footer


def test_page_is_dark_rtl_by_default_and_footer_links_meet_tap_target(tmp_path):
    output = _assembled(tmp_path)
    html, _parser = _parse(output)
    assert '<html lang="ar" dir="rtl">' in html
    assert re.search(r':root\{color-scheme:dark;', html)
    assert re.search(r'\.social\{[^}]*width:44px;height:44px', html)
    assert re.search(r'\.footer-link\{[^}]*min-height:44px', html)


def _run_landing_js(output, scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the landing page behavior harness")
    harness = textwrap.dedent("""
        const fs = require('node:fs');
        const [landingPath, configPath] = process.argv.slice(1);
        const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
        const storage = Object.assign({}, scenario.storage || {});
        storage.getItem = key => Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null;
        storage.setItem = (key, value) => { storage[key] = value; };
        const attributes = {};
        const nav = {setAttribute: (key, value) => { attributes[key] = value; }};
        const toggle = {setAttribute: () => {}, addEventListener: () => {}};
        global.localStorage = storage;
        global.location = new URL('https://www.mayos.example/' + (scenario.search || ''));
        global.location.replace = value => { scenario.replaced = value; };
        global.document = {
          referrer: scenario.referrer || '', title: '',
          documentElement: {dataset: {}, removeAttribute: () => {}},
          body: {dataset: {page: scenario.page || ''}},
          querySelector: selector => selector === 'nav' ? nav : null,
          querySelectorAll: () => [],
          getElementById: () => toggle,
          addEventListener: () => {},
          createElement: () => ({})
        };
        Object.defineProperty(globalThis, 'navigator', {
          value: {languages: ['en'], language: 'en'}, configurable: true
        });
        global.matchMedia = () => ({matches: false});
        global.requestAnimationFrame = () => {};
        global.window = {MAYOS_LANDING: {}};
        (0, eval)(fs.readFileSync(configPath, 'utf8'));
        (0, eval)(fs.readFileSync(landingPath, 'utf8'));
        process.stdout.write(JSON.stringify({storage, replaced: scenario.replaced || null}));
    """)
    result = subprocess.run(
        [node, "-e", harness, str(output / "landing.js"), str(output / "landing-config.js")],
        input=json.dumps(scenario), text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_external_referrer_and_utm_are_saved_as_first_touch(tmp_path):
    output = _assembled(tmp_path)
    result = _run_landing_js(output, {
        "search": "?utm_source=Newsletter&utm_medium=Email&utm_campaign=Autumn",
        "referrer": "https://BLOG.Example.org/story",
    })
    assert json.loads(result["storage"]["mayos.first_touch"]) == {
        "utm_source": "Newsletter", "utm_medium": "Email", "utm_campaign": "Autumn",
        "referrer_host": "blog.example.org",
    }


def test_same_host_referrer_without_utm_does_not_save_first_touch(tmp_path):
    output = _assembled(tmp_path)
    result = _run_landing_js(output, {"referrer": "https://WWW.MAYOS.EXAMPLE/page"})
    assert "mayos.first_touch" not in result["storage"]


def test_existing_first_touch_is_not_overwritten(tmp_path):
    output = _assembled(tmp_path)
    existing = '{"utm_source":"original"}'
    result = _run_landing_js(output, {
        "search": "?utm_source=new", "referrer": "https://outside.example/",
        "storage": {"mayos.first_touch": existing},
    })
    assert result["storage"]["mayos.first_touch"] == existing


def test_signed_in_landing_redirects_to_app(tmp_path):
    output = _assembled(tmp_path)
    result = _run_landing_js(output, {
        "storage": {"FlutterSecureStorage.mayos.access_token": "token"},
    })
    assert result["replaced"] == "/app/"


def test_signed_in_visitor_stays_on_the_deletion_page(tmp_path):
    # Someone signed in on this browser may still need the public deletion
    # form (another device, another account), so the page never redirects.
    output = _assembled(tmp_path)
    assert (output / "account-deletion.html").is_file()
    result = _run_landing_js(output, {
        "page": "account-deletion",
        "storage": {"FlutterSecureStorage.mayos.access_token": "token"},
    })
    assert result["replaced"] is None


def test_account_deletion_page_explains_deletion_and_reuses_the_api_form(tmp_path):
    output = _assembled(tmp_path)
    html, parser = _parse_page(output, "account-deletion.html")

    # Stays reachable for signed-in visitors: the redirect guard reads this.
    assert '<body data-page="account-deletion">' in html

    english = {slot["data-copy"]: slot.get("data-en", "") for slot in parser.copy}
    arabic = {slot["data-copy"]: slot.get("data-ar", "") for slot in parser.copy}
    expected_english = {
        "page_title": "Delete your MAYOS account",
        "page_description": (
            "How to delete your MAYOS account in the app, or request deletion "
            "from this page without the app."
        ),
        "language_toggle": "العربية",
        "heading": "Delete your MAYOS account.",
        "lead": "Deletion is immediate and permanent, and you can do it yourself. You do not need to contact anyone.",
        "in_app_title": "From the app",
        "in_app_line": (
            "Open Settings → Linked sign-in → Danger zone → Delete account, "
            "then confirm with your password. If you signed in with Google, "
            "confirm with Google instead."
        ),
        "web_title": "Without the app",
        "web_line": (
            "If you cannot open the app — for example on a lost device — use the "
            "public deletion form on our server. It asks for your username and "
            "password and one confirmation, and applies the same deletion as the app."
        ),
        "web_action": "Open the deletion form",
        "email_action": "or write to us at founders@mayos.online",
        "web_note": (
            "The form never reveals whether a username exists: unknown usernames "
            "and wrong passwords get the same answer. If you have lost your "
            "password, request a reset first — the form page links to it. Write "
            "to us by email only when the form cannot work for you (for example "
            "a deleted recovery email); we will verify you are the account owner "
            "before deleting anything."
        ),
        "removed_title": "What is deleted",
        "removed_1": (
            "Your training ledger: profile, Training program, workouts, schedule, "
            "Nutrition setup and targets, Food log entries and Personal foods, and "
            "your assistant chat."
        ),
        "removed_2": "Your recovery email and reset tokens, your invites, and every signed-in session.",
        "removed_3": "Any active coaching assignment ends immediately; your coach loses access to your history.",
        "kept_title": "What is kept, and for how long",
        "kept_1": (
            "A small deletion record (internal ids and the time) stays outside the "
            "backups so a restore cannot bring the account back."
        ),
        "kept_2": "Model-usage rows keyed only by an opaque id stay for cost reconciliation.",
        "kept_3": "Whole-catalog recovery snapshots may briefly retain deleted rows for up to 30 days.",
        "back": "Back to mayos.online",
        "privacy": "Privacy policy",
    }
    expected_arabic = {
        "page_title": "حذف حسابك في ميوس",
        "page_description": "كيفية حذف حسابك في ميوس من التطبيق، أو طلب الحذف من هذه الصفحة بدون التطبيق.",
        "language_toggle": "English",
        "heading": "احذف حسابك في ميوس.",
        "lead": "الحذف فوري ونهائي، ويمكنك القيام به بنفسك. لا تحتاج إلى مراسلة أحد.",
        "in_app_title": "من التطبيق",
        "in_app_line": (
            "افتح الإعدادات ← تسجيل الدخول المرتبط ← منطقة الخطر ← حذف الحساب، "
            "ثم أكّد بكلمة المرور. إذا سجّلت الدخول بحساب Google، فأكّد بحساب "
            "Google بدلًا منها."
        ),
        "web_title": "بدون التطبيق",
        "web_line": (
            "إذا تعذّر فتح التطبيق — مثلًا على جهاز مفقود — استخدم نموذج الحذف العام "
            "على خادمنا. يطلب اسم المستخدم وكلمة المرور وتأكيدًا واحدًا، ويطبّق الحذف "
            "نفسه كما في التطبيق."
        ),
        "web_action": "افتح نموذج الحذف",
        "email_action": "أو راسلنا على founders@mayos.online",
        "web_note": (
            "لا يكشف النموذج أبدًا عن وجود اسم مستخدم: الأسماء غير المسجلة وكلمات "
            "المرور الخاطئة تحصل على الرد نفسه. إذا فقدت كلمة المرور، فاطلب إعادة "
            "التعيين أولًا — صفحة النموذج تربط بها. راسلنا بالبريد فقط عندما يعجز "
            "النموذج (مثلًا بعد حذف بريد الاسترداد)؛ سنتحقق أنك مالك الحساب قبل أي حذف."
        ),
        "removed_title": "ما الذي يُحذف",
        "removed_1": (
            "سجل تدريبك: الملف التدريبي، البرنامج التدريبي، الحصص التدريبية، جدول "
            "التدريب، إعداد التغذية وأهدافها، سجل الطعام والأطعمة الخاصة، ومحادثتك "
            "مع المساعد."
        ),
        "removed_2": "بريد الاسترداد ورموز إعادة التعيين، ودعواتك، وكل جلسات تسجيل الدخول.",
        "removed_3": "تنتهي فورًا أي علاقة تدريب نشطة؛ ويفقد المدرب الوصول إلى سجلك.",
        "kept_title": "ما الذي نحتفظ به ومدة الاحتفاظ",
        "kept_1": "يبقى سجل حذف صغير (معرّفات داخلية ووقت الحذف) خارج النسخ الاحتياطية حتى لا تُعيد نسخة مستعادة الحساب.",
        "kept_2": "تبقى صفوف استخدام النماذج، المرتبطة بمعرّف مجهول فقط، لمطابقة التكاليف.",
        "kept_3": "قد تحتفظ لقطات استعادة الكتالوج بالكامل بصفوف محذوفة لمدة تصل إلى 30 يومًا.",
        "back": "العودة إلى mayos.online",
        "privacy": "سياسة الخصوصية",
    }
    assert english == expected_english
    assert arabic == expected_arabic

    by_id = {link.get("id"): link for link in parser.links if link.get("id")}
    # The public form is the existing rate-limited API endpoint: no second
    # deletion implementation on the landing host.
    assert by_id["delete-request-link"]["href"] == "https://api.mayos.online/account/delete-request"
    assert by_id["deletion-email-link"]["href"] == (
        "mailto:founders@mayos.online?subject=MAYOS%20account%20deletion%20request"
    )
    assert by_id["privacy-link"]["href"] == "https://api.mayos.online/privacy"
    assert by_id["back-link"]["href"] == "/"


def test_first_paint_resources_stay_under_300_kib(tmp_path):
    output = _assembled(tmp_path)
    _html, parser = _parse(output)
    loaded = {"index.html"}
    pending = list(parser.resources)
    pending.extend(re.findall("url\\([\'\"]?([^)\'\"]+)", (output / "index.html").read_text(encoding="utf-8")))
    while pending:
        resource = pending.pop()
        if resource in parser.lazy:
            continue
        parsed = urlsplit(resource)
        assert not parsed.scheme and not parsed.netloc, f"outside origin: {resource}"
        path = resource.split("?", 1)[0].lstrip("/")
        if path in loaded:
            continue
        assert (output / path).is_file(), f"missing first-load resource: {resource}"
        loaded.add(path)
        if path.endswith(".css"):
            css = (output / path).read_text(encoding="utf-8")
            pending.extend(re.findall("url\\([\'\"]?([^)\'\"]+)", css))
    total = sum((output / path).stat().st_size for path in loaded)
    assert total < 300 * 1024, f"first-load resources weigh {total} bytes: {sorted(loaded)}"


def test_assembly_injects_deploy_time_values_without_a_posthog_key(tmp_path, monkeypatch):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    monkeypatch.setenv("MAYOS_API_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("POSTHOG_CLIENT_KEY", "")
    output = tmp_path / "pages"

    assemble(flutter, LANDING, output)

    config = json.loads(
        (output / "landing-config.js").read_text(encoding="utf-8")
        .removeprefix("window.MAYOS_LANDING = ").removesuffix(";\n")
    )
    assert config == {"posthogKey": ""}
    html, parser = _parse(output)
    by_id = {link.get("id"): link for link in parser.links if link.get("id")}
    assert by_id["privacy-link"]["href"] == "https://api.example.test/privacy"
