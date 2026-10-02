import 'dart:convert';

/// Reads a token subject only to select account-namespaced local cache keys.
/// The API remains responsible for verifying and authorizing the token.
String? unverifiedTokenSubject(String? token) {
  if (token == null || token.isEmpty) return null;
  final List<String> parts = token.split('.');
  if (parts.length < 2) return null;
  try {
    final String payload =
        utf8.decode(base64Url.decode(base64Url.normalize(parts[1])));
    final dynamic decoded = jsonDecode(payload);
    if (decoded is Map && decoded['sub'] is String) {
      final String subject = decoded['sub'] as String;
      return subject.isEmpty ? null : subject;
    }
  } on Object {
    // Malformed tokens have no usable cache namespace.
  }
  return null;
}
