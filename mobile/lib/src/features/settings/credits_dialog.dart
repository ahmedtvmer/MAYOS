import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/settings_copy.dart';
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
  final SettingsCopy copy = settingsCopyOf(context);
  return showDialog<void>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(copy.credits),
      content: Text(
        copy.creditsBody(gymVisualCredit),
        textAlign: copy.isArabic ? TextAlign.end : null,
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () async {
            final bool opened = await openUrl(gymVisualUrl);
            if (!opened && context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(copy.couldNotOpenCredits)),
              );
            }
          },
          child: const Text(
            'gymvisual.com',
            textDirection: TextDirection.ltr,
          ),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(copy.close),
        ),
      ],
    ),
  );
}
