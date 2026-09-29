import 'package:flutter/widgets.dart';

import 'google_web_button_stub.dart'
    if (dart.library.js_interop) 'google_web_button_web.dart' as platform;

Widget renderGoogleWebButton({
  required bool darkTheme,
  required double width,
}) =>
    platform.renderGoogleWebButton(darkTheme: darkTheme, width: width);
