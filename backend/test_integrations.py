import unittest
from types import SimpleNamespace

from app.integrations import _wl_matches


class WatchlistGateTest(unittest.TestCase):
    def attribute_item(self, **overrides):
        values = {
            "kind": "attribute",
            "vehicle_type": "truck",
            "color": "white",
            "min_track_hits": 4,
            "min_confidence": 0.72,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def detection(self, **overrides):
        values = {
            "track_hits": 4,
            "vehicle_type": "truck",
            "color": "white",
            "confidence": 0.9,
            "class_confidence": 1.0,
            "color_confidence": 1.0,
            "plate_norm": None,
            "plate_confidence": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_attribute_match_requires_track_persistence(self):
        self.assertIsNone(
            _wl_matches(self.attribute_item(), self.detection(track_hits=2))
        )

    def test_heavy_vehicle_match_rejects_unstable_classification(self):
        self.assertIsNone(
            _wl_matches(
                self.attribute_item(), self.detection(class_confidence=0.75)
            )
        )

    def test_stable_attribute_match_returns_bounded_confidence(self):
        self.assertEqual(
            _wl_matches(self.attribute_item(), self.detection()),
            ("attribute", 0.9),
        )

    def test_plate_match_requires_ocr_confidence(self):
        item = SimpleNamespace(
            kind="plate",
            plate_norm="GJ01AB1234",
            min_track_hits=3,
            min_confidence=0.55,
        )
        det = self.detection(
            track_hits=3,
            plate_norm="GJ01AB1234",
            plate_confidence=0.4,
        )
        self.assertIsNone(_wl_matches(item, det))


if __name__ == "__main__":
    unittest.main()
