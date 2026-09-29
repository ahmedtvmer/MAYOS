/// Returns whether [userAgent] belongs to iOS or iPadOS Safari.
///
/// iPadOS desktop-mode Safari reports a Mac user agent, so callers pass the
/// platform and touch-point check separately through [iPadDesktop].
bool isIosSafariUserAgent(String userAgent, {required bool iPadDesktop}) {
  final bool isAppleMobile = iPadDesktop ||
      RegExp(r'\b(iPhone|iPad|iPod)\b', caseSensitive: false)
          .hasMatch(userAgent);
  if (!isAppleMobile) return false;

  final bool hasSafariTokens = RegExp(
    r'\bVersion/[^\s]+.*\bSafari/[^\s]+',
    caseSensitive: false,
  ).hasMatch(userAgent);
  if (!hasSafariTokens) return false;

  return !RegExp(
    r'CriOS|FxiOS|EdgiOS|\bGSA/|\bOPiOS|\bOPT/|\bDdg/|DuckDuckGo|\bYaBrowser/|\bGmail\b|\bLINE(?:/|\b)|\bSnapchat(?:/|\b)|\bTwitter\b|FBAN/|FBAV/|\bInstagram\b|\bX/',
    caseSensitive: false,
  ).hasMatch(userAgent);
}
