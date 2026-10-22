import 'package:flutter/widgets.dart';

import '../app_mode.dart';

/// Keeps shared screen layout mode-aware without depending on app providers.
class MyosAppModeScope extends InheritedWidget {
  const MyosAppModeScope({
    super.key,
    required this.mode,
    required super.child,
  });

  final AppMode mode;

  static AppMode? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<MyosAppModeScope>()?.mode;

  @override
  bool updateShouldNotify(MyosAppModeScope oldWidget) =>
      mode != oldWidget.mode;
}
