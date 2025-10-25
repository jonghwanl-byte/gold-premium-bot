import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import matplotlib.pyplot as plt
from io import BytesIO
import openai
from urllib.parse import quote_plus # 텔레그램 메시지 인코딩용

# ---------- 환경 변수 및 초기 설정 ----------
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# [수정] OpenAI 최신 클라이언트 방식으로 초기화
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    openai_client = None
    # 이 오류는 메인 함수에서 처리하여 텔레그램으로 알립니다.

DATA_FILE = "gold_premium_history.json"

# ---------- 텔레그램 ----------
def send_telegram_text(msg):
    # 텔레그램 메시지는 URL 인코딩이 필요합니다.
    encoded_msg = quote_plus(msg)
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                 params={"chat_id": CHAT_ID, "text": encoded_msg})

def send_telegram_photo(image_bytes, caption=""):
    encoded_caption = quote_plus(caption)
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": encoded_caption}
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data)

# ---------- 시세 수집 함수 ----------
def get_korean_gold():
    url = "https://www.koreagoldx.co.kr/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    # KRX 금시세: 원/g (3.75g 한 돈 기준)
    price_per_don = float(soup.select_one("#gold_price").text.replace(",", ""))
    # 1g 당 가격으로 변환 (1돈 = 3.75g)
    return price_per_don / 3.75 

def get_international_gold():
    # [주의] Investing.com은 스크래핑 방어가 강력하며, 언제든 다시 오류가 날 수 있습니다.
    url = "https://www.investing.com/commodities/gold"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"} # User-Agent 강화

    # 403 Forbidden 에러 방지를 위해 세션 사용 시도 (requests.get 대신)
    with requests.Session() as s:
        response = s.get(url, headers=headers)
        response.raise_for_status() # HTTP 오류 발생 시 예외 발생
        soup = BeautifulSoup(response.text, "html.parser")
        
        # [수정] 태그 이름에 관계없이 'data-test' 속성만 사용하여 요소를 찾도록 수정
        # 현재는 <div ...> 이지만, 향후 span이나 다른 태그로 바뀔 수 있음
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        
        if price_element is None:
            # 요소를 찾지 못하면 명시적으로 오류를 발생시켜 main 함수로 전달
            raise ValueError("국제 금 시세 요소를 HTML에서 찾을 수 없습니다. (선택자 변경 가능성 높음)")
            
        # 국제 금 시세: 달러/온스 ($/oz)
        return float(price_element.text.replace(",", ""))

def get_usdkrw():
    url = "https://finance.naver.com/marketindex/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    # 환율: 원/$
    return float(soup.select_one(".value").text.replace(",", ""))

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
    # 최소 2개 이상의 데이터가 있어야 그래프를 그립니다.
    history = history[-7:]
    if len(history) < 2:
        return None
        
    dates = [x["date"] for x in history]
    premiums = [x["premium"] for x in history]

    plt.figure(figsize=(6, 3))
    plt.plot(dates, premiums, marker="o")
    plt.title("금 프리미엄 7일 추세 (%)")
    plt.ylabel("프리미엄(%)")
    plt.xticks(rotation=45, ha='right') # 날짜 겹침 방지
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png")
    plt.close() # 메모리 해제
    buf.seek(0)
    return buf

# ---------- AI 분석 ----------
def analyze_with_ai(today_msg, history):
    if not openai_client:
         return "AI 분석 오류: OpenAI 클라이언트 초기화 실패 (API 키 누락)"
         
    prompt = f"""
다음은 최근 7일간의 금 프리미엄 데이터입니다.
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}

오늘의 주요 데이터:
{today_msg}

이 데이터를 기반으로 한국 금 프리미엄 상승/하락 원인과 간단한 투자 관점 요약을 3줄 이내로 설명해줘.
"""
    try:
        # [수정] 최신 클라이언트 호출 방식
        response = openai_client.chat.completions.create( 
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 분석 오류: {e}"

# ---------- 메인 로직 ----------
def main():
    # 0. 초기 환경 변수 확인 (메시지 전송 함수가 작동하는지 확인)
    if not BOT_TOKEN or not CHAT_ID:
        # 이 경우 텔레그램 알림 자체가 불가능합니다.
        print("FATAL ERROR: TELEGRAM BOT_TOKEN or CHAT_ID is not set in environment.")
        return 
        
    try:
        # 1. 시세 수집
        today = datetime.date.today().isoformat()
        
        # 한국 금 (KRX)
        kg = get_korean_gold()
        
        # 국제 금 (Investing.com 스크래핑은 try-except로 감싸 안정성 확보)
        try:
            intl = get_international_gold()
        except Exception as e:
            # 국제 금 시세 수집 실패 시 알림을 보내고 종료 (가장 흔한 실패 원인)
            send_telegram_text(f"⚠️ 국제 금 시세 수집 실패 (스크래핑 오류): {e}")
            return
            
        # 환율
        usdkrw = get_usdkrw()
        
        # 2. 프리미엄 계산
        # 국제금시세(달러/온스)를 원/그램으로 환산 (1온스 = 31.1035g)
        intl_krw_per_g = intl * usdkrw / 31.1035
        premium = (kg / intl_krw_per_g - 1) * 100

        # 3. 데이터 저장
        history = load_history()
        history.append({"date": today, "premium": round(premium, 2)})
        save_history(history)

        # 4. 메시지 작성
        msg = (
            f"📅 {today} 금 프리미엄 알림\n"
            f"KRX 금시세 (g): {kg:,.0f}원\n"
            f"국제금시세 (oz): ${intl:,.2f}\n"
            f"환율: {usdkrw:,.2f}원/$\n"
            f"👉 금 프리미엄: {premium:+.2f}%"
        )

        # 5. AI 분석 및 최종 메시지
        ai_summary = analyze_with_ai(msg, history)
        full_msg = f"{msg}\n\n🤖 AI 요약:\n{ai_summary}"

        # 6. 텔레그램 전송
        send_telegram_text(full_msg)

        # 7. 그래프 전송
        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption="📈 최근 7일 금 프리미엄 추세")

    except Exception as e:
        # 최종 예외 처리: 다른 예기치 못한 오류 발생 시 알림
        send_telegram_text(f"🔥 치명적인 오류 발생: {e}")

if __name__ == "__main__":
    main()





