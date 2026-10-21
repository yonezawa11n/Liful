"""サンプルデータ（架空の応募者）を data/sample/ に作り直す。

実在の人物ではない。テストとデモ用。`python3 scripts/make_sample.py`
"""

import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit import applicants as A  # noqa: E402
from recruit import store as S  # noqa: E402

SAMPLE_TODAY = "2026-12-09"

# (求人ID, 応募日, 経路, 最終ステータス, 関連日)
PLAN = [
    ("HK-01", "2026-11-03", "Indeed", "入社予定", "2026-12-16"),
    ("HK-01", "2026-11-05", "採用係長", "内定承諾", ""),
    ("HK-01", "2026-11-12", "Indeed", "辞退", ""),
    ("HK-01", "2026-11-20", "公式LINE", "面接予定", "2026-12-11"),
    ("HK-02", "2026-11-06", "求人ボックス", "不採用", ""),
    ("HK-02", "2026-11-25", "Indeed", "内定", ""),
    ("HK-03", "2026-11-10", "自社採用サイト", "面接日程調整中", ""),
    ("HK-03", "2026-12-08", "Indeed", "初回連絡待ち", ""),
    ("HD-01", "2026-11-04", "採用係長", "入社済み", "2026-12-01"),
    ("HD-02", "2026-11-09", "Instagram", "面接実施済み", ""),
    ("HD-02", "2026-11-18", "Indeed", "辞退", ""),
    ("HD-03", "2026-11-14", "スタンバイ", "連絡済み", ""),
    ("HD-03", "2026-12-07", "紹介（スタッフ・知人）", "初回連絡待ち", ""),
    ("GH-02", "2026-12-02", "自社採用サイト", "面接予定", "2026-12-14"),
]

PATH = {
    "初回連絡待ち": [],
    "連絡済み": ["連絡済み"],
    "面接日程調整中": ["連絡済み", "面接日程調整中"],
    "面接予定": ["連絡済み", "面接日程調整中", "面接予定"],
    "面接実施済み": ["連絡済み", "面接予定", "面接実施済み"],
    "内定": ["連絡済み", "面接予定", "面接実施済み", "内定"],
    "内定承諾": ["連絡済み", "面接予定", "面接実施済み", "内定", "内定承諾"],
    "入社予定": ["連絡済み", "面接予定", "面接実施済み", "内定", "内定承諾", "入社予定"],
    "入社済み": ["連絡済み", "面接予定", "面接実施済み", "内定", "内定承諾", "入社予定", "入社済み"],
    "不採用": ["連絡済み", "面接予定", "面接実施済み", "不採用"],
    "辞退": ["連絡済み", "面接予定", "面接実施済み", "内定", "辞退"],
}


def main():
    random.seed(7)
    dest = S.SAMPLE_DIR
    if dest.exists():
        shutil.rmtree(dest)
    st = S.Store(dest)
    st.init()
    jobs = S.load_jobs()
    import datetime as dt

    for n, (job, applied, src, final, rel) in enumerate(PLAN, 1):
        row = A.add_applicant(st, jobs, {"氏名": f"サンプル応募者{n:02d}", "求人ID": job, "応募日": applied,
                                         "応募経路": src, "対応担当者": "採用担当"}, "sample")
        day = dt.date.fromisoformat(applied)
        for step in PATH[final]:
            day += dt.timedelta(days=random.randint(1, 3))
            date = ""
            if step == "面接予定":
                date = rel if final == "面接予定" else (day + dt.timedelta(days=2)).isoformat()
            if step == "入社予定":
                date = rel
            if step == "入社済み":
                date = rel
            A.change_status(st, row["応募者ID"], step, "sample", date=date, at=f"{day} 10:00:00")
    # 媒体の週次数値（架空）
    rows = []
    for week in ("2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"):
        for job, imp, clk in (("HK-01", 820, 31), ("HK-02", 410, 9), ("HK-03", 260, 4), ("HD-01", 350, 12),
                              ("HD-02", 500, 6), ("HD-03", 300, 10)):
            rows.append({"週開始日": week, "媒体": "Indeed", "求人ID": job, "表示数": str(imp + random.randint(-50, 50)),
                         "クリック数": str(clk + random.randint(-3, 3)), "広告費": "0", "メモ": "サンプル"})
    st.save_media_weekly(rows)
    st.save_job_status([{"求人ID": j, "公開状況": "公開確認済み", "公開確認日": "2026-11-02",
                         "確認方法": "サンプル（架空）", "確認者": "sample", "メモ": "", "更新日時": "2026-11-02 12:00:00"}
                        for j in ("HD-01", "HD-02", "HD-03", "HK-01", "HK-02", "HK-03")])
    # 応募日をずらしたので更新日時・ログはサンプル用に固定
    (dest / S.AUDIT_LOG).unlink(missing_ok=True)
    print(f"作成: {dest}（基準日 {SAMPLE_TODAY}）")


if __name__ == "__main__":
    main()
