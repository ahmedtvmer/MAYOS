import 'package:flutter/widgets.dart';

import 'safe_area_insets.dart';

SafeAreaInsetsSource createSafeAreaInsetsSource() =>
    _StubSafeAreaInsetsSource();

class _StubSafeAreaInsetsSource extends SafeAreaInsetsSource {
  @override
  EdgeInsets get insets => EdgeInsets.zero;
}
