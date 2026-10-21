"""サンプルデータで一連の流れを確認するテスト。`python3 -m unittest discover tests`"""

import csv
import datetime as dt
import shutil
import tempfile
import unittest
from pathlib import Path

from recruit import applicants as A
from recruit import metrics as M
from recruit import report
from recruit.cli import main
from recruit.jobs import check_all, readiness
from recruit.store import SAMPLE_DIR, Store, load_jobs

TODAY = dt.date(2026, 12, 9)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dir = self.tmp / "data"
        shutil.copytree(SAMPLE_DIR, self.dir)
        self.st = Store(self.dir)
        self.jobs = load_jobs()

    def tearDown(self):
        shutil.rmtree(self.tmp)


class TestFunnel(Base):
    def test_sample_numbers(self):
        s = report.snapshot(self.st, TODAY)
        t = s["total"]
        self.assertEqual(t["応募"], 14)
        # 面接実施 = 面接実施済み以降に一度でも進んだ人（辞退・不採用も含む）
        self.assertEqual(t["面接実施"], 8)
        self.assertEqual(t["内定"], 6)
        # 入社確定 = 内定承諾・入社予定・入社済み（辞退者は含まない）
        self.assertEqual(t["入社確定"], 3)
        self.assertEqual(sum(b["入社確定"] for b in s["business"]), 3)
        self.assertEqual(sum(j["応募"] for j in s["job_rows"]), 14)
        self.assertEqual(sum(m["応募"] for m in s["media"]), 14)

    def test_business_shortfall(self):
        s = report.snapshot(self.st, TODAY)
        by = {b["事業"]: b for b in s["business"]}
        self.assertEqual(by["訪問介護"]["不足"], 2)
        self.assertEqual(by["グループホーム"]["不足"], 3)

    def test_declined_after_offer_not_confirmed(self):
        hidx = M.history_index(self.st.history())
        declined = [a for a in self.st.applicants() if a["選考ステータス"] == "辞退"]
        self.assertTrue(declined)
        f = M.funnel(declined, hidx)
        self.assertEqual(f["入社確定"], 0)
        self.assertGreater(f["内定"], 0)


class TestApplicants(Base):
    def test_add_and_status_history(self):
        row = A.add_applicant(self.st, self.jobs, {"氏名": "テスト 花子", "求人ID": "HD-02", "応募日": "2026/12/9"}, "t")
        self.assertEqual(row["応募日"], "2026-12-09")
        self.assertEqual(row["応募事業"], "放課後等デイサービス")
        with self.assertRaises(A.RecruitError):
            A.change_status(self.st, row["応募者ID"], "面接予定", "t")  # 面接日がない
        A.change_status(self.st, row["応募者ID"], "面接予定", "t", date="2026-12-12")
        hist = [h for h in self.st.history() if h["応募者ID"] == row["応募者ID"]]
        self.assertEqual([h["変更後"] for h in hist], ["初回連絡待ち", "面接予定"])
        self.assertEqual(hist[-1]["変更前"], "初回連絡待ち")

    def test_duplicate_add_rejected(self):
        A.add_applicant(self.st, self.jobs, {"氏名": "重複 一郎", "求人ID": "HK-01", "応募日": "2026-12-01"}, "t")
        with self.assertRaises(A.RecruitError):
            A.add_applicant(self.st, self.jobs, {"氏名": "重複　一郎", "求人ID": "HK-01", "応募日": "2026-12-01"}, "t")

    def test_terminal_requires_force(self):
        a = next(r for r in self.st.applicants() if r["選考ステータス"] == "不採用")
        with self.assertRaises(A.RecruitError):
            A.change_status(self.st, a["応募者ID"], "面接予定", "t", date="2026-12-20")
        A.change_status(self.st, a["応募者ID"], "面接予定", "t", date="2026-12-20", force=True)

    def test_sensitive_note_blocked(self):
        with self.assertRaises(A.RecruitError):
            A.add_applicant(self.st, self.jobs, {"氏名": "a", "求人ID": "HK-01", "申し送り": "持病あり"}, "t")
        a = self.st.applicants()[0]
        with self.assertRaises(A.RecruitError):
            A.update_fields(self.st, a["応募者ID"], {"申し送り": "家族構成を確認"}, "t")
        A.update_fields(self.st, a["応募者ID"], {"申し送り": "普通免許あり。土曜は勤務不可"}, "t")

    def test_unknown_job_rejected(self):
        with self.assertRaises(A.RecruitError):
            A.add_applicant(self.st, self.jobs, {"氏名": "a", "求人ID": "XX-99"}, "t")

    def test_audit_log_has_no_names(self):
        A.add_applicant(self.st, self.jobs, {"氏名": "ログ 確認子", "求人ID": "HK-02"}, "t")
        text = (self.dir / "audit.log").read_text(encoding="utf-8")
        self.assertNotIn("ログ 確認子", text)

    def test_validate_clean_sample(self):
        self.assertEqual([p for p in A.validate(self.st, self.jobs) if "参考" not in p], [])


class TestImport(Base):
    def write(self, rows, enc="utf-8-sig"):
        p = self.tmp / "in.csv"
        with p.open("w", encoding=enc, newline="") as f:
            w = csv.writer(f)
            w.writerows(rows)
        return p

    def test_import_dedupe_and_mapping(self):
        p = self.write([
            ["応募者名", "求人番号", "応募日時", "応募番号"],
            ["取込 太郎", "HK-01", "2026/12/08 10:15", "K-1"],
            ["取込 太郎", "HK-01", "2026/12/08 10:15", "K-1"],      # 同じCSV内の重複
            ["サンプル応募者01", "HK-01", "2026-11-03", ""],        # 登録済み
            ["", "HK-01", "2026-12-08", ""],                          # 氏名なし
        ], enc="cp932")
        mapping = {"応募者名": "氏名", "求人番号": "求人ID", "応募日時": "応募日", "応募番号": "外部応募番号"}
        plan = A.plan_import(self.st, self.jobs, A.read_import_file(p, mapping))
        self.assertEqual(len(plan["new"]), 1)
        self.assertEqual(len(plan["duplicates"]), 2)
        self.assertEqual(len(plan["errors"]), 1)
        before = len(self.st.applicants())
        ids = A.apply_import(self.st, plan, "t", "in.csv")
        self.assertEqual(len(self.st.applicants()), before + 1)
        self.assertEqual(len(ids), 1)
        self.assertTrue(self.st.backups())  # 取込前に自動バックアップ
        # 2回目は全部重複
        plan2 = A.plan_import(self.st, self.jobs, A.read_import_file(p, mapping))
        self.assertEqual(len(plan2["new"]), 0)


class TestBackupRestore(Base):
    def test_delete_then_restore(self):
        aid = self.st.applicants()[0]["応募者ID"]
        A.delete_applicant(self.st, aid, "t")
        self.assertNotIn(aid, [r["応募者ID"] for r in self.st.applicants()])
        self.st.restore(self.st.backups()[-1])
        self.assertIn(aid, [r["応募者ID"] for r in self.st.applicants()])


class TestJobs(unittest.TestCase):
    def test_ten_slots_and_targets(self):
        res = check_all(load_jobs())
        self.assertEqual(res["slot_count"], 10)
        self.assertEqual(res["target_total"], 10)
        self.assertEqual(res["duplicates"], [])

    def test_unconfirmed_jobs_not_publishable(self):
        for j in load_jobs():
            self.assertNotEqual(readiness(j), "公開可", j["job_id"])  # 現時点で確定済みの求人はない

    def test_drafts_have_no_banned_phrases(self):
        for r in check_all(load_jobs())["jobs"]:
            banned = [p for p in r["draft"] if "—" in p]
            self.assertEqual(banned, [], r["job"]["job_id"])


class TestReportsAndCli(Base):
    def test_report_has_no_names(self):
        out = self.tmp / "out"
        files = report.weekly(self.st, TODAY, out, ["md", "csv"])
        for f in files:
            text = f.read_text(encoding="utf-8-sig")
            self.assertNotIn("サンプル応募者", text)
        md = files[0].read_text(encoding="utf-8")
        self.assertIn("翌週の行動計画", md)

    def test_dashboard_hides_names_by_default(self):
        from recruit import dashboard
        html = dashboard.build(self.st, TODAY)
        self.assertNotIn("サンプル応募者", html)
        self.assertIn("サンプル応募者", dashboard.build(self.st, TODAY, show_names=True))

    def test_publish_requires_method(self):
        self.assertEqual(main(["--data-dir", str(self.dir), "publish", "GH-01", "公開確認済み"]), 2)
        self.assertEqual(main(["--data-dir", str(self.dir), "publish", "GH-01", "公開確認済み",
                               "--method", "ログアウト状態でIndeed検索し表示を確認"]), 0)
        self.assertEqual({j["job_id"]: j for j in self.st.jobs()}["GH-01"]["publish_status"], "公開確認済み")

    def test_cli_status_and_media(self):
        aid = next(r for r in self.st.applicants() if r["選考ステータス"] == "初回連絡待ち")["応募者ID"]
        self.assertEqual(main(["--data-dir", str(self.dir), "status", aid, "連絡済み", "--note", "電話"]), 0)
        self.assertEqual(main(["--data-dir", str(self.dir), "media", "--week", "2026-12-09", "--media", "Indeed",
                               "--job", "HK-01", "--impressions", "500", "--clicks", "20", "-y"]), 0)
        self.assertEqual(main(["--data-dir", str(self.dir), "status", aid, "入社済み"]), 2)  # 入社日なし


if __name__ == "__main__":
    unittest.main()
