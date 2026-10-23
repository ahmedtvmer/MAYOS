import 'app_display_mode_stub.dart'
    if (dart.library.js_interop) 'app_display_mode_web.dart' as platform;

/// Returns the browser display mode on web and null on native platforms.
String? currentAppDisplayMode() => platform.currentAppDisplayMode();
