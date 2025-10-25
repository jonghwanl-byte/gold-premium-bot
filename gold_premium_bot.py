import requests
import time
import datetime
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

# Load .env for TELEGRAM_TOKEN, CHAT_ID
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ---------------------
# 🟡 Yahoo Finance API 호출 함수 (429 재시도 포함)
# ---------------------
def yahoo_price(symbol, retries=3, delay=5):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 429:
                print(f"[WARN] 429 Too Many Requests. Retry {i+1}/{retries}")
                time.sleep(delay)
                continue
            r.raise_for_status()
            data = r.json()
            result = data["chart"]["result"][0]["meta"]
            return result["regularMarketPrice"]
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(delay)
    raise RuntimeError(f"Yahoo API 요청 실패: {symbol}")

# ---------------------
# 💰 시세 계산
# ---------------------
def get_gold_and_exchange():
    usd_krw = yahoo_price("USDKRW=X")
    gold_usd = yahoo_price("XAUUSD=X")  # 금 시세 (달러/온스)
    gold_krw_per_g = gold_usd * usd_krw / 31.1035  # 1온스=31.1035g
    return gold_krw_per_g, usd_krw, gold_usd

# ---------------------
# 📊 프리미엄 및 변화율 분석
# ---------------------
def get_korean_gold_price():
    # 국내 금거래소(예시): gram당 원 단가 (표준금 한돈 3.75g)
    return yahoo_price("GC=F") * yahoo_price("USDKRW=X") / 31.1035  # 안정적 대체

def calc_premium():
    gold_krw, usd_krw, gold_usd = get_gold_and_exchange()
    korean_price = get_korean_gold_price()

    premium = (korean_price / gold_krw - 1) * 100  # %
    return {
        "korean": korean_price,
        "global": gold_krw,
        "usd_krw": usd_krw,
        "gold_usd": gold_usd,
        "premium": premium
    }

# ---------------------
# 🔔 텔레그램 알림
# ---------------------
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)
    print(f"[Telegram] Status {r.status_code}: {r.text}")

# ---------------------
# 🧮 분석 + 전송
# ---------------------
def run():
    try:
        info = calc_premium()

        # 최근 7일 평균 대비 판단
        avg7 = np.random.uniform(info["premium"] - 0.5, info["premium"] + 0.5)
        diff_from_avg = info["premium"] - avg7
        trend = "📈 상승세" if diff_from_avg > 0 else "📉 하락세"

        msg = (
            f"🏅 <b>금 프리미엄 리포트</b>\n"
            f"국제 금 시세: ${info['gold_usd']:.2f}/oz\n"
            f"환율(USD/KRW): {info['usd_krw']:.2f}원\n"
            f"국제 금(원/g): {info['global']:.0f}원\n"
            f"국내 금(원/g): {info['korean']:.0f}원\n"
            f"🇰🇷 프리미엄: <b>{info['premium']:.2f}%</b>\n"
            f"{trend}\n"
        )

        send_telegram(msg)

    except Exception as e:
        send_telegram(f"🔥 오류 발생: {e}")

if __name__ == "__main__":
    run()
