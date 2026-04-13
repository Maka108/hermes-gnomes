import json
from pathlib import Path

from freezegun import freeze_time

from hermes_gnomes.decision_log import DecisionLog


def test_append_writes_one_line_per_decision(tmp_memory_dir: Path) -> None:
    log = DecisionLog(tmp_memory_dir / "decisions.log")
    with freeze_time("2026-04-13 12:00:00"):
        log.append(action="auto_post", decision="posted", confidence=0.92, reason="routine ig post")
    with freeze_time("2026-04-13 12:00:05"):
        log.append(
            action="listing_draft", decision="queued", confidence=0.80, reason="contains name"
        )

    lines = (tmp_memory_dir / "decisions.log").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["action"] == "auto_post"
    assert first["decision"] == "posted"
    assert first["confidence"] == 0.92
    assert first["reason"] == "routine ig post"
    assert first["ts"] == "2026-04-13T12:00:00+00:00"
    assert second["action"] == "listing_draft"


def test_iter_recent_returns_newest_first(tmp_memory_dir: Path) -> None:
    log = DecisionLog(tmp_memory_dir / "decisions.log")
    with freeze_time("2026-04-13 12:00:00") as frozen:
        for i in range(5):
            log.append(action=f"a{i}", decision="posted", confidence=1.0, reason="r")
            frozen.tick(1)

    recent = list(log.iter_recent(limit=3))
    assert len(recent) == 3
    assert recent[0]["action"] == "a4"
    assert recent[1]["action"] == "a3"
    assert recent[2]["action"] == "a2"


def test_append_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "decisions.log"
    log = DecisionLog(path)
    log.append(action="x", decision="y", confidence=0.5, reason="z")
    assert path.exists()
