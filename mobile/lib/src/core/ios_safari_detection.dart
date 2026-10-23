/// Returns whether [userAgent] is an iOS browser with a share sheet.
///
/// iPadOS desktop-mode Safari reports a Mac user agent, so callers pass the
/// platform and touch-point check separately through [iPadDesktop].
bool isIosShareBrowserUserAgent(String userAgent, {required bool iPadDesktop}) {
  final bool isAppleMobile = iPadDesktop ||
      RegExp(r'\b(iPhone|iPad|iPod)\b', caseSensitive: false)
          .hasMatch(userAgent);
  if (!isAppleMobile) return false;

  final bool supportedBrowser = RegExp(
    r'\bVersion/[^\s]+.*\bSafari/[^\s]+|CriOS/|EdgiOS/|FxiOS/',
    caseSensitive: false,
  ).hasMatch(userAgent);
  if (!supportedBrowser) return false;
  return !RegExp(
    r'\bGSA/|\bOPiOS|\bOPT/|\bDdg/|DuckDuckGo|\bYaBrowser/|\bGmail\b|\bLINE(?:/|\b)|\bSnapchat(?:/|\b)|\bTwitter\b|FBAN/|FBAV/|\bInstagram\b|\bX/',
    caseSensitive: false,
  ).hasMatch(userAgent);
}
