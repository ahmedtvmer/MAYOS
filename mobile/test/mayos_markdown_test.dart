import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
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

Future<void> _pump(
  WidgetTester tester,
  String markdown, {
  ThemeData? theme,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: theme ?? MayosTheme.light,
      home: Scaffold(
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: MayosMarkdown(source: markdown),
        ),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('renders bold, italic and MAYOS-sized headings', (
    WidgetTester tester,
  ) async {
    await _pump(
      tester,
      '# Training plan\n\n## Main lift\n\nUse **control** and *patience*.',
    );

    final String text = _visibleText(tester);
    final List<TextSpan> spans = <TextSpan>[
      for (final SelectableText selectableText in
          tester.widgetList<SelectableText>(find.byType(SelectableText)))
        if (selectableText.textSpan != null)
          ..._spans(selectableText.textSpan!),
      for (final RichText richText in
          tester.widgetList<RichText>(find.byType(RichText)))
        ..._spans(richText.text),
    ];
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
    expect(text, contains('3 reps'));
    expect(text, contains('Keep the same setup.'));
    expect(text, contains('Stay patient.'));
    expect(text, contains('First paragraph.'));
    expect(text, contains('Second paragraph.'));
    expect(text, contains('Line two.'));
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'refuses HTML and remote images, leaves links plain and keeps malformed text',
    (WidgetTester tester) async {
      const String source =
          'Raw <script>alert(1)</script>\n\n'
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
      expect(body.onTapLink, isNull);
      expect(body.imageBuilder, isNotNull);
    },
  );

  testWidgets('long mixed Markdown has no overflow at 360 dp in both themes', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    const String source =
        '# Training notes\n\n'
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
