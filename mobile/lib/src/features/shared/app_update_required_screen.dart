import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/external_url_launcher.dart';
import '../../providers.dart';

class AppUpdateRequiredScreen extends ConsumerWidget {
  const AppUpdateRequiredScreen({super.key});

  static const Key storeButtonKey = Key('app_update_store');

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppVersionPolicy? update = ref.watch(appUpdateRequiredProvider);
    final copy = displayCopyOf(context);
    if (update == null) return const SizedBox.shrink();

    return PopScope<Object?>(
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Text(
                      copy.updateRequiredTitle,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      copy.updateRequiredMessage,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                    const SizedBox(height: 28),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        key: storeButtonKey,
                        onPressed: () async {
                          final bool opened =
                              await ref.read(externalUrlLauncherProvider)(
                            update.storeUrl,
                          );
                          if (!opened && context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(copy.updateStoreUnavailable),
                              ),
                            );
                          }
                        },
                        child: Text(copy.updateRequiredButton),
                      ),
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
