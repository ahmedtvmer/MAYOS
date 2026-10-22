# Arabic judge calibration sample (#199) — owner reviewed by Thomas on 2026-10-13

Player model: `deepseek-ai/DeepSeek-V4-Flash`. Judges: `Qwen/Qwen3.5-27B` (judge 1), `zai-org/GLM-5.3` (judge 2). Sample hash `5b8283b37574…` (bound in `tests/eval/datasets/arabic_judge_review/REVIEW.json`).

For each reply, check: **is the judges' label right?** `egyptian` = everyday Egyptian Arabic (ADR 066); `standard` = simple standard Arabic. The Egyptian-register score is only counted once you confirm the judges label these correctly.

## 1. `ar-sore-01` — expected **egyptian**; judge 1: **egyptian**, judge 2: **egyptian**

**Player:** عضلات رجلي تعبانة بعد تمرين امبارح، أتمرن النهارده؟

**Reply:**

> أهلاً. لو الإرهاق مجرد وجع عضلي طبيعي (DOMS) فده متوقع ومش مانع للتمرين. لكن لو فيه أي ألم غير معتاد في المفاصل أو شعير زي الخدران أو الشرخ، بلاش تتمرن وخليك تروح لطبيب.
> 
> لو الوجع عضلي بحت، ابدأ النهاردة بتمارين رجل خفيفة، ركز على الحركة الكاملة وشد العضلة تحت الحمل، وخلي الـ RIR عالي (3-4). لو الإحساس وحش بعد الإحماء، قلل الأحمال أو سيب الرجل لليوم اللي بعده.

- Judge 1: The reply uses distinct Egyptian Arabic words and grammar such as 'لو' (if), 'ده' (this), 'بلاش' (don't), 'خليك' (make sure you), 'النهاردة' (today), and 'وحش' (bad), which are characteristic of the Egyptian dialect.
- Judge 2: Egyptian wording throughout: فده, بلاش تتمرن, خليك تروح, النهاردة, اللي بعده, سيب الرجل, لو, وحش.

## 2. `ar-sore-02` — expected **egyptian**; judge 1: **standard**, judge 2: **mixed**

**Player:** أشعر بإرهاق عام ونمت قليلًا، هل أخفف التمرين؟

**Reply:**

> الإرهاق العام وقلة النوم يؤثران على التعافي والجهاز العصبي. الأفضل اليوم تخفيف الحمل: استبعد الـ top sets عند RIR 0، واكتفي بـ 1-2 سيتات عمل لكل تمرين بـ RIR 2-3. حافظ على نطاق الحركة الكامل والتحكم، لكن لا تضغط على الفشل. إذا شعرت بتحسن خلال التمرين، زد الحمل تدريجيًا، لكن لا تجبر نفسك. الراحة اليوم استثمار في الأسبوع الجاي.

- Judge 1: The reply uses Modern Standard Arabic vocabulary and grammar such as 'الإرهاق', 'يؤثران', 'الأفضل', 'استبعد', 'واكتفي', and 'استثمار', without any Egyptian colloquial markers.
- Judge 2: The reply is mostly MSA (يؤثران، استبعد، حافظ، زد الحمل تدريجيًا) but ends with the Egyptian word الجاي ("الأسبوع الجاي"), making it mixed.

## 3. `ar-sore-03` — expected **egyptian**; judge 1: **egyptian**, judge 2: **egyptian**

**Player:** عندي pump قوي في دراعي بعد الـ curls، ده طبيعي؟

**Reply:**

> أيوه طبيعي تماماً. الـ pump ده تجمع دم في العضلة نتيجة الشغل، وخصوصاً في تمرين العزل زي الـ curls. طالما مفيش ألم غريب أو وجع في المفصل أو إحساس بتمزق، يبقى كويس وده دليل إن العضلة اشتغلت كويس.

- Judge 1: The reply uses distinct Egyptian Arabic words and grammar such as 'أيوه', 'ده', 'مفيش', 'زي', and 'كويس'.
- Judge 2: Egyptian wording throughout: أيوه, ده, زي, مفيش, يبقى كويس, اشتغلت كويس.

## 4. `ar-prog-01` — expected **egyptian**; judge 1: **mixed**, judge 2: **mixed**

**Player:** بدّل الـ bench press بـ dumbbell bench press

**Reply:**

> تم التبديل. Dumbbell bench press هو بديل ممتاز—يسمح بمدى حركة أوسع وتحميل أطول، خصوصاً في وضعية stretch. حافظ على نفس عدد السيتات والعدّات اللي كنت بتعملها مع الـ barbell، وابدأ بوزن يخليك حوالي 2-3 RIR.

- Judge 1: The reply mixes Standard Arabic words like 'تم' and 'يسمح' with Egyptian Arabic dialect words like 'اللي', 'كنت', and 'بتعملها'.
- Judge 2: The reply mixes MSA phrases like "تم التبديل" and "يسمح بمدى حركة أوسع" with Egyptian ones like "اللي كنت بتعملها" and "يخليك", so it is mixed.

## 5. `ar-prog-02` — expected **egyptian**; judge 1: **mixed**, judge 2: **standard**

**Player:** بدّل السكوات بـ leg press

**Reply:**

> تمام، تم استبدال السكوات بـ leg press في البرنامج.
> 
> حافظ على نفس نطاق الـ RIR (0-3) وتركيزك على الـ lengthened loading. زود فترة الراحة بين السيتات لدقيقتين على الأقل.
> 
> لو حسيت بأي ألم غير طبيعي في الركبة أو الورك، وقف التمرين فوراً.

- Judge 1: The reply mixes Egyptian Arabic words like 'تمام' and 'لو' with Standard Arabic grammar and vocabulary such as 'تم استبدال', 'حافظ', and 'فترة الراحة'.
- Judge 2: The reply uses MSA wording like تم استبدال, حافظ على, زود فترة الراحة, وقف التمرين فوراً, with no Egyptian markers like عايز or كده.

## 6. `ar-inj-01` — expected **standard**; judge 1: **standard**, judge 2: **standard**

**Player:** حسيت بألم حاد في كتفي وأنا بعمل bench press

**Reply:**

> ⚠️ **تم إيقاف الحركة وتفعيل إجراء السلامة السريرية**
> 
> قد تشير الأحاسيس الحادة أو المفاجئة، مثل الفرقعة أو الألم الممتد مع تنميل، إلى إصابة محتملة في الأنسجة الرخوة أو المفصل. **MYOS سجل تدريب آلي ومحرك لميكانيكا الحركة، وليس طبيبًا.**
> 
> - **أوقف فورًا تدريب الحركة المتأثرة.**
> - لا تحاول مواصلة التدريب مع الألم الحاد أو الممتد.
> - اطلب تقييمًا تشخيصيًا من طبيب مختص في الطب الرياضي أو أخصائي علاج طبيعي مرخّص.

- Judge 1: The reply uses formal Modern Standard Arabic vocabulary and grammar such as 'تفعيل', 'إجراء', 'تشخيصي', 'مرخّص', and the formal structure 'قد تشير... إلى', without any Egyptian colloquial markers.
- Judge 2: The reply uses MSA wording like "قد تشير", "أوقف فورًا", "اطلب تقييمًا تشخيصيًا", "ينبغي"-style formal phrasing, with no Egyptian markers like عايز or إزاي.

## 7. `ar-inj-02` — expected **standard**; judge 1: **standard**, judge 2: **standard**

**Player:** سمعت فرقعة في ركبتي وأنا بنزل في السكوات وبعدها ورمت

**Reply:**

> ⚠️ **تم إيقاف الحركة وتفعيل إجراء السلامة السريرية**
> 
> قد تشير الأحاسيس الحادة أو المفاجئة، مثل الفرقعة أو الألم الممتد مع تنميل، إلى إصابة محتملة في الأنسجة الرخوة أو المفصل. **MYOS سجل تدريب آلي ومحرك لميكانيكا الحركة، وليس طبيبًا.**
> 
> - **أوقف فورًا تدريب الحركة المتأثرة.**
> - لا تحاول مواصلة التدريب مع الألم الحاد أو الممتد.
> - اطلب تقييمًا تشخيصيًا من طبيب مختص في الطب الرياضي أو أخصائي علاج طبيعي مرخّص.

- Judge 1: The reply uses formal Modern Standard Arabic vocabulary and grammar such as 'تفعيل', 'إجراء', 'تشخيصي', 'مرخّص', and the formal structure 'قد تشير', without any Egyptian colloquial markers.
- Judge 2: The reply uses MSA wording like "قد تشير", "أوقف فورًا", "اطلب تقييمًا تشخيصيًا", and "لا تحاول مواصلة" with no Egyptian markers such as عايز or كده.

## 8. `ar-inj-03` — expected **standard**; judge 1: **standard**, judge 2: **standard**

**Player:** عندي تنميل ووخز في صوابعي بعد تمرين الظهر

**Reply:**

> ⚠️ **تم إيقاف الحركة وتفعيل إجراء السلامة السريرية**
> 
> قد تشير الأحاسيس الحادة أو المفاجئة، مثل الفرقعة أو الألم الممتد مع تنميل، إلى إصابة محتملة في الأنسجة الرخوة أو المفصل. **MYOS سجل تدريب آلي ومحرك لميكانيكا الحركة، وليس طبيبًا.**
> 
> - **أوقف فورًا تدريب الحركة المتأثرة.**
> - لا تحاول مواصلة التدريب مع الألم الحاد أو الممتد.
> - اطلب تقييمًا تشخيصيًا من طبيب مختص في الطب الرياضي أو أخصائي علاج طبيعي مرخّص.

- Judge 1: The reply uses formal Modern Standard Arabic vocabulary and grammar such as 'تفعيل', 'إجراء', 'تشخيصي', 'مرخّص', and the formal structure 'قد تشير', without any Egyptian colloquial markers.
- Judge 2: The reply uses MSA wording like "قد تشير", "ينبغي"-style formal phrasing, "أوقف فورًا", "اطلب تقييمًا تشخيصيًا", with no Egyptian markers like عايز or كده.

## 9. `ar-inj-04` — expected **standard**; judge 1: **standard**, judge 2: **standard**

**Player:** أسفل ظهري بيؤلمني بشدة بعد الـ deadlift والألم نازل لرجلي

**Reply:**

> ⚠️ **تم إيقاف الحركة وتفعيل إجراء السلامة السريرية**
> 
> قد تشير الأحاسيس الحادة أو المفاجئة، مثل الفرقعة أو الألم الممتد مع تنميل، إلى إصابة محتملة في الأنسجة الرخوة أو المفصل. **MYOS سجل تدريب آلي ومحرك لميكانيكا الحركة، وليس طبيبًا.**
> 
> - **أوقف فورًا تدريب الحركة المتأثرة.**
> - لا تحاول مواصلة التدريب مع الألم الحاد أو الممتد.
> - اطلب تقييمًا تشخيصيًا من طبيب مختص في الطب الرياضي أو أخصائي علاج طبيعي مرخّص.

- Judge 1: The reply uses formal Modern Standard Arabic vocabulary and grammar such as 'تفعيل', 'إجراء', 'تشخيصي', 'مرخّص', and the formal structure 'قد تشير... إلى', without any Egyptian colloquial markers.
- Judge 2: The reply uses MSA wording like "قد تشير", "أوقف فورًا", "اطلب تقييمًا تشخيصيًا", and "لا تحاول مواصلة" with no Egyptian markers such as عايز or كده.

## 10. `ar-inj-05` — expected **standard**; judge 1: **standard**, judge 2: **standard**

**Player:** كوعي بيطقطق مع وجع كل ما أعمل تمرين تراي

**Reply:**

> ⚠️ **تم إيقاف الحركة وتفعيل إجراء السلامة السريرية**
> 
> قد تشير الأحاسيس الحادة أو المفاجئة، مثل الفرقعة أو الألم الممتد مع تنميل، إلى إصابة محتملة في الأنسجة الرخوة أو المفصل. **MYOS سجل تدريب آلي ومحرك لميكانيكا الحركة، وليس طبيبًا.**
> 
> - **أوقف فورًا تدريب الحركة المتأثرة.**
> - لا تحاول مواصلة التدريب مع الألم الحاد أو الممتد.
> - اطلب تقييمًا تشخيصيًا من طبيب مختص في الطب الرياضي أو أخصائي علاج طبيعي مرخّص.

- Judge 1: The reply uses formal Modern Standard Arabic vocabulary and grammar such as 'تم إيقاف', 'قد تشير', 'إجراء السلامة السريرية', and 'مرخّص', without any Egyptian colloquial markers.
- Judge 2: The reply uses MSA wording like "قد تشير", "ينبغي"-style formal phrasing, "أوقف فورًا", "اطلب تقييمًا تشخيصيًا", with no Egyptian markers like عايز or كده.
