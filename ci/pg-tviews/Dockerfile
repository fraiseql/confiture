# PostgreSQL 18 carrying pg_tviews, for the `pg-tviews` leg of quality-gate.yml (#504).
#
# pg_tviews is in no distribution and publishes no installable package, so it is
# built here from a pinned tag with the pgrx version it pins (Cargo.toml:
# pgrx = "=0.17.0") against PGDG's PostgreSQL 18, and its packaged tree is
# copied onto the official image of the same Debian release.
FROM rust:1.91.1-slim-bookworm AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends wget gnupg ca-certificates lsb-release git \
 && wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor > /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-18 postgresql-server-dev-18 build-essential pkg-config clang libclang-dev \
 && rm -rf /var/lib/apt/lists/*
RUN cargo install --locked cargo-pgrx --version 0.17.0
RUN cargo pgrx init --pg18 /usr/lib/postgresql/18/bin/pg_config
ARG PG_TVIEWS_REF=v0.1.0-beta.17
RUN git clone --depth 1 --branch "$PG_TVIEWS_REF" https://github.com/fraiseql/pg_tviews /src
WORKDIR /src
RUN cargo pgrx package --no-default-features --features pg18 \
      --pg-config /usr/lib/postgresql/18/bin/pg_config --out-dir /out

FROM postgres:18-bookworm
COPY --from=build /out/ /
# Preloaded, as pg_tviews requires: a session that has not loaded the library
# turns `CREATE TABLE tv_x AS …` into a plain table and registers nothing.
CMD ["postgres", "-c", "shared_preload_libraries=pg_tviews"]
