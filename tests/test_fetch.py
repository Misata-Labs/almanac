"""Retry behaviour of the evidence fetcher."""

from __future__ import annotations

import httpx
import pytest

from almanac.fetch import Fetcher, FetchError

URL = "https://example.org/data.csv"


def scripted(responses: list[httpx.Response | Exception]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        outcome = responses[min(len(requests), len(responses)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return httpx.MockTransport(handler), requests


def fetcher(transport: httpx.MockTransport, delays: list[float], retries: int = 3) -> Fetcher:
    return Fetcher(transport=transport, retries=retries, backoff=1.0, sleep=delays.append)


def test_transient_status_is_retried_until_success() -> None:
    transport, requests = scripted([httpx.Response(504), httpx.Response(503), httpx.Response(200, content=b"a,b")])
    delays: list[float] = []
    resource = fetcher(transport, delays).get(URL)
    assert resource.content == b"a,b"
    assert len(requests) == 3
    assert delays == [1.0, 2.0]


def test_dropped_connection_is_retried() -> None:
    transport, requests = scripted([httpx.ReadTimeout("timed out"), httpx.Response(200, content=b"ok")])
    delays: list[float] = []
    assert fetcher(transport, delays).get(URL).content == b"ok"
    assert len(requests) == 2


def test_definitive_status_fails_without_retry() -> None:
    transport, requests = scripted([httpx.Response(404)])
    delays: list[float] = []
    with pytest.raises(FetchError, match=r"HTTP 404$"):
        fetcher(transport, delays).get(URL)
    assert len(requests) == 1
    assert delays == []


def test_persistent_outage_reports_attempt_count() -> None:
    transport, requests = scripted([httpx.Response(500)])
    delays: list[float] = []
    with pytest.raises(FetchError, match=r"HTTP 500 \(after 4 attempts\)"):
        fetcher(transport, delays).get(URL)
    assert len(requests) == 4
    assert delays == [1.0, 2.0, 4.0]


def test_retries_can_be_disabled() -> None:
    transport, requests = scripted([httpx.Response(503), httpx.Response(200)])
    with pytest.raises(FetchError, match=r"HTTP 503$"):
        fetcher(transport, [], retries=0).get(URL)
    assert len(requests) == 1


def test_negative_retries_are_rejected() -> None:
    with pytest.raises(ValueError):
        Fetcher(retries=-1)
