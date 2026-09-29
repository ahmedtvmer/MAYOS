import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config.dart';
import '../../core/privacy_policy.dart';

/// The media credit, shown from Settings → About → Credits.
///
/// Gym visual's terms require the credit "© Gym visual —
/// https://gymvisual.com/" on every use of its images and GIFs, and the
/// 180×180 size limit that the exercise-detail hero honours. The owner's
/// 2026-09-29 decision shows the media pending MAYOS's own licence; the
/// notice lives here so the credit ships wherever the media does
/// (`docs/design-review/53/MEDIA-PROVENANCE.md`).
Future<void> showMediaCredits(BuildContext context, WidgetRef ref) {
  final UrlLauncherFn openUrl = ref.read(privacyUrlLauncherProvider);
  return showDialog<void>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: const Text('Credits'),
      content: Text(
        'Exercise media (the catalog pictures and GIFs) is credited as '
        'required by its terms:\n\n'
        '$gymVisualCredit\n\n'
        'The media is shown at its native size, never larger than 180 × 180, '
        'with this credit, while MAYOS\'s own licence from Gym visual is '
        'pending.',
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () async {
            final bool opened = await openUrl(gymVisualUrl);
            if (!opened && context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                    content: Text('Could not open gymvisual.com.')),
              );
            }
          },
          child: const Text('gymvisual.com'),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    ),
  );
}
