import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/ios_safari_detection.dart';

void main() {
  final List<
      ({
        String name,
        String userAgent,
        bool iPadDesktop,
        bool expected,
      })> cases = <({
    String name,
    String userAgent,
    bool iPadDesktop,
    bool expected,
  })>[
    (
      name: 'iPhone Safari',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 '
          'Mobile/15E148 Safari/604.1',
      iPadDesktop: false,
      expected: true,
    ),
    (
      name: 'iPad Safari',
      userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 '
          'Mobile/15E148 Safari/604.1',
      iPadDesktop: false,
      expected: true,
    ),
    (
      name: 'iPadOS desktop-mode Safari',
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
      iPadDesktop: true,
      expected: true,
    ),
    (
      name: 'iOS Chrome',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 '
          'Mobile/15E148 Safari/604.1',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'iOS Firefox',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/116.0 '
          'Mobile/15E148 Safari/605.1.15',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'iOS Edge',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 EdgiOS/117.2045.65',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Google app',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) GSA/282.0.568143716 '
          'Mobile/15E148 Safari/604.1',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Opera iOS',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) OPT/3.0.0 '
          'Mobile/15E148 Safari/605.1.15',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Opera iOS alternate token',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) OPiOS/4.0.0 '
          'Mobile/15E148 Safari/605.1.15',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'DuckDuckGo',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 Ddg/7.0.0',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Yandex Browser',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 YaBrowser/23.1.2.1000',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Gmail / LINE-style WebView',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Line/13.20.0',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Gmail WebView',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
          'Gmail/6.0.240825',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Snapchat',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 Snapchat/12.0.0.0',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Instagram',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 Instagram 300.0.0.0.0',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Facebook app',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 FBAN/FBIOS;FBAV/435.0.0.36.112',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Twitter in-app browser',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 Twitter for iPhone',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'X in-app browser',
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
          'Mobile/15E148 Safari/604.1 X/10.0',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'Android Chrome',
      userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 '
          'Mobile Safari/537.36',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'desktop Safari without iPad touch signal',
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
          'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
      iPadDesktop: false,
      expected: false,
    ),
    (
      name: 'desktop Chrome',
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 '
          'Safari/537.36',
      iPadDesktop: false,
      expected: false,
    ),
  ];

  for (final testCase in cases) {
    test('${testCase.name} ${testCase.expected ? 'matches' : 'is excluded'}',
        () {
      expect(
        isIosSafariUserAgent(
          testCase.userAgent,
          iPadDesktop: testCase.iPadDesktop,
        ),
        testCase.expected,
      );
    });
  }
}
