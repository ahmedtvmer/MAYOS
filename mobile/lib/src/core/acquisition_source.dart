import 'first_touch.dart';
import 'acquisition_source_stub.dart'
    if (dart.library.js_interop) 'acquisition_source_web.dart'
    if (dart.library.io) 'acquisition_source_io.dart' as platform;

export 'first_touch.dart';

AcquisitionSource createAcquisitionSource({
  FirstTouchPersistence? persistence,
  InstallReferrerReader? installReferrerReader,
}) =>
    platform.createAcquisitionSource(
      persistence: persistence,
      installReferrerReader: installReferrerReader,
    );
