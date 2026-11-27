import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../router.dart';
import '../display_language/catalog.dart';
import '../display_language/copy_context.dart';
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
    this.titleWidget,
    this.showLogo = true,
    this.showBack = false,
    this.actions = const <Widget>[],
  });

  /// Key on the centred brand treatment, exposed so layout tests can assert its
  /// position and size without reaching into the private widget.
  static const Key brandKey = Key('mayos.header.brand');

  final String? title;

  /// Replaces the [title] string with the caller's own widget, for the few
  /// bars whose title is more than plain serif text — the logger's
  /// `Log workout · 32:10` line, which is sans and live (#159). When both are
  /// given, this wins.
  final Widget? titleWidget;

  final bool showLogo;
  final bool showBack;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = displayCopyOf(context);
    // The default shell header shows the brand alone, centred on the screen so
    // it is independent of how many actions sit on the right. Titled sub-pages
    // keep the left-aligned back button + title row.
    final bool centredBrand =
        showLogo && !showBack && title == null && titleWidget == null;
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
      padding: const EdgeInsetsDirectional.fromSTEB(
          MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.xs, MayosSpacing.xs),
      child: Row(
        children: <Widget>[
          if (showBack)
            IconButton(
              tooltip: copy.back,
              // Pop the page underneath when there is one. A deep link or a
              // cold start leaves the stack empty, so `maybePop` reports the
              // pop unhandled and Back resolves to Home instead of doing
              // nothing (#156). The router's redirect maps homePath to the
              // account's real landing (coach, login, deferred intake), so
              // this is safe for every sub-page that shows the affordance.
              onPressed: () async {
                final bool handled = await Navigator.of(context).maybePop();
                if (!context.mounted || handled) {
                  return;
                }
                context.go(homePath);
              },
              // Icons.arrow_back opts into Flutter's text-direction mirroring.
              icon: const Icon(Icons.arrow_back),
            )
          else if (showLogo)
            const Padding(
              padding: EdgeInsetsDirectional.only(start: 4),
              child: _MayosWordmark(),
            )
          else
            const SizedBox(width: MayosSpacing.xs),
          if (titleWidget != null) ...<Widget>[
            const SizedBox(width: MayosSpacing.xs),
            Expanded(child: titleWidget!),
          ] else if (title != null) ...<Widget>[
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: Text(
                title!,
                overflow: TextOverflow.ellipsis,
                style: MayosTypography.of(context).pageHeading.copyWith(
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

/// The small-placement brand treatment (#886): the red dumbbell M alone, with
/// no word under it. Screen readers still hear the brand name.
class _MayosWordmark extends StatelessWidget {
  const _MayosWordmark({super.key});

  @override
  Widget build(BuildContext context) {
    final String brandName = displayCopyOf(context).brandName;
    return Semantics(
      label: brandName,
      excludeSemantics: true,
      child: const MayosBrandMark(size: 24),
    );
  }
}
