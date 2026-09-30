"""Generate the Fly secrets for the separate owner dashboard identity."""

import base64
import getpass
import re
import secrets
from urllib.parse import quote, urlencode

import bcrypt

_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def generate_credentials(username: str, password: str) -> tuple[str, str, str]:
    """Returns a bcrypt hash, a fresh Base32 TOTP secret, and its app URI."""
    if not _USERNAME.fullmatch(username):
        raise ValueError("Owner username must use letters, digits, dot, underscore, or hyphen.")
    password_bytes = password.encode("utf-8")
    if not 8 <= len(password_bytes) <= 72:
        raise ValueError("Owner password must be 8 to 72 UTF-8 bytes.")
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    label = quote(f"MAYOS:{username}", safe="")
    query = urlencode({"secret": secret, "issuer": "MAYOS", "algorithm": "SHA1", "digits": 6, "period": 30})
    return password_hash, secret, f"otpauth://totp/{label}?{query}"


def main() -> None:
    username = input("Owner username: ").strip()
    password = getpass.getpass("Owner password: ")
    confirmation = getpass.getpass("Confirm owner password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match.")
    password_hash, secret, uri = generate_credentials(username, password)
    print(f"ADMIN_USERNAME={username}")
    print(f"ADMIN_PASSWORD_HASH={password_hash}")
    print(f"ADMIN_TOTP_SECRET={secret}")
    print(f"Authenticator URI: {uri}")


if __name__ == "__main__":
    main()
