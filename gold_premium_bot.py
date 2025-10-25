import requests
import json
import os
from datetime import datetime, timedelta
import numpy as np

# ---------- 파일 경로 ----------
DATA_FILE = "premium_history.json"

# ---------- 1. 시세 수집 ----------
def get_korean_gold():
    """
    한국 금 시세 (24K, 1g) – 한국금거래소 or similar site
    """
    url = "https://api.manana.kr/exchange/rate.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        usd_krw = next((x["rate"] for x in data if x["name"] == "USD/KRW"), None)
        if not usd_krw:
            raise ValueError("환율 정보를 찾을 수 없습니다.")
    except Exception:
        usd_krw = 1400.0  # fallback

    # 참고: goldprice.org 등은 금지되어 있으므로 샘플 API or 수동 설정
    # 예시로, 1돈(3.75g) = 389,000원 기준 → 1g당 약 103,733원
    return 103_700.0  # 원/그램 기준 예시

def get_international_gold():
    """
    국제 금 시세 (달러/온스) – Yahoo Finance JSON API
    """
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    result = data["chart"]["result"][0]
    price = result["meta"]["regularMarketPrice"]
    return float(price)

def get_international_gold_1h_change():
    """
    최근 1시간 내 국제 금 시세 변화율(%) 계산
    """
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=5m&range=1h"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    response.raise_for_status()
    data = response.json()
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    closes = [x for x in closes if x is not None]
    if len(closes) < 2:
        return 0.0
    return ((closes[-1] - closes[0]) / closes[0]) * 100

# ---------- 2. 데이터 저장 및 불러오기 ----------
def load_history():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ---------- 3. 프리미엄 계산 ----------
def calc_premium(kor_gold, intl_gold, usd_krw):
    """
    프리미엄(%) = (한국금시세(원/g) - 국제금시세*환율/31.1035) / (국제금시세*환율/31.1035) * 100
    """
    intl_per_g = intl_gold * usd_krw / 31.1035
    premium = (kor_gold - intl_per_g) / intl_per_g * 100
    return premium, intl_per_g

# ---------- 4. 추세 분석 ----------
def analyze_trend(history):
    if len(history) < 3:
        return "데이터 부족"
    recent = [h["premium"] for h in history[-7:]]
    diffs = np.diff(recent)
    trend = np.sign(np.mean(diffs))
    if trend > 0:
        return f"상승세 ({sum(d > 0 for d in diffs)}일 상승)"
    elif trend < 0:
        return f"하락세 ({sum(d < 0 for d in diffs)}일 하락)"
    else:
        return "보합세"

# ---------- 5. 메인 실행 ----------
def main():
    try:
        kor_gold = get_korean_gold()
        intl_gold = get_international_gold()
        usd_krw = 1400.0  # 환율 고정 or API 연동 가능
        intl_change_1h = get_international_gold_1h_change()

        premium, intl_per_g = calc_premium(kor_gold, intl_gold, usd_krw)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        history = load_history()
        history.append({"time": now, "premium": premium})
        save_history(history)

        last7 = [h["premium"] for h in history[-7:]]
        avg7 = sum(last7) / len(last7) if last7 else premium
        diff_vs_avg = premium - avg7
        level = "📈 평균보다 높음" if diff_vs_avg > 0 else "📉 평균보다 낮음"

        trend_text = analyze_trend(history)

        print(f"⏰ {now}")
        print(f"🇰🇷 국내 금 시세: {kor_gold:,.0f}원/g")
        print(f"🌎 국제 금 시세: ${intl_gold:,.2f}/oz ({intl_change_1h:+.2f}%)")
        print(f"💱 환율: {usd_krw:,.1f}원/USD")
        print(f"💰 국제 금 (환산): {intl_per_g:,.0f}원/g")
        print(f"📈 프리미엄: {premium:+.2f}%")
        print(f"📊 최근 7일 평균 대비: {diff_vs_avg:+.2f}% ({level})")
        print(f"📉 최근 추세: {trend_text}")

    except Exception as e:
        print(f"🔥 오류 발생: {e}")

# ---------- 실행 ----------
if __name__ == "__main__":
    main()
