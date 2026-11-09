import argparse
import json
import platform
import os
from pathlib import Path
import numpy as np
from PIL import Image
from .data import (
    METRICS,
    code_hash,
    counts,
    metrics,
    load_example,
    overlay,
    safe_path,
    sha,
    manifest,
    write_json,
)


def predictor(model, prep, device_name):
    kind = model["kind"]
    if kind == "demo":

        def demo(rgb):
            h, w = rgb.shape[:2]
            y, x = np.mgrid[:h, :w]
            return (y >= h * 0.44) & (abs(x - w / 2) < (y - h * 0.28) * 0.9)

        return demo
    if kind == "all_background":
        return lambda rgb: np.zeros(rgb.shape[:2], dtype=bool)
    if kind != "unet":
        raise ValueError("unknown model")
    import torch
    from .model import UNet, ARCHITECTURE, device

    p = safe_path(model["checkpoint"])
    if sha(p) != model["checkpoint_sha256"]:
        raise ValueError("checkpoint hash mismatch")
    checkpoint = torch.load(p, map_location="cpu", weights_only=True)
    if (
        checkpoint["architecture"] != ARCHITECTURE
        or checkpoint["preprocessing"] != prep
    ):
        raise ValueError("checkpoint architecture/preprocessing mismatch")
    dev = device(device_name)
    net = UNet().to(dev)
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()

    def predict(rgb):
        x = (
            torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().unsqueeze(0).to(dev)
            / 255
        )
        with torch.inference_mode():
            return (net(x).sigmoid()[0, 0] >= METRICS["threshold"]).cpu().numpy()

    return predict


def evaluate(spec, out, progress=lambda x: None, device_name="cpu"):
    ds, model = spec["dataset"], spec["model"]
    prep = ds["preprocessing"]
    if model["preprocessing"] != prep:
        raise ValueError("model and dataset preprocessing differ")
    if model["kind"] == "demo" and not ds["synthetic_demo"]:
        raise ValueError("demo predictor only supports synthetic data")
    if not ds["examples"]:
        raise ValueError("empty dataset")
    predict = predictor(model, prep, device_name)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    total = dict(tp=0, fp=0, fn=0, tn=0)
    images = []
    for i, item in enumerate(ds["examples"]):
        rgb, truth, valid = load_example(item, prep)
        pred = predict(rgb)
        c = counts(pred, truth, valid)
        for k in total:
            total[k] += c[k]
        names = {
            view: f"{i:04}_{view}.png"
            for view in (
                "original",
                "ground_truth",
                "prediction",
                "gt_overlay",
                "overlay",
            )
        }
        Image.fromarray(rgb).save(out / names["original"])
        # Gray marks ignored pixels in standalone masks.
        for view, mask in [("ground_truth", truth), ("prediction", pred)]:
            arr = (mask * 255).astype("uint8")
            arr[~valid] = 127
            Image.fromarray(arr).save(out / names[view])
        overlay(rgb, truth, valid).save(out / names["gt_overlay"])
        overlay(rgb, pred, valid).save(out / names["overlay"])
        images.append(
            {"id": item["id"], "counts": c, "metrics": metrics(c), "artifacts": names}
        )
        progress((i + 1) / len(ds["examples"]))
    valid_ious = [
        x["metrics"]["iou"] for x in images if x["metrics"]["iou"] is not None
    ]
    result = {
        "kind": "evaluation",
        "label": (
            "synthetic demo"
            if ds["synthetic_demo"]
            else "internal image-space evaluation"
        ),
        "synthetic_demo": ds["synthetic_demo"],
        "dataset_sha256": spec["dataset_sha256"],
        "metric_config": METRICS,
        "preprocessing": prep,
        "counts": total,
        "metrics": metrics(total),
        "mean_image_iou": float(np.mean(valid_ious)) if valid_ious else None,
        "images": images,
        "worst_ids": [
            x["id"]
            for x in sorted(
                images,
                key=lambda x: (
                    x["metrics"]["iou"] if x["metrics"]["iou"] is not None else 2
                ),
            )[:10]
        ],
        "provenance": {
            "model": model,
            "model_manifest_sha256": spec["model_manifest_sha256"],
            "worker_code_sha256": code_hash(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "device_requested": device_name,
            "dataset": {k: v for k, v in ds.items() if k != "examples"},
        },
    }
    # Flush image bytes before the manifest becomes publishable.
    for image_path in out.glob("*.png"):
        with image_path.open("rb") as f:
            os.fsync(f.fileno())
    write_json(out / "result.json", result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--device", default="cpu")
    a = p.parse_args()
    ds, dh = manifest("datasets", a.dataset)
    m, mh = manifest("models", a.model)
    r = evaluate(
        {"dataset": ds, "model": m, "dataset_sha256": dh, "model_manifest_sha256": mh},
        a.out,
        device_name=a.device,
    )
    print(json.dumps({"label": r["label"], "metrics": r["metrics"]}))


if __name__ == "__main__":
    main()
