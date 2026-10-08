import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Loads the app font for layout tests that measure text width.
Future<void> loadInterTestFont() async {
  final FontLoader inter = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  await inter.load();
}
