# MAYOS Launch Business & Product Requirements

**Status:** Trial client scope and public-launch business requirements under review  
**Scope:** Required trial client surfaces plus public-launch requirements for adoption, retention, subscriptions, and reliable daily use  
**Related:** `MAYOS_LAUNCH_PRICING.md`

The closed trial is free and requires the Android app plus one web app serving
desktop coaches and iPhone players. The trial scope in `ANDROID-PLAN.md` and
ADR 022 supersedes ADR 017's Android-only scope. Subscriptions start at public
launch, after the free trial.

## 1. Launch Objective

MAYOS should remove the major barriers to coach and player adoption without expanding the MVP into a general coaching-business suite.

Launch priorities:

- Easy migration
- Fast coach/player onboarding
- Reliable workout/program workflow
- Useful automation
- Trustworthy AI assistance
- Clear Free → Pro value
- Data portability
- Measurable unit economics and retention

---

## 2. Coach Program Templates

### Goal
Prevent coaches from rebuilding common splits/programs for every player.

Basic reusable templates are required for the public launch on Android and web.
The first release supports create, name, edit, duplicate, archive, and assign.

### Requirements
A coach can:
- Create, name, edit, duplicate, and archive templates.
- Define days, exercises, sets, reps, RIR/RPE, rest, and supported prescription fields.
- Assign a template to one or more players as independent program copies.
- Customize an assigned program independently of its source template.
- Reuse templates indefinitely.

### Rule
Templates are starting points, not automatically synchronized live programs.

```text
Coach Template
      ↓
Assigned Player Program
      ↓
Player-specific customization
```

Editing a template must not silently modify already assigned programs.

---

## 3. Trial Web App

### Goal
The closed trial needs one web app for both player and coach capabilities, as
the Android app supports both in one account. Web and Android must share
features, data, and the MAYOS design system, with layouts adapted to iPhone
screens and desktop coach work. Assess whether the existing Flutter app can be
extended to web before selecting a separate frontend; the technology choice
remains open until a feasibility check.

### Architecture
Web uses the same:
- FastAPI backend
- Authentication
- Database
- Domain logic
- AI infrastructure
- Subscription/entitlement state

Do not create a separate web backend.

**Flutter web feasibility status (2026-09-25):** A disposable copy of the
current Flutter project passed `flutter analyze` and a JavaScript
`flutter build web` after adding web scaffolding. This proves compilation,
not trial readiness. Before choosing Flutter web, verify iPhone Safari login,
HTTPS token storage, API CORS/preflight, route reload/back navigation,
responsive player/coach layouts, and clear handling of failed online workout
writes. The current app has no web host; those browser checks are still open.
If Flutter-specific limitations block the required Safari experience, use
another web frontend against the same API. Hold the trial if the required
online behavior remains blocked in the browser.

### Coach Views on Web
The closed-trial minimum is:
- Authentication, coach profile, invitations, and assignment management.
- Roster and assigned-player workout history.
- Program creation, editing, publication, and player request handling.
- The working alert center and relevant roster summaries.

Reusable templates are a public-launch addition. Coach AI remains conditional
on its separate privacy and evaluation gate; subscriptions begin at public
launch. Account settings remain available.

Desktop UX should use the available screen space rather than stretching the mobile UI.

### Player Views on Web
The iPhone web experience must cover the Android player's trial features while
online: authentication and onboarding, current program, set/reps/load/RIR
logging, completion, history, coach program updates and assignment controls,
the player assistant, account management, and the same privacy boundaries.
Web does not provide offline use or Android-style offline workout drafts.
Connectivity requirements and failed-write states must be clear to the player.

### Platform strategy
```text
Closed trial → Android Flutter app + one web app for players and coaches
Public launch → Android app + the same shared web app
```

Native iOS is deferred until demand justifies it.

---

## 4. Migration & Data Portability

### Goal
Reduce switching friction from spreadsheets, existing apps, and manual workflows.

### Program Import
Spreadsheet program import is a later adoption feature, not a public-launch
gate. When added, target:
- `.xlsx`
- `.csv`

Flow:
1. Upload.
2. Parse.
3. Preview.
4. Detect ambiguous/missing fields.
5. Let coach correct mappings.
6. Deterministically validate.
7. Confirm.
8. Create MAYOS program/template.

AI may interpret inconsistent spreadsheet structures, but deterministic validation approves the final structured program.

### Export
At public launch, provide a machine-readable export of the player's current
program as JSON and workout history as CSV and JSON. Preserve the existing
program XLSX download as a presentation/logging workbook; it is not a complete
structured program export. Template, derived exercise-performance, progress,
and full-account archives can be specified separately after the basic export.

### Principle
MAYOS should make it easy to enter and reasonable to leave. Portability reduces platform-risk concerns.

---

## 5. Coach Authority

> **MAYOS analyzes, recommends, automates, and assists. The coach decides.**

MAYOS may:
- Detect problems/patterns.
- Recommend interventions.
- Explain evidence.
- Suggest programming changes.
- Generate candidate splits/programs.
- Prioritize players needing attention.

Coach may:
- Approve.
- Modify.
- Reject.
- Ignore.

Material coaching changes should not silently override the coach.

```text
Detect → Explain → Recommend → Coach decision → Deterministic execution
```

---

## 6. Core Workflow Reliability

Critical chain:

```text
Program delivery
→ Workout logging
→ Local persistence
→ Sync
→ Server state
→ Coach visibility
→ Coach update
→ Player receives update
```

### Workout Logging
- Fast input.
- No silent data loss.
- Safe duplicate handling.
- Recover interrupted workouts.

### Program Delivery
- Clearly identify active program/version.
- Propagate coach changes reliably.
- Handle stale/conflicting versions explicitly.

### Sync
- Tolerate temporary connectivity loss.
- Retry failed synchronization safely.
- Communicate meaningful sync state.
- Make critical writes idempotent where appropriate.

### Offline/Poor Network
Android workout logging preserves offline drafts under ADR 020. The web app is
online-only; a lost connection must surface an explicit failure instead of
claiming a workout was saved. Keep entries in the open tab's memory for an
explicit retry, using the server's idempotent session key so a lost response
cannot duplicate the workout. Web entries are not retained after the tab closes
or reloads; communicate that limit before the player starts logging.

---

## 7. Coach Onboarding & Player Invitation

### Goal
Minimize time from coach approval to first real player using MAYOS. The closed
trial retains owner-invited coaches. At public launch, an account holder may
self-sign up and request the coach capability; an owner approves that request
before coaching actions become available.

```text
Account signup → coach capability request → owner approval
→ Essential setup
→ Create/reuse program
→ Invite player
→ Player joins
→ Player completes onboarding and receives an auto-generated split
→ Coach may publish a replacement split
→ Player logs workouts from the active split
```

### Coach Requirements
- Quick account creation.
- Create first program without unnecessary setup.
- Generate/send player invite.
- See invite status.
- Resend/revoke invite.
- Publish a coach-authored split after the player's onboarding and assignment;
  the auto-generated split remains usable until then.

### Player Requirements
- Open invitation.
- Create/sign into account.
- Connect to coach.
- Complete required onboarding.
- Receive the generated split even if no coach is assigned.
- See a coach-authored split when the assigned coach publishes it later.
- Start training.

### Measure
Track:
- Coach approval → first connected player.
- Player invitation → first completed workout.

---

## 8. Coach–Player Data Ownership

### Principles
- Player owns their personal MAYOS account.
- Player retains personal workout history.
- Coach access depends on the coaching relationship.
- Ending the assignment immediately ends the former coach's access to both
  earlier and later private training history.
- Subscription status must not destroy user-owned training history.
- Public Coach Pro cross-player model requests require updated player
  disclosure and consent, active-assignment checks, identifier removal, and
  a separate privacy and evaluation gate. The closed trial keeps its
  one-selected-player coach-model boundary.
- The public roster briefing is on demand and stateless. Deterministic ranking
  selects at most five consenting, actively assigned players per model
  request; the model receives only needed de-identified evidence. Declining
  this model use does not remove ordinary authorized coach access or
  deterministic alerts.

### When Player Leaves Coach
- Player keeps the account, history, and current coach-authored program.
- Player continues on their own account, regardless of future subscription tier.
- Former coach loses access to the player's training history immediately.
- Shared coach-created records retained in the player's history follow the
  accepted assignment and account-deletion rules.
- No silent deletion without an explicit policy.

Finalize legal/privacy retention rules before production launch.

---

## 9. Subscription Lifecycle

Lifter Pro launches at 199 EGP/month and Coach Pro at 399 EGP/month; useful
Lifter Free and Coach Free plans remain available. Public sales begin at
launch, without a private paid-pilot gate. All advertised Pro benefits must
work before sale; if any listed benefit is missing, delay the entire public
launch. Tune proposed AI allowances and other tier details using measured
usage and cost before enabling them.
Test coach and player subscriptions separately; one account may have both
capabilities, and a coach subscription does not grant a player subscription to
assigned players.
After launch, review at least five standard-price coach payers and five player
payers. Track whether at least three in each cohort make a second monthly
payment and remain active: a player completes at least four workouts per month,
and a coach takes a recorded coaching action for an assigned player at least
weekly (for example, a check-in, program change, request response, or alert
action). Calculate contribution margin as collected subscription revenue minus
payment fees, hosted-model costs, and allocated hosting costs. If margin turns
negative, promptly review and adjust internal limits or costs. Track founding
coaches paying 299 EGP separately from standard-price coach payers. Model
subscription lifecycle states rather than only `is_pro`.

Design for:
- Free
- Active Pro
- Trial/promotion
- Payment pending
- Payment failed
- Roster over-cap grace
- Cancelled but active until period end
- Expired

Support:
- Subscribe
- Renew
- Cancel
- Failed-payment handling
- Entitlement restoration
- Promotional/free periods
- Duplicate-subscription prevention
- Clear current entitlement

Founding-coach rewards should use explicit promotion state, not manual database flags.
When payment fails, paid features continue only through the already-paid
period, then downgrade. The separate 14-day roster grace below does not
extend Pro features.
If an account drops from Coach Pro with more than five active players, allow a
14-day grace period. Afterward, coach access becomes read-only while the roster
is above five, except that either party may end an assignment. Program
publication, request responses, check-ins, and invitations resume when Pro
returns or the roster falls to five or fewer. Do not delete player data or end
assignments automatically.

---

## 10. AI Usage Metering

### Customer-facing
The pricing draft proposes simple daily request limits; tune
them from measured usage before committing a public plan:
- Free: **5/day**
- Pro: **30/day**

### Record Per Inference
- Account/user
- Lifter/coach role
- Subscription tier
- Model
- Timestamp
- Input tokens
- Output tokens
- Context tokens
- Request/use-case type
- Estimated cost
- Latency
- Success/failure

### Safeguards
- Daily request ceiling
- Context ceiling
- Output ceiling
- Rate limiting
- Abuse detection
- Per-account spend visibility
- Global spend alarms

Customer UX remains simple while internal controls remain granular.

---

## 11. Product Analytics

### Activation
Track:
- Account created
- Onboarding completed
- First program/template created
- First player invited
- Invitation accepted
- First program received
- First workout logged/completed
- First AI request
- First alarm generated/acted upon

### Engagement
Track:
- DAU/WAU/MAU
- Workouts logged/completed
- AI usage
- Active coached players
- Programs created/assigned
- Alarm interaction
- Coach dashboard usage
- Player retention

### Business
Track:
- Free → Pro conversion
- Lifter Pro conversion
- Coach Pro conversion
- MRR
- Churn
- Promotion/trial conversion
- Average coach roster
- Revenue per paying user
- AI cost per user/payer
- Infrastructure cost per active user

At **10,000 active accounts** (a completed workout or recorded coaching action
in the previous 30 days), review pricing using real telemetry. This is a
review milestone, not an automatic increase.

---

## 12. Automated Alarms

The Free/Pro split below is a feature proposal. Validate its usefulness
with coaches before enabling tier-specific alarm entitlements.

### Coach Free
Provide useful essential monitoring without aggressively limiting alarm count:
- Missed workouts
- Major adherence decline
- Clear progression stalls
- Significant performance deterioration

### Coach Pro
Unlock greater depth, breadth, and automation:
- Deeper stall detection
- Fatigue/performance trends
- Volume-related signals
- Cross-player prioritization
- Richer explanations
- Configurable monitoring
- Advanced future alarm categories

### Principle
Free demonstrates the value of monitoring. Pro unlocks the complete professional monitoring layer.

---

## 13. Privacy, Deletion & Export

Design for:
- Account deletion
- Personal/training data export
- Coach-player relationship removal
- Revocation of coach access
- Secure authentication
- Server-side authorization on every protected coach-player resource

A coach must never gain player data merely by knowing an player ID or manipulating a client request.

---

## 14. Founding Coach Program

### Goal
Treat early coaches as a structured validation cohort, not simply discount users.

### Trial Cohort Offer
- Only coaches who join during the free closed trial qualify for founder status.
- At public launch, receive **2 free Coach Pro months** automatically, without
  payment details or an automatic charge.
- After those months, a founding coach pays **299 EGP/month** instead of
  the public-launch standard **399 EGP/month** while continuously subscribed to
  Coach Pro. The coach must opt into web checkout before all earned free
  months end; there is no automatic charge or late signup window. Cancellation
  of renewal or a lapse ends the founder rate immediately. The founder rate
  remains 299 EGP/month even if the standard price later changes.
- Each referred coach must join during the closed trial. Their first
  successful subscription payment after billing begins adds one free month to
  the referring founding coach only while that founder's Coach Pro plan is
  active and renewal has not been cancelled, capped at two referral months.
  A raw signup earns nothing. Self-referrals are ineligible. A refund removes an unused
  credit; an already-used free month is not charged back.
- Rewards require valid participating coaches, not raw signups.

### Track
- Founding status
- Promotion start/end
- Referral source
- Successful referrals
- Earned months
- Post-promotion conversion
- Post-promotion churn

### Learn
Determine:
- Missing workflow features
- Migration friction
- Ignored features
- Essential features
- Remaining Excel/WhatsApp/manual work
- Player onboarding problems
- Why coaches would/would not pay 399 EGP

Key validation signal:

> After the promotion, does the coach voluntarily pay because losing MAYOS would materially hurt their workflow?

---

## 15. Deferred Features

Do not let these delay validation of the core coaching product.

### Coach Business Management
Future candidates:
- Coaching packages
- Client subscriptions
- Paid/unpaid tracking
- Renewals
- Revenue dashboard
- Client onboarding pipeline
- Leads
- Payment reminders

### Nutrition
Future candidates:
- Nutrition plans
- Macro/meal management
- Nutrition adherence
- Coach nutrition workflow

Evaluate scope and safety separately.

### Studio / Multi-Coach
Potential future tier:
- Multiple coaches
- Organization roles/permissions
- Shared organization dashboard
- Staff management
- Larger rosters
- Business analytics

Only introduce after real demand emerges.

### Native iOS
Defer native iOS and reassess from actual usage, retention, web/PWA limitations,
and customer requests when the later iPhone-access strategy is chosen.

---

## 16. Priority

### Closed-trial client gate
- Android app for both player and coach capabilities.
- One online-only web app for both capabilities: core coach console and iPhone
  player feature parity except Android-only offline drafts.
- Browser login, authorization, responsive layouts, and failed-write retry
  verified on the supported trial devices before trial access opens.

### P0 — Must Be Reliable
- Authentication
- Program delivery
- Workout logging
- Persistence
- Sync
- Coach/player updates
- Authorization
- AI metering
- Backup/recovery

### P1 — Strong Launch Requirements
- Basic coach templates
- Coach onboarding
- Player invitations
- Automated alarms
- Product analytics
- Data export

### Public subscriptions
- Launch Lifter Pro at 199 EGP/month and Coach Pro at 399 EGP/month through web
  checkout. The Android Play app consumes existing entitlements without sales
  links. Recheck store policy before release.
- Deliver every advertised Pro benefit before sale; tune proposed AI limits
  and context budgets against measured usage and costs.
- Add subscription lifecycle and server-side entitlements for public launch;
  keep training history independent of subscription state.
- Enforce the agreed five-active-player Coach Free cap when paid plans launch;
  track founding promotions explicitly.

### P2 — Adoption Accelerators
- Excel/CSV program import
- Advanced migration tooling
- Advanced exports
- Expanded alarm configuration

### Post-launch / Validation-dependent
- Coach business management
- Nutrition
- Studio tier
- Native iOS
- Large-organization features

---

## 17. Launch Checklist

- [ ] New coach can reach first player quickly.
- [ ] Coach can reuse program templates.
- [ ] Player reliably receives active program.
- [ ] Workout logging does not risk silent data loss.
- [ ] Poor connectivity fails gracefully.
- [ ] Coach updates reliably reach players.
- [ ] Coaches can inspect required player data.
- [ ] Public subscriptions enforce their entitlements server-side.
- [ ] Coach Free limits new active assignments to five players when paid plans launch.
- [ ] AI requests/tokens/cost are measured per account.
- [ ] Any approved Free/Pro alarm differentiation has been validated with coaches.
- [ ] Activation, conversion, retention, and churn are measurable.
- [ ] Coach access is revoked correctly when relationship ends.
- [ ] Relevant data can be exported.
- [ ] Account deletion is supported or finalized before production.
- [ ] Any approved founding promotions are explicitly tracked.
- [ ] The trial coach has an effective desktop/web workflow.
- [ ] The trial iPhone player can use the essential training workflow on the web.
- [ ] Coach remains final authority over coaching decisions.
- [ ] Deferred features are prevented from delaying the core launch.

---

## 18. Core Principle

```text
Easy migration
+ fast onboarding
+ reliable daily workflow
+ useful automation
+ trustworthy AI assistance
+ clear Free → Pro value
+ measurable unit economics
= sustainable adoption
```

Anything that does not materially improve one of these outcomes should be challenged before entering launch scope.
