# Closed test: testers (issue #881)

New personal Play developer accounts must run a **closed test with at least
12 testers opted in for 14 days in a row** before they can apply for
production. Aim for about 15 testers so one or two dropping out doesn't reset
the count. Use real people only: Google checks real installs and use, and a
padded tester list can get production access refused or the account
suspended.

## Google Group setup (once)

1. Create a Google Group at groups.google.com, for example `mayos-testers`.
   Set **Who can join** to "Invited users only" and **Who can view members**
   to "Group managers".
2. Add each tester's Gmail address (the one signed in to Play on their phone).
3. Play Console → **Testing → Closed testing** → the track → **Testers** →
   add the group's email address as the tester list.
4. Copy the **opt-in link** from the same page; it goes in the message below.

New testers then join the group, with no Play Console change.

## Invite message (English)

> Hi! I'm testing MAYOS, my training app, before it launches on Google Play, and I'd love your help.
>
> 1. Open this link on your Android phone, signed in with this Gmail: [opt-in link]
> 2. Tap "Become a tester", then "Download it on Google Play" and install.
> 3. Create an account and use it like a normal Player: build your program, log a workout or two, try the Food log, and ask the assistant something.
> 4. Please keep the app installed and stay in the test for 14 days. Leaving early resets Google's count.
>
> If something breaks or feels confusing, tell me, or report the assistant reply from its menu. Thank you!

## Invite message (Arabic)

> أهلاً! أنا بجرّب تطبيقي للتمرين MAYOS ميوس قبل ما ينزل على Google Play، ومحتاج مساعدتك.
>
> ١. افتح اللينك ده من موبايلك الأندرويد وإنت داخل بنفس حساب Gmail ده: [رابط الانضمام]
>
> ٢. اضغط "Become a tester" وبعدين "Download it on Google Play" ونزّل التطبيق.
>
> ٣. اعمل حساب واستخدمه عادي كلاعب: اعمل برنامجك التدريبي، سجّل حصة تدريبية أو اتنين، جرّب سجل الطعام، واسأل المساعد أي سؤال.
>
> ٤. من فضلك خلّي التطبيق متسطّب وفضل في التجربة ١٤ يوم. لو خرجت بدري العدّ بيبدأ من الأول عند جوجل.
>
> لو حاجة باظت أو مش واضحة قولّي، أو بلّغ عن رد المساعد من القائمة بتاعته. شكراً!

## During the 14 days

- Check Play Console → **Testing → Closed testing** for the opted-in count;
  keep it at 12 or more every day.
- Ship fixes to the same closed track; updating the build does not reset the
  14 days.
- When applying for production, Play asks how testers were recruited, what
  feedback they gave and what changed. Keep short notes as feedback comes in.
