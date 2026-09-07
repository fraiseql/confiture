"""``import confiture.testing`` must not import the core package.

pytest loads ``confiture.testing.pytest_plugin`` through its ``pytest11`` entry point at
the start of every session on a machine with confiture installed. Until Phase 11 the
package's ``__init__`` eagerly re-exported the sandbox, fixtures and frameworks, which
imported ``confiture.core`` — paying the whole package's import cost in every user's
pytest start-up and, under ``pytest --cov``, importing the package before coverage
began recording. The names are lazy now; this pins it, in a fresh interpreter.
"""

from __future__ import annotations

import json
import subprocess
import sys

import confiture.testing as testing_pkg

PROBE = """
import json, sys
import confiture.testing
import confiture.testing.pytest_plugin
loaded = sorted(m for m in sys.modules if m.startswith("confiture."))
print(json.dumps(loaded))
"""


def test_importing_the_testing_package_and_plugin_leaves_core_unimported() -> None:
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    ).stdout
    loaded = json.loads(out)
    heavy = [
        m for m in loaded if m.startswith(("confiture.core", "confiture.cli", "confiture.config"))
    ]
    assert heavy == [], f"importing confiture.testing pulled in: {heavy}"


def test_every_public_name_resolves_lazily() -> None:
    for name in testing_pkg.__all__:
        assert getattr(testing_pkg, name) is not None, name
    assert "MigrationSandbox" in dir(testing_pkg)


def test_unknown_name_raises_attribute_error() -> None:
    try:
        testing_pkg.no_such_name  # noqa: B018
    except AttributeError as exc:
        assert "no_such_name" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected AttributeError")
