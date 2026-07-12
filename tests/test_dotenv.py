"""Tests for the stdlib .env loader."""

from __future__ import annotations

from cryptobot.dotenv import load_dotenv


def _write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_loads_key_values(tmp_path):
    path = _write(tmp_path, "BINANCE_API_KEY=abc\nBINANCE_API_SECRET=def\n")
    env = {}
    loaded = load_dotenv(path, environ=env)
    assert env["BINANCE_API_KEY"] == "abc"
    assert env["BINANCE_API_SECRET"] == "def"
    assert set(loaded) == {"BINANCE_API_KEY", "BINANCE_API_SECRET"}


def test_does_not_override_existing_by_default(tmp_path):
    path = _write(tmp_path, "BINANCE_API_KEY=from_file\n")
    env = {"BINANCE_API_KEY": "from_shell"}
    loaded = load_dotenv(path, environ=env)
    assert env["BINANCE_API_KEY"] == "from_shell"  # shell wins
    assert "BINANCE_API_KEY" not in loaded


def test_override_true_replaces_existing(tmp_path):
    path = _write(tmp_path, "BINANCE_API_KEY=from_file\n")
    env = {"BINANCE_API_KEY": "from_shell"}
    load_dotenv(path, environ=env, override=True)
    assert env["BINANCE_API_KEY"] == "from_file"


def test_comments_and_blank_lines_ignored(tmp_path):
    path = _write(tmp_path, "# comment\n\n   \nKEY=value\n")
    env = {}
    load_dotenv(path, environ=env)
    assert env == {"KEY": "value"}


def test_export_prefix_and_quotes(tmp_path):
    path = _write(tmp_path, 'export A="a b"\nB=\'c\'\n')
    env = {}
    load_dotenv(path, environ=env)
    assert env["A"] == "a b"
    assert env["B"] == "c"


def test_value_may_contain_equals(tmp_path):
    path = _write(tmp_path, "TOKEN=a=b=c\n")
    env = {}
    load_dotenv(path, environ=env)
    assert env["TOKEN"] == "a=b=c"


def test_lines_without_equals_are_skipped(tmp_path):
    path = _write(tmp_path, "NOT_A_PAIR\nKEY=ok\n")
    env = {}
    load_dotenv(path, environ=env)
    assert env == {"KEY": "ok"}


def test_empty_value_allowed(tmp_path):
    path = _write(tmp_path, "EMPTY=\n")
    env = {}
    load_dotenv(path, environ=env)
    assert env["EMPTY"] == ""


def test_missing_file_is_noop():
    env = {"X": "1"}
    loaded = load_dotenv("/no/such/path/.env", environ=env)
    assert loaded == {}
    assert env == {"X": "1"}
