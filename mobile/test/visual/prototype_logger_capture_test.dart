@Tags(<String>['capture'])
library;

// PROTOTYPE capture harness (wayfinder #107) — throwaway branch only.
//
//   cd mobile
//   CAPTURE=1 OUT=../docs/design-review/107 flutter test --tags capture \
//     test/visual/prototype_logger_capture_test.dart

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/features/player/workout/prototype_logger/prototype_logger_model.dart';
import 'package:mayos_mobile/src/features/player/workout/prototype_logger/prototype_logger_screen.dart';
import 'package:mayos_mobile/src/features/player/workout/prototype_logger/prototype_logger_widgets.dart';

final bool _enabled = Platform.environment['CAPTURE'] == '1';
final String _out =
    Platform.environment['OUT'] ?? '../docs/design-review/107';
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
  for (int i = 0; i < 6; i++) {
    await t.pump(const Duration(milliseconds: 100));
  }
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
    initialLocation: '$prototypeLoggerPath?variant=$variant',
    routes: <RouteBase>[
      GoRoute(
        path: prototypeLoggerPath,
        builder: (_, GoRouterState s) => PrototypeLoggerScreen(
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
  await t.pump();
}

/// Set 1 as last time, set 2 a 102.5 kg PR, set 3 105 × 3 which beats set 2
/// for Heaviest; rest is running. Plus one Unplanned exercise.
void _logSomeSets() {
  final ProtoSession s = protoSession;
  final ProtoExercise bench = s.exercises.first;
  s.toggle(bench, bench.sets[0]);
  s.setKg(bench.sets[1], 102.5);
  s.toggle(bench, bench.sets[1]);
  s.setKg(bench.sets[2], 105);
  s.setReps(bench.sets[2], 3);
  s.setRir(bench.sets[2], 0);
  s.toggle(bench, bench.sets[2]);
}

void main() {
  // Created in the real zone so its periodic ticker isn't a pending fake timer.
  protoSession.reset();

  setUpAll(_loadFonts);

  const Map<String, String> names = <String, String>{
    'A': 'a-table',
    'B': 'b-focus',
    'C': 'c-feed',
  };

  for (final MapEntry<String, ThemeData> theme in <String, ThemeData>{
    'dark': MayosTheme.dark,
    'light': MayosTheme.light,
  }.entries) {
    for (final String v in names.keys) {
      final String base = '${names[v]}-${theme.key}';
      testWidgets('$base', (WidgetTester t) async {
        protoSession.reset();
        await _pump(t, v, theme.value);
        await _write(t, '$base-1-start');

        // Keypad open on the weight field.
        final Finder kg = switch (v) {
          'A' => find.text('95').first,
          _ => find.text('kg').first,
        };
        await t.tap(kg);
        await _write(t, '$base-2-keypad');
        await t.tap(find.text('Hide').first);
        await t.pump();

        _logSomeSets();
        await _write(t, '$base-3-prs-and-rest');

        if (v == 'A' && theme.key == 'dark') {
          protoSession.skipRest();
          protoSession.addUnplanned('Cable Fly', protoLibrary.first.$2);
          await t.pump();
          await t.drag(find.byType(ListView).first, const Offset(0, -900));
          await _write(t, 'a-table-dark-4-unplanned-scrolled');
          protoSession.startRest(protoSession.exercises.first);
          await t.tap(find.byIcon(Icons.lock_outline));
          await _write(t, 'lock-screen-notification');
          await t.tapAt(const Offset(200, 400));
          await t.pump();
          showFinish(t.element(find.byType(PrototypeLoggerScreen)),
              protoSession);
          await _write(t, 'finish-unticked-sets');
        }
        protoSession.skipRest();
      }, skip: !_enabled);
    }
  }
}
