import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

class _DashboardData {
  const _DashboardData({required this.volume, required this.records});

  final Map<String, double> volume;
  final List<PersonalRecord> records;
}

class DashboardTab extends ConsumerStatefulWidget {
  const DashboardTab({super.key});

  @override
  ConsumerState<DashboardTab> createState() => _DashboardTabState();
}

class _DashboardTabState extends ConsumerState<DashboardTab> {
  late Future<_DashboardData> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<_DashboardData> _load() async {
    final ApiClient api = ref.read(apiClientProvider);
    final List<Object> results = await Future.wait<Object>(<Future<Object>>[
      api.volume(),
      api.personalRecords(),
    ]);
    return _DashboardData(
      volume: results[0] as Map<String, double>,
      records: results[1] as List<PersonalRecord>,
    );
  }

  Future<void> _refresh() async {
    final Future<_DashboardData> future = _load();
    setState(() => _future = future);
    await future;
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_DashboardData>(
      future: _future,
      builder: (BuildContext context, AsyncSnapshot<_DashboardData> snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          final Object error = snapshot.error!;
          final String message = error is ApiException
              ? error.message
              : 'Could not load your dashboard.';
          return _ErrorView(message: message, onRetry: _refresh);
        }
        final _DashboardData data = snapshot.data!;
        final double total =
            data.volume.values.fold<double>(0, (double a, double b) => a + b);
        final List<MapEntry<String, double>> muscles = data.volume.entries
            .where((MapEntry<String, double> entry) => entry.value > 0)
            .toList(growable: false)
          ..sort((MapEntry<String, double> a, MapEntry<String, double> b) =>
              b.value.compareTo(a.value));

        return RefreshIndicator(
          onRefresh: _refresh,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text('Weekly weighted sets',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 4),
                      Text(
                        '${total.toStringAsFixed(1)} sets',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text('Weighted sets by muscle',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (muscles.isEmpty)
                const Text('No sets logged in the last 7 days.')
              else
                ...muscles.map(
                  (MapEntry<String, double> entry) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(entry.key),
                    trailing: Text('${entry.value.toStringAsFixed(1)} sets'),
                  ),
                ),
              const SizedBox(height: 16),
              Text('Recent personal records',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (data.records.isEmpty)
                const Text('No personal records yet.')
              else
                ...data.records.map(
                  (PersonalRecord record) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(record.name),
                    subtitle: Text(record.recordType),
                    trailing: Text(
                      '${record.value.toStringAsFixed(1)} kg × ${record.reps}',
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: onRetry,
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}
