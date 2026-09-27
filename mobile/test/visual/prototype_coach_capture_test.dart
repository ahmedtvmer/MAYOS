@Tags(<String>['capture'])
library;

// PROTOTYPE capture harness (wayfinder #105) — throwaway branch only.
//
//   cd mobile
//   CAPTURE=1 OUT=../docs/design-review/105 flutter test --tags capture \
//     test/visual/prototype_coach_capture_test.dart

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/features/coach/prototype_coach_shell/prototype_coach_model.dart';
import 'package:mayos_mobile/src/features/coach/prototype_coach_shell/prototype_coach_screen.dart';

final String _out = Platform.environment['OUT'] ?? '../docs/design-review/105';
const Key _boundaryKey = Key('proto.capture');

Future<void> _loadFonts() async {
  final FontLoader serif = FontLoader('PlayfairDisplay')
    ..addFont(rootBundle.load('assets/fonts/PlayfairDisplay-Variable.ttf'));
  final FontLoader sans = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  final FontLoader icons = FontLoader('MaterialIcons')
    ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await Future.wait<void>(
      <Future<void>>[serif.load(), sans.load(), icons.load()]);
}

Future<void> _write(WidgetTester t, String name) async {
  await t.pumpAndSettle();
  final RenderRepaintBoundary b =
      t.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  await t.runAsync(() async {
    final Directory dir = Directory(_out);
    await dir.create(recursive: true);
    final ui.Image image = await b.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data != null) {
      await File('${dir.path}/$name.png')
          .writeAsBytes(data.buffer.asUint8List());
    }
  });
}

Future<void> _pump(WidgetTester t, String variant, ThemeData theme) async {
  t.view.physicalSize = const Size(412, 915) * 2;
  t.view.devicePixelRatio = 2;
  final GoRouter r = GoRouter(
    initialLocation: '$prototypeCoachPath?variant=$variant',
    routes: <RouteBase>[
      GoRoute(
        path: prototypeCoachPath,
        builder: (_, GoRouterState s) => PrototypeCoachScreen(
            variant: s.uri.queryParameters['variant'] ?? 'A'),
      ),
    ],
  );
  await t.pumpWidget(MaterialApp.router(
    debugShowCheckedModeBanner: false,
    theme: theme,
    routerConfig: r,
    builder: (BuildContext context, Widget? child) =>
        RepaintBoundary(key: _boundaryKey, child: child),
  ));
  await t.pumpAndSettle();
}

void main() {
  setUpAll(_loadFonts);

  const Map<String, String> names = <String, String>{
    'A': 'a-tabs',
    'B': 'b-today',
    'C': 'c-players',
  };

  for (final MapEntry<String, ThemeData> theme in <String, ThemeData>{
    'dark': MayosTheme.dark,
    'light': MayosTheme.light,
  }.entries) {
    for (final String v in names.keys) {
      final String base = '${names[v]}-${theme.key}';
      testWidgets(base, (WidgetTester t) async {
        protoCoach.reset();
        await _pump(t, v, theme.value);
        await _write(t, '$base-1-landing');

        if (v == 'A') {
          await t.tap(find.text('Alerts').last);
          await _write(t, '$base-2-alerts');
          await t.tap(find.text('Requests').last);
          await _write(t, '$base-3-requests');
          await t.tap(find.text('Roster').last);
          await t.pumpAndSettle();
        }
        if (v == 'C') {
          await t.tap(find.text('Requests'));
          await _write(t, '$base-2-filter-requests');
          await t.tap(find.text('Requests'));
          await t.pumpAndSettle();
        }

        // Drill into the most urgent player.
        if (v == 'B') {
          await t.tap(find.text('Players').last);
          await _write(t, '$base-2-players');
        }
        await t.tap(find.text('karim_lifts').first);
        await _write(t, '$base-4-player-history');
        await t.tap(find.text('Check-ins'));
        await _write(t, '$base-5-player-checkins');
        await t.pageBack();
        await t.pumpAndSettle();

        // Resolve a substitution request.
        if (v == 'B') await t.tap(find.text('Today').last);
        if (v == 'A') await t.tap(find.text('Requests').last);
        if (v == 'C') {
          await t.tap(find.text('sara.m').first);
          await t.pumpAndSettle();
          await t.tap(find.text('Requests · 1'));
        }
        await t.pumpAndSettle();
        await t.tap(find.text('Barbell Back Squat → Hack Squat').first);
        await _write(t, '$base-6-resolve-sheet');
        Navigator.of(t.element(find.text('Apply swap'))).pop();
        await t.pumpAndSettle();
        if (v == 'C') {
          await t.pageBack();
          await t.pumpAndSettle();
        }

        // Mode switch.
        await t.tap(find.bySemanticsLabel(RegExp('Account and mode')));
        await _write(t, '$base-7-mode-sheet');
        await t.tap(find.text('Player mode'));
        await _write(t, '$base-8-player-mode');
      });
    }
  }
}
