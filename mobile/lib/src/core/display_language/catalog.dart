import '../password_policy.dart';

/// Small hand-written app catalog entry point. Product copy is added here as
/// each surface joins the account Display language workflow.
const supportedDisplayLanguages = <String>{'en', 'ar'};

bool isSupportedDisplayLanguage(Object? value) =>
    value is String && supportedDisplayLanguages.contains(value);

String normalizeDisplayLanguage(Object? value) =>
    isSupportedDisplayLanguage(value) ? value! as String : 'en';

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
  String get logIn => isArabic ? 'تسجيل الدخول' : 'Log in';
  String get signIn => isArabic ? 'تسجيل الدخول' : 'Sign in';
  String get signInLead => isArabic
      ? 'سجّل الدخول لمواصلة التدريب من حيث توقفت.'
      : 'Sign in to keep training and pick up where you left off.';
  String get createAccount => isArabic ? 'إنشاء حساب' : 'Create account';
  String get createAccountLink => isArabic ? 'إنشاء حساب' : 'Create an account';
  String get registerLead => isArabic
      ? 'أنشئ حساب MAYOS لبدء التدريب.'
      : 'Set up your MAYOS account to start training.';
  String get forgotPassword =>
      isArabic ? 'نسيت كلمة المرور' : 'Forgot password';
  String get forgotPasswordQuestion =>
      isArabic ? 'نسيت كلمة المرور؟' : 'Forgot password?';
  String get resetPassword =>
      isArabic ? 'إعادة تعيين كلمة المرور' : 'Reset password';
  String get resetPasswordLead => isArabic
      ? 'اختر كلمة مرور جديدة لحسابك.'
      : 'Choose a new password for your account.';
  String get recoveryEmail =>
      isArabic ? 'البريد الإلكتروني للاسترداد' : 'Recovery email';
  String get chooseUsername =>
      isArabic ? 'اختر اسم المستخدم' : 'Choose your username';
  String get chooseUsernameLead => isArabic
      ? 'اختر الاسم الذي ستتدرب به. يجب أن يكون متاحًا.'
      : 'Pick the name you want to train under. It must be free.';
  String get privacyPolicy => isArabic ? 'سياسة الخصوصية' : 'Privacy policy';
  String get passwordChanged => isArabic
      ? 'تم تغيير كلمة المرور. سجّل الدخول بكلمة المرور الجديدة.'
      : 'Password changed. Sign in with your new password.';
  String get username => isArabic ? 'اسم المستخدم' : 'Username';
  String get password => isArabic ? 'كلمة المرور' : 'Password';
  String get confirmPassword =>
      isArabic ? 'تأكيد كلمة المرور' : 'Confirm password';
  String get newPassword => isArabic ? 'كلمة المرور الجديدة' : 'New password';
  String get showPassword => isArabic ? 'إظهار كلمة المرور' : 'Show password';
  String get hidePassword => isArabic ? 'إخفاء كلمة المرور' : 'Hide password';
  String get passwordMismatch =>
      isArabic ? 'كلمتا المرور غير متطابقتين.' : 'Passwords do not match.';
  String get passwordLength => isArabic
      ? 'استخدم $kMinPasswordLength أحرف على الأقل.'
      : 'Use at least $kMinPasswordLength characters.';
  String get passwordLengthHint => isArabic
      ? '$kMinPasswordLength أحرف على الأقل'
      : 'At least $kMinPasswordLength characters';
  String get keepMeSignedIn =>
      isArabic ? 'إبقائي مسجلًا للدخول' : 'Keep me signed in';
  String get iHaveCoachInvite => isArabic
      ? 'لدي رمز دعوة لتفعيل دور المدرب'
      : 'I have a coach invite code';
  String get hideCoachInvite =>
      isArabic ? 'إخفاء رمز دعوة لتفعيل دور المدرب' : 'Hide coach invite code';
  String get coachInviteCode =>
      isArabic ? 'رمز دعوة لتفعيل دور المدرب' : 'Coach invite code';
  String get alreadyHaveAccount =>
      isArabic ? 'لدي حساب بالفعل' : 'I already have an account';
  String get sendResetLink =>
      isArabic ? 'إرسال رابط إعادة التعيين' : 'Send reset link';
  String get backToLogIn =>
      isArabic ? 'العودة إلى تسجيل الدخول' : 'Back to log in';
  String get backToSignIn =>
      isArabic ? 'العودة إلى تسجيل الدخول' : 'Back to sign in';
  String get email => isArabic ? 'البريد الإلكتروني' : 'Email';
  String get setNewPassword =>
      isArabic ? 'تعيين كلمة مرور جديدة' : 'Set new password';
  String get requestNewLink =>
      isArabic ? 'طلب رابط جديد' : 'Request a new link';
  String get resetCode => isArabic ? 'رمز إعادة التعيين' : 'Reset code';
  String get saveEmail => isArabic ? 'حفظ البريد الإلكتروني' : 'Save email';
  String get logOut => isArabic ? 'تسجيل الخروج' : 'Log out';
  String get createSeparateAccount => isArabic
      ? 'إنشاء حساب منفصل على أي حال'
      : 'Create a separate account anyway';
  String get existingAccountTitle => isArabic
      ? 'لديك حساب MAYOS لهذا البريد الإلكتروني بالفعل.'
      : 'You already have a MAYOS account for this email.';
  String get existingAccountLead => isArabic
      ? 'سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
      : 'Log in with your password, then connect Google in Settings.';
  String get existingAccountNudge => isArabic
      ? 'لديك حساب MAYOS بالفعل؟ سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
      : 'Already have a MAYOS account? Log in with your password, then connect Google in Settings';
  String get recoveryEmailLead => isArabic
      ? 'أضف بريدًا للاسترداد لتتمكن من إعادة تعيين كلمة المرور إذا فقدتها. يُحفظ منفصلًا عن بيانات تدريبك.'
      : 'Add a recovery email so you can reset your password if you lose it. It is kept separately from your training data.';
  String get googleSignupIncomplete => isArabic
      ? 'تعذر إكمال تسجيل الدخول عبر Google، لذلك لم يتم إنشاء حساب.'
      : 'The Google sign-in could not be finished, so no account was created.';
  String get googleSignupExpired => isArabic
      ? 'انتهت صلاحية تسجيل الدخول عبر Google. يُرجى المحاولة مرة أخرى.'
      : 'Your Google sign-up expired. Please try again.';
  String get usernameFormatError => isArabic
      ? 'استخدم من 3 إلى 30 حرفًا من a–z و0–9 و_ و- (بحروف صغيرة).'
      : 'Use 3–30 characters from a–z, 0–9, _ and - (lowercase).';
  String get usernameTaken =>
      isArabic ? 'اسم المستخدم مستخدم بالفعل.' : 'That username is taken.';
  String get checkingAvailability =>
      isArabic ? 'جارٍ التحقق من التوفر…' : 'Checking availability…';
  String get usernameAvailable =>
      isArabic ? 'اسم المستخدم متاح.' : 'This username is free.';
  String get availabilityCheckFailed =>
      isArabic ? 'تعذر التحقق من التوفر.' : 'Could not check availability.';
  String get forgotEmailHint => isArabic
      ? 'أدخل بريد الاسترداد وسنرسل رابط إعادة التعيين. افتحه على هذا الجهاز لاختيار كلمة مرور جديدة.'
      : 'Enter your recovery email and we will send a reset link. Open it on this device to choose a new password.';
  String get resetRequestConfirmation => isArabic
      ? 'إذا كان هذا البريد الإلكتروني مرتبطًا بحساب، فسيصلك رابط إعادة التعيين قريبًا.'
      : 'If this email is linked to a ledger, a reset link is on its way.';
  String get noEmailHint => isArabic
      ? 'لم يصلك بريد؟ تحقق من العنوان،'
      : "Didn't get an email? Check the address,";
  String get signUp => isArabic ? 'أنشئ حسابًا' : 'sign up';
  String get forgotSettingsHint => isArabic
      ? 'أو سجّل الدخول وأضف بريدًا للاسترداد في الإعدادات.'
      : 'or log in and add a recovery email in Settings.';
  String get signInOr => isArabic ? 'أو' : 'or';
  String get homeScreenHint => isArabic
      ? 'أضف MAYOS: مشاركة ← إضافة إلى الشاشة الرئيسية.'
      : 'Add MAYOS: Share → Add to Home Screen.';
  String get dismissHomeScreenHint =>
      isArabic ? 'إخفاء تلميح الشاشة الرئيسية' : 'Dismiss Home Screen hint';
  String get googleName =>
      isArabic ? 'المتابعة باستخدام Google' : 'Continue with Google';
}
