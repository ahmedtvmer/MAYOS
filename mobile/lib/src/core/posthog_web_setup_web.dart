import 'dart:convert';
import 'dart:js_interop';

@JS('mayosInitializePosthog')
external JSPromise<JSAny?> _initializePosthog(
  JSString clientKey,
  JSString commonDimensionsJson,
);

@JS('mayosIdentifyPosthog')
external JSAny? _identifyPosthog(
  JSString accountId,
  JSString role,
  JSString commonDimensionsJson,
);

@JS('mayosCapturePosthog')
external JSAny? _capturePosthog(JSString eventName, JSString propertiesJson);

@JS('mayosResetPosthog')
external JSAny? _resetPosthog();

Future<void> initializePostHogWeb(
  String clientKey,
  Map<String, String> commonDimensions,
) async {
  await _initializePosthog(
    clientKey.toJS,
    jsonEncode(commonDimensions).toJS,
  ).toDart;
}

Future<void> identifyPostHogWeb(
  String accountId,
  String role,
  Map<String, String> commonDimensions,
) async {
  _identifyPosthog(
    accountId.toJS,
    role.toJS,
    jsonEncode(commonDimensions).toJS,
  );
}

Future<void> capturePostHogWeb(
  String eventName,
  Map<String, Object> properties,
) async {
  _capturePosthog(eventName.toJS, jsonEncode(properties).toJS);
}

Future<void> resetPostHogWeb() async {
  _resetPosthog();
}
