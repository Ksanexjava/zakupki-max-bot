FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PANEL_HOST=0.0.0.0 \
    PANEL_PORT=8080 \
    DATABASE_URL=sqlite+aiosqlite:////data/purchases.db \
    MEDIA_DIR=/data/media
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# uid фиксируем: папку data на хосте надо отдать этому же пользователю
RUN useradd --create-home --uid 1000 appuser && mkdir -p /data && chown -R appuser /data /app
USER appuser
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"
CMD ["python", "-m", "bot.main"]
