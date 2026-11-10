# Dataset card: KITTI Road and synthetic fixtures

**Update:** the official archives are now available locally, and all 289 labeled images have been imported for the [full run](kitti-full-run.md). The [40-image subset report](kitti-small-run.md) documents verified mapping format, decoded previews, splits and an actual training run. Use `worker.kitti_subset` for direct, selective ZIP extraction. The full-import/manual CSV route below remains available.

## Verified source and label semantics

The [official KITTI Road page](https://www.cvlibs.net/datasets/kitti/eval_road.php) describes 289 labeled training images and 290 test images with withheld ground truth. It separates all-road areas from ego-lane labels and evaluates its official leaderboard in bird's-eye-view space. RoadLab uses RGB left images and **all-road** annotations from the labeled training release. It does not claim official benchmark scores.

Before implementing the adapter, the public [official development-kit archive](https://s3.eu-central-1.amazonaws.com/avg-kitti/devkit_road.zip) was downloaded and inspected. In `python/helper.py`, `load_gt` reads blue > 0 for road and red > 0 for valid area (OpenCV uses BGR). The February 2015 update in `readme.txt` confirms those RGB channels. Pillow reads RGB, so RoadLab uses channel 2 for road and channel 0 for valid pixels.

| RGB example | Meaning |
| --- | --- |
| (255, 0, 255) | valid road |
| (255, 0, 0) | valid non-road |
| (0, 0, 255) | road bit set but ignored: not included in loss or metrics |
| (0, 0, 0) | ignored |

These are semantic examples tested with tiny fixtures, not claimed annotations from downloaded images. The implementation uses the devkit's `>0` checks, not hard-coded color equality. Green is not the road/valid channel.

Inspected archive SHA-256:
`6f7cba10eeeb82d26cb0fa64ea4771ae92ff818be50098b162a21fcab8e06156`

Inspected `helper.py` SHA-256:
`59b00c8b6509f526984a9728b7b7ead89a7b9a1b0f134013fded9ee2138ce164`

Source consulted on November 9, 2026. KITTI's [dataset home page](https://www.cvlibs.net/datasets/kitti/) states CC BY-NC-SA 3.0. Review and comply with the official download terms; source data is not bundled or committed here. Credit the KITTI authors and the [Road benchmark publication](https://www.cvlibs.net/publications/Fritsch2013ITSC.pdf) in work using it.

## Exact remaining download and import steps

1. Log in or register through the official Road page and accept any terms yourself. Download **base kit: left color images, calibration and training labels**, using the revised ground truth. Also download **mapping of training set to raw data sequences**. Do not download or invent test labels.
2. Extract the base kit so that this repository contains `storage/datasets/kitti/data_road/training/image_2` and `training/gt_image_2`.
3. Preserve the original official mapping file/archive. Normalize it to a CSV with header `image,sequence`: one image basename per row, and a sequence identifier that includes the recording date and raw drive ID. Frames belonging to the same raw recording must have the exact same sequence value. Do not use frame number as the group. Validate this normalization against the official mapping before import. This manual normalization route is optional. The supplied official mapping ZIP has now been inspected and is parsed directly by `worker.kitti_subset`; see the subset report.
4. Import using your actual paths:

```sh
.venv/bin/python -m worker.kitti \
  --root storage/datasets/kitti/data_road \
  --mapping storage/datasets/kitti/sequence-map.csv \
  --mapping-source storage/datasets/kitti/official-mapping.zip
```

The adapter hashes both the normalized CSV and original mapping source. It requires complete coverage, unique mapping rows, image/label dimension agreement, RGB label encoding, and exactly 289 images. Pairing is by category and six-digit index: `<category>_<index>.png` maps to `<category>_road_<index>.png`. The `um_lane` annotations are never substituted.

If you genuinely cannot obtain the official mapping, the explicit fallback is:

```sh
.venv/bin/python -m worker.kitti \
  --root storage/datasets/kitti/data_road --allow-ungrouped
```

This records **UNGROUPED: neighboring-frame leakage possible**. It is not evidence of sequence-independent generalization. Prefer obtaining the mapping. Do not silently use this fallback when sequence identity is available.

## Split policy and preprocessing

With mapping: sort sequence IDs, shuffle with Python seed 2026, assign about 70%/15%/15% of groups to train/validation/internal-test, requiring at least one group per split. Image proportions can differ because groups differ in size; the split is not category-stratified. Membership, categories, group IDs, seed, hashes and policy are explicit in the generated registry JSON files. Do not regenerate splits while tuning a model.

Training checks train and validation roles, matching preprocessing, and disjoint image IDs, image hashes and groups. Checkpoint selection uses validation only. The internal test manifest is held out for reporting. A standalone evaluation command can evaluate any registered labeled split; the dashboard intentionally offers validation and internal-test splits.

Current preprocessing deliberately uses a small 128×64 grid to keep CPU experiments readable and fast: RGB bilinear resize, divide values by 255, no additional normalization or augmentation. Masks use **nearest-neighbor** interpolation, preserving discrete labels. Both loss and metrics exclude red-channel-invalid pixels. Direct resizing distorts the original aspect ratio; this is an explicit low-cost baseline, not an optimized KITTI recipe. Changing resolution requires new matching dataset and model manifests/checkpoints; compare only identical preprocessing.

Import writes up to six decoded overlay previews per split into `storage/previews/kitti/`. Inspect them before training: green road should align with pavement, purple denotes ignored area. Actual subset overlays have now been produced and inspected; see `storage/previews/kitti-small-v1/`.

## Synthetic fixture

`python -m worker.fixtures` generates 24 deterministic 128×64 road-like illustrations and masks using seed 2026 plus sample index. Disjoint generated samples: 12 training, 6 validation, 6 internal-test. These are invented illustrations explicitly identified as synthetic; they carry no real driving annotations or weather categories. They use the same RGB mask convention solely to exercise the adapter/evaluation math. A geometric trapezoid predictor intentionally makes errors; an all-background baseline makes no road predictions.

Real-data provenance is not inferred from filenames alone. Every imported image and mask has its own SHA-256; every run snapshots the dataset manifest and stores its digest. Changed files fail evaluation rather than silently changing a historical split.
