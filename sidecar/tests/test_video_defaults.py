import unittest

from uncloud_engine import video_engine


class VideoQualityDefaultsTest(unittest.TestCase):
    def test_ltx_quality_defaults_do_not_regress_to_draft_settings(self) -> None:
        self.assertEqual((video_engine.DEFAULT_W, video_engine.DEFAULT_H), (960, 544))
        self.assertGreaterEqual(video_engine.DEFAULT_STEPS, 40)
        self.assertEqual(video_engine.DEFAULT_GUIDANCE, 3.0)
        self.assertGreaterEqual(video_engine.DEFAULT_EXPORT_QUALITY, 8.0)
        self.assertIn("inconsistent motion", video_engine.DEFAULT_NEGATIVE_PROMPT)
        self.assertIn("jittery", video_engine.DEFAULT_NEGATIVE_PROMPT)

    def test_default_frame_count_is_valid_for_ltx(self) -> None:
        self.assertEqual(video_engine.valid_frames(video_engine.DEFAULT_FRAMES),
                         video_engine.DEFAULT_FRAMES)


if __name__ == "__main__":
    unittest.main()
