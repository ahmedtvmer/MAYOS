part of 'api_client.dart';

extension NutritionDraftApi on ApiClient {
  String _nutritionDraftPath(String assignmentId) =>
      '/coach/assignments/$assignmentId/nutrition/draft';

  Future<Map<String, dynamic>> coachNutritionDraft(String assignmentId) async {
    final response = await _send(() => _dio.get<dynamic>(_nutritionDraftPath(assignmentId)));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> startNutritionDraft(String assignmentId, String source) async {
    final response = await _send(() => _dio.post<dynamic>(_nutritionDraftPath(assignmentId),
        data: <String, dynamic>{'source': source}));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> saveNutritionDraft(String assignmentId,
      Map<String, dynamic> draft, int revision) async {
    final response = await _send(() => _dio.put<dynamic>(_nutritionDraftPath(assignmentId),
        data: <String, dynamic>{'draft': draft, 'revision': revision}));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<void> discardNutritionDraft(String assignmentId) async {
    await _send(() => _dio.delete<dynamic>(_nutritionDraftPath(assignmentId)));
  }

  Future<void> publishNutritionDraft(String assignmentId, int revision) async {
    await _send(() => _dio.post<dynamic>('${_nutritionDraftPath(assignmentId)}/publish',
        data: <String, dynamic>{'revision': revision, 'confirm_takeover': true}));
  }

  Future<List<Map<String, dynamic>>> nutritionDraftFoods(String assignmentId, String query) async {
    final response = await _send(() => _dio.get<dynamic>('${_nutritionDraftPath(assignmentId)}/foods',
        queryParameters: <String, dynamic>{'q': query}));
    return (response.data['foods'] as List<dynamic>)
        .map((dynamic food) => Map<String, dynamic>.from(food as Map)).toList();
  }
}
