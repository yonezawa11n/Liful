"""データの読み書き・バックアップ・操作ログ。

応募者データは `private/`（.gitignore 済み）に置く。場所は環境変数
RECRUIT_DATA_DIR か --data-dir で変えられる。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
from pathlib import Path

from .constants import APPLICANT_FIELDS, HISTORY_FIELDS, JOB_STATUS_FIELDS, MEDIA_WEEKLY_FIELDS

ROOT = Path(__file__).resolve().parent.parent
MASTER_DIR = ROOT / "data" / "master"
SAMPLE_DIR = ROOT / "data" / "sample"
DEFAULT_DATA_DIR = ROOT / "private"
OUTPUT_DIR = ROOT / "output"

APPLICANTS = "applicants.csv"
HISTORY = "status_history.csv"
MEDIA_WEEKLY = "media_weekly.csv"
JOB_STATUS = "job_status.csv"
AUDIT_LOG = "audit.log"
BACKUP_DIR = "backups"
KEEP_BACKUPS = 30


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def data_dir(arg: str | None = None) -> Path:
    return Path(arg or os.environ.get("RECRUIT_DATA_DIR") or DEFAULT_DATA_DIR)


def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)  # 自分のユーザーだけが開ける
    except OSError:
        pass


def read_csv(path: Path, fields: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append({k: (row.get(k) or "").strip() for k in fields})
        return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    _secure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


class Store:
    """1つのデータフォルダ（本番 private/ またはサンプル）を表す。"""

    def __init__(self, directory: Path):
        self.dir = Path(directory)

    # ---- 初期化 ----
    def exists(self) -> bool:
        return (self.dir / APPLICANTS).exists()

    def init(self) -> None:
        _secure_dir(self.dir)
        for name, fields in ((APPLICANTS, APPLICANT_FIELDS), (HISTORY, HISTORY_FIELDS),
                             (MEDIA_WEEKLY, MEDIA_WEEKLY_FIELDS)):
            if not (self.dir / name).exists():
                write_csv(self.dir / name, fields, [])

    # ---- 読み書き ----
    def applicants(self) -> list[dict]:
        return read_csv(self.dir / APPLICANTS, APPLICANT_FIELDS)

    def history(self) -> list[dict]:
        return read_csv(self.dir / HISTORY, HISTORY_FIELDS)

    def media_weekly(self) -> list[dict]:
        return read_csv(self.dir / MEDIA_WEEKLY, MEDIA_WEEKLY_FIELDS)

    def job_status(self) -> list[dict]:
        return read_csv(self.dir / JOB_STATUS, JOB_STATUS_FIELDS)

    def save_job_status(self, rows: list[dict]) -> None:
        write_csv(self.dir / JOB_STATUS, JOB_STATUS_FIELDS, rows)

    def jobs(self) -> list[dict]:
        """求人マスタに、このデータフォルダの公開状況（job_status.csv）を重ねたもの。"""
        jobs = load_jobs()
        st = {r["求人ID"]: r for r in self.job_status()}
        for j in jobs:
            r = st.get(j["job_id"])
            if r:
                j["publish_status"] = r["公開状況"]
                j["publish_verified"] = r["公開確認日"]
        return jobs

    def save_applicants(self, rows: list[dict]) -> None:
        write_csv(self.dir / APPLICANTS, APPLICANT_FIELDS, rows)

    def append_history(self, entries: list[dict]) -> None:
        rows = self.history() + entries
        write_csv(self.dir / HISTORY, HISTORY_FIELDS, rows)

    def save_media_weekly(self, rows: list[dict]) -> None:
        write_csv(self.dir / MEDIA_WEEKLY, MEDIA_WEEKLY_FIELDS, rows)

    # ---- 操作ログ（氏名などの個人情報は書かない） ----
    def log(self, actor: str, action: str, target: str = "", detail: str = "") -> None:
        _secure_dir(self.dir)
        entry = {"time": now(), "actor": actor, "action": action, "target": target, "detail": detail}
        path = self.dir / AUDIT_LOG
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def audit_entries(self) -> list[dict]:
        p = self.dir / AUDIT_LOG
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ---- バックアップ ----
    def backup(self, reason: str = "manual") -> Path | None:
        if not self.exists():
            return None
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        _secure_dir(self.dir / BACKUP_DIR)
        dest = self.dir / BACKUP_DIR / f"{stamp}_{reason}"
        _secure_dir(dest)
        for name in (APPLICANTS, HISTORY, MEDIA_WEEKLY, JOB_STATUS, AUDIT_LOG):
            src = self.dir / name
            if src.exists():
                shutil.copy2(src, dest / name)
                try:
                    os.chmod(dest / name, 0o600)
                except OSError:
                    pass
        self._prune_backups()
        return dest

    def backups(self) -> list[Path]:
        root = self.dir / BACKUP_DIR
        if not root.exists():
            return []
        return sorted(p for p in root.iterdir() if p.is_dir())

    def _prune_backups(self) -> None:
        items = self.backups()
        for old in items[:-KEEP_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)

    def restore(self, backup: Path) -> None:
        for name in (APPLICANTS, HISTORY, MEDIA_WEEKLY, JOB_STATUS):
            src = backup / name
            if src.exists():
                shutil.copy2(src, self.dir / name)


def load_jobs() -> list[dict]:
    return load_json(MASTER_DIR / "jobs.json")["jobs"]


def load_settings() -> dict:
    return load_json(MASTER_DIR / "settings.json")


def load_media_master() -> list[dict]:
    return load_json(MASTER_DIR / "media.json")["media"]


def load_schedule() -> list[dict]:
    return read_csv(MASTER_DIR / "schedule.csv", ["開始日", "終了日", "フェーズ", "主な作業", "担当", "状態"])
