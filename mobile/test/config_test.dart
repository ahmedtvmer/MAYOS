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

  test('a media address is the API base plus the encoded path (#53/#161)', () {
    expect(
      mediaUrlFor('images/0001-2gPfomN.jpg'),
      '$debugDefaultApiBaseUrl/media/images/0001-2gPfomN.jpg',
    );
    // Leading slash is stripped, each segment percent-encoded on its own, so
    // a payload cannot smuggle a query, fragment or path traversal past the
    // route's media directory.
    expect(
      mediaUrlFor('/images/a b.jpg'),
      '$debugDefaultApiBaseUrl/media/images/a%20b.jpg',
    );
    expect(
      mediaUrlFor('images/../secrets.txt'),
      '$debugDefaultApiBaseUrl/media/images/%2E%2E/secrets.txt',
    );
    expect(mediaUrlFor(null), isNull);
    expect(mediaUrlFor('   '), isNull);
  });

  test('a payload cannot point the app at an arbitrary host (#53)', () {
    expect(mediaUrlFor('https://evil.example.com/x.jpg'), isNull);
    expect(mediaUrlFor('http://evil.example.com/x.jpg'), isNull);
    // The configured host itself is still addressable (the schema allows a
    // URL alongside the usual relative path).
    expect(
      mediaUrlFor('$debugDefaultApiBaseUrl/media/images/x.jpg'),
      '$debugDefaultApiBaseUrl/media/images/x.jpg',
    );
  });
}
