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
    def test_the_decode_outweighs_the_denoise_at_native_size(self) -> None:
        # The reason quantising the weights does not bring video into range on
        # a small machine: the peak is the decode, and it is not weights.
        est = budget.estimate_video_gb(25, 1280, 704, weights_gb=5.4, family="wan")
        self.assertGreater(est["decode_gb"], est["denoise_gb"])
        self.assertEqual(est["total_gb"], est["decode_gb"])

    def test_a_machine_that_fits_only_unusable_sizes_is_not_offered_video(self) -> None:
        # Wan below its native size does not degrade, it returns noise, so
        # "the clip fits" is not enough to put the tab in front of someone.
        real = budget.memory_budget
        budget.memory_budget = lambda: {"budget_gb": 11.0}
        try:
            self.assertFalse(budget.video_capability(5.4, "wan")["runnable"])
        finally:
            budget.memory_budget = real


if __name__ == "__main__":
    unittest.main()
