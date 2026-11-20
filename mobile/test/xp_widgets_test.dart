import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/training_status_projection.dart';
import 'package:mayos_mobile/src/features/player/xp/xp_widgets.dart';

// XP, ranks and the Weekly streak in the Player app (#743, #796).

TrainingStatus _status({
  int xpTotal = 120,
  int weeklyStreak = 4,
  int longestStreak = 9,
  bool thisWeekDone = true,
  bool weekPaused = false,
  int mayosWorkouts = 14,
  String rankId = 'regular',
}) {
  final PlayerRank rank =
      playerRankLadder.firstWhere((PlayerRank r) => r.id == rankId);
  final int index = playerRankLadder.indexOf(rank);
  final PlayerRank? next =
      index + 1 < playerRankLadder.length ? playerRankLadder[index + 1] : null;
  return TrainingStatus(
    weeklyStreak: weeklyStreak,
    weekStart: '2026-11-21',
    weekDone: thisWeekDone ? 1 : 0,
    weekTarget: 3,
    mayosWorkouts: mayosWorkouts,
    nextCheckpoint: 25,
    workoutsToNext: 11,
    longestStreak: longestStreak,
    thisWeekDone: thisWeekDone,
    weekPaused: weekPaused,
    xpTotal: xpTotal,
    rank: rank,
    nextRank: next,
    xpIntoRank: xpTotal - rank.threshold,
    xpForNextRank: next == null ? null : next.threshold - rank.threshold,
  );
}

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  String language = 'en',
  bool dark = false,
  Size size = const Size(390, 844),
  bool disableAnimations = false,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: dark ? MayosTheme.dark : MayosTheme.light,
      locale: Locale(language),
      supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
      localizationsDelegates: const <LocalizationsDelegate<dynamic>>[
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: MediaQuery(
        data: MediaQueryData(size: size, disableAnimations: disableAnimations),
        child: Scaffold(body: SingleChildScrollView(child: child)),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  group('Home strip', () {
    testWidgets('shows rank, progress to the next rank and the streak with a tick',
        (WidgetTester tester) async {
      int taps = 0;
      await _pump(tester, XpStatusStrip(status: _status(), onTap: () => taps++));
      expect(find.text('Regular'), findsOneWidget);
      expect(find.text('40 / 160 XP to Committed'), findsOneWidget);
      expect(find.text('4-wk streak'), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('xp.thisWeekTick')), findsOneWidget);
      await tester.tap(find.byKey(XpStatusStrip.stripKey));
      expect(taps, 1);
      expect(tester.getSize(find.byKey(XpStatusStrip.stripKey)).height,
          greaterThanOrEqualTo(44));
    });

    testWidgets('a new Player sees the first-workout hint', (WidgetTester tester) async {
      await _pump(
        tester,
        XpStatusStrip(
          status: _status(xpTotal: 0, weeklyStreak: 0, longestStreak: 0,
              thisWeekDone: false, mayosWorkouts: 0, rankId: 'rookie'),
          onTap: () {},
        ),
      );
      expect(find.text('Rookie'), findsOneWidget);
      expect(find.text('Finish your first workout to earn XP'), findsOneWidget);
      expect(find.text('No streak yet'), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('xp.thisWeekTick')), findsNothing);
    });

    testWidgets('a paused week reads paused, with no tick and no warning',
        (WidgetTester tester) async {
      await _pump(tester,
          XpStatusStrip(status: _status(weekPaused: true, thisWeekDone: false), onTap: () {}));
      expect(find.text('paused'), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('xp.thisWeekTick')), findsNothing);
    });

    testWidgets('Arabic strip reads right to left without overflow at 360 px',
        (WidgetTester tester) async {
      await _pump(tester, XpStatusStrip(status: _status(), onTap: () {}),
          language: 'ar', size: const Size(360, 780));
      expect(find.text('منتظم'), findsOneWidget);
      expect(tester.takeException(), isNull);
      expect(
        Directionality.of(tester.element(find.byKey(XpStatusStrip.stripKey))),
        TextDirection.rtl,
      );
    });
  });

  testWidgets('the Rank sheet lists every rank, marks the current one and explains XP',
      (WidgetTester tester) async {
    await _pump(tester, RankSheetBody(status: _status()));
    for (final PlayerRank rank in playerRankLadder) {
      expect(find.byKey(ValueKey<String>('xp.ladder.${rank.id}')), findsOneWidget);
    }
    expect(find.text('Regular · you'), findsOneWidget);
    expect(find.text('120 more XP to Committed, about 15 workouts'), findsOneWidget);
    expect(find.text('How you earn XP'), findsOneWidget);
    expect(find.text('+2 each'), findsOneWidget);
    expect(find.textContaining('XP never goes down'), findsOneWidget);
  });

  testWidgets('the Profile card shows the weekly and longest streaks and workouts',
      (WidgetTester tester) async {
    await _pump(tester, RankProfileCard(status: _status(), onTap: () {}));
    expect(find.text('4 wk'), findsOneWidget);
    expect(find.text('9 wk'), findsOneWidget);
    expect(find.text('14'), findsOneWidget);
    expect(find.text('Longest streak'), findsOneWidget);
    expect(find.text('120 XP · 120 to Committed'), findsOneWidget);
  });

  group('saved workout XP card', () {
    WorkoutXp xp({required int effort, bool counted = true}) => WorkoutXp.tryParse(
          <String, dynamic>{
            'counted': counted,
            'awarded': counted ? 7 + effort + 2 : 0,
            'breakdown': <Map<String, dynamic>>[
              <String, dynamic>{'kind': 'planned_workout', 'xp': counted ? 5 : 0},
              <String, dynamic>{'kind': 'all_sets', 'xp': counted ? 2 : 0},
              <String, dynamic>{'kind': 'effort_in_range', 'xp': counted ? effort : 0},
              <String, dynamic>{'kind': 'personal_record', 'xp': counted ? 2 : 0},
              <String, dynamic>{'kind': 'cardio', 'xp': 0},
            ],
            'xp_total': 129,
            'rank': playerRankLadder[1].toJson(),
            'next_rank': playerRankLadder[2].toJson(),
            'xp_into_rank': 49,
            'xp_for_next_rank': 160,
            'rank_up': null,
          },
        )!;

    testWidgets('lists every rule with +0 lines and the over-target note',
        (WidgetTester tester) async {
      await _pump(tester, WorkoutXpCard(xp: xp(effort: 0)));
      expect(find.text('+9 XP'), findsOneWidget);
      expect(find.text('Effort in the target range'), findsOneWidget);
      expect(find.text('+0'), findsNWidgets(2));
      expect(find.textContaining('never have to push harder'), findsOneWidget);
      expect(find.text('Weekly streak: counts at the end of the week'), findsOneWidget);
      expect(find.text('111 to Committed'), findsOneWidget);
    });

    testWidgets('effort in range shows no over-target note', (WidgetTester tester) async {
      await _pump(tester, WorkoutXpCard(xp: xp(effort: 1)));
      expect(find.text('+10 XP'), findsOneWidget);
      expect(find.textContaining('never have to push harder'), findsNothing);
    });

    testWidgets('a second workout that day explains why it earned nothing',
        (WidgetTester tester) async {
      await _pump(tester, WorkoutXpCard(xp: xp(effort: 0, counted: false)));
      expect(find.text('+0 XP'), findsOneWidget);
      expect(find.textContaining('Only one workout a day earns XP'), findsOneWidget);
      expect(find.text('Planned workout completed'), findsNothing);
    });
  });

  group('rank up', () {
    for (final String language in <String>['en', 'ar']) {
      for (final bool dark in <bool>[false, true]) {
        for (final Size size in const <Size>[Size(390, 844), Size(1280, 900)]) {
          testWidgets(
              'lays out in $language, ${dark ? 'dark' : 'light'}, ${size.width.toInt()} px',
              (WidgetTester tester) async {
            await _pump(
              tester,
              SizedBox(
                height: size.height,
                child: RankUpScreen(
                  rank: playerRankLadder[2],
                  status: _status(xpTotal: 242, rankId: 'committed'),
                  onSeeAllRanks: () {},
                ),
              ),
              language: language,
              dark: dark,
              size: size,
            );
            await tester.pump(const Duration(milliseconds: 700));
            expect(tester.takeException(), isNull);
            expect(find.text(language == 'ar' ? 'ملتزم' : 'Committed'), findsOneWidget);
            expect(find.text(language == 'ar' ? 'رتبة جديدة' : 'New rank'), findsOneWidget);
          });
        }
      }
    }

    testWidgets('with reduced motion the badge is fully shown on the first frame',
        (WidgetTester tester) async {
      await _pump(
        tester,
        SizedBox(
          height: 844,
          child: RankUpScreen(
            rank: playerRankLadder[2],
            status: _status(xpTotal: 242, rankId: 'committed'),
            onSeeAllRanks: () {},
          ),
        ),
        disableAnimations: true,
      );
      final Opacity badge = tester.widget<Opacity>(find
          .ancestor(of: find.byIcon(Icons.shield), matching: find.byType(Opacity))
          .first);
      expect(badge.opacity, 1);
    });
  });

  testWidgets('coach chips show rank and streak, paused and none-yet states',
      (WidgetTester tester) async {
    CoachRosterEntry entry({int? streak, bool? paused}) => CoachRosterEntry(
          assignmentId: 'a',
          playerUsername: 'sara',
          startedAt: '2026-11-01',
          status: 'active',
          rank: playerRankLadder[3],
          weeklyStreak: streak,
          weekPaused: paused,
        );
    await _pump(tester, Column(children: <Widget>[
      CoachRankChips(entry: entry(streak: 11, paused: false)),
      CoachRankChips(entry: entry(streak: 2, paused: true)),
      CoachRankChips(entry: entry(streak: 0, paused: false)),
    ]));
    expect(find.text('Dedicated'), findsNWidgets(3));
    expect(find.text('11-wk streak'), findsOneWidget);
    expect(find.text('Streak paused'), findsOneWidget);
    expect(find.text('No streak yet'), findsOneWidget);
  });

  test('the roster entry and status parse XP fields and tolerate old payloads', () {
    final CoachRosterEntry old = CoachRosterEntry.fromJson(<String, dynamic>{
      'assignment_id': 'a',
    });
    expect(old.rank, isNull);
    expect(old.weeklyStreak, isNull);
    final TrainingStatus cached = TrainingStatus.fromJson(<String, dynamic>{
      'weekly_streak': 2,
      'week_start': '2026-11-21',
      'week_done': 1,
      'week_target': 3,
      'mayos_workouts': 5,
      'next_checkpoint': 10,
      'workouts_to_next': 5,
    });
    expect(cached.rank, isNull);
    expect(cached.xpTotal, 0);
    final TrainingStatus roundTrip = TrainingStatus.fromJson(_status().toJson());
    expect(roundTrip.rank, playerRankLadder[1]);
    expect(roundTrip.longestStreak, 9);
    expect(roundTrip.thisWeekDone, isTrue);
  });

  test('a workout extends the projected Weekly streak only as the week\'s first', () {
    final DateTime saturday = DateTime(2026, 11, 21, 10);
    WeeklyStreakSummaryLine line(TrainingStatus status) =>
        projectTrainingStatusSummary(status: status, drafts: const <WorkoutDraft>[], now: saturday)
            .whereType<WeeklyStreakSummaryLine>()
            .single;
    expect(line(_status(weeklyStreak: 3, thisWeekDone: false)).weeks, 4);
    expect(line(_status(weeklyStreak: 4, thisWeekDone: true)).weeks, 4);
  });
}
