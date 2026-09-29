import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

import 'home_screen_install_hint_store.dart';

const String _dismissalStorageKey = 'mayos.homeScreenInstallHint.dismissed';

HomeScreenInstallHintStore createHomeScreenInstallHintStore() =>
    _WebHomeScreenInstallHintStore();

class _WebHomeScreenInstallHintStore implements HomeScreenInstallHintStore {
  @override
  Future<HomeScreenInstallHintEnvironment> readEnvironment() async =>
      HomeScreenInstallHintEnvironment(
        isWeb: true,
        isIosSafari: _isIosSafari,
        isStandalone: _isStandalone,
        wasDismissed: _wasDismissed(),
      );

  bool get _isIosSafari {
    final String userAgent = web.window.navigator.userAgent;
    final String platform = web.window.navigator.platform;
    final bool iPadDesktop =
        platform == 'MacIntel' && web.window.navigator.maxTouchPoints > 1;
    final bool appleMobile = userAgent.contains('iPhone') ||
        userAgent.contains('iPad') ||
        iPadDesktop;
    final bool safari = userAgent.contains('Safari') &&
        !RegExp(
          r'CriOS|FxiOS|EdgiOS',
          caseSensitive: false,
        ).hasMatch(userAgent);
    return appleMobile && safari;
  }

  bool get _isStandalone {
    final JSBoolean? standaloneValue = (web.window.navigator as JSObject)
        .getProperty<JSBoolean?>('standalone'.toJS);
    return (standaloneValue?.toDart ?? false) ||
        web.window.matchMedia('(display-mode: standalone)').matches;
  }

  bool _wasDismissed() {
    try {
      return web.window.localStorage.getItem(_dismissalStorageKey) == 'true';
    } catch (_) {
      // Storage is optional: a denied read leaves the hint visible.
      return false;
    }
  }

  @override
  Future<bool> rememberDismissal() async {
    try {
      web.window.localStorage.setItem(_dismissalStorageKey, 'true');
      return true;
    } catch (_) {
      // Storage denial leaves the hint visible and available to try again.
      return false;
    }
  }
}
