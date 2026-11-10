"""Freeze one category-covered grouped split using metadata only, never model scores."""

import argparse
from collections import Counter
import copy
import random
from .data import REGISTRY, PREPROCESS, manifest, write_json
from .kitti_subset import ROLES, CATEGORIES


def covered_partition(records, seed=2026, candidates=1000):
    groups = sorted({r["group"] for r in records})
    if len(groups) < 3:
        raise ValueError("at least three groups required")
    ntrain = max(1, min(len(groups) - 2, round(len(groups) * 0.7)))
    nval = max(1, min(len(groups) - ntrain - 1, round(len(groups) * 0.15)))
    totals = Counter(x["category"] for x in records)
    rng = random.Random(seed)
    best = None
    for index in range(candidates):
        shuffled = groups.copy()
        rng.shuffle(shuffled)
        group_sets = (
            set(shuffled[:ntrain]),
            set(shuffled[ntrain : ntrain + nval]),
            set(shuffled[ntrain + nval :]),
        )
        parts = {
            role: [r for r in records if r["group"] in gs]
            for role, gs in zip(ROLES, group_sets)
        }
        counts = {
            role: Counter(r["category"] for r in part) for role, part in parts.items()
        }
        if any(counts[role][cat] == 0 for role in ROLES for cat in CATEGORIES):
            continue
        # Match per-category image proportions; no pixels, losses or predictions enter selection.
        cost = sum(
            (counts[role][cat] / totals[cat] - fraction) ** 2
            for role, fraction in zip(ROLES, (0.7, 0.15, 0.15))
            for cat in CATEGORIES
        )
        if best is None or cost < best[0]:
            best = cost, index, parts
    if best is None:
        raise ValueError(
            "no category-covered group partition found within fixed candidate budget"
        )
    return best[2], {
        "seed": seed,
        "candidates": candidates,
        "chosen_candidate": best[1],
        "metadata_cost": best[0],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="kitti-full-v1")
    p.add_argument("--name", default="kitti-balanced-v2")
    a = p.parse_args()
    import re

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", a.name):
        raise ValueError("invalid name")
    sources = [manifest("datasets", a.source + "-" + role) for role in ROLES]
    records = [x for ds, _ in sources for x in ds["examples"]]
    if len({x["id"] for x in records}) != len(records):
        raise ValueError("duplicate source IDs")
    parts, audit = covered_partition(records)
    prep = {
        **PREPROCESS,
        "height": 128,
        "width": 384,
        "resize_mode": "letterbox",
        "padding": "center; black RGB; invalid label",
    }
    paths = [REGISTRY / "datasets" / f"{a.name}-{role}.json" for role in ROLES]
    baseline = REGISTRY / "models" / f"{a.name}-background.json"
    if any(p.exists() for p in paths + [baseline]):
        raise ValueError("choose an unused benchmark name")
    for role, path in zip(ROLES, paths):
        ds = copy.deepcopy(sources[0][0])
        ds.update(
            name=f"KITTI grouped v2 / {role}",
            role=role,
            preprocessing=prep,
            examples=parts[role],
            split_policy="Category-covered recording groups, metadata-only fixed candidate search",
            split_search=audit,
            source_manifest_sha256={
                r: digest for r, (_, digest) in zip(ROLES, sources)
            },
            evaluation_note="Versioned exploratory internal split; data appeared in earlier experiments. Train fresh models; old checkpoints are not compatible baselines.",
        )
        ds.pop("subset_counts", None)
        write_json(path, ds)
        print(role, len(parts[role]), dict(Counter(x["category"] for x in parts[role])))
    write_json(
        baseline,
        {
            "name": a.name + "-background",
            "kind": "all_background",
            "architecture": "all_background-v1",
            "checkpoint": None,
            "checkpoint_sha256": None,
            "preprocessing": prep,
        },
    )
    print("Fixed split search:", audit)


if __name__ == "__main__":
    main()
