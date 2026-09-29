import 'secure_store.dart';

/// The flat rest default when a planned exercise carries no usable
/// `rest_seconds`, and what an unplanned exercise resolves to (#108 point 6,
/// #125).
const int kDefaultRestSeconds = 120;

/// The rest picker's choices: Off (0) first, then 1:00–5:00 in 15-second
/// steps (#125).
const List<int> kRestLengthOptions = <int>[
  0, 60, 75, 90, 105, 120, 135, 150, 165, 180, 195, 210, 225, 240, 255, 270,
  285, 300,
];

/// Resolves the rest length one exercise uses (#125):
///
/// 1. the player's device override for that exercise, when there is one
///    (0 means Off and wins outright);
/// 2. else the program's `rest_seconds`, when it carries one;
/// 3. else the flat [kDefaultRestSeconds].
///
/// A *missing* `rest_seconds` is unset — not 180 — so it lands on 2:00 rather
/// than 3:00 (#125 fixes `ProgramExercise.fromJson` to agree with this).
int resolveRestSeconds({
  required int? programSeconds,
  required int? overrideSeconds,
}) {
  if (overrideSeconds != null) {
    return overrideSeconds;
  }
  if (programSeconds != null && programSeconds > 0) {
    return programSeconds;
  }
  return kDefaultRestSeconds;
}

/// `2:00`, `0:59`, `3:15` — every rest label in the app (#125).
String restMmSs(int totalSeconds) {
  final int seconds = totalSeconds < 0 ? 0 : totalSeconds;
  final int minutes = seconds ~/ 60;
  final int rest = seconds % 60;
  return '$minutes:${rest.toString().padLeft(2, '0')}';
}

/// Device persistence for the player's per-exercise rest overrides, keyed by
/// account (the per-account pattern of `AppModeStore`): one exercise id →
/// seconds map per account, 0 meaning Off. Overrides live on this device only
/// and never reach the server (#125).
abstract class RestLengthStore {
  Future<Map<String, int>> read(String accountId);

  Future<void> write(String accountId, Map<String, int> overrides);
}

/// Reuses the app's keystore-backed [SecureStore]; a keystore failure must
/// never crash a read or a write (#125).
class SecureRestLengthStore implements RestLengthStore {
  SecureRestLengthStore({SecureStore? store}) : _store = store ?? SecureStore();

  final SecureStore _store;

  static String _key(String accountId) => 'rest_length.$accountId';

  @override
  Future<Map<String, int>> read(String accountId) async {
    try {
      final dynamic decoded = await _store.readJson(_key(accountId));
      if (decoded is! Map<String, dynamic>) {
        return <String, int>{};
      }
      return <String, int>{
        for (final MapEntry<String, dynamic> entry in decoded.entries)
          if (entry.value is int) entry.key: entry.value as int,
      };
    } on Object {
      return <String, int>{};
    }
  }

  @override
  Future<void> write(String accountId, Map<String, int> overrides) async {
    try {
      await _store.writeJson(key: _key(accountId), value: overrides);
    } on Object {
      // Persistence is best-effort; the in-memory override still applies.
    }
  }
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates a restart reading the same per-account overrides.
class InMemoryRestLengthStore implements RestLengthStore {
  InMemoryRestLengthStore([Map<String, Map<String, int>>? values])
      : values = values ?? <String, Map<String, int>>{};

  final Map<String, Map<String, int>> values;

  @override
  Future<Map<String, int>> read(String accountId) async =>
      Map<String, int>.of(values[accountId] ?? const <String, int>{});

  @override
  Future<void> write(String accountId, Map<String, int> overrides) async {
    values[accountId] = Map<String, int>.of(overrides);
  }
}
