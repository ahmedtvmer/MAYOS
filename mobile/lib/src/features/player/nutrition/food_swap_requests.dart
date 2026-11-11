import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/food_swap_request_copy.dart';
import '../../../core/models.dart';
import '../../../core/planned_meals_models.dart';
import '../../../providers.dart';
import '../tour/tour_targets.dart';

class FoodSwapRequestsEntry extends ConsumerWidget {
  const FoodSwapRequestsEntry({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final FoodSwapRequestCopy copy =
        FoodSwapRequestCopy(ref.watch(displayLanguageProvider));
    return IconButton(
      key: const Key('food_swap_requests_entry'),
      tooltip: copy.title,
      icon: const Icon(Icons.question_answer_outlined),
      onPressed: () => Navigator.of(context).push<void>(MaterialPageRoute<void>(
          builder: (_) => const FoodSwapRequestsScreen())),
    );
  }
}

class FoodSwapRequestsScreen extends ConsumerWidget {
  const FoodSwapRequestsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final FoodSwapRequestCopy copy =
        FoodSwapRequestCopy(ref.watch(displayLanguageProvider));
    return Directionality(
        textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
        child: Scaffold(
            appBar: AppBar(title: Text(copy.title)),
            body: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: TourTarget(
                    id: 'food_swap_requests',
                    child: Column(
                        key: const Key('food_swap_requests_history'),
                        children: <Widget>[
                          const PlayerFoodSwapRequests(),
                        ])))));
  }
}

class RequestFoodSwapDialog extends ConsumerStatefulWidget {
  const RequestFoodSwapDialog(
      {super.key,
      required this.plan,
      required this.meal,
      required this.foodIndex});
  final PlannedMeals plan;
  final PlannedMeal meal;
  final int foodIndex;
  @override
  ConsumerState<RequestFoodSwapDialog> createState() =>
      _RequestFoodSwapDialogState();
}

class _RequestFoodSwapDialogState extends ConsumerState<RequestFoodSwapDialog> {
  final TextEditingController _reason = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).requestFoodSwap(
          widget.plan, widget.meal, widget.foodIndex, _reason.text.trim());
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (error) {
      if (mounted)
        setState(() => _error = displayCopyOf(context)
            .failureMessage(mutationFailureMessage(error)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodSwapRequestCopy copy =
        FoodSwapRequestCopy(ref.watch(displayLanguageProvider));
    return Directionality(
        textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
        child: PopScope(
            canPop: !_busy,
            child: AlertDialog(
                title: Text(copy.request),
                content: SingleChildScrollView(
                    child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: <Widget>[
                      Text(copy.arabic
                          ? widget.meal.foods[widget.foodIndex].arabicName ??
                              widget.meal.foods[widget.foodIndex].name
                          : widget.meal.foods[widget.foodIndex].name),
                      TextField(
                          key: const Key('food_swap_request_reason'),
                          controller: _reason,
                          enabled: !_busy,
                          maxLength: 500,
                          maxLines: 3,
                          decoration: InputDecoration(labelText: copy.reason)),
                      if (_error != null)
                        Text(_error!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                    ])),
                actions: <Widget>[
                  TextButton(
                      onPressed: _busy ? null : () => Navigator.pop(context),
                      child: Text(copy.cancel)),
                  FilledButton(
                      key: const Key('send_food_swap_request'),
                      onPressed: _busy ? null : _send,
                      child: Text(copy.send)),
                ])));
  }
}

class PlayerFoodSwapRequests extends ConsumerStatefulWidget {
  const PlayerFoodSwapRequests({super.key, this.revision = 0, this.onRefresh});
  final int revision;
  final VoidCallback? onRefresh;
  @override
  ConsumerState<PlayerFoodSwapRequests> createState() =>
      _PlayerFoodSwapRequestsState();
}

class _PlayerFoodSwapRequestsState
    extends ConsumerState<PlayerFoodSwapRequests> {
  List<ProgramRequest>? _requests;
  String? _error;
  bool _busy = false;
  int _sequence = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(PlayerFoodSwapRequests oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.revision != oldWidget.revision) _load();
  }

  Future<void> _load() async {
    final int sequence = ++_sequence;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final List<ProgramRequest> requests =
          await ref.read(apiClientProvider).playerFoodSwapRequests();
      if (mounted && sequence == _sequence)
        setState(() => _requests = requests);
    } on ApiException catch (error) {
      if (mounted && sequence == _sequence)
        setState(() => _error =
            displayCopyOf(context).failureMessage(apiFailureMessage(error)));
    } finally {
      if (mounted && sequence == _sequence) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodSwapRequestCopy copy =
        FoodSwapRequestCopy(ref.watch(displayLanguageProvider));
    return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(copy.title, style: Theme.of(context).textTheme.titleMedium),
          TextButton(
              onPressed: _busy
                  ? null
                  : () async {
                      await _load();
                      if (mounted) widget.onRefresh?.call();
                    },
              child: Text(copy.refresh)),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) Text(_error!),
          if (_requests?.isEmpty == true) Text(copy.empty),
          for (final ProgramRequest request in _requests ?? <ProgramRequest>[])
            ListTile(
                key: Key('food_swap_request_${request.requestId}'),
                title: Text(copy.target(request.foodSwap!)),
                subtitle: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(copy.status(request.status)),
                      if (request.reason.isNotEmpty) Text(request.reason),
                      if (request.hasResponse)
                        Text('${copy.reply}: ${request.response}'),
                      if (request.status == 'closed') Text(copy.closeNote),
                    ])),
        ]);
  }
}
