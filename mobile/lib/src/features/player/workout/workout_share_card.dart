import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';

import '../../../core/display_language/workout_copy.dart';
import '../../../core/analytics_client.dart';
import '../../../core/models.dart';
import '../../../core/personal_records.dart';
import '../../../core/ui/mayos_logo.dart';
import 'workout_card_action_adapter.dart';
import 'workout_card_action_platform.dart';
import 'workout_photo_adapter.dart';

class WorkoutShareFlowFeedback {
  WorkoutShareFlowFeedback({
    required this.overlay,
    required this.analytics,
    required this.source,
    required this.languageCode,
  });

  final OverlayState overlay;
  final AnalyticsClient analytics;
  final String source;
  final String languageCode;
  bool _reportedFailure = false;
  OverlayEntry? _preparingOverlay;

  void showPreparing() {
    if (!overlay.mounted || _preparingOverlay != null) return;
    final bool arabic = WorkoutCopy(languageCode).isArabic;
    _preparingOverlay = OverlayEntry(builder: (BuildContext context) =>
      Positioned.fill(child: Stack(children: <Widget>[
        const ModalBarrier(dismissible: false, color: Color(0xc9070f1a)),
        Center(child: Column(mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const CircularProgressIndicator(color: Color(0xff2F6BFF)),
            const SizedBox(height: 16),
            Text(arabic ? 'جارٍ تجهيز البطاقة…' : 'Preparing your card…',
              style: const TextStyle(color: Colors.white, fontSize: 16)),
          ])),
      ])));
    overlay.insert(_preparingOverlay!);
  }

  void dismissPreparing() {
    _preparingOverlay?.remove();
    _preparingOverlay = null;
  }

  void failed(String stage, Object error) {
    if (_reportedFailure) return;
    _reportedFailure = true;
    dismissPreparing();
    analytics.shareCardFailed(source: source, stage: stage,
        errorType: shareErrorCategory(error));
  }
}

/// A stable, message-free name for a share failure. Release web builds minify
/// class names (`runtimeType` reads `minified:K1`), so known types map to fixed
/// categories; a browser DOMException contributes only its standard name
/// (e.g. `SecurityError`), never its message.
String shareErrorCategory(Object error) {
  if (error is TimeoutException) return 'timeout';
  if (error is PlatformException) return 'platform';
  if (error is StateError) return 'state';
  if (error is FormatException) return 'format';
  if (error is ArgumentError) return 'argument';
  if (error is Exception) return 'exception';
  if (error is Error) return 'error';
  if (error is String) return 'string';
  final RegExpMatch? named =
      RegExp(r'^([A-Z][A-Za-z]*(?:Error|Exception))\b').firstMatch(error.toString());
  return named?.group(1) ?? 'object';
}

class WorkoutShareFlowGuard {
  static bool _inFlight = false;

  static Future<void> run(Future<void> Function() flow) async {
    if (_inFlight) return;
    _inFlight = true;
    try {
      await flow();
    } finally {
      _inFlight = false;
    }
  }
}

/// A device-rendered 9:16 workout card. Its inputs are the immutable summary
/// captured when Finish was tapped; sensitive profile and cardio calorie data
/// are deliberately not inputs to this view.
class WorkoutShareCard extends StatelessWidget {
  const WorkoutShareCard({
    required this.languageCode,
    required this.dayName,
    this.duration,
    required this.stats,
    required this.records,
    this.prCount,
    this.photoBytes,
    this.photoFile,
    this.performedDate,
    this.feedback,
    this.captureOverlay,
    super.key,
  });

  final String languageCode;
  final String? dayName;
  final Duration? duration;
  final WorkoutSummaryStats stats;
  final List<WorkoutRecord> records;
  final int? prCount;
  final Uint8List? photoBytes;
  final XFile? photoFile;
  final DateTime? performedDate;
  final WorkoutShareFlowFeedback? feedback;
  final OverlayState? captureOverlay;

  WorkoutShareCard withPhotoBytes(Uint8List? bytes) => WorkoutShareCard(
    languageCode: languageCode,
    dayName: dayName,
    duration: duration,
    stats: stats,
    records: records,
    prCount: prCount,
    photoBytes: bytes,
    performedDate: performedDate,
    feedback: feedback,
    captureOverlay: captureOverlay,
  );

  Future<WorkoutShareCard> withPreparedPhoto(
      Future<Uint8List> Function(XFile) preparePhoto) async {
    if (photoBytes != null || photoFile == null) return this;
    try {
      return withPhotoBytes(await preparePhoto(photoFile!));
    } on Object catch (error) {
      feedback?.failed('decode_error', error);
      rethrow;
    }
  }

  bool get _arabic => languageCode == 'ar';
  WorkoutCopy get _copy => WorkoutCopy(languageCode);

  TextStyle get _valueStyle => TextStyle(color: Colors.white,
      fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Montserrat', fontSize: 24.3,
      fontWeight: FontWeight.w700);

  /// Arabic duration drawn as separate pieces in a fixed left-to-right row, so
  /// each unit sits left of its number (د 12  س 1) whatever the text engine's
  /// bidi ordering does with mixed Arabic letters and Latin digits.
  Widget _arabicDurationValue() {
    final int minutes = duration!.inMinutes;
    final int hours = minutes ~/ 60;
    final int remainder = minutes % 60;
    Widget piece(String text) => Text(text, maxLines: 1, style: _valueStyle);
    List<Widget> part(String unit, int number) =>
        <Widget>[piece(unit), const SizedBox(width: 2), piece('$number')];
    return Row(mainAxisSize: MainAxisSize.min, textDirection: ui.TextDirection.ltr,
      children: <Widget>[
        if (hours == 0 || remainder > 0) ...part('د', hours == 0 ? minutes : remainder),
        if (hours > 0 && remainder > 0) const SizedBox(width: 8),
        if (hours > 0) ...part('س', hours),
      ]);
  }

  String? get _duration {
    final Duration? elapsed = duration;
    if (elapsed == null) return null;
    final int minutes = elapsed.inMinutes;
    if (minutes >= 60) {
      final int hours = minutes ~/ 60;
      final int remainder = minutes % 60;
      return '$hours${_arabic ? 'س' : 'h'}${remainder == 0 ? '' : ' $remainder${_arabic ? 'د' : 'm'}'}';
    }
    return '$minutes${_arabic ? 'د' : 'm'}';
  }

  String get _cardioMinutes => _arabic
      ? '${NumberFormat('#,##0', 'en').format(stats.cardioMinutes!)} ${_copy.minutes}'
      : '${NumberFormat('#,##0', 'en').format(stats.cardioMinutes!)} min';

  int get _prExerciseCount => prCount ?? records
      .map((WorkoutRecord r) => r.exerciseId ?? r.exerciseName)
      .toSet()
      .length;

  @override
  Widget build(BuildContext context) {
    final bool cardioOnly = stats.workingSets == 0 && stats.cardioMinutes != null;
    final String volume = NumberFormat('#,##0', 'en').format(stats.totalVolumeKg.round());
    final TextStyle baseStyle = TextStyle(fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Inter', color: Colors.white);
    return AspectRatio(aspectRatio: 9 / 16, child: Material(type: MaterialType.transparency,
      child: DefaultTextStyle(style: baseStyle, child: Directionality(
        textDirection: _arabic ? ui.TextDirection.rtl : ui.TextDirection.ltr,
        child: MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.noScaling),
          child: _buildCardSurface(cardioOnly: cardioOnly, volume: volume)),
      )),
    ));
  }

  Widget _buildCardSurface({required bool cardioOnly, required String volume}) => DecoratedBox(
    decoration: const BoxDecoration(gradient: RadialGradient(
      center: Alignment(0.6, -0.9), radius: 1.2,
      colors: <Color>[Color(0xff16305A), Color(0xff0A1422), Color(0xff070F1A)],
      stops: <double>[0, .55, 1])),
    child: Stack(fit: StackFit.expand, children: <Widget>[
      if (photoBytes case final Uint8List photo)
        Positioned.fill(child: Image(image: ResizeImage(MemoryImage(photo), width: 1080, height: 1920,
          policy: ResizeImagePolicy.fit), fit: BoxFit.cover, alignment: Alignment.center,
          errorBuilder: (_, __, ___) => const SizedBox.shrink())),
      const Positioned.fill(child: DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: <Color>[Color(0x59070F1A), Color(0x00070F1A), Color(0xeb070F1A)],
        stops: <double>[0, .45, 1])))),
      Align(key: const ValueKey<String>('workoutCard.logoPlacement'),
        alignment: AlignmentDirectional.bottomEnd, child: Padding(
        padding: const EdgeInsetsDirectional.only(end: 26, bottom: 23),
        child: const MayosBrandLockup(
          key: ValueKey<String>('workoutCard.logo'), height: 37, gap: 2,
          variant: MayosBrandVariant.white))),
      Align(alignment: Alignment.bottomCenter, child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(26, 24, 26, 57),
        child: _buildCardDetails(cardioOnly: cardioOnly, volume: volume))),
    ]));

  Widget _buildCardDetails({required bool cardioOnly, required String volume}) => Column(
    mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch,
    children: <Widget>[
      if (_prExerciseCount > 0) _buildPrBadge(),
      if (_dayName case final String name) _buildDayName(name),
      if (performedDate case final DateTime date) _buildPerformedDate(date),
      _buildStatsRow(cardioOnly: cardioOnly, volume: volume),
    ]);

  Widget _buildPrBadge() => Padding(padding: const EdgeInsets.only(bottom: 11),
    child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
      const Icon(Icons.emoji_events_outlined, key: ValueKey<String>('workoutCard.trophy'),
        color: Color(0xffF2C94C), size: 20),
      const SizedBox(width: 8),
      Flexible(child: FittedBox(fit: BoxFit.scaleDown, alignment: AlignmentDirectional.centerStart,
        child: Text(_prCopy, maxLines: 1, style: TextStyle(fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Inter',
          color: const Color(0xffF2C94C), fontSize: 16.4, fontWeight: FontWeight.w600)))),
    ]));

  String get _prCopy => _arabic
      ? '${NumberFormat('#,##0', 'en').format(_prExerciseCount)} ${_prExerciseCount == 1 ? 'رقم قياسي' : 'أرقام قياسية'}'
      : '${NumberFormat('#,##0', 'en').format(_prExerciseCount)} personal records';

  // With a date under it the day name hugs the date so they read as one unit.
  Widget _buildDayName(String name) => Padding(
    padding: EdgeInsets.only(bottom: performedDate == null ? 20 : 6),
    child: Text(name, maxLines: 2, overflow: TextOverflow.ellipsis,
      style: TextStyle(color: Colors.white, fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Montserrat',
        fontSize: 43, height: 1.02, fontWeight: FontWeight.w800)));

  Widget _buildPerformedDate(DateTime date) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Text(_formatPerformedDate(date),
      style: TextStyle(color: const Color(0xffC9D3E1),
        fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Inter', fontSize: 14.3,
        fontWeight: FontWeight.w500)));

  static const List<String> _weekdaysEn = <String>['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  static const List<String> _monthsEn = <String>['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  static const List<String> _weekdaysAr = <String>['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'];
  static const List<String> _monthsAr = <String>['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];

  /// Fixed names instead of intl locale data, so the card never waits on (or
  /// throws for) locale initialisation at capture time. Digits stay Latin.
  String _formatPerformedDate(DateTime date) => _arabic
      ? '${_weekdaysAr[date.weekday - 1]} ${date.day} ${_monthsAr[date.month - 1]} ${date.year}'
      : '${_weekdaysEn[date.weekday - 1]}, ${date.day} ${_monthsEn[date.month - 1]} ${date.year}';

  String? get _dayName {
    final String? name = dayName?.trim();
    return name == null || name.isEmpty || name == 'Day' ? null : name;
  }

  Widget _buildStatsRow({required bool cardioOnly, required String volume}) {
    final List<(String, String)> values = <(String, String)>[];
    if (_duration case final String elapsed) values.add((elapsed, _arabic ? _copy.duration : 'Duration'));
    if (cardioOnly) {
      values.add((_cardioMinutes, _copy.cardio));
    } else {
      values.add((volume, _arabic ? 'الوزن كجم' : 'Volume kg'));
      values.add(('${stats.workingSets}', _arabic ? 'المجموعات' : 'Sets'));
    }
    return Container(padding: const EdgeInsets.only(top: 14),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Color(0x47f3f6fb)))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      for (int i = 0; i < values.length; i++)
        Expanded(child: Container(
          padding: EdgeInsetsDirectional.only(start: i == 0 ? 0 : 14, end: 8),
          decoration: i == 0 ? null : const BoxDecoration(
            border: BorderDirectional(start: BorderSide(color: Color(0x33f3f6fb)))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
            FittedBox(fit: BoxFit.scaleDown, alignment: AlignmentDirectional.centerStart,
              child: _arabic && values[i].$1 == _duration
                  ? _arabicDurationValue()
                  : Text(values[i].$1, maxLines: 1, textDirection: ui.TextDirection.ltr,
                      style: _valueStyle)),
            const SizedBox(height: 3),
            Text(values[i].$2, maxLines: 2, overflow: TextOverflow.ellipsis,
              style: TextStyle(color: const Color(0xffC9D3E1),
                fontFamily: _arabic ? 'IBMPlexSansArabic' : 'Inter', fontSize: 14.3,
                fontWeight: FontWeight.w500)),
          ]))),
    ]));
  }

}

WorkoutShareCard latestSessionShareCard({
  required LatestSession session,
  required String languageCode,
  Uint8List? photoBytes,
  XFile? photoFile,
  WorkoutShareFlowFeedback? feedback,
  OverlayState? captureOverlay,
}) =>
    WorkoutShareCard(
      languageCode: languageCode,
      dayName: session.splitName == 'Day' ? null : session.splitName,
      duration: switch (session.durationSeconds) {
        final int seconds when seconds > 0 => Duration(seconds: seconds),
        _ => null,
      },
      stats: WorkoutSummaryStats(
        exercisesDone: 0,
        workingSets: session.workingSets,
        totalVolumeKg: session.volumeKg,
        cardioMinutes: session.cardioMinutes == 0 ? null : session.cardioMinutes,
      ),
      records: const <WorkoutRecord>[],
      prCount: session.prCount,
      performedDate: _sessionDate(session.sessionDate),
      photoBytes: photoBytes,
      photoFile: photoFile,
      feedback: feedback,
      captureOverlay: captureOverlay,
    );

DateTime? _sessionDate(String value) {
  final DateTime? parsed = DateTime.tryParse(value);
  return parsed == null ? null : DateTime(parsed.year, parsed.month, parsed.day);
}

/// Captures the card, then waits for an explicit action in the preview.
Future<bool> shareWorkoutCard(
    BuildContext context, WorkoutShareCard card, {
      Future<Uint8List> Function(XFile)? preparePhoto,
    }) =>
    captureAndPreviewWorkoutCard(context, card,
      capture: () async {
        final WorkoutShareCard preparedCard = await card.withPreparedPhoto(
            preparePhoto ?? prepareWorkoutPhoto);
        if (!context.mounted) throw StateError('Share card capture context was removed');
        return _captureWorkoutCard(context, preparedCard,
          photoBytes: preparedCard.photoBytes,
          overlay: card.captureOverlay);
      }, feedback: card.feedback);

Future<bool> captureAndPreviewWorkoutCard(
  BuildContext context, WorkoutShareCard card, {
  required Future<Uint8List> Function() capture,
  Duration captureTimeout = const Duration(seconds: 20),
  WorkoutCardActionAdapter? actionAdapter,
  WorkoutShareFlowFeedback? feedback,
}) async {
  final String languageCode = card.languageCode;
  try {
    feedback?.showPreparing();
    final Uint8List pngBytes = await capture().timeout(captureTimeout);
    feedback?.dismissPreparing();
    if (!context.mounted) {
      feedback?.failed('capture_error', StateError('Share card context was removed'));
      return false;
    }
    final WorkoutCardActionAdapter actions = actionAdapter ??
        createWorkoutCardActionAdapter(pngBytes);
    try {
      return await showWorkoutCardPreview(context, pngBytes,
        languageCode: languageCode, share: actions.share, save: actions.save,
        feedback: feedback) ?? false;
    } finally {
      actions.dispose();
    }
  } on TimeoutException catch (error) {
    feedback?.failed('capture_timeout', error);
    if (context.mounted) _showShareError(context, languageCode);
    return false;
  } on _WorkoutPhotoDecodeException catch (error) {
    feedback?.failed('decode_error', error);
    if (context.mounted) _showShareError(context, languageCode);
    return false;
  } on Object catch (error) {
    feedback?.failed('capture_error', error);
    if (context.mounted) _showShareError(context, languageCode);
    return false;
  }
}

/// Full-screen preview. The platform operation is invoked only by a button tap.
Future<bool?> showWorkoutCardPreview(
  BuildContext context,
  Uint8List pngBytes, {
  required String languageCode,
  required Future<bool> Function() share,
  required Future<bool> Function() save,
  WorkoutShareFlowFeedback? feedback,
}) => showDialog<bool>(
  context: context,
  barrierDismissible: false,
  builder: (BuildContext dialogContext) => _WorkoutCardPreview(
    pngBytes: pngBytes, languageCode: languageCode, share: share, save: save,
    feedback: feedback),
);

class _WorkoutCardPreview extends StatefulWidget {
  const _WorkoutCardPreview({required this.pngBytes, required this.languageCode,
    required this.share, required this.save, this.feedback});
  final Uint8List pngBytes;
  final String languageCode;
  final Future<bool> Function() share;
  final Future<bool> Function() save;
  final WorkoutShareFlowFeedback? feedback;
  @override
  State<_WorkoutCardPreview> createState() => _WorkoutCardPreviewState();
}

class _WorkoutCardPreviewState extends State<_WorkoutCardPreview> {
  bool _busy = false;
  bool get _ar => widget.languageCode == 'ar';

  Future<void> _run(Future<bool> Function() action, {bool isShare = false}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final bool complete = await action();
      if (mounted && complete) {
        Navigator.of(context).pop(true);
      } else if (mounted) {
        setState(() => _busy = false);
      }
    } on Object catch (error) {
      widget.feedback?.failed(isShare ? 'share_error' : 'save_error', error);
      _reportActionFailure();
    }
  }

  void _reportActionFailure() {
    if (!mounted) return;
    setState(() => _busy = false);
    _showShareError(context, widget.languageCode);
  }

  @override
  Widget build(BuildContext context) => PopScope<dynamic>(
    canPop: !_busy,
    child: Scaffold(
    backgroundColor: const Color(0xff07162d),
    appBar: AppBar(backgroundColor: const Color(0xff07162d),
      leading: IconButton(tooltip: _ar ? 'إغلاق' : 'Close', icon: const Icon(Icons.close),
        onPressed: _busy ? null : () => Navigator.of(context).pop(false))),
    body: SafeArea(child: Column(children: <Widget>[
      Expanded(child: Center(child: Padding(padding: const EdgeInsets.all(12),
        child: AspectRatio(aspectRatio: 9 / 16, child: Image.memory(widget.pngBytes, fit: BoxFit.contain)))),),
      Padding(padding: const EdgeInsets.all(16), child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
        SizedBox(width: double.infinity, child: FilledButton.icon(
          key: const ValueKey<String>('workoutCard.share'), onPressed: _busy ? null : () => _run(widget.share, isShare: true),
          icon: const Icon(Icons.ios_share), label: Text(_ar ? 'مشاركة' : 'Share'))),
        SizedBox(width: double.infinity, child: OutlinedButton.icon(
          key: const ValueKey<String>('workoutCard.save'), onPressed: _busy ? null : () => _run(widget.save),
          icon: const Icon(Icons.download), label: Text(_ar ? 'حفظ الصورة' : 'Save image'))),
      ])),
    ])),
  ));
}

void _showShareError(BuildContext context, String languageCode) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(languageCode == 'ar' ? 'تعذر إنشاء الصورة أو مشاركتها. حاول مرة أخرى.' : 'Could not create or share the image. Try again.'),
  ));
}

Future<bool> shareWorkoutCardAndTrack({
  required Future<bool> Function() share,
  required AnalyticsClient analytics,
  required String source,
  required WorkoutPhotoChoiceResult photo,
}) async {
  final bool completed = await share();
  if (completed) {
    analytics.shareCardShared(
      source: source,
      hasPhoto: photo.photoBytes != null || photo.photoFile != null,
      photoSource: photo.source,
    );
  }
  return completed;
}

typedef WorkoutImagePicker = Future<XFile?> Function(ImageSource source);

Future<XFile?> _pickWorkoutImage(ImageSource source) => ImagePicker().pickImage(
  source: source,
);

final Provider<WorkoutImagePicker> workoutImagePickerProvider =
    Provider<WorkoutImagePicker>((Ref ref) => _pickWorkoutImage);

typedef WorkoutCardShare = Future<bool> Function(
    BuildContext context, WorkoutShareCard card);

final Provider<WorkoutCardShare> workoutCardShareProvider =
    Provider<WorkoutCardShare>((Ref ref) => shareWorkoutCard);

enum _WorkoutPhotoChoice { camera, gallery, none }

@immutable
class WorkoutPhotoChoiceResult {
  const WorkoutPhotoChoiceResult.cancelled()
      : cancelled = true, photoBytes = null, photoFile = null, source = 'none';
  const WorkoutPhotoChoiceResult.noPhoto()
      : cancelled = false, photoBytes = null, photoFile = null, source = 'none';
  const WorkoutPhotoChoiceResult.photo(this.photoFile, this.source)
      : cancelled = false, photoBytes = null;

  final bool cancelled;
  final Uint8List? photoBytes;
  final XFile? photoFile;

  final String source;
}

/// Shows the on-device photo choice. A cancelled or denied picker returns to
/// this sheet, so skipping the photo is always available.
Future<WorkoutPhotoChoiceResult> chooseWorkoutPhoto(
  BuildContext context, {
  required String languageCode,
  WorkoutImagePicker? pickImage,
  void Function(String source)? onSourceSelected,
  void Function(String stage)? onFailureStage,
  void Function(String stage, Object error)? onFailure,
}) async {
  final WorkoutCopy copy = WorkoutCopy(languageCode);
  final WorkoutImagePicker picker = pickImage ?? _pickWorkoutImage;
  while (context.mounted) {
    if (!context.mounted) return const WorkoutPhotoChoiceResult.cancelled();
    final _WorkoutPhotoChoice? choice =
        await _showWorkoutPhotoChoices(context, copy);
    if (!context.mounted) return const WorkoutPhotoChoiceResult.cancelled();
    if (choice == null) return const WorkoutPhotoChoiceResult.cancelled();
    if (choice == _WorkoutPhotoChoice.none) {
      onSourceSelected?.call('none');
      return const WorkoutPhotoChoiceResult.noPhoto();
    }
    try {
      final ImageSource source = choice == _WorkoutPhotoChoice.camera
          ? ImageSource.camera
          : ImageSource.gallery;
      final String sourceName = choice == _WorkoutPhotoChoice.camera
          ? 'camera'
          : 'gallery';
      final XFile? photoFile = await picker(source);
      if (photoFile == null) {
        continue;
      }
      onSourceSelected?.call(sourceName);
      return WorkoutPhotoChoiceResult.photo(photoFile, sourceName);
    } on Object catch (error) {
      onFailureStage?.call('picker_error');
      onFailure?.call('picker_error', error);
      if (context.mounted) _showShareError(context, languageCode);
      return const WorkoutPhotoChoiceResult.cancelled();
    }
  }
  return const WorkoutPhotoChoiceResult.cancelled();
}

Future<_WorkoutPhotoChoice?> _showWorkoutPhotoChoices(
    BuildContext context, WorkoutCopy copy) =>
    showModalBottomSheet<_WorkoutPhotoChoice>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext sheetContext) => SafeArea(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                _photoChoiceTile(
                  sheetContext,
                  _WorkoutPhotoChoice.camera,
                  Icons.photo_camera_outlined,
                  copy.takePhoto,
                ),
                _photoChoiceTile(
                  sheetContext,
                  _WorkoutPhotoChoice.gallery,
                  Icons.photo_library_outlined,
                  copy.choosePhotoFromGallery,
                ),
                _photoChoiceTile(
                  sheetContext,
                  _WorkoutPhotoChoice.none,
                  Icons.block_outlined,
                  copy.noPhoto,
                ),
              ],
            ),
          ),
        ),
      ),
    );

ListTile _photoChoiceTile(BuildContext context, _WorkoutPhotoChoice choice,
        IconData icon, String label) =>
    ListTile(
      leading: Icon(icon),
      title: Text(label),
      onTap: () => Navigator.pop(context, choice),
    );

class _WorkoutPhotoDecodeException implements Exception {}

Future<void> _precacheWorkoutPhoto(Uint8List photo, BuildContext context) async {
  final Completer<void> decoded = Completer<void>();
  precacheImage(
    ResizeImage(MemoryImage(photo), width: 1080, height: 1920,
        policy: ResizeImagePolicy.fit),
    context,
    onError: (Object error, StackTrace? stackTrace) {
      if (!decoded.isCompleted) {
        decoded.completeError(error, stackTrace ?? StackTrace.current);
      }
    },
  ).then((_) {
    if (!decoded.isCompleted) decoded.complete();
  });
  try {
    await decoded.future;
  } on Object {
    throw _WorkoutPhotoDecodeException();
  }
}

Future<Uint8List> _captureWorkoutCard(
    BuildContext context, WorkoutShareCard card, {
      Uint8List? photoBytes, OverlayState? overlay,
    }) async {
  final Uint8List? imageBytes = photoBytes ?? card.photoBytes;
  final WorkoutShareCard renderedCard = card.withPhotoBytes(imageBytes);
  if (imageBytes case final Uint8List photo) {
    await _precacheWorkoutPhoto(photo, context);
  }
  if (!context.mounted) throw StateError('Share card capture context was removed');
  final GlobalKey boundaryKey = GlobalKey();
  final OverlayState captureOverlay = overlay ?? Overlay.of(context);
  final OverlayEntry entry = OverlayEntry(
    builder: (BuildContext context) => Positioned(
      left: -1200,
      top: 0,
      width: 360,
      child: Material(type: MaterialType.transparency, child: DefaultTextStyle(
        style: TextStyle(fontFamily: card.languageCode == 'ar' ? 'IBMPlexSansArabic' : 'Inter', color: Colors.white),
        child: RepaintBoundary(key: boundaryKey, child: renderedCard))),
    ),
  );
  captureOverlay.insert(entry);
  WidgetsBinding.instance.scheduleFrame();
  try {
    await WidgetsBinding.instance.endOfFrame;
    final RenderRepaintBoundary boundary = boundaryKey.currentContext!
        .findRenderObject()! as RenderRepaintBoundary;
    final ui.Image image = await boundary.toImage(pixelRatio: 3);
    final ByteData? bytes =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (bytes == null) throw StateError('Could not render workout card');
    return bytes.buffer.asUint8List();
  } finally {
    entry.remove();
  }
}
