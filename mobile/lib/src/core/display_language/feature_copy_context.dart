import 'package:flutter/widgets.dart';

import 'assignment_copy.dart';
import 'coach_copy.dart';
import 'copy_context.dart';
import 'program_change_copy.dart';
import 'profile_copy.dart';
import 'settings_copy.dart';
import 'workout_copy.dart';

export 'workout_copy.dart' show WorkoutCopy;

WorkoutCopy workoutCopyOf(BuildContext context) =>
    WorkoutCopy(displayCopyOf(context).languageCode);

ProfileCopy profileCopyOf(BuildContext context) =>
    ProfileCopy(displayCopyOf(context).languageCode);

AssignmentCopy assignmentCopyOf(BuildContext context) =>
    AssignmentCopy(displayCopyOf(context).languageCode);

ProgramChangeCopy programChangeCopyOf(BuildContext context) =>
    ProgramChangeCopy(displayCopyOf(context).languageCode);

CoachCopy coachCopyOf(BuildContext context) =>
    CoachCopy(displayCopyOf(context).languageCode);

SettingsCopy settingsCopyOf(BuildContext context) =>
    SettingsCopy(displayCopyOf(context).languageCode);
