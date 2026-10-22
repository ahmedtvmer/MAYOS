import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';

/// Shows a scrollable form with actions fixed above the keyboard.
Future<T?> showMyosBottomSheetEditor<T>({
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
          duration: MyosMotion.base,
          curve: Curves.easeOut,
          padding: EdgeInsets.only(bottom: media.viewInsets.bottom),
          child: ConstrainedBox(
            constraints: BoxConstraints(maxHeight: media.size.height * 0.9),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Flexible(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(MyosSpacing.lg),
                    child: content,
                  ),
                ),
                SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.all(MyosSpacing.md),
                    child: actions,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
