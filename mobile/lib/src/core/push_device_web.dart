import 'dart:convert';
import 'dart:js_interop';

@JS('MAYOS_PUSH_STATE')
external JSString _state();
@JS('MAYOS_PUSH_ENABLE')
external JSPromise<JSString> _enable(JSString key);
@JS('MAYOS_PUSH_REFRESH')
external JSPromise<JSString?> _refresh(JSString key);
@JS('MAYOS_PUSH_DISABLE')
external JSPromise<JSAny?> _disable();

Map<String, dynamic> pushDeviceState() =>
    jsonDecode(_state().toDart) as Map<String, dynamic>;
Future<Map<String, dynamic>?> enablePushDevice(String key) async =>
    jsonDecode((await _enable(key.toJS).toDart).toDart) as Map<String, dynamic>;
Future<Map<String, dynamic>?> refreshPushDevice(String key) async {
  final JSString? value = await _refresh(key.toJS).toDart;
  return value == null
      ? null
      : jsonDecode(value.toDart) as Map<String, dynamic>;
}

Future<void> disablePushDevice() async {
  await _disable().toDart;
}
