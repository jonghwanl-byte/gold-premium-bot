import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import telegram
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import openai

# ---------- 환경 변수 ----------
# GitHub Secret에 설정한 이름 그대로 가져와야 합니다.
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

openai.api_key = OPENAI_API_KEY
DATA_FILE = "gold_premium_history.json"

# ---------- 시세 수집 함수 ----------
def get_korean_gold():
    url = "https://www.koreagoldx.co.kr/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    return float(soup.select_one("#gold_price").text.replace(",", ""))

def get_international_gold():
    url = "https://www.investing.com/commodities/gold"
    headers = {"User-Agent": "Mozilla/5.0"}
    soup = BeautifulSoup(requests.get(url, headers=headers).text, "html.parser")
    return float(soup.select_one("span[data-test='instrument-price-last']").text.replace(",", ""))

def get_usdkrw():
    url = "https://finance.naver.com/marketindex/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    return float(soup.select_one(".value").text.replace(",", ""))

# ---------- 텔레그램 ----------
def send_telegram_text(msg):
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                 params={"chat_id": CHAT_ID, "text": msg})

def send_telegram_photo(image_bytes, caption=""):
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": caption}
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data)

# ---------- 데이터 저장/불러오기 ----------
def load_history():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- 그래프 생성 ----------
def create_graph(history):
    dates = [x["date"] for x in history[-7:]]
    premiums = [x["premium"] for x in history[-7:]]

    plt.figure(figsize=(6, 3))
    plt.plot(dates, premiums, marker="o")
    plt.title("금 프리미엄 7일 추세 (%)")
    plt.ylabel("프리미엄(%)")
    plt.grid(True)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    return buf

# ---------- AI 분석 ----------
def analyze_with_ai(today_msg, history):
    prompt = f"""
다음은 최근 7일간의 금 프리미엄 데이터입니다.
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}

오늘의 주요 데이터:
{today_msg}

이 데이터를 기반으로 한국 금 프리미엄 상승/하락 원인과 간단한 투자 관점 요약을 3줄 이내로 설명해줘.
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 분석 오류: {e}"

# ---------- 메인 로직 ----------
def main():
    try:
        today = datetime.date.today().isoformat()
        kg = get_korean_gold()
        intl = get_international_gold()
        usdkrw = get_usdkrw()
        intl_krw_per_g = intl * usdkrw / 31.1035
        premium = (kg / intl_krw_per_g - 1) * 100

        history = load_history()
        history.append({"date": today, "premium": round(premium, 2)})
        save_history(history)

        msg = (
            f"📅 {today} 금 프리미엄 알림\n"
            f"KRX 금시세: {kg:,.0f}원/g\n"
            f"국제금시세: ${intl:,.2f}/oz\n"
            f"환율: {usdkrw:,.2f}원/$\n"
            f"👉 금 프리미엄: {premium:+.2f}%"
        )

        ai_summary = analyze_with_ai(msg, history)
        full_msg = f"{msg}\n\n🤖 AI 요약:\n{ai_summary}"

        send_telegram_text(full_msg)

        if len(history) >= 2:
            graph_buf = create_graph(history)
            send_telegram_photo(graph_buf, caption="📈 최근 7일 금 프리미엄 추세")

    except Exception as e:
        send_telegram_text(f"⚠️ 오류 발생: {e}")

if __name__ == "__main__":
    main()

