import 'dart:io';

import 'package:play_install_referrer/play_install_referrer.dart';

import 'first_touch.dart';
import 'secure_store.dart';

const String _firstTouchKey = 'mayos.first_touch.install';

AcquisitionSource createAcquisitionSource({
  FirstTouchPersistence? persistence,
  InstallReferrerReader? installReferrerReader,
}) {
  if (!Platform.isAndroid) return _EmptyAcquisitionSource();
  return PersistentAcquisitionSource(
      persistence: persistence ?? _SecureFirstTouchPersistence(SecureStore()),
      readCurrent: () async {
        final String? rawReferrer = await (installReferrerReader ?? _readInstallReferrer)()
            .timeout(const Duration(milliseconds: 200), onTimeout: () => null);
        return rawReferrer == null
            ? null
            : FirstTouch.fromInstallReferrer(rawReferrer);
      },
    );
}

Future<String?> _readInstallReferrer() async {
  final ReferrerDetails details = await PlayInstallReferrer.installReferrer;
  return details.installReferrer;
}

class _SecureFirstTouchPersistence implements FirstTouchPersistence {
  _SecureFirstTouchPersistence(this._store);

  final SecureStore _store;

  @override
  Future<String?> read() => _store.readString(_firstTouchKey);

  @override
  Future<void> write(String value) => _store.writeString(_firstTouchKey, value);

  @override
  Future<void> clear() => _store.delete(_firstTouchKey);
}

class _EmptyAcquisitionSource implements AcquisitionSource {
  @override
  Future<FirstTouch?> captureFirstTouch() async => null;

  @override
  Future<void> clearAfterRegistration() async {}
}
