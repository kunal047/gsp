import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from tracking import TrackLifecycle, consensus_plate


def detection(
    track_id, vehicle_type, x, confidence=0.8, color="white",
    plate=None, plate_confidence=None,
):
    return {
        "track_id": track_id,
        "box": (x, 30, x + 50, 90),
        "vehicle_type": vehicle_type,
        "confidence": confidence,
        "color": color,
        "crop": np.full((60, 50, 3), 120, dtype=np.uint8),
        "plate": plate,
        "plate_confidence": plate_confidence,
    }


class TrackLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((180, 320, 3), 80, dtype=np.uint8)
        self.start = datetime(2026, 6, 14, 8, 0, tzinfo=timezone.utc)

    def test_emits_once_with_majority_class_and_annotated_evidence(self):
        lifecycle = TrackLifecycle(min_hits=3, max_misses=2, min_confidence=0.5)
        labels = ["truck", "bus", "bus", "bus"]
        for index, label in enumerate(labels):
            completed = lifecycle.update(
                "cam-1",
                [detection(7, label, 20 + index * 15)],
                self.frame,
                float(index),
                self.start + timedelta(seconds=index),
            )
            self.assertEqual(completed, [])

        self.assertEqual(
            lifecycle.update("cam-1", [], self.frame, 4.0, self.start), []
        )
        completed = lifecycle.update("cam-1", [], self.frame, 5.0, self.start)
        self.assertEqual(len(completed), 1)
        event = completed[0]
        self.assertEqual(event["vehicle_type"], "bus")
        self.assertEqual(event["class_confidence"], 0.75)
        self.assertEqual(event["track_hits"], 4)
        self.assertEqual(event["direction"], "right")
        self.assertIsNotNone(event["crop"])
        self.assertIsNotNone(event["evidence"])
        self.assertGreater(event["evidence"].shape[1], event["crop"].shape[1])
        self.assertEqual(
            lifecycle.update("cam-1", [], self.frame, 6.0, self.start), []
        )

    def test_discards_short_lived_detection(self):
        lifecycle = TrackLifecycle(min_hits=3, max_misses=1, min_confidence=0.5)
        lifecycle.update(
            "cam-1", [detection(9, "car", 20)], self.frame, 0.0, self.start
        )
        completed = lifecycle.update("cam-1", [], self.frame, 1.0, self.start)
        self.assertEqual(completed, [])
        self.assertEqual(lifecycle.states, {})


class PlateConsensusTest(unittest.TestCase):
    def test_rejects_single_low_confidence_false_read(self):
        # The exact false positive that reached production: one 0.30-confidence
        # crop, not a valid Indian plate. Must never be stored.
        from collections import Counter

        plate, conf, agree = consensus_plate(
            Counter({"60J2K647": 1}), {"60J2K647": 0.30}
        )
        self.assertIsNone(plate)

    def test_rejects_noisy_non_repeating_reads(self):
        from collections import Counter

        votes = Counter({"GJ32K1347": 1, "GJ32K7347": 1, "6J32K134": 1})
        plate, _, _ = consensus_plate(votes, {"GJ32K1347": 0.6})
        self.assertIsNone(plate)

    def test_accepts_corroborated_valid_plate(self):
        from collections import Counter

        votes = Counter({"GJ01AB1234": 4, "GJ01AB1284": 1})
        plate, conf, agree = consensus_plate(votes, {"GJ01AB1234": 0.71})
        self.assertEqual(plate, "GJ01AB1234")
        self.assertEqual(agree, 4)

    def test_lifecycle_only_emits_plate_after_consensus(self):
        frame = np.full((180, 320, 3), 80, dtype=np.uint8)
        start = datetime(2026, 6, 14, 8, 0, tzinfo=timezone.utc)
        life = TrackLifecycle(min_hits=3, max_misses=1, min_confidence=0.4)
        # Same valid plate read on 4 frames at good confidence.
        for i in range(4):
            life.update(
                "cam-1",
                [detection(3, "car", 20 + i * 10, plate="GJ01AB1234",
                           plate_confidence=0.7)],
                frame, float(i), start + timedelta(seconds=i),
            )
        done = life.update("cam-1", [], frame, 5.0, start)
        self.assertEqual(done[0]["plate"], "GJ01AB1234")

        # One noisy misread on a single frame -> no plate stored.
        life2 = TrackLifecycle(min_hits=3, max_misses=1, min_confidence=0.4)
        labels = [("car", None, None), ("car", "60J2K647", 0.30),
                  ("car", None, None), ("car", None, None)]
        for i, (vt, pl, pc) in enumerate(labels):
            life2.update(
                "cam-1",
                [detection(5, vt, 20 + i * 10, plate=pl, plate_confidence=pc)],
                frame, float(i), start + timedelta(seconds=i),
            )
        done2 = life2.update("cam-1", [], frame, 5.0, start)
        self.assertIsNone(done2[0]["plate"])


if __name__ == "__main__":
    unittest.main()
