import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

import 'src/app.dart';
import 'src/core/error_reporting.dart';
import 'src/core/foreground_policy.dart';

Future<void> main() async {
  // Clean URLs on web: the browser path is the route, no '#' fragment (#127).
  // A no-op on Android, where the platform supplies the location.
  usePathUrlStrategy();
  WidgetsFlutterBinding.ensureInitialized();
  await initializeErrorReporting();
  runApp(ProviderScope(
    overrides: <Override>[
      // Release timings for resume refreshes and the offline banner (#894).
      foregroundPolicyProvider.overrideWithValue(ForegroundPolicy.release),
    ],
    child: const MayosApp(),
  ));
}
