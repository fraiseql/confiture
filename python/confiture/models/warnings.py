"""The build-time warning every envelope that carries ``warnings[]`` reports.

A leaf of ``models/``: ``models/schema.py`` and ``models/results.py`` both need it,
and when it lived in ``results`` it made ``schema`` import ``results`` while
``results`` annotated with ``schema`` — a cycle inside the package every other
layer imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from confiture.error_codes import ERROR_CODE_REGISTRY


@dataclass(frozen=True)
class BuildWarning:
    """A build-time diagnostic that reaches the envelope, not only the console.

    ``confiture build`` has always had diagnostics it printed and never
    published — a seed file that failed under ``--continue-on-error``, a file
    pglast could not parse during the duplicate scan. A consumer doing the right
    thing (reading the JSON, not the prose) could not see them (issue #268).
    They are entries here now, keyed by an error-code registry entry so a
    consumer matches a code rather than a sentence.

    Attributes:
        code: The registry entry that names the situation.
        severity: That entry's severity — ``warning`` or ``info``. Resolved from
            the registry by :meth:`of`, never written twice.
        message: What happened, in one line.
        file: The file the warning is about, named the way a finding names one;
            ``None`` when the warning is about the build rather than a file.
    """

    code: str
    severity: str
    message: str
    file: str | None = None

    @classmethod
    def of(cls, code: str, *, file: str | None = None, **fields: object) -> BuildWarning:
        """The registry's entry for *code*, filled in.

        Severity *and* wording come from the registry, so the sentence a build
        prints is the one the published codebook documents — neither can drift
        from the other by being written twice.

        Args:
            code: A registered error code.
            file: The file the warning is about, when it is about one. Also
                available to the message template as ``{file}``.
            **fields: The remaining placeholders of the code's message template.

        Returns:
            The warning, ready for the envelope.

        Raises:
            ValueError: *code* is not registered — a warning no consumer could
                look up is a bug, not a payload.
            KeyError: The template has a placeholder *fields* does not fill.
        """
        definition = ERROR_CODE_REGISTRY.get(code)
        return cls(
            code=code,
            severity=definition.severity.value,
            message=definition.message_template.format(file=file, **fields),
            file=file,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the envelope's ``warnings[]`` entry."""
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
        }
