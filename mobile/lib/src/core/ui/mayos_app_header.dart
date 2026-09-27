import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';
import 'mayos_logo.dart';

/// The MAYOS app header: the brand treatment centred on the screen with the
/// actions on the right, or a titled sub-page header (back affordance on the
/// left, title, actions on the right).
class MayosAppHeader extends StatelessWidget {
  const MayosAppHeader({
    super.key,
    this.title,
    this.showLogo = true,
    this.showBack = false,
    this.actions = const <Widget>[],
  });

  /// Key on the centred brand treatment, exposed so layout tests can assert its
  /// position and size without reaching into the private widget.
  static const Key brandKey = Key('mayos.header.brand');

  final String? title;
  final bool showLogo;
  final bool showBack;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    // The default shell header shows the brand alone, centred on the screen so
    // it is independent of how many actions sit on the right. Titled sub-pages
    // keep the left-aligned back button + title row.
    final bool centredBrand = showLogo && !showBack && title == null;
    if (centredBrand) {
      // Symmetric horizontal padding keeps the centred brand on the screen's
      // mid-line (the right-aligned actions sit inside the same inset).
      return Padding(
        padding: const EdgeInsets.fromLTRB(
            MayosSpacing.sm, MayosSpacing.sm, MayosSpacing.sm, MayosSpacing.xs),
        child: Stack(
          alignment: Alignment.center,
          children: <Widget>[
            const _MayosWordmark(key: MayosAppHeader.brandKey),
            if (actions.isNotEmpty)
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: actions,
              ),
          ],
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.xs, MayosSpacing.xs),
      child: Row(
        children: <Widget>[
          if (showBack)
            IconButton(
              tooltip: 'Back',
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.arrow_back),
            )
          else if (showLogo)
            const Padding(
              padding: EdgeInsets.only(left: 4),
              child: _MayosWordmark(),
            )
          else
            const SizedBox(width: MayosSpacing.xs),
          if (title != null) ...<Widget>[
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: Text(
                title!,
                overflow: TextOverflow.ellipsis,
                style: MayosTypography.pageHeading.copyWith(
                  fontSize: 22,
                  color: c.textPrimary,
                ),
              ),
            ),
          ] else
            const Spacer(),
          ...actions,
        ],
      ),
    );
  }
}

/// The small-placement brand treatment: the supplied mark at ~22dp beside a
/// clean, letterspaced "MAYOS" wordmark in the brand sans, in the theme's
/// primary text colour. This is the documented clean text treatment used where
/// the vertical lockup's baked wordmark would be illegible. The wordmark is a
/// decorative label, so its text scaling is clamped to keep the header from
/// crowding the actions at 320dp.
class _MayosWordmark extends StatelessWidget {
  const _MayosWordmark({super.key});

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: 1.2,
      child: Semantics(
        label: 'MAYOS',
        excludeSemantics: true,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const MayosBrandMark(size: 22),
            const SizedBox(width: MayosSpacing.xxs),
            Text(
              'MAYOS',
              style: MayosTypography.label.copyWith(
                fontSize: 10.5,
                letterSpacing: 2.2,
                color: c.textPrimary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
