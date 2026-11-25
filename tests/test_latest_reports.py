import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import latest_reports
from latest_reports import git_creation_times, write_latest_reports


def make_report(root: Path, name: str) -> Path:
    path = root / "output" / "pdf" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    return path


def test_selects_latest_creation_per_product_not_filename_or_modification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = make_report(tmp_path, "power-apps-updates-2099-01-01-old.pdf")
    new = make_report(tmp_path, "power-apps-updates-2026-01-01-new.pdf")
    automate = make_report(tmp_path, "power-automate-updates-2026-01-01-test.pdf")
    dates = {
        old.relative_to(tmp_path).as_posix(): datetime(2026, 1, 1, tzinfo=UTC),
        new.relative_to(tmp_path).as_posix(): datetime(2026, 2, 1, tzinfo=UTC),
        automate.relative_to(tmp_path).as_posix(): datetime(2026, 1, 2, tzinfo=UTC),
    }
    monkeypatch.setattr(latest_reports, "git_creation_times", lambda root: dates)
    reports = write_latest_reports(tmp_path, "owner/repo", "main")
    assert [report["name"] for report in reports] == [new.name, automate.name]
    assert reports[0]["created_at"] == "2026-02-01T00:00:00.000000Z"
    assert reports[0]["size"] == new.stat().st_size
    assert reports[0]["download_url"] == (
        f"https://raw.githubusercontent.com/owner/repo/main/output/pdf/{new.name}"
    )
    assert json.loads((tmp_path / "output" / "latest.json").read_text()) == reports


def test_new_report_creation_survives_later_commits_and_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    apps = make_report(tmp_path, "power-apps-updates-2026-01-01-test.pdf")
    automate = make_report(tmp_path, "power-automate-updates-2026-01-01-test.pdf")
    dates = {automate.relative_to(tmp_path).as_posix(): datetime(2026, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(latest_reports, "git_creation_times", lambda root: dates)
    created = datetime(2026, 2, 1, tzinfo=UTC)
    initial = write_latest_reports(tmp_path, "owner/repo", "main", apps, created)
    dates[apps.relative_to(tmp_path).as_posix()] = datetime(2026, 2, 2, tzinfo=UTC)
    apps.write_bytes(b"%PDF-1.4\nUpdated body\n")
    later = write_latest_reports(
        tmp_path, "owner/repo", "main", apps, datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert later[0]["created_at"] == initial[0]["created_at"]
    assert later[0]["size"] == apps.stat().st_size


def test_unrecorded_pdf_is_not_given_an_invented_creation_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_report(tmp_path, "power-apps-updates-2026-01-01-test.pdf")
    monkeypatch.setattr(latest_reports, "git_creation_times", lambda root: {})
    with pytest.raises(ValueError, match="No recorded creation time"):
        write_latest_reports(tmp_path, "owner/repo", "main")
    assert not (tmp_path / "output" / "latest.json").exists()


def test_git_history_uses_first_addition_not_later_update(tmp_path: Path) -> None:
    def git(*args: str, date: str = "2026-01-01T00:00:00Z") -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
                "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_DATE": date,
            },
        )

    git("init")
    pdf = make_report(tmp_path, "power-apps-updates-2026-01-01-test.pdf")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-m", "Add report")
    pdf.write_bytes(b"Updated PDF")
    git("add", ".")
    git(
        "-c", "commit.gpgsign=false", "commit", "-m", "Update report",
        date="2026-02-01T00:00:00Z",
    )
    assert git_creation_times(tmp_path) == {
        pdf.relative_to(tmp_path).as_posix(): datetime(2026, 1, 1, tzinfo=UTC),
    }
