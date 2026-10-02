# GatorPlate brain, console, card and pages: one process, one worker (in-process event bus and per-call locks).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# A non-root user runs the app. The Fly volume is mounted root-owned at run time, so the start command hands /data
# to that user first and then drops privileges with runuser (util-linux, part of the Debian slim base).
RUN useradd --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /app /data

EXPOSE 8080

CMD ["sh","-c","chown app:app /data && exec runuser -u app -- uvicorn gatorplate.main:app --host 0.0.0.0 --port 8080 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips '*'"]
