import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

import 'browser_key_value_store.dart';
import 'install_prompt_dismissal.dart';
import 'install_prompt_store.dart';
import 'in_app_browser_detection.dart';
import 'ios_safari_detection.dart';

InstallPromptStore createInstallPromptStore(
  BrowserKeyValueStore storage, {
  DateTime Function()? clock,
}) =>
    _WebInstallPromptStore(storage, clock ?? DateTime.now);

class _WebInstallPromptStore implements InstallPromptStore {
  _WebInstallPromptStore(BrowserKeyValueStore storage, DateTime Function() clock)
      : _dismissal = InstallPromptDismissal(storage, clock: clock);

  final InstallPromptDismissal _dismissal;

  @override
  Future<InstallPromptEnvironment> readEnvironment() async {
    return InstallPromptEnvironment(
      isIosShareBrowser: _isIosShareBrowser && !_isInAppBrowser,
      hasInstallButton: _installAvailable && !_isInAppBrowser,
      isStandalone: _isStandalone,
      wasDismissed: _dismissal.isDismissed(),
      isInAppBrowser: _isInAppBrowser,
    );
  }

  bool get _installAvailable => _readBoolean('MYOS_INSTALL_PROMPT_AVAILABLE');

  bool get _isStandalone {
    final JSBoolean? standalone = (web.window.navigator as JSObject)
        .getProperty<JSBoolean?>('standalone'.toJS);
    return (standalone?.toDart ?? false) ||
        web.window.matchMedia('(display-mode: standalone)').matches;
  }

  bool get _isIosShareBrowser {
    final String ua = web.window.navigator.userAgent;
    final String platform = web.window.navigator.platform;
    final bool ipad = platform == 'MacIntel' && web.window.navigator.maxTouchPoints > 1;
    return isIosShareBrowserUserAgent(ua, iPadDesktop: ipad);
  }

  bool get _isInAppBrowser {
    return isKnownInAppBrowserUserAgent(web.window.navigator.userAgent);
  }

  bool _readBoolean(String property) {
    final JSBoolean? value = (web.window as JSObject)
        .getProperty<JSBoolean?>(property.toJS);
    return value?.toDart ?? false;
  }

  @override
  Future<void> rememberDismissal() async {
    _dismissal.dismiss();
  }

  @override
  Future<String> promptInstall() async {
    final JSFunction? prompt = (web.window as JSObject)
        .getProperty<JSFunction?>('MYOS_PROMPT_INSTALL'.toJS);
    if (prompt == null) return 'unavailable';
    final JSPromise<JSAny?> resultPromise =
        prompt.callAsFunction() as JSPromise<JSAny?>;
    final JSAny? result = await resultPromise.toDart;
    return (result as JSString?)?.toDart ?? 'unavailable';
  }

  @override
  void listenForInstalled(void Function() onInstalled) {
    web.window.addEventListener(
      'myos-app-installed',
      ((web.Event _) => onInstalled()).toJS,
    );
  }

  @override
  void listenForInstallState(void Function() onInstallStateChanged) {
    web.window.addEventListener(
      'myos-install-state',
      ((web.Event _) => onInstallStateChanged()).toJS,
    );
  }

  @override
  bool consumeInstalled() {
    final JSFunction? consume = (web.window as JSObject)
        .getProperty<JSFunction?>('MYOS_CONSUME_APP_INSTALLED'.toJS);
    final JSBoolean? result = consume?.callAsFunction() as JSBoolean?;
    return result?.toDart ?? false;
  }
}
