# The ledger-desk images: one build, two targets.
#
#   docker build --target api -t ledger-desk-api .
#   docker build --target erp -t ledger-desk-erp .
#
# Follows uv's Docker guide (docs.astral.sh/uv/guides/integration/docker, read 2026-11-14): uv
# pinned, dependencies installed in their own layer before the project, bytecode compiled. No
# credentials go into the image: the database address arrives as LEDGER_DESK_DB_URL at run time,
# from the platform's secret store.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/
ENV UV_NO_DEV=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first: this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY invoices ./invoices
COPY evals ./evals
COPY replays ./replays
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 app && mkdir -p /app/out && chown app /app/out
USER app

FROM base AS api
EXPOSE 8000
CMD ["ledger-desk", "api-serve", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS erp
EXPOSE 8100
CMD ["ledger-desk", "erp-serve", "--host", "0.0.0.0", "--port", "8100"]
