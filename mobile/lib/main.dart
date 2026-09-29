import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

import 'src/app.dart';

void main() {
  // Clean URLs on web: the browser path is the route, no '#' fragment (#127).
  // A no-op on Android, where the platform supplies the location.
  usePathUrlStrategy();
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: MayosApp()));
}
