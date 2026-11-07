"""Uptime monitors probe with HEAD, so a health route must not answer 405."""

import pytest
from fastapi.testclient import TestClient

from svc.app import create_app


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_head_gets_the_same_status_as_get(path):
    client = TestClient(create_app())
    assert client.head(path).status_code == client.get(path).status_code
