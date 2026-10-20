import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';

/// Keeps interactive controls at least 48dp high on phone layouts while
/// leaving their existing desktop dimensions intact.
Widget mayosPhoneTapTarget(BuildContext context, Widget child) {
  if (MediaQuery.sizeOf(context).width >=
      MayosLayout.desktopNavigationBreakpoint) {
    return child;
  }
  return ConstrainedBox(
    constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
    child: child,
  );
}
