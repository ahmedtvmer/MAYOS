# MAYOS Coaching Context

MAYOS supports personal training and a consented coaching relationship. A person can train, coach others, or do both through one account.

## Language

Arabic wording uses simple standard Arabic for ordinary training and coaching
terms: set is **مجموعة**, rep is **تكرار**, and Training program is
**برنامج تدريبي**. Exercise names and established abbreviations retain their
English spelling; the label RIR stays **RIR**. The UI, emails, server messages,
fixed safety replies, Roster briefings and Checkpoint reviews use this
vocabulary.

Arabic **assistant chat replies** (player chat and coach chat about one
player) are an exception: they use polite everyday Egyptian Arabic, as a
trainer talks to a client, without street slang, whatever kind of Arabic the
person wrote. They use the glossary term when naming something in the app
(Training program, Exercise library, Checkpoint) and everyday Egyptian gym
words otherwise, such as **سيتات** for sets and **عدّات** for reps.

**Account**:
The identity a person uses to access MAYOS. An account can have player and coach capabilities at the same time.

**Recovery email**:
The account's verified email address for password recovery. It lives in the shared catalog with the account, separately from training data. The account remains behind the recovery-email gate until its current address is verified.
_Arabic_: البريد الإلكتروني للاسترداد

**Player**:
An account holder using MAYOS for their own training. A player may also be a coach.
_Arabic_: لاعب
_Avoid_: Trainee (legacy code and API term), client

**Coach**:
An account holder who provides coaching to assigned players. A coach may also be a player.
_Arabic_: مدرب

**Lifter plan**:
The customer-facing Free or Pro plan for a player's own training features. It is independent of any coaching plan on the same account.

**Coach plan**:
The customer-facing Free or Pro plan for coaching features and capacity. It does not upgrade the coach's assigned players to Lifter Pro.

**Free plan**:
An ongoing, usable Lifter or Coach plan. It is distinct from the time-limited closed trial or a promotional free period.

**Closed trial**:
The free, invitation-only period before public launch, during which no plan is sold.

**Founding coach**:
A coach who joined during the closed trial and therefore qualifies for the founding promotion at public launch. Joining during the trial is necessary but the promotion itself decides the status.

**AI allowance**:
The maximum number of completed assistant requests an account may use in a given period, with the same request-count ceiling in English and Arabic. An account with both player and coach capabilities has separate Lifter and Coach allowances.

**Assistant style**:
How the player's assistant talks to that player: a chosen tone and optional instructions in the player's own words. It shapes the wording of assistant chat and Checkpoint reviews, never their facts, numbers, program changes, safety rules or reply language. It does not apply to what a coach reads.
_Arabic_: أسلوب المساعد
_Avoid_: Persona, coach tone

**Active account**:
An account that completed a workout or recorded a coaching action in the previous 30 days. A login alone does not make an account active.

**Coaching action**:
A recorded act of coaching by a coach for a player on an active assignment: recording a check-in, publishing a program, resolving a program request, or acknowledging or resolving a coach alert. Issuing invites and reading player history are not coaching actions.

**Roster**:
A coach's list of players on active assignments. It opens most urgent first, by the roster urgency order.
_Arabic_: قائمة اللاعبين

**Roster urgency order**:
The fixed, inspectable order of a roster by need for attention. Players are ranked first by new lapsing alerts, then by other new coach alerts plus pending program requests, then by longest missed-day streak, then by the most overdue follow-up, then by the oldest last workout, then by longest stall length. Username breaks any remaining tie. It uses no weights and no model scores. Acknowledged alerts do not count.
_Avoid_: priority score

**Lapsing**:
A player drifting away from training, shown by a new coach alert for a missed-day streak or a follow-up due.

**Stalling**:
A player who keeps training without a personal record on any exercise in the current program. It is measured as stall length.

**Stall length**:
The number of consecutive committing sessions without a personal record on any exercise in the current program. A personal-record session resets it to zero; otherwise the first session under a new program version counts as one.

**Volume review**:
A per-muscle assessment of a player's weekly working sets, made once at least four weeks of the current program have enough training behind them. Each muscle is judged progressing, stalled, or under-recovered from its primary exercises, which leads to keeping, adding, or removing sets. It is distinct from Stalling, which concerns the whole player.
_Arabic_: مراجعة مجموعات التدريب

**Roster briefing**:
An on-demand coach view that summarizes which assigned players need attention across the roster. It is distinct from a conversation about one selected player.
_Arabic_: ملخص قائمة اللاعبين

**Assignment**:
A mutually consented coaching relationship between a coach and a player. A player has at most one active assignment, and the coach can access that player's training history only while it is active.
_Arabic_: علاقة تدريب

**Assignment invite**:
A single-use invitation issued by a coach. The first player to redeem it may accept an assignment with that coach.
_Arabic_: دعوة للتدريب مع مدرب
_Avoid_: Invite code (ambiguous with Coach invite)

**Coach invite**:
A single-use invitation issued by MAYOS that grants an account the coach capability. It can be bound to an existing Account or hold a username for a future Account. It is how a person becomes a Coach, and it never creates an Assignment; an Assignment invite is a separate code issued by a Coach to invite a Player into a coaching relationship.
_Arabic_: دعوة لتفعيل دور المدرب
_Avoid_: Invite code, redeem coach invite

**Owner dashboard**:
The owner-only, phone-first web surface served by the API at `/admin`, protected by a separate password and TOTP identity. It exposes account metadata and owner operations, never training content.
_Avoid_: Dashboard (without a qualifier; that usually means the player dashboard)

**Audit log**:
The append-only catalog record of owner and CLI operations, identified by actor and action and optionally an immutable account id, source IP, and reason. It is retained for one year and excludes credentials and contact details.
_Avoid_: Activity feed

**Exercise library**:
The shared reference set of exercises that programs, substitutions, and search draw from. It is the same for every account and holds no personal data.
_Arabic_: مكتبة التمارين
_Avoid_: Exercise catalog

**Primary muscle**:
The lifter-friendly main-muscle label curated for an Exercise library row.
Search filters may match one or more Primary muscles; the source row's
`target_muscle` remains a separate catalog field.
_Arabic_: العضلة الأساسية

**Primary action**:
The main joint action curated for an Exercise library row, such as Knee
Extension or Shoulder Flexion. Search filters match the Primary action only;
Secondary actions describe additional joint actions and do not match a Primary
action filter.
_Arabic_: الحركة الأساسية

**Coach exercise**:
An exercise a Coach creates when the Exercise library lacks the movement. It has a Coach-owned id, optional body-part and Equipment tags, an optional note, and an optional HTTPS video link stored as text. It has no media, is searchable only by its owner in Coach mode, and is visible to a Player when prescribed in that Coach's Training program. The Player keeps its logged history after the Assignment ends.
_Arabic_: تمرين من إنشاء المدرب
_Avoid_: Custom exercise

**Exercise display name**:
Every Exercise library row has a name shown to the Player. A reviewed row uses its gym-standard name, such as "Lat Pulldown"; an unreviewed row shows its Exercise source name in Title Case. The source name, id and media stay unchanged.

**Exercise source name**:
The name supplied by ExerciseDB or by a MAYOS-authored Exercise library definition. It stays on the source row with its id and media; curation never rewrites it.

**Exercise alias**:
An alternative name a player may search by that resolves to one exercise in the Exercise library, such as "frontal lat pulldown" or "lat pull-down".

**Hidden exercise**:
An Exercise library row excluded from Player and Coach search, Replace browse, program generation, and substitution suggestions. Its stable id remains readable in existing Training programs and workout history; when marked as a duplicate, those reads show the kept Exercise's display name.

**Exercise curation file**:
The MAYOS-owned `data/exercise_curation.csv`, keyed by Exercise library id. It holds reviewed Exercise display names and aliases, with curated fields such as Primary muscle kept beside the source row.

**Equipment category**:
The derived category for an Exercise library row, computed from its Equipment value: Free weight, Machine, Cable, Bodyweight, Band, or Other. It describes the kind of equipment and is separate from Equipment access.
_Arabic_: فئة المعدات

**Load type**:
The curated loading mechanism for a Machine exercise: selectorized, plate-loaded, or unknown. The app labels these Pin-loaded, Plate-loaded, or Unknown. Load type does not change Equipment access.
_Arabic_: نوع التحميل

**Staple exercise**:
An exercise that elite coaches repeatedly choose for a movement, such as the Lat Pulldown for a vertical pull. Each movement has an ordered list of staples; the first one the player's Equipment access allows is prescribed and the next ones are its suggested substitutes.

**Equipment access**:
Where a player trains, as one of Commercial gym, Home gym, or Bodyweight only. A Commercial gym player is never prescribed or suggested band or bodyweight working sets, though they may still choose one themselves.
_Avoid_: Gym type, location

**Experience level**:
How long a player has trained, as one of beginner (under 2 training years), intermediate (2 to under 5) or advanced (5 or more), derived from their training years. It sets working-set effort in reps in reserve and, later, Volume review ceilings.
_Avoid_: Training level, skill level

**Training ledger**:
An account's private record of its own training: program, workouts, schedule, onboarding answers, and assistant chat. It is separate from the shared coaching data (accounts, assignments, alerts, check-ins), and a coach reaches it only through an active assignment.
_Avoid_: User database, user DB

**Training program**:
The player's current structured selection of training days and exercises.
_Arabic_: برنامج تدريبي

**Program draft**:
An unpublished Training program a Coach is writing for a Player on an active Assignment. It lives in the Player's Training ledger, is keyed to that Assignment, and is visible only to that Coach while the Assignment is active. There is at most one open Program draft per Assignment. It keeps the existing program fields; the editor shows target RIR and storage keeps `target_rpe` (RIR = 10 − RPE). Publishing activates it as a new program version and removes the draft. Ending the Assignment discards it.
_Arabic_: مسودة برنامج تدريبي

**Program import**:
Turning a spreadsheet a Coach uploads into the Program draft of a Player on an active Assignment. A sheet in the MAYOS template is read directly; a sheet in the Coach's own layout is first translated into the same rows. Either way the result is only a Program draft: an import never publishes, and a multi-week sheet contributes one chosen week.
_Avoid_: Program migration, program upload

**Training profile**:
The editable facts a player can update after onboarding: current goal, Equipment access, injuries or limitations, latest weight, and optional Target weight. Weight history records each local-day weight entry; the profile continues to show the latest value. Body proportions remain onboarding-only.
_Arabic_: الملف التدريبي

**Weight history**:
The dated record of a Player's bodyweight in the Training ledger, with at most one entry per Player-local calendar day. A later entry on the same day replaces that day's value; the Training profile shows the latest weight.
_Arabic_: سجل الوزن

**Target weight**:
An optional bodyweight goal, in kg, saved in the Training profile and used as a reference for Player progress context and active Coach alerts.
_Arabic_: الوزن المستهدف

**Body proportions**:
A player's self-reported comparison of leg and torso length, recorded as coaching context.

**Program provenance**:
The origin of a training program, such as automatic generation or coach authorship. It does not change when the right to edit that program changes.

**Program authority**:
The right to change a player's program structure. It remains with the player until an assigned coach publishes a program, then belongs to that coach until the assignment ends.

**Substitution request**:
A player's request for their coach to replace an exercise in a coach-controlled program. The program does not change until the coach applies a replacement.
_Arabic_: طلب تبديل تمرين من المدرب

**Exercise substitution**:
A permanent change of one exercise in the player's own program, made by the player while they hold Program authority. It is distinct from Replace exercise, which changes one workout only, and Substitution request, which asks the coach to make a permanent change.
_Arabic_: تبديل تمرين في البرنامج

**Program edit**:
A permanent change to one training day of the player's own program, made while the player holds Program authority: removing working-set exercises, lowering their working-set counts, or reordering them. It never adds an exercise, and one save creates one program version. It is distinct from Exercise substitution, which swaps an exercise, and from reordering or deleting sets in an Active workout, which changes that workout only.
_Avoid_: Program customization

**Unplanned exercise**:
An exercise the player performed and recorded that was not prescribed in the active program. Recording it does not change the program.

**Replace exercise**:
Swapping a prescribed exercise for a different one while logging a workout. It applies to that workout only: the program is unchanged, the replaced exercise is recorded as skipped and the replacement as performed.
_Arabic_: استبدال تمرين لهذه الحصة

**Reps in reserve (RIR)**:
The player's own estimate of how many more reps they could have completed in a set. It is the effort measure players see and enter; it is optional, and a blank value means the player did not rate the set.
_Avoid_: RPE (internal legacy measure; RIR = 10 − RPE)

**Personal record**:
A player's best result on an exercise, measured as heaviest weight lifted, best estimated one-rep max, or most reps in a 0 kg working set on body-weight or band equipment. An exercise's first working-set session sets the baseline and is never itself a Personal record. For most reps, the first eligible 0 kg working-set session sets that record's baseline even when earlier weighted sessions exist (ADR 061).
_Arabic_: رقم قياسي شخصي
_Avoid_: PR (in prose), PB

**Player mode** / **Coach mode**:
The two app surfaces of one account: training for oneself, or coaching assigned players. An account holding both capabilities switches between them; neither is a separate account.
_Avoid_: Lifter UI, coach account

**Display language**:
An account's chosen English or Arabic language for the app and MAYOS messages, initially taken from the system or a manual choice and restored on sign-in without later system changes overriding it. The assistant replies in the language of the player's latest message and falls back to Display language only when that message has no clear language.
_Avoid_: Locale (implementation term), app language

**Franco-Arabic**:
Arabic written in Latin letters and digits, such as "3ayez a8ayar el bench". The assistant does not act on or answer it, and asks the person to write in Arabic or English instead.
_Avoid_: Arabizi, Franco

**Linked sign-in**:
An external identity, such as a Google account, attached to exactly one MAYOS account and usable to sign in to it. Sign-in and connection match only by provider and subject; accounts are never linked or merged by email. Google's verified email may be kept as the recovery email when a new account is created and no live account already uses it. On an existing account, it can verify the current unverified recovery email only when the addresses match; it never replaces a different address. It never replaces the account's username. An account always keeps at least one way to sign in, so a Linked sign-in can be removed only while the account has a password.

**Workout**:
A single training session recorded by a player, distinct from an individual exercise within it.
_Arabic_: حصة تدريبية

**Active workout**:
A workout the player is logging right now and has not yet finished. A device holds at most one, and it survives the app closing; in the web app it survives a reload of that browser. Finishing it produces a Workout draft on Android; in the web app, finishing commits it directly, and a failed commit keeps the Active workout for retry.

**Current set**:
The next set of an Active workout the player should log: the first working set that is not yet ticked, in workout order, skipping warm-ups and moving across exercises. There is no Current set once every working set is ticked.

**Warm-up set**:
A set recorded as preparation rather than training. It is kept in the workout's history but never counts toward personal records, progress, volume, the Current set, or sets done.
_Arabic_: مجموعة إحماء

**Warm-up movement**:
A general preparation exercise prescribed in a training day's warm-up block, logged only as warm-up sets. Doing or leaving it out is never a workout divergence: it is neither skipped nor unplanned.
_Arabic_: حركة إحماء
_Avoid_: Warm-up exercise (confusable with an exercise's own ramped warm-up sets)

**Cardio**:
The conditioning work a training day prescribes, recorded in a workout by the minutes done. It counts toward no set totals.

**Workout time**:
The time a player has spent on the Active workout they are logging: measured from when that workout started to the present, with no pause, shown live in the logger and as the workout's total duration in its summary.

**Workout draft**:
A workout the player has recorded on their Android device but has not yet committed to their training history. A draft may be captured without connectivity. The web app has no Workout drafts.

**Training schedule**:
The weekdays on which a player expects to train, interpreted in the player's timezone. It is separate from the ordered training days in a program.
_Arabic_: جدول التدريب

**Schedule pause**:
An interval during which the player's expected training days do not count as missed days.

**Missed expected day**:
A scheduled training day that no workout satisfied within its grace period. One workout can satisfy at most one expected day.

**Missed-day streak**:
A run of consecutive missed expected days, measured over the sequence of expected days. Paused and non-expected days are skipped and neither break nor extend it. It drives coach alerts.

**Weekly streak**:
A run of consecutive weeks, starting Saturday in the player's timezone, in each of which the player completed at least as many workouts as they had expected training days, or as their program's weekly frequency when they keep no Training schedule. Fully paused weeks neither break nor extend it, and the week in progress never breaks it. It is the player-facing counterpart of the Missed-day streak.
_Arabic_: أسابيع الالتزام المتتالية

**Checkpoint**:
A workout-count landmark in a player's training: the 10th, 25th, 50th and 100th workout, then every 100th. Only workouts completed in MAYOS count; imported history does not.
_Arabic_: محطة تقدم
_Avoid_: Milestone, achievement

**Checkpoint review**:
The assessment of a player's training since their previous checkpoint, with a rating computed from recorded facts and player-facing prose written once in their Assistant style and never changed. During an active assignment, the coach reads a neutral assessment of those same facts and rating, unaffected by the player's style or optional instructions.
_Arabic_: مراجعة محطة التقدم
_Avoid_: AI rating, performance score

**Coach alert**:
A catalog-side notification of a coaching fact about an assigned player, such as a missed-day streak of at least two days, a due follow-up, or Stalling at a Stall length of eight. It has new, acknowledged, and resolved states, and deduplicates on a kind-specific key so retries never duplicate it.

**Deload**:
A temporary cut to a player's prescribed sets and effort, recommended when recorded readiness and effort show fatigue. Without an assigned coach it is applied to the player's workouts automatically; with one it is only suggested, and the coach decides. Either way the player can, through the assistant, undo an applied deload or apply a suggested one for their next workout only, and an assigned coach sees that choice on the deload alert.
_Arabic_: تخفيف التدريب

**Signal episode**:
A run of consecutive committing sessions over which a progression signal (a recommended deload, or a regression on one exercise) keeps firing. It opens when the signal first fires and closes on the first later commit where it does not, producing one durable coach alert per episode rather than one per session.

**Check-in**:
A contact recorded by the coach and visible to both coach and player, including contact outside MAYOS. It starts the interval until the next follow-up is due.
_Arabic_: تواصل; recording a Check-in is تسجيل تواصل.

**Follow-up due**:
The state of an assignment whose most recent check-in (or assignment start) is at least the weekly cadence in the past, measured in the player's timezone.
_Arabic_: حان موعد المتابعة
