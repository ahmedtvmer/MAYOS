import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/connectivity.dart';
import 'package:mayos_mobile/src/core/foreground_policy.dart';
import 'package:mayos_mobile/src/core/refetch_on_reconnect.dart';

/// #894: returning to the app refreshes only after a real stay in the
/// background, and a single failed request does not flash the offline banner.
void main() {
  group('ResumeGate', () {
    late DateTime now;
    ResumeGate gate(Duration? threshold) =>
        ResumeGate(threshold, now: () => now);

    setUp(() => now = DateTime(2026, 11, 28, 9));

    test('without a threshold every resume refreshes', () {
      final ResumeGate resume = gate(null);
      expect(resume.onLifecycle(AppLifecycleState.inactive), isFalse);
      expect(resume.onLifecycle(AppLifecycleState.resumed), isTrue);
    });

    test('the notification shade (inactive, then resumed) never refreshes', () {
      final ResumeGate resume = gate(const Duration(seconds: 30));
      resume.onLifecycle(AppLifecycleState.inactive);
      now = now.add(const Duration(minutes: 5));
      expect(resume.onLifecycle(AppLifecycleState.resumed), isFalse);
    });

    test('a short trip to another app does not refresh', () {
      final ResumeGate resume = gate(const Duration(seconds: 30));
      resume.onLifecycle(AppLifecycleState.inactive);
      resume.onLifecycle(AppLifecycleState.hidden);
      resume.onLifecycle(AppLifecycleState.paused);
      now = now.add(const Duration(seconds: 29));
      resume.onLifecycle(AppLifecycleState.hidden);
      resume.onLifecycle(AppLifecycleState.inactive);
      expect(resume.onLifecycle(AppLifecycleState.resumed), isFalse);
    });

    test('a stay in the background from the first hide refreshes once', () {
      final ResumeGate resume = gate(const Duration(seconds: 30));
      resume.onLifecycle(AppLifecycleState.hidden);
      now = now.add(const Duration(seconds: 20));
      resume.onLifecycle(AppLifecycleState.paused);
      now = now.add(const Duration(seconds: 10));
      expect(resume.onLifecycle(AppLifecycleState.resumed), isTrue);
      // The next shade pull starts from scratch.
      resume.onLifecycle(AppLifecycleState.inactive);
      expect(resume.onLifecycle(AppLifecycleState.resumed), isFalse);
    });
  });

  group('ReconnectController', () {
    test('counts a real return and resets connections first', () {
      DateTime now = DateTime(2026, 11, 28, 9);
      final List<String> events = <String>[];
      final ReconnectController controller = ReconnectController(
        resumeGate: ResumeGate(const Duration(seconds: 30), now: () => now),
        onReturn: () => events.add('reset'),
      );
      addTearDown(controller.dispose);
      controller.addListener((int value) => events.add('refetch $value'),
          fireImmediately: false);

      controller.didChangeAppLifecycleState(AppLifecycleState.inactive);
      controller.didChangeAppLifecycleState(AppLifecycleState.resumed);
      expect(events, isEmpty);

      controller.didChangeAppLifecycleState(AppLifecycleState.paused);
      now = now.add(const Duration(minutes: 2));
      controller.didChangeAppLifecycleState(AppLifecycleState.resumed);
      expect(events, <String>['reset', 'refetch 1']);
    });
  });

  group('ConnectivityController offline grace', () {
    testWidgets('a failure followed by a response within the grace stays online',
        (WidgetTester tester) async {
      final ConnectivityController controller =
          ConnectivityController(offlineGrace: const Duration(seconds: 3));
      addTearDown(controller.dispose);
      controller.noteTransportFailure();
      await tester.pump(const Duration(seconds: 1));
      controller.markOnline();
      await tester.pump(const Duration(seconds: 5));
      expect(controller.state, isTrue);
    });

    testWidgets('a failure with no response goes offline after the grace',
        (WidgetTester tester) async {
      final ConnectivityController controller =
          ConnectivityController(offlineGrace: const Duration(seconds: 3));
      addTearDown(controller.dispose);
      controller.noteTransportFailure();
      await tester.pump(const Duration(seconds: 2));
      expect(controller.state, isTrue);
      await tester.pump(const Duration(seconds: 1));
      expect(controller.state, isFalse);
      controller.markOnline();
      expect(controller.state, isTrue);
    });

    test('without a grace a failure is offline at once', () {
      final ConnectivityController controller = ConnectivityController();
      addTearDown(controller.dispose);
      controller.noteTransportFailure();
      expect(controller.state, isFalse);
    });

    test('an explicit offline signal is immediate even with a grace', () {
      final ConnectivityController controller =
          ConnectivityController(offlineGrace: const Duration(seconds: 3));
      addTearDown(controller.dispose);
      controller.markOffline();
      expect(controller.state, isFalse);
    });
  });
}
