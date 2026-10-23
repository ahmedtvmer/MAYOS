import 'package:flutter/material.dart';

import '../display_language/copy_context.dart';
import '../theme/myos_theme.dart';

/// Supplied MYOS logo variants. Marks are never redrawn, recoloured or
/// distorted; the bundled files are deterministic trims of the supplied
/// originals (see `mobile/tool/trim_logos.py` and DESIGN.md).
enum MyosBrandVariant {
  /// Picks by effective theme (see each widget's `auto` mapping).
  auto,
  white,
  black,
}

String _file(MyosBrandVariant variant, String kind) {
  final String name = switch (variant) {
    MyosBrandVariant.white => 'white',
    MyosBrandVariant.black => 'black',
    MyosBrandVariant.auto => 'black',
  };
  return 'assets/brand/myos-$kind-$name.png';
}

/// The full mark + wordmark lockup, cropped to its content. Used for the
/// splash hero. `auto` maps dark→white and light→black.
class MyosBrandLockup extends StatelessWidget {
  const MyosBrandLockup({
    super.key,
    this.height = 120,
    this.variant = MyosBrandVariant.auto,
  });

  final double height;
  final MyosBrandVariant variant;

  @override
  Widget build(BuildContext context) {
    final String brandName = displayCopyOf(context).brandName;
    final MyosThemeExtension c = MyosTheme.of(context);
    final MyosBrandVariant resolved = variant == MyosBrandVariant.auto
        ? (c.isDark ? MyosBrandVariant.white : MyosBrandVariant.black)
        : variant;
    return Semantics(
      label: brandName,
      image: true,
      excludeSemantics: true,
      child: Image.asset(
        _file(resolved, 'lockup'),
        height: height,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.high,
        excludeFromSemantics: true,
        errorBuilder: (_, __, ___) => _fallback(context, height),
      ),
    );
  }
}

/// The mark only, with the wordmark split off. Used beside a clean, letter-
/// spaced "MYOS" text wordmark at small placements (the app header).
/// `auto` maps dark→white and light→black.
class MyosBrandMark extends StatelessWidget {
  const MyosBrandMark({
    super.key,
    this.size = 30,
    this.variant = MyosBrandVariant.auto,
  });

  final double size;
  final MyosBrandVariant variant;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final MyosBrandVariant resolved = variant == MyosBrandVariant.auto
        ? (c.isDark ? MyosBrandVariant.white : MyosBrandVariant.black)
        : variant;
    return Image.asset(
      _file(resolved, 'mark'),
      height: size,
      fit: BoxFit.contain,
      filterQuality: FilterQuality.high,
      excludeFromSemantics: true,
      errorBuilder: (_, __, ___) => SizedBox(height: size, width: size),
    );
  }
}

Widget _fallback(BuildContext context, double height) => Text(
      'MYOS',
      style: TextStyle(
        fontFamily: 'PlayfairDisplay',
        fontSize: height * 0.5,
        letterSpacing: height * 0.08,
        color: MyosTheme.of(context).textPrimary,
      ),
    );
