import 'package:dio/dio.dart';

/// Web: the browser manages connections, so Dio keeps its default adapter.
HttpClientAdapter? createAppHttpAdapter() => null;
