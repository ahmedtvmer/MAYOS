import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../providers.dart';

final Provider<CoachRosterLoader> coachRosterLoaderProvider =
    Provider<CoachRosterLoader>(CoachRosterLoader.new);

class CoachRosterLoader {
  CoachRosterLoader(this._ref);

  final Ref _ref;
  Future<List<CoachRosterEntry>?>? _inFlight;
  String? _inFlightAccountId;
  int _generation = 0;

  Future<List<CoachRosterEntry>?> load() {
    final List<CoachRosterEntry>? cached =
        _ref.read(coachRosterEntriesProvider);
    if (cached != null &&
        _ref.read(coachRosterEntriesRevisionProvider) ==
            _ref.read(coachRosterRevisionProvider)) {
      _clearUnlessAssigned(cached);
      return Future<List<CoachRosterEntry>?>.value(cached);
    }
    return refresh();
  }

  Future<List<CoachRosterEntry>?> refresh() {
    final String? accountId =
        _ref.read(authControllerProvider).session?.account.accountId;
    final Future<List<CoachRosterEntry>?>? pending = _inFlight;
    if (pending != null && _inFlightAccountId == accountId) return pending;
    if (pending != null) {
      _generation++;
      _inFlight = null;
    }

    final Future<List<CoachRosterEntry>?> fetch =
        _fetchCurrentRoster(accountId, _generation);
    _inFlight = fetch;
    _inFlightAccountId = accountId;
    return fetch.whenComplete(() {
      if (identical(_inFlight, fetch)) {
        _inFlight = null;
        _inFlightAccountId = null;
      }
    });
  }

  Future<List<CoachRosterEntry>?> _fetchCurrentRoster(
    String? accountId,
    int generation,
  ) async {
    while (true) {
      final int revision = _ref.read(coachRosterRevisionProvider);
      final List<CoachRosterEntry> assignments =
          await _ref.read(apiClientProvider).coachAssignments();
      final String? currentAccountId =
          _ref.read(authControllerProvider).session?.account.accountId;
      if (accountId != currentAccountId) return null;
      if (generation != _generation) return null;
      if (revision != _ref.read(coachRosterRevisionProvider)) continue;
      publish(assignments);
      return assignments;
    }
  }

  void publish(List<CoachRosterEntry> assignments) {
    _generation++;
    _ref.read(coachRosterEntriesProvider.notifier).state = assignments;
    _ref.read(coachRosterEntriesRevisionProvider.notifier).state =
        _ref.read(coachRosterRevisionProvider);
    _clearUnlessAssigned(assignments);
  }

  void _clearUnlessAssigned(List<CoachRosterEntry> assignments) {
    _ref.read(coachAssistantControllerProvider.notifier).clearUnlessAssigned(
          assignments.map((CoachRosterEntry row) => row.assignmentId),
        );
  }
}
