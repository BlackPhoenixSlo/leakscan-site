# One origin: landing site (site/ -> /site) + scan API and legacy UI at /app/ (app/ -> /app).
# Build from the repo root: docker build -f deploy/Dockerfile .   (compose: context .., see docker-compose.yml)
FROM python:3.13-slim

WORKDIR /app
# Pillow: build_gallery.py / media_gather.py. curl_cffi + playwright (python package only, no browsers:
# media_gather.py drives a remote Browserbase browser over CDP). Own layer so it caches apart from the code.
RUN pip install --no-cache-dir Pillow curl_cffi playwright
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PUBLIC_HOST=0.0.0.0 \
    PUBLIC_PORT=8080 \
    BIG_SCAN_CSE_IMAGES_ONLY=0 \
    INCOGNITON_DISABLE=1 \
    BIO_VERIFY_ENABLED=0 \
    TRUST_XFF=1 \
    PUBLIC_DB=/data/public.db \
    SITE_DIR=/site

COPY app/ /app/
COPY site/ /site/
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=8s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4).status==200 else 1)"

CMD ["python3", "public_app.py"]
