"""Black-box checks for the static landing site in the assembled Pages folder."""

import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from scripts.assemble_web import assemble


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "web_landing"


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []
        self.links = []
        self.copy = []
        self.features = []
        self.feature_icons = 0
        self.feature_icon_attributes = []
        self.tracks = []
        self.badges = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "img", "link"):
            key = "src" if tag in ("script", "img") else "href"
            if attrs.get(key):
                self.resources.append(attrs[key])
        if tag == "a":
            self.links.append(attrs)
        if attrs.get("data-copy"):
            self.copy.append(attrs)
        if tag == "li" and (attrs.get("data-copy", "").startswith("lifter_") or
                             attrs.get("data-copy", "").startswith("coach_")):
            self.features.append(attrs)
        if tag == "svg":
            self.feature_icons += 1
            self.feature_icon_attributes.append(attrs)
        if attrs.get("data-track"):
            self.tracks.append(attrs["data-track"])
        if "data-store-badge" in attrs:
            self.badges.append((tag, attrs))


def _assembled(tmp_path):
    flutter = tmp_path / "flutter"
    flutter.mkdir()
    (flutter / "index.html").write_text('<base href="/app/">', encoding="utf-8")
    shutil.copyfile(ROOT / "mobile" / "web" / "posthog_init.js", flutter / "posthog_init.js")
    output = tmp_path / "pages"
    assemble(flutter, LANDING, output)
    return output


def _parse(output):
    html = (output / "index.html").read_text(encoding="utf-8")
    parser = LandingParser()
    parser.feed(html)
    return html, parser


def test_assembled_page_exposes_working_destinations_and_localized_copy(tmp_path):
    output = _assembled(tmp_path)
    html, parser = _parse(output)
    by_id = {link.get("id"): link for link in parser.links if link.get("id")}
    by_contact = {link.get("data-contact"): link for link in parser.links if link.get("data-contact")}

    assert by_id["login"]["href"] == "/app/login"
    assert by_id["start-free"]["href"] == "/app/register"
    assert by_id["coach-contact-en"]["href"] == "mailto:ahmedtamerhejazi@gmail.com?subject=MYOS%20coach%20request"
    assert by_id["coach-contact-ar"]["href"] == (
        "mailto:ahmedtamerhejazi@gmail.com?subject=%D8%B7%D9%84%D8%A8%20"
        "%D8%A7%D9%86%D8%B6%D9%85%D8%A7%D9%85%20%D9%85%D8%AF%D8%B1%D8%A8%20%D8%A5%D9%84%D9%89%20%D9%85%D9%8A%D9%88%D8%B3"
    )
    assert by_contact["instagram"]["href"] == "https://instagram.com/ahmedtvmer"
    assert by_contact["tiktok"]["href"] == "https://tiktok.com/@ahmedforges"
    assert by_contact["email"]["href"] == "mailto:ahmedtamerhejazi@gmail.com"
    assert by_id["privacy-link"]["href"] == "https://mayos-api.fly.dev/privacy"

    english = {slot["data-copy"]: slot.get("data-en", "") for slot in parser.copy}
    arabic = {slot["data-copy"]: slot.get("data-ar", "") for slot in parser.copy}
    expected_english = {
        "login": "Log in", "language_toggle": "العربية", "tagline": "Progress, Engineered.",
        "hero_line": "Training programs, set-by-set logging and coaching, in one app. Free to start on the web.",
        "start_free": "Start free", "coming_soon": "Coming soon", "lifters_heading": "For lifters",
        "lifter_1": "Get a program built around your goal, your schedule and the equipment you have.",
        "lifter_2": "Log every set as you train.", "lifter_3": "See your history and progress over time.",
        "lifter_4": "Ask the MYOS assistant about your training.", "coaches_heading": "For coaches",
        "coach_1": "Keep all your players in one roster.",
        "coach_2": "Write programs and assign them, or let MYOS draft them for you.",
        "coach_3": "Follow each player's workouts and history.",
        "coach_4": "Swap exercises from a library with video demos.",
        "coach_action": "Become a MYOS coach", "coach_instagram": "Message us on Instagram",
        "name_heading": "Why MYOS",
        "name_story": 'MYOS comes from the Greek <em>mys</em>, a word that meant both "mouse" and "muscle". The Romans saw it too: in Latin, <em>musculus</em> means "little mouse", because a flexed muscle moving under the skin looks like a small mouse running beneath it. That\'s where the English word <em>muscle</em> comes from.',
        "contact_heading": "Contact", "privacy": "Privacy policy",
    }
    expected_arabic = {
        "login": "تسجيل الدخول", "language_toggle": "English", "tagline": "تقدّمٌ مدروس.",
        "hero_line": "برامج تمرين، وتسجيل لكل مجموعة، وتدريب، في تطبيق واحد. ابدأ مجانًا على الويب.",
        "start_free": "ابدأ مجانًا", "coming_soon": "قريبًا", "lifters_heading": "للاعبين",
        "lifter_1": "احصل على برنامج مبني على هدفك ووقتك والأدوات المتاحة لك.",
        "lifter_2": "سجّل كل مجموعة أثناء تمرينك.", "lifter_3": "تابع سجلّ تمارينك وتقدّمك مع الوقت.",
        "lifter_4": "اسأل مساعد ميوس عن تمرينك.", "coaches_heading": "للمدربين",
        "coach_1": "كل لاعبيك في قائمة واحدة.",
        "coach_2": "اكتب البرامج وخصّصها للاعبيك، أو دع ميوس يكتب لك مسودتها.",
        "coach_3": "تابع تمارين كل لاعب وسجلّه.",
        "coach_4": "بدّل التمارين من مكتبة فيها فيديوهات توضيحية.",
        "coach_action": "انضم مدربًا في ميوس", "coach_instagram": "راسلنا على إنستغرام",
        "name_heading": "لماذا ميوس",
        "name_story": "اسم ميوس مأخوذ من الكلمة اليونانية <em>μῦς</em>، وكانت تعني «الفأر» و«العضلة» معًا. ورأى الرومان الشيء نفسه، فكلمة <em>musculus</em> اللاتينية تعني «الفأر الصغير»، لأن العضلة حين تنقبض وتتحرك تحت الجلد تشبه فأرًا صغيرًا يجري تحته. ومنها جاءت كلمة <em>muscle</em> في الإنجليزية.",
        "contact_heading": "تواصل معنا", "privacy": "سياسة الخصوصية",
    }
    assert english == expected_english
    assert arabic == expected_arabic
    assert "Progress, Engineered." in html and "تقدّمٌ مدروس." in html

    assert set(parser.tracks) >= {
        "landing_start_free", "landing_login", "landing_coach_contact", "landing_store_badge"
    }
    for tag, attrs in parser.badges:
        assert tag == "span" and attrs.get("aria-disabled") == "true"
        assert "href" not in attrs
    badge_sources = {
        resource for resource in parser.resources
        if resource.endswith((".svg", ".png"))
    }
    assert {"/google-play-ar.png", "/app-store-en.svg"} <= badge_sources
    assert not any("app-store-ar" in resource for resource in parser.resources)
    assert len(parser.features) == 8
    assert parser.feature_icons == 8
    assert all(icon.get("aria-hidden") == "true" for icon in parser.feature_icon_attributes)
    story_word = re.search(r'class="story-word"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert '<bdi dir="ltr">μῦς</bdi>' in story_word
    footer = re.search(r'<footer\b.*?</footer>', html, re.S).group(0)
    assert "min-height:44px" in (output / "index.html").read_text(encoding="utf-8")
    assert "id=\"privacy-link\"" in footer


def test_first_paint_follows_system_theme_and_footer_links_meet_tap_target(tmp_path):
    output = _assembled(tmp_path)
    html, _parser = _parse(output)
    assert '<html lang="ar" dir="rtl">' in html
    assert re.search(r'@media\(prefers-color-scheme:dark\)\{:root:not\(\[data-theme="light"\]\)', html)
    assert re.search(r'\.footer-top>a\{[^}]*min-height:44px', html)
    assert re.search(r'\.contact-links a\{[^}]*min-height:44px', html)


def test_attribution_is_first_touch_only_and_uses_app_storage_shape(tmp_path):
    output = _assembled(tmp_path)
    javascript = (output / "landing.js").read_text(encoding="utf-8")
    assert "mayos.first_touch" in javascript
    assert "utm_source" in javascript and "utm_medium" in javascript and "utm_campaign" in javascript
    assert "referrer_host" in javascript
    assert "referrer.hostname.toLowerCase() !== location.hostname.toLowerCase()" in javascript
    assert "localStorage.getItem(firstTouchKey) !== null" in javascript
    assert "JSON.stringify(touch)" in javascript


def test_first_paint_resources_stay_under_300_kib(tmp_path):
    output = _assembled(tmp_path)
    _html, parser = _parse(output)
    loaded = {"index.html"}
    pending = list(parser.resources)
    pending.extend(re.findall("url\\([\'\"]?([^)\'\"]+)", (output / "index.html").read_text(encoding="utf-8")))
    while pending:
        resource = pending.pop()
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
    monkeypatch.setenv("GOOGLE_PLAY_URL", "https://play.example.test/app")
    monkeypatch.setenv("APP_STORE_URL", "https://apps.example.test/app")
    output = tmp_path / "pages"

    assemble(flutter, LANDING, output)

    config = json.loads(
        (output / "landing-config.js").read_text(encoding="utf-8")
        .removeprefix("window.MYOS_LANDING = ").removesuffix(";\n")
    )
    assert config["posthogKey"] == ""
    assert config["googlePlayUrl"] == "https://play.example.test/app"
    assert config["appStoreUrl"] == "https://apps.example.test/app"
    html, parser = _parse(output)
    by_id = {link.get("id"): link for link in parser.links if link.get("id")}
    assert by_id["privacy-link"]["href"] == "https://api.example.test/privacy"
