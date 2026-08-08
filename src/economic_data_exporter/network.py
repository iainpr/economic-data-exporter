"""Bounded, TLS-verified HTTP client with safe GET caching and retries."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from economic_data_exporter.config import CACHE_DIR, LIMITS, USER_AGENT, Limits
from economic_data_exporter.exceptions import (
    AuthenticationError,
    NetworkError,
    RateLimitError,
    SourceNotFoundError,
    SourceUnavailableError,
)
from economic_data_exporter.utils.redaction import redact_url

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    retrieved_at: datetime
    from_cache: bool = False

    def json(self) -> object:
        return json.loads(self.content.decode("utf-8-sig"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8-sig")


class HttpClient:
    """A small wrapper that exposes only bounded HTTPS GET requests."""

    def __init__(
        self,
        *,
        limits: Limits = LIMITS,
        cache_dir: Path = CACHE_DIR,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limits = limits
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sleep = sleep
        self._prune_lock = threading.Lock()
        self._bytes_written_since_prune = 0
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=limits.connect_timeout_seconds,
                read=limits.read_timeout_seconds,
                write=limits.read_timeout_seconds,
                pool=limits.connect_timeout_seconds,
            ),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
            verify=True,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _validate_url(url: str, trusted_hosts: Iterable[str]) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise NetworkError("Only HTTPS endpoints are permitted.")
        hosts = {host.lower() for host in trusted_hosts}
        if (parts.hostname or "").lower() not in hosts:
            raise NetworkError("Request host is not on the adapter's trusted allow-list.")
        if parts.username or parts.password:
            raise NetworkError("Credentials in URLs are not permitted.")

    def _cache_paths(
        self,
        method: str,
        url: str,
        params: dict[str, object] | None,
        json_payload: object | None,
    ) -> tuple[Path, Path]:
        canonical = str(httpx.URL(url, params=params))
        if json_payload is not None:
            canonical += "|" + json.dumps(json_payload, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{method}:{canonical}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.bin", self.cache_dir / f"{digest}.json"

    def _read_cache(
        self,
        method: str,
        url: str,
        params: dict[str, object] | None,
        json_payload: object | None,
    ) -> FetchResponse | None:
        body_path, meta_path = self._cache_paths(method, url, params, json_payload)
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            stored_at = datetime.fromisoformat(meta["stored_at"])
            age = (datetime.now(UTC) - stored_at).total_seconds()
            if age > self.limits.cache_ttl_seconds:
                return None
            return FetchResponse(
                url=meta["url"],
                status_code=int(meta["status_code"]),
                headers=dict(meta["headers"]),
                content=body_path.read_bytes(),
                retrieved_at=stored_at,
                from_cache=True,
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _write_cache(
        self,
        method: str,
        response: FetchResponse,
        params: dict[str, object] | None,
        json_payload: object | None,
    ) -> None:
        body_path, meta_path = self._cache_paths(
            method, response.url.split("?", 1)[0], params, json_payload
        )
        unique = f".{os.getpid()}.{threading.get_ident()}.tmp"
        body_tmp = body_path.with_name(body_path.name + unique)
        meta_tmp = meta_path.with_name(meta_path.name + unique)
        try:
            body_tmp.write_bytes(response.content)
            meta_tmp.write_text(
                json.dumps(
                    {
                        "url": response.url,
                        "status_code": response.status_code,
                        "headers": response.headers,
                        "stored_at": response.retrieved_at.isoformat(),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(body_tmp, body_path)
            os.replace(meta_tmp, meta_path)
            self._maybe_prune_cache(len(response.content))
        except OSError:
            body_tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)
            LOGGER.warning("Cache write failed; continuing without cached copy")

    def _maybe_prune_cache(self, written_bytes: int) -> None:
        # A full prune does an iterdir()+stat() scan of the cache directory. Doing
        # that after every write is O(files) per request; only rescan once enough
        # has been written in-process to plausibly matter.
        prune_check_interval = max(1024 * 1024, self.limits.max_cache_bytes // 20)
        with self._prune_lock:
            self._bytes_written_since_prune += written_bytes
            if self._bytes_written_since_prune < prune_check_interval:
                return
            self._bytes_written_since_prune = 0
        self._prune_cache()

    def _prune_cache(self) -> None:
        files = [
            path
            for path in self.cache_dir.iterdir()
            if path.is_file() and not path.name.endswith(".tmp")
        ]
        total = sum(path.stat().st_size for path in files)
        if total <= self.limits.max_cache_bytes:
            return
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            try:
                total -= path.stat().st_size
                path.unlink(missing_ok=True)
            except OSError:
                continue
            if total <= self.limits.max_cache_bytes:
                break

    def get(
        self,
        url: str,
        *,
        trusted_hosts: Iterable[str],
        params: dict[str, object] | None = None,
        expected_content_types: tuple[str, ...] = (),
        use_cache: bool = True,
        max_bytes: int | None = None,
    ) -> FetchResponse:
        return self._request(
            "GET",
            url,
            trusted_hosts=trusted_hosts,
            params=params,
            expected_content_types=expected_content_types,
            use_cache=use_cache,
            max_bytes=max_bytes,
        )

    def post_json(
        self,
        url: str,
        *,
        trusted_hosts: Iterable[str],
        payload: object,
        expected_content_types: tuple[str, ...] = ("json",),
        use_cache: bool = True,
        max_bytes: int | None = None,
    ) -> FetchResponse:
        """Bounded HTTPS JSON POST used only for provider APIs that require POST metadata calls."""
        return self._request(
            "POST",
            url,
            trusted_hosts=trusted_hosts,
            json_payload=payload,
            expected_content_types=expected_content_types,
            use_cache=use_cache,
            max_bytes=max_bytes,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        trusted_hosts: Iterable[str],
        params: dict[str, object] | None = None,
        json_payload: object | None = None,
        expected_content_types: tuple[str, ...] = (),
        use_cache: bool = True,
        max_bytes: int | None = None,
    ) -> FetchResponse:
        self._validate_url(url, trusted_hosts)
        request_path = urlsplit(url).path
        started = time.perf_counter()
        if (
            use_cache
            and (cached := self._read_cache(method, url, params, json_payload)) is not None
        ):
            LOGGER.info(
                "%s cache_hit host=%s path=%s bytes=%d",
                method,
                urlsplit(url).hostname,
                request_path,
                len(cached.content),
            )
            return cached

        max_size = max_bytes or self.limits.max_response_bytes
        last_error: Exception | None = None
        for attempt in range(self.limits.max_retries + 1):
            try:
                # httpx's QueryParams stub is narrower than the dict[str, object] this
                # client accepts from adapters (to allow any JSON-serializable value).
                with self._client.stream(
                    method, url, params=params, json=json_payload  # type: ignore[arg-type]
                ) as response:
                    if response.is_redirect:
                        raise NetworkError("Unexpected redirect was refused.")
                    if response.status_code in {401, 403}:
                        raise AuthenticationError("Provider rejected authentication or access.")
                    if response.status_code == 404:
                        raise SourceNotFoundError("Provider could not find the requested resource.")
                    if response.status_code == 429:
                        if attempt >= self.limits.max_retries:
                            raise RateLimitError(
                                "Provider rate limit was exceeded after bounded retries."
                            )
                        retry_after = response.headers.get("Retry-After")
                        LOGGER.warning(
                            "%s retry rate_limit host=%s path=%s attempt=%d",
                            method,
                            urlsplit(url).hostname,
                            request_path,
                            attempt + 1,
                        )
                        self._backoff(
                            attempt,
                            float(retry_after) if retry_after and retry_after.isdigit() else None,
                        )
                        continue
                    if response.status_code in {408, 500, 502, 503, 504}:
                        if attempt >= self.limits.max_retries:
                            raise SourceUnavailableError(
                                f"Provider remained unavailable (HTTP {response.status_code})."
                            )
                        LOGGER.warning(
                            "%s retry transient_status host=%s path=%s status=%d attempt=%d",
                            method,
                            urlsplit(url).hostname,
                            request_path,
                            response.status_code,
                            attempt + 1,
                        )
                        self._backoff(attempt)
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        raise NetworkError(f"Provider returned HTTP {response.status_code}.")

                    content_type = response.headers.get("Content-Type", "").lower()
                    if expected_content_types and not any(
                        item in content_type for item in expected_content_types
                    ):
                        raise NetworkError(
                            f"Unexpected response content type: {content_type or 'missing'}."
                        )
                    chunks: list[bytes] = []
                    total_bytes = 0
                    for chunk in response.iter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > max_size:
                            raise NetworkError(
                                f"Response exceeds the configured {max_size:,}-byte limit."
                            )
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    fetched = FetchResponse(
                        url=redact_url(str(response.url)),
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        content=content,
                        retrieved_at=datetime.now(UTC),
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= self.limits.max_retries:
                    raise NetworkError(f"Network request failed: {exc.__class__.__name__}") from exc
                LOGGER.warning(
                    "%s retry network_error host=%s path=%s attempt=%d",
                    method,
                    urlsplit(url).hostname,
                    request_path,
                    attempt + 1,
                )
                self._backoff(attempt)
                continue

            if use_cache:
                self._write_cache(method, fetched, params, json_payload)
            LOGGER.info(
                "%s live host=%s path=%s status=%d bytes=%d elapsed_s=%.4f",
                method,
                urlsplit(url).hostname,
                request_path,
                fetched.status_code,
                len(fetched.content),
                time.perf_counter() - started,
            )
            return fetched
        raise NetworkError(f"Network request failed: {last_error}")

    def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        delay = retry_after if retry_after is not None else min(8.0, 0.5 * (2**attempt))
        self._sleep(delay + random.uniform(0.0, 0.25))
