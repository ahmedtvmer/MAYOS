"""Hermetic test environment.

``agent/*`` modules call ``load_dotenv()`` at import time, which injects any
``.env`` keys not already present into ``os.environ``. If a developer keeps
cloud settings (``LLM_BACKEND=openai`` / ``LLM_API_KEY``) in their ``.env``,
every local-path unit test would silently take the cloud branch.

Declaring the backend pins here — at conftest import, before any test module is
collected — keeps the suite deterministic. ``load_dotenv()`` does not override
existing keys, and empty strings count as existing, so these neutral values
survive the agent-module imports. Cloud tests override them explicitly with
``monkeypatch.setenv`` and restore to these values on teardown.
"""

import os

os.environ["LLM_BACKEND"] = "local"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_BASE"] = ""
os.environ["LLM_EXTRA_BODY"] = ""
os.environ["LLM_ENABLE_THINKING"] = ""

# Same for outbound email: a developer `.env` with real SMTP settings must not
# make tests send mail. ``service/email_sender._deliver`` treats an empty
# SMTP_HOST as its console backend, so pinning it empty makes delivery hermetic.
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_PORT"] = ""
os.environ["SMTP_USE_TLS"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["SMTP_FROM"] = ""
os.environ["OWNER_ALERT_EMAIL"] = ""
