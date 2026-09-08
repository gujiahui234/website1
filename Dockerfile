FROM python:3.13-slim

# Tsinghua PyPI mirror: docker01's direct PyPI route is slow and flaky. The
# pip cache mount keeps downloaded wheels across builds.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# NOTE: no git on purpose — the GitHub-hosted dependencies
# (class-roster-simulator, sclog_lite) come from the committed wheelhouse/
# directory so the build never needs to reach github.com. PyPI access is
# still required for Flask/celery/etc.
COPY pyproject.toml README.md LICENSE ./
COPY wheelhouse ./wheelhouse
COPY src ./src
COPY wsgi.py ./

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --find-links=/app/wheelhouse .

RUN mkdir -p /app/logs && chown -R app:app /app/logs

USER app

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "wsgi:app"]
