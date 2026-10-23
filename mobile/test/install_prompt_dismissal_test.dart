import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/core/browser_key_value_store.dart';
import 'package:myos_mobile/src/core/install_prompt_dismissal.dart';

class _MemoryBrowserStorage implements BrowserKeyValueStore {
  final Map<String, String> values = <String, String>{};
  bool failWrites = false;
  bool failRemoves = false;

  @override
  String? getItem(String key) => values[key];
  @override
  void setItem(String key, String value) {
    if (failWrites) throw StateError('write denied');
    values[key] = value;
  }
  @override
  void removeItem(String key) {
    if (failRemoves) throw StateError('remove denied');
    values.remove(key);
  }
}

void main() {
  final DateTime start = DateTime.utc(2026, 10, 1);

  test('a dismissal is active just before 30 days and expires at 30 days', () {
    final _MemoryBrowserStorage storage = _MemoryBrowserStorage()
      ..values['mayos.installPrompt.dismissedAt'] = start.toIso8601String();
    DateTime now = start.add(const Duration(days: 30) - const Duration(microseconds: 1));
    final InstallPromptDismissal dismissal =
        InstallPromptDismissal(storage, clock: () => now);

    expect(dismissal.isDismissed(), isTrue);
    now = start.add(const Duration(days: 30));
    expect(dismissal.isDismissed(), isFalse);
  });

  test('legacy dismissal migrates only after the timestamp is written', () {
    final _MemoryBrowserStorage storage = _MemoryBrowserStorage()
      ..values['mayos.homeScreenInstallHint.dismissed'] = 'true';
    final InstallPromptDismissal dismissal =
        InstallPromptDismissal(storage, clock: () => start);

    expect(dismissal.isDismissed(), isTrue);
    expect(storage.values['mayos.installPrompt.dismissedAt'], start.toIso8601String());
    expect(storage.values, isNot(contains('mayos.homeScreenInstallHint.dismissed')));
  });

  test('failed legacy migration keeps the old key and hides for this visit', () {
    final _MemoryBrowserStorage storage = _MemoryBrowserStorage()
      ..values['mayos.homeScreenInstallHint.dismissed'] = 'true'
      ..failWrites = true;
    final InstallPromptDismissal dismissal =
        InstallPromptDismissal(storage, clock: () => start);

    expect(dismissal.isDismissed(), isTrue);
    expect(storage.values['mayos.homeScreenInstallHint.dismissed'], 'true');
    expect(storage.values, isNot(contains('mayos.installPrompt.dismissedAt')));
    expect(dismissal.isDismissed(), isTrue);
  });

  test('dismissal still applies in memory if timestamp storage fails', () {
    final _MemoryBrowserStorage storage = _MemoryBrowserStorage()..failWrites = true;
    final InstallPromptDismissal dismissal =
        InstallPromptDismissal(storage, clock: () => start);

    dismissal.dismiss();

    expect(dismissal.isDismissed(), isTrue);
  });
}
