import 'package:web/web.dart' as web;

import 'browser_key_value_store.dart';

BrowserKeyValueStore createBrowserKeyValueStore() => _BrowserLocalStorage();

class _BrowserLocalStorage implements BrowserKeyValueStore {
  @override
  String? getItem(String key) => web.window.localStorage.getItem(key);

  @override
  void setItem(String key, String value) =>
      web.window.localStorage.setItem(key, value);

  @override
  void removeItem(String key) => web.window.localStorage.removeItem(key);
}
