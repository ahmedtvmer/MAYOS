# Arabic app UI strings awaiting owner review

This inventory lists Arabic app-owned copy from chunks A, B, and C. It awaits owner review.
English fallbacks supplied by the API remain unchanged. Known structured API
messages have matching Arabic templates in the app catalog and are listed
below, including the server-authored structured-intake copy. Player-entered
goals and limitations, coach-written notes, historical assistant replies, and
saved workout summaries stay in their original language. New assistant replies
follow the existing reply-language rule. Values in braces are runtime values;
numbers use Western digits.

## Shared navigation and player shell

| English | Arabic |
| --- | --- |
| Home | الرئيسية |
| Program | البرنامج التدريبي |
| Progress | التقدم |
| Assistant | المساعد |
| Back | رجوع |
| Retry | إعادة المحاولة |
| Send | إرسال |
| Set up your own training | إعداد تدريبك |
| Player mode needs a short intake before it can build your program. Your coaching stays as it is. | يحتاج وضع اللاعب إلى إجابات قصيرة لإعداد برنامجك التدريبي. ستبقى مهامك التدريبية كما هي. |
| Start intake | بدء الإجابة |
| Back to Coach mode | العودة إلى وضع المدرب |
| Player mode | وضع اللاعب |
| Coach mode | وضع المدرب |
| Switch mode | تبديل الوضع |
| This needs a connection. Nothing was changed. | يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء. |
| Next session | الحصة التالية |
| Next session · {weekday} | الحصة التالية · {weekday} |
| Mon / Tue / Wed / Thu / Fri / Sat / Sun | الاثنين / الثلاثاء / الأربعاء / الخميس / الجمعة / السبت / الأحد |
| Your own training | تدريبك الشخصي |
| Your roster, alerts, and profile | قائمة اللاعبين والتنبيهات والملف الشخصي |
| Account and mode. Current: Coach mode | الحساب والوضع. الوضع الحالي: وضع المدرب |
| Account and mode. Current: Player mode | الحساب والوضع. الوضع الحالي: وضع اللاعب |

## Home

| English | Arabic |
| --- | --- |
| Checkpoint review | مراجعة محطة التقدم |
| Checkpoint | محطة تقدم |
| Open your review | افتح المراجعة |
| No active program | لا يوجد برنامج تدريبي نشط |
| Generate a program to see your next session here. | أنشئ برنامجًا تدريبيًا لعرض حصتك التالية هنا. |
| Go to Program | الانتقال إلى البرنامج التدريبي |
| This week | هذا الأسبوع |
| all logged sessions | كل الحصص المسجلة |
| Personal records | الأرقام القياسية الشخصية |
| Log workout | تسجيل حصة تدريبية |
| Good morning | صباح الخير |
| Good afternoon | طاب يومك |
| Good evening | مساء الخير |
| No sets logged in the last 7 days. | لم تُسجل مجموعات خلال آخر 7 أيام. |
| No personal records yet. | لا توجد أرقام قياسية شخصية بعد. |
| Could not load your home. | تعذر تحميل الصفحة الرئيسية. |
| Offline — showing your saved program. | غير متصل — يعرض البرنامج التدريبي المحفوظ. |
| {count} workout draft(s) waiting to sync | مسودة تدريبية واحدة / مسودتان تدريبيتان / {count} مسودات تدريبية / {count} مسودة تدريبية بانتظار المزامنة |
| No sets recorded for this exercise yet. Log a workout to start a trend. | لا توجد مجموعات مسجلة لهذا التمرين بعد. سجّل حصة تدريبية لبدء متابعة التقدم. |
| {count} weighted sets | 1: مجموعة محسوبة واحدة لكل عضلة; 2: مجموعتان محسوبتان لكل عضلة; 3–10: {count} مجموعات محسوبة لكل عضلة; 11+: {count} مجموعة محسوبة لكل عضلة; fractional values use {count} مجموعة محسوبة لكل عضلة |
| No training history yet | لا يوجد سجل تدريب بعد |
| Log a workout and your strength trend, volume, and per-exercise history will show here. | سجّل حصة تدريبية لعرض تقدم القوة والحجم التدريبي لكل تمرين هنا. |

## Program

| English | Arabic |
| --- | --- |
| Substitute exercise | تبديل التمرين |
| Substitute exercise? | هل تريد تبديل التمرين؟ |
| Cancel | إلغاء |
| Substitute | تبديل |
| Substitution undone. | تم التراجع عن تبديل التمرين. |
| Undo | تراجع |
| Regenerate program | إنشاء البرنامج التدريبي من جديد |
| Also replace on {count} other days | استبدل أيضًا في يوم واحد آخر / يومين آخرين / {count} أيام أخرى / {count} يومًا آخر |
| More actions for {exercise} | المزيد من الخيارات للتمرين {exercise} |
| Every match is already in this day. | كل النتائج موجودة بالفعل في هذا اليوم. |
| No active program yet. Complete onboarding to build one. | لا يوجد برنامج تدريبي نشط بعد. أكمل إعدادك لإنشاء برنامج. |
| Offline — showing saved program | غير متصل — يعرض البرنامج المحفوظ |
| Warm-up | الإحماء |
| Working sets | مجموعات التدريب |
| Cardio | تمارين اللياقة |
| Former coach | المدرب السابق |
| Published by your coach | نشره مدربك |
| Suggested substitutes | التمارين البديلة المقترحة |
| Suggested substitutes: {names} | التمارين البديلة المقترحة: {names} |
| Day {order}: {name} | اليوم {order}: {name} |
| {count} warm-up sets | {Arabic count phrase for warm-up sets} |
| {sets} × {reps} · rest {seconds}s | {sets} × {reps} · راحة {Arabic count phrase for seconds} |
| Deload applied | تم تطبيق تخفيف التدريب |
| Deload suggested | اقتُرح تخفيف التدريب |
| Fatigue signal detected. | ظهرت إشارة إلى الإرهاق. |
| sets scaled to {percent}% of plan | خُفضت المجموعات إلى {percent}% من البرنامج |
| RPE capped at {rpe} | ضُبط الجهد عند RIR {minimum RIR label} |
| Applied: {changes}. | تم التطبيق: {changes}. |
| If applied: {changes}. Your coach has been told. | عند التطبيق: {changes}. أُبلغ مدربك. |
| No set or RPE changes applied. | لم تُطبق تغييرات على المجموعات أو RIR. |
| No set or RPE changes proposed. Your coach has been told. | لم تُقترح تغييرات على المجموعات أو RIR. أُبلغ مدربك. |
| Ask the assistant | اسأل المساعد |
| Your program changed. Refresh before substituting. | تغير برنامجك. حدّث الصفحة قبل تبديل التمرين. |
| Program authority changed again. Try once more. | تغيرت صلاحية تعديل البرنامج مجددًا. حاول مرة أخرى. |
| The program changed. Choose the exercise and replacement again. | تغير البرنامج. اختر التمرين والبديل مرة أخرى. |
| Program authority changed. Continuing with direct substitution. | تغيرت صلاحية تعديل البرنامج. جارٍ تبديل التمرين مباشرة. |
| Program authority changed. Opening a request for your coach. | تغيرت صلاحية تعديل البرنامج. جارٍ إرسال طلب إلى مدربك. |
| Your coach has been asked to replace {oldExercise} with {newExercise}. | طُلب من مدربك تبديل {oldExercise} بـ {newExercise}. |
| {oldExercise} replaced with {newExercise}. | تم تبديل {oldExercise} بـ {newExercise}. |

## Progress

| English | Arabic |
| --- | --- |
| Checkpoints | محطات التقدم |
| No Checkpoints yet. | لا توجد محطات تقدم بعد. |
| Your {ordinal} workout | حصتك التدريبية رقم {count} |
| Could not load this Checkpoint review. | تعذر تحميل مراجعة محطة التقدم. |
| Strength | القوة |
| Volume | الحجم التدريبي |
| Body weight | وزن الجسم |
| Target weight | الوزن المستهدف |
| Target weight · {value} kg | الوزن المستهدف · ⁦{value} kg⁩ |
| Target weight: {value} kg | الوزن المستهدف: ⁦{value} kg⁩ |
| Add today's weight | إضافة وزن اليوم |
| Log today's weight | تسجيل الوزن |
| Log your weight to start tracking changes over time. | سجّل وزنك لبدء متابعة التغيّر عبر الوقت. |
| Weight logged for {date}. | تم تسجيل الوزن بتاريخ ⁦{date}⁩. |
| Weight must be between {min} and {max} kg. | يجب أن يكون الوزن بين ⁦{min} kg⁩ و⁦{max} kg⁩. |
| Estimated 1RM | الحد الأقصى التقديري لتكرار واحد |
| Recent sessions | الحصص الأخيرة |
| View exercise | عرض التمرين |
| Weighted sets | مجموعات محسوبة لكل عضلة |
| Last {count} days · working sets per muscle | آخر يوم واحد / يومين / {count} أيام / {count} يومًا · مجموعات محسوبة لكل عضلة |
| Period | الفترة |
| Rating | التقييم |
| No sets recorded for {exercise} yet. Log a workout to start a trend. | لا توجد مجموعات مسجلة لهذا التمرين بعد. سجّل حصة تدريبية لبدء متابعة التقدم. |
| Only one session logged. A trend needs at least two sessions. | سُجلت حصة واحدة فقط. يلزم تسجيل حصتين على الأقل لمتابعة التقدم. |
| No weighted sets logged in the last {count} days. | لم تُسجل مجموعات محسوبة لكل عضلة خلال آخر {Arabic count phrase for days}. |
| Primary muscle counts 1 per working set, each secondary 0.5. | تُحسب مجموعة التدريب بقيمة 1 للعضلة الأساسية و0.5 لكل عضلة مساعدة. |
| Log a workout and your strength trend, volume, and per-exercise records will appear here. | سجّل حصة تدريبية لعرض تقدم القوة والحجم التدريبي وسجل كل تمرين هنا. |
| {metric} for {exercise}: no sessions. | لا توجد حصص مسجلة لتمرين {exercise} في مقياس {metric}. |
| {metric} for {exercise}: 1 session on {date}, {value} {unit}. | {metric} لتمرين {exercise}: حصة واحدة بتاريخ {date}، {value} {unit}. |
| {metric} for {exercise}, {count} sessions from {first} to {last}, latest {value} {unit}. | {metric} لتمرين {exercise}: {Arabic count phrase for sessions} من {first} إلى {last}، وآخر قيمة {value} {unit}. |
| Session | الحصة |
| {value} kg × {reps} reps | {value} kg × {Arabic count phrase for repetitions} |
| Jan / Feb / Mar / Apr / May / Jun / Jul / Aug / Sep / Oct / Nov / Dec | يناير / فبراير / مارس / أبريل / مايو / يونيو / يوليو / أغسطس / سبتمبر / أكتوبر / نوفمبر / ديسمبر |
| No training history yet | لا يوجد سجل تدريب بعد |

## Exercise detail

| English | Arabic |
| --- | --- |
| Could not load this exercise. | تعذر تحميل التمرين. |
| This exercise is not available. | هذا التمرين غير متاح. |
| You are not signed in. | لم تسجل الدخول. |
| Exercise | التمرين |
| Exercise media unavailable | وسائط التمرين غير متاحة |
| Category | الفئة |
| Body part | جزء الجسم |
| Equipment | المعدات |
| Notes | ملاحظات |
| No details are available for this exercise. | لا تتوفر تفاصيل لهذا التمرين. |
| Instructions aren't available for this exercise yet. | لا تتوفر تعليمات لهذا التمرين حاليًا. |
| No history for this exercise yet. Log a workout to see it here. | لا يوجد سجل لهذا التمرين بعد. سجّل حصة تدريبية لعرضه هنا. |
| Overview | نظرة عامة |
| Technique | الأسلوب |
| History | السجل |
| Sets × reps | المجموعات × التكرارات |
| Intensity | الشدة |
| Rest | الراحة |
| rest {seconds}s | راحة {Arabic count phrase for seconds} |
| reps | تكرارات |

## Assistant chat

| English | Arabic |
| --- | --- |
| Clear | مسح |
| I understand | فهمت |
| Clear chat history | مسح سجل المحادثة |
| Clear chat history? | هل تريد مسح سجل المحادثة؟ |
| This permanently deletes your assistant chat history. | سيؤدي هذا إلى حذف سجل محادثتك مع المساعد نهائيًا. |
| Session debrief | ملخص الحصة |
| Assistant is replying… | المساعد يرد… |
| Message your assistant | أرسل رسالة إلى المساعد |
| Offline | غير متصل |
| Offline — showing saved chat history. Sending needs a connection. | غير متصل — يعرض سجل المحادثة المحفوظ. يتطلب الإرسال اتصالًا بالإنترنت. |
| Chat needs a connection. | يتطلب استخدام المحادثة اتصالًا بالإنترنت. |
| Chat needs a connection. Reconnect and retry. | المحادثة تتطلب اتصالًا. اتصل بالإنترنت ثم أعد المحاولة. |
| The assistant did not finish. Please retry. | لم يكمل المساعد الرد. يُرجى إعادة المحاولة. |
| Clearing history needs a connection. | يتطلب مسح السجل اتصالًا بالإنترنت. |
| Ask your assistant about training, technique, or your program. | اسأل المساعد عن التدريب أو الأسلوب أو برنامجك التدريبي. |
| Accept the disclosure to start chatting. | وافق على الإفصاح لبدء المحادثة. |
| Before you start | قبل أن تبدأ |
| Chat is answered by a hosted AI model. Your message and the training context needed to answer it are sent to that model provider. Free text can contain identifying details, so do not include anything you do not want processed there. | يرد على المحادثة نموذج ذكاء اصطناعي مستضاف. تُرسل رسالتك وسياق التدريب اللازم للإجابة إلى مزود النموذج. قد يتضمن النص الحر تفاصيل تكشف هويتك، لذا لا تكتب ما لا ترغب في معالجته هناك. |
| Accept the disclosure above to enable chat. | وافق على الإفصاح أعلاه لتفعيل المحادثة. |

## Onboarding questions and choices

| English | Arabic |
| --- | --- |
| Which specialization should shape your training? | أي تخصص تريد أن يوجّه تدريبك؟ |
| Which best describes your body proportions? | أي وصف يناسب نسب جسمك؟ |
| How old are you? | كم عمرك؟ |
| How tall are you? | ما طولك؟ |
| What do you weigh? | ما وزنك؟ |
| Do you have a target weight? | هل لديك وزن مستهدف؟ |
| {value} kg | ⁦{value} kg⁩ |
| How long have you been training? | منذ متى وأنت تتدرب؟ |
| What's your main goal right now? | ما هدفك الأساسي الآن؟ |
| Where do you want to be long term? | ما هدفك على المدى الطويل؟ |
| How many days a week can you train? | كم يومًا في الأسبوع يمكنك التدريب؟ |
| What can you train with? | ما المعدات المتاحة لك؟ |
| Anything to work around? | هل هناك إصابة أو أمر يجب مراعاته؟ |
| How's your recovery? | كيف هو تعافيك؟ |
| What rep range do you prefer? | ما نطاق التكرارات الذي تفضله؟ |
| day | يوم |
| days | أيام |
| Legs longer than torso | الساقان أطول من الجذع |
| Torso longer than legs | الجذع أطول من الساقين |
| Commercial gym | صالة رياضية تجارية |
| Home gym | معدات منزلية |
| Bodyweight only | وزن الجسم فقط |
| Balanced | متوازن |
| Male | ذكر |
| Female | أنثى |
| Low | منخفض |
| High | مرتفع |
| Unmapped option with no server description | خيار |
| Specialization | التخصص |
| Proportions | نسب الجسم |
| Age | العمر |
| Height | الطول |
| Weight | الوزن |
| Target weight | الوزن المستهدف |
| Training age | سنوات التدريب |
| Current goal | الهدف الحالي |
| Long-term goal | الهدف طويل المدى |
| Weekly frequency | عدد أيام التدريب أسبوعيًا |
| Equipment | المعدات |
| Injuries or limitations | الإصابات أو القيود |
| Stress and sleep | التوتر والنوم |
| Rep preference | تفضيل التكرارات |
| Question (unknown field fallback) | السؤال |
| Not answered | لم تتم الإجابة |
| years | سنوات |
| {count} days/week | {Arabic count phrase for days} في الأسبوع |
| {minimum} to {maximum} | ⁦{minimum}⁩ إلى ⁦{maximum}⁩ |

## Onboarding flow, review, and validation

| English | Arabic |
| --- | --- |
| Enable coaching | تفعيل التدريب |
| MAYOS coach code | رمز المدرب من MAYOS |
| I'm a coach — enter coach code | أنا مدرب — أدخل رمز المدرب |
| Enter your MAYOS coach code. | أدخل رمز المدرب من MAYOS. |
| Skip for now | تخطي الآن |
| Create my program | إنشاء برنامجي التدريبي |
| About you | عنك |
| Training | التدريب |
| Health & recovery | الصحة والتعافي |
| Progress: {answered} of {total} answered | التقدم: أُجيب عن {answered} من {total} |
| Before we begin | قبل أن نبدأ |
| Review your setup | راجع إعدادك |
| Check your answers. You can edit anything before MAYOS builds your first program. | راجع إجاباتك. يمكنك تعديلها قبل أن ينشئ MAYOS برنامجك التدريبي الأول. |
| Some required answers are still missing. | ما زالت بعض الإجابات المطلوبة ناقصة. |
| Hosted AI processing | معالجة عبر الذكاء الاصطناعي المستضاف |
| Onboarding is powered by a hosted AI provider. The answers you type and the training context needed to respond are sent for processing. Free text you write may contain personal information, so avoid sharing anything you do not want processed. | يعتمد إعداد التدريب على مزود ذكاء اصطناعي مستضاف. تُرسل إجاباتك وسياق التدريب اللازم للرد لمعالجتهما. قد يتضمن النص الحر معلومات شخصية، لذا تجنب مشاركة ما لا ترغب في معالجته. |
| Nothing is sent until you continue. You can change any answer before your program is created. | لن يُرسل شيء حتى تتابع. يمكنك تغيير أي إجابة قبل إنشاء برنامجك. |
| Could not load your setup | تعذر تحميل إعدادك |
| Building your program | جارٍ إنشاء برنامجك التدريبي |
| This can take a moment. Your answers are saved. | قد يستغرق هذا بعض الوقت. حُفظت إجاباتك. |
| Something went wrong. | حدث خطأ ما. |
| A program is already being generated. Give it a moment and retry. | يجري إنشاء برنامج تدريبي بالفعل. انتظر قليلًا ثم أعد المحاولة. |
| Enter a number between {minimum} and {maximum}. | أدخل رقمًا بين {minimum} و{maximum}. |
| Choose an option to continue. | اختر خيارًا للمتابعة. |
| Write at least 2 characters. | اكتب حرفين على الأقل. |
| Review | مراجعة |
| Saved from your earlier setup | حُفظت من إعدادك السابق |
| Continue | متابعة |
| Type your answer | اكتب إجابتك |
| None | لا شيء |
| {title}. {caption} Selected / Not selected | {title}. {caption} محدد / غير محدد |
| Decrease | تقليل |
| Increase | زيادة |
| Use the stepper | استخدم أزرار الزيادة والنقصان |
| Type a value | أدخل قيمة |
| Choose your weekly training days | اختر أيام التدريب الأسبوعية |
| {count} days per week | {Arabic count phrase for days} في الأسبوع |
| Tap an example to start | اضغط على مثال للبدء |

## Shared count forms

These count forms are produced by the shared Arabic count helper and appear in
frequency, rest, warm-up, training-set, training-session, session, and
counted-set labels.

| Count | Day | Group | Training set | Warm-up set | Training session | Session | Year | Second | Repetition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 أيام | 0 مجموعات | 0 مجموعات تدريب | 0 مجموعات إحماء | 0 حصص تدريبية | 0 حصص | 0 سنوات | 0 ثوانٍ | 0 تكرارات |
| 1 | يوم واحد | مجموعة واحدة | مجموعة تدريب واحدة | مجموعة إحماء واحدة | حصة تدريبية واحدة | حصة واحدة | سنة واحدة | ثانية واحدة | تكرار واحد |
| 2 | يومان | مجموعتان | مجموعتا تدريب | مجموعتا إحماء | حصتان تدريبيتان | حصتان | سنتان | ثانيتان | تكراران |
| 3–10 | {count} أيام | {count} مجموعات | {count} مجموعات تدريب | {count} مجموعات إحماء | {count} حصص تدريبية | {count} حصص | {count} سنوات | {count} ثوانٍ | {count} تكرارات |
| 11+ | {count} يومًا | {count} مجموعة | {count} مجموعة تدريب | {count} مجموعة إحماء | {count} حصة تدريبية | {count} حصة | {count} سنة | {count} ثانية | {count} تكرارًا |

Non-integer year values use “{count} سنة”. A fractional counted-set value
uses “{count} مجموعة محسوبة لكل عضلة”.

In oblique contexts the dual changes to يومين / مجموعتين / مجموعتي إحماء /
حصتين تدريبيتين / حصتين / سنتين / ثانيتين / تكرارين (for example, “last two
days” and “rest for two seconds”).

## Chunk B: workout logger, player profile, assignment and settings

### Workout logger, keypad, rest timer and summary

| English | Arabic |
| --- | --- |
| Log workout | تسجيل حصة تدريبية |
| Log workout · {time} | تسجيل حصة تدريبية · {time} |
| Discard workout | حذف الحصة |
| Finish workout | إنهاء الحصة |
| {done}/{total} sets | {done}/{total} مجموعات |
| SET | مجموعة |
| REPS | تكرارات |
| Warm-up | الإحماء |
| Warm-up (warm-up movement tag) | حركة إحماء |
| Unplanned | غير مخطط |
| Cardio | تمارين اللياقة |
| Minutes | دقائق |
| Rest time… | مدة الراحة… |
| + Add set | + أضف مجموعة |
| Add exercise | إضافة تمرين |
| Add unplanned exercise | إضافة تمرين غير مخطط |
| Replace exercise | استبدال تمرين لهذه الحصة |
| Remove exercise | إزالة التمرين |
| Remove | إزالة |
| Undo replace | تراجع عن الاستبدال |
| Exercise menu | خيارات التمرين |
| View exercise details | عرض تفاصيل التمرين |
| View {name} details | عرض تفاصيل التمرين: {name} |
| Picture unavailable | تعذر عرض الصورة |
| No picture | لا توجد صورة |
| Mark set done | تحديد المجموعة كمكتملة |
| Mark set not done | إلغاء تحديد المجموعة |
| Mark Cardio done | تحديد اللياقة كمكتملة |
| Mark Cardio not done | إلغاء تحديد اللياقة |
| Weight (kg) | الوزن (⁦kg⁩) |
| Reps | التكرارات |
| Reps in reserve | التكرارات المتبقية |
| {exercise} · set {setNumber} · {field} | {exercise} · مجموعة {setNumber} · {field} |
| Unrated | بلا تقييم |
| Hide | إخفاء |
| Backspace | حذف آخر رقم |
| Next | التالي |
| Off | إيقاف |
| Rest · {exercise} | راحة · {exercise} |
| Skip | تخطي |
| Exercise picture | صورة التمرين |
| Replace exercise? | استبدال التمرين؟ |
| The sets you've logged on this exercise will be cleared. | ستُحذف المجموعات التي سجلتها لهذا التمرين. |
| The sets you've logged on this exercise will be discarded. | ستُحذف المجموعات التي سجلتها لهذا التمرين. |
| Reason for your coach | السبب لمدربك |
| Add a reason to continue. | أضف سببًا للمتابعة. |
| Ask my coach to make this permanent | اطلب من مدربك تبديل التمرين في البرنامج |
| Keep this swap in my program | تبديل التمرين في البرنامج |
| Send request | إرسال الطلب |
| Sending… | جارٍ الإرسال… |
| Cancel | إلغاء |
| Keep logging | متابعة التسجيل |
| Replace | استبدال |
| Ask my coach to make this permanent | طلب تبديل تمرين من المدرب |
| Keep this swap in my program | تبديل تمرين في البرنامج |
| Discard this workout? | حذف هذه الحصة؟ |
| The sets you've logged in this workout will be lost. | ستفقد المجموعات التي سجلتها في هذه الحصة. |
| Its sets will be removed from this browser. | ستُحذف مجموعات هذه الحصة من هذا المتصفح. |
| Resume | استئناف |
| Discard | حذف |
| Unfinished workout | حصة غير مكتملة |
| Finish your current workout | أنهِ حصتك الحالية |
| This device is already logging a workout. Resume it, or discard it to start a new one. | هناك حصة قيد التسجيل على هذا الجهاز. استأنفها أو احذفها لبدء حصة جديدة. |
| Resume where you left off, or discard this workout. | استأنف من حيث توقفت أو احذف هذه الحصة. |
| started | بدأت |
| {day} · started {startedAt} | {day} · بدأت {startedAt} |
| Logging workouts on web | تسجيل الحصص على الويب |
| You need a connection to finish saving. An unfinished workout is kept only in this browser. | تحتاج إلى اتصال بالإنترنت لإكمال الحفظ. تُحفظ الحصة غير المكتملة في هذا المتصفح فقط. |
| Continue logging | متابعة التسجيل |
| Only ticked sets are saved to the workout. | تُحفظ المجموعات المحددة فقط في الحصة. |
| Discard unticked sets and finish | حذف غير المحدد وإنهاء الحصة |
| Workout saved to your drafts. | حُفظت الحصة في المسودات. |
| Workout saved to your training history. | حُفظت الحصة في سجل تدريبك. |
| Workout summary | ملخص الحصة |
| Back to workout | العودة إلى الحصة |
| Save workout | حفظ الحصة |
| Done | تم |
| Performed date | تاريخ الحصة |
| Readiness | الاستعداد |
| Readiness: {value}/5 | الاستعداد: {value}/5 |
| Notes (pumps, joint aches, fatigue) | ملاحظات (الضخامة، ألم المفاصل، الإرهاق) |
| Personal records | الأرقام القياسية الشخصية |
| Your review will appear on your dashboard | ستظهر مراجعتك هنا. |
| Exercises done | التمارين المكتملة |
| Ticked working sets | مجموعات التدريب المحددة |
| Total volume | إجمالي الوزن المرفوع |
| Duration | المدة |
| min | دقيقة |
| Weight | الوزن |
| Log at least one set | سجّل مجموعة واحدة على الأقل |
| You are not signed in. | لم تسجل الدخول. |
| This training day is not available offline. | يوم التدريب هذا غير متاح دون اتصال. |
| This workout started on {started}, outside the allowed entry window, so its performed date was set to {corrected}. | بدأت هذه الحصة في {started}، خارج فترة إدخال التاريخ المسموحة، لذلك ضُبط تاريخها إلى {corrected}. |
| {exercisesDone}/{exercisesTotal} exercises · {setsDone}/{setsTotal} sets | {exercisesDone}/{exercisesTotal} تمارين · {setsDone}/{setsTotal} مجموعات |
| Your device timezone could not be determined, so the workout date cannot be recorded truthfully. Check your device time-zone settings and try again. | تعذر تحديد المنطقة الزمنية لجهازك، لذلك لا يمكن تسجيل تاريخ الحصة. تحقق من إعداد المنطقة الزمنية وحاول مجددًا. |
| Your program is unavailable. Reconnect to refresh it before logging this workout. | البرنامج التدريبي غير متاح. اتصل بالإنترنت لتحديثه قبل تسجيل هذه الحصة. |
| Your program is unavailable offline. Connect once to refresh it before saving this workout. | البرنامج التدريبي غير متاح دون اتصال. اتصل مرة واحدة لتحديثه قبل حفظ هذه الحصة. |
| Refresh your program before saving this workout. | حدّث برنامجك التدريبي قبل حفظ هذه الحصة. |
| Reopen this workout and try saving again. | افتح هذه الحصة من جديد وحاول حفظها. |
| The workout could not be saved. Nothing was lost — try again. | تعذر حفظ الحصة. لم يُفقد شيء؛ حاول مجددًا. |
| Couldn't reach MAYOS. Your workout is kept in this browser. | تعذر الاتصال بـ MAYOS. حُفظت حصتك في هذا المتصفح. |
| MAYOS is busy. Your workout is kept in this browser. | MAYOS مشغول الآن. حُفظت حصتك في هذا المتصفح. |
| Your program changed since this workout started; substitute it from the Program tab | تغير البرنامج التدريبي منذ بدء هذه الحصة. بدّل التمرين من تبويب البرنامج. |
| The swap was saved to your program. | حُفظ الاستبدال في برنامجك التدريبي. |
| Add a reason before asking your coach. | أضف سببًا قبل طلب التبديل من مدربك. |
| Your coach was asked to make this swap permanent. | أرسلت إلى مدربك طلب تبديل التمرين في البرنامج. |
| The program changed. Substitute this exercise from the Program tab. | تغير البرنامج التدريبي. بدّل هذا التمرين من تبويب البرنامج. |
| Your workout swap is saved. Your coach now controls this program. Add a reason to send the request. | حُفظ استبدال التمرين في حصتك، لكن مدربك أصبح يتحكم في البرنامج. أضف سببًا لإرسال الطلب. |
| is no longer in this program day. | لم يعد هذا التمرين ضمن يوم البرنامج التدريبي. |
| The workout swap is saved, but the program was not changed. {detail} | حُفظ استبدال التمرين لهذه الحصة، ولم يتغير البرنامج التدريبي. {detail} |
| The active program could not be loaded. | تعذر تحميل البرنامج التدريبي النشط. |
| {name} is no longer in this program day. | لم يعد {name} ضمن يوم البرنامج التدريبي. |
| Retry | إعادة المحاولة |
| Offline: showing your cached program. | غير متصل: يعرض البرنامج التدريبي المحفوظ. |
| No drafts yet. | لا توجد مسودات بعد. |
| {pending} pending · {synced} synced | {pending} بانتظار المزامنة · {synced} تمت مزامنتها |
| Sync now | مزامنة الآن |
| Workouts you log offline appear here until they sync. | تظهر هنا الحصص التي تسجلها دون اتصال حتى تتم مزامنتها. |
| {count} working sets | {Arabic count phrase for training sets} |
| Edit date | تعديل التاريخ |
| Correct date | تصحيح التاريخ |
| Discard draft | حذف المسودة |
| Date corrected. | تم تصحيح التاريخ. |
| Logged against program v{captured} (current v{current}) | سُجلت الحصة على البرنامج التدريبي v{captured} (الحالي v{current}) |
| The service returned an unexpected status ({status}). | أعادت الخدمة حالة غير متوقعة ({status}). |
| That workout is no longer available. | لم تعد هذه الحصة متاحة. |
| Only a synced workout can be corrected. | لا يمكن تصحيح إلا الحصص المتزامنة. |
| This workout was logged against an older program version. | سُجلت هذه الحصة على إصدار أقدم من البرنامج. |
| Cannot reach the service. Check your connection. | تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت. |
| The service is unavailable. Please retry. | الخدمة غير متاحة. حاول مجددًا. |
| Request failed ({status}). | فشل الطلب ({status}). |
| Offline workout drafts are available in the Android app. | مسودات الحصص دون اتصال متاحة في تطبيق Android. |
| Last: {values} | السابق: {values} |
| {minimum}–{maximum} reps | {minimum}–{maximum} تكرارات |
| Rest {time} | راحة {time} |
| Replace and discard {count} logged set(s)? | استبدال التمرين وحذف {Arabic count phrase for groups} المسجلة؟ |
| Remove and discard {count} logged set(s)? | إزالة التمرين وحذف {Arabic count phrase for groups} المسجلة؟ |
| Undo replace and discard {count} logged set(s)? | التراجع عن الاستبدال وحذف {Arabic count phrase for groups} المسجلة؟ |
| {count} set(s) isn’t/aren’t ticked | لم تُحدد {Arabic count phrase for groups}. |
| PR kg | رقم قياسي · kg |
| PR e1RM | رقم قياسي · e1RM |
| {exercise} · PR {value} kg / PR e1RM {value} kg | {exercise} · رقم قياسي {value} kg / رقم قياسي e1RM {value} kg |
| Your {ordinal} workout! | حصة تدريبية رقم {number}! |
| Weekly streak: {count} week(s) | أسابيع الالتزام المتتالية: {count} |
| This week: {done} of {total} done | هذا الأسبوع: {done} من {total} مكتملة |
| {count} workout(s) to your {ordinal} | {Arabic count phrase for training sessions} للوصول إلى محطة التقدم رقم {ordinal} |
| {count} set(s) | 1: مجموعة واحدة; 2: مجموعتان; 3–10: {count} مجموعات; 11+: {count} مجموعة |
| {count} working sets | {Arabic count phrase for training sets} |
| Workout draft status: pending / syncing / synced / needs attention / other | بانتظار المزامنة / تمت المزامنة / تحتاج إلى مراجعة / مسودة تدريبية |
| {exercise} prescription includes its target RIR | {exercise} · RIR {minimum RIR label} |
| Deload applied | تم تطبيق تخفيف التدريب |
| Deload suggested | اقتُرح تخفيف التدريب |
| Fatigue signal detected. | ظهرت إشارة إلى الإرهاق. |
| sets scaled to {targetVolume}% of plan | خُفضت المجموعات إلى {targetVolume}% من البرنامج |
| RPE capped at {cap} | ضُبط الجهد عند RIR {minimum RIR label} |
| No set or RPE changes applied. | لم تُطبق تغييرات على المجموعات أو RIR. |
| No set or RPE changes proposed. Your coach has been told. | لم تُقترح تغييرات على المجموعات أو RIR. أُبلغ مدربك. |
| Applied: {changes}. | تم التطبيق: {التغييرات}. |
| If applied: {changes}. Your coach has been told. | عند التطبيق: {التغييرات}. أُبلغ مدربك. |

Arabic prescription lines keep the paragraph right-to-left and wrap Western
numeric ranges, weights, RIR, and rest times in LRI/PDI isolates.

### Player profile and training profile

| English | Arabic |
| --- | --- |
| Sign-in methods | طرق تسجيل الدخول |
| Training profile | الملف التدريبي |
| Could not confirm the recovery email. Please retry. | تعذر تأكيد البريد الإلكتروني للاسترداد. حاول مجددًا. |
| Update the profile facts used to personalize your training. | حدّث معلومات الملف التي تساعد على تخصيص تدريبك. |
| Current goal | الهدف الحالي |
| Injuries or limitations | الإصابات أو القيود |
| Weight (kg) | الوزن (⁦kg⁩) |
| Log weight | تسجيل الوزن |
| Weight logged for {date}. | تم تسجيل الوزن بتاريخ ⁦{date}⁩. |
| Target weight (kg, optional) | الوزن المستهدف (⁦kg⁩، اختياري) |
| Training days per week | أيام التدريب في الأسبوع |
| Rep preference | تفضيل التكرارات |
| Equipment access | المعدات المتاحة |
| Save profile | حفظ الملف |
| Training schedule | جدول التدريب |
| Expected weekdays and timezone, separate from your program. | أيام التدريب المتوقعة والمنطقة الزمنية، بشكل منفصل عن برنامجك. |
| Timezone | المنطقة الزمنية |
| Save schedule | حفظ الجدول |
| Training pause | إيقاف التدريب مؤقتًا |
| Start: {date} | البداية: {date} |
| End: {date} | النهاية: {date} |
| Schedule pause | جدولة التوقف |
| No scheduled pauses. | لا توجد فترات توقف مجدولة. |
| Pause: {start} → {end} | توقف: {start} → {end} |
| Danger zone | منطقة الخطر |
| Deleting your account permanently removes it and its active data, including unsynced drafts on this device. It cannot be undone. | حذف الحساب يزيله نهائيًا ويمسح بياناته، بما فيها المسودات غير المتزامنة على هذا الجهاز. لا يمكن التراجع عن ذلك. |
| Delete account | حذف الحساب |
| Confirm program rebuild | تأكيد إعادة إنشاء البرنامج |
| This rebuilds your program | سيُعاد إنشاء برنامجك التدريبي. |
| Continue | متابعة |
| Program rebuilt. | أُعيد إنشاء البرنامج التدريبي. |
| Profile saved. | حُفظ الملف. |
| Training schedule saved. | حُفظ جدول التدريب. |
| Pause scheduled. | تمت جدولة التوقف. |
| Pause scheduled; your coach was notified. | تمت جدولة التوقف وإبلاغ مدربك. |
| Check your profile details and try again. | تحقق من معلومات ملفك وحاول مجددًا. |
| Weight must be between {min} and {max} kg. | يجب أن يكون الوزن بين ⁦{min} kg⁩ و⁦{max} kg⁩. |
| Choose an allowed {field}. | اختر قيمة مسموحًا بها لـ{field}. |
| Check your {field} and try again. | تحقق من {field} وحاول مجددًا. |
| Enter an IANA timezone, e.g. Europe/London or UTC. | أدخل منطقة زمنية بصيغة IANA، مثل Europe/London أو UTC. |
| A pause must start today or later. | يجب أن يبدأ التوقف اليوم أو بعده. |
| A pause must end on or after it starts. | يجب أن ينتهي التوقف في يوم بدايته أو بعده. |
| A pause can last at most {days} days. | يمكن أن يستمر التوقف {days} يومًا كحد أقصى. |
| Delete account? | حذف الحساب؟ |
| This permanently deletes your account and its active data: training history, program, coaching assignment, recovery email, and any unsynced drafts on this device. This cannot be undone. | سيؤدي ذلك إلى حذف حسابك وبياناته النشطة نهائيًا: سجل التدريب، والبرنامج التدريبي، وعلاقة التدريب، والبريد الإلكتروني للاسترداد، وأي مسودات غير متزامنة على هذا الجهاز. لا يمكن التراجع عن ذلك. |
| There is no password on this account, so confirm by signing in with Google: you will be asked to prove the Google account connected to this MAYOS account. | لا توجد كلمة مرور لهذا الحساب، لذا أكّد الحذف بتسجيل الدخول إلى Google. سيُطلب منك إثبات ملكية حساب Google المرتبط بحساب MAYOS هذا. |
| Password | كلمة المرور |
| Cancel | إلغاء |
| Current password | كلمة المرور الحالية |
| New password | كلمة المرور الجديدة |
| Confirm new password | تأكيد كلمة المرور الجديدة |
| Enter your current password. | أدخل كلمة المرور الحالية. |
| Use at least {minimum} characters. | استخدم {minimum} أحرف على الأقل. |
| Passwords do not match. | كلمتا المرور غير متطابقتين. |
| Set a password | تعيين كلمة مرور |
| Choose a password so you can sign in without Google. Once it is set you can disconnect Google. | اختر كلمة مرور لتسجيل الدخول دون Google. بعد تعيينها يمكنك فصل Google. |
| Set password | تعيين كلمة المرور |
| Password set. You can now disconnect Google. | تم تعيين كلمة المرور. يمكنك الآن فصل Google. |
| Change password | تغيير كلمة المرور |
| Changing your password signs you out of every device. | سيؤدي تغيير كلمة المرور إلى تسجيل خروجك من كل الأجهزة. |
| Disconnect Google? | فصل Google؟ |
| You will no longer be able to sign in with Google. Your password stays as the other way to sign in. | لن تتمكن بعد ذلك من تسجيل الدخول إلى Google. ستبقى كلمة المرور طريقة أخرى لتسجيل الدخول. |
| Disconnect | فصل |
| Google account connected. | تم ربط حساب Google. |
| Google disconnected. | تم فصل Google. |
| Use the Google sign-in button to continue. | استخدم زر تسجيل الدخول عبر Google للمتابعة. |
| Google sign-in is not set up on this build. | تسجيل الدخول عبر Google غير مهيأ في هذا الإصدار. |
| Google sign-in is not configured for this build. | تسجيل الدخول عبر Google غير مهيأ في هذا الإصدار. |
| Google sign-in is unavailable on this device. | تسجيل الدخول عبر Google غير متاح على هذا الجهاز. |
| Google sign-in failed. Please try again. | فشل تسجيل الدخول عبر Google. حاول مجددًا. |
| Google did not return a sign-in token. Please try again. | لم يُعِد Google رمز تسجيل الدخول. حاول مجددًا. |
| Could not reach Google. Check your connection and try again. | تعذر الاتصال بـ Google. تحقق من اتصالك وحاول مجددًا. |
| Google sign-in was cancelled. Your account was not deleted. | أُلغي تسجيل الدخول عبر Google. لم يُحذف حسابك. |
| Password set | تم تعيين كلمة المرور |
| No password yet | لم تُعيّن كلمة مرور بعد |
| Connected | متصل |
| Not connected | غير متصل |
| Set a password first | عيّن كلمة مرور أولًا |
| Disconnect Google | فصل Google |
| Connect Google | الاتصال بـ Google |
| Retry | إعادة المحاولة |
| The service needs an update before this profile can be edited. Please try again later. | تحتاج الخدمة إلى تحديث قبل تعديل هذا الملف. حاول مجددًا لاحقًا. |
| None | لا شيء |
| This needs a connection. Nothing was changed. | يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء. |
| Cannot reach the service. Check your connection. | تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت. |
| The service returned invalid profile data. | أعادت الخدمة بيانات الملف الشخصي بصيغة غير صالحة. |
| The service returned invalid training schedule data. | أعادت الخدمة بيانات جدول التدريب بصيغة غير صالحة. |
| The service is unavailable. Please retry. | الخدمة غير متاحة. حاول مجددًا. |
| The service rejected this request. | رفضت الخدمة هذا الطلب. |
| Request failed ({status}). | فشل الطلب ({status}). |
| Balanced | متوازن |
| Low | منخفض |
| High | مرتفع |
| Mon / Tue / Wed / Thu / Fri / Sat / Sun | الاثنين / الثلاثاء / الأربعاء / الخميس / الجمعة / السبت / الأحد |
| Goal / Injuries or limitations / Weight / Weekly frequency / Equipment / Rep preference | الهدف الحالي / الإصابات أو القيود / الوزن / عدد أيام التدريب أسبوعيًا / المعدات / تفضيل التكرارات |
| Commercial gym | صالة رياضية تجارية |
| Home gym | معدات منزلية |
| Bodyweight only | وزن الجسم فقط |

### Player coach assignment and program requests

| English | Arabic |
| --- | --- |
| Assignment accepted. | تم قبول علاقة التدريب. |
| End assignment? | إنهاء علاقة التدريب؟ |
| Your coach will immediately lose access to your training history. | سيفقد مدربك فورًا إمكانية الاطلاع على سجل تدريبك. |
| End assignment | إنهاء علاقة التدريب |
| Assignment ended. | انتهت علاقة التدريب. |
| Program requests | طلبات البرنامج التدريبي |
| Request a change | طلب تغيير |
| No program requests yet. | لا توجد طلبات للبرنامج التدريبي بعد. |
| Cancel request | إلغاء الطلب |
| Reason:  | السبب:  |
| Coach:  | المدرب:  |
| Pending | قيد الانتظار |
| Applied | تم التطبيق |
| Declined | مرفوض |
| Cancelled | ملغى |
| Notices | الإشعارات |
| Mark all read | تحديد الكل كمقروء |
| Check-ins | سجلات التواصل |
| Former coach | المدرب السابق |
| Coach {username} | المدرب {username} |
| assignment ended | انتهت علاقة التدريب |
| Your coach | مدربك |
| Coaching assignment active | علاقة التدريب نشطة |
| While this assignment is active, your coach can view your current and historical training data. Ending it revokes that access immediately. | أثناء نشاط علاقة التدريب، يمكن لمدربك الاطلاع على بيانات تدريبك الحالية والسابقة. يؤدي إنهاؤها إلى إلغاء إمكانية الاطلاع فورًا. |
| Coach assignment | علاقة التدريب مع المدرب |
| Enter the invite code from your coach. Your coach can only see your training data after you accept, and access ends when either of you ends the assignment. | أدخل رمز الدعوة من مدربك. لن يتمكن مدربك من الاطلاع على بيانات تدريبك إلا بعد موافقتك، وينتهي ذلك عند إنهاء أحدكما علاقة التدريب. |
| Invite code from your coach | رمز الدعوة من مدربك |
| Preview access | معاينة إمكانية الاطلاع |
| Your coach will be {name} | سيكون مدربك {name} |
| Accept assignment | قبول علاقة التدريب |
| Enter the invite code from your coach. | أدخل رمز الدعوة من مدربك. |
| Request type | نوع الطلب |
| In app | داخل التطبيق |
| In person | حضوري |
| Phone | هاتف |
| Video | مرئي |
| Message | رسالة |
| Email | بريد إلكتروني |
| Other | أخرى |
| This needs a connection. Nothing was changed. | يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء. |
| Cannot reach the service. Check your connection. | تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت. |
| The service returned invalid check-in data. | أعادت الخدمة بيانات سجلات التواصل بصيغة غير صالحة. |
| The service returned invalid assignment notices. | أعادت الخدمة بيانات الإشعارات بصيغة غير صالحة. |
| The service returned invalid program request data. | أعادت الخدمة بيانات طلبات البرنامج التدريبي بصيغة غير صالحة. |
| The service is unavailable. Please retry. | الخدمة غير متاحة. حاول مجددًا. |
| The service rejected this request. | رفضت الخدمة هذا الطلب. |
| Request failed ({status}). | فشل الطلب ({status}). |
| Request a program change | طلب تغيير البرنامج التدريبي |
| Exercise substitution | طلب تبديل تمرين من المدرب |
| Split change | تغيير تقسيمة البرنامج |
| Day | اليوم |
| Exercise | التمرين |
| Replacement | البديل |
| Day name | اسم اليوم |
| Current exercise id | معرّف التمرين الحالي |
| Replacement exercise id | معرّف التمرين البديل |
| Days per week | أيام في الأسبوع |
| Split preference (optional) | تفضيل التقسيمة (اختياري) |
| Reason | السبب |
| A reason is required. | السبب مطلوب. |
| Pick the day, the exercise, and its replacement. | اختر اليوم والتمرين والبديل. |
| Submit request | إرسال الطلب |
| Cancel | إلغاء |
| Substitute {exercise} on {day} with {replacement} | طلب تبديل تمرين من المدرب: {exercise} في {day} إلى {replacement} |
| Change to {frequency} days/week ({preference}) | تغيير تقسيمة البرنامج إلى {Arabic count phrase for days} في الأسبوع ({preference}) |

### Settings, personalization, credits and logout

| English | Arabic |
| --- | --- |
| Appearance | المظهر |
| Choose how MAYOS looks. System follows your device. | اختر مظهر MAYOS. يتبع خيار النظام إعداد جهازك. |
| System | النظام |
| Light | فاتح |
| Dark | داكن |
| Personalization | التخصيص |
| Assistant style | أسلوب المساعد |
| Account | الحساب |
| Profile | الملف الشخصي |
| Training preferences, schedule, and account | تفضيلات التدريب والجدول والحساب |
| Plan | الخطة |
| Lifter and Coach plan states | حالة خطتي اللاعب والمدرب |
| Coaching | التدريب مع مدرب |
| Coaching assignment | علاقة التدريب |
| Your coach and check-ins | مدربك وسجلات التواصل |
| Enable coaching | تفعيل وضع المدرب |
| Redeem an owner-issued coach code | أدخل رمز المدرب الصادر من المالك |
| Training | التدريب |
| Assistant | المساعد |
| Chat about your training | تحدث عن تدريبك |
| Workouts | الحصص التدريبية |
| Workout drafts | مسودات الحصص |
| Saved on this device, syncing when online | محفوظة على هذا الجهاز وتتم مزامنتها عند الاتصال |
| About | حول التطبيق |
| Privacy policy | سياسة الخصوصية |
| What MAYOS collects, who can see it, and deletion | ما يجمعه MAYOS، ومن يمكنه الاطلاع عليه، وكيفية الحذف |
| Credits | الاعتمادات |
| Log out | تسجيل الخروج |
| Choose how your assistant words its chat replies. Facts, training decisions, safety, and reply language stay the same. | اختر طريقة صياغة ردود المساعد في المحادثة. تبقى الحقائق وقرارات التدريب والسلامة ولغة الرد كما هي. |
| Assistant style | أسلوب آخر |
| Style description | وصف الأسلوب |
| Direct & pragmatic | مباشر وعملي |
| Clear and practical. | واضح وعملي. |
| Encouraging | مشجع |
| Recognizes effort. | يقدّر الجهد. |
| Scientific | علمي |
| Evidence and reasoning. | يعتمد على الأدلة والتعليل. |
| Tough-love | حازم باحترام |
| Firm, respectful. | حازم ومحترم. |
| Concise | موجز |
| Brief, focused replies. | ردود قصيرة ومركزة. |
| Assistant style saved. | حُفظ أسلوب المساعد. |
| Could not load Assistant style. | تعذر تحميل أسلوب المساعد. |
| Assistant style (unknown preset fallback) | أسلوب آخر |
| Style description (unknown preset fallback) | وصف الأسلوب |
| Retry | إعادة المحاولة |
| Save style | حفظ الأسلوب |
| Optional instructions | تعليمات اختيارية |
| For example: explain terms briefly. | مثلًا: اشرح المصطلحات باختصار. |
| Used for wording only. | تُستخدم لصياغة الردود فقط. |
| Could not open gymvisual.com. | تعذر فتح gymvisual.com. |
| Close | إغلاق |
| This needs a connection. Nothing was changed. | يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء. |
| Cannot reach the service. Check your connection. | تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت. |
| The service returned invalid profile data. | أعادت الخدمة بيانات الملف الشخصي بصيغة غير صالحة. |
| The service is unavailable. Please retry. | الخدمة غير متاحة. حاول مجددًا. |
| The service rejected this request. | رفضت الخدمة هذا الطلب. |
| Request failed ({status}). | فشل الطلب ({status}). |
| Unsynced workouts | حصص غير متزامنة |
| Discard drafts and log out | حذف المسودات وتسجيل الخروج |
| Keep drafts and log out | الاحتفاظ بالمسودات وتسجيل الخروج |
| Discard unfinished workout? | حذف الحصة غير المكتملة؟ |
| Logging out will discard this workout from this browser. | سيؤدي تسجيل الخروج إلى حذف هذه الحصة من هذا المتصفح. |
| Discard and log out | حذف وتسجيل الخروج |
| Cancel | إلغاء |
| Exercise media (the catalog pictures and GIFs) is credited as required by its terms:<br><br>{required credit}<br><br>The media is shown at its native size, never larger than 180 × 180, with this credit, while MAYOS's own licence from Gym visual is pending. | تُنسب صور التمارين ومقاطع GIF في المكتبة وفق شروط استخدامها:<br><br>{required credit}<br><br>تُعرض الوسائط بحجمها الأصلي وبحد أقصى 180 × 180 مع هذا الاعتماد، بينما لا يزال ترخيص MAYOS الخاص من Gym visual قيد الانتظار. |
| You have {count} unsynced workout draft(s). They stay on this device until they sync; logging out will not delete them. | لديك {Arabic count phrase for workout drafts} غير متزامنة. ستبقى على هذا الجهاز حتى تتم مزامنتها؛ تسجيل الخروج لن يحذفها. |

### Shared app-authored failure messages

| English | Arabic |
| --- | --- |
| The service returned invalid account status. | أعادت الخدمة بيانات بصيغة غير صالحة. |
| The service returned invalid program data. | أعادت الخدمة بيانات بصيغة غير صالحة. |
| The service returned invalid baseline data. | أعادت الخدمة بيانات بصيغة غير صالحة. |
| The service returned invalid exercise data. | أعادت الخدمة بيانات بصيغة غير صالحة. |
| The service returned invalid session data. | أعادت الخدمة بيانات بصيغة غير صالحة. |
| The service returned invalid training status data. | أعادت الخدمة بيانات بصيغة غير صالحة. |

## Coach mode shell, roster, and alerts (Chunk C)

| English | Arabic |
| --- | --- |
| Roster | قائمة اللاعبين |
| Alerts | التنبيهات |
| Requests | الطلبات |
| Profile | الملف الشخصي |
| Active assignments | علاقات التدريب النشطة |
| No assigned players yet. | لا يوجد لاعبون معينون بعد. |
| Revoke assignment? | إنهاء علاقة التدريب؟ |
| {player} will lose coaching immediately and can no longer be seen by you. | سيفقد {player} إمكانية التدريب معك فورًا ولن تتمكن من الاطلاع على بياناته. |
| Revoke | إنهاء العلاقة |
| Revoked {player}. | انتهت علاقة التدريب مع {player}. |
| Disable coaching? | إيقاف وضع المدرب؟ |
| Every assignment ends immediately and your coach capability is removed. Your own player training data is kept. | ستنتهي كل علاقات التدريب فورًا وسيُزال دور المدرب. ستبقى بيانات تدريبك كلاعب محفوظة. |
| Disable coaching | إيقاف وضع المدرب |
| Coaching disabled. {count} assignment(s) ended. | تم إيقاف وضع المدرب. انتهت {count} علاقة تدريب. |
| Acknowledge | تأكيد الاطلاع |
| Resolve | حل التنبيه |
| Show resolved | عرض التنبيهات المحلولة |
| No alerts to show. | لا توجد تنبيهات. |
| No active assignment. | لا توجد علاقة تدريب نشطة. |
| Resolved by {username} | حلّه {username} |
| New / Acknowledged / Resolved | جديد / تم تأكيد الاطلاع / تم الحل |
| Missed {count}d | 1: يوم واحد فائت; 2: يومان فائتان; 3–10: {count} أيام فائتة; 11+: {count} يومًا فائتًا |
| Stalled {count} sessions | توقف التقدم: {count} حصص تدريبية |
| {count} alert(s) | 1: تنبيه واحد; 2: تنبيهان; 3–10: {count} تنبيهات; 11+: {count} تنبيهًا |
| {count} request(s) | 1: طلب واحد; 2: طلبان; 3–10: {count} طلبات; 11+: {count} طلبًا |
| Follow-up today / Follow-up overdue | المتابعة اليوم / المتابعة متأخرة |
| No workouts yet | لم يسجل حصصًا بعد |
| Last workout {date} · {program} | آخر حصة تدريبية {date} · {program} |
| Revoking… | جارٍ إنهاء العلاقة… |
| Missed {count} expected training day(s) ({start} to {end}) | فات اللاعب {Arabic count phrase for days} من أيام التدريب المتوقعة ({start} إلى {end}) |
| Follow-up due since {date} | حان موعد المتابعة منذ {date} |
| Stalling — {count} sessions without a personal record (since {date}) | توقف التقدم: {Arabic count phrase for training sessions} دون رقم قياسي شخصي (منذ {date}) |
| Deload recommended — rolling readiness crash, average {average}/5 across the last 3 workouts | يوصى بتخفيف التدريب بسبب انخفاض الاستعداد في آخر 3 حصص تدريبية (المتوسط {average}/5) |
| Deload recommended — acute readiness floor, 1/5 logged | يوصى بتخفيف التدريب بعد تسجيل الاستعداد بدرجة 1/5 |
| Deload recommended — high exertion density with declining readiness | يوصى بتخفيف التدريب بسبب ارتفاع نسبة مجموعات التدريب عند RIR 0.5 أو أقل مع انخفاض الاستعداد |
| Player chose to apply deload for the next workout only | اختار اللاعب تطبيق تخفيف التدريب في الحصة التدريبية التالية فقط |
| Player chose to undo deload for the next workout only | اختار اللاعب التراجع عن تخفيف التدريب للحصة التدريبية التالية فقط |
| Performance regression — {exercise}: e1RM {delta} kg ({status}) | تراجع الأداء — {exercise}: e1RM {delta} kg ({status}) |
| Training profile changed: injuries or limitations, equipment access | تغير الملف التدريبي: الإصابات أو القيود، المعدات المتاحة |
| Weight moved away from the target by {change} kg over {windowDays} days (alert threshold {threshold} kg; target {target} kg). | ابتعد الوزن عن الهدف بمقدار ⁦{change} kg⁩ خلال آخر ⁦{windowDays}⁩ يومًا (حد التنبيه ⁦{threshold} kg⁩؛ الهدف ⁦{target} kg⁩). |
| Dated weight points: {points}. Target weight: {target}. | نقاط الوزن المؤرخة: {points}. الوزن المستهدف: ⁦{target} kg⁩. |
| Injuries or limitations: {before} → {after} | الإصابات أو القيود: {before} → {after} |
| Equipment access: {before} → {after} | المعدات المتاحة: {before} → {after} |
| Not set (profile change value) | غير محدد |
| Message unavailable. | تعذر عرض الرسالة. |
| Unknown status | حالة غير معروفة |
| Resolved by coach / system | حلّه المدرب / حلّه النظام |

## Coach assistant and check-ins (Chunk C)

| English | Arabic |
| --- | --- |
| Assistant | المساعد |
| Ask assistant | اسأل المساعد |
| Open alerts | التنبيهات المفتوحة |
| Ask about {player}'s training figures: volume, sessions, records, and schedule. | اسأل عن أرقام تدريب {player}: مجموعات التدريب، والحصص، والأرقام القياسية، والجدول. |
| Thinking… | جارٍ التفكير… |
| Answers use the player's training figures. Nothing is saved. | تستخدم الإجابات أرقام تدريب {player}. لا يُحفظ شيء. |
| Ask about this player | اسأل عن هذا اللاعب |
| You no longer coach this player | لم تعد مدربًا لهذا اللاعب. |
| Log check-in | تسجيل تواصل |
| Log check-in with {player} | تسجيل تواصل مع {player} |
| Dated today · {date} | تاريخ اليوم · {date} |
| Next follow-up: {date} | المتابعة القادمة: {date} |
| Note (optional) | ملاحظة (اختيارية) |
| Save check-in | حفظ التواصل |
| Pick a contact channel. | اختر وسيلة التواصل. |
| Check-in recorded. | تم تسجيل التواصل. |
| Next follow-up | المتابعة القادمة |
| not scheduled | غير محدد |
| No check-ins recorded yet. | لم يُسجل أي تواصل بعد. |
| In app / In person / Phone / Video / Message / Email / Other | داخل التطبيق / لقاء شخصي / مكالمة هاتفية / مكالمة فيديو / رسالة / بريد إلكتروني / أخرى |
| Become a coach | كن مدربًا |
| Enter your MAYOS coach code | أدخل رمز مدرب MAYOS |
| This code comes from MAYOS and enables Coach mode on your own account. It is single-use and expires. Entering it does not assign you to a coach. | هذا الرمز من MAYOS ويفعّل وضع المدرب في حسابك. يُستخدم مرة واحدة وتنتهي صلاحيته. إدخاله لا ينشئ علاقة تدريب مع مدرب. |
| Coach capability enabled. | تم تفعيل دور المدرب. |

## Coach profile, invitations, and program tools (Chunk C)

| English | Arabic |
| --- | --- |
| Coach profile | الملف الشخصي للمدرب |
| These details describe you as a coach. | هذه المعلومات تعرّف اللاعبين بك بصفتك مدربًا. |
| Display name | الاسم المعروض |
| Specialization | التخصص |
| e.g. Powerlifting, Hypertrophy | مثلًا: رفع الأثقال، بناء العضلات |
| Bio | نبذة |
| Roster capacity | سعة قائمة اللاعبين |
| Between {min} and {max} players. | من {min} إلى {max} لاعبًا. |
| Save profile | حفظ الملف الشخصي |
| Coach profile saved. | تم حفظ ملف المدرب. |
| Enter a display name. | أدخل اسمًا معروضًا. |
| Display name must be at most {max} characters. | يجب ألا يتجاوز الاسم {max} حرفًا. |
| Enter a whole number. | أدخل عددًا صحيحًا. |
| Capacity must be between {min} and {max}. | يجب أن تكون السعة بين {min} و{max}. |
| Invite a player | دعوة لاعب |
| Create a single-use code and give it to one player. It expires and can only be redeemed while you have roster room; the exact expiry is shown when the code is issued. | أنشئ رمزًا لمرة واحدة وقدّمه للاعب واحد. تنتهي صلاحيته، ولا يمكن استخدامه إلا عند توفر مكان في قائمة اللاعبين. سيظهر تاريخ الانتهاء بعد إنشاء الرمز. |
| Create player invite | إنشاء دعوة للاعب |
| Expires {date} | تنتهي الصلاحية {date} |
| {remaining} of {capacity} roster slots free | المتاح في قائمة اللاعبين: {remaining} من {capacity} |
| Notices | الإشعارات |
| Mark all read | تحديد الكل كمقروء |
| Resolved alerts | التنبيهات المحلولة |
| Publish program | نشر برنامج تدريبي |
| Split override (optional) | تقسيمة مخصصة (اختيارية) |
| Rep preference | تفضيل التكرارات |
| Low / Balanced / High | منخفض / متوازن / مرتفع |
| Days per week | أيام التدريب أسبوعيًا |
| Publish | نشر |
| Published program version {version} | نُشر إصدار البرنامج التدريبي {version} |

## Coach player history, requests, and metrics (Chunk C)

| English | Arabic |
| --- | --- |
| Program requests | طلبات البرنامج التدريبي |
| No program requests yet. | لا توجد طلبات للبرنامج التدريبي بعد. |
| No volume recorded yet. | لم تُسجل مجموعات تدريب بعد. |
| Volume (weighted working sets) | مجموعات محسوبة لكل عضلة |
| Training schedule | جدول التدريب |
| Expected | أيام التدريب المتوقعة |
| Timezone: {value} | المنطقة الزمنية: {value} |
| Pause: {start} → {end} | توقف التدريب: {start} → {end} |
| Latest session | أحدث حصة تدريبية |
| Recent sessions | الحصص الأخيرة |
| No sessions logged yet. | لم تُسجل حصص بعد. |
| {sets} sets · {volume} kg | {sets} مجموعة تدريب · إجمالي الوزن المرفوع {volume} kg |
| Warm-up: {count} movements | حركات الإحماء: {count} حركات إحماء |
| Cardio: {minutes} min | تمارين اللياقة: {minutes} دقائق |
| Cardio: no duration set | تمارين اللياقة: غير محددة |
| Readiness {score}/5 | الاستعداد {score}/5 |
| Skipped / Unplanned | تم تخطيه / غير مخطط |
| No personal records yet. | لا توجد أرقام قياسية شخصية بعد. |
| Checkpoints | محطات التقدم |
| No Checkpoints yet. | لا توجد محطات تقدم بعد. |
| Checkpoint {number} | محطة التقدم {number} |
| Mon / Tue / Wed / Thu / Fri / Sat / Sun | الاثنين / الثلاثاء / الأربعاء / الخميس / الجمعة / السبت / الأحد |
| Exercises | التمارين |
| No exercises logged yet. | لم تُسجل تمارين بعد. |
| No recorded sets for this exercise. | لم تُسجل مجموعات لهذا التمرين. |
| Records | الأرقام القياسية |
| No check-ins recorded yet. | لم يُسجل أي تواصل بعد. |
| History | السجل |
| Check-ins | التواصل |
| Requests ({count}) | الطلبات ({count}) |
| Pending | قيد الانتظار |
| No pending requests. | لا توجد طلبات قيد الانتظار. |
| Answered | تم الرد |
| Nothing answered yet. | لا توجد طلبات تم الرد عليها. |
| This request is no longer available. | لم يعد هذا الطلب متاحًا. |
| Select a request to review. | اختر طلبًا لمراجعته. |
| Request detail | تفاصيل الطلب |
| This request has been answered. | تم الرد على هذا الطلب. |
| Apply swap | تطبيق التبديل |
| Apply (rebuilds program) | تطبيق وإعادة إنشاء البرنامج |
| Reason for declining (shown to the player) | سبب الرفض (سيظهر للاعب) |
| Sent only with Decline · up to 500 characters. | يُرسل عند الرفض فقط · حتى 500 حرف. |
| Decline | رفض |
| {player} asks | يطلب {player} |
| Whole program | البرنامج كاملًا |
| program v{version} | إصدار البرنامج {version} |
| Program request applied. | تم تطبيق طلب البرنامج التدريبي. |
| Program request declined. | تم رفض طلب البرنامج التدريبي. |
| Player / You / tap to review | لاعب / أنت / اضغط للمراجعة |
| Sent {date} · tap to review | أُرسل {date} · اضغط للمراجعة |
| {exercise} → {replacement} (on {day}) | تبديل تمرين {exercise} في {day} إلى {replacement} |
| Split change → {frequency} days/week · {preference} | تغيير تقسيمة البرنامج إلى {frequency} أيام أسبوعيًا · {preference} |
| Split change | تغيير تقسيمة البرنامج |
| You: {response} | ردك: {response} |
| Pending / Applied / Declined / Cancelled | قيد الانتظار / تم التطبيق / مرفوض / ملغى |
| No training history yet. | لا يوجد سجل تدريب بعد. |
| Since {date} | منذ {date} |
| Expected: {value} | أيام التدريب المتوقعة: {value} |
| {split} · {date} | {split} · {date} |
| {sets} sets · {volume} kg | {sets} مجموعة تدريب · إجمالي الوزن المرفوع {volume} kg |
| Warm-up: {count} movements | حركات الإحماء: {count} حركات إحماء |
| Personal records | الأرقام القياسية الشخصية |
| {exercise}: {sets} sets · {volume} kg | {exercise}: {sets} مجموعات تدريب · إجمالي الوزن المرفوع {volume} kg |
| Logged against program v{captured} (current v{current}) | سُجلت الحصة على إصدار البرنامج {captured} (الحالي {current}) |
| Date corrected from {previous} to {corrected} | تم تصحيح التاريخ من {previous} إلى {corrected} |

## Shared screens and utilities (Chunk C final sweep)

| English | Arabic |
| --- | --- |
| You're offline | أنت غير متصل بالإنترنت |
| Could not open this link in your browser. | تعذر فتح هذا الرابط في المتصفح. |
| Could not open the privacy policy in your browser. | تعذر فتح سياسة الخصوصية في المتصفح. |
| Image omitted | صورة محذوفة |
| Page not found | الصفحة غير موجودة |
| The page you are looking for does not exist or has moved. | الصفحة التي تبحث عنها غير موجودة أو نُقلت. |
| Go to home | الانتقال إلى الرئيسية |
| Progress, Engineered. | تقدّمٌ مدروس. |
| Search the exercise catalog | ابحث في مكتبة التمارين |
| Search | بحث |
| Type an exercise name to search. | أدخل اسم تمرين للبحث. |
| No matching exercise found. | لم يُعثر على تمرين مطابق. |
| No {muscle} exercise matched. | لم يُعثر على تمرين لعضلة {muscle}. |
| Every match is already in this workout. | كل النتائج موجودة بالفعل في هذه الحصة. |
| Muscle: {muscle} | العضلة: {muscle} |
| Clear the muscle filter | مسح مرشح العضلة |
| No plan is available for this account. | لا تتوفر خطة لهذا الحساب. |
| Lifter and Coach plans are independent. | خطتا اللاعب والمدرب مستقلتان. |
| Lifter / Coach | اللاعب / المدرب |
| Ongoing plan — not a trial. | خطة مستمرة — ليست فترة تجريبية. |
| What's included | ما الذي تتضمنه |
| Automatic training program | برنامج تدريبي تلقائي |
| Weekly volume and personal-record dashboard | لوحة الحجم التدريبي والأرقام القياسية الأسبوعية |
| Coaching assignment with your coach | علاقة تدريب مع مدربك |
| Coach profile and player invites | الملف الشخصي للمدرب ودعوات اللاعبين |
| Active roster with assignment status | قائمة اللاعبين النشطة وحالة علاقات التدريب |
| End or revoke assignments at any time | إنهاء علاقات التدريب في أي وقت |
| Could not reset the password. Request a new link. | تعذر إعادة تعيين كلمة المرور. اطلب رابطًا جديدًا. |

## Rest notifications (Chunk C)

| English | Arabic |
| --- | --- |
| MAYOS · Rest {time} | MAYOS · راحة {time} |
| Next: {exercise} · set {set} · last {last} | التالي: {exercise} · المجموعة {set} · السابق {last} |
| Rest complete | انتهت الراحة |
| Rest timer | مؤقت الراحة |
| The running rest countdown while a workout is in progress. | مؤقت الراحة الجاري أثناء الحصة التدريبية. |
| The end-of-rest vibration and sound. | الصوت والاهتزاز عند انتهاء الراحة. |
| Back to {exercise} | العودة إلى {exercise} |
| Rest alerts need permission to reach you when your screen is off. | تحتاج تنبيهات الراحة إلى إذن لتصلك عند إطفاء الشاشة. |

## Player chat character counter

| English | Arabic |
| --- | --- |
| 0 characters left | المتبقي: 0 أحرف |
| 80 characters left | المتبقي: 80 حرفًا |
| 1 character left | المتبقي: حرف واحد |
| 2 characters left | المتبقي: حرفان |
| 3 characters left | المتبقي: 3 أحرف |
| 11 characters left | المتبقي: 11 حرفًا |

## New Arabic count forms used by Chunk C

The count helper keeps Western digits and selects a short form by count.

| English noun | 1 | 2 | 3–10 | 11+ |
| --- | --- | --- | --- | --- |
| assignments | علاقة تدريب واحدة | علاقتا تدريب | {count} علاقات تدريب | {count} علاقة تدريب |
| alerts | تنبيه واحد | تنبيهان | {count} تنبيهات | {count} تنبيهًا |
| requests | طلب واحد | طلبان | {count} طلبات | {count} طلبًا |
| warm-up movements | حركة إحماء واحدة | حركتا إحماء | {count} حركات إحماء | {count} حركة إحماء |
| minutes | دقيقة واحدة | دقيقتان | {count} دقائق | {count} دقيقة |

## HTTP and assistant stream errors

| English | Arabic |
| --- | --- |
| The request could not be completed. | تعذر تنفيذ الطلب. راجع البيانات وحاول مجددًا. |
| The request was not authorized. | تعذر التحقق من تسجيل الدخول. سجّل الدخول مجددًا. |
| You do not have permission to do that. | لا تملك صلاحية تنفيذ هذا الإجراء. |
| Not found. | لم يُعثر على المطلوب. |
| The request conflicts with the current state. | تعذر إتمام الطلب بسبب تعارض مع الحالة الحالية. |
| The request contains invalid fields. | راجع البيانات المدخلة وحاول مرة أخرى. |
| The field must be no longer than {limit} characters. | يجب ألا يتجاوز هذا الحقل {limit} حرفًا. |
| Too many requests. Please try again later. | وصل الطلب إلى الحد المسموح. حاول مرة أخرى لاحقًا. |
| Too many AI requests. Please wait a minute and try again. | أرسلت طلبات كثيرة إلى المساعد. انتظر دقيقة ثم أعد المحاولة. |
| You have reached your daily AI usage limit. Please try again tomorrow. | وصلت إلى حد استخدام المساعد اليوم. أعد المحاولة غدًا. |
| The service is unavailable. Please retry. | تعذر إكمال الطلب. حاول مجددًا. |
| The request failed. Please try again. | تعذر تنفيذ الطلب. حاول مجددًا. |
| The assistant is temporarily unavailable. | تعذر على المساعد إكمال الرد. يُرجى إعادة المحاولة. |
| This Google account is already linked to a MAYOS account. | حساب Google هذا مرتبط بالفعل بحساب MAYOS. |
| This workout was logged against an older program version. | سُجلت هذه الحصة على إصدار أقدم من البرنامج. |

## Google sign-in button

| English | Arabic |
| --- | --- |
| Continue with Google | المتابعة مع Google |

## Structured HTTP errors

| Message code | English fallback | Arabic |
| --- | --- | --- |
| google.invalid_token.v1 | Invalid Google credentials. | تعذر التحقق من بيانات Google. |
| google.linked_elsewhere.v1 | This Google account is already connected to another MAYOS account | حساب Google هذا مرتبط بالفعل بحساب MAYOS آخر. |
| google.different_account.v1 | This account already has a different Google account connected. Disconnect it first. | يوجد حساب Google مختلف مرتبط بهذا الحساب. افصله أولًا. |
| google.unlink_password_required.v1 | Set a password before disconnecting Google, so you can still sign in. | عيّن كلمة مرور قبل فصل Google لتتمكن من تسجيل الدخول. |
| recovery.invalid_or_expired_code.v1 | Invalid or expired verification code. | رمز التحقق غير صالح أو انتهت صلاحيته. |
| recovery.code_send_limit.v1 | Invalid or expired verification code. | تعذر إرسال رمز التحقق الآن. حاول مجددًا لاحقًا. |
| recovery.invalid_or_expired_token.v1 | Invalid or expired reset code. | رابط إعادة تعيين كلمة المرور غير صالح أو انتهت صلاحيته. |
| coach_invite.invalid_code.v1 | This coach invite code isn't valid for this username | رمز دعوة تفعيل دور المدرب غير صالح أو انتهت صلاحيته. |

## Source-specific HTTP errors

| Message code | Arabic copy |
| --- | --- |
| auth.invalid_credentials.v1 | بيانات تسجيل الدخول غير صحيحة. |
| auth.username_taken.v1 | اسم المستخدم مستخدم بالفعل. |
| auth.invalid_or_expired_token.v1 | انتهت صلاحية تسجيل الدخول أو لم يعد صالحًا. |
| auth.invalid_signup_ticket.v1 | انتهت صلاحية التسجيل عبر Google أو لم يعد صالحًا. |
| auth.signup_ticket_missing.v1 | تعذر العثور على تذكرة التسجيل. |
| assignment.none_active.v1 | لا توجد علاقة تدريب نشطة. |
| assignment.invite_invalid.v1 | رمز الدعوة للتدريب مع مدرب غير صالح أو انتهت صلاحيته. |
| assignment.self_assignment.v1 | لا يمكنك تعيين نفسك مدربًا لك. |
| assignment.already_assigned.v1 | لديك علاقة تدريب نشطة بالفعل. |
| assignment.consent_required.v1 | اقبل علاقة التدريب صراحةً للمتابعة. |
| assignment.roster_full.v1 | قائمة اللاعبين لدى المدرب ممتلئة. اطلب دعوة جديدة لاحقًا. |
| assignment.coach_roster_full.v1 | قائمة اللاعبين ممتلئة. أنهِ علاقة تدريب قبل إصدار دعوة أخرى. |
| assignment.coach_capability_required.v1 | تتطلب هذه العملية صلاحية المدرب. |
| assignment.coach_profile_required.v1 | أكمل إعداد ملف المدرب قبل إصدار الدعوات. |
| assignment.invite_lifetime_invalid.v1 | يجب أن تكون مدة الدعوة بالدقائق أكبر من صفر. |
| assignment.not_participant.v1 | لا تملك صلاحية إدارة علاقة التدريب هذه. |
| assignment.already_ended.v1 | انتهت علاقة التدريب هذه بالفعل. |
| assignment.program_draft_exists.v1 | توجد مسودة برنامج تدريبي مفتوحة لعلاقة التدريب هذه بالفعل. |
| assignment.program_draft_changed.v1 | تغيرت مسودة البرنامج أثناء إنشائها. أعد المحاولة. |
| assignment.program_draft_invalid.v1 | راجع تفاصيل البرنامج التدريبي وحاول مجددًا. |
| assignment.check_in_invalid.v1 | تعذر تسجيل التواصل. راجع البيانات وحاول مجددًا. |
| assignment.not_found.v1 | لم يُعثر على الإسناد. |
| assignment.program_draft_not_found.v1 | لم يُعثر على مسودة البرنامج التدريبي. |
| assignment.notice_not_found.v1 | لم يُعثر على الإشعار. |
| assignment.request_invalid.v1 | تعذر تنفيذ طلب علاقة التدريب. راجع البيانات وحاول مجددًا. |
| program.no_active.v1 | لا يوجد برنامج تدريبي نشط. |
| program.coach_controls.v1 | يتحكم مدربك في برنامجك التدريبي. اطلب منه إجراء التغييرات. |
| program.substitution.day_not_found.v1 | هذا اليوم غير موجود في برنامجك التدريبي الحالي. |
| program.substitution.source_not_on_day.v1 | هذا التمرين غير موجود في ذلك اليوم من برنامجك الحالي. |
| program.substitution.replacement_is_source.v1 | اختر تمرينًا بديلًا مختلفًا. |
| program.substitution.replacement_not_found.v1 | لم يُعثر على التمرين البديل. |
| program.substitution.replacement_already_on_day.v1 | التمرين البديل موجود بالفعل في اليوم المستهدف. |
| program.substitution.restore_version_not_found.v1 | لم يُعثر على إصدار البرنامج المطلوب استعادته. |
| program.substitution.changed.v1 | تغير البرنامج منذ هذا الاستبدال. حدّث البرنامج ثم أعد المحاولة. |
| program_request.invalid_kind.v1 | اختر استبدال تمرين أو تغيير تقسيم التدريب. |
| program_request.reason_required.v1 | أضف سببًا للطلب. |
| program_request.reason_too_long.v1 | يجب ألا يتجاوز سبب الطلب {limit} حرفًا. |
| program_request.direct_change.v1 | يتحكم مدربك في برنامجك التدريبي. أرسل طلب تغيير إليه. |
| program_request.no_active_program.v1 | لا يوجد برنامج تدريبي نشط لتغييره. |
| program_request.target_incomplete.v1 | اختر اليوم والتمرين والتمرين البديل. |
| program_request.same_replacement.v1 | اختر تمرينًا بديلًا مختلفًا. |
| program_request.day_not_in_program.v1 | هذا اليوم غير موجود في برنامجك التدريبي الحالي. |
| program_request.exercise_not_in_day.v1 | هذا التمرين غير موجود في ذلك اليوم من برنامجك الحالي. |
| program_request.replacement_not_found.v1 | لم يُعثر على التمرين البديل. |
| program_request.frequency_invalid.v1 | يجب أن يتراوح عدد أيام التدريب أسبوعيًا بين 1 و5. |
| program_request.split_too_long.v1 | يجب ألا يتجاوز تفضيل تقسيم التدريب {limit} حرفًا. |
| program_request.not_found.v1 | لم يُعثر على الطلب. |
| program_request.not_pending.v1 | لم يعد هذا الطلب قيد الانتظار. |
| program_request.stale.v1 | تغير البرنامج منذ إنشاء هذا الطلب. اطلب من اللاعب تحديثه. |
| program_request.response_required.v1 | أضف ردًا على الطلب. |
| program_request.response_too_long.v1 | يجب ألا يتجاوز الرد {limit} حرفًا. |
| program_request.selection_invalid.v1 | تعذر اعتماد بعض طلبات تغيير البرنامج المحددة. |
| intake.structured_active.v1 | يوجد تسجيل منظم جارٍ بالفعل. أكمله قبل بدء تسجيل آخر. |
| intake.in_progress.v1 | يجري إنشاء البرنامج التدريبي لهذا التسجيل. انتظر ثم حاول مجددًا. |
| intake.gender.explanation.v1 | اختيار التخصص مطلوب. وهو يحدد تقسيمة التدريب الافتراضية التي سنبنيها لك: تركز التقسيمات المخصصة للاعبات على عضلات الألوية والجزء السفلي من الجسم، أما التقسيمات المخصصة للاعبين فتتبع تقسيمتنا المتوازنة المعتادة. ويحدد عدد أيام تدريبك أسبوعيًا شكل التقسيمة بالتفصيل. |
| intake.gender.option.male.v1 | تدريب متوازن للجزء العلوي والسفلي بحسب عدد الأيام: Full Body عند 1-3 أيام، وUpper/Lower عند 4 أيام، وArnold-style عند 5 أيام. |
| intake.gender.option.female.v1 | تُخصص التقسيمات بحسب عدد الأيام: Glute-specialised Full Body عند 1-3 أيام، وLower-body (glute bias) وUpper body + core عند 4-5 أيام. |
| intake.proportions.explanation.v1 | نسبة طول الساقين إلى الجذع معلومات تساعد على توجيه التدريب فقط. ولا تغيّر اختيار التمارين أو بنية البرنامج التدريبي أو حجم التدريب. |
| intake.proportions.option.long_legs.v1 | الساقان أطول من الجذع |
| intake.proportions.option.balanced.v1 | تناسب متوازن بين الجزء العلوي والسفلي |
| intake.proportions.option.long_torso.v1 | الجذع أطول من الساقين |
| intake.current_goal.hint.v1 | ما الذي تتمرن من أجله الآن؟ |
| intake.current_goal.example.1.v1 | بناء عضلات الألوية والساقين |
| intake.current_goal.example.2.v1 | زيادة القوة |
| intake.current_goal.example.3.v1 | خسارة الدهون |
| intake.long_term_goal.hint.v1 | ما الذي تريد تحقيقه على المدى الطويل؟ |
| intake.long_term_goal.example.1.v1 | زيادة القوة والكتلة العضلية |
| intake.long_term_goal.example.2.v1 | الحفاظ على الصحة وتجنب الألم |
| intake.equipment_access.option.commercial_gym.v1 | صالة رياضية تجارية مجهزة بالكامل. |
| intake.equipment_access.option.home_gym.v1 | معدات تحتفظ بها في المنزل، مثل الأوزان أو الأجهزة. |
| intake.equipment_access.option.bodyweight_only.v1 | لا تتوفر معدات رياضية؛ تتدرب باستخدام وزن جسمك فقط. |
| intake.injuries_or_limitations.hint.v1 | اذكر أي إصابات أو قيود. إجابة «لا شيء» مقبولة. |
| intake.injuries_or_limitations.example.1.v1 | لا شيء |
| intake.injuries_or_limitations.example.2.v1 | ألم في الركبة اليسرى عند أداء القرفصاء العميقة |
| intake.stress_and_sleep.hint.v1 | كيف هو مستوى التوتر والنوم لديك؟ |
| intake.stress_and_sleep.example.1.v1 | توتر متوسط، ونوم 7 ساعات |
| intake.stress_and_sleep.example.2.v1 | توتر منخفض، ونوم 8 ساعات |
| intake.rep_preference.option.low.v1 | أهداف تكرارات أقل: التمارين المركبة 5-8، وتمارين العزل 8-12. |
| intake.rep_preference.option.balanced.v1 | أهداف التكرارات الافتراضية: التمارين المركبة 6-10، وتمارين العزل 10-15. |
| intake.rep_preference.option.high.v1 | أهداف تكرارات أعلى: التمارين المركبة 8-12، وتمارين العزل 12-20. |
| intake.program_generation_unavailable.v1 | يتحكم مدربك المعيّن في برنامجك التدريبي. اطلب من مدربك إجراء التغييرات. |
| coach.ai_unavailable.v1 | مساعد المدرب غير متاح حاليًا. |
| media.unavailable.v1 | تعذر تحميل الوسائط حاليًا. حاول مجددًا. |
| media.not_found.v1 | لم يُعثر على الوسائط المطلوبة. |
