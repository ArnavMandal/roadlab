"""Import labeled KITTI Road only, using verified devkit RGB channel semantics."""

import argparse
import csv
import random
import re
from pathlib import Path
from PIL import Image
from .data import ROOT, REGISTRY, PREPROCESS, sha, write_json, load_example, overlay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--root", required=True, help="extracted data_road directory INSIDE storage/"
    )
    p.add_argument(
        "--mapping", help="normalized official mapping CSV with image,sequence columns"
    )
    p.add_argument(
        "--mapping-source", help="original official mapping archive/file for provenance"
    )
    p.add_argument(
        "--allow-ungrouped",
        action="store_true",
        help="explicitly accept possible neighboring-frame leakage",
    )
    p.add_argument("--seed", type=int, default=2026)
    a = p.parse_args()
    root = Path(a.root).resolve()
    if not root.is_relative_to(ROOT):
        raise ValueError("dataset must be inside STORAGE_ROOT")
    mapping = {}
    if a.mapping:
        if not a.mapping_source:
            raise ValueError("--mapping-source required to retain official source hash")
        with open(a.mapping, newline="") as f:
            for row in csv.DictReader(f):
                name = row["image"]
                seq = row["sequence"]
                if name in mapping or not seq:
                    raise ValueError("duplicate image or missing sequence")
                mapping[name] = seq
    elif not a.allow_ungrouped:
        raise ValueError(
            "provide official sequence mapping or explicitly --allow-ungrouped"
        )
    items = []
    for ip in sorted((root / "training" / "image_2").glob("*.png")):
        match = re.fullmatch(r"(um|umm|uu)_(\d{6})\.png", ip.name)
        if not match:
            raise ValueError("unexpected image name: " + ip.name)
        category, index = match.groups()
        mp = root / "training" / "gt_image_2" / f"{category}_road_{index}.png"
        if not mp.is_file():
            raise ValueError("missing all-road label: " + str(mp))
        with Image.open(ip) as image, Image.open(mp) as mask:
            if image.size != mask.size or mask.mode != "RGB":
                raise ValueError("unexpected label size/encoding")
        if mapping and ip.name not in mapping:
            raise ValueError("mapping missing " + ip.name)
        items.append(
            {
                "id": ip.stem,
                "category": category,
                "group": mapping.get(ip.name, ip.stem),
                "image": str(ip.relative_to(ROOT)),
                "mask": str(mp.relative_to(ROOT)),
                "image_sha256": sha(ip),
                "mask_sha256": sha(mp),
            }
        )
    if len(items) != 289:
        raise ValueError(
            f"expected complete labeled release (289 images), found {len(items)}"
        )
    groups = sorted({x["group"] for x in items})
    random.Random(a.seed).shuffle(groups)
    if len(groups) < 3:
        raise ValueError("at least 3 groups needed for three disjoint splits")
    n = len(groups)
    ntrain = max(1, min(n - 2, round(n * 0.7)))
    nval = max(1, min(n - ntrain - 1, round(n * 0.15)))
    splits = {
        "train": set(groups[:ntrain]),
        "validation": set(groups[ntrain : ntrain + nval]),
        "internal_test": set(groups[ntrain + nval :]),
    }
    preview = ROOT / "previews" / "kitti"
    preview.mkdir(parents=True, exist_ok=True)
    for role, group_set in splits.items():
        selected = [x for x in items if x["group"] in group_set]
        ds = {
            "name": "KITTI Road / " + role,
            "role": role,
            "synthetic_demo": False,
            "provenance": "KITTI Road 2015 revised labeled training release; RGB all-road only",
            "license": "CC BY-NC-SA 3.0; see official dataset terms",
            "source": "https://www.cvlibs.net/datasets/kitti/eval_road.php",
            "seed": a.seed,
            "preprocessing": PREPROCESS,
            "split_policy": (
                "official raw-sequence groups"
                if mapping
                else "UNGROUPED: neighboring-frame leakage possible; no sequence-independence claim"
            ),
            "mapping_sha256": sha(a.mapping) if mapping else None,
            "mapping_source_sha256": sha(a.mapping_source) if mapping else None,
            "examples": selected,
        }
        write_json(REGISTRY / "datasets" / f"kitti-{role}.json", ds)
        for item in selected[:6]:
            rgb, road, valid = load_example(item, PREPROCESS)
            overlay(rgb, road, valid).save(preview / (item["id"] + ".png"))
        print(role, len(selected), "images", len(group_set), "groups")
    print(
        "Inspect decoded overlays in",
        preview,
        "before training. Green=road; purple=ignored.",
    )


if __name__ == "__main__":
    main()
