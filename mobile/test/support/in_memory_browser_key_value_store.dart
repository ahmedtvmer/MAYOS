import 'package:mayos_mobile/src/core/browser_key_value_store.dart';

/// Test fake shared across app rebuilds to model browser localStorage.
class InMemoryBrowserKeyValueStore implements BrowserKeyValueStore {
  final Map<String, String> values = <String, String>{};

  @override
  String? getItem(String key) => values[key];

  @override
  void setItem(String key, String value) => values[key] = value;

  @override
  void removeItem(String key) => values.remove(key);
}
