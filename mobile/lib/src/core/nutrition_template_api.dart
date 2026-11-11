part of 'api_client.dart';

extension NutritionTemplateApi on ApiClient {
  static const String _templatesPath = '/coach/nutrition-templates';

  Future<List<Map<String, dynamic>>> nutritionTemplates() async {
    final response = await _send(() => _dio.get<dynamic>(_templatesPath));
    return (response.data['templates'] as List<dynamic>)
        .map((dynamic template) => Map<String, dynamic>.from(template as Map)).toList();
  }

  Future<Map<String, dynamic>> nutritionTemplate(String templateId) async {
    final response = await _send(() => _dio.get<dynamic>('$_templatesPath/$templateId'));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> updateNutritionTemplate(String templateId, Map<String, dynamic> body) async {
    final response = await _send(() => _dio.put<dynamic>('$_templatesPath/$templateId', data: body));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<void> deleteNutritionTemplate(String templateId) async {
    await _send(() => _dio.delete<dynamic>('$_templatesPath/$templateId'));
  }

  Future<void> saveNutritionTemplate(String assignmentId, Map<String, dynamic> body) async {
    await _send(() => _dio.post<dynamic>('/coach/assignments/$assignmentId/nutrition/save-template', data: body));
  }

  Future<Map<String, dynamic>> nutritionTemplateSource(String assignmentId) async {
    final response = await _send(() => _dio.get<dynamic>('/coach/assignments/$assignmentId/nutrition/template-source'));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> applyNutritionTemplate(String templateId, String assignmentId, {int? revision}) async {
    final response = await _send(() => _dio.post<dynamic>('$_templatesPath/$templateId/apply',
      data: <String, dynamic>{'assignment_id': assignmentId, if (revision != null) 'revision': revision}));
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<List<Map<String, dynamic>>> nutritionTemplateFoods(String query) async {
    final response = await _send(() => _dio.get<dynamic>('$_templatesPath/foods',
      queryParameters: <String, dynamic>{'q': query}));
    return (response.data['foods'] as List<dynamic>)
        .map((dynamic food) => Map<String, dynamic>.from(food as Map)).toList();
  }
}
