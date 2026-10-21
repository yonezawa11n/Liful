"""集計（ファネル・事業別・求人別・媒体別）、改善診断、今日のタスク。"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .applicants import parse_date
from .constants import BUSINESSES, CONFIRMED_STATUSES, RANK


def _d(s: str) -> dt.date | None:
    try:
        return parse_date(s)
    except Exception:
        return None


def max_rank(app: dict, hist_by_id: dict[str, list[dict]]) -> int:
    """その応募者がこれまでに到達した一番先の段階（不採用・辞退になった後も残る）。"""
    ranks = [RANK.get(app["選考ステータス"], 0)]
    ranks += [RANK.get(h["変更後"], 0) for h in hist_by_id.get(app["応募者ID"], [])]
    return max(ranks)


def history_index(history: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = defaultdict(list)
    for h in history:
        idx[h["応募者ID"]].append(h)
    return idx


def funnel(apps: list[dict], hist_by_id) -> dict:
    out = {"応募": len(apps), "面接予定": 0, "面接実施": 0, "内定": 0, "入社確定": 0,
           "入社済み": 0, "不採用": 0, "辞退": 0, "選考中": 0, "定着中": 0, "退職": 0}
    for a in apps:
        r = max_rank(a, hist_by_id)
        st = a["選考ステータス"]
        if st == "面接予定":
            out["面接予定"] += 1
        if r >= RANK["面接実施済み"]:
            out["面接実施"] += 1
        if r >= RANK["内定"]:
            out["内定"] += 1
        if st in CONFIRMED_STATUSES:
            out["入社確定"] += 1
        if st == "入社済み":
            out["入社済み"] += 1
            if a["定着状況"] == "退職":
                out["退職"] += 1
            else:
                out["定着中"] += 1
        if st == "不採用":
            out["不採用"] += 1
        elif st == "辞退":
            out["辞退"] += 1
        elif st not in CONFIRMED_STATUSES:
            out["選考中"] += 1
    return out


def rate(n: float, d: float) -> float | None:
    return (n / d) if d else None


def pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.1f}%" if x < 0.1 else f"{x * 100:.0f}%"


def group_funnels(apps, hist_by_id, key: str, keys: list[str] | None = None) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for a in apps:
        groups[a[key] or "（未入力）"].append(a)
    names = list(keys or []) + sorted(k for k in groups if k not in (keys or []))
    return {k: funnel(groups.get(k, []), hist_by_id) for k in names}


def pace(settings: dict, today: dt.date) -> dict:
    """計画上、今日までに到達しているべき累計（直線で按分した目安）。"""
    start = dt.date.fromisoformat(settings["apply_period"]["start"])
    end = dt.date.fromisoformat(settings["apply_period"]["end"])
    deadline = dt.date.fromisoformat(settings["deadline"])
    t = settings["funnel_targets"]

    def frac(s: dt.date, e: dt.date) -> float:
        if today <= s:
            return 0.0
        if today >= e:
            return 1.0
        return (today - s).days / (e - s).days

    f_apply = frac(start, end)
    f_hire = frac(start, deadline)
    return {
        "応募": round(t["応募"] * f_apply, 1),
        "面接実施": round(t["面接実施"] * f_apply, 1),
        "内定": round(t["内定"] * f_hire, 1),
        "入社確定": round(t["入社確定"] * f_hire, 1),
        "days_left": (deadline - today).days,
    }


def in_week(date_str: str, start: dt.date) -> bool:
    d = _d(date_str)
    return bool(d and start <= d < start + dt.timedelta(days=7))


def week_counts(apps, history, start: dt.date) -> dict:
    """その週（月曜始まり7日間）に起きたこと。"""
    hist_in = [h for h in history if in_week(h["日時"], start)]
    reached = defaultdict(set)
    for h in hist_in:
        reached[h["変更後"]].add(h["応募者ID"])
    return {
        "応募": sum(1 for a in apps if in_week(a["応募日"], start)),
        "面接実施": len(reached["面接実施済み"]),
        "内定": len(reached["内定"]),
        "入社確定": len(reached["内定承諾"] | reached["入社予定"]),
        "辞退": len(reached["辞退"]),
        "面接予定_翌週": sum(1 for a in apps if a["選考ステータス"] == "面接予定"
                            and in_week(a["面接予定日"], start + dt.timedelta(days=7))),
    }


def media_summary(apps, hist_by_id, media_weekly: list[dict], media_master: list[dict]) -> list[dict]:
    """媒体ごとの表示・クリック・応募・面接・採用・費用・採用単価。"""
    by_media = group_funnels(apps, hist_by_id, "応募経路", [m["name"] for m in media_master])
    totals = defaultdict(lambda: {"表示数": 0, "クリック数": 0, "広告費": 0, "入力週": 0})
    for r in media_weekly:
        t = totals[r["媒体"]]
        t["入力週"] += 1
        for k in ("表示数", "クリック数", "広告費"):
            try:
                t[k] += int(float(r[k] or 0))
            except ValueError:
                pass
    status = {m["name"]: m for m in media_master}
    out = []
    for name, f in by_media.items():
        t = totals.get(name, {"表示数": 0, "クリック数": 0, "広告費": 0, "入力週": 0})
        m = status.get(name, {})
        if not f["応募"] and not t["入力週"] and m.get("display") is False:
            continue
        hires = f["入社確定"]
        out.append({
            "媒体": name,
            "連携状況": m.get("status", "未登録"),
            "表示数": t["表示数"] if t["入力週"] else None,
            "クリック数": t["クリック数"] if t["入力週"] else None,
            "応募": f["応募"],
            "面接実施": f["面接実施"],
            "入社確定": hires,
            "広告費": t["広告費"],
            "採用単価": (t["広告費"] / hires) if hires and t["広告費"] else None,
        })
    return out


def job_media_totals(media_weekly: list[dict]) -> dict[str, dict]:
    out = defaultdict(lambda: {"表示数": 0, "クリック数": 0, "広告費": 0, "入力週": 0})
    for r in media_weekly:
        t = out[r["求人ID"]]
        t["入力週"] += 1
        for k in ("表示数", "クリック数", "広告費"):
            try:
                t[k] += int(float(r[k] or 0))
            except ValueError:
                pass
    return out


def job_rows(jobs, apps, hist_by_id, media_weekly) -> list[dict]:
    by_job = group_funnels(apps, hist_by_id, "求人ID", [j["job_id"] for j in jobs])
    mt = job_media_totals(media_weekly)
    rows = []
    for j in jobs:
        f = by_job.get(j["job_id"], funnel([], hist_by_id))
        t = mt.get(j["job_id"])
        target = j.get("target_hires", 0)
        rows.append({
            "枠": j["slot"], "求人ID": j["job_id"], "事業": j["business"], "職種": j["role"],
            "公開状況": j.get("publish_status", "下書き"),
            "目標": target, "応募": f["応募"], "面接実施": f["面接実施"], "内定": f["内定"],
            "入社確定": f["入社確定"], "不足": max(target - f["入社確定"], 0),
            "表示数": t["表示数"] if t else None, "クリック数": t["クリック数"] if t else None,
            "広告費": t["広告費"] if t else 0,
            "_funnel": f,
        })
    return rows


# ---------- 改善診断（提案のみ。求人の変更・公開は人が承認してから） ----------

def diagnose(job_rows_: list[dict], apps, hist_by_id, settings: dict) -> list[dict]:
    th = settings["diagnose_thresholds"]
    findings = []
    decl = defaultdict(lambda: {"面接後辞退": 0, "内定後辞退": 0})
    for a in apps:
        if a["選考ステータス"] != "辞退":
            continue
        r = max_rank(a, hist_by_id)
        if r >= RANK["内定"]:
            decl[a["求人ID"]]["内定後辞退"] += 1
        elif r >= RANK["面接実施済み"]:
            decl[a["求人ID"]]["面接後辞退"] += 1

    def add(job, kind, evidence, actions):
        findings.append({"求人ID": job["求人ID"], "職種": job["職種"], "症状": kind,
                         "根拠": evidence, "改善案": actions})

    for j in job_rows_:
        if j["公開状況"] not in ("公開確認済み",):
            continue  # 公開を確認できていない求人は診断しない（数字が意味を持たない）
        f = j["_funnel"]
        imp, clk = j["表示数"], j["クリック数"]
        if imp is None:
            add(j, "表示数・クリック数が未入力", "media_weekly.csv に記録がない",
                ["採用係長の管理画面で表示数・クリック数を確認し、週1回記録する（社長に依頼）"])
            continue
        if imp < th["min_impressions_per_week"] * max(1, _weeks(j)):
            add(j, "表示数が少ない", f"表示数 {imp}",
                ["求人タイトルに職種名（例:訪問介護員・児童指導員）と勤務地（市名）を入れる",
                 "検索されやすい一般的な職種名にする（社内呼称は避ける）",
                 "雇用形態・勤務地が同じ求人の重複掲載になっていないか確認する"])
        ctr = rate(clk or 0, imp)
        if imp >= th["min_impressions_for_rate"] and ctr is not None and ctr < th["ctr_low"]:
            add(j, "クリック率が低い", f"クリック率 {pct(ctr)}（基準 {pct(th['ctr_low'])}）",
                ["タイトル冒頭に給与・働き方（例: 直行直帰、扶養内OK）など確定済みの条件を出す",
                 "給与は確定した数字だけを、月給/時給の別を明記して記載する"])
        if (clk or 0) >= th["min_clicks_for_rate"] and f["応募"] == 0:
            add(j, "クリックはあるが応募がない", f"クリック {clk} / 応募 0",
                ["仕事内容・1日の流れ・勤務時間・応募条件を具体的にする",
                 "応募のハードルを下げる（見学・面談のみ可、LINE相談の導線）",
                 "要確認のまま残っている項目がないか確認する"])
        elif (clk or 0) >= th["min_clicks_for_rate"]:
            ar = rate(f["応募"], clk)
            if ar is not None and ar < th["apply_rate_low"]:
                add(j, "応募率が低い", f"応募率 {pct(ar)}（基準 {pct(th['apply_rate_low'])}）",
                    ["仕事内容・応募条件・勤務時間・福利厚生の記載を見直す"])
        if f["応募"] >= th["min_apps_for_rate"]:
            ir = rate(f["面接実施"], f["応募"])
            if ir is not None and ir < th["interview_rate_low"]:
                add(j, "応募はあるが面接につながらない", f"面接実施率 {pct(ir)}",
                    ["初回連絡を応募から24時間以内にする（連絡待ちの一覧を毎日確認）",
                     "応募後の自動返信・案内文に面接の流れと所要時間を書く",
                     "面接日程の候補を最初の連絡で3つ出す"])
        d = decl.get(j["求人ID"])
        if d and f["面接実施"] and d["面接後辞退"] / f["面接実施"] >= th["decline_rate_high"]:
            add(j, "面接後の辞退が多い", f"面接後辞退 {d['面接後辞退']} / 面接 {f['面接実施']}",
                ["面接で説明した条件と求人原稿の差がないか確認する",
                 "面接から結果連絡までの日数を短くする"])
        if d and f["内定"] and d["内定後辞退"] / f["内定"] >= th["decline_rate_high"]:
            add(j, "内定後の辞退が多い", f"内定後辞退 {d['内定後辞退']} / 内定 {f['内定']}",
                ["給与・勤務条件・仕事内容の認識違いがなかったかを辞退理由から確認する",
                 "内定時に労働条件通知書の内容を対面で説明する"])
        if f["入社確定"] and j["広告費"] / f["入社確定"] > th["cost_per_hire_high"]:
            add(j, "採用単価が高い", f"採用単価 {j['広告費'] / f['入社確定']:,.0f}円",
                ["有料広告の配分を応募単価の低い求人に寄せる（予算変更は社長承認）"])
    return findings


def _weeks(job_row: dict) -> int:
    return 1


# ---------- 今日のタスク ----------

def todo(apps: list[dict], today: dt.date, settings: dict) -> dict[str, list[dict]]:
    sla = settings.get("first_contact_sla_days", 1)
    out = {"初回連絡が遅れている": [], "連絡待ち": [], "日程調整待ち": [], "面接予定（7日以内）": [],
           "内定回答待ち": [], "入社予定": [], "次回対応日が来ている": []}
    for a in apps:
        st = a["選考ステータス"]
        applied = _d(a["応募日"])
        if st in ("応募受付", "初回連絡待ち"):
            out["連絡待ち"].append(a)
            if applied and (today - applied).days >= sla:
                out["初回連絡が遅れている"].append(a)
        elif st == "面接日程調整中":
            out["日程調整待ち"].append(a)
        elif st == "面接予定":
            d = _d(a["面接予定日"])
            if d and 0 <= (d - today).days <= 7:
                out["面接予定（7日以内）"].append(a)
        elif st == "内定":
            out["内定回答待ち"].append(a)
        elif st in ("内定承諾", "入社予定"):
            out["入社予定"].append(a)
        nd = _d(a["次回対応日"])
        if nd and nd <= today and st not in ("入社済み", "不採用", "辞退"):
            out["次回対応日が来ている"].append(a)
    return out


def business_progress(apps, hist_by_id, settings) -> list[dict]:
    targets = settings["business_targets"]
    fs = group_funnels(apps, hist_by_id, "応募事業", BUSINESSES)
    rows = []
    for b in BUSINESSES:
        f = fs.get(b) or funnel([], hist_by_id)
        rows.append({"事業": b, "目標": targets[b], "入社確定": f["入社確定"],
                     "不足": max(targets[b] - f["入社確定"], 0), "_funnel": f})
    return rows


def current_phase(schedule: list[dict], today: dt.date) -> dict | None:
    for s in schedule:
        if dt.date.fromisoformat(s["開始日"]) <= today <= dt.date.fromisoformat(s["終了日"]):
            return s
    return None


def phases_between(schedule, start: dt.date, end: dt.date) -> list[dict]:
    return [s for s in schedule
            if dt.date.fromisoformat(s["開始日"]) <= end and dt.date.fromisoformat(s["終了日"]) >= start]
