import 'package:flutter/material.dart';

import '../app_mode.dart';
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
    final _MayosScaffoldLayout layout = _buildLayout(context);
    return Scaffold(
      backgroundColor: c.canvas,
      resizeToAvoidBottomInset: resizeToAvoidBottomInset,
      body: SafeArea(
        bottom: safeBottom && (bottomBar == null || layout.showRail),
        child: layout.content,
      ),
      bottomNavigationBar: layout.showRail ? null : bottomBar,
    );
  }

  _MayosScaffoldLayout _buildLayout(BuildContext context) {
    final bool desktop = MediaQuery.sizeOf(context).width >=
        MayosSpacing.desktopNavigationBreakpoint;
    final Widget? rail = desktop ? _buildRail(context, bottomBar) : null;
    return _MayosScaffoldLayout(
      content: Row(
        children: <Widget>[
          // Keep the content column in the same slot so tab state survives
          // resizing.
          SizedBox(
            width: rail == null ? 0 : MayosSpacing.navigationRailWidth,
            child: rail,
          ),
          Expanded(child: _buildResponsiveContent(context)),
        ],
      ),
      showRail: rail != null,
    );
  }

  Widget? _buildRail(BuildContext context, Widget? bottomNavigation) {
    if (bottomNavigation is! MayosBottomNavigation) {
      return null;
    }
    return MayosNavigationRail(
      items: bottomNavigation.items,
      index: bottomNavigation.index,
      onSelected: bottomNavigation.onSelected,
    );
  }

  Widget _buildResponsiveContent(BuildContext context) {
    final double viewportWidth = MediaQuery.sizeOf(context).width;
    final bool constrainPlayer =
        viewportWidth >= MayosSpacing.desktopNavigationBreakpoint &&
            MayosAppModeScope.maybeOf(context) == AppMode.player;
    final double maxWidth =
        constrainPlayer ? MayosSpacing.playerColumnMaxWidth : viewportWidth;
    // Keep the wrapper ancestry stable; resizing changes only this constraint.
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: SizedBox(width: double.infinity, child: _buildContentColumn()),
      ),
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

class _MayosScaffoldLayout {
  const _MayosScaffoldLayout({required this.content, required this.showRail});

  final Widget content;
  final bool showRail;
}
