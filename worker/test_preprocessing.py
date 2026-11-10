import unittest
import numpy as np
from PIL import Image
from .data import preprocess_pair, counts
from .prepare_benchmark import covered_partition


class PreprocessingTests(unittest.TestCase):
    def test_letterbox_ignores_padding_preserves_shape(self):
        rgb, road, valid = preprocess_pair(
            Image.new("RGB", (8, 2), "white"),
            Image.new("RGB", (8, 2), (255, 0, 255)),
            {"width": 16, "height": 8, "resize_mode": "letterbox"},
        )
        self.assertEqual(rgb.shape, (8, 16, 3))
        self.assertEqual(int(valid.sum()), 64)
        self.assertTrue(valid[2:6].all())
        self.assertFalse(valid[:2].any())
        self.assertFalse(valid[6:].any())
        self.assertTrue(road[valid].all())
        self.assertEqual(
            counts(np.ones_like(road), road, valid), dict(tp=64, fp=0, fn=0, tn=0)
        )

    def test_group_coverage_and_determinism(self):
        records = [
            {"id": f"{g}-{c}", "group": str(g), "category": c}
            for g in range(12)
            for c in ("um", "umm", "uu")
        ]
        parts, audit = covered_partition(records, candidates=20)
        self.assertEqual((parts, audit), covered_partition(records, candidates=20))
        groups = [{x["group"] for x in rows} for rows in parts.values()]
        for rows in parts.values():
            self.assertEqual({x["category"] for x in rows}, {"um", "umm", "uu"})
        for i in range(3):
            for j in range(i):
                self.assertFalse(groups[i] & groups[j])
