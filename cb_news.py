#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 CB 相關新聞(Google News RSS),輸出 cb_news.html
來源:總體可轉債新聞 + 警示名單個股(重設7天內/賣回60天內/低溢價)近7天新聞
"""
import datetime as dt
import html
import re
import sqlite3
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
DB = BASE / "cb_monitor.db"
OUT = BASE / "cb_news.html"
UA = {"User-Agent": "Mozilla/5.0"}
MAX_COMPANIES = 25   # 每天最多查幾家公司(避免跑太久)
PER_FEED = 5         # 每家公司最多留幾則

def company_name(bond_name: str) -> str:
    """債券名稱 -> 公司名:全新二->全新, 麗豐二KY->麗豐, 遠東新E2永->遠東新"""
    s = str(bond_name)
    s = re.sub(r"KY$", "", s)
    s = re.sub(r"[一二三四五六七八九十0-9E永創]+$", "", s)
    return s or str(bond_name)

def fetch_feed(query: str):
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query) +
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            src = it.find("{https://news.google.com}source") or it.find("source")
            source = src.text.strip() if (src is not None and src.text) else ""
            try:
                d = dt.datetime.strptime(pub[:16], "%a, %d %b %Y").date().isoformat()
            except Exception:
                d = ""
            items.append({"title": title, "link": link, "date": d, "source": source})
        return items
    except Exception as e:
        print("  feed 失敗 [" + query + "]: " + str(e))
        return []

def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS news(
        fetched TEXT, keyword TEXT, title TEXT, link TEXT UNIQUE,
        pub_date TEXT, source TEXT)""")
    snap = conn.execute("SELECT MAX(snapshot_date) FROM cb_master").fetchone()[0]
    master = pd.read_sql("SELECT * FROM cb_master WHERE snapshot_date=?", conn, params=(snap,))
    mdate = conn.execute("SELECT MAX(trade_date) FROM metrics_daily").fetchone()[0]
    met = pd.read_sql("SELECT * FROM metrics_daily WHERE trade_date=?", conn, params=(mdate,))
    df = master.merge(met, on="bond_code", how="left")
    today = dt.date.today()

    def days_to(s):
        try:
            return (dt.date.fromisoformat(str(s).replace("/", "-")) - today).days
        except Exception:
            return None

    df["d_rst"] = df["reset_base_date"].map(days_to)
    df["d_put"] = df["put_date"].map(days_to)
    watch = df[((df["d_rst"].notna()) & (df["d_rst"].between(0, 7))) |
               ((df["d_put"].notna()) & (df["d_put"].between(0, 30))) |
               ((df["premium"].notna()) & (df["premium"] < 3) & (df["moneyness"] > 0))]
    names = []
    for bn in watch["bond_name"]:
        n = company_name(bn)
        if n and n not in names:
            names.append(n)
    names = names[:MAX_COMPANIES]
    print("監看公司 " + str(len(names)) + " 家: " + ", ".join(names))

    sections = []
    print("抓取總體可轉債新聞...")
    general = fetch_feed("可轉債 OR 可轉換公司債 when:7d")[:12]
    sections.append(("可轉債總體新聞", "", general))
    for n in names:
        time.sleep(0.4)
        items = fetch_feed(n + " when:7d")[:PER_FEED]
        if items:
            sections.append((n, "警示個股", items))
        print("  " + n + ": " + str(len(items)) + " 則")

    fetched = dt.datetime.now().isoformat(timespec="seconds")
    for _, tag, items in sections:
        for it in items:
            try:
                conn.execute("INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?)",
                             (fetched, tag or "general", it["title"], it["link"],
                              it["date"], it["source"]))
            except Exception:
                pass
    conn.commit(); conn.close()

    cards = []
    for name, tag, items in sections:
        if not items:
            continue
        lis = "".join(
            '<li><a href="' + html.escape(it["link"]) + '" target="_blank">' +
            html.escape(it["title"]) + '</a><span class="m"> ' +
            html.escape(it["source"]) + " " + html.escape(it["date"]) + "</span></li>"
            for it in items)
        badge = '<span class="b">' + tag + '</span>' if tag else ""
        cards.append('<div class="card"><h2>' + html.escape(name) + badge +
                     '</h2><ul>' + lis + '</ul></div>')

    page = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CB 新聞</title><style>
body{margin:0;background:#101418;color:#e8ecf0;font:14px/1.6 "PingFang TC",sans-serif}
header{padding:18px 22px;border-bottom:1px solid #2a323c;display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
h1{font-size:19px;margin:0}.meta{color:#8c98a6;font-size:12px;font-family:Menlo,monospace}
a.back{color:#f5b841;font-size:13px;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;padding:16px 22px}
.card{background:#1a2027;border:1px solid #2a323c;border-radius:8px;padding:12px 14px}
.card h2{font-size:14px;margin:0 0 8px;color:#f5b841}
.b{font-size:10px;color:#8c98a6;border:1px solid #2a323c;border-radius:10px;padding:1px 7px;margin-left:8px;font-weight:400}
ul{margin:0;padding:0;list-style:none;font-size:13px}
li{padding:5px 0;border-bottom:1px dashed #232b34}
a{color:#e8ecf0;text-decoration:none}a:hover{color:#f5b841}
.m{color:#8c98a6;font-size:11px;display:block}
</style></head><body>
<header><h1>CB 相關新聞</h1><span class="meta">__GEN__ 更新</span>
<a class="back" href="cb_dashboard.html">← 回儀表板</a></header>
<div class="grid">__CARDS__</div></body></html>"""
    page = page.replace("__GEN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    page = page.replace("__CARDS__", "".join(cards) or "<p style='padding:22px'>今日無新聞</p>")
    OUT.write_text(page, encoding="utf-8")
    print("已產生: " + str(OUT))

if __name__ == "__main__":
    main()
