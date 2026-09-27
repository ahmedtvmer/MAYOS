// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// In-memory stub of everything the Coach mode shell needs. Field names mirror
// the real API models (CoachRosterEntry, CoachAlert, ProgramRequest, CheckIn)
// so the prototype shows only data the backend can already supply, except
// where a field is marked GAP.

import 'package:flutter/foundation.dart';

enum ProtoMode { player, coach }

class ProtoPlayer {
  ProtoPlayer({
    required this.assignmentId,
    required this.username,
    required this.startedAt,
    required this.missedStreak,
    required this.nextFollowUpOn,
    required this.lastWorkoutOn,
    required this.programName,
    required this.prs,
    required this.recentSessions,
  });

  final String assignmentId;
  final String username;
  final String startedAt;
  int missedStreak;
  String? nextFollowUpOn;

  /// GAP: the roster payload has no last-workout date; the summary endpoint does.
  final String? lastWorkoutOn;
  final String programName;
  final List<(String, String)> prs; // (exercise, "140 kg · e1RM 152")
  final List<(String, String, String)> recentSessions; // (date, day, summary)
}

class ProtoAlert {
  ProtoAlert({
    required this.id,
    required this.assignmentId,
    required this.kind,
    required this.title,
    required this.detail,
    required this.createdAt,
    this.state = 'new',
  });

  final String id;
  final String assignmentId;

  /// missed_day | follow_up_due | deload | performance_regression
  final String kind;
  final String title;
  final String detail;
  final String createdAt;
  String state; // new | acknowledged | resolved
}

class ProtoRequest {
  ProtoRequest({
    required this.id,
    required this.assignmentId,
    required this.kind,
    required this.dayName,
    required this.fromExercise,
    required this.toExercise,
    required this.reason,
    required this.createdAt,
    this.status = 'pending',
  });

  final String id;
  final String assignmentId;
  final String kind; // exercise_substitution | split_change
  final String? dayName;
  final String? fromExercise;
  final String? toExercise; // or "4 days · upper/lower" for split_change
  final String reason;
  final String createdAt;
  String status; // pending | applied | declined | stale
  String? response;
}

class ProtoCheckIn {
  ProtoCheckIn(this.assignmentId, this.on, this.channel, this.note);
  final String assignmentId;
  final String on;
  final String channel; // call | message | in_person | other
  final String? note;
}

class ProtoCoachState extends ChangeNotifier {
  ProtoCoachState() {
    reset();
  }

  ProtoMode mode = ProtoMode.coach;

  /// Persisted on device in the real app: the app reopens in this mode.
  ProtoMode lastMode = ProtoMode.coach;

  /// A coach reaches Coach mode without player onboarding (map #102).
  bool playerOnboarded = false;
  late List<ProtoPlayer> players;
  late List<ProtoAlert> alerts;
  late List<ProtoRequest> requests;
  late List<ProtoCheckIn> checkIns;
  final List<String> log = <String>[];

  void reset() {
    mode = ProtoMode.coach;
    lastMode = ProtoMode.coach;
    playerOnboarded = false;
    players = <ProtoPlayer>[
      ProtoPlayer(
        assignmentId: 'a1',
        username: 'karim_lifts',
        startedAt: '2026-06-02',
        missedStreak: 3,
        nextFollowUpOn: '2026-09-25',
        lastWorkoutOn: '2026-09-20',
        programName: 'Upper/Lower · 4 days',
        prs: <(String, String)>[
          ('Barbell Back Squat', '140 kg · e1RM 158'),
          ('Bench Press', '100 kg · e1RM 112'),
        ],
        recentSessions: <(String, String, String)>[
          ('2026-09-20', 'Lower A', '6 exercises · 21 sets · 1 PR'),
          ('2026-09-18', 'Upper A', '6 exercises · 20 sets'),
        ],
      ),
      ProtoPlayer(
        assignmentId: 'a2',
        username: 'sara.m',
        startedAt: '2026-07-14',
        missedStreak: 0,
        nextFollowUpOn: '2026-09-28',
        lastWorkoutOn: '2026-09-26',
        programName: 'Full body · 3 days',
        prs: <(String, String)>[('Romanian Deadlift', '85 kg · e1RM 101')],
        recentSessions: <(String, String, String)>[
          ('2026-09-26', 'Day B', '5 exercises · 16 sets · 2 PRs'),
          ('2026-09-24', 'Day A', '5 exercises · 15 sets'),
        ],
      ),
      ProtoPlayer(
        assignmentId: 'a3',
        username: 'omar_h',
        startedAt: '2026-08-01',
        missedStreak: 1,
        nextFollowUpOn: null,
        lastWorkoutOn: '2026-09-24',
        programName: 'Push/Pull/Legs · 6 days',
        prs: <(String, String)>[('Overhead Press', '62.5 kg · e1RM 70')],
        recentSessions: <(String, String, String)>[
          ('2026-09-24', 'Pull', '6 exercises · 19 sets'),
        ],
      ),
      ProtoPlayer(
        assignmentId: 'a4',
        username: 'lina.fit',
        startedAt: '2026-09-10',
        missedStreak: 0,
        nextFollowUpOn: '2026-10-03',
        lastWorkoutOn: '2026-09-27',
        programName: 'Upper/Lower · 4 days',
        prs: <(String, String)>[],
        recentSessions: <(String, String, String)>[
          ('2026-09-27', 'Upper B', '6 exercises · 18 sets'),
        ],
      ),
      ProtoPlayer(
        assignmentId: 'a5',
        username: 'youssef99',
        startedAt: '2026-05-20',
        missedStreak: 0,
        nextFollowUpOn: '2026-09-27',
        lastWorkoutOn: '2026-09-26',
        programName: 'Full body · 3 days',
        prs: <(String, String)>[('Deadlift', '180 kg · e1RM 196')],
        recentSessions: <(String, String, String)>[
          ('2026-09-26', 'Day C', '5 exercises · 15 sets'),
        ],
      ),
    ];
    alerts = <ProtoAlert>[
      ProtoAlert(
          id: 'al1',
          assignmentId: 'a1',
          kind: 'missed_day',
          title: 'Missed 3 expected days',
          detail: 'Since 2026-09-22 · last missed 2026-09-26',
          createdAt: '2026-09-26'),
      ProtoAlert(
          id: 'al2',
          assignmentId: 'a1',
          kind: 'follow_up_due',
          title: 'Follow-up overdue',
          detail: 'Due 2026-09-25 · last check-in 2026-09-11',
          createdAt: '2026-09-25'),
      ProtoAlert(
          id: 'al3',
          assignmentId: 'a3',
          kind: 'deload',
          title: 'Deload suggested',
          detail: 'Readiness avg 2.1 · volume ×0.6 · cap RPE 7',
          createdAt: '2026-09-26',
          state: 'acknowledged'),
      ProtoAlert(
          id: 'al4',
          assignmentId: 'a5',
          kind: 'performance_regression',
          title: 'Regression on Deadlift',
          detail: 'e1RM down 6% over 3 sessions',
          createdAt: '2026-09-27'),
      ProtoAlert(
          id: 'al5',
          assignmentId: 'a5',
          kind: 'follow_up_due',
          title: 'Follow-up due today',
          detail: 'Due 2026-09-27 · last check-in 2026-09-13',
          createdAt: '2026-09-27'),
    ];
    requests = <ProtoRequest>[
      ProtoRequest(
          id: 'r1',
          assignmentId: 'a2',
          kind: 'exercise_substitution',
          dayName: 'Day A',
          fromExercise: 'Barbell Back Squat',
          toExercise: 'Hack Squat',
          reason: 'Knee pain at the bottom of the squat since last week.',
          createdAt: '2026-09-26'),
      ProtoRequest(
          id: 'r2',
          assignmentId: 'a3',
          kind: 'split_change',
          dayName: null,
          fromExercise: null,
          toExercise: '4 days · Upper/Lower',
          reason: 'New job, can only train 4 days now.',
          createdAt: '2026-09-25'),
      ProtoRequest(
          id: 'r3',
          assignmentId: 'a1',
          kind: 'exercise_substitution',
          dayName: 'Upper A',
          fromExercise: 'Dips',
          toExercise: 'Close-Grip Bench Press',
          reason: 'Shoulder discomfort.',
          createdAt: '2026-09-12',
          status: 'applied')
        ..response = 'Swapped. Keep the same rep range.',
    ];
    checkIns = <ProtoCheckIn>[
      ProtoCheckIn('a1', '2026-09-11', 'call', 'Travelling next week.'),
      ProtoCheckIn('a2', '2026-09-21', 'message', 'Sleep improving.'),
      ProtoCheckIn('a5', '2026-09-13', 'in_person', null),
    ];
    log
      ..clear()
      ..add('reset: opened in Coach mode (last used)');
    notifyListeners();
  }

  ProtoPlayer player(String assignmentId) =>
      players.firstWhere((ProtoPlayer p) => p.assignmentId == assignmentId);

  List<ProtoAlert> openAlerts([String? assignmentId]) => alerts
      .where((ProtoAlert a) =>
          a.state != 'resolved' &&
          (assignmentId == null || a.assignmentId == assignmentId))
      .toList();

  List<ProtoRequest> pendingRequests([String? assignmentId]) => requests
      .where((ProtoRequest r) =>
          r.status == 'pending' &&
          (assignmentId == null || r.assignmentId == assignmentId))
      .toList();

  List<ProtoRequest> requestsOf(String assignmentId) => requests
      .where((ProtoRequest r) => r.assignmentId == assignmentId)
      .toList();

  List<ProtoCheckIn> checkInsOf(String assignmentId) => checkIns
      .where((ProtoCheckIn c) => c.assignmentId == assignmentId)
      .toList();

  bool followUpDue(ProtoPlayer p) =>
      p.nextFollowUpOn != null && p.nextFollowUpOn!.compareTo(today) <= 0;

  /// Attention score used to sort the roster: most urgent first.
  int attention(ProtoPlayer p) =>
      openAlerts(p.assignmentId)
              .where((ProtoAlert a) => a.state == 'new')
              .length *
          3 +
      pendingRequests(p.assignmentId).length * 3 +
      p.missedStreak * 2 +
      (followUpDue(p) ? 2 : 0);

  List<ProtoPlayer> rosterByAttention() =>
      <ProtoPlayer>[...players]..sort((ProtoPlayer a, ProtoPlayer b) {
          final int d = attention(b).compareTo(attention(a));
          return d != 0 ? d : a.username.compareTo(b.username);
        });

  void switchMode(ProtoMode next) {
    if (next == mode) return;
    mode = next;
    lastMode = next;
    log.insert(0, 'switch → ${next.name} (remembered; app reopens here)');
    notifyListeners();
  }

  void finishPlayerOnboarding() {
    playerOnboarded = true;
    log.insert(0, 'player onboarding finished (deferred until first Player mode)');
    notifyListeners();
  }

  void acknowledge(ProtoAlert a) {
    a.state = 'acknowledged';
    log.insert(0, 'alert ${a.id} acknowledged');
    notifyListeners();
  }

  void resolve(ProtoAlert a) {
    a.state = 'resolved';
    log.insert(0, 'alert ${a.id} resolved');
    notifyListeners();
  }

  void apply(ProtoRequest r, String? response) {
    r
      ..status = 'applied'
      ..response = response;
    log.insert(0, 'request ${r.id} applied${response == null ? '' : ' · "$response"'}');
    notifyListeners();
  }

  void decline(ProtoRequest r, String? response) {
    r
      ..status = 'declined'
      ..response = response;
    log.insert(0, 'request ${r.id} declined${response == null ? '' : ' · "$response"'}');
    notifyListeners();
  }

  void addCheckIn(ProtoPlayer p, String channel, String? note) {
    checkIns.insert(0, ProtoCheckIn(p.assignmentId, today, channel, note));
    // A check-in schedules the next follow-up and clears a due one (ADR 031).
    p.nextFollowUpOn = '2026-10-11';
    for (final ProtoAlert a in alerts) {
      if (a.assignmentId == p.assignmentId && a.kind == 'follow_up_due') {
        a.state = 'resolved';
      }
    }
    log.insert(0, 'check-in logged for ${p.username} ($channel) → next follow-up 2026-10-11');
    notifyListeners();
  }
}

const String today = '2026-09-27';

final ProtoCoachState protoCoach = ProtoCoachState();
