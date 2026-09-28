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
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;

  /// A count badge shown on the icon (0 hides it), used by the coach shell's
  /// new-alerts count (#119).
  final int badge;
}

/// A deliberately restrained bottom bar: a thin top border over the surface,
/// two-or-more equal destinations, active state in MAYOS blue. Avoids the
/// default Material pill indicator so the shell reads as MAYOS.
class MayosBottomNavigation extends StatelessWidget {
  const MayosBottomNavigation({
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
    final TextTheme text = Theme.of(context).textTheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 62,
          child: Row(
            children: <Widget>[
              for (int i = 0; i < items.length; i++)
                Expanded(
                  child: _Destination(
                    item: items[i],
                    selected: i == index,
                    onTap: () => onSelected(i),
                    labelStyle: text,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Destination extends StatelessWidget {
  const _Destination({
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
    return Semantics(
      button: true,
      selected: selected,
      label: item.label,
      excludeSemantics: true,
      child: InkResponse(
        onTap: onTap,
        radius: 44,
        containedInkWell: true,
        highlightShape: BoxShape.rectangle,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            Badge(
              isLabelVisible: item.badge > 0,
              label: Text('${item.badge}'),
              backgroundColor: c.danger,
              child: AnimatedSwitcher(
                duration: MayosMotion.fast,
                child: Icon(
                  selected ? item.selectedIcon : item.icon,
                  key: ValueKey<bool>(selected),
                  size: 24,
                  color: color,
                ),
              ),
            ),
            const SizedBox(height: 3),
            // With three destinations the cells are narrow and large text
            // scales could wrap a label into a second line, overflowing the
            // fixed bar height. Keep labels on one line and shrink to fit.
            FittedBox(
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
          ],
        ),
      ),
    );
  }
}
