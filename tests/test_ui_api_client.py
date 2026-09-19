"""Transport-helper tests: ``request_json`` never raises and shapes errors cleanly.

These cover the blank-screen bug class: malformed bodies, HTML error pages,
timeouts, and refused connections must all come back as displayable tuples.
"""

import httpx

from ui import api_client


def test_success_dict_body():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    assert api_client.request_json("GET", "/x", transport=transport) == (200, {"ok": True}, None)


def test_success_list_body_preserved():
    # /chat/history and /dashboard/exercises return JSON arrays; they must survive.
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"role": "user"}]))
    assert api_client.request_json("GET", "/chat/history", transport=transport) == (200, [{"role": "user"}], None)


def test_204_and_empty_200_have_no_body_or_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    assert api_client.request_json("DELETE", "/x", transport=transport) == (204, None, None)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    assert api_client.request_json("GET", "/x", transport=transport) == (200, None, None)


def test_400_detail_is_displayable():
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"detail": "Invalid credentials."}))
    status, body, detail = api_client.request_json("POST", "/auth/login", json={}, transport=transport)
    assert status == 400 and body == {"detail": "Invalid credentials."} and detail == "Invalid credentials."


def test_429_slowapi_error_key_is_displayable():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "Rate limit exceeded: 5 per 1 minute"})
    )
    status, _, detail = api_client.request_json("POST", "/auth/login", json={}, transport=transport)
    assert status == 429 and "Rate limit" in detail


def test_422_validation_detail_list_is_displayable():
    transport = httpx.MockTransport(lambda request: httpx.Response(422, json={"detail": [{"msg": "bad"}]}))
    status, _, detail = api_client.request_json("POST", "/auth/register", json={}, transport=transport)
    assert status == 422 and detail and "bad" in detail


def test_500_html_body_never_raises():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, headers={"content-type": "text/html"}, text="<html>boom</html>")
    )
    status, body, detail = api_client.request_json("GET", "/profile", transport=transport)
    assert status == 500 and body is None and detail == "Request failed (500)."


def test_connect_error_returns_status_zero():
    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(refused)
    status, body, detail = api_client.request_json("GET", "/x", transport=transport)
    assert status == 0 and body is None and "Cannot reach the training service" in detail


def test_timeout_returns_status_zero():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(slow)
    status, _, detail = api_client.request_json("GET", "/x", transport=transport)
    assert status == 0 and "ReadTimeout" in detail


def test_headers_are_forwarded():
    seen = {}

    def capture(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    api_client.request_json("GET", "/x", headers={"Authorization": "Bearer t"}, transport=httpx.MockTransport(capture))
    assert seen["auth"] == "Bearer t"
