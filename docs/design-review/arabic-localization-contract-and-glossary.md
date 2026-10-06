# Arabic server messages and gym glossary

Design interview for [Server text localization contract (#142)](https://github.com/ahmedtvmer/MAYOS/issues/142)
and [Arabic gym glossary (#144)](https://github.com/ahmedtvmer/MAYOS/issues/144),
2026-10-01. These are accepted design directions, not descriptions of
implemented behavior. GitHub issues remain the implementation source of truth.

## Accepted directions

The owner accepted all three interview rounds, with the language and RIR
clarifications recorded below:

- Structured in-app alerts, notices and errors carry stable codes and values;
  the app supplies the wording in the account's Display language.
- The server renders emails in the recipient's Display language.
- Assistant replies remain complete text under the existing reply-language
  rule: the latest message's language, falling back to Display language when
  that message has no clear language.
- Ordinary training and coaching terms use simple standard Arabic in both
  the UI and Arabic assistant replies. Accepted examples: set **مجموعة**, rep
  **تكرار**, Training program **برنامج تدريبي**. Exercise names retain their
  English spelling, as do abbreviations such as RIR. Digits remain Western
  `0–9`, consistent with the earlier [Arabic review](arabic-language-review.md).

The vocabulary decision supersedes the blanket instruction to keep gym terms
in English in the Arabic-support map (#135). It does not change accepted
Arabic/English mixed input cases.

## Compatibility and historical text

- Add codes and values alongside existing English fallback strings. Updated
  apps translate known codes; unknown codes and legacy message-only notices
  show the original English fallback. Occasional English is accepted for these
  cases. Existing clients retain their existing fields and English text.
- Structured labels, alerts and new-format notices follow the current Display
  language, including cached content with enough structured data to render it.
- Coach-written notes, past chat, saved workout summaries and stored Checkpoint
  review prose remain in their original language. Future prose uses the
  applicable language rule. A coach reads the player's original Checkpoint
  prose, while structured labels may follow the coach's Display language.

## Logged-out screens, emails and web forms

- The initial language follows the system's preferred language, and the person
  can change it manually. Logged-out screens and generic confirmations use
  that selected language, including password-reset confirmations for both
  known and unknown accounts.
- A new account inherits the language selected before registration. Signing in
  restores an existing account's saved language. Changes while signed in save
  to the account; later system-language changes do not override them. Unsupported
  languages fall back to English within this English/Arabic scope.
- Emails to existing accounts use the recipient's Display language when the
  email is prepared for sending. Prepared emails retain that language.
- Emails without an account use the request's selected language, defaulting
  to English.
- Recovery and account-deletion web forms offer English and Arabic. The privacy
  policy remains English under the Arabic-support map's existing scope.

## Accepted training terms

| English | Arabic |
| --- | --- |
| Set | مجموعة |
| Rep | تكرار |
| Working set | مجموعة تدريب |
| Warm-up set | مجموعة إحماء |
| Warm-up movement | حركة إحماء |
| Rest | راحة |
| Deload | تخفيف التدريب |
| Personal record | رقم قياسي شخصي |
| Recovery | التعافي |
| Training program | برنامج تدريبي |
| Training schedule | جدول التدريب |
| Check-in | تواصل |
| Record a check-in | تسجيل تواصل |
| Follow-up due | حان موعد المتابعة |

## Primary muscle labels

| English label | Arabic label |
| --- | --- |
| Chest | الصدر |
| Upper Chest | أعلى الصدر |
| Front Delts | الكتف الأمامي |
| Side Delts | الكتف الجانبي |
| Rear Delts | الكتف الخلفي |
| Lats | العضلات الظهرية العريضة |
| Upper Back | أعلى الظهر |
| Traps | العضلة شبه المنحرفة |
| Lower Back | أسفل الظهر |
| Biceps | العضلة ذات الرأسين |
| Triceps | العضلة ثلاثية الرؤوس |
| Forearms | الساعد |
| Abs | عضلات البطن |
| Obliques | العضلات المائلة |
| Quads | العضلة رباعية الرؤوس |
| Hamstrings | عضلات الفخذ الخلفية |
| Glutes | عضلات الألوية |
| Adductors | العضلات المقربة |
| Abductors | العضلات المبعدة |
| Calves | عضلات الساق |
| Neck | الرقبة |
| Cardio | تمارين القلب |

## Exercise action labels

| English label | Arabic label |
| --- | --- |
| Shoulder Flexion | ثني الكتف |
| Shoulder Extension | بسط الكتف |
| Shoulder Abduction | إبعاد الكتف |
| Shoulder Adduction | تقريب الكتف |
| Shoulder Horizontal Adduction | التقريب الأفقي للكتف |
| Shoulder Horizontal Abduction | الإبعاد الأفقي للكتف |
| Shoulder External Rotation | الدوران الخارجي للكتف |
| Shoulder Internal Rotation | الدوران الداخلي للكتف |
| Scapular Elevation | رفع لوح الكتف |
| Scapular Retraction | تقريب لوحي الكتف |
| Scapular Depression | خفض لوح الكتف |
| Scapular Protraction | إبعاد لوحي الكتف |
| Elbow Flexion | ثني المرفق |
| Elbow Extension | بسط المرفق |
| Wrist Flexion | ثني الرسغ |
| Wrist Extension | بسط الرسغ |
| Spinal Flexion | ثني العمود الفقري |
| Spinal Extension | بسط العمود الفقري |
| Spinal Rotation | دوران العمود الفقري |
| Spinal Lateral Flexion | الانثناء الجانبي للعمود الفقري |
| Anti-Extension | مقاومة بسط الجذع |
| Anti-Rotation | مقاومة دوران الجذع |
| Anti-Lateral Flexion | مقاومة الانثناء الجانبي للجذع |
| Hip Flexion | ثني الورك |
| Hip Extension | بسط الورك |
| Hip Abduction | إبعاد الورك |
| Hip Adduction | تقريب الورك |
| Knee Flexion | ثني الركبة |
| Knee Extension | بسط الركبة |
| Ankle Plantar Flexion | العطف الأخمصي للكاحل |
| Ankle Dorsiflexion | العطف الظهري للكاحل |
| Neck Flexion | ثني الرقبة |
| Neck Extension | بسط الرقبة |
| Conditioning | اللياقة البدنية |

Keep the label **RIR** unchanged; do not replace it with an Arabic label.
Keep **kg** beside numeric weights.

## Accepted product terms

| English | Arabic |
| --- | --- |
| Player | لاعب |
| Coach | مدرب |
| Workout | حصة تدريبية |
| Training profile | الملف التدريبي |
| Exercise library | مكتبة التمارين |
| Roster | قائمة اللاعبين |
| Roster briefing | ملخص قائمة اللاعبين |
| Assignment | علاقة تدريب |
| Assignment invite | دعوة للتدريب مع مدرب |
| Coach invite | دعوة لتفعيل دور المدرب |
| Assistant style | أسلوب المساعد |
| Checkpoint | محطة تقدم |
| Checkpoint review | مراجعة محطة التقدم |
| Weekly streak | أسابيع الالتزام المتتالية |
| Permanent exercise substitution | تبديل تمرين في البرنامج |
| One-workout replacement | استبدال تمرين لهذه الحصة |
| Substitution request to coach | طلب تبديل تمرين من المدرب |

Retain **MAYOS**, **Free**, **Pro**, and established split names such as
**Upper/Lower**; translate their surrounding explanations. Retain established
abbreviations, including **RIR** and **e1RM**. The existing restriction against
using PR as the prose name for a Personal record still applies.

## Distinct volume labels

- Muscle contributions: **مجموعات محسوبة لكل عضلة**, with an explanation
  that a working set counts as `1` for the main muscle and `0.5` for each
  secondary muscle.
- Weight multiplied by repetitions: **إجمالي الوزن المرفوع**, in **kg**.
- The review that adjusts weekly working sets: **مراجعة مجموعات التدريب**.

These names distinguish the existing metrics; they do not change calculations.

## Exercise content boundary

For launch, translate app labels and explanations around programs, while
exercise names and library instructions remain English. Translating library
instructions is separate, owner-reviewed work. The assistant may explain an
exercise in Arabic under its existing reply-language rule.

Arabic exercise search aliases are follow-up work, each verified against the
exact movement. Launch library search keeps existing English names and aliases.
This does not withdraw Arabic assistant input support or its separate routing
work. Arabic/English mixed player input remains supported.

## Confirmed localization contract

These technical boundaries apply the accepted decisions to the current code.
They are implementation requirements, not claims of completed work.

- Each structured message has a stable, specific translation code and typed
  values for its template, alongside its existing English fallback where one
  exists. Preserve response fields, HTTP statuses, enum values and business
  machine codes. Do not replace existing strings with objects.
- A code's meaning and required values stay stable. Outcomes such as a program
  request received, applied or declined need distinct translation codes even
  if their current event kind is shared.
- Store new-format notice codes and values durably for cached rendering. Keep
  old message-only rows as fallbacks; do not reconstruct them by parsing prose.
- Updated apps translate known valid codes. Unknown codes, missing required
  values or old messages use a safe English fallback. Without one, show an
  appropriate generic message in Display language; never treat an unknown
  alert as a known missed-day alert.
- Template values are allowlisted and stay within the existing authorized
  payload. Human-written text retains its original language. Do not expose raw
  validation input, credentials or tokens in translation metadata or logs.
  Localization does not add training data to emails or expand model payloads.
- Cover ordinary HTTP errors, validation errors, rate limits, pre-stream
  errors and SSE errors. Preserve authentication, authorization, deletion and
  retry behavior.
- Localize server-owned intake explanations, hints, examples and option
  descriptions through structured metadata. Keep field names, allowed values
  and ranges unchanged.
- Deterministic assistant replies and model replies follow the same assistant
  reply-language and glossary rules. Future deterministic workout summaries
  use Display language; stored summaries remain untouched. Localization never
  changes facts, training actions or clinical behavior.
- Checkpoint rating labels are structured display text. Preserve rating facts
  and stored review prose. Temporary templates may render in the applicable
  current Display language. Expose original text language if needed, without
  regenerating a stored review.
- Logged-out response language follows the request's selected language,
  independently of account lookup. Localizing recovery and deletion forms
  preserves their existing generic responses and token protections.

## Shared message implementation notes

Coach alert responses keep their existing `kind`, state and evidence fields and
add `message_code`, `message_params` and `message_fallback`. Codes identify one
stable meaning; each resolver entry validates its required typed values before
rendering. The fallback is safe English for old or malformed metadata. An
unknown kind has no translation code and uses a generic fallback rather than a
known alert template. When no usable fallback exists, the client uses a
localized generic message.

To add a code, add its typed value allowlist and safe English fallback to the
server message builder, then add a matching client template and a test for valid
and invalid values. Values must come from existing authorized evidence or a
stable enum emitted by the decision that produced that evidence; human-written
text stays in its original field and language. Never derive a code or values by
parsing prose, or show a code as readable text. Preserve all existing API fields
and keep translations in the Display language catalog so already loaded
messages can be rendered again after a language change.

## Verified implementation boundaries

Read-only findings on 2026-10-01; implementation belongs in subsequent GitHub
tickets.

| Surface | Current boundary and relevant source |
| --- | --- |
| Account language | `database/schema/definitions.py` has no account language column; `service/checkpoint_reviews.py` resolves language to English |
| Alerts | `svc/schemas.py` exposes kinds and evidence; `mobile/lib/src/core/models.dart` constructs English descriptions |
| Notices | `svc/routers/assignments.py` serves `/coach/assignments/notices` and `/assignments/notices`; `database/schema/definitions.py` stores rendered messages without template values |
| HTTP errors | `mobile/lib/src/core/api_client.dart` handles several shapes; `mobile/lib/src/features/player/auth/auth_controller.dart` distinguishes a Google conflict by exact English text |
| Stream errors | `svc/routers/chat.py` serves `/chat/messages`, with pre-stream JSON errors and detail-only SSE error frames |
| Intake | `svc/routers/onboarding.py`, `svc/schemas.py` and `service/intake.py` provide `/onboarding/intake` explanations, hints, examples and option descriptions |
| Assistant and summaries | `agent/assistant_graph.py`, `agent/debrief.py` and `service/workouts.py` produce deterministic text separately from model replies |
| Checkpoint reviews | `svc/routers/checkpoint_reviews.py` serves `/checkpoint-reviews` and `/checkpoint-reviews/{checkpoint}`; `service/checkpoint_reviews.py` handles ratings, templates and saved prose |
| Emails | `service/email_sender.py` assembles customer emails; program-request email deliberately excludes training details |
| Public forms | `svc/routers/recovery.py` and `svc/routers/public_pages.py` serve recovery and deletion pages |
| Volume | `agent/progression_engine.py` counts main-muscle contributions as `1` and secondary contributions as `0.5`; `service/dashboard.py` sums weight multiplied by repetitions |

## Completion state

The owner confirmed the complete synthesis on 2026-10-01 and invoked to-spec.
No interview choice remains open for #142 or #144. ADR 058 is accepted design,
not implemented behavior. The owner confirmed the existing public API/HTML and
Flutter widget test boundaries, with captured emails and fake models.

Published spec: [Arabic localization: account language, server messages and
shared gym glossary (#246)](https://github.com/ahmedtvmer/MAYOS/issues/246),
labelled `ready-for-agent`. Decision issues #142 and #144 are closed with
resolution comments, and the parent map #135 links the spec and decisions.
The map stays open for its remaining decisions and implementation-ticket
slicing. Implementation is a separate step.

Arabic library instructions and search aliases are follow-up scope, not open
launch decisions. Apply this glossary when drafting remaining Arabic strings,
with the owner review required by the parent map.
