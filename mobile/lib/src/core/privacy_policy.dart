import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import 'config.dart';

/// Hands a URL to the system browser. Tests override
/// [privacyUrlLauncherProvider], so widget tests never reach a platform channel.
typedef UrlLauncherFn = Future<bool> Function(String url);

Future<bool> _openInSystemBrowser(String url) =>
    launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

/// The browser hand-off for the privacy policy (ADR 046).
final Provider<UrlLauncherFn> privacyUrlLauncherProvider =
    Provider<UrlLauncherFn>((ref) => _openInSystemBrowser);

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
      const SnackBar(
          content: Text('Could not open the privacy policy in your browser.')),
    );
  }
}
