import 'browser_key_value_store.dart';

const String legacyInstallPromptDismissalKey =
    'mayos.homeScreenInstallHint.dismissed';
const String installPromptDismissalKey = 'mayos.installPrompt.dismissedAt';
const Duration installPromptDismissalPeriod = Duration(days: 30);

class InstallPromptDismissal {
  InstallPromptDismissal(this._storage, {DateTime Function()? clock})
      : _clock = clock ?? DateTime.now;

  final BrowserKeyValueStore _storage;
  final DateTime Function() _clock;
  DateTime? _visitDismissalAt;

  bool isDismissed() {
    if (_isActive(_visitDismissalAt)) return true;

    String? savedTimestamp;
    try {
      savedTimestamp = _storage.getItem(installPromptDismissalKey);
    } on Object {
      return _isActive(_visitDismissalAt);
    }
    if (savedTimestamp != null) return _timestampIsActive(savedTimestamp);

    return _migrateLegacyDismissal();
  }

  void dismiss() {
    final DateTime now = _clock().toUtc();
    _visitDismissalAt = now;
    try {
      _storage.setItem(installPromptDismissalKey, now.toIso8601String());
    } on Object {
      // The in-memory timestamp still suppresses the prompt for this visit.
    }
  }

  bool _migrateLegacyDismissal() {
    try {
      if (_storage.getItem(legacyInstallPromptDismissalKey) != 'true') {
        return false;
      }
    } on Object {
      return _isActive(_visitDismissalAt);
    }

    final DateTime migrationTime = _clock().toUtc();
    try {
      _storage.setItem(
        installPromptDismissalKey,
        migrationTime.toIso8601String(),
      );
    } on Object {
      _visitDismissalAt = migrationTime;
      return true;
    }
    _visitDismissalAt = migrationTime;
    try {
      _storage.removeItem(legacyInstallPromptDismissalKey);
    } on Object {
      // The saved timestamp now owns the migration; a stale legacy key is harmless.
    }
    return true;
  }

  bool _timestampIsActive(String value) {
    final DateTime? timestamp = DateTime.tryParse(value)?.toUtc();
    return timestamp != null && _isActive(timestamp);
  }

  bool _isActive(DateTime? timestamp) {
    if (timestamp == null) return false;
    final Duration age = _clock().toUtc().difference(timestamp);
    return !age.isNegative && age < installPromptDismissalPeriod;
  }
}
