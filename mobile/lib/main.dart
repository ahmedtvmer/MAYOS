import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

import 'src/app.dart';
import 'src/core/error_reporting.dart';

Future<void> main() async {
  // Clean URLs on web: the browser path is the route, no '#' fragment (#127).
  // A no-op on Android, where the platform supplies the location.
  usePathUrlStrategy();
  WidgetsFlutterBinding.ensureInitialized();
  await initializeErrorReporting();
  runApp(const ProviderScope(child: MayosApp()));
}
