import 'package:dio/dio.dart';
import 'package:dio/io.dart';

/// Android/desktop: a fresh adapter has an empty connection pool (#894).
HttpClientAdapter? createAppHttpAdapter() => IOHttpClientAdapter();
