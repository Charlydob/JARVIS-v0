from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_uses_mock_provider() -> None:
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "Hola"})
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert "Hola" in response.json()["message"]


def test_websocket_ping() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong"}
