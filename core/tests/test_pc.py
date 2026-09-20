import asyncio

from jarvis_core.integrations import pc


def test_pc_open_url_rejects_non_http_and_never_uses_shell(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(pc.os, "name", "nt")
    monkeypatch.setattr(pc.os, "startfile", opened.append, raising=False)
    rejected = asyncio.run(pc.open_url({"url": "file:///C:/Windows/System32/cmd.exe"}))
    accepted = asyncio.run(pc.open_url({"url": "https://example.com/source", "title": "Fuente"}))
    assert rejected["opened"] is False
    assert accepted == {"opened": True, "verified": True, "url": "https://example.com/source", "title": "Fuente"}
    assert opened == ["https://example.com/source"]
