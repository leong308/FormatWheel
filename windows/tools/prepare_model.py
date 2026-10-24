"""Prepare the pinned cutout model at build time; inference never downloads it."""
from pathlib import Path
import hashlib
import urllib.request

folder = Path(__file__).resolve().parents[1] / ".tools/models"
folder.mkdir(parents=True, exist_ok=True)
target = folder / "u2netp.onnx"
expected = "8e83ca70e441ab06c318d82300c84806"


def verified(path):
    return path.is_file() and hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest() == expected


if not verified(target):
    temporary = target.with_suffix(".download")
    try:
        urllib.request.urlretrieve("https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx", temporary)
        if not verified(temporary):
            raise RuntimeError("Downloaded cutout model failed verification")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
print("Verified local cutout model:", target)
