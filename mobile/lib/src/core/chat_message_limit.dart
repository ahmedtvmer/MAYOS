import 'package:flutter/services.dart';

/// Player chat input limit, matching `svc.schemas.CHAT_MESSAGE_MAX_CHARS`.
const int chatMessageMaxChars = 400;

/// Starts showing the remaining-character count near the message limit.
const int chatMessageCounterStart = 320;

/// Enforces the server's Unicode code-point count, including when text is pasted.
class ChatMessageCodePointLengthFormatter extends TextInputFormatter {
  const ChatMessageCodePointLengthFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final Runes codePoints = newValue.text.runes;
    if (codePoints.length <= chatMessageMaxChars) return newValue;

    final String text =
        String.fromCharCodes(codePoints.take(chatMessageMaxChars));
    final int offset = newValue.selection.extentOffset.clamp(0, text.length);
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: offset),
      composing: TextRange.empty,
    );
  }
}
