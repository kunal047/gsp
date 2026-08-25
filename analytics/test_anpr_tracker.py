import unittest

import numpy as np

from anpr import parse_bytetrack_rows


class ByteTrackRowContractTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((100, 160, 3), 220, dtype=np.uint8)

    def test_parses_current_ultralytics_row_layout(self):
        # xyxy, track_id, score, class, original detection index
        rows = np.array([[10, 20, 80, 90, 37, 0.876, 5, 2]], dtype=float)
        result = parse_bytetrack_rows(rows, self.frame, {5: "bus"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["track_id"], 37)
        self.assertEqual(result[0]["vehicle_type"], "bus")
        self.assertEqual(result[0]["confidence"], 0.876)
        self.assertEqual(result[0]["box"], (10, 20, 80, 90))

    def test_skips_malformed_unknown_and_empty_boxes(self):
        rows = [
            [1, 2, 3],
            [10, 20, 80, 90, 1, 0.8, 99, 0],
            [50, 50, 50, 80, 2, 0.8, 5, 0],
        ]
        self.assertEqual(parse_bytetrack_rows(rows, self.frame, {5: "bus"}), [])


if __name__ == "__main__":
    unittest.main()
