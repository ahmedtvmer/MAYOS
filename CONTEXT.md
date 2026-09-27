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

**AI allowance**:
The number of assistant requests available to an account for a given period. An account with both player and coach capabilities has separate Lifter and Coach allowances.

**Active account**:
An account that completed a workout or recorded a coaching action in the previous 30 days. A login alone does not make an account active.

**Roster briefing**:
An on-demand coach view that summarizes which assigned players need attention across the roster. It is distinct from a conversation about one selected player.

**Assignment**:
A mutually consented coaching relationship between a coach and a player. A player has at most one active assignment, and the coach can access that player's training history only while it is active.

**Invite code**:
A single-use invitation issued by a coach. The first player to redeem it may accept an assignment with that coach.

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

**Unplanned exercise**:
An exercise the player performed and recorded that was not prescribed in the active program. Recording it does not change the program.

**Workout draft**:
A workout the player has recorded on their device but has not yet committed to their training history. A draft may be captured without connectivity.

**Training schedule**:
The weekdays on which a player expects to train, interpreted in the player's timezone. It is separate from the ordered training days in a program.

**Schedule pause**:
An interval during which the player's expected training days do not count as missed days.

**Missed expected day**:
A scheduled training day that no workout satisfied within its grace period. One workout can satisfy at most one expected day.

**Missed-day streak**:
A run of consecutive missed expected days, measured over the sequence of expected days. Paused and non-expected days are skipped and neither break nor extend it. It drives coach alerts.

**Coach alert**:
A catalog-side notification of a coaching fact about an assigned player, such as a missed-day streak of at least two days or a due follow-up. It has new, acknowledged, and resolved states, and deduplicates on a kind-specific key so retries never duplicate it.

**Signal episode**:
A run of consecutive committing sessions over which a progression signal (a recommended deload, or a regression on one exercise) keeps firing. It opens when the signal first fires and closes on the first later commit where it does not, producing one durable coach alert per episode rather than one per session.

**Check-in**:
A contact recorded by the coach and visible to both coach and player, including contact outside MAYOS. It starts the interval until the next follow-up is due.

**Follow-up due**:
The state of an assignment whose most recent check-in (or assignment start) is at least the weekly cadence in the past, measured in the player's timezone.
