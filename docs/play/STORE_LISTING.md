# Store listing (English + Arabic)

Prepared for issue #750. Source for Play Console → **Main store listing** in
both languages. Follows the Arabic glossary in
`docs/design-review/arabic-localization-contract-and-glossary.md` so the
listing uses the same words as the app's Arabic UI. Free app, app type "App",
category **Health & Fitness**, no ads.

App name / tagline vocabulary (do not substitute):

| English | Arabic |
| :--- | :--- |
| MAYOS | MAYOS ميوس |
| Player | لاعب |
| Coach | مدرب |
| Training program | برنامج تدريبي |
| Workout | حصة تدريبية |

Play length rules: app name ≤ 30 characters, short description ≤ 80, full
description ≤ 4000. The counts below fit.

## AI disclosure (Play policy requirement)

The listing must say the app uses AI-generated content — it does, in the
assistant chat. Both full descriptions carry a fixed sentence:

- EN: "The training assistant is powered by AI: its replies are generated and
  may sometimes be wrong."
- AR: "مدربك المساعد يعمل بالذكاء الاصطناعي: ردوده مولّدة آلياً وقد تكون
  أحياناً غير دقيقة."

A second sentence about **reporting** a bad reply ("You can report any
assistant reply with one tap") is included in the AR/EN drafts below. #748
(the 👍/👎 vote and Report action) ships in the same release as this ticket,
ahead of it, so the sentence is part of the submitted listing; the listing
must not promise a control that is not in the uploaded build.

## English listing

- **App name**: MAYOS
- **Short description** (66 chars):

  > Build training programs, log workouts, and get AI guidance — free.

- **Full description**:

  > MAYOS is a free training app for Players and their Coaches.
  >
  > YOUR TRAINING PROGRAM
  > • A training program built from your onboarding answers — goals,
  >   equipment, and the days you actually train.
  > • Weekly volume and personal records tracked for you, with scheduled
  >   deloads.
  >
  > LOG EVERY WORKOUT
  > • A workout logger built for the gym: sets, reps, weights, and effort
  >   (RIR/RPE), with a rest timer that reminds you when the rest is over.
  > • Your history, readiness, and progress stay in your account.
  >
  > YOUR AI TRAINING ASSISTANT
  > • Ask the assistant anything about your training; it can build and adapt
  >   your program and answer questions about your own logged data.
  > • The training assistant is powered by AI: its replies are generated and
  >   may sometimes be wrong.
  > • You can report any assistant reply from its menu.
  >
  > TRAIN WITH A COACH (OPTIONAL)
  > • Invite a Coach you trust, or work as a Coach for your own Players.
  > • Coaches see the data you choose to share through the assignment — your
  >   assistant chats are never shared.
  > • Coaches: review requests, record check-ins, and ask AI questions about
  >   your roster of Players.
  >
  > PRIVATE BY DESIGN
  > • Your training data is yours: delete your account anytime from Settings
  >   → Linked sign-in → Danger zone → Delete account, or from the web
  >   without the app.
  > • The privacy policy covers every processor, including the AI provider:
  >   https://api.mayos.online/privacy
  >
  > MAYOS is free. Available in English and Arabic (واجهة عربية كاملة).

## Arabic listing (RTL)

- **App name**: MAYOS ميوس
- **Short description** (64 chars):

  > أنشئ برنامجاً تدريبياً، سجّل حصصك، واحصل على إرشاد ذكي — مجاناً.

- **Full description**:

  > MAYOS ميوس هو تطبيق تدريب مجاني للاعب ومدربه.
  >
  > برنامجك التدريبي
  > • برنامج تدريبي يُبنى من إجاباتك في البداية: أهدافك، معداتك، وأيام
  >   تدريبك الفعلية.
  > • تُتتبع لك أسبوعياً أحجام التدريب والأرقام القياسية الشخصية، مع تخفيف
  >   التدريب المجدول.
  >
  > سجّل كل حصة تدريبية
  > • مسجّل حصص مصمم للنادي: المجموعات، التكرارات، الأوزان، ومستوى الجهد
  >   (RIR/RPE)، مع مؤقّت راحة ينبّهك عند انتهاء الراحة.
  > • سجل تدريبك وتعافيك وتقدمك يبقى في حسابك.
  >
  > مدربك المساعد بالذكاء الاصطناعي
  > • اسأل المساعد أي شيء عن تدريبك؛ يستطيع بناء برنامجك وتعديله والإجابة
  >   عن أسئلتك من بياناتك المسجّلة.
  > • مدربك المساعد يعمل بالذكاء الاصطناعي: ردوده مولّدة آلياً وقد تكون
  >   أحياناً غير دقيقة.
  > • يمكنك الإبلاغ عن أي رد من المساعد من قائمته.
  >
  > تدرّب مع مدرب (اختياري)
  > • ادعُ مدرباً تثق به، أو اعمل كمدرب للاعبيك.
  > • يرى المدرب البيانات التي تختار مشاركتها عبر الإسناد فقط — محادثاتك مع
  >   المساعد لا تُشارك أبداً.
  > • للمدربين: راجع الطلبات، سجّل التواصل، واطرح أسئلة الذكاء الاصطناعي عن
  >   قائمة لاعبيك.
  >
  > الخصوصية أولاً
  > • بياناتك تدريبية ملكك: احذف حسابك في أي وقت من الإعدادات ← تسجيل
  >   الدخول المرتبط ← منطقة الخطر ← حذف الحساب، أو من الويب دون التطبيق.
  > • سياسة الخصوصية تغطي كل معالج بيانات، بما في ذلك مزوّد الذكاء
  >   الاصطناعي: https://api.mayos.online/privacy
  >
  > MAYOS ميوس مجاني، ويتوفر بالعربية والإنجليزية.

## Screenshots

Phone screenshots: minimum 2, up to 8; PNG or JPEG, 16:9 or 9:16, min side
320px, max side 3840px. Produce two sets — **English (LTR)** and **Arabic
(RTL)** — and upload each to its language tab. Use demo data, never real user
data or real photos of people.

| # | Screen | What it shows | EN text overlay | AR text overlay |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Dashboard / Home | Today's training at a glance: the scheduled workout, readiness, streak | "Your training, today" | "تدريبك، اليوم" |
| 2 | Program tab | The built training program: days, exercises, sets and reps | "A program built for you" | "برنامج مصمّم لك" |
| 3 | Workout logger | Sets, reps, weights and the running rest timer | "Log every workout" | "سجّل كل حصة تدريبية" |
| 4 | Assistant chat | A question about the Player's own data and the AI answer, with the AI disclosure visible | "Ask your AI assistant" | "اسأل مساعدك الذكي" |
| 5 | Personal records / progress | PR list and weekly volume | "Track your progress" | "تتبّع تقدمك" |
| 6 | Coach view (roster/alerts) | A Coach's Player roster with alerts | "Train your Players together" | "درّب لاعبيك معاً" |

Screenshot notes:

- Keep device chrome out (no status bar with a real time/battery) or keep it
  consistent across all shots.
- Reflect the app's real fonts and theme; do not invent UI that does not
  exist — Play reviews screenshots against the app.
- The AI chat screenshot must show a reply in the same language as the store
  listing (an Arabic reply in the AR tab, an English reply in the EN tab).

## Graphics

- **App icon (512×512 high-res, PNG 32-bit)**: source of truth is
  `assets/mayos-android-logo.png`; the in-app launcher icon is generated by
  the `flutter_launcher_icons` pipeline (`mobile/pubspec.yaml`, see
  `docs/PLAY_RELEASE.md` §6). Do not hand-draw a variant for Play — export
  from the same source so the store and the launcher match.
- **Feature graphic (1024×500, PNG/JPEG)**: brand-safe composition on the
  navy background (`#01183D`), MAYOS wordmark, no text near the edges (Play
  overlays buttons there), no screenshots of UI. Avoid large text — it gets
  cropped on some surfaces.
- **No promo video** is required for the first release.

## Before submitting

- [ ] Re-count app name (≤30), short description (≤80), full description
      (≤4000) after any edit — Play enforces these with hard errors.
- [ ] The AI-disclosure sentence is present in both languages.
- [ ] The "report a reply" sentence is present in both languages (#748 ships
      in the same release as this ticket, ahead of it).
- [ ] Every Arabic string matches the glossary (لاعب / مدرب / برنامج
      تدريبي / حصة تدريبية).
- [ ] Screenshots uploaded per language; feature graphic and icon uploaded.
