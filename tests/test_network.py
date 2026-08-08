from pathlib import Path

import httpx
import pytest

from economic_data_exporter.config import Limits
from economic_data_exporter.exceptions import NetworkError, RateLimitError, SourceNotFoundError
from economic_data_exporter.network import HttpClient


def limits(retries: int = 2) -> Limits:
    return Limits(
        max_retries=retries,
        cache_ttl_seconds=60,
        max_response_bytes=1024,
        connect_timeout_seconds=0.01,
        read_timeout_seconds=0.01,
    )


def test_retries_transient_status(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = HttpClient(
        limits=limits(), cache_dir=tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    response = client.get(
        "https://example.org/data", trusted_hosts=("example.org",), expected_content_types=("json",)
    )
    assert response.json() == {"ok": True}
    assert calls == 3


def test_timeout_failure_is_bounded(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = HttpClient(
        limits=limits(1), cache_dir=tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    with pytest.raises(NetworkError):
        client.get("https://example.org/data", trusted_hosts=("example.org",))


def test_rate_limit_response(tmp_path: Path) -> None:
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request)),
        sleep=lambda _: None,
    )
    with pytest.raises(RateLimitError):
        client.get("https://example.org/data", trusted_hosts=("example.org",))


def test_rejects_untrusted_host(tmp_path: Path) -> None:
    client = HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    with pytest.raises(NetworkError):
        client.get("https://evil.example/data", trusted_hosts=("example.org",))


def test_streamed_response_size_limit(tmp_path: Path) -> None:
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 2048,
                headers={"content-type": "application/octet-stream"},
                request=request,
            )
        ),
    )
    with pytest.raises(NetworkError):
        client.get(
            "https://example.org/data",
            trusted_hosts=("example.org",),
            max_bytes=1024,
        )


def test_post_json_enforces_size_limit_while_streaming(tmp_path: Path) -> None:
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 2048,
                headers={"content-type": "application/json"},
                request=request,
            )
        ),
    )
    with pytest.raises(NetworkError):
        client.post_json(
            "https://example.org/data",
            trusted_hosts=("example.org",),
            payload={"vectorId": 1},
            max_bytes=1024,
        )


def test_post_json_maps_404_to_source_not_found(tmp_path: Path) -> None:
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(404, request=request)),
    )
    with pytest.raises(SourceNotFoundError):
        client.post_json(
            "https://example.org/data",
            trusted_hosts=("example.org",),
            payload={"vectorId": 1},
        )


def test_post_json_uses_cache_on_repeat_payload(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True}, request=request)

    client = HttpClient(
        limits=limits(0), cache_dir=tmp_path, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    first = client.post_json("https://example.org/data", trusted_hosts=("example.org",), payload={"vectorId": 1})
    second = client.post_json("https://example.org/data", trusted_hosts=("example.org",), payload={"vectorId": 1})
    assert calls == 1
    assert first.json() == second.json() == {"ok": True}


def test_cache_is_not_pruned_on_every_small_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}, request=request)),
    )
    prune_calls = 0
    original_prune = client._prune_cache

    def counting_prune() -> None:
        nonlocal prune_calls
        prune_calls += 1
        original_prune()

    monkeypatch.setattr(client, "_prune_cache", counting_prune)

    for index in range(20):
        client.get(f"https://example.org/data/{index}", trusted_hosts=("example.org",))

    assert prune_calls == 0


def test_cached_metadata_redacts_secret_url(tmp_path: Path) -> None:
    secret = "abcdefghijklmnopqrstuvwxyz123456"
    client = HttpClient(
        limits=limits(0),
        cache_dir=tmp_path,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"ok": True},
                request=request,
            )
        ),
    )
    client.get(
        "https://example.org/data",
        trusted_hosts=("example.org",),
        params={"api_key": secret},
    )
    metadata_text = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json"))
    assert secret not in metadata_text
    assert "redacted" in metadata_text
