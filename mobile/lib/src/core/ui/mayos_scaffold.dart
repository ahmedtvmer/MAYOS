import 'package:flutter/material.dart';

import '../app_mode.dart';
import '../connectivity.dart';
import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import 'mayos_app_header.dart';
import 'mayos_app_mode_scope.dart';
import 'mayos_bottom_navigation.dart';

/// The shared MAYOS screen frame: a themed canvas with an optional
/// [MayosAppHeader] (logo and actions, or a titled sub-page header) and an
/// optional bottom bar.
///
/// Screens use this instead of a raw [Scaffold] so headers, safe areas, and
/// background treatment stay consistent.
class MayosScaffold extends StatelessWidget {
  /// Stable body bounds for responsive shell and pushed-screen layout checks.
  static const Key bodyContentKey = ValueKey<String>('mayos_scaffold_body');

  const MayosScaffold({
    super.key,
    required this.body,
    this.title,
    this.showLogo = false,
    this.showBack = false,
    this.actions = const <Widget>[],
    this.bottomBar,
    this.header,
    this.resizeToAvoidBottomInset = true,
    this.safeBottom = true,
  });

  final Widget body;
  final String? title;
  final bool showLogo;
  final bool showBack;
  final List<Widget> actions;
  final Widget? bottomBar;

  /// Replaces the default header entirely (the shell supplies its own).
  final Widget? header;
  final bool resizeToAvoidBottomInset;
  final bool safeBottom;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool desktop = MediaQuery.sizeOf(context).width >=
        MayosLayout.desktopNavigationBreakpoint;
    final Widget? rail = desktop ? _rail() : null;
    // Player mode reads as a phone-width column on desktop; Coach mode uses
    // the full width (#133).
    final bool playerColumn =
        desktop && MayosAppModeScope.maybeOf(context) == AppMode.player;
    return Scaffold(
      backgroundColor: c.canvas,
      resizeToAvoidBottomInset: resizeToAvoidBottomInset,
      body: SafeArea(
        bottom: safeBottom && (bottomBar == null || rail != null),
        // The rail slot and the content wrapper stay in the tree at every
        // width, so resizing across the breakpoint keeps tab state.
        child: Row(
          children: <Widget>[
            SizedBox(
              width: rail == null ? 0 : MayosLayout.navigationRailWidth,
              child: rail,
            ),
            Expanded(
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxWidth: playerColumn
                        ? MayosLayout.playerColumnMaxWidth
                        : double.infinity,
                  ),
                  child: SizedBox(
                    width: double.infinity,
                    child: _buildContentColumn(),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: rail == null ? bottomBar : null,
    );
  }

  /// The desktop rail for this screen's tabs, or null when it has none.
  Widget? _rail() {
    final Widget? tabs = bottomBar;
    if (tabs is! MayosBottomNavigation) {
      return null;
    }
    return MayosNavigationRail(
      items: tabs.items,
      index: tabs.index,
      onSelected: tabs.onSelected,
    );
  }

  Widget _buildContentColumn() => Column(
        children: <Widget>[
          header ??
              MayosAppHeader(
                title: title,
                showLogo: showLogo,
                showBack: showBack,
                actions: actions,
              ),
          const OfflineBannerSlot(),
          Expanded(
            child: SizedBox(
              key: bodyContentKey,
              width: double.infinity,
              child: body,
            ),
          ),
        ],
      );
}
