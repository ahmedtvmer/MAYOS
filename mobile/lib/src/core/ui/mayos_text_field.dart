import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// A thin wrapper over [TextField] so inputs share the themed decoration and
/// consistent text actions. The visual treatment lives in the theme's
/// `inputDecorationTheme`; this exists to keep call sites uniform.
class MayosTextField extends StatelessWidget {
  const MayosTextField({
    super.key,
    this.controller,
    this.label,
    this.hint,
    this.helperText,
    this.errorText,
    this.obscureText = false,
    this.enabled = true,
    this.readOnly = false,
    this.autofocus = false,
    this.keyboardType,
    this.textDirection,
    this.textInputAction,
    this.textCapitalization = TextCapitalization.none,
    this.autofillHints,
    this.autocorrect = true,
    this.enableSuggestions = true,
    this.focusNode,
    this.onSubmitted,
    this.onChanged,
    this.validator,
    this.prefixIcon,
    this.suffixIcon,
    this.minLines,
    this.maxLines = 1,
    this.maxLength,
    this.maxLengthEnforcement,
    this.inputFormatters,
    this.hideCounter = false,
    this.dense = false,
    this.fieldKey,
  });

  final TextEditingController? controller;
  final String? label;
  final String? hint;
  final String? helperText;
  final String? errorText;
  final bool obscureText;
  final bool enabled;
  final bool readOnly;
  final bool autofocus;
  final TextInputType? keyboardType;
  final TextDirection? textDirection;
  final TextInputAction? textInputAction;
  final TextCapitalization textCapitalization;
  final Iterable<String>? autofillHints;
  final bool autocorrect;
  final bool enableSuggestions;
  final FocusNode? focusNode;
  final ValueChanged<String>? onSubmitted;
  final ValueChanged<String>? onChanged;
  final String? Function(String?)? validator;
  final Widget? prefixIcon;
  final Widget? suffixIcon;
  final int? minLines;
  final int maxLines;

  /// When set, this limit is enforced. The field shows a live `n/maxLength`
  /// counter unless [hideCounter] is true.
  final int? maxLength;

  /// Selects how [maxLength] applies to edits and pasted text.
  final MaxLengthEnforcement? maxLengthEnforcement;

  /// Optional input formatters applied before the text field's length limit.
  final List<TextInputFormatter>? inputFormatters;

  /// Hides the built-in counter while preserving [maxLength] enforcement.
  final bool hideCounter;

  /// Tighter content padding for narrow numeric cells (workout set rows)
  /// while keeping the themed border and label.
  final bool dense;

  /// Applied to the inner [TextField] so existing test keys keep working.
  final Key? fieldKey;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: fieldKey,
      controller: controller,
      focusNode: focusNode,
      obscureText: obscureText,
      enabled: enabled,
      readOnly: readOnly,
      autofocus: autofocus,
      keyboardType: keyboardType,
      textDirection: textDirection,
      textInputAction: textInputAction,
      textCapitalization: textCapitalization,
      autofillHints: autofillHints,
      autocorrect: autocorrect,
      enableSuggestions: enableSuggestions,
      onSubmitted: onSubmitted,
      onChanged: onChanged,
      inputFormatters: inputFormatters,
      minLines: minLines,
      maxLines: maxLines,
      maxLength: maxLength,
      maxLengthEnforcement: maxLengthEnforcement,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        helperText: helperText,
        errorText: errorText,
        prefixIcon: prefixIcon,
        suffixIcon: suffixIcon,
        counterText: hideCounter ? '' : null,
        isDense: dense,
        contentPadding: dense
            ? const EdgeInsets.symmetric(horizontal: 10, vertical: 12)
            : null,
        border: const OutlineInputBorder(),
      ),
    );
  }
}
