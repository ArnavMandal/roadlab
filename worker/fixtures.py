"""Generate deterministic illustrations, never evidence of driving performance."""

from PIL import Image, ImageDraw
import numpy as np
from .data import ROOT, REGISTRY, PREPROCESS, sha, write_json


def main():
    entries = []
    for i in range(24):
        rng = np.random.default_rng(2026 + i)
        a = np.zeros((64, 128, 3), dtype=np.uint8)
        a[:] = [114, 167, 189]
        a[24:] = [77, 110, 82]
        a = np.clip(a.astype(int) + rng.integers(-8, 9, a.shape), 0, 255).astype(
            "uint8"
        )
        im = Image.fromarray(a)
        mask = Image.new("RGB", im.size, (255, 0, 0))
        shift = (i % 7 - 3) * 3
        polygon = [
            (58 + shift, 26),
            (70 + shift, 26),
            (120 + shift, 63),
            (8 + shift, 63),
        ]
        ImageDraw.Draw(im).polygon(polygon, fill=(73 + i % 4 * 4, 76, 78))
        ImageDraw.Draw(im).line(
            [(64 + shift, 33), (64 + shift, 63)], fill=(221, 206, 137), width=2
        )
        ImageDraw.Draw(mask).polygon(polygon, fill=(255, 0, 255))
        ImageDraw.Draw(mask).rectangle((0, 0, 127, 5), fill=(0, 0, 0))
        base = ROOT / "datasets" / "synthetic" / f"frame_{i:03}"
        base.parent.mkdir(parents=True, exist_ok=True)
        ip, mp = base.with_suffix(".png"), base.with_name(base.name + "_road.png")
        im.save(ip)
        mask.save(mp)
        entries.append(
            {
                "id": f"synthetic_{i:03}",
                "group": f"generated_{i:03}",
                "image": str(ip.relative_to(ROOT)),
                "mask": str(mp.relative_to(ROOT)),
                "image_sha256": sha(ip),
                "mask_sha256": sha(mp),
            }
        )
    for role, items in [
        ("train", entries[:12]),
        ("validation", entries[12:18]),
        ("internal_test", entries[18:]),
    ]:
        write_json(
            REGISTRY / "datasets" / f"synthetic-{role}.json",
            {
                "name": f"Synthetic / {role}",
                "role": role,
                "synthetic_demo": True,
                "provenance": "RoadLab procedural fixture seed 2026; not driving data",
                "license": "project-generated fixture",
                "preprocessing": PREPROCESS,
                "split_policy": "disjoint generated sample IDs",
                "examples": items,
            },
        )
    for name, kind in [("demo", "demo"), ("all-background", "all_background")]:
        write_json(
            REGISTRY / "models" / f"{name}.json",
            {
                "name": name,
                "kind": kind,
                "architecture": kind + "-v1",
                "checkpoint": None,
                "checkpoint_sha256": None,
                "preprocessing": PREPROCESS,
            },
        )
    print("Created 24 synthetic demo images and three disjoint manifests.")


if __name__ == "__main__":
    main()
