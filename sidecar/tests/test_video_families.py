import unittest

from uncloud_engine import budget, video_engine


class FrameConstraintTest(unittest.TestCase):
    def test_each_family_rounds_to_a_length_it_will_honour(self) -> None:
        # Getting this wrong is silent: the pipeline pads to its own multiple
        # and returns a clip of a length nobody asked for.
        ltx, wan = video_engine.FAMILIES["ltx"], video_engine.FAMILIES["wan"]
        for n in range(9, 258):
            self.assertEqual((video_engine.valid_frames(n, ltx) - 1) % ltx.frame_step, 0)
            self.assertEqual((video_engine.valid_frames(n, wan) - 1) % wan.frame_step, 0)

    def test_a_folder_without_a_marker_is_ltx(self) -> None:
        # Every video model installed before families existed is LTX and has
        # no marker; misreading one as Wan would load the wrong pipeline.
        self.assertEqual(video_engine.family_for("/nonexistent").name, "ltx")


class BudgetTest(unittest.TestCase):
    def test_a_bigger_frame_does_not_cost_more_to_decode(self) -> None:
        # The decode is tiled, so frame size sets how long it takes and not
        # what it costs. Before that it was the peak and it scaled with area,
        # which is what put video out of reach of a 16GB machine.
        small = budget.estimate_video_gb(25, 640, 384, weights_gb=5.4, family="wan")
        native = budget.estimate_video_gb(25, 1280, 704, weights_gb=5.4, family="wan")
        self.assertEqual(small["decode_gb"], native["decode_gb"])

    def test_the_estimate_matches_what_the_job_measured(self) -> None:
        # Two end-to-end runs of this job: 19.31GB decoding whole frames and
        # 10.07GB decoding tiles. The estimate tracks the second.
        est = budget.estimate_video_gb(25, 1280, 704, weights_gb=5.4, family="wan")
        self.assertAlmostEqual(est["total_gb"], 10.07, delta=1.0)

    def test_a_machine_that_fits_only_unusable_sizes_is_not_offered_video(self) -> None:
        # Wan below its native size does not degrade, it returns noise, so
        # "the clip fits" is not enough to put the tab in front of someone.
        # At 9GB a clip fits, but only up to 704x480 — refuse it.
        real = budget.memory_budget
        budget.memory_budget = lambda: {"budget_gb": 9.0}
        try:
            self.assertFalse(budget.video_capability(5.4, "wan")["runnable"])
        finally:
            budget.memory_budget = real

    def test_a_sixteen_gigabyte_machine_now_clears_native_resolution(self) -> None:
        # It did not before the decode was tiled. This is the whole point.
        real = budget.memory_budget
        budget.memory_budget = lambda: {"budget_gb": 11.0}
        try:
            result = budget.video_capability(5.4, "wan")
            self.assertTrue(result["runnable"])
            self.assertEqual(result["largest_size_at_min_frames"], [1280, 704])
        finally:
            budget.memory_budget = real


if __name__ == "__main__":
    unittest.main()


class PlatformTest(unittest.TestCase):
    def test_apple_only_runtimes_are_not_offered_elsewhere(self) -> None:
        # The failure this prevents: a Windows user downloads 13.7GB and gets
        # ModuleNotFoundError on Generate, because mflux never installed.
        real = budget.is_apple_silicon
        budget.is_apple_silicon = lambda: False
        try:
            for engine in ("mflux", "mlx", "mlx-vlm"):
                self.assertFalse(budget.engine_runs_here(engine), engine)
            for engine in ("diffusers", "gguf", "faster-whisper"):
                self.assertTrue(budget.engine_runs_here(engine), engine)
        finally:
            budget.is_apple_silicon = real

    def test_something_is_still_offered_on_a_non_mac(self) -> None:
        # Gating is only correct if it leaves a usable app behind.
        from uncloud_engine.catalog import CATALOG

        real = budget.is_apple_silicon
        budget.is_apple_silicon = lambda: False
        try:
            left = {e.category for e in CATALOG if budget.engine_runs_here(e.engine)}
        finally:
            budget.is_apple_silicon = real
        for category in ("image", "text", "video", "voice-stt"):
            self.assertIn(category, left)
