import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';

/// The centred Player column shared by the app shell, auth, and onboarding.
class MyosPlayerColumn extends StatelessWidget {
  const MyosPlayerColumn({
    super.key,
    required this.child,
    this.constrained = true,
  });

  static const Key contentKey = ValueKey<String>('myos.playerColumn');

  final Widget child;
  final bool constrained;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: constrained
                ? MyosLayout.playerColumnMaxWidth
                : double.infinity,
          ),
          child: SizedBox(
            key: contentKey,
            width: double.infinity,
            child: child,
          ),
        ),
      );
}
