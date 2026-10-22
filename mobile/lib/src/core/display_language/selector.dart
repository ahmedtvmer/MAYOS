import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../theme/myos_spacing.dart';
import 'catalog.dart';
import 'choices.dart';
import 'controller.dart';

class DisplayLanguageSelector extends ConsumerWidget {
  const DisplayLanguageSelector({super.key, this.compact = false});
  final bool compact;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final language = ref.watch(displayLanguageProvider);
    final MyosCopy copy = MyosCopy(language);
    return Align(
      alignment: AlignmentDirectional.centerEnd,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: kMyosMinTapTarget),
        child: DropdownButton<String>(
          key: const Key('display_language_selector'),
          value: language,
          isDense: compact,
          iconSize: compact ? MyosIconSizes.medium : MyosIconSizes.navigation,
          style: compact ? Theme.of(context).textTheme.bodySmall : null,
          underline: const SizedBox.shrink(),
          items: displayLanguageMenuItems(copy),
          onChanged: (value) {
            if (value != null) {
              ref.read(displayLanguageProvider.notifier).choose(value);
            }
          },
        ),
      ),
    );
  }
}
