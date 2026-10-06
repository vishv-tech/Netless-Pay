FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 wallet
COPY --chown=wallet:wallet app ./app
COPY --chown=wallet:wallet alembic ./alembic
COPY --chown=wallet:wallet alembic.ini .
USER wallet
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]

FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=wallet:wallet tests ./tests
COPY --chown=wallet:wallet pyproject.toml .
USER wallet
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

# Normal builds remain runtime-only: test code/dependencies are not shipped.
FROM base AS runtime
