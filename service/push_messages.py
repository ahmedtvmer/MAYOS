"""Supportive, bilingual reminder rotation. Facts are optional, never invented."""

import random

# Stable ids make the rolling exclusion window survive restarts and language changes.
MESSAGES = {
    "start": ("A little movement can brighten your day. Start at your own pace.", "القليل من الحركة قد يجعل يومك أجمل. ابدأ بالوتيرة المناسبة لك."),
    "space": ("Your training time is a little space for you. Enjoy it.", "وقت تدريبك مساحة صغيرة لك. استمتع بها."),
    "small": ("Small steps count. See how you feel after your warm-up.", "الخطوات الصغيرة مهمة. جرّب الإحماء وراقب شعورك."),
    "steady": ("One comfortable set at a time. You've got room to grow.", "مجموعة مريحة في كل مرة. لديك مساحة للتقدم."),
    "care": ("Make room for movement and take care of yourself today.", "امنح نفسك بعض الحركة واعتنِ بنفسك اليوم."),
    "enjoy": ("A fresh chance to enjoy moving. Choose a pace that feels good.", "فرصة جديدة للاستمتاع بالحركة. اختر وتيرة مريحة لك."),
    "ready": ("Your next session is ready whenever you are.", "حصتك التدريبية التالية جاهزة عندما تكون مستعدًا."),
    "breathe": ("Take a breath, warm up gently, and see where today takes you.", "خذ نفسًا وابدأ بإحماء هادئ، ثم استكشف ما يناسبك اليوم."),
    "session": ("Your session is ready for you today. Start gently and enjoy it.", "\u062d\u0635\u062a\u0643 \u0627\u0644\u062a\u062f\u0631\u064a\u0628\u064a\u0629 \u062c\u0627\u0647\u0632\u0629 \u0627\u0644\u064a\u0648\u0645. \u0627\u0628\u062f\u0623 \u0628\u0647\u062f\u0648\u0621 \u0648\u0627\u0633\u062a\u0645\u062a\u0639 \u0628\u0627\u0644\u062a\u062f\u0631\u064a\u0628."),
    "streak": ("You've built a {streak}-week streak. Enjoy another step at your own pace.", "حققت {streak} من أسابيع الالتزام المتتالية. استمتع بخطوة أخرى بالوتيرة المناسبة لك."),
    "return": ("Welcome back. An easy start is a great way to return to movement.", "أهلًا بعودتك. البداية الهادئة طريقة رائعة للعودة إلى الحركة."),
}


def choose_reminder(language, recent_ids, *, session_ready=False, streak=0, returning=False):
    context = {"streak": streak}
    candidates = list(MESSAGES)[:8]
    candidates += [key for key, available in (("session", session_ready), ("streak", streak),
                                             ("return", returning)) if available]
    # Five recent sends are excluded even across restarts; the base pool has eight.
    available = [key for key in candidates if key not in recent_ids[:5]]
    contextual = [key for key in available if key in ("session", "streak", "return")]
    key = random.choice(contextual or available)
    body = MESSAGES[key][1 if language.startswith("ar") else 0].format(**context)
    return key, body


EVENT_COPY = {
    "coach_alert": ("A Player has a new alert. Open your alerts to review it.", "لدى أحد اللاعبين تنبيه جديد. افتح التنبيهات لمراجعته."),
    "program_request": ("A Player sent a program request.", "أرسل أحد اللاعبين طلبًا بخصوص البرنامج التدريبي."),
    "food_swap_request": ("A Player sent a Food swap request.", "أرسل أحد اللاعبين طلب تبديل طعام."),
    "program_published": ("Your coach published your Training program.", "نشر مدربك برنامجك التدريبي."),
    "nutrition_published": ("Your coach published your Nutrition plan.", "نشر مدربك خطة تغذيتك."),
    "swap_reply": ("Your coach replied to your request.", "رد مدربك على طلبك."),
    "self_coach_slip": ("A little support for your training is ready. Open MAYOS when it suits you.", "بعض الدعم لتدريبك جاهز. افتح MAYOS عندما يناسبك."),
}

ROUTES = {
    "coach_alert": "/coach/alerts?push=coach", "program_request": "/coach/requests?push=coach",
    "food_swap_request": "/coach/requests?push=coach",
    "program_published": "/home?push=program", "nutrition_published": "/home?push=nutrition",
    "swap_reply": "/player-notifications?push=player", "food_swap_reply": "/food-swap-requests?push=player",
    "workout_reminder": "/home?push=program", "self_coach_slip": "/home?push=player",
}
