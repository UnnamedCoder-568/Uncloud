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


def test_delete_http_confirmation_retry_removes_only_selected_model(tmp_path, monkeypatch):
    from test_permissions import _Client

    from uncloud_engine import lifecycle
    from uncloud_engine.core.permission import Mode, Risk
    target = tmp_path / 'selected.gguf'
    other = tmp_path / 'keep.gguf'
    target.write_bytes(b'selected')
    other.write_bytes(b'keep')
    item = library.LocalModel('selected', 'Selected', 'text', 'gguf', str(target), 1)
    monkeypatch.setattr(main, 'scan_library_cached', lambda *args, **kwargs: [item])
    monkeypatch.setattr(lifecycle, 'resident', lambda: {})
    with _Client() as client:
        client.main.gate.set_mode(Risk.DELETE, Mode.ASK)
        body = {'path': str(target), 'delete_files': True}
        response = client.client.post('/api/models/remove', json=body)
        assert response.status_code == 428 and target.exists()
        request = response.json()['detail']['approval']
        answer = {key: request[key] for key in ['request_id', 'action', 'category', 'summary']}
        answer['answer'] = 'yes'
        assert client.client.post('/api/approvals/answer', json=answer).status_code == 200
        assert client.client.post('/api/models/remove', json=body).status_code == 200
        assert not target.exists() and other.read_bytes() == b'keep'
