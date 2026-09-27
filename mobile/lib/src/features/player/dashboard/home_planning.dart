import '../../../core/models.dart';

/// Pure planning rules for the Home "next session" block (#53).
///
/// Kept free of widgets and providers so the mapping can be unit-tested.
///
/// The device wall clock is the source of "today"; the schedule's timezone is
/// informational only, because the app carries no IANA timezone database to
/// convert the device's wall clock into a different zone. When the device and
/// schedule zones match (the common case) this is exact.

/// The editorial greeting for the hour, without inventing a name. No account
/// field exposes a display/preferred name, so Home greets neutrally.
String greetingFor(DateTime now) {
  final int hour = now.hour;
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}

/// The identity and performed date of one logged workout, used to derive the
/// next program day from data the app already has: the latest committed session
/// from the ledger and any queued/committed local drafts. No weekday→program-day
/// mapping is invented: ordered program days are not tied to weekdays.
class TrainedDay {
  const TrainedDay({
    this.dayOrder,
    this.dayName,
    required this.performedDate,
    required this.updatedAt,
  });

  /// The ledger `day_order` when the source carries one (drafts do; the
  /// committed-session read does not, so [dayName] is used instead).
  final int? dayOrder;

  /// The day name written at commit (`split_name` / draft `day_name`).
  final String? dayName;

  final String performedDate;
  final String updatedAt;

  /// Builds the trained-day view from an existing workout draft.
  factory TrainedDay.fromDraft(WorkoutDraft draft) => TrainedDay(
        dayOrder: draft.dayOrder,
        dayName: draft.dayName,
        performedDate: draft.performedDate,
        updatedAt: draft.updatedAt,
      );

  /// Builds the trained-day view from the server's latest committed session.
  factory TrainedDay.fromLatestSession(LatestSession session) => TrainedDay(
        dayOrder: session.dayOrder,
        dayName: session.splitName,
        performedDate: session.sessionDate,
        // The ledger exposes no update timestamp; the performed date is the only
        // tiebreak available, and a same-day draft wins with its own.
        updatedAt: session.sessionDate,
      );
}

/// The next expected training weekday (1=Mon..7=Sun) at or after [now]'s
/// weekday, wrapping to the following week. [weekdays] must be non-empty and
/// sorted ascending.
int nextScheduledWeekday(List<int> weekdays, DateTime now) {
  final int today = now.weekday;
  for (final int day in weekdays) {
    if (day >= today) {
      return day;
    }
  }
  return weekdays.first;
}

/// The label for the next-session block: a bare "Next session" without a weekly
/// schedule, or "Next session · Tue" once a schedule exists.
///
/// The label is independent of which program day is next.
String nextSessionLabel(TrainingSchedule? schedule, DateTime now) {
  final List<int> sorted = _sortedWeekdays(schedule);
  if (sorted.isEmpty) {
    return 'Next session';
  }
  final int next = nextScheduledWeekday(sorted, now);
  return 'Next session · ${weekdayLabels[next - 1]}';
}

/// The ordered program day after the one most recently trained, wrapping to
/// Day 1 after the last day.
///
/// The last trained day is the latest of [trained] (the server's committed
/// session and local drafts) by performed date. It is matched to the program by
/// `day_order` when present, else by day name (case-insensitive). When nothing
/// matches — a program change, or no history at all — Day 1 is the honest
/// starting point. Days are ordered by `day_order`, not by weekday.
ProgramDay? selectNextDay(
  TrainingProgram program,
  Iterable<TrainedDay> trained,
) {
  if (program.days.isEmpty) {
    return null;
  }
  final List<ProgramDay> ordered = List<ProgramDay>.of(program.days)
    ..sort((ProgramDay a, ProgramDay b) => a.dayOrder.compareTo(b.dayOrder));
  final TrainedDay? last = latestTrainedDay(trained);
  if (last == null) {
    return ordered.first;
  }
  final int index = _indexOfTrainedDay(ordered, last);
  if (index < 0) {
    // The last trained day is no longer part of the program; restart at Day 1.
    return ordered.first;
  }
  return ordered[(index + 1) % ordered.length];
}

int _indexOfTrainedDay(List<ProgramDay> ordered, TrainedDay trained) {
  final int? order = trained.dayOrder;
  if (order != null) {
    final int byOrder =
        ordered.indexWhere((ProgramDay day) => day.dayOrder == order);
    if (byOrder >= 0) {
      return byOrder;
    }
  }
  final String? name = trained.dayName;
  if (name != null && name.trim().isNotEmpty) {
    final String needle = name.trim().toLowerCase();
    return ordered.indexWhere(
        (ProgramDay day) => day.dayName.trim().toLowerCase() == needle);
  }
  return -1;
}

/// The most recently performed trained day, or null when [trained] is empty.
/// Later performed dates win; equal dates fall back to the later `updatedAt`, so
/// a same-day double session still progresses.
TrainedDay? latestTrainedDay(Iterable<TrainedDay> trained) {
  TrainedDay? latest;
  for (final TrainedDay day in trained) {
    if (latest == null || _isAfter(day, latest)) {
      latest = day;
    }
  }
  return latest;
}

/// The `day_order` of the most recently performed trained day, or null when
/// [trained] is empty or the latest source carries no order.
int? lastTrainedDayOrder(Iterable<TrainedDay> trained) =>
    latestTrainedDay(trained)?.dayOrder;

bool _isAfter(TrainedDay candidate, TrainedDay current) {
  final int byDate = candidate.performedDate.compareTo(current.performedDate);
  if (byDate != 0) {
    return byDate > 0;
  }
  return candidate.updatedAt.compareTo(current.updatedAt) > 0;
}

List<int> _sortedWeekdays(TrainingSchedule? schedule) {
  final List<int>? raw = schedule?.current?.weekdays;
  if (raw == null || raw.isEmpty) {
    return const <int>[];
  }
  return List<int>.of(raw)..sort();
}
