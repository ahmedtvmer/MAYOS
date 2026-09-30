# MAYOS Coaching Context

MAYOS supports personal training and a consented coaching relationship. A person can train, coach others, or do both through one account.

## Language

**Account**:
The identity a person uses to access MAYOS. An account can have player and coach capabilities at the same time.

**Player**:
An account holder using MAYOS for their own training. A player may also be a coach.
_Avoid_: Trainee (legacy code and API term), client

**Coach**:
An account holder who provides coaching to assigned players. A coach may also be a player.

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
The number of assistant requests available to an account for a given period. An account with both player and coach capabilities has separate Lifter and Coach allowances.

**Active account**:
An account that completed a workout or recorded a coaching action in the previous 30 days. A login alone does not make an account active.

**Coaching action**:
A recorded act of coaching by a coach for a player on an active assignment: recording a check-in, publishing a program, resolving a program request, or acknowledging or resolving a coach alert. Issuing invites and reading player history are not coaching actions.

**Roster**:
A coach's list of players on active assignments. It opens most urgent first, by the roster urgency order.

**Roster urgency order**:
The fixed, inspectable order of a roster by need for attention. Players are ranked first by new coach alerts plus pending program requests, then by longest missed-day streak, then by the most overdue follow-up, then by the oldest last workout. Username breaks any remaining tie. It uses no weights and no model scores. Acknowledged alerts do not count.
_Avoid_: priority score

**Roster briefing**:
An on-demand coach view that summarizes which assigned players need attention across the roster. It is distinct from a conversation about one selected player.

**Assignment**:
A mutually consented coaching relationship between a coach and a player. A player has at most one active assignment, and the coach can access that player's training history only while it is active.

**Assignment invite**:
A single-use invitation issued by a coach. The first player to redeem it may accept an assignment with that coach.
_Avoid_: Invite code (ambiguous with Coach invite)

**Coach invite**:
A single-use invitation issued by MAYOS that grants an account the coach capability. It is how a person becomes a coach, and it never creates an assignment.
_Avoid_: Invite code, redeem coach invite

**Owner dashboard**:
The owner-only, phone-first web surface served by the API at `/admin`, protected by a separate password and TOTP identity. It exposes account metadata and owner operations, never training content.
_Avoid_: Dashboard (without a qualifier; that usually means the player dashboard)

**Audit log**:
The append-only catalog record of owner and CLI operations, identified by actor and action and optionally an immutable account id, source IP, and reason. It is retained for one year and excludes credentials and contact details.
_Avoid_: Activity feed

**Exercise library**:
The shared reference set of exercises that programs, substitutions, and search draw from. It is the same for every account and holds no personal data.
_Avoid_: Exercise catalog

**Training ledger**:
An account's private record of its own training: program, workouts, schedule, onboarding answers, and assistant chat. It is separate from the shared coaching data (accounts, assignments, alerts, check-ins), and a coach reaches it only through an active assignment.
_Avoid_: User database, user DB

**Training program**:
The player's current structured selection of training days and exercises.

**Body proportions**:
A player's self-reported comparison of leg and torso length, recorded as coaching context.

**Program provenance**:
The origin of a training program, such as automatic generation or coach authorship. It does not change when the right to edit that program changes.

**Program authority**:
The right to change a player's program structure. It remains with the player until an assigned coach publishes a program, then belongs to that coach until the assignment ends.

**Substitution request**:
A player's request for their coach to replace an exercise in a coach-controlled program. The program does not change until the coach applies a replacement.

**Exercise substitution**:
A permanent change of one exercise in the player's own program, made by the player while they hold Program authority. It is distinct from Replace exercise, which changes one workout only, and Substitution request, which asks the coach to make a permanent change.

**Unplanned exercise**:
An exercise the player performed and recorded that was not prescribed in the active program. Recording it does not change the program.

**Replace exercise**:
Swapping a prescribed exercise for a different one while logging a workout. It applies to that workout only: the program is unchanged, the replaced exercise is recorded as skipped and the replacement as performed.

**Reps in reserve (RIR)**:
The player's own estimate of how many more reps they could have completed in a set. It is the effort measure players see and enter; it is optional, and a blank value means the player did not rate the set.
_Avoid_: RPE (internal legacy measure; RIR = 10 − RPE)

**Personal record**:
A player's best result on an exercise, measured as heaviest weight lifted or best estimated one-rep max. An exercise's first recorded session sets the baseline and is never itself a personal record.
_Avoid_: PR (in prose), PB

**Player mode** / **Coach mode**:
The two app surfaces of one account: training for oneself, or coaching assigned players. An account holding both capabilities switches between them; neither is a separate account.
_Avoid_: Lifter UI, coach account

**Display language**:
The language, English or Arabic, an account chooses for the app and for messages MAYOS sends it. It belongs to the account, not the device. It does not bind the assistant, which replies in the language of the player's latest message and falls back to the Display language only when that message has no clear language.
_Avoid_: Locale (implementation term), app language

**Linked sign-in**:
An external identity, such as a Google account, attached to exactly one MAYOS account and usable to sign in to it. It never replaces the account's username. An account always keeps at least one way to sign in, so a Linked sign-in can be removed only while the account has a password.

**Active workout**:
A workout the player is logging right now and has not yet finished. A device holds at most one, and it survives the app closing; in the web app it survives a reload of that browser. Finishing it produces a Workout draft on Android; in the web app, finishing commits it directly, and a failed commit keeps the Active workout for retry.

**Current set**:
The next set of an Active workout the player should log: the first working set that is not yet ticked, in workout order, skipping warm-ups and moving across exercises. There is no Current set once every working set is ticked.

**Warm-up set**:
A set recorded as preparation rather than training. It is kept in the workout's history but never counts toward personal records, progress, volume, the Current set, or sets done.

**Warm-up movement**:
A general preparation exercise prescribed in a training day's warm-up block, logged only as warm-up sets. Doing or leaving it out is never a workout divergence: it is neither skipped nor unplanned.
_Avoid_: Warm-up exercise (confusable with an exercise's own ramped warm-up sets)

**Cardio**:
The conditioning work a training day prescribes, recorded in a workout by the minutes done. It counts toward no set totals.

**Workout time**:
The time a player has spent on the Active workout they are logging: measured from when that workout started to the present, with no pause, shown live in the logger and as the workout's total duration in its summary.

**Workout draft**:
A workout the player has recorded on their Android device but has not yet committed to their training history. A draft may be captured without connectivity. The web app has no Workout drafts.

**Training schedule**:
The weekdays on which a player expects to train, interpreted in the player's timezone. It is separate from the ordered training days in a program.

**Schedule pause**:
An interval during which the player's expected training days do not count as missed days.

**Missed expected day**:
A scheduled training day that no workout satisfied within its grace period. One workout can satisfy at most one expected day.

**Missed-day streak**:
A run of consecutive missed expected days, measured over the sequence of expected days. Paused and non-expected days are skipped and neither break nor extend it. It drives coach alerts.

**Weekly streak**:
A run of consecutive weeks, starting Saturday in the player's timezone, in each of which the player completed at least as many workouts as they had expected training days, or as their program's weekly frequency when they keep no Training schedule. Fully paused weeks neither break nor extend it, and the week in progress never breaks it. It is the player-facing counterpart of the Missed-day streak.

**Checkpoint**:
A workout-count landmark in a player's training: the 10th, 25th, 50th and 100th workout, then every 100th. Only workouts completed in MAYOS count; imported history does not.
_Avoid_: Milestone, achievement

**Checkpoint review**:
The written assessment of a player's training since their previous checkpoint, produced once when a checkpoint is reached and never changed. Its rating is computed from recorded facts; the assistant only writes the words around it. An assigned coach can read it while the assignment is active.
_Avoid_: AI rating, performance score

**Coach alert**:
A catalog-side notification of a coaching fact about an assigned player, such as a missed-day streak of at least two days or a due follow-up. It has new, acknowledged, and resolved states, and deduplicates on a kind-specific key so retries never duplicate it.

**Signal episode**:
A run of consecutive committing sessions over which a progression signal (a recommended deload, or a regression on one exercise) keeps firing. It opens when the signal first fires and closes on the first later commit where it does not, producing one durable coach alert per episode rather than one per session.

**Check-in**:
A contact recorded by the coach and visible to both coach and player, including contact outside MAYOS. It starts the interval until the next follow-up is due.

**Follow-up due**:
The state of an assignment whose most recent check-in (or assignment start) is at least the weekly cadence in the past, measured in the player's timezone.
