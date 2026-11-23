import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Tapping a picker candidate opens the shared exercise screen as a preview
/// (#803); this taps its "Use this exercise", which makes the selection a
/// tap used to make.
Future<void> usePreviewedExercise(WidgetTester tester) async {
  final Finder use = find.byKey(const ValueKey<String>('exercise.detail.use'));
  for (int i = 0; i < 100 && use.evaluate().isEmpty; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  await tester.tap(use);
  await tester.pumpAndSettle();
}
