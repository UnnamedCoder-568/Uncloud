from pathlib import Path

from uncloud_engine.narration_engine import _venv_python


def test_optional_runtime_interpreter_paths_cover_both_desktop_layouts() -> None:
    venv = Path("runtime")
    assert _venv_python(venv, windows=True) == venv / "Scripts" / "python.exe"
    assert _venv_python(venv, windows=False) == venv / "bin" / "python"
