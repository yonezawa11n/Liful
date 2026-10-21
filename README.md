# NewValley 採用管理（採用業務統合プロジェクト）

2027年2月末までに10人（訪問介護4・放課後等デイ3・グループホーム3）を採用するための、求人・応募者・進捗の管理ツールと資料一式です。

- 計画: [PROJECT_PLAN.md](PROJECT_PLAN.md)
- 環境調査と構成: [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)
- タスク: [TASKS.md](TASKS.md)／リスク: [RISKS.md](RISKS.md)
- 使い方: [docs/運用マニュアル.md](docs/運用マニュアル.md)
- 事業責任者への確認事項: [docs/確認事項リスト.md](docs/確認事項リスト.md)
- 求人原稿（10枠）: [jobs/drafts/](jobs/drafts/)
- 媒体戦略: [docs/媒体戦略.md](docs/媒体戦略.md)／SNS: [docs/SNS採用計画.md](docs/SNS採用計画.md)

## 起動方法

Python 3.9 以上（Mac 標準の `python3` で動きます。Excel 出力だけ `pip3 install openpyxl` が必要）。

```bash
python3 -m recruit demo          # サンプルデータでダッシュボードとレポートを作る（output/demo/）
python3 -m recruit init          # 本番の応募者データフォルダ private/ を作る（初回のみ）
python3 -m recruit -h            # コマンド一覧
```

| よく使うコマンド | 内容 |
|---|---|
| `add --name 氏名 --job HK-01 --source Indeed` | 応募者を登録 |
| `status A0001 面接予定 --date 2026-11-10` | 選考ステータスを変更（履歴に残る） |
| `tasks` | 今日やること（初回連絡の遅れ・日程調整待ち・内定回答待ちなど） |
| `dashboard` | ダッシュボード（output/dashboard.html、氏名は非表示） |
| `report` | 週次レポート（Markdown・CSV・Excel、氏名なし） |
| `diagnose` | 求人ごとの改善案 |
| `jobs -v` | 求人10枠のチェック（要確認・重複・禁止表現） |
| `checklist` | 事業責任者向けの確認事項リストを作り直す |
| `publish HK-01 公開確認済み --method "..."` | 求人の公開状況を記録 |
| `import file.csv --mapping m.json --dry-run` | CSV 取込（重複は自動でスキップ） |
| `media --week 2026-11-09 --media Indeed --job HK-01 --impressions 800 --clicks 30` | 媒体の数値を記録 |
| `validate` / `backup` / `restore` | 検証・バックアップ・復元 |

## テスト

```bash
python3 -m unittest discover tests      # サンプルデータで一連の流れを確認
python3 scripts/make_sample.py          # サンプルデータを作り直す（架空の応募者）
```

## 大事なルール
- 応募者データ（`private/`）とレポート類（`output/`）は Git に入りません。GitHub に上げないでください。
- 採用係長などのパスワードはこのツールでは使いません。ファイルやチャットに書かないでください。
- 求人の公開・変更、有料広告、応募者への連絡、内定・採否は人が判断します（ツールは記録と提案だけ）。
- 確定していない求人条件は【要確認】のまま。推測で埋めません。
