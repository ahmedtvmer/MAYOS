import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'package:mayos_mobile/src/core/error_reporting.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('event sanitization removes location and user fields without a user', () {
    final SentryEvent event = sanitizeSentryEvent(SentryEvent(), Hint())!;
    expect(event.user?.ipAddress, '0.0.0.0');
    expect(event.user?.id, isNull);
    expect(event.user?.geo, isNull);
    expect(event.user?.email, isNull);
    expect(event.user?.username, isNull);
    expect(event.user?.name, isNull);
    expect(event.user?.data, isNull);
  });

  test('null breadcrumbs are dropped', () {
    expect(filterSentryBreadcrumb(null, Hint()), isNull);
  });

  test('captured exception excludes UI data and uses anonymous user', () async {
    final _CapturingTransport transport = _CapturingTransport();
    await initializeErrorReporting(
      testDsn: 'https://public@example.ingest.sentry.io/1',
      configure: (SentryFlutterOptions options) {
        options.transport = transport;
        // The host test runner has no native Sentry library (libsentry.so).
        options.autoInitializeNativeSdk = false;
        options.enableScopeSync = false;
      },
    );
    addTearDown(Sentry.close);
    await setSentryAnonymousAccountId('anon-account-42');
    await Sentry.addBreadcrumb(Breadcrumb(
      category: 'navigation',
      type: 'navigation',
      data: <String, dynamic>{'screen': 'player_home', 'secret': 'drop-me'},
    ));
    await Sentry.addBreadcrumb(Breadcrumb(
      category: 'http',
      type: 'http',
      data: <String, dynamic>{
        'method': 'POST',
        'route': '/auth/:id',
        'status': 500,
        'query': 'typed-private-query',
        'body': 'typed-private-body',
      },
    ));
    await Sentry.addBreadcrumb(Breadcrumb(
      category: 'ui.click',
      message: 'typed-private-text',
    ));

    await Sentry.captureException(StateError('widget failure'));

    expect(transport.events, hasLength(1));
    final SentryEvent event = transport.events.single;
    final String serializedEvent = jsonEncode(event.toJson());
    expect(serializedEvent, isNot(contains('typed-private-text')));
    expect(serializedEvent, isNot(contains('typed-private-query')));
    expect(serializedEvent, isNot(contains('typed-private-body')));
    expect(serializedEvent, isNot(contains('screenshot')));
    expect(serializedEvent, isNot(contains('view_hierarchy')));
    expect(event.user?.id, 'anon-account-42');
    expect(event.user?.ipAddress, '0.0.0.0');
    final Map<String, dynamic> sentUser =
        event.toJson()['user'] as Map<String, dynamic>;
    expect(sentUser.keys, containsAll(<String>['id', 'ip_address']));
    expect(sentUser.keys, isNot(contains('geo')));
    expect(
      sentUser.keys,
      isNot(contains(anyOf('email', 'username', 'name', 'data'))),
    );
    expect(transport.attachmentCount, 0);
    expect(event.breadcrumbs?.map((Breadcrumb breadcrumb) => breadcrumb.category),
        everyElement(anyOf('navigation', 'http')));
    expect(event.breadcrumbs?.map((Breadcrumb breadcrumb) => breadcrumb.data),
        contains(equals(<String, dynamic>{'screen': 'player_home'})));
    expect(event.breadcrumbs?.map((Breadcrumb breadcrumb) => breadcrumb.data),
        contains(equals(<String, dynamic>{
          'method': 'POST',
          'route': '/auth/:id',
          'status': 500,
        })));

    await setSentryAnonymousAccountId(null);
    await Sentry.configureScope((Scope scope) {
      expect(scope.user, isNull);
    });
  }, timeout: const Timeout(Duration(seconds: 30)));

  testWidgets('no compiled DSN leaves reporting disabled',
      (WidgetTester tester) async {
    var configureCalled = false;
    await initializeErrorReporting(configure: (_) => configureCalled = true);
    expect(configureCalled, isFalse);
    expect(errorReportingInitialized, isFalse);
    await captureSentryTestError(StateError('test error'));
  });
}

class _CapturingTransport implements Transport {
  final List<SentryEvent> events = <SentryEvent>[];
  int attachmentCount = 0;

  @override
  Future<SentryId?> send(SentryEnvelope envelope) {
    for (final SentryEnvelopeItem item in envelope.items) {
      final Object? original = item.originalObject;
      if (original is SentryEvent) events.add(original);
      if (item.header.type.toString().contains('attachment')) {
        attachmentCount++;
      }
    }
    return Future<SentryId?>.value(null);
  }
}
