// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// Variant B — "Focus": one exercise per page (swipe between them). The
// current set is a big card with giant weight/reps tiles, one-tap RIR chips
// and a full-width Complete button. During rest the card becomes a large
// countdown ring. The exercise's other sets sit in a compact list below.

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../../core/theme/mayos_spacing.dart';
import '../../../../core/theme/mayos_theme.dart';
import '../../../../core/theme/mayos_typography.dart';
import 'prototype_logger_model.dart';
import 'prototype_logger_widgets.dart';

class VariantBFocus extends StatefulWidget {
  const VariantBFocus({super.key, required this.session});
  static const String label = 'Focus';
  final ProtoSession session;

  @override
  State<VariantBFocus> createState() => _VariantBFocusState();
}

class _VariantBFocusState extends State<VariantBFocus> {
  final PageController _pages = PageController();
  int _page = 0;
  ProtoFocus? _focus;

  /// A set the player tapped in the list to edit; otherwise the first
  /// unticked set of the page's exercise.
  final Map<ProtoExercise, ProtoSet> _selected = <ProtoExercise, ProtoSet>{};

  ProtoSession get s => widget.session;

  ProtoSet? _current(ProtoExercise ex) {
    final ProtoSet? sel = _selected[ex];
    if (sel != null && ex.sets.contains(sel)) return sel;
    for (final ProtoSet set in ex.sets) {
      if (!set.done) return set;
    }
    return null;
  }

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ListenableBuilder(
      listenable: s,
      builder: (BuildContext context, _) => Column(children: <Widget>[
        _pager(context, c),
        Expanded(
          child: PageView(
            controller: _pages,
            onPageChanged: (int p) => setState(() {
              _page = p;
              _focus = null;
            }),
            children: <Widget>[
              for (final ProtoExercise ex in s.exercises) _exercisePage(context, c, ex),
            ],
          ),
        ),
        if (_focus != null)
          ProtoKeypad(
            session: s,
            focus: _focus!,
            compact: true,
            onFocus: (ProtoFocus? f) => setState(() {
              // Focus mode never walks off into the next set: RIR ends here.
              _focus = f != null && f.set != _focus!.set ? null : f;
            }),
          ),
      ]),
    );
  }

  Widget _pager(BuildContext context, MayosThemeExtension c) {
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: <Widget>[
          for (int i = 0; i < s.exercises.length; i++)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                label: Text('${s.exercises[i].name.split(' ').first} '
                    '${s.exercises[i].doneCount}/${s.exercises[i].sets.length}'),
                selected: i == _page,
                onSelected: (_) => _pages.animateToPage(i,
                    duration: MayosMotion.base, curve: MayosMotion.standard),
              ),
            ),
          ActionChip(
            avatar: const Icon(Icons.add, size: 18),
            label: const Text('Exercise'),
            onPressed: () async {
              final ProtoExercise? ex = await showAddExercise(context, s);
              if (ex != null) {
                WidgetsBinding.instance.addPostFrameCallback((_) =>
                    _pages.animateToPage(s.exercises.length - 1,
                        duration: MayosMotion.base, curve: MayosMotion.standard));
              }
            },
          ),
          const SizedBox(width: 6),
          ActionChip(
            label: const Text('Finish'),
            onPressed: () => showFinish(context, s),
          ),
        ],
      ),
    );
  }

  Widget _exercisePage(BuildContext context, MayosThemeExtension c, ProtoExercise ex) {
    final ProtoSet? cur = _current(ex);
    final bool resting = s.rest != null && s.rest!.exercise == ex;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: <Widget>[
        Row(children: <Widget>[
          Expanded(
            child: Text(ex.name, style: MayosTypography.pageHeading),
          ),
          if (!ex.planned)
            Text('Unplanned',
                style: MayosTypography.caption.copyWith(color: c.textMuted)),
          IconButton(
            tooltip: 'Rest timer',
            onPressed: () => showRestPicker(context, s, ex),
            icon: const Icon(Icons.timer_outlined),
          ),
        ]),
        const SizedBox(height: 8),
        if (resting)
          _restCard(c, s.rest!, ex, cur)
        else if (cur != null)
          _setCard(c, ex, cur)
        else
          _doneCard(c, ex),
        const SizedBox(height: 16),
        for (int i = 0; i < ex.sets.length; i++) _setLine(c, ex, i, cur),
        TextButton.icon(
          style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
          onPressed: () => s.addSet(ex),
          icon: const Icon(Icons.add),
          label: const Text('Add set'),
        ),
      ],
    );
  }

  Widget _setCard(MayosThemeExtension c, ProtoExercise ex, ProtoSet set) {
    final int i = ex.sets.indexOf(set);
    final ProtoPrevSet? prev = ex.previousFor(i);
    Widget tile(String caption, ProtoField field, String? value, String? hint) {
      final bool focused = _focus?.set == set && _focus?.field == field;
      return Expanded(
        child: Material(
          color: focused ? c.selectedSurface : c.surfaceSunken,
          shape: RoundedRectangleBorder(
            borderRadius: MayosRadii.largeRadius,
            side: BorderSide(
                color: focused ? c.selectedBorder : Colors.transparent, width: 2),
          ),
          child: InkWell(
            borderRadius: MayosRadii.largeRadius,
            onTap: () => setState(() => _focus = ProtoFocus(ex, set, field)),
            child: SizedBox(
              height: 104,
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: <Widget>[
                Text(value ?? hint ?? '–',
                    style: MayosTypography.numeric.copyWith(
                        fontSize: 44,
                        color: value == null ? c.textDisabled : c.textPrimary)),
                Text(caption,
                    style: MayosTypography.caption.copyWith(color: c.textMuted)),
              ]),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: MayosRadii.xlargeRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
        Text('SET ${i + 1} OF ${ex.sets.length}'
            '${set.done ? ' · done' : ''}',
            style: MayosTypography.label.copyWith(color: c.textMuted)),
        Text(prev == null ? 'First time: this sets your baseline' : 'Last time ${prev.label}',
            style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary)),
        const SizedBox(height: 12),
        Row(children: <Widget>[
          tile('kg', ProtoField.kg, set.kg == null ? null : fmtKg(set.kg!),
              prev == null ? null : fmtKg(prev.kg)),
          const SizedBox(width: 12),
          tile('reps', ProtoField.reps, set.reps?.toString(), prev?.reps.toString()),
        ]),
        const SizedBox(height: 12),
        Text('Reps in reserve',
            style: MayosTypography.caption.copyWith(color: c.textMuted)),
        const SizedBox(height: 4),
        Row(children: <Widget>[
          for (final int? v in <int?>[0, 1, 2, 3, 4, 5, null])
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: ChoiceChip(
                  showCheckmark: false,
                  labelPadding: EdgeInsets.zero,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  label: SizedBox(
                      width: double.infinity,
                      child: Text(v?.toString() ?? '–', textAlign: TextAlign.center)),
                  selected: set.rir == v,
                  onSelected: (_) => s.setRir(set, v),
                ),
              ),
            ),
        ]),
        const SizedBox(height: 16),
        FilledButton.icon(
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(64),
            backgroundColor: set.done ? c.surfaceSunken : c.success,
            foregroundColor: set.done ? c.textPrimary : c.onSuccess,
          ),
          onPressed: () => setState(() {
            if (!s.toggle(ex, set)) {
              _focus = ProtoFocus(ex, set, ProtoField.kg);
              return;
            }
            _focus = null;
            _selected.remove(ex);
          }),
          icon: Icon(set.done ? Icons.undo : Icons.check, size: 28),
          label: Text(set.done ? 'Untick set' : 'Complete set',
              style: MayosTypography.label.copyWith(fontSize: 18, color: set.done ? c.textPrimary : c.onSuccess)),
        ),
      ]),
    );
  }

  Widget _restCard(MayosThemeExtension c, ProtoRest r, ProtoExercise ex, ProtoSet? next) {
    final ProtoSet? last = ex.sets
        .where((ProtoSet x) => x.done)
        .fold<ProtoSet?>(null, (ProtoSet? a, ProtoSet b) => a == null || b.doneSeq > a.doneSeq ? b : a);
    final List<Widget> badges = last == null ? <Widget>[] : protoBadges(s, last);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: MayosRadii.xlargeRadius,
        border: Border.all(color: c.accent),
      ),
      child: Column(children: <Widget>[
        if (badges.isNotEmpty) Wrap(spacing: 6, children: badges),
        const SizedBox(height: 8),
        SizedBox(
          width: 180,
          height: 180,
          child: CustomPaint(
            painter: _RingPainter(
                r.total == 0 ? 0 : r.remaining / r.total, c.accent, c.surfaceSunken),
            child: Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
                Text(fmtClock(r.remaining),
                    style: MayosTypography.numeric.copyWith(fontSize: 44)),
                Text('rest', style: MayosTypography.caption.copyWith(color: c.textMuted)),
              ]),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Row(children: <Widget>[
          Expanded(
              child: OutlinedButton(
                  style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  onPressed: () => s.adjustRest(-15),
                  child: const Text('−15 s'))),
          const SizedBox(width: 8),
          Expanded(
              child: OutlinedButton(
                  style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  onPressed: () => s.adjustRest(15),
                  child: const Text('+15 s'))),
          const SizedBox(width: 8),
          Expanded(
              child: FilledButton(
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  onPressed: s.skipRest,
                  child: const Text('Skip'))),
        ]),
        if (next != null) ...<Widget>[
          const SizedBox(height: 12),
          Text('Up next: set ${ex.sets.indexOf(next) + 1}'
              '${ex.previousFor(ex.sets.indexOf(next)) == null ? '' : ' · last ${ex.previousFor(ex.sets.indexOf(next))!.label}'}',
              style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary)),
        ],
      ]),
    );
  }

  Widget _doneCard(MayosThemeExtension c, ProtoExercise ex) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: MayosRadii.xlargeRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(children: <Widget>[
        Icon(Icons.check_circle, color: c.success, size: 40),
        const SizedBox(height: 8),
        Text('All ${ex.sets.length} sets done', style: MayosTypography.sectionHeading),
        const SizedBox(height: 8),
        if (_page < s.exercises.length - 1)
          FilledButton(
            onPressed: () => _pages.nextPage(
                duration: MayosMotion.base, curve: MayosMotion.standard),
            child: const Text('Next exercise'),
          ),
      ]),
    );
  }

  Widget _setLine(MayosThemeExtension c, ProtoExercise ex, int i, ProtoSet? cur) {
    final ProtoSet set = ex.sets[i];
    final ProtoPrevSet? prev = ex.previousFor(i);
    final bool isCur = set == cur;
    return Material(
      color: isCur ? c.selectedSurface : Colors.transparent,
      borderRadius: MayosRadii.mediumRadius,
      child: InkWell(
        borderRadius: MayosRadii.mediumRadius,
        onTap: () => setState(() {
          _selected[ex] = set;
          _focus = null;
          if (s.rest?.exercise == ex) s.skipRest();
        }),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 52),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(children: <Widget>[
              SizedBox(
                width: 28,
                child: Text('${i + 1}', style: MayosTypography.numericSmall),
              ),
              Expanded(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text(
                      set.done
                          ? '${fmtKg(set.kg!)} kg × ${set.reps}${set.rir == null ? '' : ' @${set.rir}'}'
                          : (prev == null ? 'not logged' : 'last ${prev.label}'),
                      style: set.done
                          ? MayosTypography.body
                          : MayosTypography.bodySecondary.copyWith(color: c.textMuted),
                    ),
                    ...protoBadges(s, set),
                  ],
                ),
              ),
              Icon(set.done ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: set.done ? c.success : c.textDisabled),
            ]),
          ),
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.progress, this.color, this.track);
  final double progress;
  final Color color;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    final Rect rect = Offset.zero & size;
    final Paint base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 12
      ..color = track;
    final Paint arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 12
      ..strokeCap = StrokeCap.round
      ..color = color;
    canvas.drawArc(rect.deflate(6), 0, math.pi * 2, false, base);
    canvas.drawArc(rect.deflate(6), -math.pi / 2,
        math.pi * 2 * progress.clamp(0, 1), false, arc);
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.progress != progress;
}
