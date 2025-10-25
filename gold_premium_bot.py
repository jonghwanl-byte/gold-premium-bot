import requests
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

# ---------- Yahoo Finance ----------
def get_yahoo_price(symbol):
    """Yahoo Finance 실시간 시세 조회"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"Yahoo 데이터 없음: {symbol}")
    return result[0]["meta"]["regularMarketPrice"]

def get_gold_and_fx():
    """Yahoo에서 금 시세 및 환율 조회"""
    gold_usd = get_yahoo_price("XAUUSD=X")     # 금 $/oz
    usdkrw = get_yahoo_price("USDKRW=X")       # 원/$
    return gold_usd, usdkrw

# ---------- 국내 금 시세 (₩/g) ----------
def get_korean_gold_price_yahoo():
    """국제 금 시세를 환율로 환산해 국내 금시세(₩/g) 추정"""
    gold_usd, usdkrw = get_gold_and_fx()
    gold_krw_per_g = gold_usd * usdkrw / 31.1035  # 1oz = 31.1035g
    return gold_krw_per_g, gold_usd, usdkrw

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
- 최근 평균 대비 현재 프리미엄 수준이 높은지/낮은지
- 프리미엄 변동 추세 (상승세/하락세)
- 투자 관점에서 간단 요약 (2~3줄)
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

        # 1️⃣ 금 시세 및 환율 가져오기 (Yahoo 기반)
        krx_gold, intl_usd, usdkrw = get_korean_gold_price_yahoo()

        # 2️⃣ 프리미엄 계산
        intl_krw_per_g = intl_usd * usdkrw / 31.1035
        premium = (krx_gold / intl_krw_per_g - 1) * 100  # 이론상 0% (기준)

        # 3️⃣ 기록 저장
        history = load_history()
        history.append({"date": today, "premium": round(premium, 2)})
        save_history(history)

        # 4️⃣ 전일 대비 & 7일 평균 비교
        prev = history[-2]["premium"] if len(history) > 1 else premium
        change = premium - prev
        avg7 = sum(x["premium"] for x in history[-7:]) / min(7, len(history))
        rel_level = "고평가" if premium > avg7 else "저평가"

        # 5️⃣ 메시지 구성
        msg = (
            f"📅 {today} 금 프리미엄 알림 (Yahoo 기반)\n"
            f"국제 금시세 ($/oz): {intl_usd:,.2f}\n"
            f"환율: {usdkrw:,.2f}₩/$\n"
            f"환산 금시세 (₩/g): {krx_gold:,.0f}\n"
            f"👉 프리미엄: {premium:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"📊 최근 7일 평균 대비: {rel_level} ({avg7:.2f}%)"
        )

        ai_summary = analyze_with_ai(msg, history)
        full_msg = f"{msg}\n\n🤖 AI 요약:\n{ai_summary}"

        # 6️⃣ 텔레그램 발송
        send_telegram_text(full_msg)

        # 7️⃣ 그래프 발송
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
