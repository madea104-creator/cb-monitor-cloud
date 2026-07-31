#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台灣可轉債(CB)監控系統 v2 — CB 日成交價已接通(TPEx RSta0113)
用法:
  python cb_monitor.py weekly / daily / status / export
"""
import csv
import datetime as dt
import io
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests
import urllib3

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cb_monitor.db"
EXPORT_DIR = BASE_DIR / "exports"

PSC_API = "https://cbas16889.pscnet.com.tw/api/CbasQuote/GetIssuedCBSchedule"
TWSE_DAILY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_CB_CSV = ("https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/"
               "{y}/{ym}/RSta0113.{ymd}-C.csv")

ALERT_RESET_DAYS = 7
ALERT_PUT_DAYS = 60
ALERT_PREMIUM_MAX = 5.0
ALERT_MONEYNESS_MIN = -10.0

HEADERS = {"User-Agent": "Mozilla/5.0"}


def get(url, referer=None, as_json=True):
    h = dict(HEADERS)
    if referer:
        h["Referer"] = referer
    try:
        r = requests.get(url, timeout=60, headers=h)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, timeout=60, headers=h, verify=False)
    r.raise_for_status()
    return r.json() if as_json else r.content


def num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "----"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cb_master (
        snapshot_date TEXT, bond_code TEXT, bond_name TEXT, stock_code TEXT,
        issue_date TEXT, expiry_date TEXT,
        circulation REAL, balance_lots REAL, balance_ratio REAL,
        tcri TEXT, guarantee TEXT,
        conversion_price REAL, cb_price_weekly REAL,
        put_date TEXT, put_price REAL, put_yield REAL,
        stop_conv_from TEXT, stop_conv_to TEXT, force_redeem_date TEXT,
        reset_status TEXT, reset_base_date TEXT, reset_est_price REAL,
        PRIMARY KEY (snapshot_date, bond_code)
    );
    CREATE TABLE IF NOT EXISTS stock_daily (
        trade_date TEXT, stock_code TEXT, close REAL, source TEXT,
        PRIMARY KEY (trade_date, stock_code)
    );
    CREATE TABLE IF NOT EXISTS cb_daily (
        trade_date TEXT, bond_code TEXT, close REAL, volume REAL,
        PRIMARY KEY (trade_date, bond_code)
    );
    CREATE TABLE IF NOT EXISTS metrics_daily (
        trade_date TEXT, bond_code TEXT,
        stock_close REAL, cb_price REAL, cb_price_src TEXT,
        conversion_value REAL, moneyness REAL, premium REAL,
        PRIMARY KEY (trade_date, bond_code)
    );
    """)
    conn.commit()


def latest_master(conn):
    d = conn.execute("SELECT MAX(snapshot_date) FROM cb_master").fetchone()[0]
    if not d:
        sys.exit("主檔是空的,請先跑: python cb_monitor.py weekly")
    return pd.read_sql("SELECT * FROM cb_master WHERE snapshot_date=?", conn, params=(d,))


def cmd_weekly():
    print("[weekly] 下載統一證券 CBAS 主檔...")
    payload = get(PSC_API, referer="https://cbas16889.pscnet.com.tw/marketInfo/issued/")
    if payload.get("message") != "QuerySuccess":
        sys.exit("API 回傳異常: " + str(payload.get("message")))
    rows = payload["result"]
    today = dt.date.today().isoformat()
    recs = [(
        today,
        r.get("bond_code"), r.get("underlying_bond"), r.get("convert_target_code"),
        r.get("issue_date"), r.get("expiry_date"),
        num(r.get("circulation")), num(r.get("circulating_balance")), num(r.get("balance_ratio")),
        r.get("tcri"), r.get("guarantee_situation"),
        num(r.get("conversion_price")), num(r.get("convertible_bond_market_price")),
        r.get("latest_sale_date"), num(r.get("latest_sale_price")), num(r.get("sell_back_yield")),
        r.get("stop_conversion_date"), r.get("stop_converting_until_date"),
        r.get("mandatory_redemption_date"),
        r.get("reset_conversion_price"), r.get("reset_conversion_day"), num(r.get("reset_price")),
    ) for r in rows]
    conn = db(); init_db(conn)
    prev = conn.execute(
        "SELECT snapshot_date, COUNT(*) FROM cb_master "
        "WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM cb_master) GROUP BY 1").fetchone()
    if prev and prev[1] and len(recs) < prev[1] * 0.9:
        conn.close()
        sys.exit("[weekly] 中止:本次僅 " + str(len(recs)) + " 檔,前次(" + str(prev[0]) +
                 ")有 " + str(prev[1]) + " 檔,疑似來源異常,未寫入")
    conn.executemany("INSERT OR REPLACE INTO cb_master VALUES (" + ",".join("?" * 22) + ")", recs)
    conn.commit()
    print("[weekly] 已寫入 " + str(len(recs)) + " 檔 CB 主檔 snapshot=" + today)
    prev = conn.execute(
        "SELECT DISTINCT snapshot_date FROM cb_master ORDER BY snapshot_date DESC LIMIT 2"
    ).fetchall()
    if len(prev) == 2:
        cur_d, prev_d = prev[0][0], prev[1][0]
        cur = pd.read_sql("SELECT bond_code, bond_name, balance_lots FROM cb_master WHERE snapshot_date=?",
                          conn, params=(cur_d,)).set_index("bond_code")
        old = pd.read_sql("SELECT bond_code, bond_name, balance_lots FROM cb_master WHERE snapshot_date=?",
                          conn, params=(prev_d,)).set_index("bond_code")
        new_codes = cur.index.difference(old.index)
        gone_codes = old.index.difference(cur.index)
        both = cur.join(old, lsuffix="_new", rsuffix="_old").dropna()
        both = both[both["balance_lots_old"] > 0]
        both["chg"] = both["balance_lots_new"] / both["balance_lots_old"] - 1
        big_drop = both[both["chg"] < -0.20]
        if len(new_codes):
            print("  新掛牌 " + str(len(new_codes)) + " 檔: " + ", ".join(cur.loc[new_codes, "bond_name"]))
        if len(gone_codes):
            print("  下市/消失 " + str(len(gone_codes)) + " 檔: " + ", ".join(old.loc[gone_codes, "bond_name"]))
        if len(big_drop):
            print("  餘額週減逾20%: " + str(len(big_drop)) + " 檔:")
            for c, row in big_drop.iterrows():
                print("     " + row["bond_name_new"] + ": " + str(int(row["balance_lots_old"])) +
                      " -> " + str(int(row["balance_lots_new"])) + " 張")
    conn.close()


def fetch_stock_closes():
    out = {}
    try:
        for r in get(TWSE_DAILY):
            c = num(r.get("ClosingPrice"))
            if c is not None:
                out[str(r.get("Code")).strip()] = (str(r.get("Date", "")), c, "TWSE")
        print("[daily] TWSE 上市收盤價 OK")
    except Exception as e:
        print("[daily] TWSE 抓取失敗: " + str(e))
    try:
        for r in get(TPEX_DAILY):
            code = str(r.get("SecuritiesCompanyCode") or r.get("Code") or "").strip()
            c = num(r.get("Close") or r.get("ClosingPrice"))
            if code and c is not None:
                out[code] = (str(r.get("Date", "")), c, "TPEx")
        print("[daily] TPEx 上櫃收盤價 OK")
    except Exception as e:
        print("[daily] TPEx 抓取失敗: " + str(e))
    return out


def fetch_cb_closes():
    """TPEx 每日轉(交)換公司債買賣斷行情(RSta0113 CSV, Big5)。
    當日檔尚未出或非交易日時,往回找最多 6 天。
    回傳 ({bond_code: (close, volume)}, 使用的日期)"""
    for back in range(0, 7):
        d = dt.date.today() - dt.timedelta(days=back)
        url = TPEX_CB_CSV.format(y=d.strftime("%Y"), ym=d.strftime("%Y%m"),
                                 ymd=d.strftime("%Y%m%d"))
        try:
            raw = get(url, referer="https://www.tpex.org.tw/zh-tw/bond/info/statistics-cb/day.html",
                      as_json=False)
        except Exception:
            continue
        text = raw.decode("big5", errors="replace")
        out = {}
        cur_code = None
        for row in csv.reader(io.StringIO(text)):
            if not row or row[0] != "BODY":
                continue
            # BODY,代號,名稱,交易,收市,漲跌,開市,最高,最低,筆數,單位,金額,均價,明日參價,...
            code = row[1].strip().strip('"')
            if code:
                cur_code = code
            if not cur_code or len(row) < 14:
                continue
            deal_type = row[3].strip()
            if "等價" not in deal_type:
                continue
            close = num(row[4])
            vol = num(row[10]) or 0
            if close is None:
                close = num(row[13])  # 無成交時用明日參價
                vol = 0
            if close is not None:
                out[cur_code] = (close, vol)
        if out:
            print("[daily] TPEx CB 日成交 OK(" + d.isoformat() + ",共 " +
                  str(len(out)) + " 檔)")
            return out, d.isoformat()
    print("[daily] CB 日成交:近 7 天皆無檔案,改用週價")
    return {}, None


def cmd_daily():
    conn = db(); init_db(conn)
    master = latest_master(conn)
    today = dt.date.today().isoformat()
    closes = fetch_stock_closes()
    if closes:
        conn.executemany("INSERT OR REPLACE INTO stock_daily VALUES (?,?,?,?)",
                         [(today, code, px, src) for code, (_, px, src) in closes.items()])
    fb = dict(conn.execute(
        "SELECT stock_code, close FROM stock_daily a WHERE trade_date="
        "(SELECT MAX(trade_date) FROM stock_daily b WHERE b.stock_code=a.stock_code)"))
    cb_closes, cb_date = fetch_cb_closes()
    if cb_closes:
        conn.executemany("INSERT OR REPLACE INTO cb_daily VALUES (?,?,?,?)",
                         [(cb_date, bc, px, vol) for bc, (px, vol) in cb_closes.items()])
    recs = []
    for _, m in master.iterrows():
        sc = str(m["stock_code"] or "").strip()
        cp = m["conversion_price"]
        stock_close = closes.get(sc, (None, None, None))[1] if sc else None
        if stock_close is None and sc:
            stock_close = fb.get(sc)
        if cb_closes.get(m["bond_code"]):
            cb_px, cb_src = cb_closes[m["bond_code"]][0], "daily"
        else:
            cb_px, cb_src = m["cb_price_weekly"], "weekly"
        conv_val = moneyness = premium = None
        if stock_close and cp:
            conv_val = round(stock_close * 100.0 / cp, 2)
            moneyness = round((stock_close / cp - 1) * 100, 2)
            if cb_px:
                premium = round((cb_px / conv_val - 1) * 100, 2)
        recs.append((today, m["bond_code"], stock_close, cb_px, cb_src,
                     conv_val, moneyness, premium))
    conn.executemany("INSERT OR REPLACE INTO metrics_daily VALUES (?,?,?,?,?,?,?,?)", recs)
    conn.commit()
    n_ok = sum(1 for r in recs if r[5] is not None)
    n_d = sum(1 for r in recs if r[4] == "daily")
    print("[daily] 指標已重算 " + str(n_ok) + "/" + str(len(recs)) +
          " 檔(其中 " + str(n_d) + " 檔使用日成交價)")
    print_alerts(conn, master, today)
    conn.close()


def print_alerts(conn, master, today):
    met = pd.read_sql("SELECT * FROM metrics_daily WHERE trade_date=?", conn, params=(today,))
    df = master.merge(met, on="bond_code", how="left")
    t = dt.date.fromisoformat(today)

    def days_to(s):
        try:
            return (dt.date.fromisoformat(str(s).replace("/", "-")) - t).days
        except Exception:
            return None

    df["d_reset"] = df["reset_base_date"].map(days_to)
    df["d_put"] = df["put_date"].map(days_to)
    print("")
    print("======== 警示 ========")
    a = df[(df["d_reset"].notna()) & (df["d_reset"].between(0, ALERT_RESET_DAYS))]
    if len(a):
        print("◆ 重設基準日 " + str(ALERT_RESET_DAYS) + " 天內(" + str(len(a)) + " 檔):")
        for _, r in a.sort_values("d_reset").iterrows():
            print("   " + str(r["bond_name"]) + "(" + str(r["bond_code"]) + ") " +
                  str(r["reset_base_date"]) + " 還有" + str(int(r["d_reset"])) +
                  "天 預估重設價 " + str(r["reset_est_price"]))
    b = df[(df["d_put"].notna()) & (df["d_put"].between(0, ALERT_PUT_DAYS))]
    if len(b):
        print("◆ 賣回日 " + str(ALERT_PUT_DAYS) + " 天內(" + str(len(b)) + " 檔):")
        for _, r in b.sort_values("d_put").iterrows():
            print("   " + str(r["bond_name"]) + "(" + str(r["bond_code"]) + ") " +
                  str(r["put_date"]) + " 還有" + str(int(r["d_put"])) + "天 賣回價 " +
                  str(r["put_price"]) + " 收益率 " + str(r["put_yield"]) + "%")
    c = df[(df["premium"].notna()) & (df["premium"] < ALERT_PREMIUM_MAX)
           & (df["moneyness"] > ALERT_MONEYNESS_MIN)]
    if len(c):
        print("◆ 低溢價且接近價內(" + str(len(c)) + " 檔,前15):")
        for _, r in c.sort_values("premium").head(15).iterrows():
            tag = "(週價)" if r["cb_price_src"] == "weekly" else ""
            print("   " + str(r["bond_name"]) + "(" + str(r["bond_code"]) + ") CB " +
                  str(r["cb_price"]) + tag + " 轉換價值 " + str(r["conversion_value"]) +
                  " 溢價 " + str(r["premium"]) + "% 價內外 " + str(r["moneyness"]) + "%")
    if not (len(a) or len(b) or len(c)):
        print("(今日無警示)")


def snapshot_df(conn):
    master = latest_master(conn)
    d = conn.execute("SELECT MAX(trade_date) FROM metrics_daily").fetchone()[0]
    if d:
        met = pd.read_sql("SELECT * FROM metrics_daily WHERE trade_date=?", conn, params=(d,))
        master = master.merge(met, on="bond_code", how="left")
    cbd = conn.execute("SELECT MAX(trade_date) FROM cb_daily").fetchone()[0]
    master["cb_quote_date"] = cbd or ""
    return master


def cmd_status():
    conn = db(); init_db(conn)
    df = snapshot_df(conn)
    print("主檔快照: " + str(df["snapshot_date"].iloc[0]) + ",共 " + str(len(df)) + " 檔")
    if "trade_date" in df.columns and df["trade_date"].notna().any():
        print("指標日期: " + str(df["trade_date"].dropna().iloc[0]))
        top = df[df["premium"].notna()].sort_values("premium").head(10)
        print("")
        print("溢價率最低 10 檔:")
        print(top[["bond_code", "bond_name", "cb_price", "conversion_value",
                   "premium", "moneyness"]].to_string(index=False))
    conn.close()


EXPORT_COLS = {
    "bond_code": "債券代號", "bond_name": "債券名稱", "stock_code": "標的代號",
    "stock_close": "標的股價", "conversion_price": "轉換價格",
    "cb_price": "CB價", "cb_price_src": "CB價來源", "cb_quote_date": "CB收盤日期",
    "conversion_value": "轉換價值", "premium": "溢價率(%)", "moneyness": "價內外(%)",
    "put_date": "最近賣回日", "put_price": "賣回價格", "put_yield": "賣回收益率(%)",
    "reset_status": "重設狀態", "reset_base_date": "重設基準日", "reset_est_price": "預估重設價",
    "tcri": "TCRI", "guarantee": "擔保情形",
    "issue_date": "發行日", "expiry_date": "到期日",
    "circulation": "發行總額(億)", "balance_lots": "流通餘額(張)", "balance_ratio": "餘額比率(%)",
    "stop_conv_from": "停止轉換起日", "stop_conv_to": "停止轉換迄日",
    "force_redeem_date": "強制贖回日", "cb_price_weekly": "CB週價(參考)",
    "snapshot_date": "主檔日期", "trade_date": "行情日期",
}


def cmd_export():
    conn = db(); init_db(conn)
    df = snapshot_df(conn)
    df = df[[c for c in EXPORT_COLS if c in df.columns]].rename(columns=EXPORT_COLS)
    if "CB價來源" in df.columns:
        df["CB價來源"] = df["CB價來源"].map({"daily": "日成交", "weekly": "週價"}).fillna("")
    EXPORT_DIR.mkdir(exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    xlsx = EXPORT_DIR / ("cb_snapshot_" + stamp + ".xlsx")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="CB快照")
        ws = w.sheets["CB快照"]
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
    df.to_csv(EXPORT_DIR / ("cb_snapshot_" + stamp + ".csv"), index=False, encoding="utf-8-sig")
    print("已匯出: " + str(xlsx))
    conn.close()


if __name__ == "__main__":
    cmds = {"weekly": cmd_weekly, "daily": cmd_daily,
            "status": cmd_status, "export": cmd_export}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]]()
