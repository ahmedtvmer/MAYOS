import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'browser_key_value_store.dart';

const supportedDisplayLanguages = <String>{'en', 'ar'};

/// Small hand-written app catalog entry point. Product copy is added here as
/// each surface joins the account Display language workflow.
class MayosCopy {
  const MayosCopy(this.languageCode);
  final String languageCode;
  bool get isArabic => languageCode == 'ar';
  String get settings => isArabic ? 'الإعدادات' : 'Settings';
  String get displayLanguage => isArabic ? 'لغة العرض' : 'Display language';
  String get english => isArabic ? 'الإنجليزية' : 'English';
  String get arabic => isArabic ? 'العربية' : 'Arabic';
  String get save => isArabic ? 'حفظ' : 'Save';
  String get languageSaved =>
      isArabic ? 'تم حفظ لغة العرض.' : 'Display language saved.';
  String get languageSaveFailed =>
      isArabic ? 'تعذر حفظ لغة العرض.' : 'Could not save Display language.';
  String translate(String value) => switch (value) {
        'Log in' => isArabic ? 'تسجيل الدخول' : value,
        'Create account' => isArabic ? 'إنشاء حساب' : value,
        'Forgot password' => isArabic ? 'نسيت كلمة المرور' : value,
        'Reset password' => isArabic ? 'إعادة تعيين كلمة المرور' : value,
        'Choose a new password for your account.' =>
          isArabic ? 'اختر كلمة مرور جديدة لحسابك.' : value,
        'Recovery email' => isArabic ? 'البريد الإلكتروني للاسترداد' : value,
        'Choose your username' => isArabic ? 'اختر اسم المستخدم' : value,
        'Sign in to keep training and pick up where you left off.' =>
          isArabic ? 'سجّل الدخول لمواصلة التدريب من حيث توقفت.' : value,
        'Set up your MAYOS account to start training.' =>
          isArabic ? 'أنشئ حساب MAYOS لبدء التدريب.' : value,
        'Sign in' => isArabic ? 'تسجيل الدخول' : value,
        'Create an account' => isArabic ? 'إنشاء حساب' : value,
        'Forgot password?' => isArabic ? 'نسيت كلمة المرور؟' : value,
        'Privacy policy' => isArabic ? 'سياسة الخصوصية' : value,
        'Password changed. Sign in with your new password.' => isArabic
            ? 'تم تغيير كلمة المرور. سجّل الدخول بكلمة المرور الجديدة.'
            : value,
        'Username' => isArabic ? 'اسم المستخدم' : value,
        'Keep me signed in' => isArabic ? 'إبقائي مسجلًا للدخول' : value,
        'I already have an account' => isArabic ? 'لدي حساب بالفعل' : value,
        'Hide coach invite code' =>
          isArabic ? 'إخفاء رمز دعوة لتفعيل دور المدرب' : value,
        'I have a coach invite code' =>
          isArabic ? 'لدي رمز دعوة لتفعيل دور المدرب' : value,
        'Coach invite code' => isArabic ? 'رمز دعوة لتفعيل دور المدرب' : value,
        'At least 8 characters' => isArabic ? '8 أحرف على الأقل' : value,
        'Confirm password' => isArabic ? 'تأكيد كلمة المرور' : value,
        'Send reset link' => isArabic ? 'إرسال رابط إعادة التعيين' : value,
        'Back to log in' => isArabic ? 'العودة إلى تسجيل الدخول' : value,
        'Email' => isArabic ? 'البريد الإلكتروني' : value,
        "Didn't get an email? Check the address," =>
          isArabic ? 'لم يصلك بريد؟ تحقق من العنوان،' : value,
        'sign up' => isArabic ? 'أنشئ حسابًا' : value,
        'or log in and add a recovery email in Settings.' => isArabic
            ? 'أو سجّل الدخول وأضف بريدًا للاسترداد في الإعدادات.'
            : value,
        'Enter your recovery email and we will send a reset link. Open it on this device to choose a new password.' =>
          isArabic
              ? 'أدخل بريد الاسترداد وسنرسل رابط إعادة التعيين. افتحه على هذا الجهاز لاختيار كلمة مرور جديدة.'
              : value,
        'Set new password' => isArabic ? 'تعيين كلمة مرور جديدة' : value,
        'Request a new link' => isArabic ? 'طلب رابط جديد' : value,
        'Reset code' => isArabic ? 'رمز إعادة التعيين' : value,
        'New password' => isArabic ? 'كلمة المرور الجديدة' : value,
        'Save email' => isArabic ? 'حفظ البريد الإلكتروني' : value,
        'Log out' => isArabic ? 'تسجيل الخروج' : value,
        'Create a separate account anyway' =>
          isArabic ? 'إنشاء حساب منفصل على أي حال' : value,
        'Use a different account' => isArabic ? 'استخدام حساب آخر' : value,
        'Back to sign in' => isArabic ? 'العودة إلى تسجيل الدخول' : value,
        'Pick the name you want to train under. It must be free.' =>
          isArabic ? 'اختر الاسم الذي ستتدرب به. يجب أن يكون متاحًا.' : value,
        'You already have a MAYOS account for this email.' =>
          isArabic ? 'لديك حساب MAYOS لهذا البريد الإلكتروني بالفعل.' : value,
        'Log in with your password, then connect Google in Settings.' =>
          isArabic
              ? 'سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
              : value,
        'Already have a MAYOS account? Log in with your password, then connect Google in Settings' =>
          isArabic
              ? 'لديك حساب MAYOS بالفعل؟ سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
              : value,
        'Add a recovery email so you can reset your password if you lose it. It is kept separately from your training data.' =>
          isArabic
              ? 'أضف بريدًا للاسترداد لتتمكن من إعادة تعيين كلمة المرور إذا فقدتها. يُحفظ منفصلًا عن بيانات تدريبك.'
              : value,
        'The Google sign-in could not be finished, so no account was created.' =>
          isArabic
              ? 'تعذر إكمال تسجيل الدخول عبر Google، لذلك لم يتم إنشاء حساب.'
              : value,
        'Password' => isArabic ? 'كلمة المرور' : value,
        'Show password' => isArabic ? 'إظهار كلمة المرور' : value,
        'Hide password' => isArabic ? 'إخفاء كلمة المرور' : value,
        'Passwords do not match.' =>
          isArabic ? 'كلمتا المرور غير متطابقتين.' : value,
        'Use at least 8 characters.' =>
          isArabic ? 'استخدم 8 أحرف على الأقل.' : value,
        'or' => isArabic ? 'أو' : value,
        'Add MAYOS: Share → Add to Home Screen.' =>
          isArabic ? 'أضف MAYOS: مشاركة ← إضافة إلى الشاشة الرئيسية.' : value,
        'Dismiss Home Screen hint' =>
          isArabic ? 'إخفاء تلميح الشاشة الرئيسية' : value,
        'Settings' => settings,
        'Display language' => displayLanguage,
        _ => value,
      };
}

abstract interface class DisplayLanguageStore {
  Future<String?> read();
  Future<void> write(String language);
  Future<String?> readAccount(String accountId);
  Future<void> writeAccount(String accountId, String language);
  Future<void> deleteAccount(String accountId);
}

class PlatformDisplayLanguageStore implements DisplayLanguageStore {
  PlatformDisplayLanguageStore(
      {FlutterSecureStorage? secureStorage,
      BrowserKeyValueStore? browserStorage,
      bool? isWeb})
      : _secure = secureStorage ?? const FlutterSecureStorage(),
        _browser = browserStorage ?? createBrowserKeyValueStore(),
        _isWeb = isWeb ?? kIsWeb;
  final FlutterSecureStorage _secure;
  final BrowserKeyValueStore _browser;
  final bool _isWeb;
  static const _key = 'mayos.display_language';
  static const _accountPrefix = 'mayos.display_language.account.';
  static final Map<String, String> _pluginFallback = <String, String>{};

  Future<String?> _secureRead(String key) async {
    try {
      return await _secure.read(key: key);
    } on MissingPluginException {
      return _pluginFallback[key];
    }
  }

  Future<void> _secureWrite(String key, String value) async {
    try {
      await _secure.write(key: key, value: value);
    } on MissingPluginException {
      _pluginFallback[key] = value;
    }
  }

  Future<void> _secureDelete(String key) async {
    try {
      await _secure.delete(key: key);
    } on MissingPluginException {
      _pluginFallback.remove(key);
    }
  }

  @override
  Future<String?> read() async =>
      _isWeb ? _browser.getItem(_key) : _secureRead(_key);
  @override
  Future<void> write(String value) async {
    if (_isWeb) {
      _browser.setItem(_key, value);
    } else {
      await _secureWrite(_key, value);
    }
  }

  @override
  Future<String?> readAccount(String id) async => _isWeb
      ? _browser.getItem('$_accountPrefix$id')
      : _secureRead('$_accountPrefix$id');
  @override
  Future<void> writeAccount(String id, String value) async {
    if (_isWeb) {
      _browser.setItem('$_accountPrefix$id', value);
    } else {
      await _secureWrite('$_accountPrefix$id', value);
    }
  }

  @override
  Future<void> deleteAccount(String id) async {
    if (_isWeb) {
      _browser.removeItem('$_accountPrefix$id');
    } else {
      await _secureDelete('$_accountPrefix$id');
    }
  }
}

class InMemoryDisplayLanguageStore implements DisplayLanguageStore {
  String? value;
  final Map<String, String> accountValues = <String, String>{};
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String language) async => value = language;
  @override
  Future<String?> readAccount(String id) async => accountValues[id];
  @override
  Future<void> writeAccount(String id, String language) async =>
      accountValues[id] = language;
  @override
  Future<void> deleteAccount(String id) async {
    accountValues.remove(id);
  }
}

final displayLanguageStoreProvider = Provider<DisplayLanguageStore>(
  (ref) => PlatformDisplayLanguageStore(),
);

final displayLanguageProvider =
    StateNotifierProvider<DisplayLanguageController, String>((ref) =>
        DisplayLanguageController(ref.watch(displayLanguageStoreProvider),
            systemLanguage: ref.watch(systemDisplayLanguageProvider)));

final systemDisplayLanguageProvider = Provider<String>(
    (ref) => WidgetsBinding.instance.platformDispatcher.locale.languageCode);

class DisplayLanguageSelector extends ConsumerWidget {
  const DisplayLanguageSelector({super.key, this.compact = false});
  final bool compact;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final language = ref.watch(displayLanguageProvider);
    return Align(
      alignment: AlignmentDirectional.centerEnd,
      child: DropdownButton<String>(
        key: const Key('display_language_selector'),
        value: language,
        underline: const SizedBox.shrink(),
        items: <DropdownMenuItem<String>>[
          DropdownMenuItem(
              value: 'en',
              child: Text(language == 'ar' ? 'الإنجليزية' : 'English')),
          DropdownMenuItem(
              value: 'ar',
              child: Text(language == 'ar' ? 'العربية' : 'Arabic')),
        ],
        onChanged: (value) {
          if (value != null) {
            ref.read(displayLanguageProvider.notifier).choose(value);
          }
        },
      ),
    );
  }
}

class DisplayLanguageController extends StateNotifier<String> {
  DisplayLanguageController(this._store, {String? systemLanguage})
      : super(_supported(systemLanguage ?? _platformLanguage()));
  final DisplayLanguageStore _store;
  static String _platformLanguage() =>
      WidgetsBinding.instance.platformDispatcher.locale.languageCode;
  static String _supported(String code) {
    return supportedDisplayLanguages.contains(code) ? code : 'en';
  }

  Future<void> initialize({String? accountId}) async {
    if (accountId != null) {
      final accountValue = await _store.readAccount(accountId);
      if (supportedDisplayLanguages.contains(accountValue)) {
        _storeChoiceLoaded = true;
        state = accountValue!;
        return;
      }
    }
    final saved = await _store.read();
    if (supportedDisplayLanguages.contains(saved)) {
      _storeChoiceLoaded = true;
      state = saved!;
    } else {
      await _store.write(state);
      _storeChoiceLoaded = true;
    }
  }

  Future<void> choose(String value) async {
    if (!supportedDisplayLanguages.contains(value)) {
      return;
    }
    await _store.write(value);
    _storeChoiceLoaded = true;
    state = value;
  }

  Future<void> useAccount(String accountId, String value) async {
    final confirmed = supportedDisplayLanguages.contains(value) ? value : 'en';
    await _store.writeAccount(accountId, confirmed);
    _storeChoiceLoaded = true;
    state = confirmed;
  }

  void systemLanguageChanged(String code) {
    if (_storeChoiceLoaded == false) state = _supported(code);
  }

  bool _storeChoiceLoaded = false;
}
