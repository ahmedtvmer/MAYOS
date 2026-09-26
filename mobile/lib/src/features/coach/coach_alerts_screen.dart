import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
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
    final Color color = switch (alert.state) {
      'new' => Theme.of(context).colorScheme.error,
      'acknowledged' => Colors.orange.shade800,
      _ => Theme.of(context).colorScheme.outline,
    };
    return Chip(
      label: Text(alert.stateLabel),
      labelStyle: TextStyle(color: color, fontSize: 12),
      visualDensity: VisualDensity.compact,
      side: BorderSide(color: color),
      backgroundColor: Colors.transparent,
    );
  }

  Widget _alertCard(BuildContext context, CoachAlert alert) {
    final bool busy = _busyAlertId == alert.alertId;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(alert.playerUsername,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                _stateChip(context, alert),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Missed ${alert.missedCount} expected training '
              '${alert.missedCount == 1 ? 'day' : 'days'} '
              '(${alert.streakStartDate} to ${alert.lastMissedDate})',
            ),
            if (alert.resolvedBy != null)
              Text('Resolved by ${alert.resolvedBy}',
                  style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            Row(
              children: <Widget>[
                if (alert.isNew)
                  TextButton(
                    onPressed: busy ? null : () => _acknowledge(alert),
                    child: const Text('Acknowledge'),
                  ),
                if (!alert.isResolved)
                  FilledButton(
                    onPressed: busy ? null : () => _resolve(alert),
                    child: const Text('Resolve'),
                  ),
                if (busy)
                  const Padding(
                    padding: EdgeInsets.only(left: 12),
                    child: SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
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
    final List<CoachAlert> visible = _alerts
        .where((CoachAlert alert) => _visibleStates.contains(alert.state))
        .toList(growable: false);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        Wrap(
          spacing: 8,
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
        const SizedBox(height: 12),
        if (visible.isEmpty)
          const Text('No alerts to show.')
        else
          for (final CoachAlert alert in visible) _alertCard(context, alert),
      ],
    );
  }
}
