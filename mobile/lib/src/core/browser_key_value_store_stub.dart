import 'browser_key_value_store.dart';

/// Ephemeral storage for platforms without browser localStorage. It is used
/// only by stubbed browser features; protected workouts use their own store.
BrowserKeyValueStore createBrowserKeyValueStore() =>
    _EphemeralBrowserKeyValueStore();

class _EphemeralBrowserKeyValueStore implements BrowserKeyValueStore {
  final Map<String, String> _values = <String, String>{};

  @override
  String? getItem(String key) => _values[key];

  @override
  void setItem(String key, String value) => _values[key] = value;

  @override
  void removeItem(String key) => _values.remove(key);
}
