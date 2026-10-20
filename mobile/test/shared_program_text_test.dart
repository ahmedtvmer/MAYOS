import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/shared_program_text.dart';

void main() {
  test('parses shared text and text-file payloads', () {
    final message = SharedProgramText.parse(<String, Object?>{
      'text': 'Day 1\nSquat 3x8',
    });
    final file = SharedProgramText.parse(<String, Object?>{
      'text': 'Day 2\nPress 3x10',
    });

    expect(message?.text, 'Day 1\nSquat 3x8');
    expect(file?.text, 'Day 2\nPress 3x10');
    expect(SharedProgramText.parse(null), isNull);
    expect(SharedProgramText.parse(<String, Object?>{'text': 4}), isNull);
  });

  test('parses refusals and Kotlin selected-file payload', () {
    final Map<String, SharedProgramTextError> refusals =
        <String, SharedProgramTextError>{
      'file_too_large': SharedProgramTextError.fileTooLarge,
      'not_txt': SharedProgramTextError.unsupportedFileType,
      'invalid_utf8': SharedProgramTextError.invalidUtf8,
      'file_read_failed': SharedProgramTextError.fileReadFailed,
    };
    for (final MapEntry<String, SharedProgramTextError> entry
        in refusals.entries) {
      expect(
        SharedProgramText.parse(<String, Object?>{'error': entry.key})?.error,
        entry.value,
      );
    }

    // MainActivity prefers EXTRA_STREAM to any caption, then sends only the
    // selected content as `text`. Dart parses that Kotlin payload shape.
    final SharedProgramText? parsedFile = SharedProgramText.parse(
      <String, Object?>{'text': 'Program from the .txt file'},
    );
    expect(parsedFile?.text, 'Program from the .txt file');
  });

  test('initial shared intent is consumed once by the Dart source', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    const MethodChannel channel = MethodChannel('com.mayos/share');
    int initialIntentCalls = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (MethodCall call) async {
      if (call.method == 'getInitialIntent') {
        initialIntentCalls++;
        return <String, Object?>{'text': 'one time'};
      }
      return null;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null));
    final AndroidSharedProgramTextSource source =
        AndroidSharedProgramTextSource();

    expect((await source.initial())?.text, 'one time');
    expect(await source.initial(), isNull);
    expect(initialIntentCalls, 1);
  });

  test('keeps pending shared text only in memory until cleared', () async {
    final SharedProgramTextStore store = SharedProgramTextStore();
    final values = <SharedProgramText>[];
    final subscription = store.events.listen(values.add);
    const SharedProgramText text = SharedProgramText('Squat 3x8');

    store.put(text);
    await Future<void>.delayed(Duration.zero);
    expect(store.pending?.text, text.text);
    expect(values.single.text, text.text);

    store.clear();
    expect(store.pending, isNull);
    await subscription.cancel();
  });
}
