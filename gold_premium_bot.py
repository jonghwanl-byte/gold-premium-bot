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

# 0. 초기 환경 변수 확인 (메시지 전송 함수가 작동하기 전 확인)
if not BOT_TOKEN or not CHAT_ID:
    # 이 경우 텔레그램 알림 자체가 불가능합니다.
    print("FATAL ERROR: TELEGRAM_BOT_TOKEN or CHAT_ID is not set in environment.")
    # GitHub Actions 실패로 명확히 표시되도록 종료
    raise EnvironmentError("필수 환경 변수(TELEGRAM_BOT_TOKEN 또는 CHAT_ID) 누락.")

# OpenAI 최신 클라이언트 방식으로 초기화
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    # 키가 잘못되었을 경우, AI 분석 함수에서 이 객체가 None임을 확인하고 처리함
    openai_client = None 

DATA_FILE = "gold_premium_history.json"

# ---------- 텔레그램 ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # 텔레그램 메시지는 URL 인코딩이 필요합니다.
    encoded_msg = quote_plus(msg)
    params = {"chat_id": CHAT_ID, "text": encoded_msg}
    
    response = requests.get(url, params=params)
    
    # [디버깅] 응답 상태와 내용을 로그에 출력하여 문제 원인을 파악합니다.
    print(f"\n--- Telegram API Debug ---")
    print(f"Status Code: {response.status_code}")
    print(f"Response JSON: {response.text}")
    print(f"--------------------------\n")
    
    # HTTP 오류(400, 401 등) 발생 시 예외를 발생시켜 GitHub Actions에 실패를 알립니다.
    response.raise_for_status()

def send_telegram_photo(image_bytes, caption=""):
    encoded_caption = quote_plus(caption)
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": encoded_caption}
    
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data)
    response.raise_for_status()

# ---------- 시세 수집 함수 ----------
def get_korean_gold():
    url = "https://www.koreagoldx.co.kr/"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")
    # KRX 금시세: 원/돈 (3.75g) 기준
    price_per_don = float(soup.select_one("#gold_price").text.replace(",", ""))
    # 1g 당 가격으로 변환 (1돈 = 3.75g)
    return price_per_don / 3.75 

def get_international_gold():
    # Investing.com은 스크래핑 방어가 강력함. 
    url = "https://www.investing.com/commodities/gold"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

    with requests.Session() as s:
        response = s.get(url, headers=headers)
        response.raise_for_status() # 4xx/5xx HTTP 오류 시 예외 발생
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 'data-test' 속성만을 사용하여 태그 이름에 관계없이 요소 찾기
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        
        if price_element is None:
            raise ValueError("국제 금 시세 요소를 HTML에서 찾을 수 없습니다. (선택자 변경/스크래핑 차단)")
            
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
    history = history[-7:]
    if len(history) < 2:
        return None
        
    dates = [x["date"] for x in history]
    premiums = [x["premium"] for x in history]

    plt.figure(figsize=(6, 3))
    plt.plot(dates, premiums, marker="o")
    plt.title("금 프리미엄 7일 추세 (%)")
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
다음은 최근 7일간의 금 프리미엄 데이터입니다.
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}

오늘의 주요 데이터:
{today_msg}

이 데이터를 기반으로 한국 금 프리미엄 상승/하락 원인과 간단한 투자 관점 요약을 3줄 이내로 설명해줘.
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

# ---------- 메인 로직 ----------
def main():
    # 환경 변수 누락 오류는 이미 코드 시작 부분에서 처리됨 (EnvironmentError 발생)
    try:
        # 1. 시세 수집
        today = datetime.date.today().isoformat()
        
        kg = get_korean_gold()
        
        # 국제 금 (스크래핑 오류 발생 가능성이 가장 높으므로 try-except로 감쌈)
        try:
            intl = get_international_gold()
        except Exception as e:
            # 국제 금 시세 수집 실패 시 알림을 보내고 종료
            send_telegram_text(f"⚠️ 국제 금 시세 수집 실패 (스크래핑 오류): {e}")
            return
            
        usdkrw = get_usdkrw()
        
        # 2. 프리미엄 계산
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
        try:
            send_telegram_text(f"🔥 치명적인 오류 발생: {e}")
        except Exception as telegram_error:
            # 텔레그램 발송 자체가 실패하면 GitHub 로그에만 출력
            print(f"ERROR: 최종 오류 알림 발송 실패: {telegram_error}")
            print(f"Original Exception: {e}")


if __name__ == "__main__":
    main()
