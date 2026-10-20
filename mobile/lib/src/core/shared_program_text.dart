import 'dart:async';

import 'package:flutter/services.dart';

class SharedProgramText {
  const SharedProgramText(this.text) : error = null;
  const SharedProgramText.refused(this.error) : text = null;

  final String? text;
  final SharedProgramTextError? error;

  static SharedProgramText? parse(Object? payload) {
    if (payload is! Map) return null;
    if (payload['text'] is String) {
      return SharedProgramText(payload['text'] as String);
    }
    final Object? rawError = payload['error'];
    for (final SharedProgramTextError error in SharedProgramTextError.values) {
      if (rawError == error.code) return SharedProgramText.refused(error);
    }
    return null;
  }
}

enum SharedProgramTextError {
  fileTooLarge('file_too_large'),
  unsupportedFileType('not_txt'),
  invalidUtf8('invalid_utf8'),
  fileReadFailed('file_read_failed');

  const SharedProgramTextError(this.code);

  final String code;
}

abstract class SharedProgramTextSource {
  Future<SharedProgramText?> initial();
  Stream<SharedProgramText> get events;
}

class NoopSharedProgramTextSource implements SharedProgramTextSource {
  @override
  Future<SharedProgramText?> initial() async => null;

  @override
  Stream<SharedProgramText> get events =>
      const Stream<SharedProgramText>.empty();
}

class AndroidSharedProgramTextSource implements SharedProgramTextSource {
  static const MethodChannel _method = MethodChannel('com.mayos/share');
  final StreamController<SharedProgramText> _events =
      StreamController<SharedProgramText>.broadcast();
  bool _initialIntentConsumed = false;

  AndroidSharedProgramTextSource() {
    _method.setMethodCallHandler((MethodCall call) async {
      if (call.method == 'sharedText') {
        final SharedProgramText? sharedText =
            SharedProgramText.parse(call.arguments);
        if (sharedText != null) _events.add(sharedText);
      }
    });
  }

  @override
  Future<SharedProgramText?> initial() async {
    await _method.invokeMethod<void>('startListening');
    if (_initialIntentConsumed) return null;
    _initialIntentConsumed = true;
    return SharedProgramText.parse(
      await _method.invokeMethod<Object?>('getInitialIntent'),
    );
  }

  @override
  Stream<SharedProgramText> get events => _events.stream;
}

class SharedProgramTextStore {
  SharedProgramText? _pending;
  final StreamController<SharedProgramText> _events =
      StreamController<SharedProgramText>.broadcast();

  SharedProgramText? get pending => _pending;
  Stream<SharedProgramText> get events => _events.stream;

  void put(SharedProgramText value) {
    _pending = value;
    _events.add(value);
  }

  void clear() => _pending = null;

  void dispose() => _events.close();
}
