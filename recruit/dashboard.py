"""採用管理ダッシュボード（1ファイルのHTML。外部通信なし）。

既定では氏名を出さない（応募者IDのみ）。--show-names はこのPCで見る時だけ使う。
"""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from . import metrics as M
from .constants import BUSINESS_LABEL
from .report import issues_and_actions, snapshot
from .store import Store, load_schedule

CSS = """
:root{color-scheme:light;--bg:#f6f5f2;--surface:#fcfcfb;--line:#e4e2dc;--text:#0b0b0b;--text2:#52514e;--muted:#8a8984;
--s1:#2a78d6;--track:#e9e7e1;--good:#0ca30c;--warn:#fab219;--serious:#ec835a;--crit:#d03b3b;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--line:#2f2f2c;--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;--s1:#3987e5;--track:#2b2b28;--chip:#262624}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--line:#2f2f2c;--text:#f0efec;--text2:#c3c2b7;
--muted:#8f8e86;--s1:#3987e5;--track:#2b2b28;--chip:#262624}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",Meiryo,system-ui,sans-serif;font-size:14px;line-height:1.6}
main{max-width:1120px;margin:0 auto;padding-block:20px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between;margin-bottom:16px}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 12px}
.meta{color:var(--text2);font-size:13px}
.grid{display:grid;gap:12px}.kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.two{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}
.kpi .label{color:var(--text2);font-size:12px}.kpi .value{font-size:28px;font-weight:700;line-height:1.2}
.kpi .sub{color:var(--text2);font-size:12px}
section{margin-top:12px}
.row{display:grid;grid-template-columns:minmax(110px,180px) 1fr auto;gap:10px;align-items:center;margin:8px 0}
.row .name{font-size:13px;color:var(--text2)}.row .num{font-variant-numeric:tabular-nums;font-size:13px;white-space:nowrap}
.bar{position:relative;height:14px;background:var(--track);border-radius:4px;cursor:default}
.bar .fill{position:absolute;left:0;top:0;bottom:0;background:var(--s1);border-radius:4px}
.bar .target{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--text)}
.status{display:inline-flex;gap:4px;align-items:center;font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip);white-space:nowrap}
.status i{width:8px;height:8px;border-radius:50%;display:inline-block}
.good i{background:var(--good)}.warn i{background:var(--warn)}.serious i{background:var(--serious)}.crit i{background:var(--crit)}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{color:var(--text2);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
ul.tasks{margin:0;padding-left:18px}ul.tasks li{margin:2px 0}
.empty{color:var(--muted)}.note{color:var(--text2);font-size:12px;margin-top:8px}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);font-size:12px;padding:4px 8px;border-radius:6px;display:none;z-index:9;max-width:260px}
.sample{background:var(--warn);color:#0b0b0b;padding:6px 12px;border-radius:8px;font-weight:600;margin-bottom:12px}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('mousemove',e=>{tip.textContent=el.dataset.tip;tip.style.display='block';
  tip.style.left=Math.min(e.clientX+12,innerWidth-270)+'px';tip.style.top=(e.clientY+14)+'px'});
 el.addEventListener('mouseleave',()=>tip.style.display='none');
 el.addEventListener('focus',()=>{const r=el.getBoundingClientRect();tip.textContent=el.dataset.tip;tip.style.display='block';tip.style.left=r.left+'px';tip.style.top=(r.bottom+6)+'px'});
 el.addEventListener('blur',()=>tip.style.display='none');
});
"""


def e(x) -> str:
    return html.escape(str(x))


def status_chip(level: str, text: str) -> str:
    return f'<span class="status {level}"><i aria-hidden="true"></i>{e(text)}</span>'


def bar_row(name: str, value: float, target: float, scale: float, label: str, tip: str, marker: float | None = None) -> str:
    w = 0 if not scale else min(value / scale, 1) * 100
    mk = "" if marker is None or not scale else f'<span class="target" style="left:calc({min(marker / scale, 1) * 100:.1f}% - 1px)"></span>'
    return (f'<div class="row"><span class="name">{e(name)}</span>'
            f'<span class="bar" tabindex="0" data-tip="{e(tip)}" role="img" aria-label="{e(tip)}">'
            f'<span class="fill" style="width:{w:.1f}%"></span>{mk}</span>'
            f'<span class="num">{e(label)}</span></div>')


def person(a: dict, show_names: bool) -> str:
    who = f"{a['応募者ID']} {a['氏名']}" if show_names else a["応募者ID"]
    extra = []
    if a["面接予定日"] and a["選考ステータス"] == "面接予定":
        extra.append(f"面接 {a['面接予定日']}")
    if a["入社予定日"]:
        extra.append(f"入社 {a['入社予定日']}")
    if a["次回対応日"]:
        extra.append(f"次回 {a['次回対応日']} {a['次回対応内容']}")
    return f"<li>{e(who)}（{e(a['求人ID'])}・応募 {e(a['応募日'])}）{e(' / '.join(extra))}</li>"


def build(store: Store, today: dt.date, show_names: bool = False, sample: bool = False) -> str:
    s = snapshot(store, today)
    t, p, ft = s["total"], s["pace"], s["settings"]["funnel_targets"]

    def kpi(label, value, sub):
        return f'<div class="card kpi"><div class="label">{e(label)}</div><div class="value">{e(value)}</div><div class="sub">{e(sub)}</div></div>'

    def pace_chip(actual, plan):
        if plan == 0:
            return ""
        return status_chip("good", "計画どおり") if actual >= plan else status_chip("warn", f"計画比 {actual - plan:+.1f}")

    kpis = "".join([
        kpi("応募（累計）", t["応募"], f"目標 {ft['応募']}／今週 {s['week']['応募']}"),
        kpi("面接予定", t["面接予定"], f"来週 {s['week']['面接予定_翌週']}件"),
        kpi("面接実施", t["面接実施"], f"目標 {ft['面接実施']}"),
        kpi("内定", t["内定"], f"目標 {ft['内定']}"),
        kpi("入社確定", f"{t['入社確定']} / {ft['入社確定']}", f"あと {max(ft['入社確定'] - t['入社確定'], 0)}人"),
        kpi("採用期限まで", f"{p['days_left']}日", "2027年2月末"),
    ])

    biz_max = max([b["目標"] for b in s["business"]] + [b["入社確定"] for b in s["business"]] + [1])
    biz = "".join(
        bar_row(BUSINESS_LABEL[b["事業"]], b["入社確定"], b["目標"], biz_max,
                f"{b['入社確定']} / {b['目標']}人（不足 {b['不足']}）",
                f"{BUSINESS_LABEL[b['事業']]}: 入社確定 {b['入社確定']}人／目標 {b['目標']}人・応募 {b['_funnel']['応募']}・面接 {b['_funnel']['面接実施']}・内定 {b['_funnel']['内定']}",
                marker=b["目標"])
        for b in s["business"])

    stages = [("応募", t["応募"], ft["応募"], p["応募"]), ("面接実施", t["面接実施"], ft["面接実施"], p["面接実施"]),
              ("内定", t["内定"], ft["内定"], p["内定"]), ("入社確定", t["入社確定"], ft["入社確定"], p["入社確定"])]
    fmax = max([x[2] for x in stages] + [x[1] for x in stages] + [1])
    fun = "".join(
        bar_row(n, v, tg, fmax, f"{v} / {tg}", f"{n}: 実績 {v}・最終目標 {tg}・今日時点の計画 {pl}", marker=pl) + ""
        for n, v, tg, pl in stages)
    fun += '<p class="note">棒＝実績、縦線＝今日時点の計画ペース（期間で直線按分した目安）。' + \
        " ".join(pace_chip(v, pl) for n, v, tg, pl in stages[:1]) + "</p>"

    task_html = ""
    for k, items in s["todo"].items():
        body = "".join(person(a, show_names) for a in items) or '<li class="empty">なし</li>'
        level = "crit" if k == "初回連絡が遅れている" and items else "warn" if items else "good"
        task_html += f'<div class="card"><h2>{status_chip(level, f"{len(items)}件")} {e(k)}</h2><ul class="tasks">{body}</ul></div>'

    jrows = ""
    for j in s["job_rows"]:
        rd = s["readiness"][j["求人ID"]]
        lv = "good" if j["公開状況"] == "公開確認済み" else "crit" if rd.startswith("公開不可") else "warn"
        jrows += (f"<tr><td class='n'>{j['枠']}</td><td>{e(j['求人ID'])}</td><td>{e(j['職種'])}</td>"
                  f"<td>{status_chip(lv, j['公開状況'])}</td><td>{e(rd)}</td>"
                  + "".join(f"<td class='n'>{'—' if j[k] is None else j[k]}</td>" for k in ("表示数", "クリック数", "応募", "面接実施", "内定", "入社確定", "目標", "不足"))
                  + "</tr>")

    mrows = ""
    for m in s["media"]:
        lv = "good" if m["連携状況"] in ("連携確認済み", "利用中") else "warn"
        cph = "—" if m["採用単価"] is None else f"{m['採用単価']:,.0f}円"
        mrows += (f"<tr><td>{e(m['媒体'])}</td><td>{status_chip(lv, m['連携状況'])}</td>"
                  f"<td class='n'>{'—' if m['表示数'] is None else m['表示数']}</td><td class='n'>{'—' if m['クリック数'] is None else m['クリック数']}</td>"
                  f"<td class='n'>{m['応募']}</td><td class='n'>{m['面接実施']}</td><td class='n'>{m['入社確定']}</td>"
                  f"<td class='n'>{m['広告費']:,}円</td><td class='n'>{cph}</td></tr>")

    issues, actions = issues_and_actions(s)
    find = "".join(f"<li><b>{e(f['求人ID'])} {e(f['症状'])}</b>（{e(f['根拠'])}）: {e(f['改善案'][0])}</li>" for f in s["findings"]) \
        or '<li class="empty">公開確認済みの求人の数字がそろうと表示されます</li>'
    act = "".join(f"<li>{e(a)}</li>" for a in actions) or '<li class="empty">なし</li>'

    sched = ""
    for ph in load_schedule():
        a, b = dt.date.fromisoformat(ph["開始日"]), dt.date.fromisoformat(ph["終了日"])
        now_flag = status_chip("good", "今ここ") if a <= today <= b else ""
        sched += f"<tr><td>{a:%m/%d}〜{b:%m/%d}</td><td>{e(ph['フェーズ'])} {now_flag}</td><td style='white-space:normal'>{e(ph['主な作業'])}</td></tr>"

    banner = '<div class="sample">サンプルデータです（実在の応募者ではありません）</div>' if sample else ""
    phase = s["phase"]["フェーズ"] if s["phase"] else "—"
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>NewValley 採用ダッシュボード</title><style>{CSS}</style></head><body><main>
{banner}
<header><h1>NewValley 採用ダッシュボード</h1>
<span class="meta">{today:%Y年%m月%d日} 時点／フェーズ: {e(phase)}／{'氏名を表示中（この画面を共有しない）' if show_names else '氏名は非表示（応募者IDのみ）'}</span></header>
<div class="grid kpis">{kpis}</div>
<section class="grid two">
<div class="card"><h2>事業別の入社確定（目標 合計{sum(b['目標'] for b in s['business'])}人）</h2>{biz}
<p class="note">縦線＝目標人数</p></div>
<div class="card"><h2>採用ファネル</h2>{fun}</div>
</section>
<section><h2 style="margin:16px 0 8px">次に対応すること</h2><div class="grid two">{task_html}</div></section>
<section class="card"><h2>翌週の行動（提案）</h2><ol class="tasks">{act}</ol>
<h2 style="margin-top:16px">求人の改善提案</h2><ul class="tasks">{find}</ul>
<p class="note">求人の変更・公開・有料広告は社長の承認後に行います。</p></section>
<section class="card"><h2>求人別（採用係長 10枠）</h2><div class="tablewrap"><table>
<thead><tr><th class="n">枠</th><th>求人ID</th><th>職種</th><th>公開状況</th><th>公開準備</th><th class="n">表示</th><th class="n">クリック</th>
<th class="n">応募</th><th class="n">面接</th><th class="n">内定</th><th class="n">確定</th><th class="n">目標</th><th class="n">不足</th></tr></thead>
<tbody>{jrows}</tbody></table></div>
<p class="note">「公開確認済み」は求職者側の画面で表示を確認できた求人だけです。</p></section>
<section class="card"><h2>媒体別</h2><div class="tablewrap"><table>
<thead><tr><th>媒体</th><th>連携状況</th><th class="n">表示</th><th class="n">クリック</th><th class="n">応募</th><th class="n">面接</th><th class="n">入社確定</th><th class="n">広告費</th><th class="n">採用単価</th></tr></thead>
<tbody>{mrows}</tbody></table></div></section>
<section class="card"><h2>採用スケジュール</h2><div class="tablewrap"><table><thead><tr><th>期間</th><th>フェーズ</th><th>主な作業</th></tr></thead>
<tbody>{sched}</tbody></table></div></section>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""


def write(store: Store, today: dt.date, out: Path, show_names: bool = False, sample: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(store, today, show_names, sample), encoding="utf-8")
    return out
