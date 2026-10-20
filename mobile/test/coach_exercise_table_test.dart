import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_colors.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_card_table.dart';
import 'package:mayos_mobile/src/core/ui/mayos_table_frame.dart';
import 'package:mayos_mobile/src/features/coach/coach_exercise_table.dart';

const Key _frameKey = Key('table-frame');
const Key _headerKey = Key('table-header');
const MayosTableColumns _columns =
    MayosTableColumns(<double>[40, 300, 150], 1);

void main() {
  testWidgets('card table desktop uses shared header and configured widths',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(1440, 960);
    addTearDown(tester.view.resetPhysicalSize);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: MayosTheme.light,
        home: Scaffold(
          body: MayosCardTable(
            columns: const <String>['Player', 'Follow-up', 'Actions'],
            tableColumns: const MayosTableColumns(<double>[120, 220, 100], 1),
            rows: const <MayosCardTableRow>[
              MayosCardTableRow(
                cells: <Widget?>[
                  Text('Bob'),
                  Text('Follow-up overdue'),
                  Text('Revoke'),
                ],
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.text('Player'), findsOneWidget);
    expect(find.text('Follow-up'), findsOneWidget);
    expect(find.text('Actions'), findsOneWidget);
    expect(find.text('Bob'), findsOneWidget);
    expect(find.text('Follow-up overdue'), findsOneWidget);
    expect(find.text('Revoke'), findsOneWidget);
    final List<double> widths = MayosTableLayout.widthsOf(
      tester.element(find.text('Player')),
    );
    expect(widths, <double>[120, 1202, 100]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow table keeps horizontal scrolling without overflow',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpTable(tester, width: 360, theme: MayosTheme.light);

    final Finder scrollableFinder = find.descendant(
      of: find.byKey(_frameKey),
      matching: find.byType(Scrollable),
    );
    final ScrollableState scrollable =
        tester.state<ScrollableState>(scrollableFinder);
    expect(scrollable.position.maxScrollExtent, greaterThan(0));
    await tester.drag(find.byKey(_frameKey), const Offset(-100, 0));
    await tester.pumpAndSettle();
    expect(scrollable.position.pixels, greaterThan(0));
    expect(tester.takeException(), isNull);
  });

  testWidgets('table headers render the light and dark palette colours',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(900, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final List<({ThemeData theme, Color header, Color muted})> appearances =
        <({ThemeData theme, Color header, Color muted})>[
      (
        theme: MayosTheme.light,
        header: MayosPalette.lightSecondarySurface,
        muted: MayosPalette.lightTextMuted,
      ),
      (
        theme: MayosTheme.dark,
        header: MayosPalette.darkSurfaceElevated,
        muted: MayosPalette.darkTextMuted,
      ),
    ];
    for (final ({ThemeData theme, Color header, Color muted}) appearance
        in appearances) {
      await _pumpTable(tester, width: 900, theme: appearance.theme);

      final Finder headerContainer = find.descendant(
        of: find.byKey(_headerKey),
        matching: find.byType(Container),
      ).first;
      final BoxDecoration decoration =
          tester.widget<Container>(headerContainer).decoration! as BoxDecoration;
      expect(decoration.color, appearance.header);
      expect(
        tester.widget<Text>(find.text('Exercise')).style!.color,
        appearance.muted,
      );
    }
  });

  testWidgets('table hit area follows the 16dp rounded frame',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(900, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    int tapCount = 0;
    await _pumpTable(
      tester,
      width: 900,
      theme: MayosTheme.light,
      onTap: () => tapCount++,
    );

    final Rect frame = tester.getRect(find.byKey(_frameKey));
    await tester.tapAt(Offset(frame.left + 1, frame.top + 1));
    await tester.pump();
    expect(tapCount, 0);

    await tester.tapAt(Offset(frame.left + 14, frame.top + 2));
    await tester.pump();
    expect(tapCount, 1);
  });
}

Future<void> _pumpTable(
  WidgetTester tester, {
  required double width,
  required ThemeData theme,
  VoidCallback? onTap,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: theme,
      themeAnimationDuration: Duration.zero,
      home: Scaffold(
        body: SizedBox(
          width: width,
          child: CoachExerciseTableFrame(
            key: _frameKey,
            columns: _columns,
            child: InkWell(
              onTap: onTap,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  MayosTableHeader(
                    key: _headerKey,
                    labels: const <String>['#', 'Exercise', 'Sets'],
                    alignments: const <TextAlign>[
                      TextAlign.center,
                      TextAlign.start,
                      TextAlign.end,
                    ],
                  ),
                  MayosTableRow(
                    cells: <Widget>[
                      const Text('1'),
                      const Text('Example exercise'),
                      const Text('3'),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
