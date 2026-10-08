# Separación de pistas en RunPod Serverless

Worker que separa voz e instrumental en una GPU de RunPod. La app (ASP.NET Core)
le manda el audio en base64 y recibe de vuelta las dos pistas en base64.

## Contenido

- `handler.py` — lógica del worker (Demucs y audio-separator/UVR).
- `Dockerfile` — imagen con CUDA + PyTorch + Demucs + audio-separator.
- `requirements.txt` — dependencias Python.

## Esquema de entrada/salida

Entrada (`input`):

```json
{
  "audio_base64": "<audio en base64>",
  "filename": "original.mp3",
  "engine": "demucs",          // "demucs" | "uvr"
  "model": "htdemucs",         // archivo o preset del modelo
  "preset": false,             // true para el ensamble de UVR
  "output_format": "mp3",
  "bitrate": "320"
}
```

Salida correcta:

```json
{
  "vocals_base64": "...",
  "instrumental_base64": "...",
  "vocals_ext": ".mp3",
  "instrumental_ext": ".mp3",
  "elapsed_seconds": 18.4
}
```

Salida con error: `{ "error": "..." }`.

## Despliegue (resumen)

1. Crea el repositorio/imagen con estos archivos.
2. En RunPod: **Serverless → New Endpoint**.
3. Elige la GPU (recomendado: **RTX 5090 32 GB**).
4. Worker: sube este `Dockerfile` (GitHub) o una imagen ya construida.
5. Ajusta escalado, idle timeout y concurrencia.
6. Copia el **Endpoint ID** y crea una **API Key**.
7. Pégalos en `appsettings.json` de la app (`RunPod:ApiKey`, `RunPod:EndpointId`).

Los detalles completos están en la conversación de la app.
