# Arabic customer email copy

Status: **owner reviewed** by Thomas on 2026-10-12. The following simple standard Arabic subjects and bodies
were added for #258. Runtime names and links are retained, and reset expiry
uses Western digits.

The minute unit follows number agreement: `دقيقة` for 1, `دقيقتين` for 2,
`دقائق` for 3–10, and `دقيقة` for 11 or more. The configured reset lifetime is
clamped to 5–120 minutes, so runtime reset emails use the plural or singular
form.

## Password reset

**Subject**

> إعادة تعيين كلمة مرور MYOS

**Body**

> تم طلب إعادة تعيين كلمة المرور لحسابك في MYOS.
>
> افتح هذا الرابط لتعيين كلمة مرور جديدة. إذا كان تطبيق MYOS مثبتًا، فسيفتح التطبيق؛ وإلا فستفتح صفحة ويب آمنة.
>
> {reset_link}
>
> يمكن استخدام هذا الرابط مرة واحدة، وينتهي خلال {minutes} {minute_unit}.
>
> إذا لم تطلب ذلك، فتجاهل هذه الرسالة — لن تتغير كلمة مرورك.

## No-account recovery notice

**Subject**

> لا يوجد حساب في MYOS يستخدم هذا البريد الإلكتروني

**Body**

> لا يوجد حساب في MYOS يستخدم هذا البريد الإلكتروني.
>
> يمكنك إنشاء حساب في MYOS من هنا: {signup_link}.
>
> إذا كان لديك حساب بالفعل، فجرّب عنوان البريد الإلكتروني الذي استخدمته عند التسجيل، أو سجّل الدخول وأضف بريدًا إلكترونيًا للاسترداد من الإعدادات.

## Assignment acceptance

**Subject**

> قبل لاعب دعوتك للتدريب مع مدرب في MYOS

**Body**

> مرحبًا {coach_display_name}،
>
> قبل {player_username} دعوتك، وأُنشئت بينكما علاقة تدريب.
>
> افتح MYOS لمراجعة علاقة التدريب. إذا لم تكن تتوقع ذلك، يمكنك إنهاء العلاقة فورًا.
>
> لا تتضمن هذه الرسالة أي بيانات تدريبية.

## Program request

**Subject**

> طلب لاعب تغيير البرنامج التدريبي

**Body**

> مرحبًا {coach_display_name}،
>
> طلب {player_username} تغيير البرنامج التدريبي. راجع الطلب في قائمة اللاعبين.
>
> لا تتضمن هذه الرسالة أي بيانات تدريبية.

## Account deletion

**Subject**

> تم حذف حساب MYOS الخاص بك بناءً على طلبك

**Body**

> مرحبًا {username}،
>
> تم حذف حساب MYOS الخاص بك بناءً على طلبك. هذا الحذف نهائي.
