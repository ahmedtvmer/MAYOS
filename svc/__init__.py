"""FastAPI service: auth, dependencies, and routers.

Route handlers must never trust client-supplied player ids; they use
:func:`svc.dependencies.get_current_player`, which verifies the JWT ``sub``
(the immutable account id) against the catalog account registry and returns the
account's resolved ledger id for ``service.*`` calls.
"""
