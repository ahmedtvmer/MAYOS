import 'package:flutter/material.dart';

/// Finds the first strong directional character in free-form text.
///
/// Digits, whitespace, punctuation, and combining marks do not set the base
/// direction. The result is null when the string contains no recognized
/// strong character, so callers can inherit the surrounding direction.
TextDirection? firstStrongTextDirection(String text) {
  int isolateDepth = 0;
  for (final int rune in text.runes) {
    if (rune >= 0x2066 && rune <= 0x2068) {
      isolateDepth++;
      continue;
    }
    if (rune == 0x2069) {
      if (isolateDepth > 0) isolateDepth--;
      continue;
    }
    if (isolateDepth > 0) continue;
    if (_isRightToLeftLetter(rune)) return TextDirection.rtl;
    if (_isLeftToRightLetter(rune)) return TextDirection.ltr;
  }
  return null;
}

/// Applies a free-form string's first-strong direction and aligns its content
/// to that direction. The [text] is only inspected; it is never modified.
class FirstStrongDirection extends StatelessWidget {
  const FirstStrongDirection({
    super.key,
    required this.text,
    required this.child,
  });

  final String text;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final TextDirection? direction = firstStrongTextDirection(text);
    final Widget aligned = Align(
      alignment: AlignmentDirectional.topStart,
      child: child,
    );
    return direction == null
        ? aligned
        : Directionality(textDirection: direction, child: aligned);
  }
}

bool _isRightToLeftLetter(int rune) =>
    // Hebrew and related presentation forms.
    (rune >= 0x05D0 && rune <= 0x05EA) ||
    (rune >= 0x05EF && rune <= 0x05F2) ||
    (rune >= 0xFB1D && rune <= 0xFB4F) ||
    // Arabic letters. Combining marks, punctuation, and Arabic-Indic digits
    // are intentionally excluded so they cannot choose the paragraph base.
    (rune >= 0x0621 && rune <= 0x063A) ||
    (rune >= 0x0641 && rune <= 0x064A) ||
    (rune >= 0x066E && rune <= 0x066F) ||
    (rune >= 0x0671 && rune <= 0x06D3) ||
    rune == 0x06D5 ||
    (rune >= 0x06E5 && rune <= 0x06E6) ||
    (rune >= 0x06EE && rune <= 0x06EF) ||
    (rune >= 0x06FA && rune <= 0x06FC) ||
    rune == 0x06FF ||
    (rune >= 0x0700 && rune <= 0x074F) ||
    (rune >= 0x0750 && rune <= 0x077F) ||
    (rune >= 0x08A0 && rune <= 0x08C9) ||
    (rune >= 0xFB50 && rune <= 0xFD3D) ||
    (rune >= 0xFD50 && rune <= 0xFD8F) ||
    (rune >= 0xFE70 && rune <= 0xFEFC) ||
    (rune >= 0x1EE00 && rune <= 0x1EEFF);

bool _isLeftToRightLetter(int rune) =>
    (rune >= 0x0041 && rune <= 0x005A) ||
    (rune >= 0x0061 && rune <= 0x007A) ||
    (rune >= 0x00C0 && rune <= 0x00D6) ||
    (rune >= 0x00D8 && rune <= 0x00F6) ||
    (rune >= 0x00F8 && rune <= 0x02B8) ||
    (rune >= 0x1D00 && rune <= 0x1D7F) ||
    (rune >= 0x1D80 && rune <= 0x1DBF) ||
    (rune >= 0x1E00 && rune <= 0x1EFF) ||
    (rune >= 0x0370 && rune <= 0x0373) ||
    (rune >= 0x0376 && rune <= 0x0377) ||
    (rune >= 0x037B && rune <= 0x037D) ||
    rune == 0x037F ||
    rune == 0x0386 ||
    (rune >= 0x0388 && rune <= 0x03FF) ||
    (rune >= 0x0400 && rune <= 0x0481) ||
    (rune >= 0x048A && rune <= 0x052F) ||
    (rune >= 0x0531 && rune <= 0x0556) ||
    (rune >= 0x0560 && rune <= 0x0588) ||
    (rune >= 0x10A0 && rune <= 0x10FF) ||
    (rune >= 0x2C00 && rune <= 0x2DFF) ||
    (rune >= 0x3041 && rune <= 0x30FF) ||
    (rune >= 0x3100 && rune <= 0x312F) ||
    (rune >= 0x3130 && rune <= 0x318F) ||
    (rune >= 0x31A0 && rune <= 0x31BF) ||
    (rune >= 0x31F0 && rune <= 0x31FF) ||
    (rune >= 0x3400 && rune <= 0x4DBF) ||
    (rune >= 0x4E00 && rune <= 0x9FFF) ||
    (rune >= 0xAC00 && rune <= 0xD7A3) ||
    (rune >= 0xF900 && rune <= 0xFAFF) ||
    (rune >= 0x20000 && rune <= 0x3134F);
