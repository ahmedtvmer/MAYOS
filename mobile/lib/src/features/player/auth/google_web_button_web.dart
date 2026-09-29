import 'package:flutter/widgets.dart';
import 'package:google_sign_in_web/web_only.dart';

Widget renderGoogleWebButton({
  required bool darkTheme,
  required double width,
}) =>
    SizedBox(
      height: 48,
      child: renderButton(
        configuration: GSIButtonConfiguration(
          type: GSIButtonType.standard,
          theme:
              darkTheme ? GSIButtonTheme.filledBlack : GSIButtonTheme.outline,
          size: GSIButtonSize.large,
          text: GSIButtonText.continueWith,
          minimumWidth: width,
        ),
      ),
    );
