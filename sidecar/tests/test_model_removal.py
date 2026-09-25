from pathlib import Path

import pytest
from fastapi import HTTPException

from uncloud_engine import config, library, main


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'settings.json')
    monkeypatch.setattr(config.settings, '_data', {'models_dir': str(tmp_path / 'models')})
    path = tmp_path / 'models' / 'weights.gguf'
    path.parent.mkdir()
    path.write_bytes(b'test weights')
    model = library.LocalModel('test', 'Test', 'text', 'llama.cpp', str(path), 0)
    monkeypatch.setattr(library, '_scan_library', lambda root: [model] if path.exists() else [])
    library.invalidate_library_cache()
    from uncloud_engine import lifecycle
    monkeypatch.setattr(lifecycle, 'resident', lambda: {})
    monkeypatch.setattr(main, 'gated', lambda *args, **kwargs: None)
    return model


def test_remove_keeps_files_and_hides_from_all_scans(model):
    main.remove_model(main.RemoveModelBody(path=model.path))
    assert Path(model.path).exists()
    assert library.scan_library(config.settings.models_dir) == []
    assert library.scan_library_cached(config.settings.models_dir) == []
    config.settings.show_model(model.path)
    assert library.scan_library(config.settings.models_dir) == [model]


def test_delete_removes_exact_registered_file(model):
    main.remove_model(main.RemoveModelBody(path=model.path, delete_files=True))
    assert not Path(model.path).exists()


def test_arbitrary_path_cannot_be_deleted(model):
    with pytest.raises(HTTPException) as error:
        main.remove_model(main.RemoveModelBody(
            path=str(Path(model.path).parent), delete_files=True))
    assert error.value.status_code == 404
    assert Path(model.path).exists()


def test_loaded_models_prevent_deletion(model, monkeypatch):
    from uncloud_engine import lifecycle
    monkeypatch.setattr(lifecycle, 'resident', lambda: {'text_model': model.path})
    with pytest.raises(HTTPException) as error:
        main.remove_model(main.RemoveModelBody(path=model.path, delete_files=True))
    assert error.value.status_code == 409
    assert Path(model.path).exists()
