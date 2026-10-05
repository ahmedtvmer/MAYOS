import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/external_url_launcher.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/mayos_typography.dart';
import 'package:mayos_mobile/src/core/ui/mayos_markdown.dart';

String _visibleText(WidgetTester tester) {
  final StringBuffer text = StringBuffer();
  for (final SelectableText selectableText in tester.widgetList<SelectableText>(
    find.byType(SelectableText),
  )) {
    final InlineSpan? span = selectableText.textSpan;
    if (span != null) text.write(_spanText(span));
  }
  for (final RichText richText in tester.widgetList<RichText>(
    find.byType(RichText),
  )) {
    text.write(_spanText(richText.text));
  }
  return text.toString();
}

String _spanText(InlineSpan span) {
  if (span is! TextSpan) return '';
  return '${span.text ?? ''}${span.children?.map(_spanText).join() ?? ''}';
}

List<TextSpan> _spans(InlineSpan span) {
  if (span is! TextSpan) return const <TextSpan>[];
  return <TextSpan>[
    span,
    for (final InlineSpan child in span.children ?? const <InlineSpan>[])
      ..._spans(child),
  ];
}

List<TextSpan> _visibleSpans(WidgetTester tester) => <TextSpan>[
      for (final SelectableText selectableText
          in tester.widgetList<SelectableText>(find.byType(SelectableText)))
        if (selectableText.textSpan != null)
          ..._spans(selectableText.textSpan!),
      for (final RichText richText
          in tester.widgetList<RichText>(find.byType(RichText)))
        ..._spans(richText.text),
    ];

Future<void> _pump(
  WidgetTester tester,
  String markdown, {
  ThemeData? theme,
  Size? size,
  _RecordingLauncher? launcher,
}) async {
  if (size != null) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        if (launcher != null)
          externalUrlLauncherProvider.overrideWithValue(launcher.open),
      ],
      child: MaterialApp(
        theme: theme ?? MayosTheme.light,
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: MayosMarkdown(source: markdown),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

class _RecordingLauncher {
  final List<String> urls = <String>[];

  Future<bool> open(String url) async {
    urls.add(url);
    return true;
  }
}

Finder _selectableContaining(String text) => find.byWidgetPredicate(
      (Widget widget) =>
          widget is SelectableText &&
          (widget.textSpan?.toPlainText().contains(text) ?? false),
    );

Finder _horizontalScrollers() => find.byWidgetPredicate(
      (Widget widget) =>
          widget is SingleChildScrollView &&
          widget.scrollDirection == Axis.horizontal,
    );

void main() {
  testWidgets('renders bold, italic and MAYOS-sized headings', (
    WidgetTester tester,
  ) async {
    await _pump(
      tester,
      '# Training plan\n\n## Main lift\n\nUse **control** and *patience*.',
    );

    final String text = _visibleText(tester);
    final List<TextSpan> spans = _visibleSpans(tester);
    expect(text, contains('Training plan'));
    expect(text, contains('Main lift'));
    expect(text, contains('control'));
    expect(text, contains('patience'));
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'control' && span.style?.fontWeight == FontWeight.w700,
      ),
      isTrue,
    );
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'patience' &&
            span.style?.fontStyle == FontStyle.italic,
      ),
      isTrue,
    );
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'Training plan' &&
            span.style?.fontFamily == MayosTypography.forLanguage('en').pageHeading.fontFamily &&
            span.style?.fontSize == MayosTypography.forLanguage('en').pageHeading.fontSize,
      ),
      isTrue,
    );
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'Main lift' &&
            span.style?.fontFamily ==
                MayosTypography.forLanguage('en').sectionHeading.fontFamily &&
            span.style?.fontSize == MayosTypography.forLanguage('en').sectionHeading.fontSize,
      ),
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('renders bullets, numbered and nested lists', (
    WidgetTester tester,
  ) async {
    await _pump(
      tester,
      '- First cue\n  - Nested cue\n1. First step\n2. Second step',
    );

    final String text = _visibleText(tester);
    expect(text, contains('First cue'));
    expect(text, contains('Nested cue'));
    expect(text, contains('First step'));
    expect(text, contains('Second step'));
    expect(
      tester.getTopLeft(_selectableContaining('Nested cue')).dx,
      greaterThan(tester.getTopLeft(_selectableContaining('First cue')).dx),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('renders inline code, code blocks, quotes and paragraphs', (
    WidgetTester tester,
  ) async {
    await _pump(
      tester,
      'Use `3 reps`.\n\n'
      '```text\nKeep the same setup.\n```\n\n'
      '> Stay patient.\n\nFirst paragraph.\n\nSecond paragraph.\nLine two.',
    );

    final String text = _visibleText(tester);
    final List<TextSpan> spans = _visibleSpans(tester);
    expect(text, contains('3 reps'));
    expect(text, contains('Keep the same setup.'));
    expect(text, contains('Stay patient.'));
    expect(text, contains('First paragraph.'));
    expect(text, contains('Second paragraph.'));
    expect(text, contains('Line two.'));
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == '3 reps' &&
            span.style?.fontFamily == MayosTypography.forLanguage('en').code.fontFamily &&
            span.style?.height == 1.4,
      ),
      isTrue,
    );
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'Keep the same setup.' &&
            span.style?.fontFamily == MayosTypography.forLanguage('en').code.fontFamily &&
            span.style?.height == 1.4,
      ),
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'shows HTML as text, omits remote images, and keeps malformed text',
    (WidgetTester tester) async {
      const String source = 'Raw <script>alert(1)</script>\n\n'
          '![plan image](https://example.com/plan.png)\n\n'
          '[training notes](https://example.com/notes)\n\n'
          '**unfinished marker';
      await _pump(tester, source);

      final String text = _visibleText(tester);
      expect(text, contains('Raw <script>alert(1)</script>'));
      expect(text, contains('plan image'));
      expect(text, contains('training notes'));
      expect(text, contains('**unfinished marker'));
      expect(find.byType(Image), findsNothing);
      expect(find.byType(HtmlElementView), findsNothing);
      expect(tester.takeException(), isNull);

      final MarkdownBody body = tester.widget<MarkdownBody>(
        find.byType(MarkdownBody),
      );
      expect(body.selectable, isTrue);
      expect(body.onTapLink, isNotNull);
      expect(body.imageBuilder, isNotNull);
    },
  );

  testWidgets('web links launch externally while other schemes stay inert', (
    WidgetTester tester,
  ) async {
    final _RecordingLauncher launcher = _RecordingLauncher();
    await _pump(
      tester,
      '[training notes](https://example.com/notes)\n\n'
      '[script payload](javascript:alert(1))\n\n'
      '[local file](file:///tmp/notes.txt)',
      launcher: launcher,
    );

    final MayosThemeExtension colors = MayosTheme.of(
      tester.element(find.byType(MayosMarkdown)),
    );
    final List<TextSpan> spans = _visibleSpans(tester);
    expect(
      spans.any(
        (TextSpan span) =>
            span.text == 'training notes' &&
            span.style?.color == colors.accent &&
            span.style?.decoration == TextDecoration.underline,
      ),
      isTrue,
    );

    await tester.tap(find.text('training notes', findRichText: true));
    await tester.pump();
    expect(launcher.urls, <String>['https://example.com/notes']);

    await tester.tap(find.text('script payload', findRichText: true));
    await tester.pump();
    await tester.tap(find.text('local file', findRichText: true));
    await tester.pump();
    expect(launcher.urls, <String>['https://example.com/notes']);
  });

  testWidgets('wide GFM tables scroll horizontally at 360 dp', (
    WidgetTester tester,
  ) async {
    await _pump(
      tester,
      '| Set | Notes |\n| --- | --- |\n'
      '| 1 | A deliberately wide coaching note that exceeds the chat width. |',
      size: const Size(360, 640),
    );

    expect(_visibleText(tester), contains('deliberately wide coaching note'));
    expect(_horizontalScrollers(), findsOneWidget);
    expect(
        tester.getSize(_horizontalScrollers()).width, lessThanOrEqualTo(360));
    expect(tester.takeException(), isNull);
  });

  testWidgets('long code lines scroll horizontally at 360 dp', (
    WidgetTester tester,
  ) async {
    const String longCodeLine =
        '0123456789abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz'
        '0123456789abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz';
    await _pump(
      tester,
      '```text\n$longCodeLine\n```',
      size: const Size(360, 640),
    );

    expect(_visibleText(tester), contains(longCodeLine));
    expect(_horizontalScrollers(), findsOneWidget);
    expect(
        tester.getSize(_horizontalScrollers()).width, lessThanOrEqualTo(360));
    expect(tester.takeException(), isNull);
  });

  testWidgets('block HTML is rendered only as inert text', (
    WidgetTester tester,
  ) async {
    const String source = '<div>Keep this literal text</div>\n\n'
        '```html\n<div>Keep fenced HTML literal</div>\n```';
    await _pump(tester, source);

    expect(
      _visibleText(tester),
      contains('<div>Keep this literal text</div>'),
    );
    expect(
        _visibleText(tester), contains('<div>Keep fenced HTML literal</div>'));
    expect(find.byType(HtmlElementView), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('long mixed Markdown has no overflow at 360 dp in both themes', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    const String source = '# Training notes\n\n'
        'A paragraph that wraps cleanly across a narrow phone width.\n'
        'A deliberate line break remains readable.\n\n'
        '- A first item with **emphasis**\n'
        '  - A nested item\n'
        '1. One\n2. Two\n\n'
        '> Keep the movement controlled.\n\n'
        '```text\nslow and steady\n```';
    for (final ThemeData theme in <ThemeData>[
      MayosTheme.light,
      MayosTheme.dark,
    ]) {
      await _pump(tester, source, theme: theme);
      expect(tester.takeException(), isNull);
      expect(find.byType(MarkdownBody), findsOneWidget);
    }
  });
}
