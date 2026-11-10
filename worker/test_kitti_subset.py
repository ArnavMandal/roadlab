import unittest
from .kitti_subset import CATEGORIES, read_mapping, partition, select_subset


class SubsetTests(unittest.TestCase):
    def test_mapping_rows_follow_category_indices(self):
        class Archive:
            def read(self, name):
                category = name.split("/")[-1].split("_")[0]
                return "".join(
                    f"2011_09_26_drive_0002 {i:010d}\n"
                    for i in range(CATEGORIES[category])
                ).encode()

        rows = read_mapping(Archive())
        self.assertEqual(len(rows), 289)
        self.assertEqual(rows[0]["id"], "um_000000")
        self.assertEqual(rows[94]["id"], "um_000094")
        self.assertEqual(rows[95]["id"], "umm_000000")
        self.assertEqual(rows[-1]["id"], "uu_000097")
        self.assertEqual(rows[-1]["raw_frame"], "0000000097")

    def test_recordings_remain_disjoint_across_categories(self):
        records = [
            {
                "id": f"{category}_{i:06d}",
                "group": f"drive-{i // 3}",
                "category": category,
            }
            for category in ("um", "umm", "uu")
            for i in range(30)
        ]
        parts = partition(records, 2026)
        self.assertEqual(sum(map(len, parts.values())), len(records))
        groups = [{r["group"] for r in part} for part in parts.values()]
        for i in range(3):
            for j in range(i):
                self.assertFalse(groups[i] & groups[j])
        subset = select_subset(parts, [12, 3, 3], 2026)
        self.assertEqual([len(x) for x in subset.values()], [12, 3, 3])
        self.assertEqual(subset, select_subset(parts, [12, 3, 3], 2026))
        for role in parts:
            self.assertTrue(all(x in parts[role] for x in subset[role]))

    def test_unavailable_sample_count_rejected(self):
        with self.assertRaises(ValueError):
            select_subset(
                {r: [] for r in ("train", "validation", "internal_test")},
                [1, 1, 1],
                2026,
            )
