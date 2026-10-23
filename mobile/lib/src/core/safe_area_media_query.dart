import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'safe_area_insets.dart';

class SafeAreaMediaQuery extends StatelessWidget {
  const SafeAreaMediaQuery({
    required this.source,
    required this.child,
    super.key,
  });

  final SafeAreaInsetsSource source;
  final Widget child;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: source,
        builder: (BuildContext context, Widget? child) => MediaQuery(
          data: _withSafeAreaInsets(MediaQuery.of(context), source.insets),
          child: child!,
        ),
        child: child,
      );

  MediaQueryData _withSafeAreaInsets(
    MediaQueryData mediaQuery,
    EdgeInsets insets,
  ) =>
      mediaQuery.copyWith(
        padding: _maximumInsets(
          mediaQuery.padding,
          _remainingInsets(insets, mediaQuery.viewInsets),
        ),
        viewPadding: _maximumInsets(mediaQuery.viewPadding, insets),
      );

  EdgeInsets _remainingInsets(EdgeInsets supplied, EdgeInsets viewInsets) =>
      EdgeInsets.fromLTRB(
        math.max(0.0, supplied.left - viewInsets.left),
        math.max(0.0, supplied.top - viewInsets.top),
        math.max(0.0, supplied.right - viewInsets.right),
        math.max(0.0, supplied.bottom - viewInsets.bottom),
      );

  EdgeInsets _maximumInsets(EdgeInsets existing, EdgeInsets supplied) =>
      EdgeInsets.fromLTRB(
        math.max(existing.left, supplied.left),
        math.max(existing.top, supplied.top),
        math.max(existing.right, supplied.right),
        math.max(existing.bottom, supplied.bottom),
      );
}
