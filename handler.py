import glob
import os
import shutil
import subprocess
import tempfile
import time
import traceback

import runpod

# El Network Volume se monta aquí dentro del worker Serverless.
VOLUME_PATH = os.environ.get("VOLUME_PATH", "/runpod-volume")
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


# ---------------------------------------------------------------------------
# Separación de pistas (Demucs / UVR)
# ---------------------------------------------------------------------------

def _classify(path):
    """Devuelve (es_voz, es_instrumental) a partir del nombre del archivo."""
    name = os.path.basename(path).lower()
    is_instrumental = (
        "instrument" in name or "no_vocal" in name or "accompaniment" in name
    )
    is_vocals = "vocal" in name and not is_instrumental and not name.startswith("no_")
    return is_vocals, is_instrumental


def _find_stems(directory):
    vocals = None
    instrumental = None
    for path in glob.glob(os.path.join(directory, "**", "*"), recursive=True):
        if not os.path.isfile(path):
            continue
        if os.path.splitext(path)[1].lower() not in AUDIO_EXTS:
            continue
        is_vocals, is_instrumental = _classify(path)
        if is_vocals and vocals is None:
            vocals = path
        elif is_instrumental and instrumental is None:
            instrumental = path
    return vocals, instrumental


def _run_demucs(input_path, output_dir, model, output_format, bitrate):
    import demucs.separate

    argv = ["--two-stems", "vocals", "-n", model, "-o", output_dir, "-d", "cuda"]

    fmt = (output_format or "mp3").lower()
    if fmt == "mp3":
        argv += ["--mp3", "--mp3-bitrate", str(bitrate or "320")]
    elif fmt == "flac":
        argv += ["--flac"]

    argv.append(input_path)
    demucs.separate.main(argv)


def _run_uvr(input_path, output_dir, model, preset, output_format, model_dir):
    from audio_separator.separator import Separator

    kwargs = {
        "output_dir": output_dir,
        "output_format": (output_format or "mp3").upper(),
    }
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
        kwargs["model_file_dir"] = model_dir

    if preset:
        try:
            separator = Separator(**{**kwargs, "ensemble_preset": model})
        except TypeError:
            separator = Separator(**kwargs)
        separator.load_model()
    else:
        separator = Separator(**kwargs)
        separator.load_model(model_filename=model)

    separator.separate(
        input_path, {"Vocals": "vocals", "Instrumental": "instrumental"}
    )


def _separate(inp, started):
    input_key = inp.get("input_key")
    if not input_key:
        return {"error": "Falta 'input_key' en la entrada."}

    output_prefix = (inp.get("output_prefix") or os.path.dirname(input_key)).strip("/")
    engine = str(inp.get("engine") or "demucs").lower()
    model = inp.get("model") or "htdemucs"
    preset = bool(inp.get("preset"))
    output_format = inp.get("output_format") or "mp3"
    bitrate = str(inp.get("bitrate") or "320")
    model_dir = os.environ.get("MODEL_DIR", os.path.join(VOLUME_PATH, "models"))

    source = os.path.join(VOLUME_PATH, input_key.lstrip("/"))
    if not os.path.isfile(source):
        return {"error": f"No existe el archivo de entrada en el volumen: {input_key}"}

    work = tempfile.mkdtemp(prefix="sep_")
    local_input = os.path.join(work, os.path.basename(input_key))
    shutil.copyfile(source, local_input)

    output_dir = os.path.join(work, "out")
    os.makedirs(output_dir, exist_ok=True)

    try:
        if engine == "uvr":
            _run_uvr(local_input, output_dir, model, preset, output_format, model_dir)
        else:
            _run_demucs(local_input, output_dir, model, output_format, bitrate)
    except Exception as ex:  # noqa: BLE001 - se reporta al cliente tal cual
        traceback.print_exc()
        return {"error": f"{type(ex).__name__}: {ex}"}

    vocals, instrumental = _find_stems(output_dir)
    if not vocals or not instrumental:
        return {"error": "La separación no generó ambas pistas."}

    volume_output = os.path.join(VOLUME_PATH, output_prefix)
    os.makedirs(volume_output, exist_ok=True)

    vocals_ext = os.path.splitext(vocals)[1].lower()
    instrumental_ext = os.path.splitext(instrumental)[1].lower()
    vocals_key = f"{output_prefix}/vocals{vocals_ext}"
    instrumental_key = f"{output_prefix}/instrumental{instrumental_ext}"

    shutil.copyfile(vocals, os.path.join(VOLUME_PATH, vocals_key))
    shutil.copyfile(instrumental, os.path.join(VOLUME_PATH, instrumental_key))

    return {
        "vocals_key": vocals_key,
        "instrumental_key": instrumental_key,
        "vocals_ext": vocals_ext,
        "instrumental_ext": instrumental_ext,
        "engine": engine,
        "model": model,
        "elapsed_seconds": round(time.time() - started, 2),
    }


# ---------------------------------------------------------------------------
# Render del video karaoke (ffmpeg)
# ---------------------------------------------------------------------------

def _render(inp, started):
    workdir = str(inp.get("workdir") or "").strip("/")
    args = inp.get("args")
    output_name = os.path.basename(str(inp.get("output") or "karaoke.mp4"))

    if not workdir or not isinstance(args, list) or not args:
        return {"error": "Faltan 'workdir' o 'args' para el render."}

    cwd = os.path.join(VOLUME_PATH, workdir)
    if not os.path.isdir(cwd):
        return {"error": f"No existe el directorio de trabajo en el volumen: {workdir}"}

    if shutil.which("ffmpeg") is None:
        return {"error": "ffmpeg no está disponible en el worker."}

    try:
        proc = subprocess.run(
            ["ffmpeg", *[str(a) for a in args]],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except Exception as ex:  # noqa: BLE001
        traceback.print_exc()
        return {"error": f"{type(ex).__name__}: {ex}"}

    if proc.returncode != 0:
        return {"error": f"ffmpeg falló (código {proc.returncode}): {proc.stderr[-1500:]}"}

    video_path = os.path.join(cwd, output_name)
    if not os.path.isfile(video_path):
        return {"error": "ffmpeg terminó pero no generó el video."}

    return {
        "video_key": f"{workdir}/{output_name}",
        "elapsed_seconds": round(time.time() - started, 2),
    }


def handler(event):
    started = time.time()
    inp = (event or {}).get("input") or {}
    task = str(inp.get("task") or "separate").lower()

    if task == "render":
        return _render(inp, started)

    return _separate(inp, started)


runpod.serverless.start({"handler": handler})
