import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/account_data_eraser.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/first_touch.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_start_notice_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_repository.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

void main() {
  test('install referrer parsing keeps only UTM labels', () {
    final FirstTouch? touch = FirstTouch.fromInstallReferrer(
      'utm_source=Google-Play&utm_medium=organic&utm_campaign=trial&gclid=private',
    );

    expect(touch?.toJson(), <String, String>{
      'utm_source': 'Google-Play',
      'utm_medium': 'organic',
      'utm_campaign': 'trial',
    });
  });

  test('the persisted first snapshot survives reloads until registration', () async {
    final _FakeFirstTouchPersistence storage = _FakeFirstTouchPersistence();
    var reads = 0;
    final PersistentAcquisitionSource firstSource = PersistentAcquisitionSource(
      persistence: storage,
      readCurrent: () async {
        reads += 1;
        return const FirstTouch(utmSource: 'newsletter');
      },
      clearOnRegistration: true,
    );
    final FirstTouchCapture capture = FirstTouchCapture(firstSource);

    expect((await capture.capture())?.utmSource, 'newsletter');
    expect((await capture.capture())?.utmSource, 'newsletter');
    expect(reads, 1);

    final PersistentAcquisitionSource afterReload = PersistentAcquisitionSource(
      persistence: storage,
      readCurrent: () async {
        reads += 1;
        return const FirstTouch(utmSource: 'later-visit');
      },
      clearOnRegistration: true,
    );
    expect((await afterReload.captureFirstTouch())?.utmSource, 'newsletter');
    expect(reads, 1);

    await afterReload.clearAfterRegistration();
    expect((await afterReload.captureFirstTouch())?.utmSource, 'later-visit');
    expect(reads, 2);
  });

  test('an empty persisted marker prevents another install-referrer read', () async {
    final _FakeFirstTouchPersistence storage = _FakeFirstTouchPersistence();
    var reads = 0;
    final PersistentAcquisitionSource firstInstallRead = PersistentAcquisitionSource(
      persistence: storage,
      readCurrent: () async {
        reads += 1;
        return null;
      },
    );
    expect(await firstInstallRead.captureFirstTouch(), isNull);

    final PersistentAcquisitionSource afterRestart = PersistentAcquisitionSource(
      persistence: storage,
      readCurrent: () async {
        reads += 1;
        return const FirstTouch(utmSource: 'must-not-read-again');
      },
    );
    expect(await afterRestart.captureFirstTouch(), isNull);
    expect(reads, 1);
  });

  test('acquisition timeout and exceptions resolve to no first touch', () async {
    final FirstTouchCapture timedOut = FirstTouchCapture(
      _FakeAcquisitionSource(Completer<FirstTouch?>().future),
    );
    expect(await timedOut.capture(), isNull);

    final FirstTouchCapture failed = FirstTouchCapture(
      _ThrowingAcquisitionSource(),
    );
    expect(await failed.capture(), isNull);
  });

  test('AuthRepository.register sends the captured first-touch snapshot', () async {
    final FakeMayosApi fake = _signedOutFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    var clears = 0;
    final AuthRepository repository = _repository(
      fake,
      tokens,
      readFirstTouch: () async => const FirstTouch(
        utmSource: 'google-play',
        utmMedium: 'organic',
      ),
      clearFirstTouch: () async {
        clears += 1;
      },
    );

    await repository.register(username: 'new-player', password: 'password-123');

    final FakeRequest request = fake.adapter.requests.singleWhere(
      (FakeRequest request) => request.path == '/auth/register',
    );
    expect(request.body['first_touch'], <String, String>{
      'utm_source': 'google-play',
      'utm_medium': 'organic',
    });
    expect(clears, 1);
  });

  test('AuthRepository.completeGoogleSignup sends the captured snapshot', () async {
    final FakeMayosApi fake = _signedOutFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    var clears = 0;
    final AuthRepository repository = _repository(
      fake,
      tokens,
      readFirstTouch: () async => const FirstTouch(
        utmSource: 'campaign',
        referrerHost: 'example.com',
      ),
      clearFirstTouch: () async {
        clears += 1;
      },
    );

    await repository.completeGoogleSignup(
      signupTicket: fake.googleSignupTicket,
      username: 'google-player',
      idToken: 'google-id-token',
    );

    final FakeRequest request = fake.adapter.requests.singleWhere(
      (FakeRequest request) => request.path == '/auth/google/complete',
    );
    expect(request.body['first_touch'], <String, String>{
      'utm_source': 'campaign',
      'referrer_host': 'example.com',
    });
    expect(clears, 1);
  });

  test('AuthRepository registration succeeds when acquisition reader throws', () async {
    final FakeMayosApi fake = _signedOutFake();
    final AuthRepository repository = _repository(
      fake,
      InMemoryTokenStore(),
      readFirstTouch: () async => throw StateError('storage unavailable'),
    );

    await repository.register(username: 'no-acquisition', password: 'password-123');

    final FakeRequest request = fake.adapter.requests.singleWhere(
      (FakeRequest request) => request.path == '/auth/register',
    );
    expect(request.body.containsKey('first_touch'), isFalse);
  });
}

FakeMayosApi _signedOutFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.recoveryEmail = 'player@example.com';
  return fake;
}

AuthRepository _repository(
  FakeMayosApi fake,
  InMemoryTokenStore tokens, {
  Future<FirstTouch?> Function()? readFirstTouch,
  Future<void> Function()? clearFirstTouch,
}) {
  final InMemoryChatCacheStore chatCache = InMemoryChatCacheStore();
  return AuthRepository(
    api: ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    ),
    tokens: tokens,
    chatCache: chatCache,
    eraser: AccountDataEraser(
      drafts: InMemoryDraftStore(),
      workoutCache: InMemoryWorkoutCacheStore(),
      chatCache: chatCache,
      baselines: InMemoryBaselineCacheStore(),
      activeWorkout: InMemoryActiveWorkoutStore(),
      workoutStartNotice: InMemoryWorkoutStartNoticeStore(),
    ),
    readFirstTouch: readFirstTouch,
    clearFirstTouch: clearFirstTouch,
  );
}

class _FakeFirstTouchPersistence implements FirstTouchPersistence {
  String? value;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String value) async {
    this.value = value;
  }

  @override
  Future<void> clear() async {
    value = null;
  }
}

class _FakeAcquisitionSource implements AcquisitionSource {
  _FakeAcquisitionSource(this.result);

  final Future<FirstTouch?> result;

  @override
  Future<FirstTouch?> captureFirstTouch() => result;

  @override
  Future<void> clearAfterRegistration() async {}
}

class _ThrowingAcquisitionSource implements AcquisitionSource {
  @override
  Future<FirstTouch?> captureFirstTouch() async =>
      throw StateError('plugin unavailable');

  @override
  Future<void> clearAfterRegistration() async {}
}
