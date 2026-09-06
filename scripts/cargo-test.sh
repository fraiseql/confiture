#!/usr/bin/env sh
# Run the Rust crate's unit tests.
#
# Without the `extension-module` feature (which only maturin enables) the test
# binary links against libpython, so the interpreter's library directory must
# be on the loader path. This resolves it from the active Python — the project
# venv under `uv run`, or whatever `python3` is on PATH in CI — and runs
# `cargo test --locked` with any extra arguments passed through.
set -eu
PY="${PYTHON:-python3}"
if command -v uv >/dev/null 2>&1 && [ -d .venv ]; then
  PY="uv run --no-sync python"
fi
LIBDIR="$($PY -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")')"
if [ -n "$LIBDIR" ]; then
  export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export DYLD_LIBRARY_PATH="$LIBDIR${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi
exec cargo test --locked "$@"
