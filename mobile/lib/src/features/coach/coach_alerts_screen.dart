import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_shared.dart';

/// Coach alert centre (#31): lists missed expected-day alerts with their new /
/// acknowledged / resolved state and lets the coach acknowledge or resolve
/// them. It is the Alerts tab of the Coach mode shell (#119); resolved alerts
/// stay hidden behind the "Show resolved" filter, and the tab publishes the
/// new-alert count for the shell's badge.
class CoachAlertsScreen extends ConsumerStatefulWidget {
  const CoachAlertsScreen({super.key});

  @override
  ConsumerState<CoachAlertsScreen> createState() => _CoachAlertsScreenState();
}

class _CoachAlertsScreenState extends ConsumerState<CoachAlertsScreen> {
  static const List<String> _states = <String>[
    'new',
    'acknowledged',
    'resolved',
  ];

  bool _loading = true;
  String? _error;
  String? _busyAlertId;
  bool _showResolved = false;
  List<CoachAlert> _alerts = <CoachAlert>[];

  /// Bumped by every load so a slower, older response can never overwrite a
  /// newer one when revision bumps start overlapping loads (#120).
  int _loadSeq = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Publishes the new-alert count so the shell's badge tracks every change
  /// made here without a second fetch (#119).
  void _publishNewCount() {
    ref.read(coachNewAlertsCountProvider.notifier).state =
        _alerts.where((CoachAlert alert) => alert.isNew).length;
  }

  Future<void> _load({bool showLoader = true}) async {
    final int seq = ++_loadSeq;
    if (showLoader) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final List<CoachAlert> alerts =
          await ref.read(apiClientProvider).coachAlerts(states: _states);
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _alerts = alerts;
        _loading = false;
      });
      _publishNewCount();
    } on ApiException catch (error) {
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _apply(
    CoachAlert alert,
    Future<CoachAlert> Function() action,
  ) async {
    setState(() {
      _busyAlertId = alert.alertId;
      _error = null;
    });
    try {
      final CoachAlert updated = await applyCoachAlertAction(
        ref,
        action,
        wasNew: alert.isNew,
      );
      if (!mounted) return;
      setState(() {
        _busyAlertId = null;
        _alerts = _alerts
            .map((CoachAlert row) =>
                row.alertId == updated.alertId ? updated : row)
            .toList(growable: false);
      });
      _publishNewCount();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busyAlertId = null;
        _error = error.message;
      });
    }
  }

  Future<void> _acknowledge(CoachAlert alert) => _apply(
        alert,
        () => ref.read(apiClientProvider).acknowledgeCoachAlert(alert.alertId),
      );

  Future<void> _resolve(CoachAlert alert) => _apply(
        alert,
        () => ref.read(apiClientProvider).resolveCoachAlert(alert.alertId),
      );

  Widget _stateChip(BuildContext context, CoachAlert alert) =>
      coachAlertStateChip(context, alert);

  Widget _alertCard(BuildContext context, CoachAlert alert) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool busy = _busyAlertId == alert.alertId;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    alert.playerUsername,
                    style: MayosTypography.exerciseTitle
                        .copyWith(color: c.textPrimary),
                  ),
                ),
                _stateChip(context, alert),
              ],
            ),
            const SizedBox(height: MayosSpacing.xxs),
            Text(alert.description,
                style: MayosTypography.body.copyWith(color: c.textPrimary)),
            if (alert.resolvedBy != null)
              Text(
                'Resolved by ${alert.resolvedBy}',
                style: MayosTypography.caption.copyWith(color: c.textMuted),
              ),
            const SizedBox(height: MayosSpacing.xs),
            // Wraps so both actions fit on a narrow phone (390 dp).
            Wrap(
              spacing: MayosSpacing.xs,
              runSpacing: MayosSpacing.xs,
              children: <Widget>[
                if (alert.isNew)
                  MayosButton(
                    label: 'Acknowledge',
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : () => _acknowledge(alert),
                  ),
                if (!alert.isResolved)
                  MayosButton(
                    label: 'Resolve',
                    expand: false,
                    loading: busy,
                    onPressed: busy ? null : () => _resolve(alert),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // The player page acknowledged or resolved one of these alerts: refetch
    // so this list and the tab badge track it (#120). The player page bumps
    // the revision and this tab never does, so the listener cannot loop.
    ref.listen<int>(coachAlertsRevisionProvider, (int? previous, int next) {
      if (previous != next) {
        _load(showLoader: false);
      }
    });
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<CoachAlert> visible = _alerts
        .where((CoachAlert alert) => _showResolved || !alert.isResolved)
        .toList(growable: false);
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Text(
              _error!,
              style: MayosTypography.bodySecondary.copyWith(color: c.danger),
            ),
          ),
        Wrap(
          spacing: MayosSpacing.xs,
          children: <Widget>[
            FilterChip(
              label: const Text('Show resolved'),
              selected: _showResolved,
              onSelected: (bool selected) =>
                  setState(() => _showResolved = selected),
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (visible.isEmpty)
          Text('No alerts to show.',
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary))
        else
          for (final CoachAlert alert in visible) _alertCard(context, alert),
      ],
    );
  }
}
