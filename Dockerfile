# Worker de separación de pistas y render de video para RunPod Serverless.
#
# IMPORTANTE: la RTX 5090 es arquitectura Blackwell (sm_120) y necesita CUDA 12.8+
# y un PyTorch compilado para esa versión. Por eso se parte de una imagen CUDA 12.8.
# Si usas otra GPU (4090, A100, etc.) puedes bajar a una imagen CUDA 12.1.
FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VOLUME_PATH=/runpod-volume \
    MODEL_DIR=/runpod-volume/models \
    HF_HOME=/runpod-volume/models/hf \
    TORCH_HOME=/runpod-volume/models/torch

# ffmpeg y libsndfile son necesarios para leer/escribir audio.
# build-essential aporta gcc/g++, que algunas dependencias (p. ej. diffq) necesitan para compilar.
# fonts-liberation es el sustituto métricamente compatible de Arial para los subtítulos (libass).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 build-essential git fontconfig fonts-liberation \
        curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ffmpeg estático moderno: el que trae la imagen base (vía conda) es antiguo y
# no soporta filtros que usa la app, como gradients=type=linear/radial.
RUN curl -L --fail https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz -o /tmp/ff.tar.xz \
    && mkdir -p /tmp/ff \
    && tar -xf /tmp/ff.tar.xz -C /tmp/ff --strip-components=1 \
    && cp /tmp/ff/bin/ffmpeg /tmp/ff/bin/ffprobe /usr/local/bin/ \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && rm -rf /tmp/ff /tmp/ff.tar.xz

# Usar explícitamente el ffmpeg nuevo.
ENV FFMPEG_BIN=/usr/local/bin/ffmpeg

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py .

CMD ["python", "-u", "handler.py"]
