import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/providers.dart';

// Share one clock between roster urgency fixtures and the widget (#570), so
// midnight or a host clock change during a run cannot make them disagree.
final DateTime coachRosterNow = DateTime(2026, 10, 29, 12);
final String coachRosterToday = isoDateOf(coachRosterNow);
final String coachRosterYesterday =
    isoDateOf(coachRosterNow.subtract(const Duration(days: 1)));
final Override coachRosterClockOverride =
    clockProvider.overrideWithValue(() => coachRosterNow);
