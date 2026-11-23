import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/app_failure.dart';
import '../../../core/active_workout.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/api_client.dart';
import '../../../core/refetch_on_reconnect.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/effort.dart';
import '../../../core/config.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_segmented_control.dart';
import '../../../core/workout_equipment.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../tour/tour_targets.dart';
import '../workout/logger_card_widgets.dart' show ExerciseCatalogThumbnail;

const String _cableYRaiseDemoExerciseId = 'mayos:3';
const String _exerciseDemoTargetId = 'exercise_demo_media';

/// What the shared exercise screen offers besides reading it (#803).
enum ExerciseDetailOffer {
  /// Read only: Home, Progress, the exercise library, coach views.
  none,

  /// Program tab or workout logger: an Alternatives tab and
  /// "Swap this exercise", which hands [ExerciseDetailResult.swap] back to
  /// the caller so it opens its own existing swap flow.
  swap,

  /// A swap or add picker's preview: "Use this exercise", which hands
  /// [ExerciseDetailResult.use] back so the picker continues as before.
  use,
}

/// The action the Player chose on the screen; null when they went back.
enum ExerciseDetailResult { swap, use }

/// How one caller opens the single exercise screen. Every entry point (Home,
/// Program tab, logger, Progress, pickers, coach views) differs only here,
/// never in a copy of the screen (#803).
class ExerciseDetailOptions {
  const ExerciseDetailOptions({
    this.dayOrder,
    this.showProgram = true,
    this.showHistory = true,
    this.initialTab = 'overview',
    this.offer = ExerciseDetailOffer.none,
  });

  /// Reads the shared route's query (`/exercise/:id?day=&library=&coach=&tab=&offer=`).
  factory ExerciseDetailOptions.fromQuery(Map<String, String> query) =>
      ExerciseDetailOptions(
        dayOrder: int.tryParse(query['day'] ?? ''),
        showProgram: query['library'] != '1',
        showHistory: query['coach'] != '1',
        initialTab: query['tab'] ?? 'overview',
        offer: ExerciseDetailOffer.values.firstWhere(
          (ExerciseDetailOffer offer) => offer.name == query['offer'],
          orElse: () => ExerciseDetailOffer.none,
        ),
      );

  /// The program day the exercise was opened from. Null searches all days.
  final int? dayOrder;

  /// Whether this detail should load a matching program prescription.
  final bool showProgram;

  /// Whether this detail may read and show the signed-in account's history.
  final bool showHistory;

  /// Which tab to open on. Progress (#48) opens this screen on `history`.
  final String initialTab;

  final ExerciseDetailOffer offer;

  ExerciseDetailOptions copyWithOffer(ExerciseDetailOffer offer) =>
      ExerciseDetailOptions(
        dayOrder: dayOrder,
        showProgram: showProgram,
        showHistory: showHistory,
        initialTab: initialTab,
        offer: offer,
      );

  Map<String, String> toQuery() => <String, String>{
        if (dayOrder != null) 'day': '$dayOrder',
        if (!showProgram) 'library': '1',
        if (!showHistory) 'coach': '1',
        if (initialTab != 'overview') 'tab': initialTab,
        if (offer != ExerciseDetailOffer.none) 'offer': offer.name,
      };
}

/// The one way to open the exercise screen; resolves to the Player's choice.
Future<ExerciseDetailResult?> openExerciseDetail(
  BuildContext context,
  String exerciseId, [
  ExerciseDetailOptions options = const ExerciseDetailOptions(),
]) {
  if (GoRouter.maybeOf(context) == null) {
    // A dialog or screen built outside the app router still opens the same
    // screen, pushed directly.
    return Navigator.of(context).push<ExerciseDetailResult>(
      MaterialPageRoute<ExerciseDetailResult>(
        builder: (BuildContext context) =>
            ExerciseDetailScreen(exerciseId: exerciseId, options: options),
      ),
    );
  }
  final Map<String, String> query = options.toQuery();
  final String path = '$exerciseDetailPath/${Uri.encodeComponent(exerciseId)}';
  return context.push<ExerciseDetailResult>(
    query.isEmpty ? path : Uri(path: path, queryParameters: query).toString(),
  );
}

/// Exercise detail (#53): a typographic/muscle-group hero, the prescription
/// stat trio when opened from a program day, and Overview / Technique /
/// History tabs backed by real catalog and dashboard data, plus an
/// Alternatives tab or a "Use this exercise" button when the caller offers
/// one ([ExerciseDetailOffer]).
///
/// The hero stays fully useful without media; exercise media is gated behind
/// [mayosExerciseMediaEnabled] and a loadable URL.
class ExerciseDetailScreen extends ConsumerStatefulWidget {
  const ExerciseDetailScreen({
    super.key,
    required this.exerciseId,
    this.options = const ExerciseDetailOptions(),
  });

  final String exerciseId;
  final ExerciseDetailOptions options;

  int? get dayOrder => options.dayOrder;
  bool get showProgram => options.showProgram;
  bool get showHistory => options.showHistory;
  String get initialTab => options.initialTab;
  ExerciseDetailOffer get offer => options.offer;

  @override
  ConsumerState<ExerciseDetailScreen> createState() =>
      _ExerciseDetailScreenState();
}

class _DetailData {
  const _DetailData({
    required this.exercise,
    required this.catalog,
    required this.history,
    this.partialError,
  });

  final ProgramExercise? exercise;
  final ExerciseCatalogDetail? catalog;
  final ExerciseHistory? history;
  final FailureMessage? partialError;
}

class _ExerciseDetailScreenState extends ConsumerState<ExerciseDetailScreen>
    with RefetchOnReconnect<ExerciseDetailScreen> {
  @override
  Future<void> refreshAfterReconnect() => _retry();

  late Future<_DetailData> _future;
  late String _tab;
  late final StateController<Set<String>> _tourLoadingTargets;
  // Captured in initState: after dispose the `widget` getter is no longer
  // readable, but the post-frame cleanup below still runs.
  late final bool _demoTargetApplies;
  bool _demoTargetLoading = false;

  @override
  void initState() {
    super.initState();
    _tourLoadingTargets = ref.read(tourLoadingTargetsProvider.notifier);
    _demoTargetApplies = widget.exerciseId == _cableYRaiseDemoExerciseId;
    _tab = (!widget.showHistory && widget.initialTab == 'history') ||
            (widget.offer != ExerciseDetailOffer.swap &&
                widget.initialTab == 'alternatives')
        ? 'overview'
        : widget.initialTab;
    _scheduleDemoTargetLoading(true);
    _future = _load();
  }

  Future<_DetailData> _load() async {
    final ApiClient api = ref.read(apiClientProvider);
    ProgramExercise? exercise;
    ExerciseCatalogDetail? catalog;
    ExerciseHistory? history;
    FailureMessage? partialError;

    if (widget.showProgram) {
      try {
        exercise = _programExerciseForDay(
          await api.activeProgram(),
          widget.dayOrder,
        );
      } on ApiException catch (error) {
        partialError = apiFailureMessage(error);
      }
    }
    try {
      catalog = await api.exerciseCatalogDetail(widget.exerciseId);
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    if (widget.showHistory) {
      try {
        history = await api.exerciseHistory(widget.exerciseId);
      } on ApiException catch (error) {
        partialError ??= apiFailureMessage(error);
      }
    }

    final _DetailData loadedDetail = _DetailData(
      exercise: exercise,
      catalog: catalog,
      history: history,
      partialError: partialError,
    );
    if (!mayosExerciseMediaEnabled ||
        loadedDetail.catalog?.hasLoadableMedia != true) {
      _scheduleDemoTargetLoading(false);
    }
    return loadedDetail;
  }

  void _setDemoTargetLoading(bool isLoading) {
    if (!_demoTargetApplies ||
        _demoTargetLoading == isLoading ||
        !_tourLoadingTargets.mounted) {
      return;
    }
    _demoTargetLoading = isLoading;
    final Set<String> loadingTargets =
        Set<String>.of(_tourLoadingTargets.state);
    if (isLoading) {
      loadingTargets.add(_exerciseDemoTargetId);
    } else {
      loadingTargets.remove(_exerciseDemoTargetId);
    }
    _tourLoadingTargets.state = loadingTargets;
  }

  void _scheduleDemoTargetLoading(bool isLoading) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _setDemoTargetLoading(isLoading);
    });
  }

  ProgramExercise? _programExerciseForDay(
    TrainingProgram? program,
    int? dayOrder,
  ) {
    for (final ProgramDay day in program?.days ?? const <ProgramDay>[]) {
      if (dayOrder != null && day.dayOrder != dayOrder) continue;
      for (final ProgramExercise candidate in day.exercises) {
        if (candidate.exerciseId == widget.exerciseId) return candidate;
      }
    }
    return null;
  }

  Future<void> _retry() async {
    _scheduleDemoTargetLoading(true);
    final Future<_DetailData> future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }

  @override
  Widget build(BuildContext context) {
    return MayosScaffold(
      header: const MayosAppHeader(showBack: true),
      body: FutureBuilder<_DetailData>(
        future: _future,
        builder: (BuildContext context, AsyncSnapshot<_DetailData> snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _withBottomAction(
              context,
              _ErrorView(
                  message: displayCopyOf(context).loadExerciseFailed,
                  onRetry: _retry),
            );
          }
          final _DetailData data = snapshot.data!;
          if (data.catalog == null && data.exercise == null) {
            // A picker preview still lets the Player use the exercise when
            // its details cannot load, so a failed read never blocks a swap.
            return _withBottomAction(
              context,
              _ErrorView(
                message: data.partialError == null
                    ? displayCopyOf(context).exerciseUnavailable
                    : displayCopyOf(context).failureMessage(data.partialError!),
                onRetry: _retry,
              ),
            );
          }
          return _withBottomAction(context, _DetailBody(
              data: data,
              tab: _tab,
              showHistory: widget.showHistory,
              showAlternatives: widget.offer == ExerciseDetailOffer.swap,
              onOpenAlternative: _openAlternative,
              demoTargetId: _demoTargetApplies ? _exerciseDemoTargetId : null,
              onDemoMediaSettled:
                  _demoTargetApplies ? () => _setDemoTargetLoading(false) : null,
              onTab: (String tab) => setState(() => _tab = tab)));
        },
      ),
    );
  }

  Widget _withBottomAction(BuildContext context, Widget body) {
    final Widget? action = _bottomAction(context);
    if (action == null) return body;
    return Column(
      children: <Widget>[
        Expanded(child: body),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
                MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.lg, MayosSpacing.md),
            child: action,
          ),
        ),
      ],
    );
  }

  /// "Swap this exercise" on the Alternatives tab, or "Use this exercise" in
  /// a picker's preview; both hand the choice back to the caller (#803).
  Widget? _bottomAction(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    return switch (widget.offer) {
      ExerciseDetailOffer.swap when _tab == 'alternatives' => MayosButton(
          key: const ValueKey<String>('exercise.detail.swap'),
          label: copy.swapThisExercise,
          icon: Icons.swap_horiz,
          onPressed: () =>
              Navigator.of(context).pop(ExerciseDetailResult.swap),
        ),
      ExerciseDetailOffer.use => MayosButton(
          key: const ValueKey<String>('exercise.detail.use'),
          label: copy.useThisExercise,
          icon: Icons.check,
          onPressed: () => Navigator.of(context).pop(ExerciseDetailResult.use),
        ),
      _ => null,
    };
  }

  /// An alternative opens this same screen for it, read-only (#803).
  void _openAlternative(SuggestedSubstitute alternative) {
    unawaited(openExerciseDetail(
      context,
      alternative.exerciseId,
      const ExerciseDetailOptions(showProgram: false),
    ));
  }

  @override
  void dispose() {
    // Like Profile, the tour loading-provider cleanup is scheduled after the
    // frame instead of mutating a Riverpod provider while the tree tears
    // down; the provider's own `mounted` guard makes it safe when the app is
    // shutting down.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted || !_tourLoadingTargets.mounted) return;
      _setDemoTargetLoading(false);
    });
    super.dispose();
  }
}

class _DetailBody extends StatelessWidget {
  const _DetailBody({
    required this.data,
    required this.tab,
    required this.showHistory,
    required this.showAlternatives,
    required this.onOpenAlternative,
    required this.onTab,
    required this.demoTargetId,
    required this.onDemoMediaSettled,
  });

  final _DetailData data;
  final String tab;
  final bool showHistory;
  final bool showAlternatives;
  final ValueChanged<SuggestedSubstitute> onOpenAlternative;
  final ValueChanged<String> onTab;
  final String? demoTargetId;
  final VoidCallback? onDemoMediaSettled;

  @override
  Widget build(BuildContext context) {
    final ExerciseCatalogDetail? catalog = data.catalog;
    final ProgramExercise? exercise = data.exercise;
    final String name = catalog?.name ??
        exercise?.exerciseName ??
        displayCopyOf(context).exerciseFallbackName;

    return ListView(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.lg, MayosSpacing.xxl),
      children: <Widget>[
        _Hero(
          name: name,
          catalog: catalog,
          demoTargetId: demoTargetId,
          onDemoMediaSettled: onDemoMediaSettled,
        ),
        if (exercise != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xl),
          _PrescriptionTrio(exercise: exercise),
        ],
        if (data.partialError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          _InlineNotice(
            message: displayCopyOf(context).failureMessage(data.partialError!),
          ),
        ],
        const SizedBox(height: MayosSpacing.xl),
        MayosSegmentedControl<String>(
          segments: <MayosSegment<String>>[
            MayosSegment<String>(
                value: 'overview', label: displayCopyOf(context).overview),
            MayosSegment<String>(
                value: 'technique', label: displayCopyOf(context).technique),
            if (showHistory)
              MayosSegment<String>(
                  value: 'history', label: displayCopyOf(context).history),
            if (showAlternatives)
              MayosSegment<String>(
                  value: 'alternatives',
                  label: displayCopyOf(context).alternatives),
          ],
          selected: tab,
          onChanged: onTab,
        ),
        const SizedBox(height: MayosSpacing.xl),
        switch (tab) {
          'alternatives' when showAlternatives => _AlternativesTab(
              // The same list the swap picker suggests, so they agree (#803).
              alternatives: exercise?.suggestedSubstitutes ??
                  const <SuggestedSubstitute>[],
              onOpen: onOpenAlternative,
            ),
          'technique' => _TechniqueTab(catalog: catalog),
          'history' => _HistoryTab(
              history: data.history,
              equipment: catalog?.equipment ?? data.history?.equipment,
            ),
          _ => _OverviewTab(catalog: catalog, exercise: exercise),
        },
      ],
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({
    required this.name,
    required this.catalog,
    required this.demoTargetId,
    required this.onDemoMediaSettled,
  });

  final String name;
  final ExerciseCatalogDetail? catalog;
  final String? demoTargetId;
  final VoidCallback? onDemoMediaSettled;

  @override
  Widget build(BuildContext context) {
    final ExerciseCatalogDetail? detail = catalog;
    final MayosThemeExtension c = MayosTheme.of(context);

    // Media is gated behind the build flag (#53: off is the kill switch) and
    // a path `/media` can serve; with neither, today's typographic header is
    // the whole hero.
    if (mayosExerciseMediaEnabled &&
        detail != null &&
        detail.hasLoadableMedia) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // A fixed 180×180 box — Gym visual's native size, never upscaled
          // past it — so loading and failure states never shift the layout.
          Align(
            alignment: Alignment.center,
            child: _CatalogMedia(
              detail: detail,
              targetId: demoTargetId,
              onMediaSettled: onDemoMediaSettled,
            ),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            gymVisualCreditShort,
            textAlign: TextAlign.center,
            style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MayosSpacing.md),
          _typographicHeader(context, name, detail),
        ],
      );
    }

    return _typographicHeader(context, name, detail);
  }

  Widget _typographicHeader(
      BuildContext context, String name, ExerciseCatalogDetail? detail) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = displayCopyOf(context);
    final List<String> primary = <String>[
      if (detail?.primaryMuscle != null) detail!.primaryMuscle!,
      for (final String muscle in detail?.primaryMuscles ?? const <String>[])
        if (muscle.toLowerCase() != detail?.primaryMuscle?.toLowerCase())
          muscle,
    ];
    final Set<String> primaryLower =
        primary.map((String m) => m.toLowerCase()).toSet();
    // Secondary muscles only, without repeating a primary muscle.
    final List<String> secondary = <String>[
      for (final String muscle in detail?.secondaryMuscles ?? const <String>[])
        if (!primaryLower.contains(muscle.toLowerCase())) muscle,
    ];
    // Category/body part are the same field upstream; never repeat a label that
    // is already shown as a muscle chip.
    final String category = detail?.category ?? '';
    final bool showCategory = category.isNotEmpty &&
        !primaryLower.contains(category.toLowerCase()) &&
        !secondary
            .map((String m) => m.toLowerCase())
            .contains(category.toLowerCase());
    final String equipment = detail?.equipment ?? '';
    final String? primaryAction = detail?.primaryAction;
    final List<String> secondaryActions =
        detail?.secondaryActions ?? const <String>[];
    final bool hasChips = primary.isNotEmpty ||
        secondary.isNotEmpty ||
        showCategory ||
        equipment.isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          name,
          style: MayosTypography.of(context).display.copyWith(
            fontSize: 34,
            color: c.textPrimary,
          ),
        ),
        if (hasChips) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (final String muscle in primary)
                _TagChip(
                  label: muscle == detail?.primaryMuscle
                      ? copy.primaryMuscleLabel(muscle)
                      : titleCase(muscle),
                  tone: _ChipTone.primary,
                ),
              for (final String muscle in secondary)
                _TagChip(label: titleCase(muscle), tone: _ChipTone.secondary),
              if (showCategory)
                _TagChip(label: titleCase(category), tone: _ChipTone.secondary),
              if (equipment.isNotEmpty)
                _TagChip(
                  label: titleCase(equipment),
                  tone: _ChipTone.equipment,
                  icon: Icons.fitness_center,
                ),
            ],
          ),
        ],
        if (primaryAction != null || secondaryActions.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              if (primaryAction != null) ...<Widget>[
                Text(copy.primaryAction),
                _TagChip(
                  label: copy.primaryActionLabel(primaryAction),
                  tone: _ChipTone.primary,
                ),
              ],
              if (secondaryActions.isNotEmpty) ...<Widget>[
                Text(copy.secondaryActions),
                for (final String action in secondaryActions)
                  _TagChip(
                    label: copy.primaryActionLabel(action),
                    tone: _ChipTone.secondary,
                  ),
              ],
            ],
          ),
        ],
      ],
    );
  }
}

/// The catalog media in its fixed box (#53/#161): the animated GIF first,
/// the still picture when the GIF is missing or fails, then a calm glyph —
/// every state inside the same 180×180 footprint, centred, so loading and
/// failure never shift the layout.
class _CatalogMedia extends StatelessWidget {
  const _CatalogMedia({
    required this.detail,
    required this.targetId,
    required this.onMediaSettled,
  });

  /// Gym visual's native size: the box never grows past it and the picture
  /// is painted `contain` inside it, so the media is never stretched larger
  /// than 180×180 logical pixels either (Gym visual's terms).
  static const double size = 180;

  final ExerciseCatalogDetail detail;
  final String? targetId;
  final VoidCallback? onMediaSettled;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ClipRRect(
      borderRadius: MayosRadii.mediumRadius,
      child: SizedBox(
        width: size,
        height: size,
        child: ColoredBox(
          color: c.surfaceSunken,
          child: _gif(context, c),
        ),
      ),
    );
  }

  /// The GIF animates as any multi-frame network image does; a failed or
  /// absent GIF falls back to the still picture in the same box.
  Widget _gif(BuildContext context, MayosThemeExtension c) {
    final String? url = detail.gifUrl;
    if (url == null) {
      return _still(context, c);
    }
    return Image.network(
      url,
      width: size,
      height: size,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      frameBuilder: _frameBuilder,
      errorBuilder: (_, __, ___) => _still(context, c),
    );
  }

  Widget _still(BuildContext context, MayosThemeExtension c) {
    final String? url = detail.imageUrl;
    if (url == null) {
      _mediaSettled();
      return _fallback(context, c);
    }
    return Image.network(
      url,
      width: size,
      height: size,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      frameBuilder: _frameBuilder,
      errorBuilder: (_, __, ___) {
        _mediaSettled();
        return _fallback(context, c);
      },
    );
  }

  Widget _target(Widget child) {
    final String? id = targetId;
    assert(id == null || id == 'exercise_demo_media');
    return id == null
        ? child
        : TourTarget(
            // The feature-list validator discovers target ids by scanning the
            // source for a TourTarget registration whose id parameter is a
            // string literal before the child parameter, so this literal must
            // stay inline — do not swap it back for the
            // [_exerciseDemoTargetId] constant. `targetId` is only non-null
            // for the Cable Y-Raise demo, whose target is exercise_demo_media.
            id: 'exercise_demo_media',
            child: child,
          );
  }

  Widget _frameBuilder(
    BuildContext context,
    Widget child,
    int? frame,
    bool wasSynchronouslyLoaded,
  ) {
    final bool loaded = frame != null || wasSynchronouslyLoaded;
    if (frame == 0 || wasSynchronouslyLoaded) _mediaSettled();
    return loaded ? _target(child) : _placeholder(MayosTheme.of(context));
  }

  void _mediaSettled() {
    final VoidCallback? callback = onMediaSettled;
    if (callback == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) => callback());
  }

  /// A static glyph while the bytes arrive — never a spinner, so the screen
  /// keeps no animation running (#161).
  Widget _placeholder(MayosThemeExtension c) => ColoredBox(
        color: c.surfaceSunken,
        child: Center(
          child: Icon(
            Icons.image_outlined,
            size: MayosIconSizes.medium,
            color: c.textDisabled,
          ),
        ),
      );

  Widget _fallback(BuildContext context, MayosThemeExtension c) => ColoredBox(
        color: c.secondarySurface,
        child: Center(
          child: Icon(
            Icons.fitness_center,
            size: MayosIconSizes.large,
            color: c.textMuted,
            semanticLabel: displayCopyOf(context).exerciseMediaUnavailable,
          ),
        ),
      );
}

/// Chip emphasis: primary muscles highlighted, secondary muted, equipment
/// distinct with a small icon.
enum _ChipTone { primary, secondary, equipment }

class _TagChip extends StatelessWidget {
  const _TagChip({
    required this.label,
    this.tone = _ChipTone.secondary,
    this.icon,
  });

  final String label;
  final _ChipTone tone;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool highlighted = tone == _ChipTone.primary;
    final Color background = highlighted ? c.accentSubtle : c.secondarySurface;
    final Color foreground = highlighted ? c.accent : c.textSecondary;
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(MayosRadii.pill),
        border: Border.all(color: highlighted ? Colors.transparent : c.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (icon != null) ...<Widget>[
            Icon(icon, size: 13, color: foreground),
            const SizedBox(width: 4),
          ],
          Flexible(
            child: Text(
              label,
              style: MayosTypography.of(context)
                  .caption
                  .copyWith(color: foreground),
            ),
          ),
        ],
      ),
    );
  }
}

class _PrescriptionTrio extends StatelessWidget {
  const _PrescriptionTrio({required this.exercise});

  final ProgramExercise exercise;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: _PrescriptionStat(
            value: exercise.setGroups.length > 1
                ? exercise.prescriptionFor(
                    amrapLabel: displayCopyOf(context).amrapLabel,
                  )
                : '${exercise.targetSets} × '
                    '${exercise.targetRepsMin}–${exercise.targetRepsMax}',
            label: displayCopyOf(context).setsAndReps,
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: exercise.setGroups.length > 1
                ? displayCopyOf(context).rirPerSetGroup
                : 'RIR ${minRirLabel(exercise.targetRpe)}',
            label: displayCopyOf(context).intensity,
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: '${exercise.restSecondsOrDefault}s',
            label: displayCopyOf(context).rest,
          ),
        ),
      ],
    );
  }
}

class _PrescriptionStat extends StatelessWidget {
  const _PrescriptionStat({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: AlignmentDirectional.centerStart,
          child: Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              value,
              maxLines: 1,
              style:
                  MayosTypography.of(context).numericSmall.copyWith(color: c.textPrimary),
            ),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
        ),
      ],
    );
  }
}

class _OverviewTab extends StatelessWidget {
  const _OverviewTab({required this.catalog, required this.exercise});

  final ExerciseCatalogDetail? catalog;
  final ProgramExercise? exercise;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ExerciseCatalogDetail? detail = catalog;
    final ProgramExercise? ex = exercise;
    final String category = detail?.category ?? '';
    final String bodyPart = detail?.bodyPart ?? '';
    final bool categoryIsBodyPart = category.isNotEmpty &&
        bodyPart.isNotEmpty &&
        category.toLowerCase() == bodyPart.toLowerCase();
    final List<(String, String?)> rows = <(String, String?)>[
      if (category.isNotEmpty)
        (displayCopyOf(context).category, titleCase(category)),
      // Body part mirrors category upstream; show it only when it differs.
      if (bodyPart.isNotEmpty && !categoryIsBodyPart)
        (displayCopyOf(context).bodyPart, titleCase(bodyPart)),
      if (detail != null && detail.equipment.isNotEmpty)
        (displayCopyOf(context).equipment, titleCase(detail.equipment)),
      if (detail != null)
        (
          displayCopyOf(context).equipmentCategory,
          displayCopyOf(context).equipmentCategoryLabel(
            detail.equipmentCategory,
          ),
        ),
      if (detail?.loadType != null)
        (
          displayCopyOf(context).loadType,
          displayCopyOf(context).loadTypeLabel(detail!.loadType!),
        ),
      if (ex != null && ex.hasNotes) (displayCopyOf(context).notes, ex.notes),
    ];

    if (rows.isEmpty) {
      return _EmptyTab(
        message: displayCopyOf(context).noExerciseDetails,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        for (int i = 0; i < rows.length; i++) ...<Widget>[
          _DetailRow(label: rows[i].$1, value: rows[i].$2!),
          if (i < rows.length - 1)
            Divider(height: 1, thickness: 1, color: c.border),
        ],
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 108,
            child: Text(
              label,
              style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
            ),
          ),
        ],
      ),
    );
  }
}

class _TechniqueTab extends StatelessWidget {
  const _TechniqueTab({required this.catalog});

  final ExerciseCatalogDetail? catalog;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String? instructions = catalog?.instructions;
    if (instructions == null || instructions.trim().isEmpty) {
      return _EmptyTab(
        message: displayCopyOf(context).noInstructionsForExercise,
      );
    }
    final List<String> steps = instructions
        .split('\n')
        .map((String line) => line.trim())
        .where((String line) => line.isNotEmpty)
        .toList(growable: false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (int i = 0; i < steps.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                SizedBox(
                  width: 28,
                  child: Text(
                    '${i + 1}',
                    style: MayosTypography.of(context).numericSmall.copyWith(
                      color: c.accent,
                      fontSize: 15,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    steps[i],
                    style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _HistoryTab extends StatelessWidget {
  const _HistoryTab({required this.history, required this.equipment});

  final ExerciseHistory? history;
  final String? equipment;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    final List<ExerciseHistoryPoint> points =
        history?.history ?? const <ExerciseHistoryPoint>[];
    final ExerciseHistoryPoint? latest =
        points.isEmpty ? null : points.last;
    final bool latestZeroLoadUsesEquipmentLabel = latest != null &&
        zeroLoadLabelKind(latest.weightKg, equipment) != null;
    if (points.isEmpty) {
      return _EmptyTab(
        message: displayCopyOf(context).noExerciseHistory,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (history?.caption != null &&
            !latestZeroLoadUsesEquipmentLabel) ...<Widget>[
          Text(
            history!.caption!.replaceAll('**', ''),
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
        ],
        for (final ExerciseHistoryPoint point in points.reversed)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Row(
              children: <Widget>[
                SizedBox(
                  width: 88,
                  child: Text(
                    point.date,
                    textDirection: TextDirection.ltr,
                    style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
                  ),
                ),
                Expanded(
                  child: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      '${formatExerciseWeightWithUnit(
                        point.weightKg,
                        equipment: equipment,
                        languageCode: copy.languageCode,
                        unit: ' kg',
                      )} '
                      '× ${point.reps} @ RIR '
                      '${rirLabel(point.rpe)}',
                      style:
                          MayosTypography.of(context).body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ),
                if (zeroLoadLabelKind(point.weightKg, equipment) == null)
                  Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      'e1RM ${_trim(point.e1rm)}',
                      style: MayosTypography.of(context).caption
                          .copyWith(color: c.textSecondary),
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

/// The suggested substitutes, each opening its own exercise screen (#803).
class _AlternativesTab extends StatelessWidget {
  const _AlternativesTab({required this.alternatives, required this.onOpen});

  final List<SuggestedSubstitute> alternatives;
  final ValueChanged<SuggestedSubstitute> onOpen;

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    if (alternatives.isEmpty) {
      return _EmptyTab(message: copy.noSuggestedAlternatives);
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(copy.suggestedSubstitutes,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: c.textSecondary)),
        const SizedBox(height: MayosSpacing.xs),
        for (final SuggestedSubstitute alternative in alternatives)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
            child: Material(
              color: c.surface,
              borderRadius: BorderRadius.circular(12),
              child: InkWell(
                key: ValueKey<String>(
                    'exercise.alternative.${alternative.exerciseId}'),
                borderRadius: BorderRadius.circular(12),
                onTap: () => onOpen(alternative),
                child: Padding(
                  padding: const EdgeInsets.all(MayosSpacing.sm),
                  child: Row(
                    children: <Widget>[
                      ExerciseCatalogThumbnail(
                          imagePath: alternative.imagePath),
                      const SizedBox(width: MayosSpacing.sm),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Text(alternative.exerciseName,
                                style: MayosTypography.of(context).body),
                            if (_alternativeMeta(copy, alternative)
                                case final String meta)
                              Text(meta,
                                  style: MayosTypography.of(context)
                                      .caption
                                      .copyWith(color: c.textSecondary)),
                          ],
                        ),
                      ),
                      Icon(Icons.chevron_right, color: c.textMuted),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  String? _alternativeMeta(MayosCopy copy, SuggestedSubstitute alternative) {
    final List<String> parts = <String>[
      if (alternative.primaryMuscle?.trim().isNotEmpty == true)
        copy.primaryMuscleLabel(alternative.primaryMuscle!),
      if (alternative.equipment?.trim().isNotEmpty == true)
        titleCase(alternative.equipment!),
    ];
    return parts.isEmpty ? null : parts.join(' · ');
  }
}

class _EmptyTab extends StatelessWidget {
  const _EmptyTab({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.md),
      child: Text(
        message,
        style: MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
      ),
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(Icons.info_outline, size: 16, color: c.textSecondary),
        const SizedBox(width: MayosSpacing.xs),
        Expanded(
          child: Text(
            message,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
        ),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              message,
              textAlign: TextAlign.center,
              style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.md),
            FilledButton(
                onPressed: onRetry, child: Text(displayCopyOf(context).retry)),
          ],
        ),
      ),
    );
  }
}

String _trim(double value) => value == value.roundToDouble()
    ? value.round().toString()
    : value.toStringAsFixed(1);

/// Title-cases a catalog label for display ("barbell" → "Barbell",
/// "upper back" → "Upper Back"). Catalog values are stored lowercase.
String titleCase(String value) => value
    .split(' ')
    .where((String word) => word.isNotEmpty)
    .map((String word) =>
        '${word[0].toUpperCase()}${word.substring(1).toLowerCase()}')
    .join(' ');
