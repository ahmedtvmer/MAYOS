part of 'api_client.dart';

enum FoodSwapRequestDecision { apply, decline }

extension FoodSwapRequestApi on ApiClient {
  Future<List<ProgramRequest>> playerFoodSwapRequests() async {
    final response = await _send(() => _dio.get<dynamic>('/nutrition/food-swap-requests'));
    return _parseBody(response.data, (Map<String, dynamic> body) =>
        _parseBodyList(body['requests'], ProgramRequest.fromJson,
          'The service returned invalid Food swap requests.'),
        'The service returned invalid Food swap requests.');
  }

  Future<void> requestFoodSwap(PlannedMeals plan, PlannedMeal meal, int foodIndex, String reason) async {
    await _send(() => _dio.post<dynamic>('/nutrition/food-swap-requests', data: <String, dynamic>{
      'plan_version_id': plan.planVersionId, 'day_type': plan.dayType,
      'slot': meal.slot, 'food_index': foodIndex, 'food_id': meal.foods[foodIndex].id, 'reason': reason,
    }));
  }

  Future<ProgramRequest> applyFoodSwapRequest(ProgramRequest request, {required String foodId,
      required double grams, String reply = ''}) => _foodSwapDecision(request, 'apply',
        <String, dynamic>{'response': reply, 'food_id': foodId, 'grams': grams});

  Future<ProgramRequest> declineFoodSwapRequest(ProgramRequest request, String reply) =>
      _foodSwapDecision(request, 'decline', <String, dynamic>{'response': reply});

  Future<ProgramRequest> _foodSwapDecision(ProgramRequest request, String decision, Map<String, dynamic> body) async {
    final response = await _send(() => _dio.post<dynamic>(
      '/coach/assignments/${request.assignmentId}/food-swap-requests/${request.requestId}/$decision',
      data: body));
    return _parseBody(response.data, ProgramRequest.fromJson,
        'The service returned an invalid Food swap decision.');
  }
}
