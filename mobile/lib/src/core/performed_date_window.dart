/// The one place the performed-date window is derived (ADR 020/035).
///
/// The window is capture-anchored, matching the server: a performed date may be
/// up to [maxBackdateDays] before the capture's local date, and never after it,
/// nor after the device's local today. Both the offline workout logger and the
/// drafts screen use this instead of duplicating the bounds.
library;

/// Performed dates may be entered or corrected up to three days back (ADR 020).
const int maxBackdateDays = 3;

/// The inclusive [first]..[last] window a performed date may fall in.
class PerformedDateWindow {
  const PerformedDateWindow({required this.first, required this.last});

  final DateTime first;
  final DateTime last;

  bool contains(DateTime value) =>
      !value.isBefore(first) && !value.isAfter(last);

  /// Returns [value] clamped into the window, preserving the time of day.
  DateTime clamp(DateTime value) {
    if (value.isAfter(last)) {
      return value.copyWith(year: last.year, month: last.month, day: last.day);
    }
    if (value.isBefore(first)) {
      return value.copyWith(
          year: first.year, month: first.month, day: first.day);
    }
    return value;
  }
}

/// A calendar date built from [year]/[month]/[day], normalising out-of-range
/// day-of-month values without [Duration] arithmetic (DST-safe).
DateTime _calendarDate(int year, int month, int day) =>
    DateTime(year, month, day);

/// The capture-anchored window: `captureLocalDate - maxBackdateDays` through
/// `min(captureLocalDate, deviceToday)`.
///
/// For a new entry there is no earlier capture, so pass `captureAt: null` (or
/// omit it): the anchor is the device's local today and the window is unchanged
/// from before. A draft edit or a synced correction passes the draft's capture
/// instant, which is converted to device-local components first.
PerformedDateWindow performedDateWindow({DateTime? now, DateTime? captureAt}) {
  final DateTime moment = now ?? DateTime.now();
  final DateTime deviceToday =
      _calendarDate(moment.year, moment.month, moment.day);
  final DateTime anchor = (captureAt ?? moment).toLocal();
  final DateTime captureDate =
      _calendarDate(anchor.year, anchor.month, anchor.day);
  final DateTime last =
      captureDate.isBefore(deviceToday) ? captureDate : deviceToday;
  final DateTime first =
      _calendarDate(anchor.year, anchor.month, anchor.day - maxBackdateDays);
  return PerformedDateWindow(first: first, last: last);
}

/// Formats a date as a strict `YYYY-MM-DD` performed date.
String formatPerformedDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';
