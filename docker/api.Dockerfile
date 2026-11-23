FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg fonts-dejavu-core fonts-noto-core fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker/requirements.txt /app/worker/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /app/worker/requirements.txt
COPY server.py /app/server.py
COPY worker /app/worker
EXPOSE 3101
CMD ["python3", "server.py"]
