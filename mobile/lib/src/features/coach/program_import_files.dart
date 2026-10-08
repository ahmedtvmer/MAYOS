import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../providers.dart';

typedef ProgramSpreadsheetPicker = Future<PlatformFile?> Function();
typedef ProgramTemplateSaver = Future<String?> Function(
    Uint8List bytes, String fileName);
typedef ProgramTemplateDownloader = Future<void> Function(String extension);

final programSpreadsheetPickerProvider = Provider<ProgramSpreadsheetPicker>(
  (ref) => () async {
    final FilePickerResult? result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const <String>['xlsx', 'csv'],
      withData: true,
    );
    return result?.files.single;
  },
);

final programTemplateSaverProvider = Provider<ProgramTemplateSaver>(
  (ref) => (Uint8List bytes, String fileName) => FilePicker.saveFile(
    fileName: fileName,
    type: FileType.custom,
    allowedExtensions: <String>[fileName.split('.').last],
    bytes: bytes,
  ),
);

final programTemplateDownloaderProvider = Provider<ProgramTemplateDownloader>(
  (ref) => (String extension) async {
    final Uint8List bytes = await ref
        .read(apiClientProvider)
        .coachProgramImportTemplate(extension);
    await ref.read(programTemplateSaverProvider)(
      bytes,
      'mayos-program-template.$extension',
    );
  },
);

Future<void> runProgramTemplateDownload({
  required WidgetRef ref,
  required String extension,
  required void Function(bool) onBusyChanged,
  required bool Function() isMounted,
  required void Function(FailureMessage) onFailure,
  VoidCallback? onDownloaded,
}) async {
  onBusyChanged(true);
  try {
    await ref.read(programTemplateDownloaderProvider)(extension);
    if (isMounted()) onDownloaded?.call();
  } on ApiException catch (error) {
    if (isMounted()) onFailure(apiFailureMessage(error));
  } finally {
    if (isMounted()) onBusyChanged(false);
  }
}
