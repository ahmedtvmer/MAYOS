import 'first_touch.dart';

AcquisitionSource createAcquisitionSource({
  FirstTouchPersistence? persistence,
  InstallReferrerReader? installReferrerReader,
}) =>
    _EmptyAcquisitionSource();

class _EmptyAcquisitionSource implements AcquisitionSource {
  @override
  Future<FirstTouch?> captureFirstTouch() async => null;

  @override
  Future<void> clearAfterRegistration() async {}
}
