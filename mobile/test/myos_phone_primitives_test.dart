import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/core/theme/myos_theme.dart';
import 'package:myos_mobile/src/core/ui/myos_bottom_sheet_editor.dart';
import 'package:myos_mobile/src/core/ui/myos_card_table.dart';
import 'package:myos_mobile/src/core/ui/myos_table_frame.dart';

void main() {
  testWidgets('card table reuses its headers and cells in the desktop table',
      (WidgetTester tester) async {
    final double dpr = tester.view.devicePixelRatio;
    tester.view.physicalSize = Size(1280 * dpr, 900 * dpr);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: MyosTheme.light,
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(24),
            child: MyosCardTable(
              columns: const <String>['Player', 'Program'],
              tableColumns: const MyosTableColumns(<double>[160, 180], 1),
              rows: const <MyosCardTableRow>[
                MyosCardTableRow(
                  cells: <Widget>[Text('alice'), Text('Upper/Lower')],
                ),
              ],
            ),
          ),
        ),
      ),
    );

    expect(find.text('Player'), findsOneWidget);
    expect(find.text('Program'), findsOneWidget);
    expect(find.text('alice'), findsOneWidget);
    expect(find.text('Upper/Lower'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('Player')).dy,
      lessThan(tester.getTopLeft(find.text('alice')).dy),
    );
    expect(tester.getRect(find.text('Program')).right, greaterThan(1200));
    expect(tester.takeException(), isNull);
    tester.view.resetViewInsets();
  });

  testWidgets('bottom-sheet editor keeps actions above keyboard and scrolls',
      (WidgetTester tester) async {
    final double dpr = tester.view.devicePixelRatio;
    tester.view.physicalSize = Size(360 * dpr, 800 * dpr);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetViewInsets);

    await tester.pumpWidget(
      MaterialApp(
        theme: MyosTheme.light,
        home: Builder(
          builder: (BuildContext context) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => showMyosBottomSheetEditor<void>(
                  context: context,
                  content: Column(
                    children: <Widget>[
                      for (int index = 0; index < 16; index++)
                        SizedBox(
                          height: 72,
                          child: Text('Form field ${index + 1}'),
                        ),
                    ],
                  ),
                  actions: FilledButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Save'),
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    tester.view.viewInsets = FakeViewPadding(bottom: 300 * dpr);
    await tester.pumpAndSettle();

    expect(find.text('Form field 1'), findsOneWidget);
    expect(find.text('Form field 16').hitTestable(), findsNothing);
    final Finder save = find.text('Save');
    expect(save, findsOneWidget);
    expect(save.hitTestable(), findsOneWidget);
    expect(tester.getBottomLeft(save).dy, lessThan(500));
    final Finder scrollable = find.descendant(
      of: find.byType(BottomSheet),
      matching: find.byType(Scrollable),
    ).first;
    await tester.drag(scrollable, const Offset(0, -700));
    await tester.pumpAndSettle();
    expect(find.text('Form field 16'), findsOneWidget);
    expect(find.text('Save'), findsOneWidget);
    expect(find.text('Save').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
