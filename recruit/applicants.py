"""応募者の追加・ステータス変更・取込（重複検知）・検証。

採否は人が決める。このモジュールは「人が決めた結果を記録する」だけで、
合否を自動判定する処理は持たない。
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import unicodedata
from pathlib import Path

from .constants import (
    APPLICANT_FIELDS,
    CONTACT_STATES,
    INTERVIEW_RESULTS,
    RETENTION_STATES,
    SENSITIVE_WORDS,
    STATUSES,
    TERMINAL_STATUSES,
)
from .store import Store, now


class RecruitError(Exception):
    """利用者に見せるエラー（日本語メッセージ）。"""


DATE_FIELDS = ["応募日", "面接予定日", "内定日", "入社予定日", "入社日", "次回対応日"]


def parse_date(value: str) -> dt.date | None:
    value = (value or "").strip()
    if not value:
        return None
    value = unicodedata.normalize("NFKC", value).replace("/", "-").replace(".", "-")
    value = value.split(" ")[0].split("T")[0]
    try:
        return dt.date.fromisoformat("-".join(p.zfill(2) for p in value.split("-")))
    except ValueError:
        raise RecruitError(f"日付の形式が読めません: {value}（例: 2026-11-05）")


def norm_date(value: str) -> str:
    d = parse_date(value)
    return d.isoformat() if d else ""


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"\s+", "", s).lower()


def find_sensitive(text: str) -> list[str]:
    return [w for w in SENSITIVE_WORDS if w in (text or "")]


def check_note(text: str) -> None:
    hits = find_sensitive(text)
    if hits:
        raise RecruitError(
            "申し送りに採用判断に使ってはいけない情報が含まれている可能性があります: "
            + "、".join(hits)
            + "\n→ 健康・家族・信条などは記録せず、業務上必要な事実だけを書いてください。"
        )


def job_map(jobs: list[dict]) -> dict[str, dict]:
    return {j["job_id"]: j for j in jobs}


def next_id(rows: list[dict]) -> str:
    nums = [int(m.group(1)) for r in rows if (m := re.fullmatch(r"A(\d+)", r["応募者ID"]))]
    return f"A{(max(nums) + 1) if nums else 1:04d}"


def _fill_from_job(row: dict, jobs: dict[str, dict]) -> None:
    job = jobs.get(row["求人ID"])
    if job is None:
        raise RecruitError(f"求人ID {row['求人ID']} は求人マスタにありません（data/master/jobs.json）")
    row["応募事業"] = job["business"]
    row["応募職種"] = row.get("応募職種") or job["role"]


def duplicate_of(row: dict, rows: list[dict]) -> dict | None:
    """同一応募の判定: 外部応募番号が一致 / 氏名＋求人ID＋応募日が一致。"""
    ext = row.get("外部応募番号", "")
    for r in rows:
        if ext and r["外部応募番号"] == ext and r["応募経路"] == row.get("応募経路", ""):
            return r
        if (normalize_name(r["氏名"]) == normalize_name(row["氏名"])
                and r["求人ID"] == row["求人ID"] and r["応募日"] == row["応募日"]):
            return r
    return None


def similar_people(row: dict, rows: list[dict]) -> list[dict]:
    """同じ氏名で別求人・別日の応募（同一人物の可能性。自動では統合しない）。"""
    n = normalize_name(row["氏名"])
    return [r for r in rows if normalize_name(r["氏名"]) == n and r is not row]


def add_applicant(store: Store, jobs: list[dict], data: dict, actor: str) -> dict:
    rows = store.applicants()
    row = {k: "" for k in APPLICANT_FIELDS}
    row.update({k: (v or "").strip() for k, v in data.items() if k in APPLICANT_FIELDS})
    if not row["氏名"]:
        raise RecruitError("氏名は必須です")
    if not row["求人ID"]:
        raise RecruitError("求人ID は必須です（例: HK-01）")
    row["応募日"] = norm_date(row["応募日"]) or dt.date.today().isoformat()
    for f in DATE_FIELDS:
        row[f] = norm_date(row[f])
    _fill_from_job(row, job_map(jobs))
    check_note(row["申し送り"])
    if duplicate_of(row, rows):
        raise RecruitError("同じ応募がすでに登録されています（氏名・求人・応募日が一致）")
    row["選考ステータス"] = row["選考ステータス"] or "初回連絡待ち"
    if row["選考ステータス"] not in STATUSES:
        raise RecruitError(f"選考ステータスが不正です: {row['選考ステータス']}")
    row["連絡状況"] = row["連絡状況"] or "未連絡"
    row["応募者ID"] = next_id(rows)
    row["更新日時"] = now()
    rows.append(row)
    store.save_applicants(rows)
    store.append_history([{
        "日時": now(), "応募者ID": row["応募者ID"], "変更前": "",
        "変更後": row["選考ステータス"], "操作者": actor, "メモ": "新規登録",
    }])
    store.log(actor, "add", row["応募者ID"], f"求人 {row['求人ID']}")
    return row


def get(rows: list[dict], applicant_id: str) -> dict:
    for r in rows:
        if r["応募者ID"] == applicant_id:
            return r
    raise RecruitError(f"応募者ID {applicant_id} が見つかりません")


# ステータスごとに必要な入力
REQUIRED_ON_STATUS = {
    "面接予定": "面接予定日",
    "入社予定": "入社予定日",
    "入社済み": "入社日",
}


def change_status(store: Store, applicant_id: str, new_status: str, actor: str,
                  note: str = "", date: str = "", force: bool = False,
                  at: str | None = None) -> dict:
    if new_status not in STATUSES:
        raise RecruitError(f"選考ステータスが不正です: {new_status}\n使える値: " + " / ".join(STATUSES))
    check_note(note)
    rows = store.applicants()
    row = get(rows, applicant_id)
    old = row["選考ステータス"]
    if old == new_status:
        raise RecruitError(f"すでに「{new_status}」です")
    if old in TERMINAL_STATUSES and not force:
        raise RecruitError(f"「{old}」は終了ステータスです。戻す場合は --force を付けてください（履歴に残ります）")
    field = REQUIRED_ON_STATUS.get(new_status)
    if field:
        value = norm_date(date) or row[field]
        if not value:
            raise RecruitError(f"「{new_status}」にするには --date で{field}を指定してください")
        row[field] = value
    if new_status == "内定":
        row["内定日"] = norm_date(date) or row["内定日"] or norm_date(at or "") or dt.date.today().isoformat()
    if new_status == "入社済み" and not row["定着状況"]:
        row["定着状況"] = "在籍中"
    if new_status in ("連絡済み", "面接日程調整中", "面接予定") and row["連絡状況"] in ("", "未連絡"):
        row["連絡状況"] = "連絡済み"
    row["選考ステータス"] = new_status
    row["更新日時"] = now()
    store.save_applicants(rows)
    store.append_history([{
        "日時": at or now(), "応募者ID": applicant_id, "変更前": old,
        "変更後": new_status, "操作者": actor, "メモ": note,
    }])
    store.log(actor, "status", applicant_id, f"{old} → {new_status}")
    return row


EDITABLE = {
    "連絡状況": CONTACT_STATES,
    "面接結果": INTERVIEW_RESULTS,
    "定着状況": RETENTION_STATES,
}


def update_fields(store: Store, applicant_id: str, changes: dict, actor: str) -> dict:
    rows = store.applicants()
    row = get(rows, applicant_id)
    forbidden = {"応募者ID", "選考ステータス", "更新日時", "応募事業"}
    for k, v in changes.items():
        if k not in APPLICANT_FIELDS or k in forbidden:
            raise RecruitError(f"「{k}」はこのコマンドでは変更できません（ステータスは status コマンド）")
        if k in DATE_FIELDS:
            v = norm_date(v)
        if k in EDITABLE and v not in EDITABLE[k]:
            raise RecruitError(f"{k} に使える値: " + " / ".join(x or '(空欄)' for x in EDITABLE[k]))
        if k == "申し送り":
            check_note(v)
        row[k] = v
    if "求人ID" in changes:
        from .store import load_jobs
        _fill_from_job(row, job_map(load_jobs()))
    row["更新日時"] = now()
    store.save_applicants(rows)
    store.log(actor, "update", applicant_id, "変更項目: " + ",".join(changes))
    return row


def delete_applicant(store: Store, applicant_id: str, actor: str) -> None:
    rows = store.applicants()
    get(rows, applicant_id)
    store.backup("before-delete")
    store.save_applicants([r for r in rows if r["応募者ID"] != applicant_id])
    store.log(actor, "delete", applicant_id, "応募者データを削除（履歴は残す）")


# ---------- CSV 取込 ----------

def read_import_file(path: Path, mapping: dict | None) -> list[dict]:
    """外部CSV（採用係長などの出力）を読み、列名をこのツールの列名に読み替える。"""
    mapping = dict(mapping or {})
    job_names = mapping.pop("_求人名→求人ID", {})  # 採用係長の求人タイトル → HK-01 などへの読み替え
    mapping = {k: v for k, v in mapping.items() if not k.startswith("_")}
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RecruitError("CSV の文字コードが判別できません（UTF-8 か Shift_JIS で保存してください）")
    reader = csv.DictReader(text.splitlines())
    out = []
    for src in reader:
        row = {}
        for col, val in src.items():
            if col is None:
                continue
            key = mapping.get(col.strip(), col.strip())
            if key in APPLICANT_FIELDS:
                row[key] = (val or "").strip()
        if row.get("求人ID") in job_names:
            row["求人ID"] = job_names[row["求人ID"]]
        out.append(row)
    return out


def plan_import(store: Store, jobs: list[dict], incoming: list[dict]) -> dict:
    """取込の下見。保存はしない。"""
    existing = store.applicants()
    jm = job_map(jobs)
    plan = {"new": [], "duplicates": [], "errors": [], "similar": []}
    staged: list[dict] = []
    for i, data in enumerate(incoming, start=2):  # 2 = CSV の行番号（ヘッダーが1行目）
        try:
            row = {k: "" for k in APPLICANT_FIELDS}
            row.update(data)
            if not row["氏名"] or not row["求人ID"]:
                raise RecruitError("氏名・求人ID が空です")
            for f in DATE_FIELDS:
                row[f] = norm_date(row[f])
            if not row["応募日"]:
                raise RecruitError("応募日が空です")
            _fill_from_job(row, jm)
            check_note(row["申し送り"])
            if row["選考ステータス"] and row["選考ステータス"] not in STATUSES:
                raise RecruitError(f"選考ステータスが不正: {row['選考ステータス']}")
        except RecruitError as e:
            plan["errors"].append((i, str(e).splitlines()[0]))
            continue
        dup = duplicate_of(row, existing) or duplicate_of(row, staged)
        if dup:
            plan["duplicates"].append((i, dup.get("応募者ID") or "（同じCSV内）"))
            continue
        if similar_people(row, existing + staged):
            plan["similar"].append(i)
        staged.append(row)
        plan["new"].append(row)
    return plan


def apply_import(store: Store, plan: dict, actor: str, source: str) -> list[str]:
    store.backup("before-import")
    rows = store.applicants()
    hist = []
    ids = []
    for row in plan["new"]:
        row["応募者ID"] = next_id(rows)
        row["選考ステータス"] = row["選考ステータス"] or "初回連絡待ち"
        row["連絡状況"] = row["連絡状況"] or "未連絡"
        row["更新日時"] = now()
        rows.append(row)
        ids.append(row["応募者ID"])
        hist.append({"日時": now(), "応募者ID": row["応募者ID"], "変更前": "",
                     "変更後": row["選考ステータス"], "操作者": actor, "メモ": f"CSV取込 {source}"})
    store.save_applicants(rows)
    store.append_history(hist)
    store.log(actor, "import", source, f"{len(ids)}件追加 / 重複{len(plan['duplicates'])}件スキップ")
    return ids


# ---------- 検証 ----------

def validate(store: Store, jobs: list[dict]) -> list[str]:
    problems = []
    rows = store.applicants()
    jm = job_map(jobs)
    seen_ids = set()
    for r in rows:
        aid = r["応募者ID"] or "(IDなし)"
        if aid in seen_ids:
            problems.append(f"{aid}: 応募者IDが重複しています")
        seen_ids.add(aid)
        if r["求人ID"] not in jm:
            problems.append(f"{aid}: 求人ID {r['求人ID']} が求人マスタにありません")
        if r["選考ステータス"] not in STATUSES:
            problems.append(f"{aid}: 選考ステータスが不正です（{r['選考ステータス']}）")
        for f in DATE_FIELDS:
            try:
                parse_date(r[f])
            except RecruitError:
                problems.append(f"{aid}: {f} の日付が読めません（{r[f]}）")
        if r["選考ステータス"] == "面接予定" and not r["面接予定日"]:
            problems.append(f"{aid}: 面接予定なのに面接予定日が空です")
        if r["選考ステータス"] == "入社予定" and not r["入社予定日"]:
            problems.append(f"{aid}: 入社予定なのに入社予定日が空です")
        hits = find_sensitive(r["申し送り"])
        if hits:
            problems.append(f"{aid}: 申し送りにセンシティブな語があります（{'、'.join(hits)}）→ 削除してください")
        try:
            a, o = parse_date(r["応募日"]), parse_date(r["内定日"])
            if a and o and o < a:
                problems.append(f"{aid}: 内定日が応募日より前です")
        except RecruitError:
            pass
        dup = duplicate_of(r, [x for x in rows if x is not r])
        if dup:
            problems.append(f"{aid}: {dup['応募者ID']} と同じ応募の可能性があります")
    ids = {r["応募者ID"] for r in rows}
    orphans = {h["応募者ID"] for h in store.history()} - ids
    if orphans:
        problems.append(f"履歴だけ残っている応募者ID（削除済み）: {len(orphans)}件（問題なし・参考）")
    return problems
