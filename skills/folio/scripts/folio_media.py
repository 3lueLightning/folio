"""Compress and inline media for a folio build.

Images go through Pillow, which is pure Python and works on Windows, macOS and
Linux with no system packages. Video and audio go through ffmpeg when it is
installed; when it is not, the original bytes are embedded and the build warns
about the size instead of failing.

Encoded results are cached in ``.folio-cache`` keyed by the source contents
plus the encoding settings, because re-encoding video on every build makes
iteration painfully slow.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MIME = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
}

DEFAULTS = {
    "image_max_width": 1920,
    "image_quality": 80,
    "video_max_width": 1280,
    "video_crf": 30,
    "audio_bitrate": "128k",
}


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _cache_key(path: Path, settings: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(settings, sort_keys=True).encode())
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:20]


def _run(command: list[str]) -> bool:
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
        )
    except OSError:
        return False
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", "replace")[-800:] + "\n")
        return False
    return True


def _encode_image(source: Path, target: Path, settings: dict[str, Any]) -> Path:
    if source.suffix.lower() == ".svg":
        return source
    try:
        from PIL import Image
    except ImportError:
        return source

    try:
        with Image.open(source) as image:
            if getattr(image, "is_animated", False):
                return source  # animated GIF: leave alone
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            limit = int(settings["image_max_width"])
            if image.width > limit:
                height = round(image.height * limit / image.width)
                image = image.resize((limit, height), Image.LANCZOS)
            target = target.with_suffix(".webp")
            image.save(
                target, "WEBP", quality=int(settings["image_quality"]), method=6
            )
    except Exception as error:  # noqa: BLE001 - never fail a build on one image
        sys.stderr.write(f"  image passthrough ({source.name}): {error}\n")
        return source
    return target if target.stat().st_size < source.stat().st_size else source


def _encode_video(source: Path, target: Path, settings: dict[str, Any]) -> Path:
    if not have_ffmpeg():
        return source
    target = target.with_suffix(".mp4")
    width = int(settings["video_max_width"])
    ok = _run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
            "-vf", f"scale='min({width},iw)':-2",
            "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-crf", str(settings["video_crf"]), "-preset", "slow",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            str(target),
        ]
    )
    if not ok or not target.exists():
        return source
    return target if target.stat().st_size < source.stat().st_size else source


def _encode_audio(source: Path, target: Path, settings: dict[str, Any]) -> Path:
    if not have_ffmpeg():
        return source
    target = target.with_suffix(".mp3")
    ok = _run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
            "-c:a", "libmp3lame", "-b:a", str(settings["audio_bitrate"]),
            str(target),
        ]
    )
    if not ok or not target.exists():
        return source
    return target if target.stat().st_size < source.stat().st_size else source


_PLACEHOLDER = re.compile(r"\{\{asset:([^}]+)\}\}")


def _data_uri(path: Path, settings: dict[str, Any], cache_dir: Path) -> str:
    """Compress one file the same way as page media and return a data: URI."""
    kind = next((k for k, v in _KIND_EXT.items() if path.suffix.lower() in v), "file")
    key = _cache_key(path, {**settings, "kind": kind})
    cached = next(iter(cache_dir.glob(f"{key}.*")), None)
    if cached is None:
        encoder = {"image": _encode_image, "video": _encode_video, "audio": _encode_audio}.get(kind)
        cached = encoder(path, cache_dir / key, settings) if encoder else path
        if cached == path:
            cached = cache_dir / (key + path.suffix.lower())
            shutil.copyfile(path, cached)
    mime = MIME.get(cached.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(cached.read_bytes()).decode("ascii")


_KIND_EXT = {
    "image": {".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".avif"},
    "video": {".mp4", ".webm", ".mov"},
    "audio": {".mp3", ".m4a", ".wav", ".ogg", ".opus"},
}


def inline_widget_assets(
    text: str, base_dir: Path, settings: dict[str, Any], cache_dir: Path, warnings: list[str]
) -> str:
    """Replace {{asset:path}} in a widget with a data: URI of that file."""
    def swap(match: re.Match) -> str:
        ref = match.group(1).strip()
        target = (base_dir / ref).resolve()
        if not target.exists():
            warnings.append(f"widget refers to missing file: {ref}")
            return ""
        return _data_uri(target, settings, cache_dir)

    return _PLACEHOLDER.sub(swap, text)


def process(
    assets: dict[str, dict[str, Any]],
    base_dir: Path,
    settings: dict[str, Any] | None = None,
    cache_dir: Path | None = None,
    verbose: bool = True,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Compress and base64 every asset. Returns (asset map, warnings)."""
    settings = {**DEFAULTS, **(settings or {})}
    cache_dir = cache_dir or (base_dir / ".folio-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    encoders = {"image": _encode_image, "video": _encode_video, "audio": _encode_audio}
    out: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for asset_id, asset in assets.items():
        src = asset["src"]
        kind = asset.get("kind", "file")
        path = (base_dir / src).resolve()

        if not path.exists():
            warnings.append(f"missing media file: {src}")
            out[asset_id] = {"kind": kind, "missing": True, "src": src}
            continue

        if kind == "widget":
            # Widgets are text. They are embedded as written, with no encoding.
            raw_text = path.read_text(encoding="utf-8")
            text = inline_widget_assets(raw_text, base_dir, settings, cache_dir, warnings)
            out[asset_id] = {
                "kind": "widget",
                "src": src,
                "mime": "text/html",
                "bytes": len(text.encode("utf-8")),
                "html": text,
                "scan": raw_text,
            }
            if verbose:
                print(f"  {src:<40} widget, {len(text) / 1e6:>6.2f} MB with its media")
            continue

        original = path.stat().st_size
        key = _cache_key(path, {**settings, "kind": kind})
        cached = next(iter(cache_dir.glob(f"{key}.*")), None)

        if cached is not None:
            final = cached
        else:
            encoder = encoders.get(kind)
            final = path
            if encoder is not None:
                final = encoder(path, cache_dir / key, settings)
            if final == path:
                final = cache_dir / (key + path.suffix.lower())
                shutil.copyfile(path, final)

        data = final.read_bytes()
        mime = MIME.get(final.suffix.lower(), "application/octet-stream")
        out[asset_id] = {
            "kind": kind,
            "src": src,
            "mime": mime,
            "bytes": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }

        if kind in ("video", "audio") and not have_ffmpeg():
            warnings.append(
                f"{src}: ffmpeg not found, embedded uncompressed "
                f"({original / 1e6:.1f} MB)"
            )
        if verbose:
            saved = 100 * (1 - len(data) / original) if original else 0
            print(
                f"  {src:<40} {original / 1e6:>7.2f} MB -> {len(data) / 1e6:>6.2f} MB"
                f"  ({saved:+.0f}%)"
            )

    return out, warnings
