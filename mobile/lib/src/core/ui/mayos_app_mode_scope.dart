import 'package:flutter/widgets.dart';

import '../app_mode.dart';

/// Keeps shared screen layout mode-aware without depending on app providers.
class MayosAppModeScope extends InheritedWidget {
  const MayosAppModeScope({
    super.key,
    required this.mode,
    required super.child,
  });

  final AppMode mode;

  static AppMode? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<MayosAppModeScope>()?.mode;

  @override
  bool updateShouldNotify(MayosAppModeScope oldWidget) =>
      mode != oldWidget.mode;
}
