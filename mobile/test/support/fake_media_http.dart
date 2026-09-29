import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';

/// One recorded `GET /media/…`, so a test can assert the address the picture
/// was fetched from and which headers went with it (#161: the route is
/// public, so no bearer token may ride along).
class FakeMediaRequest {
  const FakeMediaRequest(this.uri, this.headers);

  final Uri uri;
  final Map<String, List<String>> headers;

  bool header(String name) => headers.keys
      .any((String key) => key.toLowerCase() == name.toLowerCase());
}

/// An in-memory stand-in for the API's public `GET /media/<image_path>`
/// route (`svc/routers/media.py`): registered paths answer 200 with real PNG
/// bytes, everything else 404 — the loaded, failed and missing cases the
/// logger's picture states need (#161).
///
/// It plugs into [debugNetworkImageHttpClientProvider], the hook Flutter
/// documents for supplying the `HttpClient` [NetworkImage] uses, so the
/// widget under test still builds the real URL and still goes through the
/// real image cache.
class FakeMediaCatalog {
  /// Catalog image path (`images/0001.jpg`) → the bytes `/media` serves.
  final Map<String, Uint8List> images = <String, Uint8List>{};

  /// Every request the image pipeline issued, in order.
  final List<FakeMediaRequest> requests = <FakeMediaRequest>[];

  /// Registers a catalog picture that will load successfully.
  void serve(String imagePath, {Uint8List? bytes}) {
    images[imagePath] = bytes ?? fakeCatalogPng();
  }

  /// How many times [imagePath] was fetched — a rebuild that refetches would
  /// push this above 1 (#161: pictures load once and are reused).
  int requestCount(String imagePath) => requests
      .where((FakeMediaRequest r) => r.uri.path.endsWith('/$imagePath'))
      .length;

  /// Total requests, for asserting nothing else was fetched.
  int get totalRequests => requests.length;

  /// The hook the widget tree uses: a fresh client per image load.
  HttpClient client() => _FakeMediaClient(this);

  /// Installs [client] as Flutter's image `HttpClient` and clears the decoded
  /// image cache, so a test starts from a cold cache.
  void install() {
    debugNetworkImageHttpClientProvider = client;
    clearImageCache();
  }

  /// Undoes [install].
  static void uninstall() {
    debugNetworkImageHttpClientProvider = null;
    clearImageCache();
  }

  static void clearImageCache() {
    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();
  }
}

/// A valid 8×8 RGBA PNG (one flat colour), enough for the engine's decoder
/// to produce a real frame in tests.
Uint8List fakeCatalogPng() => base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAEklEQVR42'
      'mNwSFjwHx9mGBkKANSvj8GxLYrFAAAAAElFTkSuQmCC',
    );

class _FakeMediaClient implements HttpClient {
  _FakeMediaClient(this._catalog);

  final FakeMediaCatalog _catalog;

  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async =>
      _FakeMediaRequest(_catalog, url);

  @override
  Future<HttpClientRequest> getUrl(Uri url) => openUrl('GET', url);

  @override
  void close({bool force = false}) {}

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      super.noSuchMethod(invocation);
}

class _FakeMediaRequest implements HttpClientRequest {
  _FakeMediaRequest(this._catalog, this.uri);

  final FakeMediaCatalog _catalog;
  @override
  final Uri uri;
  @override
  final HttpHeaders headers = _FakeHeaders();

  @override
  Future<HttpClientResponse> close() async {
    final Map<String, List<String>> recorded =
        (headers as _FakeHeaders).asMap();
    _catalog.requests.add(FakeMediaRequest(uri, recorded));
    // `/media/<image_path>`: the same address `svc/routers/media.py` serves.
    final String path = uri.path.startsWith('/media/')
        ? uri.path.substring('/media/'.length)
        : '';
    final Uint8List? body = _catalog.images[path];
    if (body == null) {
      return _FakeMediaResponse(HttpStatus.notFound, Uint8List(0));
    }
    return _FakeMediaResponse(HttpStatus.ok, body);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      super.noSuchMethod(invocation);
}

class _FakeHeaders implements HttpHeaders {
  final Map<String, List<String>> _values = <String, List<String>>{};

  Map<String, List<String>> asMap() =>
      Map<String, List<String>>.unmodifiable(_values);

  @override
  void add(String name, Object value, {bool preserveHeaderCase = false}) {
    (_values[name] ??= <String>[]).add('$value');
  }

  @override
  void set(String name, Object value, {bool preserveHeaderCase = false}) {
    _values[name] = <String>['$value'];
  }

  @override
  String? value(String name) => _values[name]?.join(',');

  @override
  void forEach(void Function(String name, List<String> values) action) {
    _values.forEach(action);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      super.noSuchMethod(invocation);
}

class _FakeMediaResponse extends StreamView<List<int>>
    implements HttpClientResponse {
  _FakeMediaResponse(this.statusCode, Uint8List body)
      : contentLength = body.length,
        super(Stream<List<int>>.fromIterable(<List<int>>[body]));

  @override
  final int statusCode;

  @override
  final int contentLength;

  @override
  final HttpHeaders headers = _FakeHeaders();

  @override
  final HttpClientResponseCompressionState compressionState =
      HttpClientResponseCompressionState.notCompressed;

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      super.noSuchMethod(invocation);
}
