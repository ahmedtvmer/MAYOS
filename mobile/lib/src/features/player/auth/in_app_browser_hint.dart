import 'package:flutter/foundation.dart'
    show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'in_app_browser_user_agent_stub.dart'
    if (dart.library.js_interop) 'in_app_browser_user_agent_web.dart' as browser;

/// Pure user-agent seam for the Google sign-in hint.
bool isKnownInAppBrowserUserAgent(String userAgent) {
  final String agent = userAgent.toLowerCase();
  return agent.contains('tiktok') ||
      agent.contains('musical_ly') ||
      agent.contains('trill_') ||
      agent.contains('bytedancewebview') ||
      agent.contains('instagram') ||
      agent.contains('fbav') ||
      agent.contains('fban') ||
      agent.contains('facebook');
}

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
