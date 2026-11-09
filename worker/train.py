import argparse
import random
import numpy as np
import torch
from torch.nn import functional as F
from .data import (
    REGISTRY,
    code_hash,
    counts,
    metrics,
    manifest,
    load_example,
    safe_path,
    sha,
    write_json,
)
from .model import UNet, ARCHITECTURE, device


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True)
    p.add_argument("--validation", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--device", default="cpu")
    a = p.parse_args()
    import re

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", a.name) or a.epochs < 1:
        raise ValueError("invalid name or epochs")
    train, th = manifest("datasets", a.train)
    val, vh = manifest("datasets", a.validation)
    if train["role"] != "train" or val["role"] != "validation":
        raise ValueError(
            "train and validation roles required; never select on internal_test"
        )
    if train["preprocessing"] != val["preprocessing"]:
        raise ValueError("preprocessing mismatch")
    for field in ("id", "image_sha256", "group"):
        if {x[field] for x in train["examples"]} & {x[field] for x in val["examples"]}:
            raise ValueError("split leakage: " + field)
    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    dev = device(a.device)
    net = UNet().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=0.001)
    prep = train["preprocessing"]
    train_data = [load_example(x, prep) for x in train["examples"]]
    val_data = [load_example(x, prep) for x in val["examples"]]
    if not train_data or not val_data:
        raise ValueError("empty split")
    target = safe_path("checkpoints/" + a.name + ".pt")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError("choose a new immutable model name")
    best = -1.0
    history = []

    def tensors(row):
        rgb, truth, valid = row
        return (
            torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().unsqueeze(0).to(dev)
            / 255,
            torch.from_numpy(truth.copy()).float()[None, None].to(dev),
            torch.from_numpy(valid.copy())[None, None].to(dev),
        )

    for epoch in range(a.epochs):
        net.train()
        losses = []
        for index in np.random.permutation(len(train_data)):
            x, y, v = tensors(train_data[index])
            if not v.any():
                continue
            opt.zero_grad()
            loss = F.binary_cross_entropy_with_logits(net(x), y, reduction="none")[
                v
            ].mean()
            loss.backward()
            opt.step()
            losses.append(float(loss.detach().cpu()))
        net.eval()
        total = dict(tp=0, fp=0, fn=0, tn=0)
        with torch.inference_mode():
            for row in val_data:
                x, _, _ = tensors(row)
                pred = (net(x).sigmoid()[0, 0] >= 0.5).cpu().numpy()
                c = counts(pred, row[1], row[2])
                for k in total:
                    total[k] += c[k]
        score = metrics(total)["iou"]
        if score is None:
            raise ValueError("validation contains no valid pixels")
        report = {
            "epoch": epoch + 1,
            "train_loss": float(np.mean(losses)) if losses else None,
            "validation_iou": score,
        }
        history.append(report)
        print(report, flush=True)
        if score > best:
            best = score
            torch.save(
                {
                    "state_dict": net.cpu().state_dict(),
                    "architecture": ARCHITECTURE,
                    "preprocessing": prep,
                    "seed": a.seed,
                    "epoch": epoch + 1,
                    "validation_iou": score,
                    "train_sha256": th,
                    "validation_sha256": vh,
                    "code_sha256": code_hash(),
                },
                target,
            )
            net.to(dev)
    write_json(
        REGISTRY / "models" / (a.name + ".json"),
        {
            "name": a.name,
            "kind": "unet",
            "architecture": ARCHITECTURE,
            "checkpoint": str(target.relative_to(safe_path("."))),
            "checkpoint_sha256": sha(target),
            "preprocessing": prep,
            "training": {
                "train_sha256": th,
                "validation_sha256": vh,
                "seed": a.seed,
                "epochs": a.epochs,
                "lr": 0.001,
                "batch_size": 1,
                "device": str(dev),
                "history": history,
                "synthetic_demo": train["synthetic_demo"],
                "code_sha256": code_hash(),
                "torch": str(torch.__version__),
            },
        },
    )


if __name__ == "__main__":
    main()
