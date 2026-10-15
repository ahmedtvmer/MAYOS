/// Reads production-format temporary player labels from a roster answer.
class CoachRosterAlias {
  static final RegExp _pattern = RegExp(
    r'(?<![A-Za-z0-9_])P[0-9a-f]{12}(?![A-Za-z0-9_])',
  );

  /// Returns answer labels that are present in [knownAliases].
  static Set<String> mentionedIn(
    String answer,
    Iterable<String> knownAliases,
  ) {
    final Set<String> known = knownAliases.toSet();
    return _pattern
        .allMatches(answer)
        .map((RegExpMatch match) => match.group(0)!)
        .where(known.contains)
        .toSet();
  }

  /// Replaces labels with their client-side display text.
  static String replaceIn(String answer, String Function(String) displayText) =>
      answer.replaceAllMapped(
        _pattern,
        (Match match) => displayText(match.group(0)!),
      );
}
