import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import matplotlib.pyplot as plt
from io import BytesIO
import openai
from urllib.parse import quote_plus

# ---------- 환경 변수 및 초기 설정 ----------
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("필수 환경 변수(TELEGRAM_BOT_TOKEN 또는 CHAT_ID) 누락.")

try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception:
    openai_client = None

DATA_FILE = "gold_premium_history.json"

# ---------- 텔레그램 ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    encoded_msg = quote_plus(msg)
    params = {"chat_id": CHAT_ID, "text": encoded_msg}
    response = requests.get(url, params=params)
    print(f"[Telegram] Status {response.status_code}: {response.text}")
    response.raise_for_status()

def send_telegram_photo(image_bytes, caption=""):
    encoded_caption = quote_plus(caption)
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": encoded_caption}
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data)
    response.raise_for_status()

# ---------- 시세 수집 함수 ----------
def get_korean_gold():
    """한국 KRX 금시세 (₩/g)"""
    url = "https://www.koreagoldx.co.kr/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    price_per_don = float(soup.select_one("#gold_price").text.replace(",", ""))
    return price_per_don / 3.75  # 1돈 = 3.75g

def get_yahoo_price(symbol):
    """Yahoo Finance에서 심볼 단가 가져오기"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data["chart"]["result"][0]["meta"]["regularMarketPrice"]

def get_international_gold():
    """국제 금 시세 ($/oz)"""
    return get_yahoo_price("GC=F")

def get_usdkrw():
    """원/달러 환율"""
    return get_yahoo_price("USDKRW=X")

# ---------- 데이터 저장/불러오기 ----------
def load_history():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- 그래프 ----------
def create_graph(history):
    history = history[-7:]
    if len(history) < 2:
        return None

    dates = [x["date"] for x in history]
    premiums = [x["premium"] for x in history]

    plt.figure(figsize=(6, 3))
    plt.plot(dates, premiums, marker="o", linewidth=2)
    plt.title("📈 최근 7일 금 프리미엄 추세 (%)")
    plt.ylabel("프리미엄(%)")
    plt.xticks(rotation=45, ha='right')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

# ---------- AI 분석 ----------
def analyze_with_ai(today_msg, history):
    if not openai_client:
        return "AI 분석 오류: OpenAI 클라이언트 초기화 실패 (API 키 누락)"
    
    prompt = f"""
다음은 최근 7일간 금 프리미엄 데이터입니다.
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}

오늘의 주요 데이터:
{today_msg}

이 데이터를 기반으로
- 현재 프리미엄 수준이 최근 평균 대비 고/저인지
- 프리미엄 변동 추세(상승세/하락세)
- 투자자 관점에서 2~3줄 요약
형태로 간결히 설명해줘.
"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 분석 오류: {e}"

# ---------- 메인 ----------
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

        # 전일 대비 변동
        prev = history[-2]["premium"] if len(history) > 1 else premium
        change = premium - prev

        # 7일 평균 대비 비교
        avg7 = sum(x["premium"] for x in history[-7:]) / min(7, len(history))
        rel_level = "고평가" if premium > avg7 else "저평가"

        msg = (
            f"📅 {today} 금 프리미엄 알림\n"
            f"KRX 금시세 (₩/g): {kg:,.0f}\n"
            f"국제 금시세 ($/oz): {intl:,.2f}\n"
            f"환율: {usdkrw:,.2f}₩/$\n"
            f"👉 프리미엄: {premium:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"📊 최근 7일 평균 대비: {rel_level} ({avg7:.2f}%)"
        )

        ai_summary = analyze_with_ai(msg, history)
        full_msg = f"{msg}\n\n🤖 AI 요약:\n{ai_summary}"
        send_telegram_text(full_msg)

        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption="최근 7일 프리미엄 추세")

    except Exception as e:
        try:
            send_telegram_text(f"🔥 오류 발생: {e}")
        except Exception:
            print(f"치명적 오류 발생: {e}")

if __name__ == "__main__":
    main()
