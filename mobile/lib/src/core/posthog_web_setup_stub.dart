Future<void> initializePostHogWeb(
  String clientKey,
  Map<String, String> commonDimensions,
) async {}

Future<void> identifyPostHogWeb(
  String accountId,
  String role,
  Map<String, String> commonDimensions,
) async {}

Future<void> capturePostHogWeb(
  String eventName,
  Map<String, Object> properties,
) async {}

Future<void> resetPostHogWeb() async {}
