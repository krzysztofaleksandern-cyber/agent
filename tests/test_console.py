import time
from pathlib import Path

import pytest

from app import cli
from app.console.manager import ConsoleManager


@pytest.fixture
def mgr(tmp_path: Path) -> ConsoleManager:
    return ConsoleManager(tmp_path / "c.db", otp_ttl=1.0, session_ttl=5.0)


def test_otp_single_use(mgr: ConsoleManager) -> None:
    otp, ttl = mgr.create_otp()
    assert len(otp) == 6 and ttl == 1
    session = mgr.redeem(otp)
    assert session is not None and session.token.startswith("cs-")
    assert mgr.verify(session.token)
    assert mgr.redeem(otp) is None  # cannot be reused


def test_otp_expiry(tmp_path: Path) -> None:
    m = ConsoleManager(tmp_path / "c.db", otp_ttl=0.01)
    otp, _ = m.create_otp()
    time.sleep(0.05)
    assert m.redeem(otp) is None


def test_session_expiry_and_logout(tmp_path: Path) -> None:
    m = ConsoleManager(tmp_path / "c.db", session_ttl=0.05)
    s = m.redeem(m.create_otp()[0])
    assert m.verify(s.token)
    m.logout(s.token)
    assert not m.verify(s.token)
    s2 = m.redeem(m.create_otp()[0])
    time.sleep(0.08)
    assert not m.verify(s2.token)


def test_wrong_otp(mgr: ConsoleManager) -> None:
    mgr.create_otp()
    assert mgr.redeem("000000x") is None
    assert not mgr.verify("cs-bogus")


def test_shared_via_db(tmp_path: Path) -> None:
    # CLI process writes the OTP, server process (separate manager, same db) redeems it
    writer = ConsoleManager(tmp_path / "c.db")
    otp, _ = writer.create_otp()
    reader = ConsoleManager(tmp_path / "c.db")
    assert reader.redeem(otp) is not None


def test_cli_console_otp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "cli.db")
    assert cli.main(["--db", db, "console-otp"]) == 0
    otp = capsys.readouterr().out.strip()
    assert len(otp) == 6 and ConsoleManager(db).redeem(otp) is not None
