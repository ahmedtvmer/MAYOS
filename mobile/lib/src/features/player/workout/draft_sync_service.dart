import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/workout_storage.dart';

/// Exponential backoff for network/timeout/5xx failures: 30s, 60s, 2m, 5m,
/// capped at 15m; reset on success or a manual retry (ADR 020/033).
const List<Duration> _backoff = <Duration>[
  Duration(seconds: 30),
  Duration(seconds: 60),
  Duration(minutes: 2),
  Duration(minutes: 5),
  Duration(minutes: 15),
];

Duration _backoffFor(int attempt) =>
    _backoff[attempt.clamp(1, _backoff.length) - 1];

/// Processes the logged-in account's drafts oldest-first: reconcile a lost
/// response through the status lookup, otherwise commit; keep network/5xx
/// failures pending for a later retry, and surface 4xx refusals for the player
/// to retry or discard (ADR 020/033).
///
/// Every store mutation is a lock-guarded read-modify-write of a single draft
/// by client session id, so a save/discard/retry racing an in-flight sync
/// pass is never lost or resurrected. A sync pass is bound to the account id
/// and a generation token it started with: [stop] (logout/account switch)
/// invalidates that token, so an abandoned pass makes no further store writes
/// or network calls under a different account's credentials.
class DraftSyncService extends ChangeNotifier {
  DraftSyncService({
    required ApiClient api,
    required DraftStore store,
    this.retryInterval = const Duration(seconds: 60),
    DateTime Function()? now,
  })  : _api = api,
        _store = store,
        _now = now ?? DateTime.now;

  final ApiClient _api;
  final DraftStore _store;
  final Duration? retryInterval;
  final DateTime Function() _now;

  String? _accountId;
  int _generation = 0;
  List<WorkoutDraft> _drafts = <WorkoutDraft>[];
  bool _syncing = false;
  bool _resyncRequested = false;
  Timer? _timer;
  Future<void> _mutex = Future<void>.value();

  String? get accountId => _accountId;

  List<WorkoutDraft> get drafts => List<WorkoutDraft>.unmodifiable(_drafts);

  bool get isSyncing => _syncing;

  /// True when the last read of this account's storage found an unreadable
  /// value that was quarantined rather than discarded (ADR 020/033).
  bool get storageQuarantined {
    final String? id = _accountId;
    return id != null && _store.isQuarantined(id);
  }

  /// How many drafts for an account are not yet committed.
  Future<int> unsyncedCountFor(String accountId) async {
    final List<WorkoutDraft> drafts = await _store.read(accountId);
    return drafts.where((WorkoutDraft draft) => draft.isUnsynced).length;
  }

  /// Begins watching an account: loads drafts, starts the periodic retry, and
  /// kicks an immediate sync. Bound to a fresh generation token, so any pass
  /// still running for a previous account abandons itself.
  void startFor(String accountId, {bool syncImmediately = true}) {
    _generation++;
    _accountId = accountId;
    _startTimer();
    scheduleMicrotask(() {
      unawaited(refresh());
      if (syncImmediately) {
        unawaited(syncNow());
      }
    });
  }

  /// Ends the current account's pass (logout/account switch): invalidates the
  /// generation token so an in-flight pass makes no further writes or
  /// network calls, and clears the in-memory drafts (never the stored ones).
  void stop() {
    _generation++;
    _accountId = null;
    _timer?.cancel();
    _timer = null;
    _drafts = <WorkoutDraft>[];
    notifyListeners();
  }

  /// Stops the periodic foreground timer (app backgrounded) without ending
  /// the account's session.
  void pauseForeground() {
    _timer?.cancel();
    _timer = null;
  }

  /// Restarts the periodic timer and runs an immediate pass (app resumed).
  void resumeForeground() {
    if (_accountId == null) {
      return;
    }
    _startTimer();
    unawaited(syncNow());
  }

  void _startTimer() {
    _timer?.cancel();
    final Duration? interval = retryInterval;
    if (interval == null) {
      return;
    }
    _timer = Timer.periodic(interval, (_) => unawaited(syncNow()));
  }

  Future<void> refresh() async {
    final String? id = _accountId;
    if (id == null) {
      return;
    }
    _drafts = await _store.read(id);
    notifyListeners();
  }

  /// Runs [action] to completion before any later-queued mutation starts, so
  /// two mutations (a save racing a sync's status update, for instance) can
  /// never interleave into a lost or stale write.
  Future<T> _locked<T>(Future<T> Function() action) {
    final Future<void> previous = _mutex;
    final Completer<void> completer = Completer<void>();
    _mutex = completer.future;
    return previous.then((_) => action()).whenComplete(completer.complete);
  }

  /// Reads the latest list, applies [mutate] to it, and writes the result
  /// back — all under the lock, so this is always a read-modify-write of
  /// current storage, never a write of a snapshot taken before an await.
  Future<List<WorkoutDraft>> _mutateDrafts(
    String accountId,
    List<WorkoutDraft> Function(List<WorkoutDraft> current) mutate,
  ) {
    return _locked(() async {
      final List<WorkoutDraft> current = await _store.read(accountId);
      final List<WorkoutDraft> next = mutate(current);
      await _store.write(accountId, next);
      if (_accountId == accountId) {
        _drafts = next;
        notifyListeners();
      }
      return next;
    });
  }

  /// Persists a draft first (never sent directly), then attempts a sync.
  Future<void> saveDraft(WorkoutDraft draft) async {
    await _mutateDrafts(draft.accountId, (List<WorkoutDraft> current) {
      return <WorkoutDraft>[
        for (final WorkoutDraft existing in current)
          if (existing.clientSessionId != draft.clientSessionId) existing,
        draft,
      ];
    });
    await syncNow();
  }

  /// Removes one draft from storage (explicit discard).
  Future<void> discardDraft(String clientSessionId) async {
    final String? id = _accountId;
    if (id == null) {
      return;
    }
    await _mutateDrafts(
        id,
        (List<WorkoutDraft> current) => current
            .where((WorkoutDraft draft) =>
                draft.clientSessionId != clientSessionId)
            .toList(growable: false));
  }

  /// Removes every draft for an account (logout's explicit discard choice).
  Future<void> discardAllForAccount(String accountId) async {
    await _mutateDrafts(accountId, (_) => <WorkoutDraft>[]);
  }

  /// Explicitly retries a needs-attention (or backed-off) draft: resets its
  /// status and backoff, then requeues a sync pass.
  Future<void> retryDraft(String clientSessionId) async {
    final String? id = _accountId;
    if (id == null) {
      return;
    }
    await _mutateDrafts(id, (List<WorkoutDraft> current) {
      return <WorkoutDraft>[
        for (final WorkoutDraft draft in current)
          if (draft.clientSessionId == clientSessionId)
            draft.copyWith(
              status: DraftStatus.pending,
              lastError: null,
              clearLastError: true,
              attempt: 0,
              clearNextAttempt: true,
              updatedAt: _iso(),
            )
          else
            draft,
      ];
    });
    await syncNow();
  }

  /// Edits an unsynced draft's performed date in local storage (ADR 020/035).
  ///
  /// Returns false when the draft is missing or already committed; a synced
  /// session must be corrected on the service instead.
  Future<bool> updatePendingPerformedDate(
      String clientSessionId, String performedDate) async {
    final String? id = _accountId;
    if (id == null) {
      return false;
    }
    bool updated = false;
    await _mutateDrafts(id, (List<WorkoutDraft> current) {
      final List<WorkoutDraft> next = <WorkoutDraft>[];
      for (final WorkoutDraft draft in current) {
        if (draft.clientSessionId == clientSessionId && !draft.isSynced) {
          updated = true;
          next.add(
              draft.copyWith(performedDate: performedDate, updatedAt: _iso()));
        } else {
          next.add(draft);
        }
      }
      return next;
    });
    return updated;
  }

  /// Corrects a committed session's performed date on the service (ADR 035).
  ///
  /// Throws [ApiException] when offline or when the service refuses (400 out of
  /// window, 409 too old, 404 unknown), so the caller can show the message. On
  /// success the local draft reflects the corrected date and response.
  Future<WorkoutDraft> correctSyncedPerformedDate(
      String clientSessionId, String performedDate) async {
    final String? accountId = _accountId;
    if (accountId == null) {
      throw const ApiException('You are not signed in.');
    }
    final List<WorkoutDraft> current = await _store.read(accountId);
    final int index = current
        .indexWhere((WorkoutDraft d) => d.clientSessionId == clientSessionId);
    if (index < 0) {
      throw const ApiException('That workout is no longer available.');
    }
    final WorkoutDraft draft = current[index];
    final String? sessionId = draft.serverSessionId;
    if (!draft.isSynced || sessionId == null) {
      throw const ApiException('Only a synced workout can be corrected.');
    }
    final Map<String, dynamic> result =
        await _api.correctSessionPerformedDate(sessionId, performedDate);
    final WorkoutDraft corrected = draft.copyWith(
      performedDate: (result['session_date'] as String?) ?? performedDate,
      serverResponse: <String, dynamic>{
        ...?draft.serverResponse,
        ...result,
      },
      updatedAt: _iso(),
    );
    await _applyResult(accountId, corrected);
    return corrected;
  }

  /// Processes pending drafts for the logged-in account, oldest-first. If a
  /// pass is already running, marks that another is needed once it finishes
  /// rather than running two passes concurrently.
  Future<void> syncNow() async {
    final String? id = _accountId;
    if (id == null) {
      return;
    }
    if (_syncing) {
      _resyncRequested = true;
      return;
    }
    final int generation = _generation;
    _syncing = true;
    notifyListeners();
    try {
      do {
        _resyncRequested = false;
        await _runSyncPass(id, generation);
      } while (_resyncRequested && _stillCurrent(id, generation));
    } finally {
      _syncing = false;
      if (_stillCurrent(id, generation)) {
        _drafts = await _store.read(id);
      }
      notifyListeners();
    }
    // A login/account switch during this pass could not start its own pass
    // (``_syncing`` was true) and this pass's loop stops on the generation
    // change, so run the queued pass for the now-current account immediately
    // instead of leaving it until the next timer tick.
    if (_resyncRequested &&
        _accountId != null &&
        !_stillCurrent(id, generation)) {
      _resyncRequested = false;
      unawaited(syncNow());
    }
  }

  bool _stillCurrent(String accountId, int generation) =>
      _accountId == accountId && _generation == generation;

  Future<void> _runSyncPass(String accountId, int generation) async {
    await _pruneSynced(accountId);
    if (!_stillCurrent(accountId, generation)) {
      return;
    }
    final DateTime now = _now();
    final List<WorkoutDraft> snapshot = await _store.read(accountId);
    final List<WorkoutDraft> ordered = snapshot
        .where((WorkoutDraft draft) =>
            !draft.isSynced && !draft.needsAttention && _isDue(draft, now))
        .toList(growable: false)
      ..sort((WorkoutDraft a, WorkoutDraft b) =>
          a.capturedAt.compareTo(b.capturedAt));

    for (final WorkoutDraft draft in ordered) {
      if (!_stillCurrent(accountId, generation)) {
        return;
      }
      final WorkoutDraft? claimed =
          await _claimForSync(accountId, draft.clientSessionId);
      if (claimed == null || !_stillCurrent(accountId, generation)) {
        continue;
      }
      final WorkoutDraft resolved =
          await _syncOne(accountId, claimed, generation);
      if (!_stillCurrent(accountId, generation)) {
        return;
      }
      await _applyResult(accountId, resolved);
    }
  }

  bool _isDue(WorkoutDraft draft, DateTime now) {
    final String? next = draft.nextAttemptAt;
    if (next == null) {
      return true;
    }
    final DateTime? at = DateTime.tryParse(next);
    return at == null || !at.isAfter(now);
  }

  /// Marks a draft "syncing" under the lock and returns its pre-claim fields
  /// for the network call, or null if it was discarded or already resolved.
  Future<WorkoutDraft?> _claimForSync(
      String accountId, String clientSessionId) {
    return _locked(() async {
      final List<WorkoutDraft> current = await _store.read(accountId);
      final int index = current
          .indexWhere((WorkoutDraft d) => d.clientSessionId == clientSessionId);
      if (index < 0) {
        return null;
      }
      final WorkoutDraft draft = current[index];
      if (draft.isSynced || draft.needsAttention) {
        return null;
      }
      final List<WorkoutDraft> next = List<WorkoutDraft>.of(current);
      next[index] =
          draft.copyWith(status: DraftStatus.syncing, updatedAt: _iso());
      await _store.write(accountId, next);
      if (_accountId == accountId) {
        _drafts = next;
        notifyListeners();
      }
      return draft;
    });
  }

  /// Writes the resolved outcome back for that single draft, or drops it
  /// silently if the draft was discarded while the network call was in
  /// flight (it is never re-added, and never marked synced/needs-attention).
  Future<void> _applyResult(String accountId, WorkoutDraft resolved) {
    return _mutateDrafts(accountId, (List<WorkoutDraft> current) {
      final int index = current.indexWhere(
          (WorkoutDraft d) => d.clientSessionId == resolved.clientSessionId);
      if (index < 0) {
        return current;
      }
      final List<WorkoutDraft> next = List<WorkoutDraft>.of(current);
      next[index] = resolved;
      return next;
    });
  }

  /// True while [clientSessionId] is still present in [accountId]'s storage;
  /// false once discarded, so a network call already in flight when a discard
  /// lands is never followed by another one for the same draft.
  Future<bool> _isPresent(String accountId, String clientSessionId) {
    return _locked(() async {
      final List<WorkoutDraft> current = await _store.read(accountId);
      return current
          .any((WorkoutDraft d) => d.clientSessionId == clientSessionId);
    });
  }

  Future<bool> _canProceed(
      String accountId, String clientSessionId, int generation) async {
    return _stillCurrent(accountId, generation) &&
        await _isPresent(accountId, clientSessionId);
  }

  Future<WorkoutDraft> _syncOne(
      String accountId, WorkoutDraft draft, int generation) async {
    if (draft.accountId != accountId) {
      // Never send another account's draft under the current credentials.
      return draft;
    }
    try {
      if (!await _canProceed(accountId, draft.clientSessionId, generation)) {
        return draft;
      }
      final Map<String, dynamic>? existing =
          await _api.sessionByClientId(draft.clientSessionId);
      if (!await _canProceed(accountId, draft.clientSessionId, generation)) {
        return draft;
      }
      if (existing != null) {
        return _synced(draft, existing);
      }
      if (!await _canProceed(accountId, draft.clientSessionId, generation)) {
        return draft;
      }
      final WorkoutCommitResult result =
          await _api.commitWorkoutSession(draft.toCommitBody());
      if (result.created || result.statusCode == 200) {
        return _synced(draft, result.body);
      }
      return draft.copyWith(
        status: DraftStatus.needsReconciliation,
        lastError:
            'The service returned an unexpected status (${result.statusCode}).',
        updatedAt: _iso(),
      );
    } on ApiException catch (error) {
      if (_isTerminal(error)) {
        return draft.copyWith(
          status: DraftStatus.needsReconciliation,
          lastError: error.message,
          updatedAt: _iso(),
        );
      }
      return _backedOff(draft, error.message);
    }
  }

  /// A committed draft: keeps the server response, clears all retry state, and
  /// adopts the server's current performed date so a corrected session is not
  /// shown with a stale date on reconcile (ADR 035).
  WorkoutDraft _synced(WorkoutDraft draft, Map<String, dynamic> response) =>
      draft.copyWith(
        performedDate:
            (response['session_date'] as String?) ?? draft.performedDate,
        status: DraftStatus.synced,
        serverResponse: response,
        lastError: null,
        clearLastError: true,
        attempt: 0,
        clearNextAttempt: true,
        updatedAt: _iso(),
      );

  WorkoutDraft _backedOff(WorkoutDraft draft, String error) {
    final int attempt = draft.attempt + 1;
    final DateTime nextAttemptAt = _now().add(_backoffFor(attempt));
    return draft.copyWith(
      status: DraftStatus.pending,
      lastError: error,
      attempt: attempt,
      nextAttemptAt: nextAttemptAt.toIso8601String(),
      updatedAt: _iso(),
    );
  }

  /// A 4xx (except a client timeout) is a refusal that will not fix itself;
  /// network failures and 5xx stay pending for a later retry.
  static bool _isTerminal(ApiException error) {
    final int? status = error.statusCode;
    return status != null && status >= 400 && status < 500 && status != 408;
  }

  String _iso() => _now().toIso8601String();

  /// Drops synced drafts older than 24 hours so the list stays small while the
  /// player still sees a recently synced state.
  Future<void> _pruneSynced(String accountId) async {
    await _locked(() async {
      final List<WorkoutDraft> current = await _store.read(accountId);
      final DateTime cutoff = _now().subtract(const Duration(hours: 24));
      final List<WorkoutDraft> kept = current.where((WorkoutDraft draft) {
        if (!draft.isSynced) {
          return true;
        }
        final DateTime? updated = DateTime.tryParse(draft.updatedAt);
        return updated == null || updated.isAfter(cutoff);
      }).toList(growable: false);
      if (kept.length == current.length) {
        return;
      }
      await _store.write(accountId, kept);
      if (_accountId == accountId) {
        _drafts = kept;
        notifyListeners();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
