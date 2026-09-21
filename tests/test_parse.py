from app.parse import parse_pr_url
import pytest


def test_parses_standard_url():
    ref = parse_pr_url("https://github.com/foo/bar/pull/42")
    assert ref.owner == "foo"
    assert ref.repo == "bar"
    assert ref.number == 42


def test_parses_pulls_and_slash():
    ref = parse_pr_url("https://github.com/foo/bar/pulls/7/")
    assert ref.number == 7


def test_rejects_non_pr():
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/foo/bar")
