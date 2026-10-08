import base64
import glob
import os
import tempfile
import time
import traceback

import runpod

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


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


def handler(event):
    started = time.time()
    inp = (event or {}).get("input") or {}

    audio_b64 = inp.get("audio_base64")
    if not audio_b64:
        return {"error": "Falta 'audio_base64' en la entrada."}

    engine = str(inp.get("engine") or "demucs").lower()
    model = inp.get("model") or "htdemucs"
    preset = bool(inp.get("preset"))
    output_format = inp.get("output_format") or "mp3"
    bitrate = str(inp.get("bitrate") or "320")
    model_dir = os.environ.get("MODEL_DIR", "/models")

    work = tempfile.mkdtemp(prefix="sep_")
    filename = inp.get("filename") or "input.mp3"
    input_path = os.path.join(work, os.path.basename(filename))
    with open(input_path, "wb") as fh:
        fh.write(base64.b64decode(audio_b64))

    output_dir = os.path.join(work, "out")
    os.makedirs(output_dir, exist_ok=True)

    try:
        if engine == "uvr":
            _run_uvr(input_path, output_dir, model, preset, output_format, model_dir)
        else:
            _run_demucs(input_path, output_dir, model, output_format, bitrate)
    except Exception as ex:  # noqa: BLE001 - se reporta al cliente tal cual
        traceback.print_exc()
        return {"error": f"{type(ex).__name__}: {ex}"}

    vocals, instrumental = _find_stems(output_dir)
    if not vocals or not instrumental:
        return {"error": "La separación no generó ambas pistas."}

    with open(vocals, "rb") as fh:
        vocals_b64 = base64.b64encode(fh.read()).decode("ascii")
    with open(instrumental, "rb") as fh:
        instrumental_b64 = base64.b64encode(fh.read()).decode("ascii")

    return {
        "vocals_base64": vocals_b64,
        "instrumental_base64": instrumental_b64,
        "vocals_ext": os.path.splitext(vocals)[1].lower(),
        "instrumental_ext": os.path.splitext(instrumental)[1].lower(),
        "engine": engine,
        "model": model,
        "elapsed_seconds": round(time.time() - started, 2),
    }


runpod.serverless.start({"handler": handler})
