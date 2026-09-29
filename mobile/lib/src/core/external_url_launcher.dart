import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

typedef ExternalUrlLauncher = Future<bool> Function(String url);

Future<bool> _launchInSystemBrowser(String url) =>
    launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

final Provider<ExternalUrlLauncher> externalUrlLauncherProvider =
    Provider<ExternalUrlLauncher>((ref) => _launchInSystemBrowser);
