# First real KITTI subset — November 9, 2026

The user supplied the official `data_road.zip` (449 MiB on disk) and `devkit_road_mapping.zip`. Neither archive was modified. Only 40 training-release RGB image/all-road-mask pairs were extracted, occupying about 32 MiB. The official benchmark's unlabeled testing images were not extracted.

## Mapping and split verification

The mapping archive contains `training/um_mapping.txt` (95 rows), `umm_mapping.txt` (96), and `uu_mapping.txt` (98). Each row has a raw drive ID and a ten-digit frame number. The importer uses the zero-based row index within each category as the image index and verifies all 289 image names in the base archive against those indices. Source ZIP SHA-256 digests:

- Road archive: `45508c51ba09020235eb714e71c7d3ef15b4551be06d996772ecc8a20fc34a34`
- Mapping archive: `cd75648c0825832c045723ec009386d8495804b5ec1f2b428d2cd61da070fdb6`

Raw drive IDs are grouped globally, including drives appearing in multiple categories. Seed 2026 assigns approximately 70/15/15% of drives to train/validation/internal-test, before selecting a small seeded sample within each partition. Thus increasing the subset later need not move recordings between roles. Full assignments and selected IDs are in `storage/datasets/kitti-small-v1/split-audit.json`; selected membership and image/mask hashes are in the registered manifests.

| Split | Images | Represented drives | Categories |
| --- | ---: | ---: | --- |
| Train | 24 | 16 | 6 um, 12 umm, 6 uu |
| Validation | 8 | 3 | 2 um, 4 umm, 2 uu |
| Internal test | 8 | 3 | 4 um, 0 umm, 4 uu |

An explicit check found no shared drive IDs across splits. The selected internal test lacks umm: no result here establishes performance on all three categories. Mapping filename coverage was checked; raw driving sequences themselves were not downloaded for independent frame-by-frame comparison.

Six decoded training/validation overlays were visually inspected before training. Road regions align with the pavement in those examples; ignored regions are excluded from metrics. See local `storage/previews/kitti-small-v1/contact-sheet.png`. All-road filenames are used, never ego-lane labels. All data and image previews remain Git-ignored.

## Fixed short experiment

Five CPU epochs, seed 2026, batch size 1, Adam learning rate 0.001, 128×64 RGB input. The checkpoint with best validation micro IoU was selected: epoch 5, validation IoU 0.306925. The held-out split was evaluated once after selection. No threshold or hyperparameter was changed based on its result.

| Held-out predictor | Road IoU | Dice | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Small U-Net | 0.246638 | 0.395685 | 0.538957 | 0.312589 |
| All-background | 0 | 0 | undefined | 0 |

These are actual **internal image-space** results, not synthetic scores and not official KITTI leaderboard results. The model misses much of the road (recall about 31%); this is an initial pipeline check, not a strong model. Eight test images and three recordings provide a very limited estimate. Fixed low resolution also distorts aspect ratio.

Evidence: [training log](evidence/kitti-small-training.txt), [U-Net counts and per-image results](evidence/kitti-small-unet.json), [background baseline](evidence/kitti-small-background.json).

## Reproduce with new names

```sh
python -m worker.kitti_subset \
  --road-zip "$HOME/Downloads/data_road.zip" \
  --mapping-zip "$HOME/Downloads/devkit_road_mapping.zip" \
  --name kitti-small-v2 --counts 24 8 8 --seed 2026
python -m worker.train --train kitti-small-v2-train \
  --validation kitti-small-v2-validation --name kitti-small-unet-v2 --epochs 5 --device cpu
python -m worker.evaluate --dataset kitti-small-v2-internal_test \
  --model kitti-small-unet-v2 --out storage/manual/kitti-small-unet-v2
```

Use the project's virtual-environment Python. In this delivered workspace, source `scripts/workspace-env.sh` and substitute `"$PYTHON"` for `python`. Dataset/model names are immutable: choose fresh names for intentional new runs. No additional download is required. The existing manifests and checkpoint are already registered for dashboard evaluations.
