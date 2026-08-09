# Portable deploy target — works on Railway, Render, Fly, Cloud Run.
# Railway/Render can also build this from the Procfile via Nixpacks; the
# Dockerfile is here so the build is identical everywhere and doesn't depend
# on a host's autodetection guessing right.
#
# IMPORTANT for Railway/Render: this app lives in backend/, not the repo
# root. Set "Root Directory" to `backend` in the service settings, or the
# build won't find requirements.txt.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The host injects $PORT. Binding 0.0.0.0 is required — binding localhost
# makes the container unreachable from outside, which is the single most
# common "deploy succeeded but nothing responds" cause.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at runtime rather than being taken literally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
