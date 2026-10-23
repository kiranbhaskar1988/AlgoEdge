"""Telegram + email alerts — AlgoEdge"""
import requests, smtplib
from email.mime.text import MIMEText
from logzero import logger
import config

def send_telegram(msg):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID: return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id":config.TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},timeout=5)
        return r.status_code==200
    except Exception as exc: logger.warning("Telegram: %s",exc); return False

def send_email(subject, body):
    if not all([config.SMTP_HOST,config.SMTP_USER,config.ALERT_EMAIL]): return False
    try:
        m=MIMEText(body); m["Subject"]=f"[AlgoEdge] {subject}"
        m["From"]=config.SMTP_USER; m["To"]=config.ALERT_EMAIL
        with smtplib.SMTP(config.SMTP_HOST,587,timeout=10) as s:
            s.starttls(); s.login(config.SMTP_USER,config.SMTP_PASSWORD); s.send_message(m)
        return True
    except Exception as exc: logger.warning("Email: %s",exc); return False

def notify(event, detail, level="INFO"):
    icon={"INFO":"ℹ️","WARNING":"⚠️","CRITICAL":"🔴"}.get(level,"ℹ️")
    send_telegram(f"{icon} <b>AlgoEdge</b>\n<b>{event}</b>\n{detail}")
    if level=="CRITICAL": send_email(event,detail)
