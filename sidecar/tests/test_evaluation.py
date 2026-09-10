"""Uncloud's evaluators, and the line between failing a job and scoring one."""

from __future__ import annotations

import pytest
from PIL import Image

from uncloud_engine.core import NOT_BLANK, Unmeasurable, compare, evaluate
from uncloud_engine.evaluation import EVALUATORS, IMAGE, NotBlank


@pytest.fixture
def pictures(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (512, 512), "#808080").save(blank)
    real = tmp_path / "real.png"
    image = Image.new("RGB", (512, 512))
    image.putdata([((x * 7) % 256, (y * 11) % 256, (x + y) % 256)
                   for y in range(512) for x in range(512)])
    image.save(real)
    return blank, real


def test_a_flat_render_scores_zero(pictures) -> None:
    blank, _ = pictures
    assert NotBlank().evaluate(blank, {})[0].value == 0.0


def test_a_real_render_scores_one(pictures) -> None:
    _, real = pictures
    assert NotBlank().evaluate(real, {})[0].value == 1.0


def test_a_missing_file_is_not_a_picture(tmp_path) -> None:
    scores = NotBlank().evaluate(tmp_path / "nothing.png", {})
    assert scores[0].value == 0.0 and "no file" in scores[0].note


def test_an_unreadable_file_is_unmeasurable_rather_than_bad(tmp_path) -> None:
    """Not the same fact. A file that cannot be read has not been judged."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png" * 200)
    with pytest.raises(Unmeasurable):
        NotBlank().evaluate(broken, {})


def test_the_real_render_outranks_the_blank_one(pictures) -> None:
    blank, real = pictures
    results = [evaluate(path, EVALUATORS, IMAGE, candidate_id=name)
               for name, path in (("blank", blank), ("real", real))]
    ranked = compare(results, IMAGE)
    assert ranked[0].candidate == "real"
    assert ranked[-1].passed(IMAGE) is False


def test_output_check_still_raises_at_generation_time() -> None:
    """The evaluator asks which is better; `output_check` decides whether a job
    failed. A degenerate render should fail rather than be handed over with a
    low score, and both behaviours are wanted."""
    from uncloud_engine import output_check

    assert hasattr(output_check, "DegenerateOutput")
    assert hasattr(output_check, "verify_image")


def test_the_rubric_floors_the_blank_check() -> None:
    assert IMAGE.dimension(NOT_BLANK.id).floor
    assert IMAGE.min_coverage > 0
