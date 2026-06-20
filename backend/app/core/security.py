"""Security helpers.

Principles enforced here:
  * No seed phrases, ever. The API explicitly rejects any field that looks
    like a mnemonic (see ``reject_seed_phrase``).
  * Sensitive at-rest values (e.g. read-only exchange API keys a user may
    store later) are encrypted with Fernet using ``ENCRYPTION_KEY``.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Common BIP-39 mnemonic lengths — a strong signal someone is pasting a seed.
_SUSPICIOUS_WORD_COUNTS = {12, 15, 18, 21, 24}


class SeedPhraseRejected(ValueError):
    """Raised when input looks like a wallet seed phrase."""


def reject_seed_phrase(text: str | None) -> None:
    """Defensive guard: never accept or store a seed phrase."""
    if not text:
        return
    words = [w for w in text.strip().split() if w.isalpha()]
    if len(words) in _SUSPICIOUS_WORD_COUNTS and len(words) == len(text.split()):
        raise SeedPhraseRejected(
            "Seed phrases are never accepted. HR5 Invest only ever uses "
            "read-only data — never import a private key or recovery phrase."
        )


def _fernet() -> Fernet | None:
    key = get_settings().encryption_key
    if not key:
        logger.warning("ENCRYPTION_KEY not set — sensitive at-rest data will not be encrypted.")
        return None
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    f = _fernet()
    return f.encrypt(value.encode()).decode() if f else value


def decrypt(token: str) -> str:
    f = _fernet()
    if not f:
        return token
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt a stored value (key mismatch?).")
        raise
