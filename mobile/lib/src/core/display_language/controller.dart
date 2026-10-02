import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'catalog.dart';
import 'store.dart';

final displayLanguageProvider =
    StateNotifierProvider<DisplayLanguageController, String>((ref) =>
        DisplayLanguageController(ref.watch(displayLanguageStoreProvider),
            systemLanguage: ref.watch(systemDisplayLanguageProvider)));

final systemDisplayLanguageProvider = Provider<String>(
    (ref) => WidgetsBinding.instance.platformDispatcher.locale.languageCode);

class DisplayLanguageController extends StateNotifier<String> {
  DisplayLanguageController(this._store, {String? systemLanguage})
      : _systemLanguage = _supported(systemLanguage ?? _platformLanguage()),
        super(_supported(systemLanguage ?? _platformLanguage()));
  final DisplayLanguageStore _store;
  String _systemLanguage;
  String? _activeAccountId;
  int _accountRevision = 0;
  static String _platformLanguage() =>
      WidgetsBinding.instance.platformDispatcher.locale.languageCode;
  static String _supported(String code) {
    return normalizeDisplayLanguage(code);
  }

  int get revision => _accountRevision;

  Future<void> initialize({String? accountId, int? expectedRevision}) async {
    final int revision = expectedRevision ?? _accountRevision;
    if (revision != _accountRevision) return;
    try {
      if (accountId != null) {
        final accountValue = await _store.readAccount(accountId);
        if (revision != _accountRevision) return;
        if (isSupportedDisplayLanguage(accountValue)) {
          _storeChoiceLoaded = true;
          _activeAccountId = accountId;
          state = accountValue!;
          return;
        }
      }
      await _restoreStoredChoice(revision);
    } on Object {
      _storeChoiceLoaded = true;
      if (revision == _accountRevision) state = _systemLanguage;
    }
  }

  Future<void> choose(String value) async {
    if (!isSupportedDisplayLanguage(value)) {
      return;
    }
    _accountRevision++;
    _activeAccountId = null;
    _hasManualChoice = true;
    _storeChoiceLoaded = true;
    state = value;
    unawaited(_store.write(value).catchError((Object _) {}));
  }

  Future<void> useAccount(String accountId, String value) async {
    _accountRevision++;
    _activeAccountId = accountId;
    final confirmed = normalizeDisplayLanguage(value);
    _storeChoiceLoaded = true;
    state = confirmed;
    unawaited(
        _store.writeAccount(accountId, confirmed).catchError((Object _) {}));
  }

  void cacheAccountChoice(String accountId, String value) {
    if (accountId.isEmpty || !isSupportedDisplayLanguage(value)) {
      return;
    }
    unawaited(_store.writeAccount(accountId, value).catchError((Object _) {}));
  }

  Future<void> restoreLoggedOutChoice() async {
    _accountRevision++;
    _activeAccountId = null;
    final int revision = _accountRevision;
    _storeChoiceLoaded = false;
    state = _systemLanguage;
    await _restoreStoredChoice(revision);
  }

  Future<void> _restoreStoredChoice(int revision) async {
    try {
      final saved = await _store.read();
      if (revision != _accountRevision) return;
      if (isSupportedDisplayLanguage(saved)) {
        state = saved!;
        _hasManualChoice = true;
      } else {
        state = _systemLanguage;
        _hasManualChoice = false;
      }
    } on Object {
      if (revision == _accountRevision) {
        state = _systemLanguage;
        _hasManualChoice = false;
      }
    } finally {
      if (revision == _accountRevision) _storeChoiceLoaded = true;
    }
  }

  void useSystemLanguage() {
    if (_activeAccountId != null || _storeChoiceLoaded) return;
    _accountRevision++;
    _storeChoiceLoaded = false;
    _activeAccountId = null;
    state = _systemLanguage;
  }

  void systemLanguageChanged(String code) {
    _systemLanguage = _supported(code);
    if (_activeAccountId == null && !_hasManualChoice) {
      state = _systemLanguage;
    }
  }

  bool _storeChoiceLoaded = false;
  bool _hasManualChoice = false;
}
