import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_swap_copy.dart';
import '../../../core/food_swap_models.dart';
import '../../../core/planned_meals_models.dart';
import '../../../core/display_language/planned_meals_copy.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../providers.dart';
import 'food_restriction_badge.dart';

class FoodSwapSheet extends ConsumerStatefulWidget {
  const FoodSwapSheet({required this.target, super.key});
  final FoodSwapTarget target;

  @override
  ConsumerState<FoodSwapSheet> createState() => _FoodSwapSheetState();
}

class _FoodSwapSheetState extends ConsumerState<FoodSwapSheet> {
  final TextEditingController _query = TextEditingController();
  Timer? _debounce;
  int _request = 0;
  FoodSwapCandidates? _candidates;
  FoodSwapCandidate? _selected;
  String? _error;
  bool _loading = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _search();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _changed(String query) {
    _debounce?.cancel();
    _request++;
    setState(() {
      _selected = null;
      _candidates = null;
      _loading = true;
      _error = null;
    });
    _debounce = Timer(const Duration(milliseconds: 250), _search);
  }

  Future<void> _search() async {
    final int request = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final FoodSwapCandidates candidates = await ref
          .read(apiClientProvider)
          .foodSwapCandidates(widget.target, _query.text);
      if (mounted && request == _request)
        setState(() => _candidates = candidates);
    } on ApiException catch (error) {
      if (mounted && request == _request)
        setState(() => _error = error.message);
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (_saving || _selected == null) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .swapPlannedFood(widget.target, _selected!.food.id);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  PlannedMeal get _meal => widget.target.plan.meals
      .firstWhere((PlannedMeal meal) => meal.slot == widget.target.slot);
  PlannedFood get _food => _meal.foods
      .firstWhere((PlannedFood food) => food.role == widget.target.role);

  int get _calorieRange {
    // Practical portions can exceed the mockup's 40 kcal; show the real range.
    double range = 40;
    final FoodSwapCandidates? candidates = _candidates;
    if (candidates != null) {
      for (final FoodSwapCandidate candidate in <FoodSwapCandidate>[
        ...candidates.staples,
        ...candidates.search
      ]) {
        if (candidate.allowed &&
            (candidate.calories! - _meal.calories).abs() > range) {
          range = (candidate.calories! - _meal.calories).abs();
        }
      }
    }
    return (range / 10).ceil() * 10;
  }

  @override
  Widget build(BuildContext context) {
    final FoodSwapCopy copy = FoodSwapCopy(ref.watch(displayLanguageProvider));
    final String name =
        copy.isArabic ? _food.arabicName ?? _food.name : _food.name;
    final PlannedMealsCopy mealsCopy = PlannedMealsCopy(copy.languageCode);
    return PopScope(
        canPop: !_saving,
        child: Directionality(
            textDirection:
                copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
            child: SafeArea(
                child: Padding(
                    padding: EdgeInsets.only(
                        bottom: MediaQuery.viewInsetsOf(context).bottom),
                    child: SizedBox(
                        height: (MediaQuery.sizeOf(context).height * .85 -
                                MediaQuery.viewInsetsOf(context).bottom)
                            .clamp(0.0, double.infinity)
                            .toDouble(),
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: <Widget>[
                              Expanded(
                                  child: RadioGroup<String>(
                                      groupValue: _selected?.food.id,
                                      onChanged: (String? id) {
                                        if (_saving ||
                                            id == null ||
                                            _candidates == null) return;
                                        setState(() => _selected =
                                                <FoodSwapCandidate>[
                                              ..._candidates!.staples,
                                              ..._candidates!.search
                                            ].firstWhere((FoodSwapCandidate
                                                        candidate) =>
                                                    candidate.food.id == id));
                                      },
                                      child: ListView(
                                          padding: const EdgeInsets.symmetric(
                                              horizontal: 16),
                                          children: <Widget>[
                                            ListTile(
                                                contentPadding: EdgeInsets.zero,
                                                title:
                                                    Text(copy.swapFood(name)),
                                                trailing: IconButton(
                                                    tooltip: copy.close,
                                                    onPressed: _saving
                                                        ? null
                                                        : () => Navigator.of(
                                                                context)
                                                            .pop(),
                                                    icon: const Icon(
                                                        Icons.close))),
                                            Text(copy.staysWithin(
                                                _meal.name.isEmpty
                                                    ? mealsCopy.slot(_meal.slot)
                                                    : _meal.name,
                                                _calorieRange)),
                                            const SizedBox(
                                                height: MayosSpacing.xs),
                                            Text(copy.permanent,
                                                style: Theme.of(context)
                                                    .textTheme
                                                    .bodySmall),
                                            Card(
                                                shape:
                                                    const RoundedRectangleBorder(
                                                        borderRadius: MayosRadii
                                                            .mediumRadius),
                                                child: ListTile(
                                                    title: Text(name),
                                                    subtitle: Text(
                                                        '${copy.currentFood} \u00b7 ${mealsCopy.amount(_food.grams)}'))),
                                            Padding(
                                                padding:
                                                    const EdgeInsets.all(16),
                                                child: TextField(
                                                    key: const Key(
                                                        'food_swap_search'),
                                                    controller: _query,
                                                    enabled: !_saving,
                                                    onChanged: _changed,
                                                    decoration: InputDecoration(
                                                        labelText:
                                                            copy.searchHint,
                                                        prefixIcon: const Icon(
                                                            Icons.search),
                                                        border:
                                                            const OutlineInputBorder()))),
                                            if (_loading || _saving)
                                              const LinearProgressIndicator(),
                                            if (_error != null)
                                              Padding(
                                                  padding: const EdgeInsets
                                                      .symmetric(
                                                      horizontal: 16),
                                                  child: Text(_error!,
                                                      style: TextStyle(
                                                          color:
                                                              Theme.of(context)
                                                                  .colorScheme
                                                                  .error))),
                                            if (_error != null &&
                                                _candidates == null)
                                              TextButton(
                                                  onPressed:
                                                      _loading ? null : _search,
                                                  child: Text(copy.retry)),
                                            ..._results(copy),
                                          ]))),
                              Padding(
                                  padding: const EdgeInsets.all(16),
                                  child: FilledButton(
                                      key: const Key('save_food_swap'),
                                      onPressed: _saving ||
                                              _loading ||
                                              _selected == null
                                          ? null
                                          : _save,
                                      child: Text(copy.saveSwap))),
                              TextButton(
                                  onPressed: _saving
                                      ? null
                                      : () => Navigator.of(context).pop(false),
                                  child: Text(copy.cancel)),
                            ]))))));
  }

  List<Widget> _results(FoodSwapCopy copy) {
    if (_loading || _candidates == null) return const <Widget>[];
    return <Widget>[
      Text(copy.nextStaples, style: Theme.of(context).textTheme.titleMedium),
      if (_candidates!.staples.isEmpty) Text(copy.noStaples),
      for (final FoodSwapCandidate candidate in _candidates!.staples)
        _tile(candidate, copy, 'staple'),
      if (_query.text.trim().isNotEmpty) ...<Widget>[
        Text(copy.searchResults,
            style: Theme.of(context).textTheme.titleMedium),
        if (_candidates!.search.isEmpty) Text(copy.noResults),
        for (final FoodSwapCandidate candidate in _candidates!.search)
          _tile(candidate, copy, 'search'),
      ],
    ];
  }

  Widget _tile(FoodSwapCandidate candidate, FoodSwapCopy copy, String source) =>
      Card(
          shape: RoundedRectangleBorder(
              borderRadius: MayosRadii.mediumRadius,
              side: BorderSide(
                  color: _selected?.food.id == candidate.food.id
                      ? MayosTheme.of(context).selectedBorder
                      : MayosTheme.of(context).border)),
          child: ListTile(
            key: Key('food_swap_${source}_${candidate.food.id}'),
            selected: _selected?.food.id == candidate.food.id,
            leading: Radio<String>(
                value: candidate.food.id,
                enabled: candidate.allowed && !_saving),
            onTap: !candidate.allowed || _saving
                ? null
                : () => setState(() => _selected = candidate),
            title: Text(candidate.food.displayName(copy.isArabic)),
            subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  if (candidate.food.restrictionReasons.isNotEmpty)
                    FoodRestrictionBadge(
                        reasons: candidate.food.restrictionReasons, copy: copy),
                  if (candidate.allowed)
                    Text(copy.optionAmount(
                        candidate.grams!,
                        candidate.food.nutrients
                            .forGrams(candidate.grams!)
                            .kcal)),
                  Text(candidate.allowed
                      ? copy.preview(candidate.grams!, candidate.calories!,
                          candidate.protein!)
                      : copy.unavailableSwap),
                ]),
          ));
}
