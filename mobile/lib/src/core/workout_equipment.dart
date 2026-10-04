/// The logger's display and input categories for Exercise library equipment.
enum WorkoutEquipmentKind { bodyWeight, band, other }

/// Maps Exercise library equipment to the logger's equipment category.
WorkoutEquipmentKind workoutEquipmentKind(String? equipment) {
  switch (equipment?.trim().toLowerCase()) {
    case 'body weight':
      return WorkoutEquipmentKind.bodyWeight;
    case 'band':
    case 'resistance band':
      return WorkoutEquipmentKind.band;
    default:
      return WorkoutEquipmentKind.other;
  }
}

/// Returns the zero-load display category when equipment gives zero a label.
WorkoutEquipmentKind? zeroLoadLabelKind(double weightKg, String? equipment) {
  if (weightKg != 0) {
    return null;
  }
  final WorkoutEquipmentKind kind = workoutEquipmentKind(equipment);
  return kind == WorkoutEquipmentKind.other ? null : kind;
}

/// Returns the weight unit unless zero load has an equipment label.
String exerciseWeightUnit(
  double weightKg,
  String? equipment, {
  String unit = 'kg',
}) =>
    zeroLoadLabelKind(weightKg, equipment) == null ? unit : '';

/// Whether Exercise library equipment is body weight or a resistance band.
bool isBodyWeightOrBandEquipment(String? equipment) =>
    workoutEquipmentKind(equipment) != WorkoutEquipmentKind.other;
