import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:web/web.dart' as web;

const int _restEndVibrationMilliseconds = 180;
const double _restEndToneFrequencyHz = 660;
const double _restEndToneDurationSeconds = 0.14;

web.AudioContext? _restAudio;

web.AudioContext get _audioContext => _restAudio ??= web.AudioContext();

Future<void> prepareWebRestAudio() => _resumeSilently(_audioContext);

/// Starts AudioContext.resume() before this user-gesture callback returns.
void unlockWebRestAudio() {
  try {
    unawaited(_resumeSilently(_audioContext));
  } on Object {
    // Audio is best-effort; unsupported contexts never block logging.
  }
}

Future<void> _resumeSilently(web.AudioContext audio) async {
  try {
    await audio.resume().toDart;
  } on Object {
    // The in-app countdown remains usable when audio is unavailable.
  }
}

Future<void> playWebRestEnd() async {
  try {
    final web.AudioContext audio = _audioContext;
    await audio.resume().toDart;
    final web.OscillatorNode tone = audio.createOscillator();
    tone.frequency.value = _restEndToneFrequencyHz;
    tone.connect(audio.destination);
    tone.onended = ((web.Event _) => tone.disconnect()).toJS;
    tone.start();
    tone.stop(audio.currentTime + _restEndToneDurationSeconds);
  } on Object {
    // The timer still ends in-app when the browser cannot play audio.
  }

  try {
    final web.Navigator navigator = web.window.navigator;
    if (navigator.has('vibrate')) {
      navigator.vibrate(_restEndVibrationMilliseconds.toJS);
    }
  } on Object {
    // Vibration is optional and unsupported on some browsers.
  }
}
