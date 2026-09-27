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

/// Coach alert centre (#31): lists missed expected-day alerts with their new /
/// acknowledged / resolved state and lets the coach acknowledge or resolve them.
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
  final Set<String> _visibleStates = <String>{'new', 'acknowledged'};
  List<CoachAlert> _alerts = <CoachAlert>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final List<CoachAlert> alerts =
          await ref.read(apiClientProvider).coachAlerts(states: _states);
      if (!mounted) return;
      setState(() {
        _alerts = alerts;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
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
      final CoachAlert updated = await action();
      if (!mounted) return;
      setState(() {
        _busyAlertId = null;
        _alerts = _alerts
            .map((CoachAlert row) =>
                row.alertId == updated.alertId ? updated : row)
            .toList(growable: false);
      });
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

  Widget _stateChip(BuildContext context, CoachAlert alert) {
    final MayosThemeExtension tokens = MayosTheme.of(context);
    final Color color = switch (alert.state) {
      'new' => tokens.danger,
      'acknowledged' => tokens.warning,
      _ => tokens.textMuted,
    };
    return Chip(
      label: Text(alert.stateLabel),
      labelStyle: MayosTypography.caption.copyWith(color: color),
      visualDensity: VisualDensity.compact,
      side: BorderSide(color: color),
      backgroundColor: Colors.transparent,
    );
  }

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
            Row(
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
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<CoachAlert> visible = _alerts
        .where((CoachAlert alert) => _visibleStates.contains(alert.state))
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
            for (final String state in _states)
              FilterChip(
                label: Text(state[0].toUpperCase() + state.substring(1)),
                selected: _visibleStates.contains(state),
                onSelected: (bool selected) => setState(() {
                  if (selected) {
                    _visibleStates.add(state);
                  } else {
                    _visibleStates.remove(state);
                  }
                }),
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
