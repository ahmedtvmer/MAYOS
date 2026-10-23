import 'package:flutter/widgets.dart';

import 'safe_area_insets_stub.dart'
    if (dart.library.js_interop) 'safe_area_insets_web.dart' as platform;

abstract class SafeAreaInsetsSource extends ChangeNotifier {
  EdgeInsets get insets;
}

SafeAreaInsetsSource createSafeAreaInsetsSource() =>
    platform.createSafeAreaInsetsSource();
