import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';

void main() {
  test('unknown deload states fall back to none', () {
    final DeloadDecision decision = DeloadDecision.fromJson(
      <String, dynamic>{'state': 'future_state'},
    );

    expect(decision.state, DeloadState.none);
    expect(decision.isVisible, isFalse);
  });

  test('applied deload without adjustments has a useful summary', () {
    const DeloadDecision decision = DeloadDecision(
      state: DeloadState.applied,
    );

    expect(decision.changeSummary, 'No set or RPE changes applied.');
    expect(decision.changeSummary, isNot('Applied: .'));
  });
}
