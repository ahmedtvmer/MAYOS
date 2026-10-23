import 'package:flutter/foundation.dart'
    show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/in_app_browser_detection.dart';
import 'in_app_browser_user_agent_stub.dart'
    if (dart.library.js_interop) 'in_app_browser_user_agent_web.dart' as browser;

bool shouldShowInAppBrowserGoogleHint({
  required bool isWeb,
  required String userAgent,
}) =>
    isWeb && isKnownInAppBrowserUserAgent(userAgent);

final Provider<bool> showInAppBrowserGoogleHintProvider = Provider<bool>(
  (ref) => shouldShowInAppBrowserGoogleHint(
    isWeb: kIsWeb,
    userAgent: kIsWeb ? browser.currentUserAgent() : '',
  ),
);
