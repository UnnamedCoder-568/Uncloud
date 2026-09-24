import json
import struct

from uncloud_engine.core.models import identify


def test_legacy_kontext_is_identified_without_an_index(tmp_path):
    (tmp_path / "vae").mkdir()
    (tmp_path / "transformer").mkdir()
    (tmp_path / "README.md").write_text(
        "---\nbase_model: black-forest-labs/FLUX.1-Kontext-dev\n---\n"
    )
    header = json.dumps(
        {
            "__metadata__": {"mflux_version": "0.9.6", "quantization_level": "4"},
            "transformer_blocks.0.attn.to_q.weight": {
                "dtype": "U32",
                "shape": [3072, 384],
                "data_offsets": [0, 0],
            },
        }
    ).encode()
    (tmp_path / "transformer/0.safetensors").write_bytes(struct.pack("<Q", len(header)) + header)
    result = identify(tmp_path, sizes=False)
    assert result.layout == "mflux-checkpoint"
    assert result.family == "dev_kontext"
    assert result.quantization == "4bit"


def test_mflux_cli_is_found_beside_runtime_python(tmp_path, monkeypatch):
    import sys

    from uncloud_engine import image_engine

    executable = tmp_path / "bin" / "python"
    executable.parent.mkdir()
    executable.touch()
    command = executable.with_name("mflux-generate-kontext")
    command.touch()
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(image_engine.shutil, "which", lambda name: None)
    assert image_engine._mflux_bin(command.name) == str(command)
