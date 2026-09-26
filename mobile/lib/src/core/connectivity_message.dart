import 'api_client.dart';

/// One consistent message for an action that mutates program/schedule state on
/// the server but cannot reach it (spec AC3, ADR 036).
///
/// Program-changing actions require connectivity and are never queued, so on a
/// network failure every screen shows the same explicit line rather than a
/// per-screen string. Only call this for an [ApiException] with a null status
/// code; a server refusal keeps its own `detail` message.
const String needsConnectionMessage =
    'This needs a connection. Nothing was changed.';

/// True when [error] is a transport failure rather than a service refusal.
///
/// This is the same signal [DraftSyncService] uses, so the app has one
/// definition of "offline" and needs no connectivity package.
bool isNetworkFailure(ApiException error) => error.statusCode == null;

/// The message to show for a failed program-changing action: the shared
/// connectivity line for a transport failure, otherwise the server's own
/// message.
String mutationFailureMessage(ApiException error) =>
    isNetworkFailure(error) ? needsConnectionMessage : error.message;
