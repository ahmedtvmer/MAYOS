import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// A large, expressive selectable option.
///
/// Selection is one surface: an accent border, a subtle accent-tinted fill, and
/// a check indicator (animated 150–350ms). It deliberately paints no inner
/// panel and no drop shadow, so the selected state never reads as a second
/// rounded rectangle inside the card.
class MayosChoiceCard extends StatefulWidget {
  const MayosChoiceCard({
    super.key,
    required this.title,
    required this.selected,
    required this.onTap,
    this.subtitle,
    this.leading,
    this.trailing,
    this.padding = const EdgeInsets.all(MayosSpacing.md),
  });

  final String title;
  final String? subtitle;
  final bool selected;
  final VoidCallback? onTap;
  final Widget? leading;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  State<MayosChoiceCard> createState() => _MayosChoiceCardState();
}

class _MayosChoiceCardState extends State<MayosChoiceCard> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    final bool selected = widget.selected;
    final Color border = selected ? c.selectedBorder : c.border;
    final Color background = selected ? c.selectedSurface : c.surface;

    return Semantics(
      button: true,
      selected: selected,
      label: widget.subtitle == null
          ? widget.title
          : '${widget.title}. ${widget.subtitle}',
      excludeSemantics: true,
      child: AnimatedScale(
        scale: _pressed ? 0.985 : 1,
        duration: MayosMotion.fast,
        curve: MayosMotion.standard,
        child: AnimatedContainer(
          duration: MayosMotion.base,
          curve: MayosMotion.standard,
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: border, width: selected ? 1.6 : 1),
          ),
          clipBehavior: Clip.antiAlias,
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              onTap: widget.onTap,
              onHighlightChanged: (bool pressed) =>
                  setState(() => _pressed = pressed),
              splashFactory: NoSplash.splashFactory,
              highlightColor: Colors.transparent,
              hoverColor: Colors.transparent,
              focusColor: Colors.transparent,
              child: Padding(
                padding: widget.padding,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: <Widget>[
                    if (widget.leading != null) ...<Widget>[
                      widget.leading!,
                      const SizedBox(width: MayosSpacing.md),
                    ],
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(widget.title, style: text.titleMedium),
                          if (widget.subtitle != null) ...<Widget>[
                            const SizedBox(height: MayosSpacing.xxs),
                            Text(
                              widget.subtitle!,
                              style: text.bodySmall
                                  ?.copyWith(color: c.textSecondary),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(width: MayosSpacing.sm),
                    widget.trailing ??
                        AnimatedContainer(
                          duration: MayosMotion.base,
                          curve: MayosMotion.standard,
                          width: 24,
                          height: 24,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: selected ? c.accent : Colors.transparent,
                            border: Border.all(
                              color: selected ? c.accent : c.borderStrong,
                              width: 1.5,
                            ),
                          ),
                          child: selected
                              ? Icon(Icons.check, size: 16, color: c.onAccent)
                              : null,
                        ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
