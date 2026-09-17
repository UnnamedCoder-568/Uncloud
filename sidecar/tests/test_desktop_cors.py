"""The packaged desktop origins can reach the otherwise private engine."""

from fastapi.testclient import TestClient

from uncloud_engine import main


def _preflight(origin: str):
    return TestClient(main.app).options(
        "/api/settings",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_windows_tauri_origin_is_allowed() -> None:
    response = _preflight("http://tauri.localhost")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_macos_and_linux_tauri_origin_remains_allowed() -> None:
    response = _preflight("tauri://localhost")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_unlisted_web_origin_is_rejected() -> None:
    response = _preflight("https://example.test")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
