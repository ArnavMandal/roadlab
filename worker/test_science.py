import unittest
import numpy as np
from PIL import Image
from .data import decode_mask, counts, metrics


class ScienceTests(unittest.TestCase):
    def test_official_rgb_decoding(self):
        pixels = np.array(
            [[[255, 0, 255], [255, 0, 0], [0, 0, 255], [0, 0, 0]]], dtype="uint8"
        )
        road, valid = decode_mask(pixels)
        np.testing.assert_array_equal(road, [[1, 0, 1, 0]])
        np.testing.assert_array_equal(valid, [[1, 1, 0, 0]])
        self.assertEqual(
            counts(np.array([[1, 1, 0, 1]], bool), road, valid),
            dict(tp=1, fp=1, fn=0, tn=0),
        )

    def test_metrics_and_empty_cases(self):
        m = metrics(dict(tp=2, fp=1, fn=1, tn=100))
        self.assertEqual(m, dict(iou=0.5, dice=2 / 3, precision=2 / 3, recall=2 / 3))
        self.assertEqual(
            metrics(dict(tp=0, fp=0, fn=0, tn=10)),
            dict(iou=1.0, dice=1.0, precision=None, recall=None),
        )
        self.assertTrue(
            all(v is None for v in metrics(dict(tp=0, fp=0, fn=0, tn=0)).values())
        )
        self.assertEqual(metrics(dict(tp=0, fp=0, fn=3, tn=0))["iou"], 0)

    def test_nearest_preserves_label_values(self):
        im = Image.fromarray(
            np.array([[[255, 0, 255], [0, 0, 0]]], dtype="uint8")
        ).resize((9, 4), Image.Resampling.NEAREST)
        self.assertEqual(set(np.unique(np.asarray(im)).tolist()), {0, 255})

    def test_unet_shape_and_gradient(self):
        import torch
        from .model import UNet

        net = UNet()
        x = torch.randn(2, 3, 17, 31)
        out = net(x)
        self.assertEqual(tuple(out.shape), (2, 1, 17, 31))
        out.square().mean().backward()
        self.assertIsNotNone(net.head.weight.grad)


if __name__ == "__main__":
    unittest.main()
