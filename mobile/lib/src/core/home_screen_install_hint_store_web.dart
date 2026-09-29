import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

import 'home_screen_install_hint_store.dart';
import 'ios_safari_detection.dart';

const String _dismissalStorageKey = 'mayos.homeScreenInstallHint.dismissed';

HomeScreenInstallHintStore createHomeScreenInstallHintStore() =>
    _WebHomeScreenInstallHintStore();

class _WebHomeScreenInstallHintStore implements HomeScreenInstallHintStore {
  @override
  Future<HomeScreenInstallHintEnvironment> readEnvironment() async =>
      HomeScreenInstallHintEnvironment(
        isIosSafari: _isIosSafari,
        isStandalone: _isStandalone,
        wasDismissed: _wasDismissed(),
      );

  bool get _isIosSafari {
    final String userAgent = web.window.navigator.userAgent;
    final String platform = web.window.navigator.platform;
    final bool iPadDesktop =
        platform == 'MacIntel' && web.window.navigator.maxTouchPoints > 1;
    return isIosSafariUserAgent(userAgent, iPadDesktop: iPadDesktop);
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
  Future<void> rememberDismissal() async {
    try {
      web.window.localStorage.setItem(_dismissalStorageKey, 'true');
    } catch (_) {
      // A denied write leaves the hint available again on the next screen.
    }
  }
}
