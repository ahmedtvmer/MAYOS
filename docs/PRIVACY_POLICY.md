# MAYOS Privacy Policy

Effective date: {{POLICY_EFFECTIVE_DATE}} — Policy version {{POLICY_VERSION}}

## Who operates MAYOS

MAYOS (the "service", "we", "us") is operated by the MAYOS project, an
independent personal-training service. It is offered as a free,
invitation-only closed trial; nothing is sold during the trial.

Questions about this policy, your data, or your account: contact
{{PRIVACY_CONTACT}}.

The service runs on a single server in Frankfurt, Germany (Fly.io) and is
served over https from the address of this page.

## What we collect

### Account and sign-in

- Your **username** and an **immutable account id** that identifies you
  internally. A username is reusable: after an account is deleted the same
  username may be registered again, always as a brand-new account.
- Your **password**, stored only as a salted hash (bcrypt). We never store or
  log the password itself.
- Whether your account has **player** and/or **coach** capability, and the
  Free/Pro plan state of each capability.
- A **session epoch** used to revoke every signed-in session at once (for
  example when you change your password or delete your account).
- The **last day you used the app**, recorded as a UTC calendar day when you
  make an authenticated request.
- Your **recovery email**, if you have added one. It is required before you can
  use the app, it lives in the shared account store (not in your training
  data), and it is used only to send password-reset links and to answer
  password-recovery requests. If you sign up with Google, MAYOS may keep a
  verified Google email as your recovery email when it is not already used as
  another account's recovery email; that address is marked verified at signup.
  If the address already belongs to a live account, MAYOS shows a reminder but
  does not store Google's address if you create a separate account, and you
  must add and verify a recovery email with a code. When you later sign in with
  or connect Google, its verified email can verify your current unverified
  recovery email only when the addresses match. It never replaces a different
  address and is never used to link or merge accounts.
- **Sign-in tokens** (short-lived JSON Web Tokens). If you tick "Keep me signed
  in", the token lasts up to 30 days; otherwise about 2 hours. You can end a
  session at any time by logging out.

### Training ledger (your own training data)

Your training record is stored privately for your account and includes:

- Your **profile**: age, gender, weight, height, body proportions, training
  goals, weekly frequency, split and rep preferences, free-text injuries or
  limitations, the assistant's tone and any custom instructions or preferred
  name you wrote, and your **IANA time zone**.
- **Onboarding answers** you give while setting up.
- Your **training program(s)**, including versions and whether a coach
  published them.
- **Workouts**: sessions, sets, weights, reps, effort ratings (RIR/RPE),
  readiness, personal records, and any notes you log.
- **Imported history (existing records only)**: these records may include the source file name, a
  snapshot fingerprint, per-table row counts, the opt-in reference, and the
  import time. MAYOS does not accept new history imports. These records are
  deleted with your account; a restricted whole-catalog recovery snapshot may
  retain deleted rows for up to 30 days.
- Your **training schedule** and any schedule pauses.
- Your **assistant chat** (your messages and the assistant's replies).
- **Offline workout drafts** held on your device until they sync.

### Coaching data (shared only while an assignment is active)

- **Assignment and invite records**: who coaches whom, when it started or
  ended, and why it ended.
- **Check-ins** recorded by your coach, including the date, channel, and any
  note. Only coaches can create them. A check-in may record contact arranged
  outside MAYOS (for example a phone number or a link you both agreed to).
- **Coach alerts** derived from your training (for example a missed-day streak
  or a due follow-up) and their acknowledgement/resolution state.
- **Program requests** you send to your coach and their responses.
- **In-app notices** about coaching events.

### Emails we send

- A **password-reset link** containing a single-use token that expires in 30
  minutes, sent to your recovery email. This is the only email sent to you.
- A **notice to your coach** when you redeem their invite; it contains your
  username, and nothing about your training.
- A **notice to your coach** when you ask them for a program change; it says
  only that your username requested a program change and asks them to review
  their roster — no exercise, day, slot, or requested change is named.

We do not email you about check-ins, coach alerts, or your coach's replies:
those appear in the app only.

Email is sent through the operator's email (SMTP) provider, which processes the
recipient address and message content to deliver it.

### Product analytics

MAYOS uses **PostHog (EU Cloud)** as a product-analytics processor to measure
how the service is used — onboarding, workouts, coaching, programs, and AI.
The service, and release builds of the Android and web app, send
**pseudonymous events** tied to your immutable internal account id, never to
your username or email.

- Events carry only allowlisted facts: the event name, your capability
  (player or coach), the app platform and version, counts, durations, and
  similar coded values. They never contain free text, chat messages, onboarding
  answers, check-in notes, prompts or AI responses, exercise names, loads, or
  other workout contents.
- Usernames, emails, passwords, and sign-in tokens are never sent. IP addresses
  are discarded: the PostHog project is configured not to store client IP
  data, and the app turns off session recording, autocapture, and similar
  automatic collection.
- When you register we record where you came from, once: campaign labels from
  the link you opened (such as `utm_source`), the referring website's host name
  (never the full address), the Android install referrer's campaign labels, and
  the coach whose invite you first redeemed. This record is never changed
  afterwards.
- **You can turn product analytics off** in Settings. When it is off, MAYOS
  stops sending events about your account from both the service and the app;
  the choice is stored with your account and applies on every device you sign
  in on. A coach's own events (for example, that their roster grew) are subject
  to the coach's choice and never identify you.

### Model usage records

Every AI request is metered per account for cost control: the immutable account
id, the player/coach role, the model, the purpose, input/output token counts
and the estimated cost. These rows carry **no username and no contact details**
and are kept after deletion for cost reconciliation.

### Owner access

The owner can see account metadata — your username, account dates, capabilities,
plan, masked recovery email, and model usage — through an owner-only admin page.
Recovery-email lookups and owner actions are audited. That page never shows your
training content or chats.

### Service logs

Like any web service we keep operational logs. They include request metadata
such as your IP address, the path and time of the request, and errors, and may
include your username when something about your account is being debugged.
Password-reset tokens are redacted from access logs. Logs are kept only as long
as they are useful for operating and securing the service.

### Children

MAYOS is a training tool for adults and older teenagers; it is **not directed
at children under 16**, and we do not knowingly collect personal data from
them. If you believe a child under 16 has provided us with data, contact us and
we will delete it.

## How your coach can see your data

Coaching access is built on mutual consent:

- A coach can only reach your history through an **assignment** you explicitly
  accept. Before accepting, the invite shows you the access it grants. Invite
  codes are single-use and expire quickly.
While the assignment is **active**, your coach sees:

- your **username**, when the assignment started, and its status;
- your **training history**: committed workouts with their sets, weights,
  reps, effort ratings (RIR/RPE) and readiness, skipped or unplanned exercises,
  the **performed-date corrections** you made, upload/edit timestamps, your
  program and its versions, volume figures, personal records, and
  per-exercise progression (weight, reps, RIR, estimated one-rep max);
- your **schedule**: expected training weekdays, your **time zone**, and your
  schedule pauses;
- your **check-ins** (date, channel, note);
- **coach alerts** — missed-day streaks, due follow-ups, and deload or
  regression alerts together with the training evidence behind them — plus their
  acknowledgement state and your roster-facing counts (new and acknowledged
  alerts, current streak, next follow-up date);
- **program requests** you send, with their state.
- Your **assistant chat is private**. A coach never sees your conversation with
  the MAYOS assistant, and no coach-facing feature sends it anywhere.
- **Ending the assignment** — by you or by your coach — cuts off access
  immediately, including to the history you accumulated before it ended.
- Records that are part of *your* history stay with you: the check-ins your
  coach wrote (visible to both of you) and the program they published remain in
  your account after the assignment ends. If a coach deletes their account,
  they are shown as "Former coach" rather than by a reusable username.

## AI features and hosted model providers

MAYOS can run its AI features on the operator's own hardware or through a
hosted, OpenAI-compatible model provider (the closed-trial deployment uses
DeepInfra by default, configured by the operator). When a hosted provider is
configured, the following is sent to it:

- **Assistant chat**: the message you sent, the recent turns of your
  conversation, and a compact training summary built from your profile (for
  example gender, age, weight, height, proportions, goal, split and rep
  preference), your active program's name/frequency/split, your most recent
  session's top set, and your current fatigue/deload state, plus the assistant
  tone, custom instructions and preferred name you wrote. It does **not**
  include your username, your recovery email, your coach's name or contact
  details, your coach's private notes, or anything a coach wrote about you.
- **Checkpoint review wording (when enabled)**: only the reduced training totals
  and computed rating parts for that Checkpoint, your Display language, your
  chosen Assistant style, and your trimmed optional wording instructions (up to
  500 characters). Other profile facts, identity/contact fields, notes and chat
  are not selected for this request. Instructions you write may themselves
  contain identifying information. The saved player prose is never rewritten;
  your assigned coach reads a neutral view of the facts and rating instead.
- **Onboarding**: the answers you type while setting up, so your profile and
  program can be built.
- **Program generation**: deterministic in the normal case — day templates,
  exercise selection, warm-ups, and progression rules are computed without the
  model. Only a **free-text split request** that the deterministic router
  cannot map reaches it, and it receives only that text plus your weekly
  training frequency and a gender context (for example "trainee: male trainee").
  Your injuries, goals, and the rest of your profile are not sent for this.
- **Coach-side program publishing**: when your coach publishes or regenerates
  your program, the same split-planning inputs are sent — your weekly
  frequency, your gender context, and any split request your coach typed —
  attributed to the coach's account. Coach-side AI never receives your
  assistant chat, your username, or any contact details.

**Free text you type can contain identifying information, and it is sent to the
model exactly as you wrote it.** Chat messages, onboarding answers, custom
instructions, your preferred name, and any free-text split request are plain
text: if you put your name, address, phone number or anything else identifying
in them, it leaves the service and is processed by the model provider. Please
keep identifying details out of free-text fields.

AI usage is metered per account and rate-limited, so a runaway client cannot
consume unlimited model capacity.

### Coach AI analysis (when enabled by the operator)

An optional feature lets your coach ask a short analysis question about you in
the coach console. It exists **only when the operator has enabled it** (the
service reports it as available; otherwise the app hides the entry point and
the request is refused).

When it is enabled, each question sends to the model:

- the coach's own question, plus the recent coach–assistant turns the app is
  holding in memory for the one selected player — the coach's text, sent
  exactly as they wrote it; and
- a telemetry block built from what your coach can already see: your active
  program's structure and version, your volume totals for the last 7 and 28
  days, your recent sessions (date, sets, volume, readiness, skipped or
  unplanned exercises), your personal records, adherence and missed-day
  figures, coach alerts, your schedule and pauses, and the dates, channels, and
  coach-written notes on your five most recent check-ins (each note is capped
  at 300 characters). It also receives your current goal, Experience level,
  Equipment access, your dated bodyweight trend for the last 8 weeks, and the
  weekly best e1RM trend for the main lifts in your active Training program
  for the last 12 weeks.

These added facts describe coaching and training rather than identity.
Check-in notes are free text and may contain identifying details; their length
is capped and their use in hosted processing is disclosed here and in the
coach console. The model does **not** receive your username or any account id,
your recovery email, your coach's name or bio, your conversation with the MAYOS
assistant, your Assistant style or custom instructions, your preferred name,
the reason or response on a program request, or other program-request free
text. Every number (volume, e1RM and bodyweight trends, adherence, and
streaks) is calculated by the service before the call; the model is told to
rely on those figures and to say when data is not available. It gives no
medical advice.

Nothing about the exchange is stored. The app keeps the short conversation in
memory for the one selected player and clears it when the player is switched,
when the assignment ends, on logout, and when the app closes. The service
keeps no transcript of these questions and answers — only the per-account
model usage records described above, attributed to your coach's account.

## How long we keep your data

- **Live data is kept while your account exists**, and is deleted when you
  delete your account.
- **On deletion** we remove your training ledger (profile, program, workouts,
  schedule, chat, drafts' server-side state), your recovery email and reset
  tokens, your invites, and the relationships that existed only to serve you;
  every session is invalidated, and any active assignment ends immediately.
  Your account's copies in the daily backups are removed too.
- **Restricted recovery backups**: whole-catalog snapshots exist for disaster
  recovery and are retained for at most **30 days**. A deleted row may briefly
  survive in one of those restricted snapshots until it ages out; that is the
  only place deleted data can linger, and it is never restored to a live
  account — every restore reapplies the deletion record first.
- **A deletion record** (an internal account id, the ledger id, and the
  deletion time) is kept outside the snapshots precisely so a restored backup
  cannot bring you back.
- **Model usage rows** stay after deletion, keyed only by the opaque account
  id, for cost reconciliation.
- **Product analytics**: deleting your account removes your registration-source
  record and your analytics choice, and asks PostHog to delete your analytics
  person and its events. If PostHog cannot be reached, MAYOS keeps retrying
  automatically until the request succeeds.
- **Other people's history**: check-ins you wrote as a coach and programs you
  published stay in the players' own accounts (you appear as "Former coach"),
  because those records are part of their history.
- **Service logs** are kept only as long as they remain useful for operations
  and security.

## Deleting your account

You can delete your account yourself, without contacting anyone:

- **In the app**: Settings → Profile → Delete account, then confirm with your
  password.
- **On the web**: open [`/account/delete-request`](/account/delete-request) on
  this site, enter your username and password, tick the confirmation box, and
  submit. The same password check applies as in the app.

Deletion is immediate and irreversible. We never tell you whether a given
username exists: an unknown username, a wrong password, and a password-less
account all produce the same generic answer. If you have forgotten your
password, reset it first from the app ("Forgot password") or contact
{{PRIVACY_CONTACT}} and we will help.

If you are a Coach, your Coach exercise names and body-part/equipment tags
remain when they are part of a player's program or history. Your notes and
video links are cleared.

## How we protect your data

- All traffic is served over https; connections are encrypted in transit.
- Passwords are stored only as salted bcrypt hashes; sessions are signed tokens
  that we can revoke instantly.
- Sign-in, password, and deletion endpoints are rate-limited, and AI requests
  are limited per account.
- A coach can only open your training data after an assignment check on every
  request; there is no shared "admin" view of player chats.
- Exercise content is served from our own host; the app loads no third-party
  scripts, fonts, or trackers.

No system is perfectly secure. If we learn of a breach affecting your data we
will contact you at your recovery email where we have one.

## Changes to this policy

The version and effective date at the top of this page identify the current
policy. When we change what the service collects or how it is used — for
example by enabling product analytics or adding a new AI feature — we will
update this page and bump the version before the change takes effect.

## Contact

{{PRIVACY_CONTACT}}
