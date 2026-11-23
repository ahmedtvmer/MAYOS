"""Deterministic Player context routing for Cardio and Nutrition history."""

import json
from datetime import date, timedelta

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from agent import assistant_graph, context_router, player_tools
from service import nutrition
from tests.fakes.chat_model import ScriptedChatModel
from tests.test_player_chat_privacy import (
    api,  # noqa: F401 (pytest fixture)
    _authed,
    _done_content,
    _force_free_form_coaching_intent,
    _register,
)


TODAY = date(2026, 11, 16)

PERSONAL_ROUTING_CASES = [
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, "en",
     "How many calories did I eat today?"),
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, "en",
     "How much protein have I eaten today?"),
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, "eg", "سعراتي كام؟"),
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, "eg", "بروتيني كام؟"),
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, "msa",
     "كم بروتين تناولت اليوم؟"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "en",
     "Have I hit my protein target today?"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "eg",
     "هل حققت هدفي من البروتين اليوم؟"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "msa",
     "كم بروتين متبقي لتحقيق هدفي اليوم؟"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "en",
     "How much protein do I have left today?"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "eg",
     "فاضل لي كام بروتين عشان أوصل لهدفي النهارده؟"),
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, "msa",
     "كم بروتين متبقي لي من هدفي اليوم؟"),
    ("targets_only", "today", "get_player_nutrition", {}, "en",
     "What are my nutrition targets?"),
    ("targets_only", "today", "get_player_nutrition", {}, "eg", "أهدافي الغذائية كام؟"),
    ("targets_only", "today", "get_player_nutrition", {}, "msa", "ما هي أهدافي الغذائية؟"),
    ("nutrition_trend", "last_n_days", "get_player_nutrition_trend", {"days": 14}, "en",
     "Show my protein trend for the last 14 days"),
    ("nutrition_trend", "last_n_days", "get_player_nutrition_trend", {"days": 7}, "eg",
     "وريني متوسط بروتيني آخر ٧ أيام"),
    ("nutrition_trend", "last_n_days", "get_player_nutrition_trend", {"days": 7}, "msa",
     "ما اتجاه بروتيني خلال آخر ٧ أيام؟"),
    ("cardio_performed", "this_week", "get_player_cardio", {"days": 3}, "en",
     "How much cardio did I do this week alongside my program?"),
    ("cardio_performed", "this_week", "get_player_cardio", {"days": 3}, "eg",
     "عملت كارديو قد ايه الاسبوع ده جنب برنامجي؟"),
    ("cardio_performed", "this_week", "get_player_cardio", {"days": 3}, "msa",
     "كم دقيقة كارديو مارست هذا الأسبوع إلى جانب برنامجي؟"),
    ("cardio_prescribed", "today", "get_active_program", {}, "en",
     "How many minutes of cardio are in my program?"),
    ("cardio_prescribed", "today", "get_active_program", {}, "eg", "كام دقيقة كارديو في برنامجي؟"),
    ("cardio_prescribed", "today", "get_active_program", {}, "msa",
     "كم دقيقة من تمارين الكارديو في برنامجي؟"),
]

PERSONAL_PERIOD_CASES = [
    ("today", "get_player_food_log", {"day": "today"}, "en", "What did I eat today?"),
    ("today", "get_player_food_log", {"day": "today"}, "eg", "اكلت ايه النهارده؟"),
    ("today", "get_player_food_log", {"day": "today"}, "msa", "ماذا أكلت اليوم؟"),
    ("yesterday", "get_player_food_log", {"day": "yesterday"}, "en", "What did I eat yesterday?"),
    ("yesterday", "get_player_food_log", {"day": "yesterday"}, "eg", "اكلت ايه امبارح؟"),
    ("yesterday", "get_player_food_log", {"day": "yesterday"}, "msa", "ماذا أكلت أمس؟"),
    ("explicit_date", "get_player_food_log", {"day": "2026-11-15"}, "en",
     "What did I eat on 2026-11-15?"),
    ("explicit_date", "get_player_food_log", {"day": "2026-11-15"}, "eg",
     "أكلت إيه يوم 2026-11-15؟"),
    ("explicit_date", "get_player_food_log", {"day": "2026-11-15"}, "msa",
     "ماذا أكلت في 2026-11-15؟"),
    ("this_week", "get_player_nutrition_trend", {"days": 3}, "en",
     "How many calories have I logged this week?"),
    ("this_week", "get_player_nutrition_trend", {"days": 3}, "eg", "اكلت كام بروتين الاسبوع ده؟"),
    ("this_week", "get_player_nutrition_trend", {"days": 3}, "msa", "كم بروتين تناولت هذا الأسبوع؟"),
    ("last_n_days", "get_player_nutrition_trend", {"days": 7}, "en",
     "How many calories have I logged in the last 7 days?"),
    ("last_n_days", "get_player_nutrition_trend", {"days": 7}, "eg",
     "سجلت كام بروتين خلال آخر ٧ أيام؟"),
    ("last_n_days", "get_player_nutrition_trend", {"days": 7}, "msa",
     "كم بروتين سجلت في آخر ٧ أيام؟"),
]

# #735 round 4: language variants exercise intent classes, including privacy boundaries.
PERSONAL_FACT_CASES = [
    ("en", "How much protein did I consume?"),
    ("en", "Show my food log"),
    ("en", "What is my daily calorie intake?"),
    ("eg", "وريني سجل أكلي"),
    ("eg", "أنا أكلت كام سعر النهارده؟"),
    ("eg", "سجلت كام جرام بروتين؟"),
    ("msa", "اعرض سجل وجباتي"),
    ("msa", "كم سعرة تناولت اليوم؟"),
    ("msa", "ما إجمالي البروتين الذي تناولته؟"),
    ("en", "What did I have for breakfast today?"),
    ("en", "What did I drink today?"),
    ("en", "How much protein have I had today?"),
    ("eg", "فطرت إيه النهارده؟"),
    ("eg", "أنا اتغديت إيه النهارده؟"),
    ("eg", "شربت كام بروتين النهارده؟"),
    ("msa", "ماذا شربت اليوم؟"),
    ("msa", "ما الذي تناولته في الغداء اليوم؟"),
    ("msa", "كم بروتين استهلكت اليوم؟"),
]
GENERAL_KNOWLEDGE_CASES = [
    ("en", "what is protein's role in my body"),
    ("en", "how do I compare protein powders"),
    ("eg", "يعني ايه بروتين"),
    ("en", "Why does my body need protein?"),
    ("en", "How can I choose a protein powder?"),
    ("en", "Can I learn how calories work?"),
    ("eg", "البروتين بيعمل إيه في جسمي؟"),
    ("eg", "إزاي أقارن أنواع البروتين؟"),
    ("eg", "أنا محتاج أفهم يعني إيه سعرات"),
    ("msa", "ما دور البروتين في جسمي؟"),
    ("msa", "كيف أقارن مساحيق البروتين؟"),
    ("msa", "هل يمكنني فهم فوائد الدهون؟"),
    ("en", "How do I compare my protein powders?"),
    ("en", "How many calories are in my protein powder?"),
    ("eg", "أقارن إزاي البروتين البودر اللي عندي؟"),
    ("eg", "كام سعر في بودرة البروتين اللي عندي؟"),
    ("msa", "كيف أقارن مساحيق البروتين الخاصة بي؟"),
    ("msa", "كم سعرة في مسحوق البروتين الذي عندي؟"),
]
NUTRITION_GOAL_CASES = [
    ("en", "Show my calorie goals"),
    ("en", "What are my saved nutrition targets?"),
    ("en", "Show my nutrition plan"),
    ("eg", "وريني أهدافي الغذائية"),
    ("eg", "هدفي من البروتين كام؟"),
    ("eg", "خطة التغذية بتاعتي إيه؟"),
    ("msa", "اعرض أهدافي من السعرات"),
    ("msa", "ما هدفي الغذائي؟"),
    ("msa", "ما خطة التغذية الخاصة بي؟"),
]
TRAINING_GOAL_CASES = [
    ("en", "What are my training goals?"),
    ("en", "Show my strength goals"),
    ("en", "How can I reach my running goal?"),
    ("eg", "أهدافي في التمرين إيه؟"),
    ("eg", "وريني هدفي في الجري"),
    ("eg", "أنا وصلت لهدفي في القوة؟"),
    ("msa", "ما أهدافي التدريبية؟"),
    ("msa", "اعرض هدفي في رفع الأثقال"),
    ("msa", "هل حققت أهدافي الرياضية؟"),
    ("en", "Have I reached my running goal by eating more protein?"),
    ("eg", "هل حققت هدفي في الجري بزيادة البروتين؟"),
    ("msa", "ما أهدافي التدريبية عند زيادة البروتين؟"),
]
RANGE_CASES = [
    ("intake_recall", "last_n_days", 3, "en", "How much protein did I eat in the past 3 days?"),
    ("nutrition_trend", "last_n_days", 1, "en", "Show my calorie trend for the last 1 day"),
    ("intake_recall", "this_week", 3, "en", "What is my protein intake this week?"),
    ("intake_recall", "last_n_days", 3, "eg", "أكلت كام بروتين آخر ٣ أيام؟"),
    ("nutrition_trend", "last_n_days", 5, "eg", "وريني متوسط سعراتي آخر ٥ أيام"),
    ("intake_recall", "this_week", 3, "eg", "إجمالي أكلي الأسبوع ده كام؟"),
    ("intake_recall", "last_n_days", 3, "msa", "كم بروتين تناولت خلال آخر ٣ أيام؟"),
    ("nutrition_trend", "last_n_days", 14, "msa", "اعرض اتجاه سعراتي خلال آخر ١٤ يوما"),
    ("intake_recall", "this_week", 3, "msa", "ما إجمالي السعرات التي سجلتها هذا الأسبوع؟"),
]
DATED_TOTAL_CASES = [
    ("yesterday", "yesterday", "en", "what were my calories yesterday"),
    ("yesterday", "yesterday", "en", "What was my protein yesterday?"),
    ("explicit_date", "2026-11-15", "en", "What were my carbs on 2026-11-15?"),
    ("explicit_date", "2026-11-14", "en", "How much fat did I log on 2026-11-14?"),
    ("yesterday", "yesterday", "eg", "سعراتي امبارح كام؟"),
    ("yesterday", "yesterday", "eg", "بروتيني مبارح كان قد إيه؟"),
    ("explicit_date", "2026-11-15", "eg", "وريني إجمالي سعراتي يوم 2026-11-15"),
    ("yesterday", "yesterday", "msa", "كم بلغت سعراتي أمس؟"),
    ("explicit_date", "2026-11-15", "msa", "ما إجمالي بروتيني في 2026-11-15؟"),
    ("yesterday", "yesterday", "msa", "كم كان مجموع الدهون التي تناولتها البارح؟"),
]
CARDIO_HISTORY_CASES = [
    ("en", "show my cardio history"),
    ("en", "my last cardio session"),
    ("eg", "وريني سجل الكارديو بتاعي"),
    ("eg", "كام دقيقة كارديو عملتها"),
    ("en", "Show my recent cardio sessions"),
    ("en", "What is in my cardio log?"),
    ("en", "How much cardio have I performed?"),
    ("eg", "وريني آخر جلسة كارديو بتاعتي"),
    ("eg", "سجلي في الكارديو عامل إزاي؟"),
    ("eg", "كام دقيقة كارديو لعبتها؟"),
    ("msa", "اعرض تاريخ الكارديو الخاص بي"),
    ("msa", "ما آخر جلسة كارديو لي؟"),
    ("msa", "كم دقيقة كارديو مارستها؟"),
]
CARDIO_RANGE_CASES = [
    ("last_n_days", 3, "en", "Show my cardio history for the past 3 days"),
    ("last_n_days", 1, "en", "How much cardio did I log in the last 1 day?"),
    ("this_week", 3, "en", "Show my cardio log this week"),
    ("last_n_days", 3, "eg", "وريني سجل الكارديو بتاعي آخر ٣ أيام"),
    ("last_n_days", 7, "eg", "عملت كام دقيقة كارديو آخر ٧ أيام؟"),
    ("this_week", 3, "eg", "كام دقيقة كارديو عملتها الأسبوع ده؟"),
    ("last_n_days", 3, "msa", "اعرض سجل الكارديو الخاص بي خلال آخر ٣ أيام"),
    ("last_n_days", 14, "msa", "كم دقيقة كارديو مارست خلال آخر ١٤ يوما؟"),
    ("this_week", 3, "msa", "كم دقيقة كارديو أنجزتها هذا الأسبوع؟"),
]
CARDIO_PRESCRIPTION_CASES = [
    ("en", "How much cardio should I do in my program?"),
    ("en", "Show cardio in my training program"),
    ("en", "What cardio is prescribed in my program?"),
    ("eg", "الكارديو في برنامجي كام دقيقة؟"),
    ("eg", "وريني كارديو برنامجي"),
    ("eg", "أعمل كام كارديو في البرنامج بتاعي؟"),
    ("msa", "ما الكارديو المقرر في برنامجي؟"),
    ("msa", "اعرض دقائق الكارديو في برنامجي"),
    ("msa", "كم كارديو ينبغي أن أمارس في برنامجي؟"),
]
GENERAL_CARDIO_CASES = [
    ("en", "What is cardio?"),
    ("en", "How can I start cardio?"),
    ("en", "How much cardio is healthy?"),
    ("eg", "يعني إيه كارديو؟"),
    ("eg", "الكارديو مفيد ليا إزاي؟"),
    ("eg", "أبدأ كارديو إزاي؟"),
    ("msa", "ما فوائد الكارديو؟"),
    ("msa", "كيف أبدأ ممارسة الكارديو؟"),
    ("msa", "ما الفرق بين الكارديو والمشي؟"),
    ("en", "What is the history of cardio?"),
    ("eg", "يعني إيه سجل الكارديو؟"),
    ("msa", "ما المقصود بسجل الكارديو؟"),
]
GENERAL_PERIOD_CASES = [
    ("this_week", "en", "How do I compare protein powders this week?"),
    ("this_week", "eg", "أقارن إزاي أنواع البروتين الأسبوع ده؟"),
    ("this_week", "msa", "كيف أختار مسحوق البروتين هذا الأسبوع؟"),
    ("yesterday", "en", "What was protein's role in my body yesterday?"),
    ("yesterday", "eg", "البروتين كان بيعمل إيه في جسمي امبارح؟"),
    ("explicit_date", "msa", "ما دور الدهون في جسمي يوم 2026-11-15؟"),
]
TARGET_RANGE_CASES = [
    ("en", "Did I hit my protein target in the last 3 days?"),
    ("eg", "هل حققت هدفي من البروتين آخر ٣ أيام؟"),
    ("msa", "كم بروتين متبقي لي من هدفي هذا الأسبوع؟"),
]


def _backdate_nutrition_plan_to_earlier_today(ledger) -> None:
    # save_nutrition_setup stamps the plan with the real clock; pin created_at to
    # earlier on the pinned Player-local TODAY so the dated target lookup sees a
    # plan saved earlier that day.
    created_at = f"{TODAY.isoformat()}T08:00:00+00:00"
    ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
    ledger.conn.execute("UPDATE nutrition_plan_versions SET created_at=?", (created_at,))
    ledger.conn.execute(
        "CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
        "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
    ledger.conn.commit()


def _add_food(ledger, entry_date=TODAY, name="Player lunch snapshot"):
    nutrients = {
        "energy_kcal": 620, "protein_g": 45,
        "carbohydrate_g": 72, "fat_g": 16,
    }
    ledger.insert_food_log_entry({
        "id": f"assistant-log-entry-{entry_date.isoformat()}",
        "entry_date": entry_date.isoformat(),
        "logged_time": "12:30", "meal_label": "lunch", "kind": "library_food",
        "food_id": "assistant-private-food", "name": name,
        "arabic_name": None, "grams": 250, "unit": "grams", "quantity": 250,
        "portion_label": None, "portion_grams": None,
        "nutrients_per_100g": nutrients, "nutrients": nutrients,
        "created_at": f"{entry_date.isoformat()}T12:30:00+00:00",
    })


@pytest.fixture
def personal_log_player(api, monkeypatch):
    client, db = api
    username = "assistant-personal-log-player"
    headers = _authed(_register(client, username)["access_token"])
    monkeypatch.setattr(player_tools, "player_local_date", lambda *_args: TODAY)
    with db.open_ledger(username) as ledger:
        ledger.upsert_player_profile({
            "gender": "male", "age": 30, "height_cm": 175.0, "weight_kg": 75.0,
            "current_goal": "get stronger", "weekly_frequency": 3,
        })
        plan = nutrition.setup(ledger, {
            "sex": "male", "daily_activity": "mostly_sitting",
            "screening": {"pregnant_or_breastfeeding": False,
                          "medical_condition": False, "eating_disorder": False},
        }, TODAY)
        assert plan["state"] == "ready"
        _backdate_nutrition_plan_to_earlier_today(ledger)
        _add_food(ledger)
        ledger.log_workout_session(
            "assistant-cardio-session", TODAY.isoformat(), "Cardio",
            f"{TODAY.isoformat()}T10:00:00Z", f"{TODAY.isoformat()}T10:30:00Z",
        )
        ledger.log_session_cardio("assistant-cardio-session", [{
            "machine": "bike", "minutes": 30, "level": 5,
            "calories_kcal": 180, "calories_are_estimate": True,
        }], f"{TODAY.isoformat()}T10:30:00Z")
    return client, db, headers, int(plan["targets"]["protein_g"])


@pytest.fixture
def empty_personal_log_player(api, monkeypatch):
    client, db = api
    username = "assistant-empty-log-player"
    headers = _authed(_register(client, username)["access_token"])
    other_username = "assistant-other-private-food-log"
    _register(client, other_username)
    monkeypatch.setattr(player_tools, "player_local_date", lambda *_args: TODAY)
    with db.open_ledger(other_username) as other_ledger:
        _add_food(other_ledger)
    return client, db, headers


def _routed_reads(model):
    messages = model.calls[0]["messages"]
    calls = [call for message in messages for call in getattr(message, "tool_calls", [])]
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in results] == [call["id"] for call in calls]
    return [(call["name"], json.loads(result.content)) for call, result in zip(calls, results, strict=True)]


# Round 5: independently authored phrasings cover each failure class, including
# negatives that must never disclose saved records to the hosted model.
HOW_TO_ADVICE_CASES = [
    ("en", "How do I use my food log?"),
    ("eg", "أستخدم سجل أكلي إزاي؟"),
    ("msa", "كيف أستخدم سجل وجباتي؟"),
    ("en", "What should I eat before my cardio session?"),
    ("en", "How can I start my food log today?"),
    ("en", "How to edit my meal log from yesterday?"),
    ("en", "Teach me how to record meals in my food log"),
    ("en", "Should I drink protein before my cardio sessions?"),
    ("en", "Give me tips for keeping my food log"),
    ("eg", "إزاي أضيف وجبة في سجل أكلي؟"),
    ("eg", "أسجل فطاري في سجل أكلي إزاي؟"),
    ("msa", "كيف أحذف وجبة من سجل وجباتي؟"),
    ("msa", "ماذا ينبغي أن أتناول قبل جلسة الكارديو الخاصة بي؟"),
    ("en", "Don't read my food log; explain how to use it"),
    ("en", "How does my food log work?"),
    ("en", "Can you suggest food for my cardio session?"),
    ("eg", "سجل أكلي يعني إيه؟"),
    ("msa", "كيف يعمل سجل وجباتي؟"),
    ("en", "How many calories should I enter in my food log?"),
    ("en", "How many entries can I add to my food log?"),
    ("en", "Could I use my cardio history to plan next week?"),
    ("eg", "أهدافي الغذائية أغيرها إزاي؟"),
    ("en", "How do I use my food log alongside my program?"),
    ("en", "What should I eat before my cardio session in my program?"),
    ("en", "How do I use my cardio history with my program?"),
    ("en", "Why is my cardio history useful?"),
    ("en", "What is my cardio log used for?"),
    ("en", "What are the benefits of my food log?"),
]
HYPOTHETICAL_INTAKE_CASES = [
    ("en", "If I ate 2 eggs, how much protein would I get?"),
    ("eg", "لو أكلت بيضتين يبقى أكلت كام بروتين؟"),
    ("msa", "إذا تناولت بيضتين، كم بروتين سأحصل عليه؟"),
    ("en", "What if I had eaten chicken today, how much protein is that?"),
    ("en", "Suppose I consumed two shakes; how many calories would I have?"),
    ("en", "Imagine I drank milk for breakfast: what is my protein intake?"),
    ("en", "If I didn't eat lunch yesterday, how many calories would I miss?"),
    ("en", "If my intake was only eggs, would I hit my protein target?"),
    ("eg", "لو كنت أكلت فول النهارده، أكلت كام بروتين؟"),
    ("eg", "لو ما أكلتش غير بيض، بروتيني كام؟"),
    ("msa", "بافتراض أنني تناولت الأرز، كم سعرة تناولت؟"),
    ("msa", "إذا لم أشرب الحليب اليوم، كم بروتين سيتبقى لي؟"),
    ("en", "Without reading my food log, if I ate rice how many carbs is that?"),
    ("eg", "لو ماكلتش غير فول، بروتيني كام؟"),
    ("eg", "لو هاكل فراخ، بروتيني كام؟"),
    ("en", "If I ate eggs before my program's workouts, how much protein would I get?"),
]
CARDIO_DAY_CASES = [
    ("today", "today", "en", "How much cardio did I do today?"),
    ("yesterday", "yesterday", "en", "How much cardio did I do yesterday?"),
    ("explicit_date", "2026-11-15", "en", "How much cardio did I do on 2026-11-15?"),
    ("yesterday", "yesterday", "msa", "كم دقيقة كارديو مارست أمس؟"),
    ("today", "today", "en", "Did I log any cardio today?"),
    ("yesterday", "yesterday", "en", "Show my cardio log from last night"),
    ("explicit_date", "2026-11-14", "en", "What is in my cardio log on 2026-11-14?"),
    ("today", "today", "eg", "عملت كام دقيقة كارديو النهاردة؟"),
    ("yesterday", "yesterday", "eg", "وريني سجل الكارديو بتاعي امبارح"),
    ("explicit_date", "2026-11-15", "eg", "لعبت كارديو قد إيه يوم 2026-11-15؟"),
    ("today", "today", "msa", "كم دقيقة كارديو مارست اليوم؟"),
    ("yesterday", "yesterday", "msa", "هل سجلت كارديو البارح؟"),
    ("explicit_date", "2026-11-14", "msa", "اعرض تاريخ الكارديو الخاص بي في 2026-11-14"),
    ("today", "today", "en", "Did I not do any cardio today?"),
]
ENDPOINT_RANGE_CASES = [
    ("this_week", 3, "en", "How much protein have I eaten this week up to today?"),
    ("this_week", 3, "msa", "كم بروتين تناولت هذا الأسبوع حتى اليوم؟"),
    ("this_week", 3, "en", "Today, show my food intake this week so far"),
    ("this_week", 3, "en", "How many calories did I log this week including today?"),
    ("last_n_days", 3, "en", "How much protein have I consumed in the last 3 days through today?"),
    ("last_n_days", 7, "en", "Show my calorie trend for the past 7 days ending today"),
    ("this_week", 3, "eg", "أكلت كام بروتين الأسبوع ده لحد النهارده؟"),
    ("this_week", 3, "eg", "النهاردة وريني إجمالي أكلي الأسبوع ده"),
    ("last_n_days", 3, "eg", "سجلت كام سعر آخر ٣ أيام لحد النهاردة؟"),
    ("this_week", 3, "msa", "ما إجمالي البروتين الذي تناولته هذا الأسبوع بما فيه اليوم؟"),
    ("last_n_days", 3, "msa", "كم سعرة سجلت خلال آخر ٣ أيام حتى اليوم؟"),
    ("this_week", 3, "en", "Have I not eaten enough protein this week up to today?"),
]
HISTORICAL_TARGET_CASES = [
    ("yesterday", {"day": "yesterday"}, "en", "What were my calorie targets yesterday?"),
    ("last_n_days", {"days": 3}, "en", "What were my nutrition targets in the last 3 days?"),
    ("yesterday", {"day": "yesterday"}, "en", "Show my saved protein target from last night"),
    ("explicit_date", {"day": "2026-11-14"}, "en", "What was my nutrition plan on 2026-11-14?"),
    ("this_week", {"days": 3}, "en", "Show my calorie goals this week up to today"),
    ("last_n_days", {"days": 7}, "en", "List my saved macro targets for the past 7 days"),
    ("yesterday", {"day": "yesterday"}, "eg", "هدفي من البروتين امبارح كان كام؟"),
    ("explicit_date", {"day": "2026-11-15"}, "eg", "وريني أهدافي الغذائية يوم 2026-11-15"),
    ("last_n_days", {"days": 3}, "eg", "أهدافي من السعرات آخر ٣ أيام كانت كام؟"),
    ("yesterday", {"day": "yesterday"}, "msa", "ما أهدافي الغذائية أمس؟"),
    ("this_week", {"days": 3}, "msa", "اعرض أهدافي من السعرات هذا الأسبوع حتى اليوم"),
    ("yesterday", {"day": "yesterday"}, "en", "Was my protein target not saved yesterday?"),
]
PAGINATED_CARDIO_QUESTION_CASES = [
    ("en", "List my logged cardio sessions"),
    ("en", "Show my cardio history with machine settings"),
    ("en", "What are my recent cardio sessions and minutes?"),
    ("en", "Tell me my cardio history including saved calorie estimates"),
    ("eg", "وريني جلسات الكارديو بتاعتي كلها"),
    ("eg", "سجلي في الكارديو فيه إيه؟"),
    ("eg", "آخر جلسة كارديو بتاعتي كانت إيه؟"),
    ("msa", "اعرض تاريخ الكارديو الخاص بي مع إعدادات الأجهزة"),
    ("msa", "ما جلسات الكارديو الأخيرة الخاصة بي؟"),
    ("en", "Is my cardio log not empty?"),
]

ROUND_FIVE_ROUTING_CASES = [
    ("general_knowledge", "today", None, None, language, question)
    for language, question in HOW_TO_ADVICE_CASES + HYPOTHETICAL_INTAKE_CASES
] + [
    ("cardio_performed", period, "get_player_cardio", {"day": day}, language, question)
    for period, day, language, question in CARDIO_DAY_CASES
] + [
    ("intake_recall", period, "get_player_nutrition_trend", {"days": days}, language, question)
    for period, days, language, question in ENDPOINT_RANGE_CASES
] + [
    ("targets_only", period, "get_player_nutrition", args, language, question)
    for period, args, language, question in HISTORICAL_TARGET_CASES
] + [
    ("cardio_performed", "today", "get_player_cardio", {}, language, question)
    for language, question in PAGINATED_CARDIO_QUESTION_CASES
] + [
    ("general_knowledge", "today", None, None, language, question)
    for language, question in [
        ("en", "Don't read my cardio history; what should I eat before cardio?"),
        ("eg", "من غير فتح سجل أكلي، آكل إيه قبل الكارديو؟"),
        ("msa", "لا تعرض تاريخ الكارديو الخاص بي، كيف أبدأ الكارديو؟"),
        ("en", "If I ate eggs this week up to today, how much protein would I get?"),
        ("msa", "إذا تناولت البيض هذا الأسبوع حتى اليوم، كم بروتين سأحصل عليه؟"),
        ("en", "How can I change my calorie targets from yesterday?"),
        ("msa", "كيف أعدل أهدافي الغذائية التي سجلت أمس؟"),
        ("en", "What should my nutrition targets have been yesterday?"),
    ]
] + [
    ("cardio_performed", "this_week", "get_player_cardio", {"days": 3}, language, question)
    for language, question in [
        ("en", "How much cardio did I do this week up to today?"),
        ("eg", "عملت كارديو قد إيه الأسبوع ده لحد النهاردة؟"),
        ("msa", "كم دقيقة كارديو مارست هذا الأسبوع حتى اليوم؟"),
    ]
]


# Ten additional, independently authored adversarial phrasings per round-5 class.
ROUND_FIVE_ADVERSARIAL_CASES = [
    ("guidance", None, None, language, question)
    for language, question in [
        ("en", "Can you show me how I should use my food log?"),
        ("en", "How could I read my cardio history?"),
        ("en", "Tell me how to organize my meal log"),
        ("en", "What would you recommend before my cardio sessions?"),
        ("en", "Shouldn't I use my food log to track protein?"),
        ("eg", "وريني إزاي أراجع سجل أكلي"),
        ("eg", "إيه أحسن طريقة أستخدم بيها سجل أكلي؟"),
        ("msa", "كيف يمكنني مراجعة سجل وجباتي؟"),
        ("msa", "اعرض لي طريقة استخدام سجل وجباتي"),
        ("msa", "لا تراجع سجل الكارديو الخاص بي؛ اشرح طريقة استخدامه"),
    ]
] + [
    ("hypothetical", None, None, language, question)
    for language, question in [
        ("en", "If I were to eat two eggs, what would my protein intake be?"),
        ("en", "How much protein did I eat, assuming I had two eggs?"),
        ("en", "Had I eaten a bowl of lentils, would I have met my protein target?"),
        ("en", "How much protein would I have eaten after two shakes?"),
        ("eg", "لو كنت مكانك وأكلت بيضتين، كنت هقول بروتيني كام؟"),
        ("eg", "بروتيني كام لو ما كنتش أكلت غير فول؟"),
        ("eg", "لو افترضنا إني ما شربتش اللبن، كم بروتين شربت؟"),
        ("msa", "إذا كنت قد تناولت وجبتين افتراضيا، كم بروتين تناولت؟"),
        ("msa", "في حالة أنني تناولت الأرز، ما إجمالي البروتين الذي تناولته؟"),
        ("msa", "تخيل أنني تناولت بيضتين، كم سعرة تناولت؟"),
    ]
] + [
    ("cardio_day", reader, args, language, question)
    for reader, args, language, question in [
        ("get_player_cardio", {"day": "today"}, "en", "How many minutes of cardio have I logged today?"),
        ("get_player_cardio", {"day": "yesterday"}, "en", "Have I not performed any cardio yesterday?"),
        ("get_player_cardio", {"day": "2026-11-03"}, "en", "Show my logged cardio sessions on 2026-11-03"),
        ("get_player_cardio", {"day": "yesterday"}, "en", "Tell me what cardio I performed yesterday"),
        ("get_player_cardio", {"day": "today"}, "msa", "ما إجمالي الكارديو الذي مارسته اليوم؟"),
        ("get_player_cardio", {"day": "yesterday"}, "eg", "كم كارديو لعبت امبارح جنب برنامجي؟"),
        ("get_player_cardio", {"day": "today"}, "eg", "وريني جلساتي في الكارديو النهارده"),
        ("get_player_cardio", {"day": "yesterday"}, "eg", "هل ما عملتش كارديو امبارح؟"),
        ("get_player_cardio", {"day": "yesterday"}, "msa", "هل لم أمارس الكارديو أمس؟"),
        (None, None, "en", "Don't load my cardio log from yesterday"),
    ]
] + [
    ("endpoint_range", "get_player_nutrition_trend", {"days": days}, language, question)
    for days, language, question in [
        (3, "en", "Through today, what is my total protein intake this week?"),
        (3, "en", "What did I eat this week through 2026-11-16?"),
        (3, "en", "Today I want to see how much protein I consumed in the past 3 days"),
        (14, "en", "Have I not hit my calorie target for the last 14 days including today?"),
        (3, "eg", "لحد النهارده، أنا أكلت كام بروتين في الأسبوع الحالي؟"),
        (3, "eg", "وريني أكلي في آخر ٣ أيام بما فيهم النهاردة"),
        (7, "eg", "أنا ما أكلتش كام سعر في آخر ٧ أيام لحد النهارده؟"),
        (3, "msa", "حتى اليوم، كم بروتين استهلكت هذا الأسبوع؟"),
        (7, "msa", "اعرض متوسط بروتيني خلال آخر ٧ أيام بما فيها اليوم"),
        (3, "msa", "هل لم أحقق هدفي من البروتين هذا الأسبوع حتى اليوم؟"),
    ]
] + [
    ("historical_targets", reader, args, language, question)
    for reader, args, language, question in [
        ("get_player_nutrition", {"day": "yesterday"}, "en", "What wasn't my calorie target yesterday?"),
        ("get_player_nutrition", {"days": 14}, "en", "List my nutrition targets for the last 14 days including today"),
        ("get_player_nutrition", {"day": "2026-11-03"}, "en", "Tell me my saved macro goals on 2026-11-03"),
        ("get_player_nutrition", {"day": "yesterday"}, "en", "What calorie targets did I have yesterday?"),
        ("get_player_nutrition", {"day": "yesterday"}, "eg", "كانت أهدافي من البروتين امبارح كام؟"),
        ("get_player_nutrition", {"days": 3}, "eg", "وريني أهداف السعرات بتاعتي خلال آخر ٣ أيام"),
        ("get_player_nutrition", {"days": 3}, "msa", "اعرض هدفي من الدهون هذا الأسبوع حتى اليوم"),
        ("get_player_nutrition", {"day": "2026-11-14"}, "msa", "ما كانت أهدافي الغذائية في 2026-11-14؟"),
        ("get_player_nutrition", {"day": "yesterday"}, "msa", "ما هدف البروتين الخاص بي أمس؟"),
        (None, None, "en", "Don't read my nutrition targets from yesterday; explain protein instead"),
    ]
] + [
    ("cardio_pagination", reader, args, language, question)
    for reader, args, language, question in [
        ("get_player_cardio", {}, "en", "Show my cardio sessions without calorie estimates"),
        ("get_player_cardio", {}, "en", "Tell me the machine settings from my last cardio session"),
        ("get_player_cardio", {}, "en", "Could I see my cardio history?"),
        ("get_player_cardio", {}, "eg", "كم جلسة كارديو عندي؟"),
        ("get_player_cardio", {}, "eg", "قارن جلسات الكارديو بتاعتي"),
        ("get_player_cardio", {}, "eg", "وريني سجل جلساتي للكارديو"),
        ("get_player_cardio", {}, "msa", "اعرض جلسات الكارديو المسجلة الخاصة بي"),
        ("get_player_cardio", {}, "msa", "هل تاريخ الكارديو الخاص بي غير فارغ؟"),
        (None, None, "en", "Never use my cardio history; give general examples"),
        (None, None, "msa", "لا تحمل سجل الكارديو الخاص بي؛ اشرح الكارديو"),
    ]
]


PERSONAL_ROUTING_MATRIX = [
    (failure_class, "adversarial", reader, args, language, question)
    for failure_class, reader, args, language, question in ROUND_FIVE_ADVERSARIAL_CASES
] + [
    ("general_knowledge", "today", None, None, language, question)
    for language, question in [
        ("en", "What is my food log for?"),
        ("en", "Why are my cardio sessions important?"),
        ("eg", "وريني إزاي سجل الكارديو بتاعي بيشتغل"),
        ("msa", "ما أهداف التغذية أمس؟"),
        ("en", "If I ate eggs, tell me if I hit my protein target"),
    ]
] + [
    ("intake_recall", period, "get_player_food_log", {"day": day}, language, question)
    for period, day, language, question in [
        ("yesterday", "yesterday", "en", "Tell me if I ate enough protein yesterday"),
        ("today", "today", "en", "Check if my food log has any meals today"),
        ("yesterday", "yesterday", "eg", "لو سمحت وريني سجل أكلي امبارح"),
        ("today", "today", "msa", "إذا سمحت اعرض سجل وجباتي اليوم"),
        ("today", "today", "en", "If possible, show my food log for today"),
    ]
] + ROUND_FIVE_ROUTING_CASES + PERSONAL_ROUTING_CASES + [
    ("intake_recall", period, reader, args, language, question)
    for period, reader, args, language, question in PERSONAL_PERIOD_CASES
] + [
    ("intake_recall", "today", "get_player_food_log", {"day": "today"}, language, question)
    for language, question in PERSONAL_FACT_CASES
] + [
    ("general_knowledge", "today", None, None, language, question)
    for language, question in GENERAL_KNOWLEDGE_CASES + TRAINING_GOAL_CASES + GENERAL_CARDIO_CASES
] + [
    ("general_knowledge", period, None, None, language, question)
    for period, language, question in GENERAL_PERIOD_CASES
] + [
    ("targets_only", "today", "get_player_nutrition", {}, language, question)
    for language, question in NUTRITION_GOAL_CASES
] + [
    (intent, period, "get_player_nutrition_trend", {"days": days}, language, question)
    for intent, period, days, language, question in RANGE_CASES
] + [
    ("intake_recall", period, "get_player_food_log", {"day": day}, language, question)
    for period, day, language, question in DATED_TOTAL_CASES
] + [
    ("cardio_performed", "today", "get_player_cardio", {}, language, question)
    for language, question in CARDIO_HISTORY_CASES
] + [
    ("cardio_performed", period, "get_player_cardio", {"days": days}, language, question)
    for period, days, language, question in CARDIO_RANGE_CASES
] + [
    ("cardio_prescribed", "today", "get_active_program", {}, language, question)
    for language, question in CARDIO_PRESCRIPTION_CASES
] + [
    ("target_achievement", "this_week" if language == "msa" else "last_n_days",
     "get_player_nutrition_trend", {"days": 3}, language, question)
    for language, question in TARGET_RANGE_CASES
] + [
    ("target_achievement", "today", "get_player_food_log", {"day": "today"}, language, question)
    for language, question in [
        ("en", "How am I doing vs my protein target?"),
        ("eg", "عامل ازاي مقارنة بهدف البروتين؟"),
        ("eg", "أنا عامل ازاي مقارنة بهدف البروتين؟"),
        ("eg", "عامل ازاي بالنسبة لهدف البروتين؟"),
    ]
] + [
    ("general_knowledge", "today", None, None, language, question)
    for language, question in [
        ("en", "What should I eat before training?"),
        ("en", "Should I eat before training?"),
        ("en", "What to eat before training?"),
        ("eg", "آكل إيه قبل التمرين؟"),
        ("eg", "ينفع آكل إيه قبل التمرين؟"),
        ("en", "What is protein?"),
        ("eg", "يعني إيه بروتين؟"),
    ]
]


@pytest.mark.parametrize(
    ("intent", "period", "expected_reader", "expected_args", "language", "question"),
    PERSONAL_ROUTING_MATRIX,
)
def test_issue_735_personal_log_routes_each_intent_and_period(
    personal_log_player, intent, period, expected_reader, expected_args, language, question,
):
    _client, db, _headers, _protein_target = personal_log_player
    with db.open_ledger("assistant-personal-log-player") as ledger:
        tools, definitions = player_tools.build_player_read_tools(ledger)
        routed = context_router.route_player_context(
            [HumanMessage(content=question)], ledger, None,
            {"tools": tools, "definitions": definitions, "language": language},
        )

    calls = [call for message in routed.messages for call in getattr(message, "tool_calls", [])]
    expected_calls = [(expected_reader, expected_args)] if expected_reader else []
    assert [(call["name"], call["args"]) for call in calls] == expected_calls, (
        f"{intent=} {period=} {question=}"
    )
    if expected_reader == "get_player_food_log":
        [result] = [json.loads(message.content) for message in routed.messages
                    if isinstance(message, ToolMessage)]
        day = expected_args["day"]
        expected_date = {"today": TODAY.isoformat(),
                         "yesterday": (TODAY - timedelta(days=1)).isoformat()}.get(day, day)
        assert result["date"] == expected_date
    if expected_reader == "get_player_cardio" and expected_args.get("day"):
        [result] = [json.loads(message.content) for message in routed.messages
                    if isinstance(message, ToolMessage)]
        day = expected_args["day"]
        expected_date = {"today": TODAY.isoformat(),
                         "yesterday": (TODAY - timedelta(days=1)).isoformat()}.get(day, day)
        assert result["window"]["start_date"] == result["window"]["end_date"] == expected_date
    if expected_args and "days" in expected_args:
        [result] = [json.loads(message.content) for message in routed.messages
                    if isinstance(message, ToolMessage)]
        start = (TODAY - timedelta(days=expected_args["days"] - 1)).isoformat()
        if expected_reader in {"get_player_nutrition_trend", "get_player_nutrition"}:
            assert result["start_date"] == start and result["end_date"] == TODAY.isoformat()
            assert len(result["days"]) == expected_args["days"]
        else:
            assert result["window"]["start_date"] == start
            assert result["window"]["end_date"] == TODAY.isoformat()


@pytest.mark.parametrize(("question", "reader"), [
    ("How much protein did I eat in the last 3 days?", "get_player_nutrition_trend"),
    ("Show my cardio history for the last 3 days", "get_player_cardio"),
])
def test_issue_735_range_reads_include_boundary_and_exclude_older_records(
    personal_log_player, question, reader,
):
    _client, db, _headers, _protein_target = personal_log_player
    boundary = TODAY - timedelta(days=2)
    outside = TODAY - timedelta(days=3)
    with db.open_ledger("assistant-personal-log-player") as ledger:
        for day in (boundary, outside):
            _add_food(ledger, day)
            session_id = f"range-cardio-{day}"
            ledger.log_workout_session(
                session_id, day.isoformat(), "Cardio",
                f"{day}T10:00:00Z", f"{day}T10:30:00Z",
            )
            ledger.log_session_cardio(session_id, [{"machine": "bike", "minutes": 20}],
                                      f"{day}T10:30:00Z")
        tools, definitions = player_tools.build_player_read_tools(ledger)
        ledger.conn.execute("PRAGMA query_only=ON")
        routed = context_router.route_player_context(
            [HumanMessage(content=question)], ledger, None,
            {"tools": tools, "definitions": definitions, "language": "en"},
        )

    [call] = [call for message in routed.messages for call in getattr(message, "tool_calls", [])]
    assert (call["name"], call["args"]) == (reader, {"days": 3})
    [result] = [json.loads(message.content) for message in routed.messages
                if isinstance(message, ToolMessage)]
    if reader == "get_player_cardio":
        assert {session["date"] for session in result["sessions"]} == {
            boundary.isoformat(), TODAY.isoformat(),
        }
        assert result["window"]["minutes"] == 50
        assert result["session_count"] == 2
        assert "last_7_days" not in result and "last_14_days" not in result
    else:
        assert [day["date"] for day in result["days"]] == [
            boundary.isoformat(), (TODAY - timedelta(days=1)).isoformat(), TODAY.isoformat(),
        ]
        assert [day["totals"]["protein_g"] if day["totals"] else None
                for day in result["days"]] == [45, None, 45]


@pytest.mark.parametrize(("local_today", "days"), [
    (date(2026, 11, 14), 1),
    (date(2026, 11, 20), 7),
])
def test_issue_735_this_week_uses_inclusive_player_local_saturday_week(
    personal_log_player, monkeypatch, local_today, days,
):
    _client, db, _headers, _protein_target = personal_log_player
    monkeypatch.setattr(player_tools, "player_local_date", lambda *_args: local_today)
    with db.open_ledger("assistant-personal-log-player") as ledger:
        tools, definitions = player_tools.build_player_read_tools(ledger)
        routed = context_router.route_player_context(
            [HumanMessage(content="How much protein did I eat this week?")], ledger, None,
            {"tools": tools, "definitions": definitions, "language": "en"},
        )

    [call] = [call for message in routed.messages for call in getattr(message, "tool_calls", [])]
    assert call["args"] == {"days": days}
    [result] = [json.loads(message.content) for message in routed.messages
                if isinstance(message, ToolMessage)]
    assert result["start_date"] == "2026-11-14"
    assert result["end_date"] == local_today.isoformat()
    assert len(result["days"]) == days


@pytest.mark.parametrize(("question", "language", "expected_tools", "answer_kind"), [
    ("How much cardio did I do this week?", "en", ["get_player_cardio"], "cardio"),
    ("عملت كارديو قد ايه الاسبوع ده؟", "ar", ["get_player_cardio"], "cardio"),
    ("What did I eat today?", "en", ["get_player_food_log"], "food"),
    ("اكلت ايه النهارده؟", "ar", ["get_player_food_log"], "food"),
    ("How am I doing vs my protein target?", "en",
     ["get_player_food_log"], "comparison"),
    ("عامل ازاي مقارنة بهدف البروتين؟", "ar",
     ["get_player_food_log"], "comparison"),
    ("أنا عامل ازاي مقارنة بهدف البروتين؟", "ar",
     ["get_player_food_log"], "comparison"),
    ("عامل ازاي بالنسبة لهدف البروتين؟", "ar",
     ["get_player_food_log"], "comparison"),
    ("Show my protein trend for the last 14 days", "en",
     ["get_player_nutrition_trend"], "trend"),
])
def test_personal_log_questions_are_routed_before_the_first_answer(
    personal_log_player, monkeypatch, question, language, expected_tools, answer_kind,
):
    client, _db, headers, protein_target = personal_log_player
    _force_free_form_coaching_intent(monkeypatch)
    if answer_kind == "cardio":
        answer = "You logged 30 minutes of Cardio this week." if language == "en" else "تمام، سجلت 30 دقيقة كارديو الأسبوع ده."
    elif answer_kind == "food":
        answer = ("You logged Player lunch snapshot today." if language == "en"
                  else "تمام، سجلت Player lunch snapshot النهارده.")
    elif answer_kind == "comparison":
        answer = (f"Your log shows 45 g protein against a {protein_target} g target."
                  if language == "en" else
                  f"تمام، سجلت 45 جم بروتين وهدفك {protein_target} جم.")
    else:
        answer = "Your recent logged intake and targets are available."
    model = ScriptedChatModel([answer])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    assert _done_content(response.text) == answer
    reads = _routed_reads(model)
    assert [name for name, _result in reads] == expected_tools
    if answer_kind == "cardio":
        entry = reads[0][1]["sessions"][0]["entries"][0]
        assert entry["minutes"] == 30 and entry["machine"] == "bike"
        assert entry["calories_kcal"] == 180
        assert reads[0][1]["sessions"][0]["calories_kcal"] == 180
    elif answer_kind == "food":
        result = reads[0][1]
        assert result["entries"][0]["name"] == "Player lunch snapshot"
        assert result["totals"]["protein_g"] == 45
    elif answer_kind == "comparison":
        food_log = reads[0][1]
        assert food_log["totals"]["protein_g"] == 45
        assert food_log["targets"]["protein_g"] == protein_target
    else:
        trend = reads[0][1]
        today = next(day for day in trend["days"] if day["date"] == TODAY.isoformat())
        assert today["totals"]["protein_g"] == 45
        assert today["targets"]["protein_g"] is not None


def test_saved_targets_come_from_the_plan_in_effect_on_that_day(personal_log_player):
    # Regression for #735: a plan saved earlier today must supply today's dated
    # targets, while days before any plan keep null targets.
    _client, db, _headers, protein_target = personal_log_player
    with db.open_ledger("assistant-personal-log-player") as ledger:
        today_targets = nutrition.targets_for_day(ledger, TODAY)
        before_plan_targets = nutrition.targets_for_day(ledger, TODAY - timedelta(days=1))
    assert today_targets is not None
    assert today_targets["protein_g"] == protein_target
    assert before_plan_targets is None


@pytest.mark.parametrize(("question", "tool_name", "answer"), [
    ("How much cardio did I do this week?", "get_player_cardio",
     "No Cardio was logged in the recent window."),
    ("What did I eat today?", "get_player_food_log",
     "No food is logged for today."),
])
def test_empty_personal_log_path_is_explicit(
    empty_personal_log_player, monkeypatch, question, tool_name, answer,
):
    client, _db, headers = empty_personal_log_player
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel([answer])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    assert _done_content(response.text) == answer
    [(name, result)] = _routed_reads(model)
    assert name == tool_name
    if tool_name == "get_player_cardio":
        assert result["status"] == "no_data" and result["sessions"] == []
    else:
        assert result["entry_count"] == 0 and result["entries"] == []
        assert "Player lunch snapshot" not in json.dumps(result)


@pytest.mark.parametrize("question", [
    "What did I eat on 2026-11-15?",
    "أكلت إيه يوم 2026-11-15؟",
])
def test_food_recall_preserves_explicit_date_before_normalization(
    personal_log_player, monkeypatch, question,
):
    client, db, headers, _protein_target = personal_log_player
    with db.open_ledger("assistant-personal-log-player") as ledger:
        _add_food(ledger, date(2026, 11, 15), "Player November 15 lunch")
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["You logged lunch on November 15."])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    [(tool_name, result)] = _routed_reads(model)
    assert tool_name == "get_player_food_log"
    call = next(call for message in model.calls[0]["messages"]
                for call in getattr(message, "tool_calls", []))
    assert call["args"] == {"day": "2026-11-15"}
    assert result["entries"][0]["name"] == "Player November 15 lunch"


@pytest.mark.parametrize("question", [
    "What did I eat yesterday?",
    "اكلت ايه أمس؟",
])
def test_food_recall_routes_yesterday_in_english_and_arabic(
    personal_log_player, monkeypatch, question,
):
    client, db, headers, _protein_target = personal_log_player
    with db.open_ledger("assistant-personal-log-player") as ledger:
        _add_food(ledger, date(2026, 11, 15), "Player yesterday lunch")
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["You logged lunch yesterday."])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    [(tool_name, result)] = _routed_reads(model)
    assert tool_name == "get_player_food_log"
    call = next(call for message in model.calls[0]["messages"]
                for call in getattr(message, "tool_calls", []))
    assert call["args"] == {"day": "yesterday"}
    assert result["entries"][0]["name"] == "Player yesterday lunch"


@pytest.mark.parametrize("question", [
    "What should I eat before training?",
    "Should I eat before training?",
    "What to eat before training?",
    "آكل إيه قبل التمرين؟",
    "ينفع آكل إيه قبل التمرين؟",
    "What is protein?",
    "يعني إيه بروتين؟",
    "How many bench sets did I log?",
    "سجلت كام سيت بنش؟",
])
def test_generic_nutrition_and_non_food_logs_do_not_load_personal_nutrition(
    personal_log_player, monkeypatch, question,
):
    client, _db, headers, _protein_target = personal_log_player
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["Here is a general answer."])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    personal_reads = {
        "get_player_nutrition", "get_player_food_log", "get_player_nutrition_trend",
    }
    assert not personal_reads.intersection(name for name, _result in _routed_reads(model))


@pytest.mark.parametrize("question", [
    "How many minutes of cardio are in my program?",
    "كام دقيقة كارديو في برنامجي؟",
])
def test_explicit_cardio_program_question_routes_to_program(
    personal_log_player, monkeypatch, question,
):
    client, _db, headers, _protein_target = personal_log_player
    _force_free_form_coaching_intent(monkeypatch)
    model = ScriptedChatModel(["Your program details are available."])
    monkeypatch.setattr(assistant_graph, "llm", model)

    response = client.post("/chat/messages", headers=headers, json={"content": question})

    assert response.status_code == 200
    reads = _routed_reads(model)
    assert [name for name, _result in reads] == ["get_active_program"]
