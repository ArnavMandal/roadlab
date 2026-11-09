"""Two-level U-Net: [N,3,H,W] RGB -> [N,1,H,W] binary logits."""

import torch
from torch import nn
from torch.nn import functional as F

ARCHITECTURE = "tiny-unet-v1-width8"


class Block(nn.Sequential):
    def __init__(self, cin, cout):
        super().__init__(
            nn.Conv2d(cin, cout, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(cout, cout, 3, padding=1),
            nn.ReLU(),
        )


class UNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.enc1 = Block(3, 8)
        self.enc2 = Block(8, 16)
        self.bridge = Block(16, 32)
        self.dec2 = Block(48, 16)
        self.dec1 = Block(24, 8)
        self.head = nn.Conv2d(8, 1, 1)

    def forward(self, x):
        a = self.enc1(x)
        b = self.enc2(F.max_pool2d(a, 2))
        c = self.bridge(F.max_pool2d(b, 2))
        d = self.dec2(
            torch.cat(
                [
                    F.interpolate(
                        c, size=b.shape[-2:], mode="bilinear", align_corners=False
                    ),
                    b,
                ],
                1,
            )
        )
        return self.head(
            self.dec1(
                torch.cat(
                    [
                        F.interpolate(
                            d, size=a.shape[-2:], mode="bilinear", align_corners=False
                        ),
                        a,
                    ],
                    1,
                )
            )
        )


def device(name="cpu"):
    if name == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(name)
