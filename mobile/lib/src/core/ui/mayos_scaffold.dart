import 'package:flutter/material.dart';

import '../theme/mayos_theme.dart';
import 'mayos_app_header.dart';

/// The shared MAYOS screen frame: a themed canvas with an optional
/// [MayosAppHeader] (logo and actions, or a titled sub-page header) and an
/// optional bottom bar.
///
/// Screens use this instead of a raw [Scaffold] so headers, safe areas, and
/// background treatment stay consistent.
class MayosScaffold extends StatelessWidget {
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
    return Scaffold(
      backgroundColor: c.canvas,
      resizeToAvoidBottomInset: resizeToAvoidBottomInset,
      body: SafeArea(
        bottom: safeBottom && bottomBar == null,
        child: Column(
          children: <Widget>[
            header ??
                MayosAppHeader(
                  title: title,
                  showLogo: showLogo,
                  showBack: showBack,
                  actions: actions,
                ),
            Expanded(child: body),
          ],
        ),
      ),
      bottomNavigationBar: bottomBar,
    );
  }
}
