#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生 cb_dashboard.html:表格 + 點列顯示歷史溢價走勢圖(近120個交易日)"""
import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DB = BASE / "cb_monitor.db"
OUT = BASE / "cb_dashboard.html"

conn = sqlite3.connect(DB)
snap = conn.execute("SELECT MAX(snapshot_date) FROM cb_master").fetchone()[0]
master = pd.read_sql("SELECT * FROM cb_master WHERE snapshot_date=?", conn, params=(snap,))
mdate = conn.execute("SELECT MAX(trade_date) FROM metrics_daily").fetchone()[0]
met = pd.read_sql("SELECT * FROM metrics_daily WHERE trade_date=?", conn, params=(mdate,))
df = master.merge(met, on="bond_code", how="left")

# 歷史走勢:近 120 個交易日
dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT trade_date FROM metrics_daily ORDER BY trade_date DESC LIMIT 120")]
hist_df = pd.read_sql(
    "SELECT trade_date, bond_code, cb_price, premium, moneyness FROM metrics_daily "
    "WHERE trade_date >= ?", conn, params=(min(dates) if dates else "",))
conn.close()

hist = {}
for _, r in hist_df.sort_values("trade_date").iterrows():
    hist.setdefault(r["bond_code"], []).append([
        r["trade_date"],
        None if pd.isna(r["premium"]) else round(r["premium"], 2),
        None if pd.isna(r["moneyness"]) else round(r["moneyness"], 2),
        None if pd.isna(r["cb_price"]) else round(r["cb_price"], 2),
    ])

today = dt.date.today()

def days_to(s):
    try:
        return (dt.date.fromisoformat(str(s).replace("/", "-")) - today).days
    except Exception:
        return None

def clean(v):
    return None if pd.isna(v) else v

rows = []
for _, r in df.iterrows():
    rows.append({
        "code": r["bond_code"], "name": r["bond_name"], "stock": r["stock_code"],
        "px": clean(r.get("stock_close")), "cp": clean(r["conversion_price"]),
        "cb": clean(r.get("cb_price")), "src": r.get("cb_price_src") or "weekly",
        "cv": clean(r.get("conversion_value")), "mny": clean(r.get("moneyness")),
        "prem": clean(r.get("premium")),
        "putD": r["put_date"], "dPut": days_to(r["put_date"]),
        "putP": clean(r["put_price"]), "putY": clean(r["put_yield"]),
        "rstD": r["reset_base_date"], "dRst": days_to(r["reset_base_date"]),
        "rstP": clean(r["reset_est_price"]), "tcri": r["tcri"],
        "bal": clean(r["balance_lots"]),
    })

HTML = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CB 監控儀表板</title><style>
:root{--bg:#101418;--panel:#1a2027;--line:#2a323c;--tx:#e8ecf0;--mut:#8c98a6;
--up:#ff5d5d;--dn:#3dd68c;--amb:#f5b841;--mono:ui-monospace,Menlo,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.5 "PingFang TC","Microsoft JhengHei",sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);display:flex;
flex-wrap:wrap;gap:16px;align-items:baseline}
h1{font-size:19px;margin:0;letter-spacing:.06em}
.meta{color:var(--mut);font-size:12px;font-family:var(--mono)}
.alerts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
gap:12px;padding:14px 22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card h2{font-size:13px;margin:0 0 8px;color:var(--amb);letter-spacing:.08em}
.card ul{margin:0;padding:0;list-style:none;max-height:190px;overflow:auto;font-size:13px}
.card li{padding:3px 0;border-bottom:1px dashed #232b34;display:flex;gap:8px;align-items:center;cursor:pointer}
.chip{font-family:var(--mono);font-size:11px;background:#2b2413;color:var(--amb);
border:1px solid #4a3d1a;border-radius:20px;padding:0 8px;white-space:nowrap}
.chip.hot{background:#3a1616;color:var(--up);border-color:#5c2222}
.bar{display:flex;flex-wrap:wrap;gap:10px;padding:10px 22px;align-items:center;
position:sticky;top:0;background:var(--bg);z-index:20;border-bottom:1px solid var(--line)}
input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--tx);
border-radius:6px;padding:7px 12px;width:240px;font-size:13px}
.btn{background:var(--panel);border:1px solid var(--line);color:var(--mut);border-radius:6px;
padding:6px 12px;font-size:12px;cursor:pointer}
.btn.on{color:var(--amb);border-color:var(--amb)}
.wrap{padding:0 22px 30px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:1100px}
th{position:sticky;top:54px;background:#161c22;color:var(--mut);font-weight:500;
text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer;
white-space:nowrap;user-select:none;z-index:10}
th.l,td.l{text-align:left}
td{padding:6px 10px;border-bottom:1px solid #1c232b;text-align:right;
font-family:var(--mono);white-space:nowrap}
td.l{font-family:inherit}
tbody tr{cursor:pointer}
tr:hover td{background:#1c242d}
.pos{color:var(--up)}.neg{color:var(--dn)}.mut{color:var(--mut)}
.tag{font-size:10px;color:var(--mut)}
footer{color:var(--mut);font-size:11px;padding:0 22px 26px}
#ov{display:none;position:fixed;inset:0;background:rgba(6,9,12,.75);z-index:50;
align-items:center;justify-content:center}
#ov.show{display:flex}
#box{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;width:min(720px,94vw)}
#box h3{margin:0 0 4px;font-size:16px}
#box .sub{color:var(--mut);font-size:12px;font-family:var(--mono);margin-bottom:10px}
#cv2{width:100%;height:300px;display:block}
.legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin-top:8px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
#close{float:right;background:none;border:1px solid var(--line);color:var(--mut);
border-radius:6px;padding:3px 10px;cursor:pointer}
</style></head><body>
<header><h1>CB 監控儀表板</h1>
<span class="meta">主檔 __SNAP__ ・ 行情 __MDATE__ ・ 共 __N__ 檔 ・ 產生於 __GEN__ ・ 點任一列看歷史走勢</span></header>
<div class="alerts">
<div class="card"><h2>重設基準日 7 天內</h2><ul id="aRst"></ul></div>
<div class="card"><h2>賣回日 60 天內</h2><ul id="aPut"></ul></div>
<div class="card"><h2>低溢價 &lt;5% 且接近價內</h2><ul id="aPrem"></ul></div>
</div>
<div class="bar">
<input type="search" id="q" placeholder="搜尋代號 / 名稱 / 標的">
<button class="btn" data-f="itm">只看價內</button>
<button class="btn" data-f="low">溢價&lt;5%</button>
<button class="btn" data-f="put">60天內賣回</button>
<button class="btn" data-f="rst">即將重設</button>
<span class="meta" id="cnt"></span>
</div>
<div class="wrap"><table id="t"><thead><tr>
<th class="l" data-k="code">代號</th><th class="l" data-k="name">名稱</th>
<th class="l" data-k="stock">標的</th><th data-k="px">股價</th>
<th data-k="cp">轉換價</th><th data-k="cb">CB價</th><th data-k="cv">轉換價值</th>
<th data-k="prem">溢價%</th><th data-k="mny">價內外%</th>
<th data-k="dPut">賣回日</th><th data-k="putY">賣回益%</th>
<th data-k="dRst">重設日</th><th data-k="rstP">預估重設</th>
<th class="l" data-k="tcri">TCRI</th><th data-k="bal">餘額(張)</th>
</tr></thead><tbody id="tb"></tbody></table></div>
<footer>紅=價內/正,綠=價外/負。點任一列可查看歷史溢價走勢(資料自 2026-07-04 起逐日累積)。</footer>
<div id="ov" onclick="if(event.target.id=='ov')ov.classList.remove('show')">
<div id="box"><button id="close" onclick="ov.classList.remove('show')">關閉</button>
<h3 id="ct"></h3><div class="sub" id="cs"></div>
<canvas id="cv2"></canvas>
<div class="legend">
<span><span class="dot" style="background:#f5b841"></span>溢價率%</span>
<span><span class="dot" style="background:#5da9ff"></span>價內外%</span>
<span id="lastv"></span></div>
</div></div>
<script>
const D=__DATA__;const H=__HIST__;
const f={itm:0,low:0,put:0,rst:0};let sk="prem",sd=1,q="";
const fmt=(v,d=2)=>v==null?"–":v.toLocaleString("en",{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=v=>v==null?"mut":v>=0?"pos":"neg";
function alerts(){
 const rs=D.filter(r=>r.dRst!=null&&r.dRst>=0&&r.dRst<=7).sort((a,b)=>a.dRst-b.dRst);
 aRst.innerHTML=rs.map(r=>`<li onclick="chart('${r.code}')"><span class="chip ${r.dRst<=1?'hot':''}">${r.dRst}天</span>${r.name} <span class="mut">預估 ${fmt(r.rstP)}</span></li>`).join("")||"<li class='mut'>無</li>";
 const ps=D.filter(r=>r.dPut!=null&&r.dPut>=0&&r.dPut<=60).sort((a,b)=>a.dPut-b.dPut);
 aPut.innerHTML=ps.map(r=>`<li onclick="chart('${r.code}')"><span class="chip ${r.dPut<=7?'hot':''}">${r.dPut}天</span>${r.name} <span class="mut">賣回 ${fmt(r.putP)} / ${r.putY==null?"–":fmt(r.putY)+"%"}</span></li>`).join("")||"<li class='mut'>無</li>";
 const pr=D.filter(r=>r.prem!=null&&r.prem<5&&r.mny>-10).sort((a,b)=>a.prem-b.prem);
 aPrem.innerHTML=pr.slice(0,30).map(r=>`<li onclick="chart('${r.code}')"><span class="chip">${fmt(r.prem)}%</span>${r.name} <span class="mut">CB ${fmt(r.cb)}${r.src=="weekly"?"w":""} 值 ${fmt(r.cv)}</span></li>`).join("")||"<li class='mut'>無</li>";
}
function rows(){
 let a=D.filter(r=>{
  if(q&&!(String(r.code).includes(q)||r.name.includes(q)||String(r.stock).includes(q)))return 0;
  if(f.itm&&!(r.mny>0))return 0;
  if(f.low&&!(r.prem!=null&&r.prem<5))return 0;
  if(f.put&&!(r.dPut!=null&&r.dPut>=0&&r.dPut<=60))return 0;
  if(f.rst&&!(r.dRst!=null&&r.dRst>=0&&r.dRst<=7))return 0;
  return 1});
 a.sort((x,y)=>{let u=x[sk],v=y[sk];
  if(u==null)return 1;if(v==null)return -1;
  return(typeof u=="string"?u.localeCompare(v):u-v)*sd});
 tb.innerHTML=a.map(r=>`<tr onclick="chart('${r.code}')">
  <td class="l">${r.code}</td><td class="l">${r.name}</td><td class="l">${r.stock||"–"}</td>
  <td>${fmt(r.px)}</td><td>${fmt(r.cp)}</td>
  <td>${fmt(r.cb)}<span class="tag">${r.src=="weekly"?" w":""}</span></td>
  <td>${fmt(r.cv)}</td>
  <td class="${cls(r.prem)}">${r.prem==null?"–":fmt(r.prem)}</td>
  <td class="${cls(r.mny)}">${r.mny==null?"–":fmt(r.mny)}</td>
  <td>${r.putD||"–"}${r.dPut!=null&&r.dPut>=0?` <span class="tag">(${r.dPut}d)</span>`:""}</td>
  <td>${r.putY==null?"–":fmt(r.putY)}</td>
  <td>${r.rstD||"–"}${r.dRst!=null&&r.dRst>=0?` <span class="tag">(${r.dRst}d)</span>`:""}</td>
  <td>${fmt(r.rstP)}</td><td class="l">${r.tcri||"–"}</td><td>${fmt(r.bal,0)}</td></tr>`).join("");
 cnt.textContent=`顯示 ${a.length} / ${D.length} 檔`;
}
function chart(code){
 const rec=D.find(r=>r.code==code);const h=(H[code]||[]).filter(p=>p[1]!=null||p[2]!=null);
 ct.textContent=rec.name+"("+code+")";
 cs.textContent="歷史走勢 ・ "+h.length+" 個交易日"+(h.length?" ・ "+h[0][0]+" ~ "+h[h.length-1][0]:"");
 lastv.textContent=rec.prem!=null?"最新:溢價 "+fmt(rec.prem)+"% / 價內外 "+fmt(rec.mny)+"%":"";
 const c=document.getElementById("cv2");const dpr=window.devicePixelRatio||1;
 const W=c.clientWidth||660,Ht=300;c.width=W*dpr;c.height=Ht*dpr;
 const g=c.getContext("2d");g.scale(dpr,dpr);g.clearRect(0,0,W,Ht);
 const padL=46,padR=12,padT=14,padB=26;
 if(h.length<1){g.fillStyle="#8c98a6";g.font="13px sans-serif";
  g.fillText("尚無歷史資料(每天會自動累積一筆)",padL,Ht/2);ov.classList.add("show");return}
 const vals=[];h.forEach(p=>{if(p[1]!=null)vals.push(p[1]);if(p[2]!=null)vals.push(p[2])});
 let lo=Math.min(...vals),hi=Math.max(...vals);
 if(hi-lo<4){const m=(hi+lo)/2;lo=m-2;hi=m+2}
 const pad=(hi-lo)*0.1;lo-=pad;hi+=pad;
 const X=i=>h.length==1?(padL+(W-padL-padR)/2):padL+(W-padL-padR)*i/(h.length-1);
 const Y=v=>padT+(Ht-padT-padB)*(1-(v-lo)/(hi-lo));
 g.strokeStyle="#2a323c";g.fillStyle="#8c98a6";g.font="10px Menlo,monospace";
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4,y=Y(v);
  g.beginPath();g.moveTo(padL,y);g.lineTo(W-padR,y);g.stroke();
  g.fillText(v.toFixed(1),4,y+3)}
 if(lo<0&&hi>0){g.strokeStyle="#4a5560";g.beginPath();g.moveTo(padL,Y(0));g.lineTo(W-padR,Y(0));g.stroke()}
 g.fillText(h[0][0].slice(5),padL,Ht-8);
 if(h.length>1)g.fillText(h[h.length-1][0].slice(5),W-padR-34,Ht-8);
 function line(idx,color){g.strokeStyle=color;g.fillStyle=color;g.lineWidth=1.6;g.beginPath();let started=0;
  h.forEach((p,i)=>{if(p[idx]==null)return;const x=X(i),y=Y(p[idx]);
   if(!started){g.moveTo(x,y);started=1}else g.lineTo(x,y);});
  g.stroke();
  h.forEach((p,i)=>{if(p[idx]==null)return;g.beginPath();g.arc(X(i),Y(p[idx]),h.length>40?1.5:2.6,0,7);g.fill();});}
 line(2,"#5da9ff");line(1,"#f5b841");
 ov.classList.add("show");
}
document.querySelectorAll("th").forEach(h=>h.onclick=()=>{
 const k=h.dataset.k;if(sk==k)sd*=-1;else{sk=k;sd=1}rows()});
document.querySelectorAll(".btn").forEach(b=>b.onclick=()=>{
 const k=b.dataset.f;f[k]^=1;b.classList.toggle("on",!!f[k]);rows()});
document.getElementById("q").oninput=e=>{q=e.target.value.trim();rows()};
alerts();rows();
</script></body></html>"""

html = (HTML.replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__HIST__", json.dumps(hist, ensure_ascii=False))
            .replace("__SNAP__", str(snap))
            .replace("__MDATE__", str(mdate or "-"))
            .replace("__N__", str(len(rows)))
            .replace("__GEN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
OUT.write_text(html, encoding="utf-8")
print("已產生: " + str(OUT))
