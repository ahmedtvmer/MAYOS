import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> scrollToControl(WidgetTester tester, Finder target,
    {Finder? list, double delta = 200}) async {
  await tester.pumpAndSettle();
  final Finder outerList = list ?? find.byType(ListView).first;
  await tester.scrollUntilVisible(target, delta,
    scrollable: find.descendant(of: outerList, matching: find.byType(Scrollable)).first);
  await tester.pumpAndSettle();
  await Scrollable.ensureVisible(tester.element(target), alignment: .5);
  await tester.pumpAndSettle();
}
