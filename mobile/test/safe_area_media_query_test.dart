import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/core/safe_area_media_query.dart';
import 'package:myos_mobile/src/core/safe_area_insets.dart';

void main() {
  testWidgets('web insets protect scaffold top and bottom controls',
      (WidgetTester tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(800, 800);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final _FakeSafeAreaInsetsSource source = _FakeSafeAreaInsetsSource(
      const EdgeInsets.only(top: 47, bottom: 34),
    );
    await tester.pumpWidget(
      _testApp(source, baseline: const EdgeInsets.only(top: 20, bottom: 20)),
    );

    expect(
      tester.getTopLeft(find.byKey(const ValueKey<String>('top-control'))).dy,
      greaterThanOrEqualTo(47),
    );
    expect(
      tester.getBottomRight(find.byKey(const ValueKey<String>('bottom-control'))).dy,
      lessThanOrEqualTo(
        tester.view.physicalSize.height / tester.view.devicePixelRatio - 34,
      ),
    );
    expect(
      find.text('47.0,34.0|47.0,34.0'),
      findsOneWidget,
    );
  });

  testWidgets('keyboard overlap reduces padding but keeps view padding',
      (WidgetTester tester) async {
    final _FakeSafeAreaInsetsSource source = _FakeSafeAreaInsetsSource(
      const EdgeInsets.only(bottom: 34),
    );
    await tester.pumpWidget(
      _testApp(
        source,
        baseline: EdgeInsets.zero,
        viewInsets: const EdgeInsets.only(bottom: 300),
      ),
    );

    expect(find.text('0.0,0.0|0.0,34.0'), findsOneWidget);
  });

  testWidgets('zero web insets preserve the existing MediaQuery padding',
      (WidgetTester tester) async {
    final _FakeSafeAreaInsetsSource source = _FakeSafeAreaInsetsSource(
      EdgeInsets.zero,
    );
    await tester.pumpWidget(
      _testApp(source, baseline: const EdgeInsets.only(top: 12, bottom: 9)),
    );

    expect(find.text('12.0,9.0|12.0,9.0'), findsOneWidget);
  });
}

Widget _testApp(
  SafeAreaInsetsSource source, {
  required EdgeInsets baseline,
  EdgeInsets viewInsets = EdgeInsets.zero,
}) =>
    MaterialApp(
      builder: (BuildContext context, Widget? child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          padding: baseline,
          viewPadding: baseline,
          viewInsets: viewInsets,
        ),
        child: SafeAreaMediaQuery(
          source: source,
          child: Builder(
            builder: (BuildContext context) => Stack(
              children: <Widget>[
                Scaffold(
                  appBar: AppBar(
                    actions: <Widget>[
                      IconButton(
                        key: const ValueKey<String>('top-control'),
                        onPressed: () {},
                        icon: const Icon(Icons.settings),
                      ),
                    ],
                  ),
                  bottomNavigationBar: SafeArea(
                    child: SizedBox(
                      height: 48,
                      child: IconButton(
                        key: const ValueKey<String>('bottom-control'),
                        onPressed: () {},
                        icon: const Icon(Icons.home),
                      ),
                    ),
                  ),
                ),
                Positioned(
                  top: 0,
                  child: Text(
                    '${MediaQuery.paddingOf(context).top},'
                    '${MediaQuery.paddingOf(context).bottom}|'
                    '${MediaQuery.viewPaddingOf(context).top},'
                    '${MediaQuery.viewPaddingOf(context).bottom}',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );

class _FakeSafeAreaInsetsSource extends ChangeNotifier
    implements SafeAreaInsetsSource {
  _FakeSafeAreaInsetsSource(this.insets);

  @override
  final EdgeInsets insets;
}
