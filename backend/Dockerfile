FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --no-deps -r requirements.lock && pip check && useradd --uid 10001 --create-home app
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests
COPY tools ./tools
COPY typings ./typings
USER 10001:10001
CMD ["python", "-m", "uvicorn", "app.bootstrap:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
