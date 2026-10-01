# #143: selected IBM Plex Sans Arabic confirmation

The question is whether the recorded owner choice—IBM Plex Sans Arabic for all
Arabic-app text roles—works on the existing RTL Home, Workout logger and
Assistant chat. This confirmation supersedes the earlier bundle's statement
that the selected family had not been captured. The original A/B trial is
preserved unchanged; no new font-selection decision is requested.

Run from the repository root:

```bash
python3 docs/design-review/143/selected/preview.py
```

Open <http://localhost:8143/selected/prototype-gallery.html?variant=C>.
The floating arrows cycle C (selected), A and B; keyboard left/right also cycle
unless a form control has focus. Screen, theme, size and font are reflected in
the URL and the visible state panel. The viewer uses unedited Flutter PNGs:
it is a capture browser, not a live workout or chat session. It lives outside
the production Flutter entry point and build assets.

## Findings

- **Selected family confirmed on these fixtures:** 28 captures cover the same
  two phone canvases (360×640 and 412×915), light/dark themes, text scale 1.0,
  synthetic program/chat and logger interactions as the original trial.
  Both heading and interface primary families are IBM Plex Sans Arabic in C,
  including Latin exercise names and Western digits. The default English build
  retains Playfair Display / Inter. MaterialIcons and brand artwork are separate.
- **Long headings wrap:** the logger day heading spans two lines at both sizes.
  At 360×640 it reduces the visible set rows; the list still scrolls. Keep this
  wrapping when implementing the family change.
- **A new glyph failure was exposed and corrected in the prototype:** IBM Plex
  Sans Arabic Regular has no U+232B (`⌫`) in its cmap. The initial C keypad showed
  a missing-glyph box. C now uses `Icons.backspace_outlined` with an Arabic
  semantic label. [Before](evidence/before-backspace-icon.png) ·
  [After](screens/C-logger-keypad-light-360x640.png).
- **RTL behavior is retained from the trial:** semantic rows and navigation
  mirror; keypad/RIR ordering and numeric phrases stay LTR; chat bubbles and
  quote borders use directional alignment; swipe-delete reveals on the left.
  Western digits, entry of 27.5, keypad ordering and RIR ordering pass the
  existing capture assertions. No layout exceptions were reported.
- **Bounds of the result:** these are the preserved trial's existing widgets
  and synthetic fixtures, not a render of every subsequent app change. The
  fixture includes bidi isolates and nonbreaking spaces; it does not establish
  correct bidi handling for arbitrary model output. Desktop, accessibility
  scales, OS keyboards, other screens and production account language remain
  outside this confirmation.

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Flutter analysis | No issues | [log](logs/analyze.log) |
| Existing selected-family capture harness | 8 passed, 28 PNGs | [log](logs/capture-C.log) |
| Existing default-English theme/shell, logger, Markdown tests | 68 passed | [log](logs/english-widget-tests.log) |

No new tests or production rollout were added. Only three disposable source
files differ from the archived trial: `arabic_prototype.dart` enables C,
`mayos_typography.dart` selects IBM Plex primary families with static face
weights, and `logger_keypad.dart` uses an icon for C's backspace. Variable-font
axis overrides are disabled for C because the bundled IBM faces are static.

## Reproduce the Flutter captures

The [original source bundle](../prototype-source.tar.gz) supplies all fonts,
licenses, fixtures and widgets. Apply [selected overrides](selected-source-overrides.tar.gz)
on top. Use Flutter 3.47.5 / Dart 3.13.4, matching the preserved trial runtime.
`FLUTTER143` may be set to an unsnapped SDK executable; it defaults to `flutter`.
From the repository root:

```bash
REVIEW143="$PWD/docs/design-review/143"
PREVIEW143=$(mktemp -d)
tar -xzf "$REVIEW143/prototype-source.tar.gz" -C "$PREVIEW143"
tar -xzf "$REVIEW143/selected/selected-source-overrides.tar.gz" -C "$PREVIEW143"
cd "$PREVIEW143/mobile"
"${FLUTTER143:-flutter}" pub get
CAPTURE=1 CAPTURE_OUT="$PREVIEW143/screens" \
  "${FLUTTER143:-flutter}" test --no-pub --dart-define=ARABIC_PAIR=C \
  --tags capture test/visual/arabic_143_capture_test.dart --reporter expanded
```

Captures write to the new scratch directory, without changing the review PNGs.
The source bundles contain no credentials, caches or build output. The
prototype source and evidence are retained on `prototype/arabic-typeface-rtl`.
The finding to carry into the Arabic implementation is the approved IBM Plex
family plus wrapping, directional layout, LTR numerics and icon-based backspace.
