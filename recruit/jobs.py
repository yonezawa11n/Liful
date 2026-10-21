"""求人マスタと求人原稿のチェック。"""

from __future__ import annotations

import re
from collections import Counter

from .store import ROOT

# 求人原稿で使わない表現（誇大・負担を軽く見せる・未確定の金額）
BANNED = [
    (r"月収\s*40\s*万", "月収40万円は構想段階（給与体系が確定するまで掲載禁止）"),
    (r"誰でも(簡単|できる)", "業務の負担を軽く見せる表現"),
    (r"(簡単|楽)な(仕事|お仕事)", "業務の負担を軽く見せる表現"),
    (r"寝ている(だけ|間)", "夜勤の負担を軽く見せる表現"),
    (r"(必ず|絶対)(稼げ|昇給|正社員)", "保証できない約束"),
    (r"高収入保証|収入保証", "保証できない約束"),
    (r"アットホーム", "根拠のない抽象表現（具体的な事実に置き換える）"),
]

REQUIRED_FIELDS = ["雇用形態", "勤務地", "必要資格", "給与", "勤務時間", "仕事内容", "休日", "応募条件"]


def field_states(job: dict) -> Counter:
    return Counter(v[0] for v in job["fields"].values())


def unresolved(job: dict) -> list[tuple[str, str, str]]:
    return [(k, v[0], v[1]) for k, v in job["fields"].items() if v[0] in ("要確認", "構想")]


def readiness(job: dict) -> str:
    """公開できる状態か。HP記載は事業責任者の承認（確定）が必要。"""
    if job["job_id"].startswith("FX"):
        return "保留"
    missing = [f for f in REQUIRED_FIELDS if f not in job["fields"]]
    states = [job["fields"][f][0] for f in REQUIRED_FIELDS if f in job["fields"]]
    if missing or any(s in ("要確認", "構想") for s in states) or any(v[0] == "構想" for v in job["fields"].values()):
        return "公開不可（要確認あり）"
    if any(v[0] == "HP記載" for v in job["fields"].values()):
        return "承認待ち（HP記載の確認）"
    return "公開可"


def duplicates(jobs: list[dict]) -> list[str]:
    """職種・雇用形態・勤務地・資格要件が実質同じ求人（重複掲載のおそれ）。"""
    seen: dict[tuple, str] = {}
    out = []
    for j in jobs:
        f = j["fields"]
        if "雇用形態" not in f:
            continue
        key = (j["business"], f["雇用形態"][1], f.get("勤務地", ["", ""])[1], f.get("必要資格", ["", ""])[1],
               f.get("給与", ["", ""])[1])
        if key in seen:
            out.append(f"{seen[key]} と {j['job_id']} は条件が同じです（重複掲載のおそれ）")
        else:
            seen[key] = j["job_id"]
    return out


def check_draft(job: dict) -> list[str]:
    path = ROOT / job["draft"]
    if not path.exists():
        return [f"原稿ファイルがありません: {job['draft']}"]
    text = path.read_text(encoding="utf-8")
    probs = []
    body = text.split("<!-- 内部メモ -->")[0]
    for pat, why in BANNED:
        for m in re.finditer(pat, body):
            line = body[: m.start()].count("\n") + 1
            probs.append(f"{job['draft']}:{line} 「{m.group(0)}」 — {why}")
    n = body.count("【要確認")
    if n:
        probs.append(f"{job['draft']}: 原稿内に【要確認】が {n} か所残っています")
    return probs


def checklist_markdown(jobs: list[dict], hp_conflicts: list[str]) -> str:
    """事業責任者に確認する項目の一覧（印刷・共有用）。"""
    L = ["# 求人条件の確認事項リスト（事業責任者・社長 確認用）", "",
         "`python3 -m recruit checklist` で求人マスタ（data/master/jobs.json）から自動作成。",
         "確認できたら jobs.json の該当項目を `[\"確定\", \"内容\", \"確認者・日付\"]` に書き換える。", "",
         "凡例: **要確認**＝情報なし／**HP記載**＝自社採用サイトに記載あり（今回の求人に使ってよいか・最新かを確認）／**構想**＝掲載禁止", ""]
    biz = None
    for j in jobs:
        if j["business"] != biz:
            biz = j["business"]
            L += [f"## {biz}", ""]
        L += [f"### 枠{j['slot']} {j['job_id']} {j['role']}（目標 {j.get('target_hires', 0)}人）", "",
              "| 確認 | 項目 | 状態 | 現在わかっていること |", "|---|---|---|---|"]
        for k, (state, val, _src) in j["fields"].items():
            if state == "確定":
                continue
            L.append(f"| □ | {k} | {state} | {val or '（情報なし）'} |")
        L.append("")
    if hp_conflicts:
        L += ["## 採用サイト（newvalleyhp.com）で表記が食い違っている点", "",
              "求人と採用サイトの内容がずれると応募後の辞退につながるため、どちらが正しいか決めて両方をそろえる。", ""]
        L += [f"- □ {c}" for c in hp_conflicts]
        L.append("")
    return "\n".join(L)


def check_all(jobs: list[dict]) -> dict:
    targets = sum(j.get("target_hires", 0) for j in jobs)
    return {
        "jobs": [{"job": j, "readiness": readiness(j), "states": field_states(j),
                  "unresolved": unresolved(j), "draft": check_draft(j)} for j in jobs],
        "duplicates": duplicates(jobs),
        "slot_count": len(jobs),
        "target_total": targets,
    }
