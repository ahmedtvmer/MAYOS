import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';

bool isDesktopLayout(BuildContext context) =>
    MediaQuery.sizeOf(context).width >= MayosLayout.desktopNavigationBreakpoint;
