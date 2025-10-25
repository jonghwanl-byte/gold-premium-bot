import requests
import time
import datetime
import os
from urllib.parse import quote_plus

# ---------- 환경 변수 ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("필수 환경 변수(TELEGRAM_BOT_TOKEN 또는 CHAT_ID) 누락.")

# ---------- 텔레그램 ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, json=payload)
    print(f"[Telegram] Status {r.status_code}: {r.text}")
    r.raise_for_status()

# ---------- Yahoo Finance 호출 (429 재시도 포함) ----------
def yahoo_price(symbol, retries=3, delay=5):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 429:
                print(f"[WARN] 429 Too Many Requests. Retry {i+1}/{retries}")
                time.sleep(delay)
                continue
            r.raise_for_status()
            data = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                raise ValueError(f"No Yahoo data for {symbol}")
            return result[0]["meta"]["regularMarketPrice"]
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(delay)
    raise RuntimeError(f"Yahoo API request failed: {symbol}")

# ---------- 금 시세 및 환율 가져오기 ----------
def get_gold_and_fx():
    usd_krw = yahoo_price("USDKRW=X")
    gold_usd = yahoo_price("XAUUSD=X")  # 국제 금 시세 ($/oz)
    gold_krw_per_g = gold_usd * usd_krw / 31.1035
    return gold_krw_per_g, usd_krw, gold_usd

# ---------- 프리미엄 계산 ----------
DATA_FILE = "gold_premium_history.json"

def load_history():
    import json
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(data):
    import json
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calc_premium():
    krx_gold, usd_krw, gold_usd = get_gold_and_fx()
    korean_gold = krx_gold  # 실제 국내 금 가격 대신 Yahoo 기반 추정
    premium = (korean_gold / krx_gold - 1) * 100  # 이론상 0% 기준
    return {
        "korean": korean_gold,
        "global": krx_gold,
        "usd_krw": usd_krw,
        "gold_usd": gold_usd,
        "premium": premium
    }

# ---------- 메인 ----------
def main():
    try:
        today = datetime.date.today().isoformat()
        info = calc_premium()

        # 히스토리 관리
        history = load_history()
        history.append({"date": today, "premium": round(info["premium"], 2)})
        save_history(history)

        # 전일 대비 변화
        prev = history[-2]["premium"] if len(history) > 1 else info["premium"]
        change = info["premium"] - prev

        # 7일 평균 대비 수준
        last7 = [x["premium"] for x in history[-7:]]
        avg7 = sum(last7)/len(last7)
        level = "고평가" if info["premium"] > avg7 else "저평가"
        trend = "📈 상승세" if change > 0 else "📉 하락세"

        # 메시지 작성
        msg = (
            f"📅 {today} 금 프리미엄 알림 (Yahoo 기반)\n"
            f"국제 금시세: ${info['gold_usd']:.2f}/oz\n"
            f"환율: {info['usd_krw']:.2f}₩/$\n"
            f"국내 금(원/g, 추정): {info['korean']:.0f}원\n"
            f"프리미엄: {info['premium']:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"최근 7일 평균 대비: {level} ({avg7:.2f}%) {trend}"
        )

        send_telegram_text(msg)

    except Exception as e:
        try:
            send_telegram_text(f"🔥 오류 발생: {e}")
        except Exception:
            print(f"치명적 오류 발생: {e}")

if __name__ == "__main__":
    main()
