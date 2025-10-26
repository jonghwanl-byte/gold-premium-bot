import requests
import time
import datetime
import os
import json
import openai
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from io import BytesIO
import yfinance as yf # yfinance 라이브러리 추가

# ---------- 환경 변수 및 초기 설정 ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 필수 환경 변수 누락 시 즉시 종료 (텔레그램 알림도 불가능한 상태)
if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("FATAL ERROR: TELEGRAM_BOT_TOKEN or CHAT_ID is not set in environment.")

# OpenAI 클라이언트 초기화
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception:
    openai_client = None

DATA_FILE = "gold_premium_history.json"

# ---------- 텔레그램 (디버깅 로직 포함) ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    encoded_msg = quote_plus(msg)
    payload = {"chat_id": CHAT_ID, "text": encoded_msg}

    try:
        r = requests.post(url, json=payload, timeout=10)
        
        # [디버깅 로그] 텔레그램 API 응답을 출력 (문제 발생 시 원인 파악용)
        print(f"\n--- Telegram API Debug ---")
        print(f"Status Code: {r.status_code}")
        print(f"Response JSON: {r.text}")
        print(f"--------------------------\n")

        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"텔레그램 메시지 발송 실패: {e}")

def send_telegram_photo(image_bytes, caption=""):
    encoded_caption = quote_plus(caption)
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": encoded_caption}
    
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data, timeout=10)
    response.raise_for_status()

# ---------- 시세 수집 함수 ----------

# 1. KRX 국내 금 시세 (원/g) - 스크래핑 셀렉터 재수정 반영
def get_korean_gold():
    url = "https://www.koreagoldx.co.kr/"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # ⚠️ (재수정된 셀렉터) #buy_price ID는 1돈(3.75g) 살 때 가격을 나타냅니다.
        gold_price_element = soup.select_one("#buy_price") 

        if gold_price_element is None:
             raise ValueError("KRX 금 시세 요소(ID: #buy_price)를 찾지 못했습니다. 웹사이트 구조가 다시 변경되었을 수 있습니다.")
             
        # 시세 텍스트에서 콤마 제거 후 실수로 변환
        price_per_don = float(gold_price_element.text.replace(",", "").strip())
        
        return price_per_don / 3.75 # 원/g으로 환산
    except Exception as e:
        # 오류가 발생하면, 호출한 쪽(get_gold_and_fx)에서 처리할 수 있도록 명확한 RuntimeError 발생
        raise RuntimeError(f"KRX 국내 금 시세 스크래핑 실패: {type(e).__name__} - {e}")

# 2. Yahoo Finance 가격 조회 (yfinance 사용) - 데이터 누락 처리 강화
def get_yahoo_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        price = data.get('regularMarketPrice')
        
        if price is None:
             # (개선) 가격 데이터 누락 시 오류 메시지 구체화
             raise ValueError(f"Yahoo Finance: '{symbol}'에 대한 실시간 시장 가격(regularMarketPrice) 데이터가 누락되었습니다.")
             
        return price
    except Exception as e:
        # 오류가 발생하면, 호출한 쪽(get_gold_and_fx)에서 처리할 수 있도록 명확한 RuntimeError 발생
        raise RuntimeError(f"Yahoo Finance '{symbol}' 데이터 조회 실패: {type(e).__name__} - {e}")

# 3. 국제 금 시세 및 환율 가져오기
def get_gold_and_fx():
    # 1. Yahoo Finance를 통해 환율 및 국제 금 선물 가격을 가져옵니다.
    usd_krw = get_yahoo_price("USDKRW=X") # 원/$
    gold_usd = get_yahoo_price("GC=F")    # 국제 금 선물 가격 ($/oz)
    
    # 2. 국제 금 시세를 KRW/g으로 환산 (1oz = 31.1035g)
    intl_krw_per_g = gold_usd * usd_krw / 31.1035
    
    # 3. KRX 국내 금 시세 (원/g)를 가져옴
    krx_gold_per_g = get_korean_gold()

    return krx_gold_per_g, intl_krw_per_g, usd_krw, gold_usd

# ---------- 데이터 처리 및 분석 ----------
def load_history():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            # 파일이 비어있거나 손상된 경우
            return []
    return []

def save_history(data):
    # history는 최근 100개까지만 저장하여 파일 크기 관리
    data = data[-100:]
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calc_premium():
    # 시세 데이터를 모두 가져옵니다. (여기서 오류가 발생하면 main 함수에서 처리됨)
    korean_gold, intl_krw, usd_krw, gold_usd = get_gold_and_fx()
    
    # 프리미엄 계산: (국내 금 가격 / 국제 금 환산 가격 - 1) * 100
    premium = (korean_gold / intl_krw - 1) * 100 
    
    return {
        "korean": korean_gold,
        "international_krw": intl_krw,
        "usd_krw": usd_krw,
        "gold_usd": gold_usd,
        "premium": premium
    }

def create_graph(history):
    # 최근 7일 데이터만 사용
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
    try:
        today = datetime.date.today().isoformat()
        
        # 1. 모든 데이터 수집 및 프리미엄 계산
        info = calc_premium()

        # 2. 히스토리 관리
        history = load_history()
        
        # 오늘 날짜 데이터가 이미 있으면 업데이트 (재실행 대비)
        if history and history[-1]["date"] == today:
            history[-1] = {"date": today, "premium": round(info["premium"], 2)}
        else:
            history.append({"date": today, "premium": round(info["premium"], 2)})
            
        save_history(history)

        # 3. 데이터 분석 및 메시지 구성
        # 전일 데이터는 오늘 데이터 직전의 유효한 데이터로 찾음
        prev_premium_data = [h for h in history if h["date"] != today]
        prev = prev_premium_data[-1]["premium"] if prev_premium_data else info["premium"]
        change = info["premium"] - prev
        
        last7 = [x["premium"] for x in history[-7:]]
        avg7 = sum(last7)/len(last7) if last7 else 0
        level = "고평가" if info["premium"] > avg7 else "저평가"
        trend = "📈 상승세" if change > 0 else "📉 하락세"
        
        msg_data = (
            f"📅 {today} 금 프리미엄 알림\n"
            f"KRX 국내 금시세 (g): {info['korean']:,.0f}원\n"
            f"국제 금시세 (oz): ${info['gold_usd']:,.2f}\n"
            f"환율: {info['usd_krw']:,.2f}원/$\n"
            f"👉 금 프리미엄: {info['premium']:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"최근 7일 평균 대비: {level} ({avg7:.2f}%) {trend}"
        )
        
        ai_summary = analyze_with_ai(msg_data, history)
        full_msg = f"{msg_data}\n\n🤖 AI 요약:\n{ai_summary}"

        # 4. 텔레그램 전송
        send_telegram_text(full_msg)

        # 5. 그래프 전송
        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption="📈 최근 7일 금 프리미엄 추세")

    except Exception as e:
        # 최종 예외 처리: 모든 시세 수집 및 계산 오류를 여기서 포착
        try:
            # 어떤 함수에서 오류가 발생했는지 명시
            send_telegram_text(f"🔥 치명적인 오류 발생: {type(e).__name__} - {e}")
        except Exception as telegram_error:
            # 텔레그램 발송 자체가 실패하면 GitHub 로그에만 출력
            print(f"ERROR: 최종 오류 알림 발송 실패: {telegram_error}")
            print(f"Original Exception: {e}")

if __name__ == "__main__":
    main()
