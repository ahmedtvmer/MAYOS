part of 'fake_mayos_api.dart';

extension _FoodSwapRequests on FakeMayosApi {
  FakeResponse _foodSwapRequestFoods(FakeRequest request) {
    if (!_authorized(request)) return const FakeResponse(401, <String, dynamic>{'detail': 'Unauthorized.'});
    if (!coach) return const FakeResponse(403, <String, dynamic>{'detail': 'Coach capability required.'});
    return FakeResponse(200, <String, dynamic>{'foods': foodSearchResults});
  }

  FakeResponse _foodSwapRequests(FakeRequest request) {
    if (!_authorized(request)) return const FakeResponse(401, <String, dynamic>{'detail': 'Unauthorized.'});
    if (request.path == '/nutrition/food-swap-requests') {
      if (request.method == 'GET') return FakeResponse(200, <String, dynamic>{
        'requests': programRequests.where((Map<String, dynamic> row) => row['kind'] == 'food_swap').toList()});
      if (foodWriteFails) return const FakeResponse(409, <String, dynamic>{'detail': 'The Nutrition plan changed.'});
      final Map<String, dynamic> meal = (plannedMealsState['meals'] as List<dynamic>)
          .cast<Map<String, dynamic>>().firstWhere((Map<String, dynamic> meal) => meal['slot'] == request.body['slot']);
      final Map<String, dynamic> food = (meal['foods'] as List<dynamic>)[request.body['food_index'] as int] as Map<String, dynamic>;
      final Map<String, dynamic> row = <String, dynamic>{
        'request_id': 'food-${programRequests.length}', 'assignment_id': 'a1', 'kind': 'food_swap',
        'program_version': null, 'status': 'pending', 'reason': request.body['reason'],
        'created_at': '2026-11-08T12:00:00Z', 'food_swap': <String, dynamic>{
          ...request.body, 'food_name': food['name'], 'food_name_ar': food['arabic_name'],
          'meal_name': meal['name'] ?? meal['slot'],
        },
      };
      programRequests.add(row);
      return FakeResponse(201, row);
    }
    if (!coach) return const FakeResponse(403, <String, dynamic>{'detail': 'Coach capability required.'});
    if (foodWriteFails) return const FakeResponse(409, <String, dynamic>{'detail': 'The Nutrition plan changed.'});
    final String id = request.path.split('/food-swap-requests/')[1].split('/')[0];
    final Map<String, dynamic> row = programRequests.firstWhere((Map<String, dynamic> row) => row['request_id'] == id);
    row['status'] = request.path.endsWith('/apply') ? 'applied' : 'declined';
    row['response'] = request.body['response'];
    row['resolved_at'] = '2026-11-08T13:00:00Z';
    return FakeResponse(200, row);
  }
}
