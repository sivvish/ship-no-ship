from app.signals import extract, is_application_code, is_docs_file, is_sensitive, is_test_file
from tests.helpers import green, pr, py_file


def test_test_file_detection():
    assert is_test_file("tests/test_app.py")
    assert is_test_file("src/app.test.ts")
    assert not is_test_file("src/app.py")


def test_docs_file_detection():
    assert is_docs_file("README.md")
    assert is_docs_file("docs/guide.md")
    assert not is_docs_file("src/app.py")


def test_sensitive_auth_segment():
    hit, kind = is_sensitive("src/auth/session.py")
    assert hit and kind == "auth"


def test_author_py_is_not_auth():
    hit, kind = is_sensitive("src/author.py")
    assert not hit


def test_application_code_excludes_lock_and_docs():
    assert is_application_code("src/app.py")
    assert not is_application_code("README.md")
    assert not is_application_code("package-lock.json")
    assert not is_application_code("tests/test_app.py")


def test_agent_detection_from_footer():
    p = pr(
        title="fix",
        body="Generated with Claude Code",
        files=[py_file("src/a.py")],
        check_runs=green(),
        user_login="alice",
    )
    sig = extract(p)
    assert sig.agent["detected"]
    assert "claude-code" in sig.agent["names"]
