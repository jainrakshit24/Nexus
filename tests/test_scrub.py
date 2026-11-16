"""AC3: a record carrying a credential is blocked, and the pattern is named."""
import pytest

from nexus import scrub
from nexus.record import Record
from nexus.store import Store


@pytest.mark.parametrize("payload,expected", [
    ("key is AKIA1234567890ABCDEF ok", "aws-access-key-id"),
    ("db at postgres://admin:hunter2@db.internal:5432/app", "database-url-with-credentials"),
    ("token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig", "jwt"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "github-token"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private-key-block"),
])
def test_secrets_are_blocked_and_named(payload, expected):
    with pytest.raises(scrub.SecretFound) as exc:
        scrub.enforce(payload)
    assert expected in str(exc.value)
    assert {f.pattern for f in exc.value.findings} == {expected} or expected in {
        f.pattern for f in exc.value.findings
    }


def test_excerpt_never_leaks_the_whole_secret():
    with pytest.raises(scrub.SecretFound) as exc:
        scrub.enforce("AKIA1234567890ABCDEF")
    for f in exc.value.findings:
        assert "1234567890ABCDEF" not in f.excerpt


def test_warnings_do_not_block():
    warnings = scrub.enforce("the box lives at 192.168.1.40")
    assert [w.pattern for w in warnings] == ["private-ip"]


def test_store_write_refuses_and_writes_nothing(store: Store):
    rec = Record(name="creds", type="project", body="aws key AKIA1234567890ABCDEF")
    with pytest.raises(scrub.SecretFound):
        store.write(rec)
    assert not store.path_for(rec).exists()
    assert store.stats()["live"] == 0
