import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/config.dart';

void main() {
  test('release requires an explicit HTTPS base URL', () {
    expect(
      () => resolveApiBaseUrl(isRelease: true, configured: ''),
      throwsStateError,
    );
    expect(
      () => resolveApiBaseUrl(
          isRelease: true, configured: 'http://api.example.com'),
      throwsStateError,
    );
    expect(
      resolveApiBaseUrl(isRelease: true, configured: 'https://api.example.com'),
      'https://api.example.com',
    );
  });

  test('debug may fall back to the emulator loopback or a local override', () {
    expect(
      resolveApiBaseUrl(isRelease: false, configured: ''),
      debugDefaultApiBaseUrl,
    );
    expect(
      resolveApiBaseUrl(isRelease: false, configured: 'http://localhost:8000'),
      'http://localhost:8000',
    );
  });
}
