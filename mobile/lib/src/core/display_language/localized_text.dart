import '../app_failure.dart';
import 'message_resolution.dart';

class LocalizedText {
  const LocalizedText({required this.text, this.metadata});

  factory LocalizedText.fromJson({
    required Object? text,
    Object? metadata,
  }) {
    final String fallback = text is String ? text : '';
    return LocalizedText(
      text: fallback,
      metadata: ServerFailureMessage.parseMetadata(
        metadata,
        safeFallback: fallback,
      ),
    );
  }

  final String text;
  final ServerFailureMessage? metadata;

  String resolve(String displayLanguage) => resolveStructuredMessage(
        messageCode: metadata?.messageCode,
        messageParams: metadata?.messageParams,
        englishFallback: metadata?.safeEnglishFallback ?? text,
        displayLanguage: displayLanguage,
      );
}
