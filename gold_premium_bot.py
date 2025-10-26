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
import yfinance as yf 

# ---------- 환경 변수 및 초기 설정 ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("FATAL ERROR: TELEGRAM_BOT_TOKEN or CHAT_ID is not set in environment.")

try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception:
    openai_client = None

DATA_FILE = "gold_premium_history.json"

# ---------- 텔레그램 함수 (기존과 동일) ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    encoded_msg = quote_plus(msg)
    payload = {"chat_id": CHAT_ID, "text": encoded_msg}

    try:
        r = requests.post(url, json=payload, timeout=10)
        
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

# 1. KRX 국내 금 시세 (원/g) - 네이버 금융 스크래핑으로 전환 및 2단계 셀렉터 검증 적용
def get_korean_gold():
    url = "https://finance.naver.com/marketindex/goldDetail.naver" 
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1단계 시도: 가장 일반적인 가격 값 셀렉터 (span.value)
        price_element = soup.select_one("span.value")
        
        if price_element is None:
             # 2단계 시도: 상위 요소(dd.data)를 찾고 그 텍스트에서 가격만 추출
             data_element = soup.select_one("dd.data")
             if data_element:
                 # dd.data의 텍스트를 공백으로 분리하여 첫 번째 요소를 가격으로 간주
                 price_parts = data_element.get_text(separator=' ', strip=True).split()
                 if price_parts:
                     price_text = price_parts[0]
                     # 추출된 텍스트가 가격 형태인지 확인 (콤마 제거 후 숫자 확인)
                     clean_text = price_text.replace(',', '').replace('.', '')
                     if clean_text.isdigit():
                        krx_gold_per_g = float(price_text.replace(",", "").strip())
                        return krx_gold_per_g
             
             # 두 가지 시도 모두 실패 시 오류 발생
             raise ValueError("네이버 금융 페이지에서 KRX 금 시세 요소를 찾지 못했습니다. 구조가 변경되었거나 데이터가 없습니다.")

        # 1단계 시도 성공 시 처리
        krx_gold_per_g = float(price_element.text.replace(",", "").strip())
        
        return krx_gold_per_g # 원/g
        
    except Exception as e:
        raise RuntimeError(f"KRX 국내 금 시세 스크래핑 실패 (네이버 금융): {type(e).__name__} - {e}")

# 2. Yahoo Finance 가격 조회 (기존과 동일)
def get_yahoo_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        price = data.get('regularMarketPrice')
        
        if price is None:
             raise ValueError(f"Yahoo Finance: '{symbol}'에 대한 실시간 시장 가격(regularMarketPrice) 데이터가 누락되었습니다.")
             
        return price
    except Exception as e:
        raise RuntimeError(f"Yahoo Finance '{symbol}' 데이터 조회 실패: {type(e).__name__} - {e}")

# 3. 국제 금 시세 및 환율 가져오기 (기존과 동일)
def get_gold_and_fx():
    usd_krw = get_yahoo_price("USDKRW=X")
    gold_usd = get_yahoo_price("GC=F")
    
    intl_krw_per_g = gold_usd * usd_krw / 31.1035
    
    krx_gold_per_g = get_korean_gold() 

    return krx_gold_per_g, intl_krw_per_g, usd_krw, gold_usd

# ---------- 데이터 처리 및 분석 (기존과 동일) ----------
def load_history():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_history(data):
    data = data[-100:]
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calc_premium():
    korean_gold, intl_krw, usd_krw, gold_usd = get_gold_and_fx()
    premium = (korean_gold / intl_krw - 1) * 100 
    
    return {
        "korean": korean_gold,
        "international_krw": intl_krw,
        "usd_krw": usd_krw,
        "gold_usd": gold_usd,
        "premium": premium
    }

def create_graph(history):
    history = history[-7:]
    if len(history) < 2: return None
        
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

# ---------- 메인 로직 (기존과 동일) ----------
def main():
    try:
        today = datetime.date.today().isoformat()
        
        info = calc_premium()

        history = load_history()
        
        if history and history[-1]["date"] == today:
            history[-1] = {"date": today, "premium": round(info["premium"], 2)}
        else:
            history.append({"date": today, "premium": round(info["premium"], 2)})
            
        save_history(history)

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

        send_telegram_text(full_msg)

        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption="📈 최근 7일 금 프리미엄 추세")

    except Exception as e:
        try:
            send_telegram_text(f"🔥 치명적인 오류 발생: {type(e).__name__} - {e}")
        except Exception as telegram_error:
            print(f"ERROR: 최종 오류 알림 발송 실패: {telegram_error}")
            print(f"Original Exception: {e}")

if __name__ == "__main__":
    main()
