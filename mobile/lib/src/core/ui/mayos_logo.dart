import 'package:flutter/material.dart';

import '../theme/mayos_theme.dart';

/// Supplied MAYOS logo variants. Marks are never redrawn, recoloured or
/// distorted; the bundled files are deterministic trims of the supplied
/// originals (see `mobile/tool/trim_logos.py` and DESIGN.md).
enum MayosBrandVariant {
  /// Picks by effective theme (see each widget's `auto` mapping).
  auto,
  white,
  blue,
  black,
}

String _file(MayosBrandVariant variant, String kind) {
  final String name = switch (variant) {
    MayosBrandVariant.white => 'white',
    MayosBrandVariant.blue => 'blue',
    MayosBrandVariant.black => 'black',
    MayosBrandVariant.auto => 'black',
  };
  return 'assets/brand/mayos-$kind-$name.png';
}

/// The full mark + wordmark lockup, cropped to its content. Used for the
/// splash hero. `auto` maps dark→blue (the owner's coloured hero) and
/// light→black.
class MayosBrandLockup extends StatelessWidget {
  const MayosBrandLockup({
    super.key,
    this.height = 120,
    this.variant = MayosBrandVariant.auto,
  });

  final double height;
  final MayosBrandVariant variant;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosBrandVariant resolved = variant == MayosBrandVariant.auto
        ? (c.isDark ? MayosBrandVariant.blue : MayosBrandVariant.black)
        : variant;
    return Semantics(
      label: 'MAYOS',
      image: true,
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
/// spaced "MAYOS" text wordmark at small placements (the app header).
/// `auto` maps dark→white and light→black.
class MayosBrandMark extends StatelessWidget {
  const MayosBrandMark({
    super.key,
    this.size = 30,
    this.variant = MayosBrandVariant.auto,
  });

  final double size;
  final MayosBrandVariant variant;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosBrandVariant resolved = variant == MayosBrandVariant.auto
        ? (c.isDark ? MayosBrandVariant.white : MayosBrandVariant.black)
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
      'MAYOS',
      style: TextStyle(
        fontFamily: 'PlayfairDisplay',
        fontSize: height * 0.5,
        letterSpacing: height * 0.08,
        color: MayosTheme.of(context).textPrimary,
      ),
    );
