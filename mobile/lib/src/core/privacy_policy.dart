import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config.dart';
import 'display_language/copy_context.dart';
import 'external_url_launcher.dart';

export 'external_url_launcher.dart' show ExternalUrlLauncher;

/// Hands a URL to the system browser. Tests override
/// [privacyUrlLauncherProvider], so widget tests never reach a platform channel.
typedef UrlLauncherFn = ExternalUrlLauncher;

/// Backwards-compatible name for tests and the privacy-policy caller.
final privacyUrlLauncherProvider = externalUrlLauncherProvider;

/// The privacy-policy URL: the API serves the single source of truth at
/// `/privacy`, so the app never renders its own copy of the text.
String get privacyPolicyUrl => '$apiBaseUrl/privacy';

/// Opens the privacy policy in the system browser and reports a platform
/// refusal with a snackbar instead of failing silently.
Future<void> openPrivacyPolicy(BuildContext context, WidgetRef ref) async {
  final bool opened =
      await ref.read(privacyUrlLauncherProvider)(privacyPolicyUrl);
  if (!opened && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(displayCopyOf(context).unavailablePrivacyPolicy)),
    );
  }
}
