# Program design evidence: order, frequency, volume, set counting

Evidence base for issue #712. It sets the numbers MAYOS uses when it builds or checks a Program. Every source in the list at the end was checked against PubMed, the publisher, or the preprint server in November 2026.

How sure we are:

- **Strong**: several meta-analyses agree.
- **Moderate**: one good meta-analysis or a position stand.
- **Practice**: our judgment, built on group averages. No trial has tested the exact number.

Most per-muscle numbers below are **Practice**. The research reports volume for "a muscle" in general and has almost no data on individual muscles such as calves, rear delts or core.

---

## 1. Exercise order (isolation before compound, "pre-exhaust")

**Evidence**

- **Hypertrophy: order makes no measurable difference.** Nunes et al. (2021) pooled 11 trials and found no effect of order on muscle growth (ES 0.03, p = 0.86). The 2026 ACSM position stand reached the same conclusion. Moderate–Strong.
- **Strength: the lift done first gains the most.** In Nunes et al., strength gains were largest in whichever exercise came first in the session. Simão et al. (2012) reviewed the field and concluded the same: put the priority exercise first. In Spineti et al. (2010), bench press strength rose more when bench was done first, and the smaller lifts gained more strength when they were done first. ACSM 2026 also favours doing a strength-priority exercise first. Strong.
- **Pre-exhaust does not make the compound lift work the target muscle harder.** Leg extension before leg press lowered quadriceps EMG and cut leg-press reps (Augustsson et al., 2003). Pec deck before bench press did not raise chest or front-delt activity, though it raised triceps activity (Gentil et al., 2007). So "the compound now hits the tired muscle harder" is not supported.
- **Long-term training: pre-exhaust is neither better nor worse.** Fisher et al. (2014) ran 12 weeks of full-body training and found no difference in strength or body composition between pre-exhaust and compound-first orders.

**Why coaches still use it.** Doing a pullover before a pulldown, or a fly before a press, lets the target muscle reach hard effort before a helper muscle (biceps, grip, triceps) gives out. It also makes the later compound lift lighter, which some joints prefer. Because growth does not depend on order, this is a safe preference for hypertrophy. It is not a growth boost.

**When not to put isolation first**

1. **Before the day's main progressed lift.** This is the lift MAYOS tracks for load progression (see `docs/PROGRESSION_RULES.md`). Fatigue from earlier work lowers its numbers and blurs whether the Player is really progressing.
2. **Beginners still learning a compound lift.** Technique practice needs fresh muscles.
3. **Safety.** Do not tire a muscle that stabilises or holds a heavy free-weight lift that comes next. Examples: no hamstring or lower-back isolation before heavy squats or deadlifts, no triceps isolation before heavy barbell bench without a spotter, no grip or forearm work before heavy pulls.

> **Rule for MAYOS – order**
> - Isolation-first for the same muscle is **allowed and preferred** (owner choice) on any exercise that is *not* the day's main progressed lift.
> - Pre-exhaust block: at most **2 isolation sets** at **RIR 1–3** (no sets to failure) before the compound for that muscle.
> - The day's **main progressed lift** always comes first among the exercises that load the same muscles.
> - **Beginners** (first **8 weeks**, or until the coach marks the technique stable): compound lifts go first.
> - Never pre-fatigue a stabiliser of a heavy free-weight lift that follows it (list above).
> - After pre-exhaust, expect the compound load to be **~5–15% lower**. Do not treat that drop as a regression.
>
> **Plain-language reason:** "Doing the small exercise first wakes up the muscle you want to grow. Your heaviest lift of the day still comes first, so you can keep adding weight to it safely."

---

## 2. Weekly frequency per muscle

**Evidence**

- **Same total sets per week:** training a muscle 1×, 2× or 3× gives about the same growth (Schoenfeld, Grgic & Krieger, 2019, 25 studies). Pelland et al. (2025) analysed 67 studies and found that, once total volume is counted, more frequent training adds little or nothing to growth. ACSM 2026 reports no difference in growth between 1 and more than 5 days per week when volume is equal. Strong.
- **Total sets not equal:** training more often tends to help, mostly because it adds sets. Schoenfeld et al. (2016) found 2×/week beat 1×/week on growth (effect size 0.49 vs 0.30). For strength, Grgic et al. (2018) found effect sizes rising with frequency (0.74 / 0.82 / 0.93 / 1.08 for 1 / 2 / 3 / 4+ days), and the effect disappeared once volume was equated. Pelland et al. found a small independent benefit of frequency on strength (about +3% more strength gain per extra day per week, with diminishing returns).
- **Practical limit:** each session can only usefully hold so many sets (Section 4). Once weekly sets for a muscle go above roughly 10–12, you need more sessions to fit them all at good quality.
- ACSM 2026's main recommendation is **at least 2 sessions per week per major muscle group**.

**Honest framing.** The owner's rule (at least 2×, 3× preferred) is sound practice and matches ACSM. The research does not show 3× grows more muscle than 2× when the sets are the same. The reasons for it are fitting volume in, keeping each session's quality high, and a small benefit for strength.

> **Rule for MAYOS – frequency**
> - Every main muscle trained **≥ 2×/week** (hard floor; a Program that fails it is flagged).
> - **3×/week preferred** when the muscle's weekly target is **> 12 sets**, or when the schedule allows it.
> - Sessions for the same muscle at least **48 h** apart where the week allows (Practice).
> - 1×/week accepted only for **maintenance** or for calves/core when the schedule forces it, and shown as a warning.
>
> **Plain-language reason:** "Spreading a muscle's sets over 2–3 days lets every set be a good one. Your muscle grows from the total work you do across the week."

---

## 3. Weekly hard sets per muscle

**Evidence**

- Growth increases with weekly sets, with diminishing returns. Schoenfeld, Ogborn & Krieger (2017) found ≥10 sets per week beat fewer. Pelland et al. (2025) found a 100% posterior probability of a positive slope for both growth and strength. The curve keeps bending but had not clearly flattened within the range the studies tested. For strength it bends much sooner. Strong.
- Baz-Valle et al. (2022), on trained young men: 12–20 sets per week was the recommended range. Going above 20 helped the triceps only, and not the quads or biceps. Moderate (6 studies).
- ACSM 2026: growth improves from **≥10 sets per muscle per week**, with diminishing returns around **18–20**.
- In a high-volume trial, 30+ sets per week grew more muscle than 6–18 at some sites, with no extra strength (Schoenfeld et al., 2019). That is one small 8-week study in trained men, so we do not set it as a default.
- Beginners grow well on low volume (any structured training works; Currier et al., 2023). Their limit is recovery and soreness, not growth.

The table uses **fractional sets** (Section 5) and **hard sets** (Section 6). Format: *minimum effective / productive range / ceiling*. The ceiling is the point where more sets add little and recovery starts to suffer. Going above it requires a coach override and is limited to blocks of at most 4 weeks. All ranges are Practice, scaled from the group-level evidence above. The studies mostly report a muscle or a broad region, not separate latissimus and trapezius/rhomboid totals. The lats and traps rows are therefore judgment splits of the prior combined upper-pull region, anchored to the group-level dose response; they are not muscle-specific findings.

| Muscle | Beginner | Intermediate | Advanced |
|---|---|---|---|
| Chest | 4 / 6–10 / 12 | 8 / 10–16 / 20 | 10 / 12–20 / 24 |
| Lats (latissimus dorsi) | 4 / 6–10 / 12 | 8 / 10–16 / 20 | 10 / 12–20 / 24 |
| Front delts | 0 / 0–4 / 8 | 0 / 0–6 / 10 | 0 / 0–8 / 12 |
| Side delts | 4 / 6–10 / 12 | 6 / 8–16 / 20 | 8 / 12–20 / 26 |
| Rear delts | 2 / 4–8 / 10 | 4 / 6–12 / 16 | 6 / 8–16 / 20 |
| Traps (upper, mid and lower; incl. rhomboids and mid-back) | 2 / 4–8 / 12 | 4 / 6–12 / 16 | 6 / 8–16 / 20 |
| Quads | 4 / 6–10 / 12 | 8 / 10–16 / 20 | 10 / 12–20 / 24 |
| Hamstrings | 3 / 4–8 / 10 | 6 / 8–14 / 18 | 8 / 10–16 / 20 |
| Glutes | 3 / 4–8 / 12 | 4 / 6–14 / 18 | 6 / 8–16 / 22 |
| Biceps | 3 / 4–8 / 10 | 6 / 8–14 / 18 | 8 / 10–18 / 22 |
| Triceps | 3 / 4–8 / 10 | 6 / 8–14 / 18 | 8 / 10–18 / 22 |
| Calves | 3 / 4–8 / 10 | 6 / 8–12 / 16 | 8 / 10–16 / 20 |
| Core | 2 / 3–6 / 10 | 4 / 6–10 / 14 | 6 / 8–12 / 16 |

Notes. Front delts usually reach their target from presses alone, so no direct work is needed. Traps, glutes and arms get a lot of indirect work, which fractional counting already includes. Experience level comes from the Player's profile: beginner < 1 year of consistent training, intermediate 1–3 years, advanced > 3 years (Practice).

> **Rule for MAYOS – weekly volume**
> - Program builder targets the **middle of the productive range**. Start new Players at the **low end** and add sets only when progress stalls and recovery is good.
> - Weekly sets below the **minimum** → warning. Above the **ceiling** → blocked unless a coach overrides it (blocks of at most 4 weeks).
> - Default progression: add at most **+2 sets per muscle per week**, then a lighter week (Practice).
>
> **Plain-language reason:** "More sets help up to a point. Past that point your body can't recover, so we start lower and add sets only when you're ready."

---

## 4. Maximum useful sets per muscle per session

**Evidence.** Remmert et al. (2025, preprint, not yet peer-reviewed) analysed the same 67 studies by per-session volume. Growth kept rising up to about **11 fractional sets per muscle per session**, and sets beyond that showed no detectable extra benefit. For strength, extra benefit stopped being detectable after about **2 direct sets per exercise/muscle per session**. The authors warn that data at very high per-session volumes are thin. ACSM 2026 recommends 2–3 sets per exercise per session for strength. Moderate–Low.

> **Rule for MAYOS – per session**
> - Hypertrophy cap: **≤ 10 fractional sets per muscle per session** (default target 6–8). Coach override up to **12**.
> - Beginners: **≤ 6** per muscle per session.
> - Main progressed lift: **2–5 working sets**. Strength benefit beyond 3 is small.
> - If a muscle's weekly target ÷ sessions exceeds the cap, the builder **adds a session** for that muscle, or lowers the target.
>
> **Plain-language reason:** "After about 10 hard sets for a muscle in one workout, extra sets mostly add tiredness. Spread them over the week instead."

---

## 5. Counting indirect work (fractional sets)

**Evidence.** Pelland et al. (2025) compared three ways to count a set for a muscle that only helps in an exercise (for example, triceps in bench press): as 1 ("total"), as 0.5 ("fractional"), and as 0 ("direct only"). **Fractional counting predicted both growth and strength best.** In the per-session analysis it fit growth best, and direct-only counting fit strength best (Remmert et al., 2025). Moderate.

The research tested only the values 0, 0.5 and 1. Any other credit value (0.25, 0.75) is **expert judgment**, not evidence. Direct counter-evidence exists for some pairs, so a few credits are set to 0. Squats did **not** grow the hamstrings (Kubo et al., 2019). Hip thrusts and squats grew the glutes by similar amounts, while squats grew the thighs more (Plotkin et al., 2023).

> **Rule for MAYOS – counting**
> - Default: **direct = 1.0, indirect = 0.5, minor helper = 0**.
> - Per-exercise overrides (table below) replace the default.
> - Fractional sets count toward **both** weekly ranges (Section 3) and session caps (Section 4).
> - For **strength** progress checks on the main lift, count **direct sets only**.
>
> **Plain-language reason:** "When a muscle only helps in an exercise, it gets half the credit. That way we don't overwork it or forget to train it."

**Starting credit table** (unlisted muscles = 0; lats = latissimus dorsi; traps includes upper, middle and lower trapezius plus rhomboids and upper/mid-back)

| # | Exercise | Credits |
|---|---|---|
| 1 | Barbell / dumbbell bench press | Chest 1, Triceps 0.5, Front delt 0.5 |
| 2 | Incline press (barbell/dumbbell) | Chest 1, Front delt 0.5, Triceps 0.5 |
| 3 | Machine chest press | Chest 1, Triceps 0.5, Front delt 0.5 |
| 4 | Push-up | Chest 1, Triceps 0.5, Front delt 0.5 |
| 5 | Dips | Chest 1, Triceps 0.5, Front delt 0.5 |
| 6 | Fly (cable/dumbbell/pec deck) | Chest 1 |
| 7 | Overhead press | Front delt 1, Triceps 0.5, Side delt 0.5 |
| 8 | Pull-up / chin-up | Lats 1, Biceps 0.5 |
| 9 | Lat pulldown | Lats 1, Biceps 0.5 |
| 10 | Barbell / cable / dumbbell row | Traps 1, Lats 0.5, Rear delt 0.5, Biceps 0.5 |
| 11 | Chest-supported row | Traps 1, Lats 0.5, Rear delt 0.5, Biceps 0.5 |
| 12 | Pullover (cable/dumbbell) | Lats 1, Triceps 0.25 |
| 13 | Romanian deadlift | Hamstrings 1, Glutes 0.5 |
| 14 | Conventional deadlift | Glutes 1, Hamstrings 0.5, Quads 0.5, Traps 0.5; spinal erectors uncounted |
| 15 | Back / front squat (full depth) | Quads 1, Glutes 0.75, Hamstrings 0 |
| 16 | Leg press | Quads 1, Glutes 0.5 |
| 17 | Lunge / split squat | Quads 1, Glutes 0.75 |
| 18 | Hip thrust / glute bridge | Glutes 1, Hamstrings 0.25 |
| 19 | Leg extension | Quads 1 |
| 20 | Leg curl | Hamstrings 1 |
| 21 | Lateral raise | Side delt 1, Traps 0.25 |
| 22 | **Y raise** | **Shoulders 1, Traps 0.75** (owner input; plausible range 0.5–1, approximate) |
| 23 | Face pull | Rear delt 1, Traps 0.5 |
| 24 | Reverse fly / rear-delt machine | Rear delt 1, Traps 0.5 |
| 25 | Shrug | Traps 1 |
| 26 | Biceps curl (any) | Biceps 1 |
| 27 | Triceps pushdown / extension | Triceps 1 |
| 28 | Calf raise (standing/seated) | Calves 1 |
| 29 | Plank / crunch / hanging leg raise | Core 1 |

Rows with a specific lats or traps target use the owner-directed row rule: traps 1, lats 0.5, rear delts 0.5, and biceps 0.5. The traps-first assignment is a movement-pattern judgment, not a muscle-specific trial result; the fractional helper value follows the indirect-set evidence above (Pelland et al., 2025). Face pulls and reverse flies credit the scapular retractors as traps; neither gets lats credit because neither is a shoulder-extension/adduction pull. The deadlift's removed broad-region credit represented spinal-erector work, which remains unlisted. Coaches may edit these credits per exercise. Each override is stored with the exercise, not with the Player.

---

## 6. Rep range and effort: what counts as a "hard set"

**Evidence**

- Hypertrophy is similar across a wide range of loads and reps when sets are hard enough (Currier et al., 2023: all prescriptions grew muscle comparably). Heavier loads (> 80% 1RM) gain the most strength.
- Growth improves as sets get closer to failure. Strength changes little across a wide range of reps in reserve (Robinson et al., 2024, exploratory). Training all the way to failure added nothing meaningful versus stopping short (Refalo et al., 2023; ACSM 2026). ACSM 2026 suggests stopping about **2–3 reps in reserve** and says the evidence is too thin to set exact targets.
- Reps-in-reserve self-ratings are less accurate far from failure and for less experienced lifters (Helms et al., 2016).

> **Rule for MAYOS – hard set**
> - A **hard set** = a working set of **5–30 reps** finished at **RIR ≤ 4** (target RIR 1–3).
> - Sets at **RIR ≥ 5**, warm-ups, and technique sets count **0**.
> - Failure (RIR 0) allowed on the last set of isolation exercises. Not allowed on the main progressed lift.
> - Beginners: if a logged RIR looks unreliable (for example, reps jump a lot from week to week), the app shows a short guide and still counts the set.
>
> **Plain-language reason:** "A set counts when you finish it with only 1 to 3 more reps left in you. You don't need to go to total failure to grow."

---

## 7. Summary of MAYOS rules

| Area | Rule | Evidence |
|---|---|---|
| Order | Isolation-first allowed/preferred, ≤ 2 sets at RIR 1–3, except before the day's main progressed lift, for beginners (first 8 weeks), or before heavy lifts it stabilises | Hypertrophy: Strong (no effect). Strength-first: Strong |
| Order | Main progressed lift is first among exercises for the same muscles | Strong |
| Frequency | ≥ 2×/week per main muscle (floor); 3× preferred when weekly target > 12 sets | Moderate (ACSM); 3× > 2× not shown |
| Weekly volume | Intermediate typical 10–16/20 sets; ceiling 18–22; beginner ceiling 10–14; advanced ceiling 20–26 (see table) | Strong for the trend, Practice for the exact numbers |
| Volume progression | +2 sets/muscle/week max; start low | Practice |
| Per session | ≤ 10 fractional sets/muscle (override 12); beginners ≤ 6; main lift 2–5 sets | Moderate–Low (preprint) |
| Counting | Direct 1, indirect 0.5, minor 0; per-exercise overrides; Y raise = shoulders 1, traps 0.75 | Moderate (0/0.5/1); Judgment (other values) |
| Strength checks | Count direct sets only | Moderate |
| Hard set | 5–30 reps, RIR ≤ 4 (target 1–3); RIR ≥ 5 = 0 | Moderate |
| Failure | Not needed; allowed on last isolation set only | Moderate |

---

## Sources

1. Pelland JC, Remmert JF, Robinson ZP, Hinson SR, Zourdos MC. The resistance training dose response: meta-regressions exploring the effects of weekly volume and frequency on muscle hypertrophy and strength gains. *Sports Med.* 2025 (online 4 Dec 2025). doi:10.1007/s40279-025-02344-w. Preprint: doi:10.51224/SRXIV.460
2. Remmert JF, Pelland JC, Robinson ZP, Hinson SR, Zourdos MC. Is there too much of a good thing? Meta-regressions of the effect of per-session volume on hypertrophy and strength. *SportRxiv* preprint, 2025. doi:10.51224/SRXIV.537 (not peer-reviewed)
3. Currier BS, D'Souza AC, Fiatarone Singh MA, et al., Phillips SM. ACSM Position Stand: Resistance training prescription for muscle function, hypertrophy, and physical performance in healthy adults: an overview of reviews. *Med Sci Sports Exerc.* 2026;58(4):851–872. doi:10.1249/MSS.0000000000003897
4. Currier BS, et al. Resistance training prescription for muscle strength and hypertrophy in healthy adults: a systematic review and Bayesian network meta-analysis. *Br J Sports Med.* 2023;57(18):1211–1220. doi:10.1136/bjsports-2023-106807
5. American College of Sports Medicine. Position stand: Progression models in resistance training for healthy adults. *Med Sci Sports Exerc.* 2009;41(3):687–708. doi:10.1249/MSS.0b013e3181915670 (superseded by #3)
6. Schoenfeld BJ, Ogborn D, Krieger JW. Dose-response relationship between weekly resistance training volume and increases in muscle mass: a systematic review and meta-analysis. *J Sports Sci.* 2017;35(11):1073–1082. doi:10.1080/02640414.2016.1210197
7. Baz-Valle E, Balsalobre-Fernández C, Alix-Fages C, Santos-Concejero J. A systematic review of the effects of different resistance training volumes on muscle hypertrophy. *J Hum Kinet.* 2022;81:199–210. doi:10.2478/hukin-2022-0017
8. Schoenfeld BJ, Contreras B, Krieger J, et al. Resistance training volume enhances muscle hypertrophy but not strength in trained men. *Med Sci Sports Exerc.* 2019;51(1):94–103. doi:10.1249/MSS.0000000000001764
9. Schoenfeld BJ, Ogborn D, Krieger JW. Effects of resistance training frequency on measures of muscle hypertrophy: a systematic review and meta-analysis. *Sports Med.* 2016;46(11):1689–1697. doi:10.1007/s40279-016-0543-8
10. Schoenfeld BJ, Grgic J, Krieger J. How many times per week should a muscle be trained to maximize muscle hypertrophy? A systematic review and meta-analysis. *J Sports Sci.* 2019;37(11):1286–1295.
11. Grgic J, Schoenfeld BJ, et al., Pedisic Z. Effect of resistance training frequency on gains in muscular strength: a systematic review and meta-analysis. *Sports Med.* 2018;48(5):1207–1220. PMID 29470825
12. Nunes JP, Grgic J, Cunha PM, et al., Cyrino ES. What influence does resistance exercise order have on muscular strength gains and muscle hypertrophy? A systematic review and meta-analysis. *Eur J Sport Sci.* 2021;21(2):149–157. PMID 32077380
13. Simão R, de Salles BF, Figueiredo T, Dias I, Willardson JM. Exercise order in resistance training. *Sports Med.* 2012;42(3):251–265. doi:10.2165/11597240-000000000-00000
14. Spineti J, de Salles BF, Rhea MR, et al., Simão R. Influence of exercise order on maximum strength and muscle volume in nonlinear periodized resistance training. *J Strength Cond Res.* 2010;24(11):2962–2969. PMID 20938358
15. Augustsson J, et al. Effect of pre-exhaustion exercise on lower-extremity muscle activation during a leg press exercise. *J Strength Cond Res.* 2003;17(2):411–416.
16. Gentil P, et al. Effects of exercise order on upper-body muscle activation and exercise performance. *J Strength Cond Res.* 2007;21(4):1082–1086. PMID 18076251
17. Fisher JP, Carlson L, Steele J, Smith D. The effects of pre-exhaustion, exercise order, and rest intervals in a full-body resistance training intervention. *Appl Physiol Nutr Metab.* 2014;39(11):1265–1270. doi:10.1139/apnm-2014-0162
18. Kubo K, Ikebukuro T, Yata H. Effects of squat training with different depths on lower limb muscle volumes. *Eur J Appl Physiol.* 2019;119:1933–1942. doi:10.1007/s00421-019-04181-y
19. Plotkin DL, et al. Hip thrust and back squat training elicit similar gluteus muscle hypertrophy and transfer similarly to the deadlift. *Front Physiol.* 2023;14:1279170. doi:10.3389/fphys.2023.1279170
20. Refalo MC, et al. Influence of resistance training proximity-to-failure on skeletal muscle hypertrophy: a systematic review with meta-analysis. *Sports Med.* 2023;53:649–665. doi:10.1007/s40279-022-01784-y
21. Robinson ZP, Pelland JC, Remmert JF, et al., Zourdos MC. Exploring the dose–response relationship between estimated resistance training proximity to failure, strength gain, and muscle hypertrophy: a series of meta-regressions. *Sports Med.* 2024. doi:10.1007/s40279-024-02069-2
22. Helms ER, Cronin J, Storey A, Zourdos MC. Application of the repetitions in reserve-based rating of perceived exertion scale for resistance training. *Strength Cond J.* 2016;38(4):42–49. doi:10.1519/SSC.0000000000000218
