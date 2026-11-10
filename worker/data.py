"""Small manifest format shared by fixtures, KITTI, training and evaluation."""

import hashlib
import json
import os
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(os.environ.get("STORAGE_ROOT", "storage")).resolve()
REGISTRY = Path(os.environ.get("REGISTRY_ROOT", "registry"))
PREPROCESS = {
    "height": 64,
    "width": 128,
    "rgb": "uint8/255",
    "image_resize": "bilinear",
    "mask_resize": "nearest",
}
METRICS = {
    "version": "road-micro-v1",
    "threshold": 0.5,
    "space": "resized-image",
    "empty_union": 1,
    "undefined_precision_recall": None,
}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def code_hash():
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def safe_path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("storage path must be relative")
    p = (ROOT / relative).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError("path outside storage root")
    return p


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Artifacts are closed and atomically renamed before their hash is published.
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def manifest(kind, name):
    import re

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        raise ValueError("invalid registry identifier")
    p = REGISTRY / kind / (name + ".json")
    return json.loads(p.read_text()), sha(p)


def decode_mask(rgb):
    """Official devkit load_gt: B>0 is road; R>0 is valid (Pillow RGB order)."""
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] != 3:
        raise ValueError("RGB label expected")
    return a[..., 2] > 0, a[..., 0] > 0


def load_example(item, prep):
    ip, mp = safe_path(item["image"]), safe_path(item["mask"])
    if sha(ip) != item["image_sha256"] or sha(mp) != item["mask_sha256"]:
        raise ValueError("dataset file hash changed")
    with Image.open(ip) as im, Image.open(mp) as mask:
        if im.size != mask.size:
            raise ValueError("image and label dimensions differ")
        rgb, road, valid = preprocess_pair(im, mask, prep)
    return rgb, road, valid


def preprocess_pair(image, mask, prep):
    """Resize identically; letterbox padding has R=0 and is ignored everywhere."""
    if image.size != mask.size:
        raise ValueError("image and label dimensions differ")
    size = (prep["width"], prep["height"])
    if min(size) < 4:
        raise ValueError("preprocessing dimensions must be at least four")
    mode = prep.get("resize_mode", "stretch")
    if mode == "stretch":
        rgb = image.convert("RGB").resize(size, Image.Resampling.BILINEAR)
        label = mask.convert("RGB").resize(size, Image.Resampling.NEAREST)
    elif mode == "letterbox":
        scale = min(size[0] / image.width, size[1] / image.height)
        fitted = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        offset = ((size[0] - fitted[0]) // 2, (size[1] - fitted[1]) // 2)
        rgb = Image.new("RGB", size, (0, 0, 0))
        label = Image.new("RGB", size, (0, 0, 0))
        rgb.paste(
            image.convert("RGB").resize(fitted, Image.Resampling.BILINEAR), offset
        )
        label.paste(
            mask.convert("RGB").resize(fitted, Image.Resampling.NEAREST), offset
        )
    else:
        raise ValueError("unknown resize mode")
    road, valid = decode_mask(label)
    return np.array(rgb), road, valid


def overlay(rgb, road, valid):
    out = rgb.astype(float).copy()
    out[road & valid] = out[road & valid] * 0.45 + np.array([39, 214, 155]) * 0.55
    out[~valid] = out[~valid] * 0.35 + np.array([145, 115, 180]) * 0.65
    return Image.fromarray(out.astype("uint8"))


def counts(pred, truth, valid):
    p, t = pred[valid].astype(bool), truth[valid].astype(bool)
    return dict(
        tp=int((p & t).sum()),
        fp=int((p & ~t).sum()),
        fn=int((~p & t).sum()),
        tn=int((~p & ~t).sum()),
    )


def metrics(c):
    tp, fp, fn, tn = (c[k] for k in ("tp", "fp", "fn", "tn"))
    if tp + fp + fn + tn == 0:
        return dict(iou=None, dice=None, precision=None, recall=None)
    return dict(
        iou=tp / (tp + fp + fn) if tp + fp + fn else 1.0,
        dice=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0,
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
    )
