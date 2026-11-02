# PostgreSQL 18 carrying pg_tviews, for the `pg-tviews` leg of quality-gate.yml (#504).
#
# pg_tviews is in no distribution, so it is built here from a pinned ref with the
# pgrx version it pins (Cargo.toml: pgrx = "=0.17.0") against PGDG's PostgreSQL 18,
# and the tree `cargo pgrx package` writes is copied onto the official image of the
# same Debian release. The ref is the head of fraiseql/pg_tviews' 0.1.0-beta.35
# branch (`refactor/architecture-2026-11`, fraiseql/pg_tviews#285); it moves to the
# signed v0.1.0-beta.35 tag's commit once that is cut. 0.1.0-beta.35 offers read
# contract 3, which confiture reads beside contract 2 (the registry, its `options`
# and `pg_tviews_create_or_replace()` as contract 2 has them; the rest of the
# surface renamed). Fetched by SHA so a build reproduces and the layer cache never
# serves another tree under the same ref.
#
# pg_tviews requires jsonb_delta (`requires = 'jsonb_delta'`), built here at the
# commit of its v0.3.0 tag, the release pg_tviews' own CI runs.
#
# The previous release's install script is copied in beside it, so a database can
# hold a 0.1.0-beta.34 catalog under the 0.1.0-beta.35 library: the state between a
# package install and `ALTER EXTENSION pg_tviews UPDATE`, which `migrate up` closes
# (#809). The same script is also installed as `0.1.0-beta.33`, a version the package
# has no update from, for the refusal and `--recreate-pg-tviews`.
FROM rust:1.91.1-slim-bookworm AS toolchain
RUN apt-get update \
 && apt-get install -y --no-install-recommends wget gnupg ca-certificates lsb-release git \
 && wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor > /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-18 postgresql-server-dev-18 build-essential pkg-config clang libclang-dev \
 && rm -rf /var/lib/apt/lists/*
RUN cargo install --locked cargo-pgrx --version 0.17.0
RUN cargo pgrx init --pg18 /usr/lib/postgresql/18/bin/pg_config

FROM toolchain AS jsonb_delta
ARG JSONB_DELTA_REF=f5c495030a92fcf112be098e9ef15f8f24d4a728
WORKDIR /src
RUN git init -q \
 && git fetch -q --depth 1 https://github.com/evoludigit/jsonb_delta "$JSONB_DELTA_REF" \
 && git checkout -q FETCH_HEAD
RUN cargo pgrx package --no-default-features --features pg18 \
      --pg-config /usr/lib/postgresql/18/bin/pg_config --out-dir /out

FROM toolchain AS previous
ARG PG_TVIEWS_PREVIOUS_REF=c36b32686860ecfe057ca55e9218051997156377
WORKDIR /src
RUN git init -q \
 && git fetch -q --depth 1 https://github.com/fraiseql/pg_tviews "$PG_TVIEWS_PREVIOUS_REF" \
 && git checkout -q FETCH_HEAD
RUN cargo pgrx package --no-default-features --features pg18 \
      --pg-config /usr/lib/postgresql/18/bin/pg_config --out-dir /out

FROM toolchain AS pg_tviews
ARG PG_TVIEWS_REF=4dda99ec2e1bbcadefca0a8d49b8cc12d8bb9ddc
WORKDIR /src
RUN git init -q \
 && git fetch -q --depth 1 https://github.com/fraiseql/pg_tviews "$PG_TVIEWS_REF" \
 && git checkout -q FETCH_HEAD
RUN cargo pgrx package --no-default-features --features pg18 \
      --pg-config /usr/lib/postgresql/18/bin/pg_config --out-dir /out

FROM postgres:18-bookworm
COPY --from=jsonb_delta /out/ /
COPY --from=pg_tviews /out/ /
ARG EXTENSIONS=/usr/share/postgresql/18/extension
COPY --from=previous /out${EXTENSIONS}/pg_tviews--0.1.0-beta.34.sql ${EXTENSIONS}/
RUN cp ${EXTENSIONS}/pg_tviews--0.1.0-beta.34.sql ${EXTENSIONS}/pg_tviews--0.1.0-beta.33.sql
# Preloaded, as pg_tviews requires: CREATE EXTENSION and every write refuse
# (55000) when the library is not in shared_preload_libraries.
CMD ["postgres", "-c", "shared_preload_libraries=pg_tviews"]
