import 'dart:js_interop';

import 'package:web/web.dart' as web;

web.AudioContext? _restAudio;

Future<void> prepareWebRestAudio() async {
  final web.AudioContext audio = _restAudio ??= web.AudioContext();
  await audio.resume().toDart;
}

Future<void> playWebRestEnd() async {
  web.window.navigator.vibrate(180.toJS);
  final web.AudioContext audio = _restAudio ??= web.AudioContext();
  final web.OscillatorNode tone = audio.createOscillator();
  tone.frequency.value = 660;
  tone.connect(audio.destination);
  tone.start();
  tone.stop(audio.currentTime + 0.14);
  await audio.resume().toDart;
}
