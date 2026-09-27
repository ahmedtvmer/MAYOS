import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';
import 'mayos_logo.dart';

/// The MAYOS app header: the supplied wordmark on the left, actions on the
/// right, with an optional title (and back affordance) for sub-pages.
class MayosAppHeader extends StatelessWidget {
  const MayosAppHeader({
    super.key,
    this.title,
    this.showLogo = true,
    this.showBack = false,
    this.actions = const <Widget>[],
  });

  final String? title;
  final bool showLogo;
  final bool showBack;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
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

/// The small-placement brand treatment: the supplied mark at ~30dp beside a
/// clean, letterspaced "MAYOS" wordmark in the brand sans, in the theme's
/// primary text colour. This is the documented clean text treatment used where
/// the vertical lockup's baked wordmark would be illegible.
class _MayosWordmark extends StatelessWidget {
  const _MayosWordmark();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      label: 'MAYOS',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          const MayosBrandMark(size: 30),
          const SizedBox(width: MayosSpacing.xs),
          Text(
            'MAYOS',
            style: MayosTypography.label.copyWith(
              fontSize: 13,
              letterSpacing: 3,
              color: c.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}
