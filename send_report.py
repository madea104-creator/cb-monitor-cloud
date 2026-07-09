#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雲端版:匯出 Excel 並以 Gmail SMTP 寄出(帳密來自環境變數)"""
import datetime, glob, os, smtplib, sqlite3, ssl, subprocess, sys
from email.message import EmailMessage
from pathlib import Path

D = Path(__file__).resolve().parent
ACCT = os.environ["GMAIL_ADDRESS"]
PW = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()

subprocess.run([sys.executable, str(D / "cb_monitor.py"), "export"], check=True)
xlsx = Path(sorted(glob.glob(str(D / "exports/cb_snapshot_*.xlsx")))[-1])

conn = sqlite3.connect(str(D / "cb_monitor.db"))
cbd = conn.execute("SELECT MAX(trade_date) FROM cb_daily").fetchone()[0] or "?"
conn.close()

msg = EmailMessage()
msg["From"] = ACCT
msg["To"] = ACCT
msg["Subject"] = "CB 監控日報 " + datetime.date.today().isoformat() + "(CB收盤: " + cbd + ")"
msg.set_content("附件為今日可轉債快照。\n儀表板: https://madea104-creator.github.io/cb-monitor-cloud/\n\n-- CB 監控系統(GitHub Actions)自動寄送")
msg.add_attachment(xlsx.read_bytes(), maintype="application",
                   subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   filename=xlsx.name)
with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
    s.login(ACCT, PW)
    s.send_message(msg)
print("已寄出: " + xlsx.name)
