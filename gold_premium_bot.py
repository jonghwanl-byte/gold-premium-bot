import requests
import time
import datetime
import os
import json
from urllib.parse import quote_plus
import matplotlib.pyplot as plt
from io import BytesIO
import yfinance as yf 
import openai

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

# 1. 국내 금 가격 대용: ACE KRX금현물 ETF 실시간 가격 및 NAV (원/주)
def get_korean_gold_data():
    symbol = "411060.KS" # ACE KRX금현물 종목코드
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        
        market_price = data.get('regularMarketPrice') # 현재 시장 가격 (원/주)
        nav_price = data.get('navPrice')              # 순자산가치 (NAV)
        
        # ⚠️ (수정) 실시간 가격이 없으면 직전 종가를 사용 (장외 시간 대응)
        if market_price is None:
            market_price = data.get('previousClose')
            
        # 시장 가격과 NAV가 모두 없으면 치명적인 오류 발생
        if market_price is None:
             raise ValueError(f"Yahoo Finance: '{symbol}'의 유효한 시장 가격(실시간 또는 종가)을 찾을 수 없습니다. 시장 휴장 가능성이 높습니다.")
        
        if nav_price is None:
             raise ValueError(f"Yahoo Finance: '{symbol}'의 NAV 데이터가 누락되었습니다. (장외 시간/API 오류)")
             
        return market_price, nav_price
    except Exception as e:
        raise RuntimeError(f"KRX 골드 ETF 가격 및 NAV 조회 실패: {type(e).__name__} - {e}")

# 2. Yahoo Finance 가격 조회 (기존과 동일)
def get_yahoo_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        # 환율이나 국제 금 시세도 장외 시간에 regularMarketPrice가 없을 수 있으므로 종가 대체 로직 추가
        price = data.get('regularMarketPrice')
        if price is None:
             price = data.get('previousClose')
             
        if price is None:
             raise ValueError(f"Yahoo Finance: '{symbol}'에 대한 가격 데이터가 누락되었습니다.")
             
        return price
    except Exception as e:
        raise RuntimeError(f"Yahoo Finance '{symbol}' 데이터 조회 실패: {type(e).__name__} - {e}")

# 3. 국제 금 시세 및 환율 가져오기 (NAV 기반으로 로직 변경)
def get_gold_and_fx():
    usd_krw = get_yahoo_price("USDKRW=X") # 원/$
    gold_usd = get_yahoo_price("GC=F")    # 국제 금 선물 가격 ($/oz)
    
    market_price, nav_price = get_korean_gold_data() 
    
    return market_price, nav_price, usd_krw, gold_usd

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
    market_price, nav_price, usd_krw, gold_usd = get_gold_and_fx()
    
    # 괴리율 계산: (시장가 / NAV - 1) * 100
    premium = (market_price / nav_price - 1) * 100 
    
    return {
        "korean": market_price, # KRW/주 (국내 시장 가격)
        "international_krw": nav_price, # NAV 가격 (이론적 국제 환산가 역할)
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
    plt.title("ETF 괴리율 7일 추세 (%)")
    plt.ylabel("괴리율(%)")
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
다음은 최근 7일간의 ETF 괴리율 데이터입니다.
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}

오늘의 주요 데이터:
{today_msg}

이 데이터를 기반으로 ACE KRX금현물 ETF의 괴리율 상승/하락 원인과 간단한 투자 관점 요약을 3줄 이내로 설명해줘.
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
            f"📅 {today} ACE KRX금현물 ETF 괴리율 알림\n"
            f"국내 ETF 시장가 (주당): {info['korean']:,.0f}원\n"
            f"ETF 기준가(NAV) (주당): {info['international_krw']:,.0f}원\n"
            f"국제 금시세 (oz): ${info['gold_usd']:,.2f}\n"
            f"환율: {info['usd_krw']:,.2f}원/$\n"
            f"👉 ETF 괴리율: {info['premium']:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"최근 7일 평균 대비: {level} ({avg7:.2f}%) {trend}"
        )
        
        ai_summary = analyze_with_ai(msg_data, history)
        full_msg = f"{msg_data}\n\n🤖 AI 요약:\n{ai_summary}"

        send_telegram_text(full_msg)

        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption="📈 최근 7일 ETF 괴리율 추세")

    except Exception as e:
        try:
            send_telegram_text(f"🔥 치명적인 오류 발생: {type(e).__name__} - {e}")
        except Exception as telegram_error:
            print(f"ERROR: 최종 오류 알림 발송 실패: {telegram_error}")
            print(f"Original Exception: {e}")

if __name__ == "__main__":
    main()
