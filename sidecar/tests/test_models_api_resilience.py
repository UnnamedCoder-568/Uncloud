"""The Models page remains usable when macOS refuses its selected folder."""

from fastapi.testclient import TestClient


def _client(monkeypatch):
    from uncloud_engine import main

    monkeypatch.setattr(main.settings, "token", "test-token")
    return main, TestClient(main.app, raise_server_exceptions=False)


def test_catalog_survives_an_unreadable_models_folder(monkeypatch) -> None:
    main, client = _client(monkeypatch)

    def denied(_path):
        raise PermissionError("Downloads is protected")

    monkeypatch.setattr(main, "scan_library_cached", denied)
    response = client.get(
        "/api/catalog",
        headers={"Authorization": "Bearer test-token", "Origin": "tauri://localhost"},
    )
    assert response.status_code == 200
    assert response.json(), "the bundled download catalogue should still be shown"
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
    assert all(not entry["installed"] for entry in response.json())


def test_library_explains_an_unreadable_models_folder(monkeypatch) -> None:
    main, client = _client(monkeypatch)

    def denied(_path):
        raise PermissionError("Downloads is protected")

    monkeypatch.setattr(main, "scan_library_cached", denied)
    response = client.get(
        "/api/library",
        headers={"Authorization": "Bearer test-token", "Origin": "tauri://localhost"},
    )
    assert response.status_code == 503
    assert "dedicated folder" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
