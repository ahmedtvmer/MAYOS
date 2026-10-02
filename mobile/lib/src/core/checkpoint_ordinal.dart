/// Formats checkpoint workout ordinals with English ordinal suffixes.
String checkpointOrdinal(int value) {
  final int lastTwo = value % 100;
  if (lastTwo >= 11 && lastTwo <= 13) {
    return '${value}th';
  }
  return switch (value % 10) {
    1 => '${value}st',
    2 => '${value}nd',
    3 => '${value}rd',
    _ => '${value}th',
  };
}
