"""Keyed, deterministic pseudonyms for PII.

A pseudonym has to be two things at once: stable, so the same email maps to the
same replacement in every table and referential integrity survives; and
unlinkable, so nobody holding the anonymised copy can recover the original.
Plain ``sha256(value)`` gives the first and not the second — anyone can hash a
candidate value and compare. HMAC under a secret that never leaves the
deployment gives both.

This module is the one place that secret is read. Every keyed pseudonym in
confiture — ``confiture sync --anonymize`` and the registry's ``hash``
strategy — comes from a :class:`Pseudonymizer`.

The secret is mandatory. There is no default key: a well-known default is a
public key, and a public key is no key.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from confiture.exceptions import ConfigurationError

SECRET_ENV_VAR = "ANONYMIZATION_SECRET"


class Pseudonymizer:
    """HMAC-SHA256 pseudonyms under a per-deployment secret.

    Args:
        secret: The key. ``None`` reads ``ANONYMIZATION_SECRET`` from the
            environment.

    Raises:
        ConfigurationError: ``CONFIG_009`` when the secret is unset or blank.

    Example:
        >>> p = Pseudonymizer("a-long-random-string")
        >>> p.hex("john@example.com", length=8)   # doctest: +SKIP
        '4f1c…'
    """

    def __init__(self, secret: str | None = None, *, algorithm: str = "sha256") -> None:
        if secret is None:
            secret = os.getenv(SECRET_ENV_VAR)
        if secret is None or not secret.strip():
            raise ConfigurationError(
                f"{SECRET_ENV_VAR} is not set. Keyed anonymization (the email, phone, "
                "name and hash strategies) needs a per-deployment secret; there is no "
                "default.",
                error_code="CONFIG_009",
                context={"env_var": SECRET_ENV_VAR},
                resolution_hint=(
                    f"Export {SECRET_ENV_VAR} to a long random string kept out of "
                    "version control (e.g. `openssl rand -hex 32`) before running an "
                    "anonymizing sync or a keyed hash strategy."
                ),
            )
        self._secret = secret
        self._digestmod = getattr(hashlib, algorithm)

    def hex(self, value: Any, *, seed: int | None = None, length: int | None = None) -> str:
        """The hex digest of *value* under the secret.

        Args:
            value: Any value; it is pseudonymized by its ``str()`` form.
            seed: Optional domain separator. Different seeds give unrelated
                pseudonyms for the same value; it is folded into the key as
                ``f"{seed}{secret}"``, the derivation the ``hash`` strategy has
                always used, so existing secret holders see unchanged output.
            length: Optional truncation.

        Returns:
            Lower-case hex, ``length`` characters long when given.
        """
        key = f"{seed}{self._secret}" if seed is not None else self._secret
        digest = hmac.new(key.encode(), str(value).encode(), self._digestmod).hexdigest()
        return digest[:length] if length else digest

    def integer(self, value: Any, modulus: int, *, seed: int | None = None) -> int:
        """A pseudonymous integer in ``range(modulus)`` for *value*.

        Args:
            value: Any value; pseudonymized by its ``str()`` form.
            modulus: Exclusive upper bound; must be positive.
            seed: Optional domain separator, as for :meth:`hex`.

        Returns:
            ``int(hex(value), 16) % modulus``.
        """
        return int(self.hex(value, seed=seed), 16) % modulus
