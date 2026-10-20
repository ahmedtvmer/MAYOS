import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';

/// Shows a scrollable form with actions fixed above the keyboard.
Future<T?> showMayosBottomSheetEditor<T>({
  required BuildContext context,
  required Widget content,
  required Widget actions,
  bool useRootNavigator = false,
}) =>
    showModalBottomSheet<T>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      useRootNavigator: useRootNavigator,
      builder: (BuildContext context) {
        final MediaQueryData media = MediaQuery.of(context);
        return AnimatedPadding(
          duration: MayosMotion.base,
          curve: Curves.easeOut,
          padding: EdgeInsets.only(bottom: media.viewInsets.bottom),
          child: ConstrainedBox(
            constraints: BoxConstraints(maxHeight: media.size.height * 0.9),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Flexible(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(MayosSpacing.lg),
                    child: content,
                  ),
                ),
                SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.all(MayosSpacing.md),
                    child: actions,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
