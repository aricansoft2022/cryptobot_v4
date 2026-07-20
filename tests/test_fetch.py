"""Tests for the paginated klines fetcher (pure logic, no network)."""

from __future__ import annotations

from cryptobot.fetch import MAX_LIMIT, paginate


def _history(n):
    """A fake Binance kline history: open_time = t * 60_000, oldest-first."""
    return [[t * 60_000, "1", "2", "0", "1", "5", t * 60_000 + 59_999, "0", 0, "0", "0", "0"] for t in range(n)]


def _fetcher(history, record=None):
    """A fake batch fetcher returning the last `limit` candles ending at end_time."""
    def fetch(symbol, interval, limit, end_time):
        if record is not None:
            record.append(limit)
        window = history if end_time is None else [r for r in history if r[0] <= end_time]
        return window[-limit:]
    return fetch


def test_paginate_collects_full_history():
    hist = _history(2500)
    out = paginate("X", "1m", 2500, _fetcher(hist), sleep=lambda _s: None)
    assert len(out) == 2500
    assert [r[0] for r in out] == [r[0] for r in hist]  # ascending, complete


def test_paginate_returns_last_n():
    hist = _history(2500)
    out = paginate("X", "1m", 1500, _fetcher(hist), sleep=lambda _s: None)
    assert len(out) == 1500
    assert out[0][0] == 1000 * 60_000  # the most recent 1500
    assert out[-1][0] == 2499 * 60_000


def test_paginate_capped_by_available_history():
    hist = _history(300)
    out = paginate("X", "1m", 999_999, _fetcher(hist), sleep=lambda _s: None)
    assert len(out) == 300


def test_paginate_batches_never_exceed_max_limit():
    hist = _history(2500)
    calls = []
    paginate("X", "1m", 2500, _fetcher(hist, record=calls), sleep=lambda _s: None)
    assert calls == [1000, 1000, 500]
    assert all(limit <= MAX_LIMIT for limit in calls)


def test_paginate_empty_history():
    out = paginate("X", "1m", 1000, _fetcher([]), sleep=lambda _s: None)
    assert out == []


def test_paginate_dedupes_and_sorts_overlapping_batches():
    # A misbehaving fetcher that ignores end_time and always returns the same rows.
    rows = _history(3)
    out = paginate("X", "1m", 10, lambda s, i, l, e: rows, sleep=lambda _s: None)
    assert [r[0] for r in out] == [0, 60_000, 120_000]  # unique, ascending


def test_paginate_pause_between_batches():
    hist = _history(2500)
    slept = []
    paginate("X", "1m", 2500, _fetcher(hist), pause=0.3, sleep=slept.append)
    # Sleeps only between full batches (not after the final short one).
    assert slept == [0.3, 0.3]
