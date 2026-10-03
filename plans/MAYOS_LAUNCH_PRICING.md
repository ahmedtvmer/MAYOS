# MAYOS Launch Pricing Plan

**Status:** Public-launch subscription design; no trial billing  
**Pricing review milestone:** 10,000 active accounts  
**Currency:** EGP  
**Billing:** Monthly

All displayed EGP prices are final customer totals, inclusive of any
applicable taxes and mandatory charges. Confirm the seller's tax treatment and
web checkout configuration before public sale. This follows Egypt's
[consumer price-disclosure rules](https://elec.eecourts.gov.eg/assets/laws/16%20-%20%D9%82%D8%A7%D9%86%D9%88%D9%86%20%D8%AD%D9%85%D8%A7%D9%8A%D8%A9%20%D8%A7%D9%84%D9%85%D8%B3%D8%AA%D9%87%D9%84%D9%83.pdf).

Public subscriptions begin at launch, after the free closed trial. Lifter Pro
launches at 199 EGP/month and Coach Pro at 399 EGP/month. Free plans remain
available, and Coach Free has a five-active-player cap. Coach Pro permits 30
active players. The 5/30 daily AI limits are starting proposals to refine
from measured usage and costs. The listed Pro benefits are required at public
launch; the entire launch waits if one is missing. Subscription billing and
entitlements still require implementation.

## 1. Public-Launch Pricing

| Plan | Price |
|---|---:|
| Lifter Free | 0 EGP |
| Lifter Pro | **199 EGP/month** |
| Coach Free | 0 EGP |
| Coach Pro | **399 EGP/month** |

Only coaches who join during the free closed trial qualify for the
founding-coach offer. Their two free Coach Pro months start automatically at
public launch without collecting payment details. Afterward, Coach Pro costs
**299 EGP/month** while they remain continuously subscribed. A lapsed
subscription or cancellation of renewal ends the founder rate immediately.
The coach must opt into web checkout before all earned free months end; there
is no automatic charge and no late signup window. The founder rate
remains 299 EGP/month even if the standard Coach Pro price later changes.
Trial referrals qualify only when the referred coach joined during the trial and
makes a first successful subscription payment after billing begins; each
qualifying referral earns one extra free month, capped at two, only while the
referring founder's Coach Pro plan remains active and renewal is not cancelled.
Self-referrals do not qualify. A refunded qualifying payment removes any
unused reward credit; an already-used free month is not billed back to the
founder.

Reaching 10,000 active accounts triggers a **pricing review**, not an automatic
increase. Count unique accounts that completed a workout or recorded a
coaching action in the previous 30 days. Review contribution margin earlier;
adjust internal limits or costs promptly if it turns negative.

A future **Studio** tier may be introduced for multi-coach businesses if real customer segmentation justifies it.

## 2. Lifter Free

A complete basic training experience, not a temporary trial.

- Workout programming and execution
- Full workout logging and training history
- Core progression functionality
- **5 AI requests/day**
- AI primarily uses recent and immediately relevant training data

## 3. Lifter Pro — 199 EGP/month

Everything in Free, plus deeper intelligence and substantially higher AI usage.

- Trends from persisted training history, including progression and volume
- Recommendations grounded in those trends and the active program
- Assistant answers that can draw on a longer relevant training-history window
  than Free
- **30 AI requests/day**

## 4. Coach Free

A genuinely usable plan for a small coach.

- Maximum **5 active players**
- Full program authoring: the program editor, spreadsheet import, Coach
  exercises, set groups (top set plus back-off sets, AMRAP), week-by-week
  programs, Program templates, and viewing, editing or approving a player's
  current program
- Full player workout logs
- Basic progress visibility
- The deterministic Roster urgency order (lapsing first)
- Essential coach alerts: missed-day streak, follow-up due, Stalling (stall
  alert), suggested deload, injury and clearance changes, and coaching
  subscription expiry. Deload alerts stay on Free because a coached player's
  deload is only suggested to the coach (ADR 055).
- Coaching packages and subscription tracking (post-launch epic)
- The one-player coach assistant within the Coach AI allowance
- **5 AI requests/day** (Coach pool)

If a coach exceeds five active players when Pro expires or a payment fails,
allow a 14-day grace period. After it ends, the coach's access is read-only
while the roster remains above five, except that coach and player can still
end assignments. Publishing programs, responding to requests, recording
check-ins, and issuing invitations resume when the coach restores Pro or
reduces the active roster to five. While read-only, the coach may still edit
(but not publish) Program drafts and Program templates, record, renew or
revoke coaching subscriptions, and use the one-player assistant within the
Free allowance. Preserve each player's program and training history; do not
end assignments automatically.

## 5. Coach Pro — 399 EGP/month

The professional coaching tier.

- Everything in Coach Free
- Up to **30 active players**
- Existing assignments above 30 remain active when this cap first applies;
  new invitations and assignments stop until the roster is at or below 30
- Deeper alerts grounded in recorded training and schedule data: regression
  on an exercise, Volume review per muscle, and effort rising at the same load
- Stall length as a key in the Roster urgency order
- The roster assistant: free-form questions across the roster ("who needs
  me today?", "who stalled this month?") answered over deterministic,
  de-identified signals for every eligible assigned player, bounded by a token
  budget, after a recorded privacy and evaluation gate. Accepting an
  assignment is the player's consent; players assigned earlier are included
  after a one-time notice.
- AI-proposed program changes for coach review; an accepted proposal opens as
  a Program draft and is published by the coach
- **30 AI requests/day** (Coach pool)

Nutrition features remain outside the public-launch scope. Coach business
management is limited to tracking coaching packages and subscription periods
(no payment processing), delivered as a post-launch epic on both Coach plans.

Internal fair-use/resource safeguards still apply.

### Coach AI allowance

One Coach pool per account covers the one-player assistant, the roster
assistant, "Generate draft" and AI program proposals: one request per completed
answer or generated draft. Writing a program by hand, importing a spreadsheet
and publishing never consume a request.

### Closed trial

During the closed trial every coach receives Coach Pro behaviour under the
trial's own AI limits. Free and Pro differences apply from public launch;
founding coaches then start with two free Coach Pro months.

## 6. AI Context Policy

Choose customer-facing daily request limits from measured usage and model
cost before public sale; 5 Free and 30 Pro are starting proposals. Internal
token and conversation budgets live in [MAYOS_AI_BUDGETS.md](MAYOS_AI_BUDGETS.md)
and require evaluation before use.
An account with both capabilities receives separate Lifter and Coach request
pools; requests for one capability do not consume the other's allowance. Daily
pools reset at midnight UTC, and the next reset time is shown in the app. Count
completed assistant answers; provider errors, interrupted streams and
provider-reported output-token truncation do not consume a daily allowance.
Add durable per-account rate limits to protect model spending.

English and Arabic receive the same request-count ceiling for the same plan
and capability. Separate Lifter and Coach daily resource budgets count actual
token usage without language normalization and may stop requests before that
ceiling is reached. Exhausting one capability's resource budget does not block
the other. Size those budgets from measured usage before sale; tokens from
output-truncated answers still count toward resource usage and cost.

Disclose this safeguard beside the plan's request allowance, explaining
upfront that longer conversations and Arabic replies may use more resources.
Show a persistent assistant warning at 80% of the capability's resource budget.
At cutoff, explain that the daily resource limit was reached and show remaining
requests and reset time. These structured messages follow Display language.
See ADR 059 and the [accepted Arabic allowance policy](../docs/design-review/arabic-model-and-allowance-policy.md).

MAYOS should retrieve only relevant context rather than filling the maximum budget:

```text
System instructions
+ compact player/user profile
+ conversation summary
+ recent relevant turns
+ retrieved program/training evidence
+ deterministic metrics and alerts
= model input
```

Older conversations should be summarized rather than continuously resent.

For coach queries across many players, MAYOS should not dump raw roster histories into the model. The deterministic domain layer should calculate relevant metrics, trends, adherence, progression, volume, and alarms first. Retrieval then supplies only the evidence needed by the model.
The roster briefing does not retain a multi-player chat transcript; the
single-player coach assistant remains scoped to one selected player. A player
who declines cross-player model processing remains visible through authorized
records and deterministic alerts but is excluded from model input.

## 7. Coach–Player Subscription Rules

Coach and lifter subscriptions are independent.

**Coach Pro does not automatically grant Lifter Pro to the coach's players.**

A coached Lifter Free player still receives:

- Coach-assigned programs
- Program updates
- Workout logging/history
- Coach monitoring
- Coach-driven changes resulting from MAYOS analysis

Lifter Pro pays for the player's own premium capabilities, especially deeper personal analysis and higher AI usage.

The fundamental coach–player workflow must never require the player to purchase Pro.

## 8. Proposed Upgrade Philosophy

Free → Pro should be differentiated primarily by **capacity, intelligence depth, automation, and advanced capabilities**, not by crippling fundamental workflows.

**Lifter:** Free stores and organizes training; Pro understands and acts on it more deeply.

**Coach:** Free lets a small coach operate on MAYOS; Pro supports growth beyond five players and unlocks deeper automation, analysis, and AI assistance.

## 9. Subscription Principles

1. Keep launch pricing highly competitive.
2. Free plans must provide real standalone value.
3. Pro plans must provide a clear, material upgrade.
4. Keep customer-facing AI limits simple.
5. Internally meter requests, input/output tokens, context size, and inference cost per account.
6. MAYOS recommends and explains; the coach approves, modifies, or rejects coaching decisions.
7. Review pricing at **10,000 active accounts** using actual conversion, churn,
   AI cost, infrastructure cost, support burden, and willingness-to-pay data.
8. Preserve the agreed 299 EGP founding rate while a qualifying coach remains
   continuously subscribed; lapse ends that rate.

## 10. Launch Tier Summary

| | Lifter Free | Lifter Pro | Coach Free | Coach Pro |
|---|---:|---:|---:|---:|
| Price/month | 0 EGP | **199 EGP** | 0 EGP | **399 EGP** |
| AI requests/day | **5** | **30** | **5** | **30** |
| Active players | — | — | **5** | **30** |
| Automated alarms | — | — | Essential | Full |
| Roster assistant | — | — | — | ✅ |
| Program authoring and templates | — | — | ✅ | ✅ |
| Advanced analysis | Limited | Full | Limited | Full |

> Daily AI request counts are starting proposals until measured costs and
> quality support final limits. Prices, roster caps, and listed benefits are
> public-launch decisions.
