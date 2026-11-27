import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

enum MayosButtonVariant { primary, secondary, tertiary }

/// MAYOS action button.
///
/// Primary is a filled red CTA; secondary is outlined; tertiary is a quiet
/// text action. All variants keep a >=48dp target, show a pressed state, and
/// swap their label for a spinner while [loading].
///
/// [destructive] paints the button in the danger colour. Danger shares the
/// brand red (#885), so it is told apart by shape: on a screen a destructive
/// action is a secondary (outlined) or tertiary (text) button with an [icon];
/// only the final confirm button inside a confirm dialog or sheet is a filled
/// destructive primary.
class MayosButton extends StatelessWidget {
  const MayosButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = MayosButtonVariant.primary,
    this.icon,
    this.loading = false,
    this.expand = true,
    this.destructive = false,
    this.semanticsLabel,
  });

  final String label;
  final VoidCallback? onPressed;
  final MayosButtonVariant variant;
  final IconData? icon;
  final bool loading;
  final bool expand;
  final bool destructive;
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final bool enabled = onPressed != null && !loading;
    final MayosThemeExtension c = MayosTheme.of(context);
    final Widget child = loading
        ? SizedBox(
            height: 18,
            width: 18,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: variant == MayosButtonVariant.primary
                  ? (destructive ? c.onDanger : c.onAccent)
                  : (destructive ? c.danger : c.accent),
            ),
          )
        : _content(context);

    final Widget button = switch (variant) {
      MayosButtonVariant.primary => FilledButton(
          onPressed: enabled ? onPressed : null,
          style: destructive
              ? FilledButton.styleFrom(
                  backgroundColor: c.danger,
                  foregroundColor: c.onDanger,
                )
              : null,
          child: child,
        ),
      MayosButtonVariant.secondary => OutlinedButton(
          onPressed: enabled ? onPressed : null,
          style: destructive
              ? OutlinedButton.styleFrom(
                  foregroundColor: c.danger,
                  side: BorderSide(color: c.danger),
                )
              : null,
          child: child,
        ),
      MayosButtonVariant.tertiary => TextButton(
          onPressed: enabled ? onPressed : null,
          style: destructive
              ? TextButton.styleFrom(foregroundColor: c.danger)
              : null,
          child: child,
        ),
    };

    final Widget wrapped = semanticsLabel == null
        ? button
        : Semantics(label: semanticsLabel, button: true, child: button);

    if (!expand) {
      return wrapped;
    }
    return SizedBox(width: double.infinity, child: wrapped);
  }

  Widget _content(BuildContext context) {
    if (icon == null) {
      return Text(label);
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: <Widget>[
        Icon(icon, size: 18),
        const SizedBox(width: MayosSpacing.xs),
        Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
      ],
    );
  }
}
