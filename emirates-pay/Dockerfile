FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Numeric UID so Kubernetes `runAsNonRoot: true` can verify it.
RUN useradd --system --uid 10001 --no-create-home appuser \
 && mkdir /data && chown 10001 /data
USER 10001

ARG APP_VERSION=dev
ARG GIT_SHA=local
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    APP_ENV=production \
    DB_PATH=/data/emirates_pay.db

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status==200 else 1)"

# ONE worker + threads: SQLite and the in-process metrics need a single process.
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "30", "app.wsgi:app"]
