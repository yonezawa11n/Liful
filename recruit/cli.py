"""コマンド: python3 -m recruit <コマンド>（一覧は python3 -m recruit -h）"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from . import applicants as A
from . import dashboard, report
from . import metrics as M
from .constants import PUBLISH_STATES, STATUSES
from .jobs import check_all
from .store import OUTPUT_DIR, SAMPLE_DIR, Store, data_dir, load_jobs, load_settings, now


def actor(args) -> str:
    return args.by or os.environ.get("RECRUIT_OPERATOR") or getpass.getuser()


def confirm(args, message: str) -> bool:
    if getattr(args, "yes", False):
        return True
    try:
        return input(f"{message} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def today(args) -> dt.date:
    return A.parse_date(args.today) if getattr(args, "today", None) else dt.date.today()


def open_store(args, must_exist=True) -> Store:
    st = Store(data_dir(args.data_dir))
    if must_exist and not st.exists():
        raise A.RecruitError(f"データフォルダがありません: {st.dir}\n→ 先に `python3 -m recruit init` を実行してください")
    return st


# ---------------- コマンド ----------------

def cmd_init(args):
    st = open_store(args, must_exist=False)
    if st.exists():
        print(f"すでにあります: {st.dir}（何も変更していません）")
        return
    st.init()
    st.log(actor(args), "init", str(st.dir))
    print(f"作成しました: {st.dir}（このフォルダは Git に入りません）")


def cmd_demo(args):
    dest = Path(args.data_dir or (OUTPUT_DIR / "demo-data"))
    if dest.exists():
        if not confirm(args, f"{dest} を作り直します。よろしいですか？"):
            print("中止しました")
            return
        shutil.rmtree(dest)
    shutil.copytree(SAMPLE_DIR, dest)
    st = Store(dest)
    t = today(args) if args.today else dt.date(2026, 12, 9)  # サンプルデータの基準日
    out = OUTPUT_DIR / "demo"
    dashboard.write(st, t, out / "dashboard.html", sample=True)
    files = report.weekly(st, t, out, ["md", "csv", "xlsx"])
    print(f"サンプルデータ: {dest}")
    print(f"ダッシュボード: {out / 'dashboard.html'}")
    for f in files:
        print(f"レポート: {f}")


def cmd_add(args):
    st = open_store(args)
    row = A.add_applicant(st, load_jobs(), {
        "氏名": args.name, "求人ID": args.job, "応募日": args.date or "", "応募経路": args.source or "",
        "外部応募番号": args.ref or "", "対応担当者": args.owner or "", "申し送り": args.note or "",
        "次回対応日": args.next_date or "", "次回対応内容": args.next_action or "",
    }, actor(args))
    print(f"登録しました: {row['応募者ID']}（{row['求人ID']} / {row['選考ステータス']}）")


def cmd_status(args):
    st = open_store(args)
    row = A.change_status(st, args.id, args.new, actor(args), note=args.note or "", date=args.date or "",
                          force=args.force)
    print(f"{row['応募者ID']}: {row['選考ステータス']} に変更しました（履歴に記録）")


def cmd_update(args):
    st = open_store(args)
    changes = {}
    for kv in args.set:
        if "=" not in kv:
            raise A.RecruitError(f"「項目=値」の形で指定してください: {kv}")
        k, v = kv.split("=", 1)
        changes[k.strip()] = v.strip()
    row = A.update_fields(st, args.id, changes, actor(args))
    print(f"{row['応募者ID']}: 更新しました（{', '.join(changes)}）")


def cmd_delete(args):
    st = open_store(args)
    if not confirm(args, f"{args.id} を削除します（バックアップを取ってから削除）。よろしいですか？"):
        print("中止しました")
        return
    A.delete_applicant(st, args.id, actor(args))
    print(f"{args.id} を削除しました。戻す場合は `python3 -m recruit restore` でバックアップから戻せます")


def cmd_import(args):
    st = open_store(args)
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
    incoming = A.read_import_file(Path(args.file), mapping)
    if args.source:
        for r in incoming:
            r["応募経路"] = r.get("応募経路") or args.source
    plan = A.plan_import(st, load_jobs(), incoming)
    print(f"読み込み: {len(incoming)}行 → 追加 {len(plan['new'])}件 / 重複 {len(plan['duplicates'])}件 / エラー {len(plan['errors'])}件")
    for line, dup in plan["duplicates"]:
        print(f"  重複（追加しない）: {line}行目 = 登録済み {dup}")
    for line, msg in plan["errors"]:
        print(f"  エラー（追加しない）: {line}行目 {msg}")
    for line in plan["similar"]:
        print(f"  注意: {line}行目は同じ氏名の別応募があります（同一人物か確認。自動では統合しません）")
    if args.dry_run or not plan["new"]:
        print("（保存していません）")
        return
    if not confirm(args, f"{len(plan['new'])}件を追加します。よろしいですか？"):
        print("中止しました")
        return
    ids = A.apply_import(st, plan, actor(args), Path(args.file).name)
    print(f"追加しました: {', '.join(ids)}")


def cmd_list(args):
    st = open_store(args)
    rows = st.applicants()
    if args.status:
        rows = [r for r in rows if r["選考ステータス"] == args.status]
    if args.job:
        rows = [r for r in rows if r["求人ID"] == args.job]
    for r in rows:
        name = r["氏名"] if args.show_names else ""
        print(f"{r['応募者ID']}\t{r['求人ID']}\t{r['応募日']}\t{r['選考ステータス']}\t{r['応募経路']}\t"
              f"次回:{r['次回対応日'] or '-'} {r['次回対応内容']}\t{name}")
    print(f"計 {len(rows)}件")


def cmd_tasks(args):
    st = open_store(args)
    td = M.todo(st.applicants(), today(args), load_settings())
    for k, items in td.items():
        print(f"■ {k}: {len(items)}件")
        for a in items:
            name = f" {a['氏名']}" if args.show_names else ""
            print(f"   {a['応募者ID']}{name}（{a['求人ID']}・応募 {a['応募日']}）面接:{a['面接予定日'] or '-'} 次回:{a['次回対応日'] or '-'} {a['次回対応内容']}")


def cmd_report(args):
    st = open_store(args)
    out = Path(args.out) if args.out else OUTPUT_DIR / "reports"
    files = report.weekly(st, today(args), out, args.format.split(","))
    for f in files:
        print(f"作成: {f}")
    if "xlsx" in args.format and not any(str(f).endswith(".xlsx") for f in files):
        print("Excel は openpyxl が必要です（pip3 install openpyxl）。Markdown・CSV は作成済み")


def cmd_dashboard(args):
    st = open_store(args)
    out = Path(args.out) if args.out else OUTPUT_DIR / "dashboard.html"
    dashboard.write(st, today(args), out, show_names=args.show_names)
    print(f"作成: {out}（ブラウザで開いてください）")
    if args.show_names:
        print("※氏名入りです。共有・アップロードしないでください")


def cmd_diagnose(args):
    st = open_store(args)
    s = report.snapshot(st, today(args))
    if not s["findings"]:
        print("改善提案なし（公開確認済みの求人の数字がまだ少ないか、問題が見つかりませんでした）")
    for f in s["findings"]:
        print(f"■ {f['求人ID']} {f['職種']} — {f['症状']}（{f['根拠']}）")
        for a in f["改善案"]:
            print(f"   - {a}")
    print("\n※提案のみ。求人の変更・公開は社長の承認後に行ってください。")


def cmd_publish(args):
    """求人の公開状況を記録する。公開・停止の操作そのものは社長が採用係長で行う。"""
    st = open_store(args)
    jobs = {j["job_id"]: j for j in load_jobs()}
    if args.job not in jobs:
        raise A.RecruitError(f"求人ID {args.job} は求人マスタにありません")
    if args.state == "公開確認済み" and not args.method:
        raise A.RecruitError(
            "公開確認済みにするには --method で確認方法を書いてください"
            "（例: 'ログアウト状態のIndeedで「訪問介護 町田市」検索し表示を確認'）。"
            "\n管理画面で「公開中」と表示されているだけでは公開確認済みにしません。")
    rows = [r for r in st.job_status() if r["求人ID"] != args.job]
    rows.append({"求人ID": args.job, "公開状況": args.state,
                 "公開確認日": (A.norm_date(args.date) or dt.date.today().isoformat()) if args.state == "公開確認済み" else "",
                 "確認方法": args.method or "", "確認者": actor(args), "メモ": args.note or "",
                 "更新日時": now()})
    rows.sort(key=lambda r: r["求人ID"])
    st.save_job_status(rows)
    st.log(actor(args), "publish", args.job, args.state)
    print(f"{args.job}: 公開状況を「{args.state}」として記録しました")


def cmd_jobs(args):
    st = Store(data_dir(args.data_dir))
    res = check_all(st.jobs() if st.exists() else load_jobs())
    print(f"求人枠: {res['slot_count']}件（採用係長の上限10件） / 目標人数の合計: {res['target_total']}人")
    for r in res["jobs"]:
        j = r["job"]
        st = r["states"]
        print(f"\n[{j['slot']}] {j['job_id']} {j['role']} — 目標 {j.get('target_hires', 0)}人")
        print(f"   公開状況: {j['publish_status']} ／ 公開準備: {r['readiness']} ／ "
              f"確定 {st.get('確定', 0)}・HP記載 {st.get('HP記載', 0)}・要確認 {st.get('要確認', 0)}・構想 {st.get('構想', 0)}")
        if args.verbose:
            for k, state, v in r["unresolved"]:
                print(f"   - {state}: {k} … {v}")
        for p in r["draft"]:
            print(f"   ! {p}")
    if res["duplicates"]:
        print("\n重複のおそれ:")
        for d in res["duplicates"]:
            print(f"  ! {d}")
    if res["slot_count"] > 10:
        print("\n! 求人枠が10件を超えています")


def cmd_checklist(args):
    from .jobs import checklist_markdown
    from .store import MASTER_DIR, ROOT, load_json
    conflicts = load_json(MASTER_DIR / "hp_conflicts.json")["conflicts"]
    out = Path(args.out) if args.out else ROOT / "docs" / "確認事項リスト.md"
    out.write_text(checklist_markdown(load_jobs(), conflicts), encoding="utf-8")
    print(f"作成: {out}")


def cmd_validate(args):
    st = open_store(args)
    probs = A.validate(st, load_jobs())
    if not probs:
        print("問題は見つかりませんでした")
    for p in probs:
        print(f"! {p}")
    sys.exit(1 if any("参考" not in p for p in probs) else 0)


def cmd_backup(args):
    st = open_store(args)
    p = st.backup("manual")
    st.log(actor(args), "backup", p.name if p else "")
    print(f"バックアップ: {p}")


def cmd_restore(args):
    st = open_store(args)
    items = st.backups()
    if not items:
        print("バックアップがありません")
        return
    if not args.name:
        for b in items[-10:]:
            print(b.name)
        print("戻すには: python3 -m recruit restore <上のフォルダ名>")
        return
    target = st.dir / "backups" / args.name
    if not target.exists():
        raise A.RecruitError(f"見つかりません: {args.name}")
    if not confirm(args, f"今のデータを {args.name} の状態に戻します（今のデータもバックアップします）。よろしいですか？"):
        print("中止しました")
        return
    st.backup("before-restore")
    st.restore(target)
    st.log(actor(args), "restore", args.name)
    print("戻しました")


def cmd_media(args):
    st = open_store(args)
    rows = st.media_weekly()
    ws = report.week_start(A.parse_date(args.week))
    for r in rows:
        if r["週開始日"] == ws.isoformat() and r["媒体"] == args.media and r["求人ID"] == args.job:
            if not confirm(args, "同じ週・媒体・求人の記録があります。上書きしますか？"):
                print("中止しました")
                return
            rows.remove(r)
            break
    rows.append({"週開始日": ws.isoformat(), "媒体": args.media, "求人ID": args.job,
                 "表示数": str(args.impressions or ""), "クリック数": str(args.clicks or ""),
                 "広告費": str(args.cost or 0), "メモ": args.note or ""})
    rows.sort(key=lambda r: (r["週開始日"], r["媒体"], r["求人ID"]))
    st.save_media_weekly(rows)
    st.log(actor(args), "media", f"{ws} {args.media} {args.job}")
    print(f"記録しました: {ws} 週 {args.media} {args.job}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m recruit", description="NewValley 採用管理ツール")
    p.add_argument("--data-dir", help="応募者データのフォルダ（既定: private/ または環境変数 RECRUIT_DATA_DIR）")
    p.add_argument("--by", help="操作者名（既定: 環境変数 RECRUIT_OPERATOR）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def sp(name, fn, help_):
        x = sub.add_parser(name, help=help_)
        x.set_defaults(fn=fn)
        return x

    sp("init", cmd_init, "応募者データのフォルダを作る（初回だけ）")
    x = sp("demo", cmd_demo, "サンプルデータでダッシュボードとレポートを作る")
    x.add_argument("--today")
    x.add_argument("-y", "--yes", action="store_true")

    x = sp("add", cmd_add, "応募者を1件登録")
    x.add_argument("--name", required=True, help="氏名")
    x.add_argument("--job", required=True, help="求人ID（例: HK-01）")
    x.add_argument("--date", help="応募日（既定: 今日）")
    x.add_argument("--source", help="応募経路（例: 採用係長, Indeed, 公式LINE）")
    x.add_argument("--ref", help="外部応募番号（採用係長などの応募番号）")
    x.add_argument("--owner", help="対応担当者")
    x.add_argument("--note", help="申し送り（業務上必要な事実だけ）")
    x.add_argument("--next-date")
    x.add_argument("--next-action")

    x = sp("status", cmd_status, "選考ステータスを変更（履歴に残る）")
    x.add_argument("id")
    x.add_argument("new", choices=STATUSES, metavar="新ステータス", help=" / ".join(STATUSES))
    x.add_argument("--date", help="面接予定日・内定日・入社予定日・入社日")
    x.add_argument("--note")
    x.add_argument("--force", action="store_true", help="終了ステータスから戻す時だけ")

    x = sp("update", cmd_update, "項目を更新（例: 次回対応日=2026-11-10）")
    x.add_argument("id")
    x.add_argument("set", nargs="+", metavar="項目=値")

    x = sp("delete", cmd_delete, "応募者を削除（確認あり・自動バックアップ）")
    x.add_argument("id")
    x.add_argument("-y", "--yes", action="store_true")

    x = sp("import", cmd_import, "CSV から取込（重複は自動でスキップ）")
    x.add_argument("file")
    x.add_argument("--mapping", help="列名の読み替え JSON（例: data/import_mapping.example.json）")
    x.add_argument("--source", help="応募経路が空の行に入れる値")
    x.add_argument("--dry-run", action="store_true", help="下見だけ（保存しない）")
    x.add_argument("-y", "--yes", action="store_true")

    x = sp("list", cmd_list, "応募者一覧")
    x.add_argument("--status")
    x.add_argument("--job")
    x.add_argument("--show-names", action="store_true")

    x = sp("tasks", cmd_tasks, "今日やること（連絡待ち・日程調整待ち・内定回答待ちなど）")
    x.add_argument("--today")
    x.add_argument("--show-names", action="store_true")

    x = sp("report", cmd_report, "週次レポート（Markdown / CSV / Excel）")
    x.add_argument("--today", help="この日を含む週のレポート（既定: 今日）")
    x.add_argument("--format", default="md,csv,xlsx")
    x.add_argument("--out")

    x = sp("dashboard", cmd_dashboard, "ダッシュボード（HTML）を作る")
    x.add_argument("--today")
    x.add_argument("--out")
    x.add_argument("--show-names", action="store_true", help="氏名を表示（このPCで見る時だけ）")

    x = sp("diagnose", cmd_diagnose, "求人ごとの改善提案")
    x.add_argument("--today")

    x = sp("jobs", cmd_jobs, "求人10枠のチェック（要確認・重複・禁止表現）")
    x.add_argument("-v", "--verbose", action="store_true", help="要確認の中身も表示")

    x = sp("publish", cmd_publish, "求人の公開状況を記録（公開確認済みは確認方法が必須）")
    x.add_argument("job")
    x.add_argument("state", choices=PUBLISH_STATES, metavar="状態", help=" / ".join(PUBLISH_STATES))
    x.add_argument("--method", help="公開を確認した方法（求職者側の画面で見たこと）")
    x.add_argument("--date", help="確認日（既定: 今日）")
    x.add_argument("--note")

    x = sp("checklist", cmd_checklist, "事業責任者向けの確認事項リスト（docs/確認事項リスト.md）を作る")
    x.add_argument("--out")

    sp("validate", cmd_validate, "応募者データの検証（重複・欠損・センシティブ情報）")
    sp("backup", cmd_backup, "バックアップを取る")
    x = sp("restore", cmd_restore, "バックアップから戻す（確認あり）")
    x.add_argument("name", nargs="?")
    x.add_argument("-y", "--yes", action="store_true")

    x = sp("media", cmd_media, "媒体の週次数値（表示数・クリック数・広告費）を記録")
    x.add_argument("--week", required=True, help="その週のどれかの日付")
    x.add_argument("--media", required=True, help="媒体名（例: Indeed）")
    x.add_argument("--job", required=True, help="求人ID")
    x.add_argument("--impressions", type=int)
    x.add_argument("--clicks", type=int)
    x.add_argument("--cost", type=int, default=0)
    x.add_argument("--note")
    x.add_argument("-y", "--yes", action="store_true")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except A.RecruitError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0
