import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// One destination in [MayosBottomNavigation].
class MayosNavItem {
  const MayosNavItem({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    this.badge = 0,
    this.dot = false,
    this.dotLabel,
    this.key,
    this.decorateIcon,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;

  /// A count badge shown on the icon (0 hides it), used by the coach shell's
  /// new-alerts count (#119).
  final int badge;

  /// A small unlabelled dot on the icon, e.g. the Player's Progress tab while a
  /// Checkpoint review waits (#789). Ignored while [badge] shows a count.
  final bool dot;

  /// What the dot means, appended to the destination's semantics label.
  final String? dotLabel;

  /// Key on the tappable destination, for tests and tour lookups.
  final Key? key;

  /// Wraps the destination's icon, e.g. in a tour target, without the core UI
  /// depending on the feature that does the wrapping.
  final Widget Function(Widget icon)? decorateIcon;
}

/// A restrained bottom bar: a thin top border over the surface, equal
/// destinations, and the selected one marked by a soft pill behind its icon
/// that slides between destinations (#789). No blur, translucency or shadow,
/// so it costs no more to draw than a plain bar; the slide is instant when the
/// platform asks for reduced motion.
class MayosBottomNavigation extends StatelessWidget {
  const MayosBottomNavigation({
    super.key,
    required this.items,
    required this.index,
    required this.onSelected,
  });

  /// Key on the sliding pill, exposed for layout tests.
  static const Key indicatorKey = Key('mayos.bottomNav.indicator');

  static const double _iconTop = 6;
  static const double _pillWidth = 56;
  static const double _pillHeight = 30;

  final List<MayosNavItem> items;
  final int index;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    final bool reduceMotion =
        MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    final bool rtl = Directionality.of(context) == TextDirection.rtl;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: MayosLayout.phoneBottomNavigationHeight,
          child: LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              final double cell = constraints.maxWidth / items.length;
              final bool hasSelection = index >= 0 && index < items.length;
              final int visual = rtl ? items.length - 1 - index : index;
              return Stack(
                children: <Widget>[
                  if (hasSelection)
                    AnimatedPositioned(
                      key: indicatorKey,
                      duration:
                          reduceMotion ? Duration.zero : MayosMotion.fast,
                      curve: MayosMotion.standard,
                      top: _iconTop,
                      left: cell * visual + (cell - _pillWidth) / 2,
                      width: _pillWidth,
                      height: _pillHeight,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: c.selectedSurface,
                          borderRadius:
                              BorderRadius.circular(_pillHeight / 2),
                        ),
                      ),
                    ),
                  Row(
                    children: <Widget>[
                      for (int i = 0; i < items.length; i++)
                        Expanded(
                          child: _Destination(
                            key: items[i].key,
                            item: items[i],
                            selected: i == index,
                            onTap: () => onSelected(i),
                            labelStyle: text,
                          ),
                        ),
                    ],
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

/// Desktop counterpart to [MayosBottomNavigation], using the same items and
/// badge presentation.
class MayosNavigationRail extends StatelessWidget {
  const MayosNavigationRail({
    super.key,
    required this.items,
    required this.index,
    required this.onSelected,
  });

  final List<MayosNavItem> items;
  final int index;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        border: BorderDirectional(end: BorderSide(color: c.border)),
      ),
      child: SizedBox(
        width: MayosLayout.navigationRailWidth,
        child: _buildRail(context, c),
      ),
    );
  }

  Widget _buildRail(BuildContext context, MayosThemeExtension c) {
    final TextTheme text = Theme.of(context).textTheme;
    return NavigationRail(
      backgroundColor: c.surface,
      indicatorColor: c.selectedSurface,
      selectedIndex: index,
      onDestinationSelected: onSelected,
      minWidth: MayosLayout.navigationRailWidth,
      labelType: NavigationRailLabelType.all,
      groupAlignment: -1,
      selectedIconTheme: IconThemeData(color: c.accent),
      unselectedIconTheme: IconThemeData(color: c.textMuted),
      selectedLabelTextStyle: text.labelSmall?.copyWith(
        color: c.accent,
        fontWeight: FontWeight.w600,
      ),
      unselectedLabelTextStyle: text.labelSmall?.copyWith(
        color: c.textMuted,
        fontWeight: FontWeight.w500,
      ),
      destinations: _destinations(c),
    );
  }

  static Widget _decorated(MayosNavItem item, Widget icon) =>
      item.decorateIcon?.call(icon) ?? icon;

  List<NavigationRailDestination> _destinations(MayosThemeExtension c) =>
      <NavigationRailDestination>[
        for (final MayosNavItem item in items)
          NavigationRailDestination(
            icon: _decorated(
              item,
              _NavigationItemIcon(
                item: item,
                selected: false,
                color: c.textMuted,
              ),
            ),
            selectedIcon: _decorated(
              item,
              _NavigationItemIcon(
                item: item,
                selected: true,
                color: c.accent,
              ),
            ),
            label: Text(item.label),
          ),
      ];
}

class _Destination extends StatelessWidget {
  const _Destination({
    super.key,
    required this.item,
    required this.selected,
    required this.onTap,
    required this.labelStyle,
  });

  final MayosNavItem item;
  final bool selected;
  final VoidCallback onTap;
  final TextTheme labelStyle;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color color = selected ? c.accent : c.textMuted;
    final Widget icon =
        _NavigationItemIcon(item: item, selected: selected, color: color);
    final String semanticsLabel =
        item.dot && item.badge == 0 && item.dotLabel != null
            ? '${item.label}, ${item.dotLabel}'
            : item.label;
    return Semantics(
      button: true,
      selected: selected,
      label: semanticsLabel,
      excludeSemantics: true,
      child: InkResponse(
        onTap: onTap,
        radius: 44,
        containedInkWell: true,
        highlightShape: BoxShape.rectangle,
        child: Column(
          children: <Widget>[
            const SizedBox(height: MayosBottomNavigation._iconTop),
            SizedBox(
              height: MayosBottomNavigation._pillHeight,
              child: Center(child: item.decorateIcon?.call(icon) ?? icon),
            ),
            const SizedBox(height: 3),
            // Five destinations make narrow cells, and large text scales could
            // wrap or overflow a label. Keep it on one line in a fixed-height
            // box and shrink it to fit both ways.
            SizedBox(
              height: 16,
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  item.label,
                  maxLines: 1,
                  softWrap: false,
                  style: labelStyle.labelSmall?.copyWith(
                    color: color,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavigationItemIcon extends StatelessWidget {
  const _NavigationItemIcon({
    required this.item,
    required this.selected,
    required this.color,
  });

  final MayosNavItem item;
  final bool selected;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Widget glyph = AnimatedSwitcher(
      duration: MayosMotion.fast,
      child: Icon(
        selected ? item.selectedIcon : item.icon,
        key: ValueKey<bool>(selected),
        size: MayosIconSizes.navigation,
        color: color,
      ),
    );
    if (item.badge == 0 && item.dot) {
      return Badge(
        smallSize: 8,
        backgroundColor: c.accent,
        child: glyph,
      );
    }
    return Badge(
      isLabelVisible: item.badge > 0,
      label: Directionality(
        textDirection: TextDirection.ltr,
        child: Text('${item.badge}'),
      ),
      backgroundColor: c.danger,
      child: glyph,
    );
  }
}
