"""FastAPI service: auth, dependencies, and routers.

Route handlers must never trust client-supplied trainee ids; they use
:func:`svc.dependencies.get_current_trainee` (JWT ``sub``) and pass the
server-derived id into ``service.*`` functions.
"""
