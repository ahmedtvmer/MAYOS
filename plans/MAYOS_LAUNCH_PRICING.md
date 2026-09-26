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
- Program creation, editing, and assignment
- Full player workout logs
- Basic progress visibility
- **5 AI requests/day**
- Automated alarms available with limited depth/scope
- Essential signals remain available, including major adherence issues, missed training, and clear progression problems

If a coach exceeds five active players when Pro expires or a payment fails,
allow a 14-day grace period. After it ends, the coach's access is read-only
while the roster remains above five, except that coach and player can still
end assignments. Publishing programs, responding to requests, recording
check-ins, and issuing invitations resume when the coach restores Pro or
reduces the active roster to five. Preserve each player's program and training
history; do not end assignments automatically.

## 5. Coach Pro — 399 EGP/month

The professional coaching tier.

- Everything in Coach Free
- Up to **30 active players**
- Existing assignments above 30 remain active when this cap first applies;
  new invitations and assignments stop until the roster is at or below 30
- Deeper adherence, progression, fatigue, and volume alerts grounded in
  recorded training and schedule data
- Ranked roster view showing which assigned players need attention
- An on-demand roster briefing that deterministically ranks eligible assigned
  players, then uses de-identified evidence for at most five consenting players
  in one model request after a separate privacy and quality gate
- Player-scoped analysis and candidate program changes for coach review and
  publication
- **30 AI requests/day**

Business-management and nutrition features remain outside the public-launch
scope and are not included in this entitlement.

Internal fair-use/resource safeguards still apply.

## 6. AI Context Policy

Choose customer-facing daily request limits from measured usage and model
cost before public sale; 5 Free and 30 Pro are starting proposals. Internal
token and conversation budgets live in [MAYOS_AI_BUDGETS.md](MAYOS_AI_BUDGETS.md)
and require evaluation before use.
An account with both capabilities receives separate Lifter and Coach request
pools; requests for one capability do not consume the other's allowance. Daily
pools reset at midnight UTC, and the next reset time is shown in the app. Count
completed assistant answers; provider errors and interrupted streams do not
consume a daily allowance. Add durable per-account rate limits to protect
model spending.

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
| Automated alarms | — | — | Limited | Full |
| Advanced analysis | Limited | Full | Limited | Full |

> Daily AI request counts are starting proposals until measured costs and
> quality support final limits. Prices, roster caps, and listed benefits are
> public-launch decisions.
