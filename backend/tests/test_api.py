from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app, settings


def test_health_reports_gateway() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gateway"}


def test_status_reports_core_offline() -> None:
    with TestClient(app) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["core_connected"] is False
    assert response.json()["status"] == "offline"


def test_chat_is_unavailable_without_core() -> None:
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "Hola"})
    assert response.status_code == 503


def test_core_rejects_invalid_token() -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/internal/core/ws", headers={"Authorization": "Bearer wrong"}):
                raise AssertionError("connection should not be accepted")
        assert error.value.code == 1008


def test_websocket_ping_reports_offline_core() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong", "core_connected": False}


def test_chat_round_trip_through_connected_core() -> None:
    headers = {"Authorization": f"Bearer {settings.core_token}"}
    with TestClient(app) as client, client.websocket_connect("/internal/core/ws", headers=headers) as core:
        assert core.receive_json() == {"type": "hello_ack"}
        core.send_json({"type": "hello", "metadata": {"providers": {"llm": "ollama/test"}}})

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.post, "/api/chat", json={"message": "Hola"})
            request = core.receive_json()
            assert request["type"] == "request"
            assert request["action"] == "chat"
            core.send_json({
                "type": "result",
                "id": request["id"],
                "ok": True,
                "result": {
                    "message": "Hola desde el PC",
                    "provider": "ollama",
                    "conversation_id": "conversation",
                    "message_id": "message",
                },
            })
            response = response_future.result(timeout=2)

        assert response.status_code == 200
        assert response.json()["message"] == "Hola desde el PC"


def test_chat_stream_relays_chunks_and_final_result() -> None:
    headers = {"Authorization": f"Bearer {settings.core_token}"}
    with TestClient(app) as client, client.websocket_connect("/internal/core/ws", headers=headers) as core:
        assert core.receive_json() == {"type": "hello_ack"}
        core.send_json({"type": "hello", "metadata": {}})

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.post, "/api/chat/stream", json={"message": "Tell me more"})
            request = core.receive_json()
            assert request["action"] == "chat_stream"
            core.send_json({"type": "chunk", "id": request["id"], "content": "First sentence. "})
            core.send_json({"type": "chunk", "id": request["id"], "content": "Second sentence."})
            core.send_json({
                "type": "result",
                "id": request["id"],
                "ok": True,
                "result": {
                    "message": "First sentence. Second sentence.",
                    "provider": "ollama",
                    "conversation_id": "conversation",
                    "message_id": "message",
                    "language": "en",
                },
            })
            response = response_future.result(timeout=2)

        assert response.status_code == 200
        assert '"type": "chunk"' in response.text
        assert '"type": "result"' in response.text
        assert "Second sentence." in response.text


def test_bad_feedback_requires_correction() -> None:
    with TestClient(app) as client:
        response = client.post("/api/feedback", json={"message_id": "message", "rating": "bad"})
    assert response.status_code == 422


def test_bad_feedback_accepts_structured_reason_without_fixed_correction() -> None:
    with TestClient(app) as client:
        response = client.post("/api/feedback", json={
            "message_id": "message", "rating": "bad",
            "reason_code": "should_have_used_tool",
            "comment": "Consulta BOOKSHELL antes de responder.",
        })
    assert response.status_code != 422


def test_stats_round_trip_through_connected_core() -> None:
    headers = {"Authorization": f"Bearer {settings.core_token}"}
    with TestClient(app) as client, client.websocket_connect("/internal/core/ws", headers=headers) as core:
        assert core.receive_json() == {"type": "hello_ack"}
        core.send_json({"type": "hello", "metadata": {}})

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.get, "/api/stats")
            request = core.receive_json()
            assert request["action"] == "stats"
            core.send_json({
                "type": "result",
                "id": request["id"],
                "ok": True,
                "result": {"messages": 42, "positives": 7, "negatives": 2},
            })
            response = response_future.result(timeout=2)

        assert response.status_code == 200
        assert response.json() == {"messages": 42, "positives": 7, "negatives": 2}


def test_audio_forwards_capture_diagnostics() -> None:
    headers = {"Authorization": f"Bearer {settings.core_token}"}
    with TestClient(app) as client, client.websocket_connect("/internal/core/ws", headers=headers) as core:
        assert core.receive_json() == {"type": "hello_ack"}
        core.send_json({"type": "hello", "metadata": {}})

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(
                client.post,
                "/api/audio",
                files={"file": ("utterance.webm", b"audio", "audio/webm")},
                data={"duration_ms": "6230", "speech_ms": "2810"},
            )
            request = core.receive_json()
            assert request["action"] == "audio"
            assert request["payload"]["duration_ms"] == 6230
            assert request["payload"]["speech_ms"] == 2810
            core.send_json({
                "type": "result",
                "id": request["id"],
                "ok": True,
                "result": {"transcript": "Hola", "language": "es", "provider": "faster-whisper"},
            })
            response = response_future.result(timeout=2)

        assert response.status_code == 200
        assert response.json()["transcript"] == "Hola"
