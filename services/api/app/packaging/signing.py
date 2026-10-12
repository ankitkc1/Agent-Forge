"""Ed25519 artifact signing.

``AGENTFORGE_SIGNING_KEY`` holds a base64-encoded 32-byte Ed25519 seed or a PKCS#8 PEM private key.
The packager signs ``.agentforge/MANIFEST.sha256``; the public key is published at
``GET /api/v1/system/signing-key`` and embedded in each artifact so anyone can verify offline::

    python -m app.cli verify-artifact build.zip
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ALGORITHM = "ed25519"


class SigningKeyError(ValueError):
    pass


@dataclass(frozen=True)
class Signer:
    private_key: Ed25519PrivateKey
    key_id: str

    @property
    def public_pem(self) -> str:
        return (
            self.private_key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

    def sign(self, data: bytes) -> str:
        return base64.b64encode(self.private_key.sign(data)).decode()


def key_id_for(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f"{ALGORITHM}:{hashlib.sha256(raw).hexdigest()[:16]}"


def key_id_for_pem(public_pem: str) -> str | None:
    try:
        public_key = serialization.load_pem_public_key(public_pem.encode())
    except ValueError:
        return None
    return key_id_for(public_key) if isinstance(public_key, Ed25519PublicKey) else None


def load_signer(secret: str | None, key_id: str | None = None) -> Signer | None:
    if not secret:
        return None
    value = secret.strip()
    try:
        if value.startswith("-----BEGIN"):
            key = serialization.load_pem_private_key(value.encode(), password=None)
        else:
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(value, validate=True))
    except (ValueError, TypeError) as exc:
        raise SigningKeyError("AGENTFORGE_SIGNING_KEY is not a valid Ed25519 key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("AGENTFORGE_SIGNING_KEY must be an Ed25519 key")
    return Signer(key, key_id or key_id_for(key.public_key()))


def generate_key() -> tuple[str, str]:
    """Return (base64 private seed, public PEM)."""
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    signer = Signer(key, key_id_for(key.public_key()))
    return base64.b64encode(seed).decode(), signer.public_pem


def verify(public_pem: str, data: bytes, signature_b64: str) -> bool:
    try:
        public_key = serialization.load_pem_public_key(public_pem.encode())
    except ValueError:
        return False
    if not isinstance(public_key, Ed25519PublicKey):
        return False
    try:
        public_key.verify(base64.b64decode(signature_b64), data)
    except (InvalidSignature, ValueError):
        return False
    return True
