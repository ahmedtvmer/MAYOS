import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'mayos_colors.dart';
import 'mayos_theme_extension.dart';
import 'mayos_typography.dart';

export 'mayos_theme_extension.dart';

/// Builds MAYOS [ThemeData] from semantic tokens.
///
/// Material is used as infrastructure only: every visual default that would
/// otherwise look like an untouched Material 3 template is overridden below.
abstract final class MayosTheme {
  static ThemeData get light => lightForLanguage('en');
  static ThemeData get dark => darkForLanguage('en');

  static ThemeData lightForLanguage(String language) =>
      _build(MayosThemeExtension.light, language: language);
  static ThemeData darkForLanguage(String language) =>
      _build(MayosThemeExtension.dark, language: language);

  /// Dark tokens tuned for the logged-out surfaces drawn on the gym photo
  /// (#110). Links, progress and focused field edges use a lighter blue so they
  /// clear WCAG AA / non-text contrast against the photo.
  static ThemeData get wallpaper => wallpaperForLanguage('en');
  static ThemeData wallpaperForLanguage(String language) => _build(
        MayosThemeExtension.wallpaper,
        linkColor: MayosPalette.wallpaperLink,
        language: language,
      );

  /// The active MAYOS semantic tokens.
  static MayosThemeExtension of(BuildContext context) =>
      Theme.of(context).extension<MayosThemeExtension>() ??
      MayosThemeExtension.light;

  static ColorScheme _scheme(MayosThemeExtension c) {
    final bool dark = c.isDark;
    final ColorScheme base =
        dark ? const ColorScheme.dark() : const ColorScheme.light();
    return base.copyWith(
      brightness: c.brightness,
      primary: c.accent,
      onPrimary: c.onAccent,
      primaryContainer: c.selectedSurface,
      onPrimaryContainer: c.isDark ? c.textPrimary : c.accentPressed,
      secondary: c.textSecondary,
      onSecondary: c.isDark ? c.canvas : c.onAccent,
      secondaryContainer: c.surfaceElevated,
      onSecondaryContainer: c.textPrimary,
      tertiary: c.success,
      onTertiary: c.onSuccess,
      error: c.danger,
      onError: c.onDanger,
      errorContainer:
          c.isDark ? const Color(0x332B1416) : const Color(0xFFFCE8E8),
      onErrorContainer:
          c.isDark ? const Color(0xFFFFD9D9) : const Color(0xFF7A1C1C),
      surface: c.surface,
      onSurface: c.textPrimary,
      onSurfaceVariant: c.textSecondary,
      surfaceContainerLowest: c.surfaceSunken,
      surfaceContainerLow: c.surface,
      surfaceContainer: c.secondarySurface,
      surfaceContainerHigh: c.surfaceElevated,
      surfaceContainerHighest: c.surfaceElevated,
      outline: c.borderStrong,
      outlineVariant: c.border,
      shadow: Color(0x33000000),
      scrim: Color(0x99000000),
      inverseSurface: c.isDark ? c.textPrimary : c.canvas,
      onInverseSurface: c.isDark ? c.canvas : c.textPrimary,
      inversePrimary: c.isDark ? c.accentPressed : c.focusRing,
    );
  }

  static SystemUiOverlayStyle overlayStyle(MayosThemeExtension c) {
    return SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: c.isDark ? Brightness.light : Brightness.dark,
      statusBarBrightness: c.isDark ? Brightness.dark : Brightness.light,
      systemNavigationBarColor: c.canvas,
      systemNavigationBarIconBrightness:
          c.isDark ? Brightness.light : Brightness.dark,
      systemNavigationBarDividerColor: c.canvas,
    );
  }

  static ThemeData _build(MayosThemeExtension c,
      {Color? linkColor, String language = 'en'}) {
    final ColorScheme scheme = _scheme(c);
    final MayosTypography typography = MayosTypography.forLanguage(language);
    final TextTheme textTheme = MayosTypography.textTheme(c, typography);
    final SystemUiOverlayStyle overlay = overlayStyle(c);
    // Links, progress and focus rings default to the accent; the wallpaper theme
    // passes a lighter blue so they clear contrast against the photo.
    final Color link = linkColor ?? c.accent;

    final RoundedRectangleBorder cardShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(16),
      side: BorderSide(color: c.border),
    );

    OutlineInputBorder inputBorder(Color color, [double width = 1]) =>
        OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: color, width: width),
        );

    return ThemeData(
      useMaterial3: true,
      brightness: c.brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: c.canvas,
      canvasColor: c.canvas,
      fontFamily: typography.interfaceFamily,
      fontFamilyFallback: typography.fallbackFamilies,
      textTheme: textTheme,
      primaryTextTheme: textTheme,
      splashFactory: InkSparkle.splashFactory,
      visualDensity: VisualDensity.standard,
      extensions: <ThemeExtension<dynamic>>[c],
      appBarTheme: AppBarTheme(
        backgroundColor: c.canvas,
        foregroundColor: c.textPrimary,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: textTheme.titleLarge,
        toolbarTextStyle: textTheme.bodyMedium,
        iconTheme: IconThemeData(color: c.textPrimary, size: 22),
        actionsIconTheme: IconThemeData(color: c.textPrimary, size: 22),
        systemOverlayStyle: overlay,
        shape: Border(bottom: BorderSide(color: c.border)),
      ),
      cardTheme: CardThemeData(
        color: c.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: cardShape,
        clipBehavior: Clip.antiAlias,
      ),
      dividerTheme: DividerThemeData(
        color: c.border,
        thickness: 1,
        space: 1,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll<Size>(Size(48, 52)),
          padding: const WidgetStatePropertyAll<EdgeInsets>(
              EdgeInsets.symmetric(horizontal: 20, vertical: 14)),
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) {
              return c.isDark ? c.surfaceElevated : c.surfaceSunken;
            }
            if (states.contains(WidgetState.pressed)) return c.accentPressed;
            return c.accent;
          }),
          foregroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) return c.textDisabled;
            return c.onAccent;
          }),
          overlayColor: WidgetStatePropertyAll<Color>(c.pressedOverlay),
          textStyle: WidgetStatePropertyAll<TextStyle>(
              textTheme.labelLarge!.copyWith(color: null)),
          shape: WidgetStatePropertyAll<OutlinedBorder>(
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
          elevation: const WidgetStatePropertyAll<double>(0),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll<Size>(Size(48, 52)),
          padding: const WidgetStatePropertyAll<EdgeInsets>(
              EdgeInsets.symmetric(horizontal: 20, vertical: 14)),
          foregroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) return c.textDisabled;
            return c.textPrimary;
          }),
          side: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.pressed)) {
              return BorderSide(color: c.accent);
            }
            return BorderSide(color: c.borderStrong);
          }),
          overlayColor: WidgetStatePropertyAll<Color>(c.pressedOverlay),
          textStyle: WidgetStatePropertyAll<TextStyle>(
              textTheme.labelLarge!.copyWith(color: null)),
          shape: WidgetStatePropertyAll<OutlinedBorder>(
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll<Size>(Size(48, 48)),
          foregroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.disabled)) return c.textDisabled;
            return link;
          }),
          overlayColor: WidgetStatePropertyAll<Color>(c.accentSubtle),
          padding: const WidgetStatePropertyAll<EdgeInsets>(
              EdgeInsets.symmetric(horizontal: 14, vertical: 10)),
          textStyle: WidgetStatePropertyAll<TextStyle>(
              textTheme.labelLarge!.copyWith(color: null)),
          shape: WidgetStatePropertyAll<OutlinedBorder>(
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll<Size>(Size(48, 48)),
          iconSize: const WidgetStatePropertyAll<double>(22),
          foregroundColor: WidgetStatePropertyAll<Color>(c.textPrimary),
          overlayColor: WidgetStatePropertyAll<Color>(c.pressedOverlay),
          shape: WidgetStatePropertyAll<OutlinedBorder>(
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: c.isDark ? c.surface : c.secondarySurface,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        hintStyle: textTheme.bodyMedium?.copyWith(color: c.textMuted),
        labelStyle: textTheme.bodyMedium?.copyWith(color: c.textSecondary),
        floatingLabelStyle: textTheme.bodySmall?.copyWith(color: link),
        errorStyle: textTheme.bodySmall?.copyWith(color: c.danger),
        border: inputBorder(c.border),
        enabledBorder: inputBorder(c.border),
        focusedBorder: inputBorder(link, 1.6),
        errorBorder: inputBorder(c.danger),
        focusedErrorBorder: inputBorder(c.danger, 1.6),
        disabledBorder: inputBorder(c.border.withValues(alpha: 0.5)),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: c.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: c.selectedSurface,
        elevation: 0,
        height: 68,
        labelTextStyle: WidgetStatePropertyAll<TextStyle>(
            textTheme.labelSmall!.copyWith(color: null)),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final bool selected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: selected ? c.accent : c.textMuted,
            size: 22,
          );
        }),
      ),
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: c.surface,
        selectedItemColor: c.accent,
        unselectedItemColor: c.textMuted,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
        selectedLabelStyle: textTheme.labelSmall,
        unselectedLabelStyle: textTheme.labelSmall,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: c.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: c.border),
        ),
        titleTextStyle: textTheme.titleLarge,
        contentTextStyle: textTheme.bodyMedium,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: c.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        modalBackgroundColor: c.surfaceElevated,
        elevation: 0,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        showDragHandle: true,
        dragHandleColor: c.borderStrong,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: c.isDark ? c.surfaceElevated : c.textPrimary,
        contentTextStyle: textTheme.bodyMedium
            ?.copyWith(color: c.isDark ? c.textPrimary : c.surface),
        actionTextColor: c.isDark ? c.accent : const Color(0xFF9EC1FF),
        behavior: SnackBarBehavior.floating,
        elevation: 0,
        insetPadding: const EdgeInsets.all(16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: c.isDark ? c.surface : c.secondarySurface,
        selectedColor: c.selectedSurface,
        disabledColor: c.surfaceSunken,
        side: BorderSide(color: c.border),
        labelStyle: textTheme.labelMedium!,
        secondaryLabelStyle: textTheme.labelMedium!,
        showCheckmark: false,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: c.textSecondary,
        textColor: c.textPrimary,
        subtitleTextStyle: textTheme.bodySmall,
        titleTextStyle: textTheme.titleMedium,
        contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        minVerticalPadding: 10,
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return c.onAccent;
          return c.textMuted;
        }),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return c.accent;
          return c.surfaceSunken;
        }),
        trackOutlineColor: WidgetStatePropertyAll<Color>(c.borderStrong),
        trackOutlineWidth: const WidgetStatePropertyAll<double>(1),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: link,
        linearTrackColor: c.surfaceSunken,
        circularTrackColor: c.surfaceSunken,
        linearMinHeight: 4,
        borderRadius: BorderRadius.circular(999),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) return c.selectedSurface;
            return Colors.transparent;
          }),
          foregroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) return c.accent;
            return c.textSecondary;
          }),
          side: WidgetStatePropertyAll<BorderSide>(BorderSide(color: c.border)),
          textStyle: WidgetStatePropertyAll<TextStyle>(
              textTheme.labelMedium!.copyWith(color: null)),
          minimumSize: const WidgetStatePropertyAll<Size>(Size(48, 48)),
        ),
      ),
      dropdownMenuTheme: DropdownMenuThemeData(
        menuStyle: MenuStyle(
          backgroundColor: WidgetStatePropertyAll<Color>(c.surfaceElevated),
          surfaceTintColor:
              const WidgetStatePropertyAll<Color>(Colors.transparent),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: c.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: c.border),
        ),
      ),
      datePickerTheme: DatePickerThemeData(
        backgroundColor: c.surfaceElevated,
        surfaceTintColor: Colors.transparent,
        headerBackgroundColor: c.surface,
        headerForegroundColor: c.textPrimary,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: <TargetPlatform, PageTransitionsBuilder>{
          TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
          TargetPlatform.linux: FadeForwardsPageTransitionsBuilder(),
          TargetPlatform.macOS: FadeForwardsPageTransitionsBuilder(),
          TargetPlatform.windows: FadeForwardsPageTransitionsBuilder(),
        },
      ),
    );
  }
}
