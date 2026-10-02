import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'catalog.dart';
import 'controller.dart';

/// Reads the selected app copy in widget code that is not itself a Consumer.
MayosCopy displayCopyOf(BuildContext context) {
  try {
    return MayosCopy(
      ProviderScope.containerOf(context).read(displayLanguageProvider),
    );
  } on StateError {
    // Small standalone widgets (including the brand header) also render in
    // plain MaterialApp tests and previews without a ProviderScope.
    return MayosCopy(Localizations.localeOf(context).languageCode);
  }
}
