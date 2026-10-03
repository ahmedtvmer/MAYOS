# MAYOS roadmap: closed trial and public launch

All 151 open issues in [ahmedtvmer/MAYOS](https://github.com/ahmedtvmer/MAYOS/issues) as of 2026-10-03, grouped by phase and then by topic. "After" lists only blockers that are still open. Inside each section, issues are listed in a workable order.

Decisions recorded on 2026-10-03:

- Core coach authoring and the current-program work are in the closed trial.
- The trial gets an Arabic localization subset: Display language, coach labels, errors and onboarding. #251 joins because #253 can't start until it's done.
- The closed-trial gate #44 doesn't yet list the newly added trial issues as blockers.

## 1. Before the closed trial (51)

Everything the closed-trial gate needs. Run the gate (1.11) last.

### 1.1 Bugs and small player/coach fixes

The coach redesign spec says the two publish bugs, #288 and #289, ship immediately.

- [ ] [#277](https://github.com/ahmedtvmer/MAYOS/issues/277) Prevent duplicate programs when onboarding finishes on two devices at once
- [ ] [#281](https://github.com/ahmedtvmer/MAYOS/issues/281) Log bodyweight and band sets at 0 kg
- [ ] [#288](https://github.com/ahmedtvmer/MAYOS/issues/288) Reject an unrecognised split override when a coach publishes a program
- [ ] [#289](https://github.com/ahmedtvmer/MAYOS/issues/289) A coach's days-per-week choice no longer changes the player's Training profile
- [ ] [#278](https://github.com/ahmedtvmer/MAYOS/issues/278) Remove "Regenerate program" and point players to the assistant or their coach
- [ ] [#279](https://github.com/ahmedtvmer/MAYOS/issues/279) Assistant refusal offers a pre-filled request to the coach
- [ ] [#282](https://github.com/ahmedtvmer/MAYOS/issues/282) "Exercises" divider after the warm-up block in the workout logger
- [ ] [#287](https://github.com/ahmedtvmer/MAYOS/issues/287) "Most reps" personal record for bodyweight and band sets at 0 kg (after [#281](https://github.com/ahmedtvmer/MAYOS/issues/281))

### 1.2 Account recovery and email

Today a mistyped recovery email still receives password reset links. #286 is optional but makes inviting coaches easier.

- [ ] [#280](https://github.com/ahmedtvmer/MAYOS/issues/280) Verify the recovery email with a code at the gate
- [ ] [#283](https://github.com/ahmedtvmer/MAYOS/issues/283) Send password resets only to verified recovery emails (after [#280](https://github.com/ahmedtvmer/MAYOS/issues/280))
- [ ] [#285](https://github.com/ahmedtvmer/MAYOS/issues/285) Google sign-up and sign-in count as a verified recovery email (after [#280](https://github.com/ahmedtvmer/MAYOS/issues/280))
- [ ] [#284](https://github.com/ahmedtvmer/MAYOS/issues/284) Change the recovery email from Settings (after [#280](https://github.com/ahmedtvmer/MAYOS/issues/280))
- [ ] [#286](https://github.com/ahmedtvmer/MAYOS/issues/286) Email a Coach invite from the Owner dashboard (after [#280](https://github.com/ahmedtvmer/MAYOS/issues/280))

### 1.3 Product analytics

Accounts are tagged with their signup cohort and acquisition channel only once, at signup. Land at least #91–#95 before the first invite.

- [ ] [#90](https://github.com/ahmedtvmer/MAYOS/issues/90) Product analytics foundation for the closed trial
- [ ] [#91](https://github.com/ahmedtvmer/MAYOS/issues/91) Analytics tracer: account and onboarding events reach PostHog
- [ ] [#92](https://github.com/ahmedtvmer/MAYOS/issues/92) Identify client platform and add the Flutter analytics client (after [#91](https://github.com/ahmedtvmer/MAYOS/issues/91))
- [ ] [#93](https://github.com/ahmedtvmer/MAYOS/issues/93) Disclose analytics and let accounts opt out (after [#92](https://github.com/ahmedtvmer/MAYOS/issues/92))
- [ ] [#94](https://github.com/ahmedtvmer/MAYOS/issues/94) Record first-touch acquisition (after [#92](https://github.com/ahmedtvmer/MAYOS/issues/92))
- [ ] [#95](https://github.com/ahmedtvmer/MAYOS/issues/95) Delete analytics data with the account (after [#93](https://github.com/ahmedtvmer/MAYOS/issues/93), [#94](https://github.com/ahmedtvmer/MAYOS/issues/94))
- [ ] [#96](https://github.com/ahmedtvmer/MAYOS/issues/96) Emit coaching relationship events (after [#91](https://github.com/ahmedtvmer/MAYOS/issues/91))
- [ ] [#97](https://github.com/ahmedtvmer/MAYOS/issues/97) Emit workout lifecycle events (after [#92](https://github.com/ahmedtvmer/MAYOS/issues/92))
- [ ] [#98](https://github.com/ahmedtvmer/MAYOS/issues/98) Emit program and program-request events (after [#91](https://github.com/ahmedtvmer/MAYOS/issues/91))
- [ ] [#99](https://github.com/ahmedtvmer/MAYOS/issues/99) Emit coach alert, check-in and review events (after [#91](https://github.com/ahmedtvmer/MAYOS/issues/91))
- [ ] [#100](https://github.com/ahmedtvmer/MAYOS/issues/100) Emit AI usage events from metering (after [#91](https://github.com/ahmedtvmer/MAYOS/issues/91))
- [ ] [#101](https://github.com/ahmedtvmer/MAYOS/issues/101) Complete the tracking plan, dashboards and privacy review (after [#95](https://github.com/ahmedtvmer/MAYOS/issues/95), [#96](https://github.com/ahmedtvmer/MAYOS/issues/96), [#97](https://github.com/ahmedtvmer/MAYOS/issues/97), [#98](https://github.com/ahmedtvmer/MAYOS/issues/98), [#99](https://github.com/ahmedtvmer/MAYOS/issues/99), [#100](https://github.com/ahmedtvmer/MAYOS/issues/100))

### 1.4 Settings by mode

#292 is close to a privacy bug: in Coach mode, Settings opens the player chat over the coach's own data.

- [ ] [#290](https://github.com/ahmedtvmer/MAYOS/issues/290) Spec: Settings follow Player mode and Coach mode
- [ ] [#291](https://github.com/ahmedtvmer/MAYOS/issues/291) Settings show mode-specific sections, and "Coaching assignment" becomes "My coach"
- [ ] [#292](https://github.com/ahmedtvmer/MAYOS/issues/292) No route to the player chat while in Coach mode (after [#291](https://github.com/ahmedtvmer/MAYOS/issues/291))

### 1.5 Coach Pro switch for the trial

Every Pro-gated coach feature depends on this.

- [ ] [#329](https://github.com/ahmedtvmer/MAYOS/issues/329) Coach plan entitlement check with a closed-trial override

### 1.6 Coach program authoring (core)

A coach can't write a program today. Order: #294 → #295 → #296. #322 can start once #294 is done.

- [ ] [#293](https://github.com/ahmedtvmer/MAYOS/issues/293) Spec: Coaches write programs in MAYOS and import them from a spreadsheet
- [ ] [#294](https://github.com/ahmedtvmer/MAYOS/issues/294) Tracer: a coach writes a one-day program by hand and publishes it
- [ ] [#295](https://github.com/ahmedtvmer/MAYOS/issues/295) Full coach program editor: multiple days, rest, tempo, notes, warm-up and cardio (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294))
- [ ] [#296](https://github.com/ahmedtvmer/MAYOS/issues/296) "Generate draft" replaces the coach publish dialog (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295), [#288](https://github.com/ahmedtvmer/MAYOS/issues/288), [#289](https://github.com/ahmedtvmer/MAYOS/issues/289))
- [ ] [#322](https://github.com/ahmedtvmer/MAYOS/issues/322) Coach exercises for movements the Exercise library lacks (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294))

### 1.7 Coach sees and edits the current program

- [ ] [#300](https://github.com/ahmedtvmer/MAYOS/issues/300) Spec: Coaches see and edit a player's current program (after [#293](https://github.com/ahmedtvmer/MAYOS/issues/293))
- [ ] [#301](https://github.com/ahmedtvmer/MAYOS/issues/301) Coach sees the player's active program on the player page
- [ ] [#302](https://github.com/ahmedtvmer/MAYOS/issues/302) Edit the player's current program as a draft, or approve it as is (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295), [#301](https://github.com/ahmedtvmer/MAYOS/issues/301))
- [ ] [#303](https://github.com/ahmedtvmer/MAYOS/issues/303) Player sees what changed when the coach publishes a program (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294))
- [ ] [#324](https://github.com/ahmedtvmer/MAYOS/issues/324) Resolve the player's open requests when the coach publishes (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295))
- [ ] [#325](https://github.com/ahmedtvmer/MAYOS/issues/325) Player sees "Your coach is preparing your program" until the first coach publish

### 1.8 Arabic localization (trial subset)

Must be done in this order: #250 → #251 → #253 → #254.

- [ ] [#250](https://github.com/ahmedtvmer/MAYOS/issues/250) Choose and restore account Display language
- [ ] [#251](https://github.com/ahmedtvmer/MAYOS/issues/251) Read coach alerts and roster labels in Display language (after [#250](https://github.com/ahmedtvmer/MAYOS/issues/250))
- [ ] [#253](https://github.com/ahmedtvmer/MAYOS/issues/253) Understand HTTP and streaming errors in Display language (after [#251](https://github.com/ahmedtvmer/MAYOS/issues/251))
- [ ] [#254](https://github.com/ahmedtvmer/MAYOS/issues/254) Complete structured onboarding in the selected language (after [#253](https://github.com/ahmedtvmer/MAYOS/issues/253))

### 1.9 Arabic safety evaluation and typography

- [ ] [#245](https://github.com/ahmedtvmer/MAYOS/issues/245) Arabic evaluation and typography: accepted spec for #138 and #143
- [ ] [#247](https://github.com/ahmedtvmer/MAYOS/issues/247) Arabic player evaluation: reviewed cases and separate safety outcomes (after [#245](https://github.com/ahmedtvmer/MAYOS/issues/245))
- [ ] [#249](https://github.com/ahmedtvmer/MAYOS/issues/249) Confirm IBM Plex Sans Arabic on Arabic RTL Home, logger and chat (after [#245](https://github.com/ahmedtvmer/MAYOS/issues/245))

### 1.10 Optional low-cost guards

- [ ] [#267](https://github.com/ahmedtvmer/MAYOS/issues/267) 400-character chat input limit
- [ ] [#266](https://github.com/ahmedtvmer/MAYOS/issues/266) Remove the local GGUF backend (prefactor)

### 1.11 Closed-trial gate

Run last. Closing #44 closes the epic #18.

- [ ] [#44](https://github.com/ahmedtvmer/MAYOS/issues/44) Run closed-trial release gate
- [ ] [#18](https://github.com/ahmedtvmer/MAYOS/issues/18) MAYOS Android closed trial: coaching platform and mobile migration

## 2. During the closed trial (1)

Needs real trial traffic.

### 2.1 AI usage measurement

- [ ] [#262](https://github.com/ahmedtvmer/MAYOS/issues/262) Measure paired Arabic/English DeepSeek usage and adjust the common trial cap (after [#190](https://github.com/ahmedtvmer/MAYOS/issues/190), [#194](https://github.com/ahmedtvmer/MAYOS/issues/194))

## 3. Before public launch (82)

#76 is the public launch gate.

### 3.1 Subscriptions, entitlements and Pro benefits

- [ ] [#55](https://github.com/ahmedtvmer/MAYOS/issues/55) Public launch subscriptions, entitlements, and Pro benefits
- [ ] [#57](https://github.com/ahmedtvmer/MAYOS/issues/57) Enforce plan-aware coach roster caps
- [ ] [#58](https://github.com/ahmedtvmer/MAYOS/issues/58) Sell Lifter Pro through web checkout
- [ ] [#59](https://github.com/ahmedtvmer/MAYOS/issues/59) Sell Coach Pro through web checkout (after [#57](https://github.com/ahmedtvmer/MAYOS/issues/57), [#58](https://github.com/ahmedtvmer/MAYOS/issues/58))
- [ ] [#60](https://github.com/ahmedtvmer/MAYOS/issues/60) Use web subscriptions in the Android app (after [#58](https://github.com/ahmedtvmer/MAYOS/issues/58), [#59](https://github.com/ahmedtvmer/MAYOS/issues/59))
- [ ] [#61](https://github.com/ahmedtvmer/MAYOS/issues/61) Handle subscription renewal and expiry (after [#58](https://github.com/ahmedtvmer/MAYOS/issues/58), [#59](https://github.com/ahmedtvmer/MAYOS/issues/59))
- [ ] [#62](https://github.com/ahmedtvmer/MAYOS/issues/62) Grant founding coaches two free months (after [#57](https://github.com/ahmedtvmer/MAYOS/issues/57))
- [ ] [#63](https://github.com/ahmedtvmer/MAYOS/issues/63) Convert founders to the 299 EGP plan (after [#59](https://github.com/ahmedtvmer/MAYOS/issues/59), [#61](https://github.com/ahmedtvmer/MAYOS/issues/61), [#62](https://github.com/ahmedtvmer/MAYOS/issues/62))
- [ ] [#64](https://github.com/ahmedtvmer/MAYOS/issues/64) Award and reverse founding referral months (after [#61](https://github.com/ahmedtvmer/MAYOS/issues/61), [#63](https://github.com/ahmedtvmer/MAYOS/issues/63))
- [ ] [#65](https://github.com/ahmedtvmer/MAYOS/issues/65) Apply the over-cap Coach Free grace (after [#57](https://github.com/ahmedtvmer/MAYOS/issues/57), [#61](https://github.com/ahmedtvmer/MAYOS/issues/61))
- [ ] [#66](https://github.com/ahmedtvmer/MAYOS/issues/66) Enforce the Lifter AI allowance and resource safeguard (after [#253](https://github.com/ahmedtvmer/MAYOS/issues/253))
- [ ] [#67](https://github.com/ahmedtvmer/MAYOS/issues/67) Enforce the Coach AI allowance and resource safeguard (after [#66](https://github.com/ahmedtvmer/MAYOS/issues/66))
- [ ] [#68](https://github.com/ahmedtvmer/MAYOS/issues/68) Show Lifter Pro history analysis (after [#58](https://github.com/ahmedtvmer/MAYOS/issues/58))
- [ ] [#69](https://github.com/ahmedtvmer/MAYOS/issues/69) Use longer relevant context for Lifter Pro (after [#58](https://github.com/ahmedtvmer/MAYOS/issues/58), [#66](https://github.com/ahmedtvmer/MAYOS/issues/66))
- [ ] [#70](https://github.com/ahmedtvmer/MAYOS/issues/70) Differentiate Free and Pro coach alerts (after [#59](https://github.com/ahmedtvmer/MAYOS/issues/59))
- [ ] [#74](https://github.com/ahmedtvmer/MAYOS/issues/74) Review Coach Pro program proposals (after [#59](https://github.com/ahmedtvmer/MAYOS/issues/59))
- [ ] [#75](https://github.com/ahmedtvmer/MAYOS/issues/75) Review subscription economics and activity (after [#61](https://github.com/ahmedtvmer/MAYOS/issues/61), [#64](https://github.com/ahmedtvmer/MAYOS/issues/64))

### 3.2 AI allowances and budgets

- [ ] [#261](https://github.com/ahmedtvmer/MAYOS/issues/261) Arabic AI allowance and resource safeguards: accepted specification
- [ ] [#263](https://github.com/ahmedtvmer/MAYOS/issues/263) Finalize measured Lifter and Coach launch request and resource limits (after [#262](https://github.com/ahmedtvmer/MAYOS/issues/262), [#67](https://github.com/ahmedtvmer/MAYOS/issues/67), [#66](https://github.com/ahmedtvmer/MAYOS/issues/66), [#69](https://github.com/ahmedtvmer/MAYOS/issues/69))

### 3.3 DeepSeek tuning and the model gate

The spec says all of it must be done before public launch. #184 looks out of date (#186 is closed): check it and close it if so.

- [ ] [#187](https://github.com/ahmedtvmer/MAYOS/issues/187) Spec: DeepSeek tuning
- [ ] [#197](https://github.com/ahmedtvmer/MAYOS/issues/197) One place that builds the player's chat prompt (prefactor, no behaviour change)
- [ ] [#188](https://github.com/ahmedtvmer/MAYOS/issues/188) Remove the LLM from onboarding
- [ ] [#189](https://github.com/ahmedtvmer/MAYOS/issues/189) Model gate, first cut: two judges, Q&A and generalization bars (after [#188](https://github.com/ahmedtvmer/MAYOS/issues/188))
- [ ] [#190](https://github.com/ahmedtvmer/MAYOS/issues/190) Count the hosted prompt budget in tokens, not bytes (Arabic history) (after [#197](https://github.com/ahmedtvmer/MAYOS/issues/197))
- [ ] [#191](https://github.com/ahmedtvmer/MAYOS/issues/191) Arabic exercise swaps by chat: model routing with data-validated actions (tracer) (after [#198](https://github.com/ahmedtvmer/MAYOS/issues/198))
- [ ] [#192](https://github.com/ahmedtvmer/MAYOS/issues/192) Make DeepSeek prompt caching work (after [#197](https://github.com/ahmedtvmer/MAYOS/issues/197), [#189](https://github.com/ahmedtvmer/MAYOS/issues/189))
- [ ] [#193](https://github.com/ahmedtvmer/MAYOS/issues/193) Adapt the player prompts for DeepSeek-V4-Flash (after [#189](https://github.com/ahmedtvmer/MAYOS/issues/189), [#198](https://github.com/ahmedtvmer/MAYOS/issues/198), [#199](https://github.com/ahmedtvmer/MAYOS/issues/199), [#192](https://github.com/ahmedtvmer/MAYOS/issues/192))
- [ ] [#194](https://github.com/ahmedtvmer/MAYOS/issues/194) Per-call-site output budgets for the player model
- [ ] [#195](https://github.com/ahmedtvmer/MAYOS/issues/195) Longer conversation memory for every player (after [#190](https://github.com/ahmedtvmer/MAYOS/issues/190), [#192](https://github.com/ahmedtvmer/MAYOS/issues/192))
- [ ] [#196](https://github.com/ahmedtvmer/MAYOS/issues/196) Reasoning mode for split plans and program generation (probe first) (after [#199](https://github.com/ahmedtvmer/MAYOS/issues/199), [#194](https://github.com/ahmedtvmer/MAYOS/issues/194))
- [ ] [#198](https://github.com/ahmedtvmer/MAYOS/issues/198) Routing suite in the model gate: English and Arabic, no unauthorized actions (after [#189](https://github.com/ahmedtvmer/MAYOS/issues/189))
- [ ] [#199](https://github.com/ahmedtvmer/MAYOS/issues/199) Structured-output and Arabic-reply suites in the model gate (after [#189](https://github.com/ahmedtvmer/MAYOS/issues/189))
- [ ] [#200](https://github.com/ahmedtvmer/MAYOS/issues/200) Arabic program changes, frequency changes and history questions by chat (after [#191](https://github.com/ahmedtvmer/MAYOS/issues/191))
- [ ] [#184](https://github.com/ahmedtvmer/MAYOS/issues/184) Evaluate DeepSeek-V4-Flash as the hosted player model

### 3.4 Coach program templates

Business requirements §2 makes templates a launch requirement.

- [ ] [#304](https://github.com/ahmedtvmer/MAYOS/issues/304) Spec: Coach program templates (after [#293](https://github.com/ahmedtvmer/MAYOS/issues/293))
- [ ] [#305](https://github.com/ahmedtvmer/MAYOS/issues/305) Template library: create, name, edit, duplicate and archive (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295))
- [ ] [#306](https://github.com/ahmedtvmer/MAYOS/issues/306) Assign a template to one or more players as independent drafts (after [#305](https://github.com/ahmedtvmer/MAYOS/issues/305))
- [ ] [#307](https://github.com/ahmedtvmer/MAYOS/issues/307) Save a player's program as a template (after [#305](https://github.com/ahmedtvmer/MAYOS/issues/305), [#301](https://github.com/ahmedtvmer/MAYOS/issues/301))

### 3.5 Coach program authoring (rest)

#298, the spreadsheet import, serves the "easy migration" launch priority.

- [ ] [#297](https://github.com/ahmedtvmer/MAYOS/issues/297) Load prescription per exercise: kg or % of e1RM (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295))
- [ ] [#323](https://github.com/ahmedtvmer/MAYOS/issues/323) Set groups per exercise: top set plus back-off sets, and AMRAP (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295), [#297](https://github.com/ahmedtvmer/MAYOS/issues/297))
- [ ] [#298](https://github.com/ahmedtvmer/MAYOS/issues/298) Import a program from the MAYOS spreadsheet template into a draft (after [#294](https://github.com/ahmedtvmer/MAYOS/issues/294), [#295](https://github.com/ahmedtvmer/MAYOS/issues/295), [#297](https://github.com/ahmedtvmer/MAYOS/issues/297), [#305](https://github.com/ahmedtvmer/MAYOS/issues/305), [#322](https://github.com/ahmedtvmer/MAYOS/issues/322))

### 3.6 Week-by-week programs

Could slip past launch if needed.

- [ ] [#299](https://github.com/ahmedtvmer/MAYOS/issues/299) Spec: Week-by-week programs (after [#293](https://github.com/ahmedtvmer/MAYOS/issues/293))
- [ ] [#330](https://github.com/ahmedtvmer/MAYOS/issues/330) A coach writes a two-week program and the player moves through it (after [#295](https://github.com/ahmedtvmer/MAYOS/issues/295))
- [ ] [#331](https://github.com/ahmedtvmer/MAYOS/issues/331) Duplicate a week in the editor and import a week column (after [#330](https://github.com/ahmedtvmer/MAYOS/issues/330), [#298](https://github.com/ahmedtvmer/MAYOS/issues/298))
- [ ] [#332](https://github.com/ahmedtvmer/MAYOS/issues/332) End of block: repeat the final week, alert the coach, tell the player (after [#330](https://github.com/ahmedtvmer/MAYOS/issues/330))

### 3.7 Coach-mode roster assistant

Coach Pro only from public launch. #326 must ship before #311.

- [ ] [#308](https://github.com/ahmedtvmer/MAYOS/issues/308) Spec: Coach-mode assistant across the roster
- [ ] [#309](https://github.com/ahmedtvmer/MAYOS/issues/309) Assistant tab in the Coach shell (after [#292](https://github.com/ahmedtvmer/MAYOS/issues/292))
- [ ] [#310](https://github.com/ahmedtvmer/MAYOS/issues/310) Roster signal snapshot and the coach stall threshold
- [ ] [#326](https://github.com/ahmedtvmer/MAYOS/issues/326) Disclose roster-AI use at assignment acceptance, with a one-time notice for existing players
- [ ] [#311](https://github.com/ahmedtvmer/MAYOS/issues/311) Coach Pro roster questions over the signal snapshot (after [#309](https://github.com/ahmedtvmer/MAYOS/issues/309), [#310](https://github.com/ahmedtvmer/MAYOS/issues/310), [#326](https://github.com/ahmedtvmer/MAYOS/issues/326))

### 3.8 Coach assistant context for one player

- [ ] [#312](https://github.com/ahmedtvmer/MAYOS/issues/312) Spec: The coach assistant sees the coaching facts it needs about one player
- [ ] [#313](https://github.com/ahmedtvmer/MAYOS/issues/313) Keep a dated history of the player's weight
- [ ] [#314](https://github.com/ahmedtvmer/MAYOS/issues/314) Coach assistant context: goal, experience, equipment, trends and check-in notes (after [#313](https://github.com/ahmedtvmer/MAYOS/issues/313))
- [ ] [#315](https://github.com/ahmedtvmer/MAYOS/issues/315) Coach assistant context: injuries and exercise clearances (after [#273](https://github.com/ahmedtvmer/MAYOS/issues/273), [#274](https://github.com/ahmedtvmer/MAYOS/issues/274), [#314](https://github.com/ahmedtvmer/MAYOS/issues/314))

### 3.9 On-demand player assistant context, memory and injuries

- [ ] [#264](https://github.com/ahmedtvmer/MAYOS/issues/264) Spec: On-demand assistant context via tools, player memory, and injury clearances
- [ ] [#265](https://github.com/ahmedtvmer/MAYOS/issues/265) Measure a TTFT baseline and test tool calls on the provider
- [ ] [#268](https://github.com/ahmedtvmer/MAYOS/issues/268) Preferred name in Settings
- [ ] [#269](https://github.com/ahmedtvmer/MAYOS/issues/269) Tool-calling assistant turn with profile and program tools (after [#265](https://github.com/ahmedtvmer/MAYOS/issues/265), [#266](https://github.com/ahmedtvmer/MAYOS/issues/266))
- [ ] [#270](https://github.com/ahmedtvmer/MAYOS/issues/270) Training read tools and prefetch (after [#269](https://github.com/ahmedtvmer/MAYOS/issues/269))
- [ ] [#271](https://github.com/ahmedtvmer/MAYOS/issues/271) Chat history search tool (after [#269](https://github.com/ahmedtvmer/MAYOS/issues/269))
- [ ] [#272](https://github.com/ahmedtvmer/MAYOS/issues/272) Assistant preferences: remember, forget, and Settings (after [#269](https://github.com/ahmedtvmer/MAYOS/issues/269))
- [ ] [#273](https://github.com/ahmedtvmer/MAYOS/issues/273) Injury records (after [#269](https://github.com/ahmedtvmer/MAYOS/issues/269))
- [ ] [#274](https://github.com/ahmedtvmer/MAYOS/issues/274) Physician follow-up and exercise clearances (after [#273](https://github.com/ahmedtvmer/MAYOS/issues/273))
- [ ] [#275](https://github.com/ahmedtvmer/MAYOS/issues/275) Enforce exercise clearances in substitution and program generation (after [#274](https://github.com/ahmedtvmer/MAYOS/issues/274))
- [ ] [#276](https://github.com/ahmedtvmer/MAYOS/issues/276) Eval and latency gate for on-demand assistant context (after [#270](https://github.com/ahmedtvmer/MAYOS/issues/270), [#271](https://github.com/ahmedtvmer/MAYOS/issues/271), [#272](https://github.com/ahmedtvmer/MAYOS/issues/272), [#275](https://github.com/ahmedtvmer/MAYOS/issues/275))

### 3.10 Coach-grade program generation

- [ ] [#224](https://github.com/ahmedtvmer/MAYOS/issues/224) Spec: coach-grade program generation, exercise names and Volume review
- [ ] [#232](https://github.com/ahmedtvmer/MAYOS/issues/232) Coach-pattern day templates and the coach rubric
- [ ] [#233](https://github.com/ahmedtvmer/MAYOS/issues/233) One-time offer to regenerate with the new design (after [#232](https://github.com/ahmedtvmer/MAYOS/issues/232))
- [ ] [#234](https://github.com/ahmedtvmer/MAYOS/issues/234) Volume review for player-controlled programs (after [#232](https://github.com/ahmedtvmer/MAYOS/issues/232))
- [ ] [#235](https://github.com/ahmedtvmer/MAYOS/issues/235) Volume review for coach-controlled programs (after [#234](https://github.com/ahmedtvmer/MAYOS/issues/234))

### 3.11 Arabic localization (rest)

- [ ] [#246](https://github.com/ahmedtvmer/MAYOS/issues/246) Arabic localization: account language, server messages and shared gym glossary
- [ ] [#252](https://github.com/ahmedtvmer/MAYOS/issues/252) Translate durable assignment and program-request notices (after [#251](https://github.com/ahmedtvmer/MAYOS/issues/251))
- [ ] [#255](https://github.com/ahmedtvmer/MAYOS/issues/255) Log workouts and read new summaries with the Arabic glossary (after [#250](https://github.com/ahmedtvmer/MAYOS/issues/250))
- [ ] [#256](https://github.com/ahmedtvmer/MAYOS/issues/256) Use the shared Arabic glossary in player and coach replies (after [#250](https://github.com/ahmedtvmer/MAYOS/issues/250), [#197](https://github.com/ahmedtvmer/MAYOS/issues/197), [#199](https://github.com/ahmedtvmer/MAYOS/issues/199))
- [ ] [#257](https://github.com/ahmedtvmer/MAYOS/issues/257) Read localized Checkpoint labels without rewriting reviews (after [#251](https://github.com/ahmedtvmer/MAYOS/issues/251))
- [ ] [#258](https://github.com/ahmedtvmer/MAYOS/issues/258) Receive customer emails in the recipient's Display language (after [#250](https://github.com/ahmedtvmer/MAYOS/issues/250))
- [ ] [#259](https://github.com/ahmedtvmer/MAYOS/issues/259) Use recovery and account-deletion web forms in English or Arabic (after [#253](https://github.com/ahmedtvmer/MAYOS/issues/253), [#258](https://github.com/ahmedtvmer/MAYOS/issues/258))

### 3.12 Arabic coach evaluation

- [ ] [#248](https://github.com/ahmedtvmer/MAYOS/issues/248) Arabic coach evaluation: reviewed questions against synthetic facts (after [#245](https://github.com/ahmedtvmer/MAYOS/issues/245))

### 3.13 Cleanup and infrastructure

- [ ] [#46](https://github.com/ahmedtvmer/MAYOS/issues/46) Retire legacy Streamlit UI (after [#44](https://github.com/ahmedtvmer/MAYOS/issues/44))
- [ ] [#132](https://github.com/ahmedtvmer/MAYOS/issues/132) Move MAYOS to an owned domain before public launch (after [#44](https://github.com/ahmedtvmer/MAYOS/issues/44), [#58](https://github.com/ahmedtvmer/MAYOS/issues/58), [#59](https://github.com/ahmedtvmer/MAYOS/issues/59), [#55](https://github.com/ahmedtvmer/MAYOS/issues/55))
- [ ] [#328](https://github.com/ahmedtvmer/MAYOS/issues/328) Spec: Coach redesign: authoring, current program, templates, coach assistants, settings by mode, coaching packages, and Coach Free vs Pro

### 3.14 Public launch gate

- [ ] [#76](https://github.com/ahmedtvmer/MAYOS/issues/76) Verify the public subscription release gate (after [#60](https://github.com/ahmedtvmer/MAYOS/issues/60), [#65](https://github.com/ahmedtvmer/MAYOS/issues/65), [#67](https://github.com/ahmedtvmer/MAYOS/issues/67), [#68](https://github.com/ahmedtvmer/MAYOS/issues/68), [#69](https://github.com/ahmedtvmer/MAYOS/issues/69), [#74](https://github.com/ahmedtvmer/MAYOS/issues/74), [#75](https://github.com/ahmedtvmer/MAYOS/issues/75), [#44](https://github.com/ahmedtvmer/MAYOS/issues/44))

## 4. Not gating either phase (17)

### 4.1 Coaching packages (post-launch epic)

Post-launch, unless trial coaches ask for it sooner.

- [ ] [#316](https://github.com/ahmedtvmer/MAYOS/issues/316) Spec: Coaching packages and subscription periods (post-launch epic)
- [ ] [#317](https://github.com/ahmedtvmer/MAYOS/issues/317) Coaching packages in Coach-mode Settings (after [#291](https://github.com/ahmedtvmer/MAYOS/issues/291))
- [ ] [#318](https://github.com/ahmedtvmer/MAYOS/issues/318) Record a coaching subscription period on an assignment (after [#317](https://github.com/ahmedtvmer/MAYOS/issues/317))
- [ ] [#319](https://github.com/ahmedtvmer/MAYOS/issues/319) Subscription expiry alerts with Renew and Revoke, and roster filters (after [#318](https://github.com/ahmedtvmer/MAYOS/issues/318))
- [ ] [#320](https://github.com/ahmedtvmer/MAYOS/issues/320) Player sees their coaching package and end date under "My coach" (after [#318](https://github.com/ahmedtvmer/MAYOS/issues/318), [#291](https://github.com/ahmedtvmer/MAYOS/issues/291))
- [ ] [#321](https://github.com/ahmedtvmer/MAYOS/issues/321) Optional auto-revoke after a grace period for expired coaching subscriptions (after [#319](https://github.com/ahmedtvmer/MAYOS/issues/319))
- [ ] [#327](https://github.com/ahmedtvmer/MAYOS/issues/327) Attach a coaching package to an assignment invite (after [#317](https://github.com/ahmedtvmer/MAYOS/issues/317), [#318](https://github.com/ahmedtvmer/MAYOS/issues/318))

### 4.2 Parked

You parked this; it has open decisions.

- [ ] [#149](https://github.com/ahmedtvmer/MAYOS/issues/149) Arabic clinical guard (draft, later)

### 4.3 Tech debt: database manager split

It touches the same code as most feature work. Schedule it for a quiet stretch, such as right after the trial gate.

- [ ] [#81](https://github.com/ahmedtvmer/MAYOS/issues/81) Add split guardrails: public-surface snapshot and store-isolation tests
- [ ] [#82](https://github.com/ahmedtvmer/MAYOS/issues/82) Move registry and Training ledger schema into the schema package (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#83](https://github.com/ahmedtvmer/MAYOS/issues/83) Move the Exercise library into its own package (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#84](https://github.com/ahmedtvmer/MAYOS/issues/84) Move registry identity: accounts, plans, recovery, model usage (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#85](https://github.com/ahmedtvmer/MAYOS/issues/85) Move registry coaching: invites, assignments, program requests, alerts, check-ins (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#86](https://github.com/ahmedtvmer/MAYOS/issues/86) Move account deletion into its own module (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#87](https://github.com/ahmedtvmer/MAYOS/issues/87) Move Training ledger program and workouts (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#88](https://github.com/ahmedtvmer/MAYOS/issues/88) Move Training ledger player context (after [#81](https://github.com/ahmedtvmer/MAYOS/issues/81))
- [ ] [#89](https://github.com/ahmedtvmer/MAYOS/issues/89) Finish the database manager facade and update references (after [#82](https://github.com/ahmedtvmer/MAYOS/issues/82), [#83](https://github.com/ahmedtvmer/MAYOS/issues/83), [#84](https://github.com/ahmedtvmer/MAYOS/issues/84), [#85](https://github.com/ahmedtvmer/MAYOS/issues/85), [#86](https://github.com/ahmedtvmer/MAYOS/issues/86), [#87](https://github.com/ahmedtvmer/MAYOS/issues/87), [#88](https://github.com/ahmedtvmer/MAYOS/issues/88))
