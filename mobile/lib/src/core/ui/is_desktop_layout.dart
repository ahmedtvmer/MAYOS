import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';

bool isDesktopLayout(BuildContext context) =>
    MediaQuery.sizeOf(context).width >= MyosLayout.desktopNavigationBreakpoint;
