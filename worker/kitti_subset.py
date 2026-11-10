"""Extract a small, sequence-separated subset from the official KITTI ZIPs."""

import argparse
from collections import Counter
import hashlib
import io
from PIL import Image
import random
import re
import zipfile
from .data import ROOT, REGISTRY, PREPROCESS, sha, write_json, load_example, overlay

CATEGORIES = {"um": 95, "umm": 96, "uu": 98}
ROLES = ("train", "validation", "internal_test")


def read_mapping(archive):
    records = []
    for category, count in CATEGORIES.items():
        lines = (
            archive.read(f"training/{category}_mapping.txt")
            .decode("utf-8")
            .splitlines()
        )
        if len(lines) != count:
            raise ValueError(f"expected {count} mapping rows for {category}")
        for index, line in enumerate(lines):
            fields = line.split()
            if (
                len(fields) != 2
                or not re.fullmatch(r"\d{4}_\d{2}_\d{2}_drive_\d{4}", fields[0])
                or not re.fullmatch(r"\d{10}", fields[1])
            ):
                raise ValueError(f"invalid mapping row: {category} {index}")
            records.append(
                {
                    "id": f"{category}_{index:06d}",
                    "category": category,
                    "group": fields[0],
                    "raw_frame": fields[1],
                }
            )
    return records


def partition(records, seed):
    # Group globally: the same drive can occur in several road categories.
    groups = sorted({r["group"] for r in records})
    if len(groups) < 3:
        raise ValueError("at least three recordings are required")
    random.Random(seed).shuffle(groups)
    ntrain = max(1, min(len(groups) - 2, round(len(groups) * 0.7)))
    nval = max(1, min(len(groups) - ntrain - 1, round(len(groups) * 0.15)))
    assigned = dict(
        zip(
            ROLES,
            (groups[:ntrain], groups[ntrain : ntrain + nval], groups[ntrain + nval :]),
        )
    )
    return {
        role: [r for r in records if r["group"] in assigned[role]] for role in ROLES
    }


def select_subset(partitions, limits, seed):
    selected = {}
    for offset, (role, limit) in enumerate(zip(ROLES, limits)):
        pool = list(partitions[role])
        if limit < 1 or len(pool) < limit:
            raise ValueError(f"{role}: requested {limit}, available {len(pool)}")
        random.Random(seed + 100 + offset).shuffle(pool)
        selected[role] = sorted(pool[:limit], key=lambda r: r["id"])
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--road-zip", required=True)
    p.add_argument("--mapping-zip", required=True)
    p.add_argument(
        "--counts",
        nargs=3,
        type=int,
        default=[24, 8, 8],
        metavar=("TRAIN", "VAL", "TEST"),
    )
    p.add_argument("--name", default="kitti-small-v1")
    p.add_argument("--seed", type=int, default=2026)
    a = p.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", a.name):
        raise ValueError("invalid dataset name")
    for role in ROLES:
        if (REGISTRY / "datasets" / f"{a.name}-{role}.json").exists():
            raise ValueError("choose a new dataset name; existing splits are immutable")
    with zipfile.ZipFile(a.mapping_zip) as mapping_zip:
        records = read_mapping(mapping_zip)
    partitions = partition(records, a.seed)
    selected = select_subset(partitions, a.counts, a.seed)
    provenance = {
        "road_archive_sha256": sha(a.road_zip),
        "mapping_archive_sha256": sha(a.mapping_zip),
        "mapping_convention": "zero-based row i of category_mapping.txt corresponds to category_i.png; fields are raw drive and frame",
    }
    base = ROOT / "datasets" / a.name
    preview = ROOT / "previews" / a.name
    preview.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(a.road_zip) as road_zip:
        names = set(road_zip.namelist())
        # Verify full filename/index coverage without extracting the full dataset.
        expected = {f"data_road/training/image_2/{r['id']}.png" for r in records}
        actual = {
            n
            for n in names
            if re.fullmatch(r"data_road/training/image_2/(um|umm|uu)_\d{6}\.png", n)
        }
        if expected != actual:
            raise ValueError("archive image indices do not match official mapping rows")
        for role in ROLES:
            examples = []
            for record in selected[role]:
                record = dict(record)
                category, index = record["id"].rsplit("_", 1)
                for kind, folder, basename in (
                    ("image", "image_2", record["id"]),
                    ("mask", "gt_image_2", f"{category}_road_{index}"),
                ):
                    member = f"data_road/training/{folder}/{basename}.png"
                    data = road_zip.read(member)
                    if kind == "mask":
                        with Image.open(io.BytesIO(data)) as mask:
                            if mask.mode != "RGB":
                                raise ValueError("expected RGB all-road label")
                    target = base / folder / f"{basename}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    record[kind] = str(target.relative_to(ROOT))
                    record[kind + "_sha256"] = hashlib.sha256(data).hexdigest()
                rgb, truth, valid = load_example(record, PREPROCESS)
                if not valid.any():
                    raise ValueError("sample has no valid evaluation pixels")
                examples.append(record)
                overlay(rgb, truth, valid).save(preview / f"{record['id']}.png")
            ds = {
                "name": f"{a.name} / {role}",
                "role": role,
                "synthetic_demo": False,
                "provenance": "Official KITTI Road labeled training archive; all-road RGB labels",
                **provenance,
                "license": "CC BY-NC-SA 3.0; KITTI authors",
                "source": "https://www.cvlibs.net/datasets/kitti/eval_road.php",
                "seed": a.seed,
                "preprocessing": PREPROCESS,
                "split_policy": "Globally partition raw drives 70/15/15, then seeded sample within each split; no recording crosses splits",
                "subset_counts": dict(zip(ROLES, a.counts)),
                "examples": examples,
            }
            write_json(REGISTRY / "datasets" / f"{a.name}-{role}.json", ds)
            print(
                role,
                len(examples),
                "images",
                len({x["group"] for x in examples}),
                "recordings",
                dict(Counter(x["category"] for x in examples)),
            )
    write_json(
        base / "split-audit.json",
        {
            **provenance,
            "seed": a.seed,
            "full_partition": partitions,
            "selected_ids": {k: [r["id"] for r in v] for k, v in selected.items()},
        },
    )
    print("Decoded overlays:", preview)


if __name__ == "__main__":
    main()
