import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;

import 'safe_area_insets.dart';

SafeAreaInsetsSource createSafeAreaInsetsSource() =>
    _WebSafeAreaInsetsSource();

class _WebSafeAreaInsetsSource extends SafeAreaInsetsSource {
  _WebSafeAreaInsetsSource() {
    _probe = web.document.createElement('div') as web.HTMLDivElement;
    _probe.style.cssText =
        'position:fixed;left:-1000px;top:0;visibility:hidden;pointer-events:none;'
        'padding:env(safe-area-inset-top) env(safe-area-inset-right) '
        'env(safe-area-inset-bottom) env(safe-area-inset-left);';
    web.document.body!.append(_probe);
    _refreshInsets();
    web.window.addEventListener('resize', _changeListener);
    web.window.addEventListener('orientationchange', _changeListener);
    web.window.visualViewport?.addEventListener('resize', _changeListener);
  }

  late final web.HTMLDivElement _probe;
  late final JSFunction _changeListener = _handleWindowChange.toJS;
  EdgeInsets _insets = EdgeInsets.zero;

  @override
  EdgeInsets get insets => _insets;

  void _handleWindowChange(web.Event event) => _refreshInsets();

  void _refreshInsets() {
    final EdgeInsets nextInsets;
    if (_isStandalone) {
      final web.CSSStyleDeclaration style = web.window.getComputedStyle(_probe);
      nextInsets = EdgeInsets.fromLTRB(
        _pixels(style.paddingLeft),
        _pixels(style.paddingTop),
        _pixels(style.paddingRight),
        _pixels(style.paddingBottom),
      );
    } else {
      nextInsets = EdgeInsets.zero;
    }
    if (nextInsets == _insets) return;
    _insets = nextInsets;
    notifyListeners();
  }

  bool get _isStandalone {
    final JSBoolean? standaloneValue = (web.window.navigator as JSObject)
        .getProperty<JSBoolean?>('standalone'.toJS);
    return (standaloneValue?.toDart ?? false) ||
        web.window.matchMedia('(display-mode: standalone)').matches;
  }

  double _pixels(String value) => double.tryParse(value.replaceAll('px', '')) ?? 0;

  @override
  void dispose() {
    web.window.removeEventListener('resize', _changeListener);
    web.window.removeEventListener('orientationchange', _changeListener);
    web.window.visualViewport?.removeEventListener('resize', _changeListener);
    _probe.remove();
    super.dispose();
  }
}
