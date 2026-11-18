"""Generate NEW VAPID credentials on stdout; never reads environment or files."""

import argparse
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, help="A mailto: contact or HTTPS contact URL")
    args = parser.parse_args()
    if not args.subject.startswith(("mailto:", "https://")) or any(c.isspace() for c in args.subject):
        parser.error("subject must be a mailto: contact or HTTPS URL without whitespace")
    private = ec.generate_private_key(ec.SECP256R1())
    public_bytes = private.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
    private_bytes = private.private_bytes(serialization.Encoding.DER,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption())
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    print(f"VAPID_PUBLIC_KEY={encode(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY={encode(private_bytes)}")
    print(f"VAPID_SUBJECT={args.subject}")


if __name__ == "__main__":
    main()
