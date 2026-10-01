# MAYOS #143 Arabic typography review

**Owner selection: IBM Plex Sans Arabic throughout the Arabic version of the
app**, including headings, body text and controls. The English version keeps
its existing Playfair Display / Inter fonts. Both versions use Western digits `0–9`.
This selection supersedes both original pairings and the agent's recommendation
of B. The selected Arabic font has not yet been implemented or captured.

The historical disposable comparison below renders the actual current Flutter Home, Workout logger and Assistant
chat through `MayosApp`, using the existing `test/visual/capture_test.dart`
FontLoader / synthetic API / RepaintBoundary capture pattern. Screens were not
recreated, redrawn or edited as raster images. Contact sheets only resize and
arrange the unchanged PNG captures.

[Approved scope](../arabic-language-review.md) ·
[Home comparison](comparison-home.png) ·
[Logger comparison](comparison-logger.png) ·
[Chat comparison](comparison-chat.png) ·
[Logger keypad / RIR / swipe inspection](comparison-logger-stress.png)

| Candidate | Arabic display | Arabic body / controls |
| --- | --- | --- |
| A | Amiri | IBM Plex Sans Arabic |
| B | Reem Kufi | Cairo |

In these historical captures, English glyphs retain Playfair Display / Inter; Western numeric glyphs use Inter,
and the Latin MAYOS brand retains its existing mark and wordmark. Arabic roles
use explicit candidate fallback families, line-height 1.5 and zero tracking.
Amiri is static Regular/Bold; IBM Plex is static Regular/Medium/SemiBold/Bold.
Reem Kufi and Cairo are variable fonts. FontLoader loads every candidate face,
Playfair Display, Inter and MaterialIcons before rendering. Font choice changes
actual Arabic glyph shapes and wrapping; it is not an image filter.

## Fixtures and captures

There are **56 screen PNGs and 4 comparison sheets**. Both candidates use the
same fixture, text, fixed logger clock, interactions and view sizes. Phone
canvases are 360×640 and 412×915 logical pixels, captured at 2x (720×1280 and
824×1830 PNGs), with light and dark themes and text scale 1.0. These are widget
captures, without OS status/navigation chrome or a simulated hardware keyboard.

The synthetic account uses a versioned two-exercise program: Wide-Grip Lat
Pulldown and Bench Press, each with 3 sets of 10 and target RIR ≥ 2. The existing
fake prescription projects 60 kg. The capture types 27.5 into the first weight
cell through the real keypad. Home includes weighted weekly sets (21.5, 12.5,
9) and the fake's existing personal record (120 kg × 5). These figures are
fixtures, not real training records or coaching recommendations. Chat contains
Egyptian input, an English question, simple standard Arabic replies, a Markdown
heading/quote, 3 × 10, 27.5 kg, RIR 2 and 02:00. No hosted model is called.

Home-detail scrolls to volume and personal records. Logger-keypad shows the
edited cell with the keypad open, after a scroll to that cell. The initial
keypad captures preserve the logger's settled automatic reveal at 360×640.
RIR and held swipe-delete captures are provided at 412×915 dark. The stress
sheet's empty cells reflect this bounded capture matrix. Chat-detail performs a
scroll gesture; where the conversation fits, it resembles the main capture.

## RTL corrections and findings

All corrections are confined to the disposable source and are visible in
[prototype.patch](prototype.patch). No domain rules, program authority checks,
set persistence, chat routes, action execution or workout commits were changed.

| Area | Prototype correction / observed result |
| --- | --- |
| App direction | Directionality below MaterialApp mirrors semantic rows and navigation for the two Arabic builds. The default build remains English. |
| Chat bubbles | Replace fixed right/left with directional end/start. In RTL the player is on the left and assistant on the right. Each message chooses its paragraph direction from its first ASCII/basic Arabic letter; English punctuation stays at the English sentence end. Streaming text uses the same rule. |
| Markdown quote | BorderDirectional.start puts the quote rule on the right for Arabic, left for English. |
| Exercise titles | Directional start alignment places English exercise titles at the right edge of RTL cards while preserving the exercise names. Long Arabic day headings wrap naturally. |
| Swipe-delete | Directional end alignment/padding makes the delete background appear on the left during the existing end-to-start swipe (a rightward swipe in RTL). The held gesture captures verify this. |
| Keypad / RIR | Semantic table columns mirror; values explicitly remain LTR, including ≥ 2. The whole keypad body stays LTR: 1 2 3 / 4 5 6 / 7 8 9 / . 0 backspace; RIR is 0 1 2 3 4 5+. Positions are checked during capture. |
| Numbers / mixed text | Western digits only. Numeric/English phrases use LTR isolates; weights and units use nonbreaking spaces. Caption translation wraps the existing computed values, rather than recomputing training facts. |
| Home bars / header | Volume fills start at the RTL start edge; header insets are directional. The brand mark/wordmark pair stays LTR. |
| Rail border | BorderDirectional.end replaces the fixed right border. Desktop was not captured, so this is a source correction, not a desktop visual sign-off. |

**Owner review points and limits:**

- Amiri's long logger title fits one line at 412×915; Reem Kufi wraps it to two.
  Both wrap at 360×640. This changes how many set rows are visible and is part of
  the comparison. No label was ellipsized and no layout exception occurred in
  the final captures; content partly outside a scroll viewport is ordinary
  scrolling, not a clipped label.
- An earlier apparent hidden keypad row was capture timing: the logger's
  automatic scroll had not settled. Finite animation pumps resolve it; the
  initial captures show the edited row above the keypad. No logger focus/reveal
  behavior was changed.
- Mixed-language chat still needs owner inspection: at 360px the long English
  exercise name can wrap across Arabic lines. We preserve that natural wrap;
  there is no general rich-span/bidi solution for arbitrary future messages.
- Chat fixture strings deliberately contain bidi isolates and nonbreaking
  spaces. This demonstrates a presentation requirement; it does **not** prove
  that arbitrary API or model output is already normalized. The paragraph
  heuristic covers this review's English/basic Arabic text, not all Unicode.
- Arabic capture text is scoped to these views. Other screens, error states,
  dialogs, accessibility scales, account Display language, OS keyboards,
  desktop layouts and full #135 localization are not approved by this bundle.
- The synthetic program initially lacked a version and displayed the real
  logger's unavailable-program warning. The fixture now uses version 1; no
  guard was bypassed. Some existing English prescription conventions, including
  `10–10`, are retained from the actual widgets.

## Gates and evidence

All Flutter commands used the unsnapped SDK at
`/mnt/work/MAYOS/.pytest_cwd/flutter_sdk/bin/flutter`, working in
`/tmp/mayos-arabic-143-prototype/mobile`.

| Command / gate | Outcome | Evidence |
| --- | --- | --- |
| `flutter pub get` | Pass; dependency resolution completed | [pub-get.log](logs/pub-get.log) |
| `flutter analyze` | Pass; no issues | [analyze.log](logs/analyze.log) |
| Candidate A capture command below | 8 tests passed; 28 PNGs | [capture-A.log](logs/capture-A.log) |
| Candidate B capture command below | 8 tests passed; 28 PNGs | [capture-B.log](logs/capture-B.log) |
| Eight relevant existing widget test files below | 125 passed | [widget-tests.log](logs/widget-tests.log) |
| `flutter test --no-pub --exclude-tags capture --reporter expanded` | Incomplete: last reported 649 passed, 2 failed; process exited 143 before a suite summary | [full-tests-incomplete.log](logs/full-tests-incomplete.log) |
| Supplied baseline: `flutter test --no-pub --reporter expanded test/program_authority_test.dart test/design_review_54_test.dart` | 58 passed, the same 2 failed | [baseline-tests.log](logs/baseline-tests.log) |
| Exact font hashes, names, fixture glyph coverage and digit scan | Pass | [font-numeric-verification.log](logs/font-numeric-verification.log) |
| Patch applied to an untouched supplied snapshot | All 34 changed/new files byte-match, including binary fonts and original license endings | [patch-verification.log](logs/patch-verification.log) |
| Real working-tree preservation | 301 preexisting files hash-identical | [preservation-verification.json](preservation-verification.json) |

The capture harness checks layout exceptions, Western digits in UI
text/fixtures, conventional keypad and RIR positions, and that typing yields
27.5. All individual screen dimensions were checked. The comparison sheets
and representative phone captures were visually inspected for clipping;
ellipsis is not checked automatically by this harness.

The two baseline failures are:

1. `program_authority_test.dart`: **older intake contract shows a service update
   error instead of hanging** hits `Bad state: No element` in the unchanged
   `profile_screen.dart:154`, followed by the spinner assertion. The supplied
   snapshot contains the owner's preexisting dirty test changes.
2. `design_review_54_test.dart`: **docs/design-review/54/README.md links all
   resolve** reports `review artifact missing`, because the disposable mobile
   snapshot does not include the original repo's adjacent #54 docs.

Neither failure was fixed, skipped or weakened. The relevant 125-test gate
includes home, logger behavior, logger back/menu/pictures, chat, markdown and
shell tests and passes. The full-suite attempt is explicitly not a green gate.

The orchestrator independently reran analysis, the 125 focused widget tests,
both 8-test capture runs, and font/digit verification. All 56 regenerated PNGs
byte-match the published captures. See
[orchestrator-verification.json](orchestrator-verification.json).

Guard review: clean-code-guard removed two redundant line-height conditionals
and narrowed the message-direction scan to actual review-language letters.
`clean-code-guard: 3 fixed, 0 flagged for author`. `test-guard: clean` (one
parameterized artifact harness, synthetic network/storage seams; no redundant
unit-test suite). `docs-guard: clean` after checking flags, files and links.

## Reproduction bundle and commands

[prototype-source.tar.gz](prototype-source.tar.gz) contains all **288** supplied
and prototype mobile source/assets files, including all fonts/licenses and the
preexisting dirty tests. It excludes build, .dart_tool, .git, credentials, local
properties, generated plugin metadata and the temporary verification copies.
The archive alone is sufficient to regenerate the captures. The supplied
snapshot is additionally identified by [supplied-snapshot-sha256.json](supplied-snapshot-sha256.json).
[prototype.patch](prototype.patch) is a binary-capable patch of every prototype
modification and new source/asset against that supplied snapshot;
[source-changes.json](source-changes.json) lists the 34 entries with hashes.
Do not apply this prototype patch to the real production working tree.

Recorded runtime: Flutter **3.47.5**, framework **6a19cca564**, Dart **3.13.4**;
[full SDK versions](logs/flutter-version.log). Python tools use the versions in
`mobile/tool/prototype143/requirements.txt` (Pillow and fonttools). Captures do not
need the Python packages; they are for contact sheets and asset verification.

From the current disposable source:

```bash
cd /tmp/mayos-arabic-143-prototype/mobile
FLUTTER143=/mnt/work/MAYOS/.pytest_cwd/flutter_sdk/bin/flutter
"$FLUTTER143" pub get
"$FLUTTER143" analyze
CAPTURE=1 CAPTURE_OUT=/mnt/work/MAYOS/docs/design-review/143/screens \
  "$FLUTTER143" test --no-pub --dart-define=ARABIC_PAIR=A --tags capture \
  test/visual/arabic_143_capture_test.dart --reporter expanded
CAPTURE=1 CAPTURE_OUT=/mnt/work/MAYOS/docs/design-review/143/screens \
  "$FLUTTER143" test --no-pub --dart-define=ARABIC_PAIR=B --tags capture \
  test/visual/arabic_143_capture_test.dart --reporter expanded
"$FLUTTER143" test --no-pub --reporter expanded \
  test/home_screen_test.dart test/workout_logger_screen_test.dart \
  test/workout_logger_back_test.dart test/workout_logger_card_menu_test.dart \
  test/workout_logger_pictures_test.dart test/player_chat_test.dart \
  test/theme_and_shell_test.dart test/mayos_markdown_test.dart
python3 tool/prototype143/verify_assets.py
python3 tool/prototype143/contact_sheets.py
```

For a portable fresh reproduction, extract `prototype-source.tar.gz` into an
empty disposable directory and `cd mobile`. Set `FLUTTER143` to an unsnapped
Flutter 3.47.5 executable, run pub get/analyze and the two capture commands
above, replacing `CAPTURE_OUT` with an absolute path to `reproduced/screens`
in your disposable directory. Set the same `CAPTURE_OUT` for
`contact_sheets.py`; it writes sheets in `reproduced/`. Install Python tooling
with `python3 -m pip install -r tool/prototype143/requirements.txt` in a virtual
environment. The sheet script uses DejaVuSans from
`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` for its English annotations.

Fonts are already bundled. Optional `python3 tool/prototype143/download_fonts.py`
fetches the pinned upstream bytes again and rebuilds their provenance manifest.
Packaging can be repeated with `BASELINE_MOBILE` pointing at the untouched
supplied mobile snapshot and `REVIEW_OUT` pointing at your review directory,
then `python3 tool/prototype143/package_review.py`; this packages source and
copies this session's `/tmp/143-*.log` evidence, so it is a session packaging
helper rather than a prerequisite for capture reproduction.

## Font provenance and licenses

[font-provenance.json](font-provenance.json) records each candidate font/license's exact
raw URL, repository, commit, upstream path, byte length and SHA-256. Original
OFL license files are retained byte-for-byte in the source archive.

| Source | Pinned commit | Font version |
| --- | --- | --- |
| [aliftype/amiri](https://github.com/aliftype/amiri) | `6331fc82b0d20d9439a0792e21a9294ca015a93f` | Amiri 1.003 |
| [IBM/plex](https://github.com/IBM/plex) | `763c36ef9117782905ae010056dfbe8fd2653a25` | IBM Plex Sans Arabic 1.005 |
| [google/fonts Reem Kufi](https://github.com/google/fonts/tree/main/ofl/reemkufi) | `9710da1eacb3be272583c3224dcb70f9da6eadbb` | Reem Kufi 2.000 |
| [google/fonts Cairo](https://github.com/google/fonts/tree/main/ofl/cairo) | `9710da1eacb3be272583c3224dcb70f9da6eadbb` | Cairo 3.130 |

The existing Playfair Display / Inter files and OFL licenses are preserved from
the supplied snapshot; [runtime-font-provenance.json](runtime-font-provenance.json) records their exact names/hashes and the MaterialIcons bytes. MaterialIcons is loaded from the pinned Flutter test
bundle, not a system substitute. The owner's subsequent IBM Plex Sans Arabic
selection for the Arabic version is recorded above; these assets preserve the
original trial.

## Preservation

The real repository's production/test files, pubspec and lock were untouched.
`AGENTS.md`, `mobile/test/program_authority_test.dart`,
`mobile/test/support/fake_mayos_api.dart`, `docs/design-review/arabic-language-review.md`
and `docs/design-review/138/arabic-eval-set.json` retain their original bytes.
Only final review artifacts were written under the real
`/mnt/work/MAYOS/docs/design-review/143/`. No commits, staging, GitHub messages,
issue mutations, account-language rollout or hosted inference occurred.
The source work remains under `/tmp/mayos-arabic-143-prototype/mobile`;
`.baseline-verification` and `.patch-verification` there are temporary diagnostic
copies and are excluded from the bundle.

## Every phone PNG

### home

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-home-light-360x640.png) | [B](screens/B-home-light-360x640.png) |
| light / 412x915 | [A](screens/A-home-light-412x915.png) | [B](screens/B-home-light-412x915.png) |
| dark / 360x640 | [A](screens/A-home-dark-360x640.png) | [B](screens/B-home-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-home-dark-412x915.png) | [B](screens/B-home-dark-412x915.png) |

### home-detail

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-home-detail-light-360x640.png) | [B](screens/B-home-detail-light-360x640.png) |
| light / 412x915 | [A](screens/A-home-detail-light-412x915.png) | [B](screens/B-home-detail-light-412x915.png) |
| dark / 360x640 | [A](screens/A-home-detail-dark-360x640.png) | [B](screens/B-home-detail-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-home-detail-dark-412x915.png) | [B](screens/B-home-detail-dark-412x915.png) |

### logger

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-logger-light-360x640.png) | [B](screens/B-logger-light-360x640.png) |
| light / 412x915 | [A](screens/A-logger-light-412x915.png) | [B](screens/B-logger-light-412x915.png) |
| dark / 360x640 | [A](screens/A-logger-dark-360x640.png) | [B](screens/B-logger-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-logger-dark-412x915.png) | [B](screens/B-logger-dark-412x915.png) |

### logger-keypad

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-logger-keypad-light-360x640.png) | [B](screens/B-logger-keypad-light-360x640.png) |
| light / 412x915 | [A](screens/A-logger-keypad-light-412x915.png) | [B](screens/B-logger-keypad-light-412x915.png) |
| dark / 360x640 | [A](screens/A-logger-keypad-dark-360x640.png) | [B](screens/B-logger-keypad-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-logger-keypad-dark-412x915.png) | [B](screens/B-logger-keypad-dark-412x915.png) |

### logger-keypad-initial

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-logger-keypad-initial-light-360x640.png) | [B](screens/B-logger-keypad-initial-light-360x640.png) |
| dark / 360x640 | [A](screens/A-logger-keypad-initial-dark-360x640.png) | [B](screens/B-logger-keypad-initial-dark-360x640.png) |

### logger-rir

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| dark / 412x915 | [A](screens/A-logger-rir-dark-412x915.png) | [B](screens/B-logger-rir-dark-412x915.png) |

### logger-swipe

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| dark / 412x915 | [A](screens/A-logger-swipe-dark-412x915.png) | [B](screens/B-logger-swipe-dark-412x915.png) |

### chat

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-chat-light-360x640.png) | [B](screens/B-chat-light-360x640.png) |
| light / 412x915 | [A](screens/A-chat-light-412x915.png) | [B](screens/B-chat-light-412x915.png) |
| dark / 360x640 | [A](screens/A-chat-dark-360x640.png) | [B](screens/B-chat-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-chat-dark-412x915.png) | [B](screens/B-chat-dark-412x915.png) |

### chat-detail

| Theme / logical size | Candidate A | Candidate B |
| --- | --- | --- |
| light / 360x640 | [A](screens/A-chat-detail-light-360x640.png) | [B](screens/B-chat-detail-light-360x640.png) |
| light / 412x915 | [A](screens/A-chat-detail-light-412x915.png) | [B](screens/B-chat-detail-light-412x915.png) |
| dark / 360x640 | [A](screens/A-chat-detail-dark-360x640.png) | [B](screens/B-chat-detail-dark-360x640.png) |
| dark / 412x915 | [A](screens/A-chat-detail-dark-412x915.png) | [B](screens/B-chat-detail-dark-412x915.png) |

## Bundle integrity

[Bundle verification](logs/bundle-verification.log) checks archive bytes, exclusions and links.

[SHA256SUMS](SHA256SUMS) covers every published file except itself. Verify from
this directory with `sha256sum -c SHA256SUMS`.
