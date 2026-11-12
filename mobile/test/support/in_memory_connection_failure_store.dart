import 'package:mayos_mobile/src/core/connection_failures.dart';

class InMemoryConnectionFailureStore implements ConnectionFailureStore {
  final Map<String, List<ClientConnectionFailure>> _failures =
      <String, List<ClientConnectionFailure>>{};

  @override
  Future<List<ClientConnectionFailure>> read(String accountId) async =>
      List<ClientConnectionFailure>.of(
        _failures[accountId] ?? <ClientConnectionFailure>[],
      );

  @override
  Future<void> write(
    String accountId,
    List<ClientConnectionFailure> failures,
  ) async {
    _failures[accountId] = List<ClientConnectionFailure>.of(failures);
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _failures.remove(accountId);
  }
}
