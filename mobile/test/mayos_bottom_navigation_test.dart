import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';

const List<MayosNavItem> _english = <MayosNavItem>[
  MayosNavItem(label: 'Home', icon: Icons.home_outlined, selectedIcon: Icons.home),
  MayosNavItem(label: 'Program', icon: Icons.article_outlined, selectedIcon: Icons.article),
  MayosNavItem(
      label: 'AI Assistant',
      icon: Icons.chat_bubble_outline,
      selectedIcon: Icons.chat_bubble),
  MayosNavItem(
      label: 'Nutrition',
      icon: Icons.restaurant_menu_outlined,
      selectedIcon: Icons.restaurant_menu),
  MayosNavItem(
      label: 'Progress',
      icon: Icons.insights_outlined,
      selectedIcon: Icons.insights,
      dot: true,
      dotLabel: 'Checkpoint review ready'),
];

const List<MayosNavItem> _arabic = <MayosNavItem>[
  MayosNavItem(label: 'الرئيسية', icon: Icons.home_outlined, selectedIcon: Icons.home),
  MayosNavItem(
      label: 'البرنامج التدريبي',
      icon: Icons.article_outlined,
      selectedIcon: Icons.article),
  MayosNavItem(
      label: 'المساعد الذكي',
      icon: Icons.chat_bubble_outline,
      selectedIcon: Icons.chat_bubble),
  MayosNavItem(
      label: 'التغذية',
      icon: Icons.restaurant_menu_outlined,
      selectedIcon: Icons.restaurant_menu),
  MayosNavItem(label: 'التقدم', icon: Icons.insights_outlined, selectedIcon: Icons.insights),
];

Future<void> _pumpBar(
  WidgetTester tester, {
  required List<MayosNavItem> items,
  required int index,
  TextDirection direction = TextDirection.ltr,
  double width = 360,
  double textScale = 1.0,
  bool disableAnimations = false,
  ValueChanged<int>? onSelected,
}) async {
  tester.view.physicalSize = Size(width, 640);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: MayosTheme.light,
      home: MediaQuery(
        data: MediaQueryData(
          size: Size(width, 640),
          textScaler: TextScaler.linear(textScale),
          disableAnimations: disableAnimations,
        ),
        child: Directionality(
          textDirection: direction,
          child: Scaffold(
            bottomNavigationBar: MayosBottomNavigation(
              items: items,
              index: index,
              onSelected: onSelected ?? (_) {},
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

Rect _pill(WidgetTester tester) =>
    tester.getRect(find.byKey(MayosBottomNavigation.indicatorKey));

void main() {
  testWidgets('the pill sits behind the selected icon and slides to the next',
      (WidgetTester tester) async {
    await _pumpBar(tester, items: _english, index: 0);
    final Rect home = _pill(tester);
    expect(home.center.dx, closeTo(tester.getCenter(find.byIcon(Icons.home)).dx, 0.5));
    expect(home.contains(tester.getCenter(find.byIcon(Icons.home))), isTrue);

    await _pumpBar(tester, items: _english, index: 3);
    // Mid-slide the pill is between Home and Nutrition ...
    await tester.pump(const Duration(milliseconds: 60));
    final double mid = _pill(tester).center.dx;
    final double nutrition =
        tester.getCenter(find.byIcon(Icons.restaurant_menu)).dx;
    expect(mid, greaterThan(home.center.dx));
    expect(mid, lessThan(nutrition));
    // ... and it lands on Nutrition.
    await tester.pump(const Duration(milliseconds: 200));
    expect(_pill(tester).center.dx, closeTo(nutrition, 0.5));
  });

  testWidgets('reduced motion moves the pill without a slide',
      (WidgetTester tester) async {
    await _pumpBar(tester, items: _english, index: 0, disableAnimations: true);
    await _pumpBar(tester, items: _english, index: 4, disableAnimations: true);
    expect(
      _pill(tester).center.dx,
      closeTo(tester.getCenter(find.byIcon(Icons.insights)).dx, 0.5),
    );
  });

  testWidgets('right-to-left puts the pill on the mirrored destination',
      (WidgetTester tester) async {
    await _pumpBar(
      tester,
      items: _arabic,
      index: 0,
      direction: TextDirection.rtl,
    );
    final double homeIcon = tester.getCenter(find.byIcon(Icons.home)).dx;
    expect(homeIcon, greaterThan(300), reason: 'Home is the rightmost in RTL');
    expect(_pill(tester).center.dx, closeTo(homeIcon, 0.5));
  });

  for (final List<MayosNavItem> items in <List<MayosNavItem>>[_english, _arabic]) {
    for (final double scale in <double>[1.0, 2.0]) {
      testWidgets(
          '${items[2].label} labels fit a 360 px bar at ${scale}x text without overflow',
          (WidgetTester tester) async {
        await _pumpBar(tester, items: items, index: 2, textScale: scale);
        expect(tester.takeException(), isNull);
        final double cell = 360 / items.length;
        for (final MayosNavItem item in items) {
          final Rect label = tester.getRect(find.text(item.label));
          expect(label.width, lessThanOrEqualTo(cell + 0.5),
              reason: '${item.label} must stay inside its cell');
          expect(label.height, lessThanOrEqualTo(16.5),
              reason: '${item.label} must stay on one line');
        }
      });
    }
  }

  testWidgets('the dot is announced with the destination and taps select it',
      (WidgetTester tester) async {
    int? tapped;
    await _pumpBar(
      tester,
      items: _english,
      index: 0,
      onSelected: (int value) => tapped = value,
    );
    expect(find.bySemanticsLabel('Progress, Checkpoint review ready'),
        findsOneWidget);
    await tester.tap(find.text('AI Assistant'));
    expect(tapped, 2);
  });

  testWidgets('a count badge still shows and wins over the dot',
      (WidgetTester tester) async {
    await _pumpBar(
      tester,
      items: const <MayosNavItem>[
        MayosNavItem(label: 'Roster', icon: Icons.people_outline, selectedIcon: Icons.people),
        MayosNavItem(
            label: 'Alerts',
            icon: Icons.notifications_none,
            selectedIcon: Icons.notifications,
            badge: 3,
            dot: true),
      ],
      index: 0,
    );
    expect(find.text('3'), findsOneWidget);
    expect(find.bySemanticsLabel('Alerts'), findsOneWidget);
  });
}
