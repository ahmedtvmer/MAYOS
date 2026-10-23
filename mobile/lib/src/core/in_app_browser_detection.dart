/// Recognizes user agents belonging to common embedded social-app browsers.
bool isKnownInAppBrowserUserAgent(String userAgent) {
  final String agent = userAgent.toLowerCase();
  return agent.contains('tiktok') ||
      agent.contains('musical_ly') ||
      agent.contains('trill_') ||
      agent.contains('bytedancewebview') ||
      agent.contains('instagram') ||
      agent.contains('whatsapp') ||
      agent.contains('line/') ||
      agent.contains('snapchat') ||
      agent.contains('gsa/') ||
      agent.contains('twitter') ||
      agent.contains('fb_iab') ||
      agent.contains('fbav') ||
      agent.contains('fban') ||
      agent.contains('facebook');
}
