import requests
import time
import datetime
import os
import json
import matplotlib.pyplot as plt
from io import BytesIO
import yfinance as yf
import openai
# ---------- 환경 변수 및 초기 설정 ----------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_TO")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("FATAL ERROR: TELEGRAM_TOKEN or TELEGRAM_TO is not set in environment.")
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception:
    openai_client = None
DATA_FILE = "gold_premium_history.json"
TROY_OUNCE_TO_GRAM = 31.1035  # 1 트로이 온스 = 31.1035 그램
# ---------- 헬퍼 함수: Unix 타임스탬프를 KST 문자열로 변환 ----------
def timestamp_to_kst(timestamp):
    """Unix 타임스탬프를 'YYYY-MM-DD HH:MM:SS KST' 형식으로 변환"""
    if timestamp is None:
        return "N/A"
    dt_object = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    kst_dt = dt_object.astimezone(kst_tz)
    return kst_dt.strftime('%Y-%m-%d %H:%M:%S KST')
# ---------- 텔레그램 함수 ----------
def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
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
    files = {"photo": image_bytes}
    data = {"chat_id": CHAT_ID, "caption": caption}
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", files=files, data=data, timeout=10)
    response.raise_for_status()
# 1. 국내 금 가격 대용 (ACE KRX금현물 ETF)
def get_korean_gold_data():
    symbol = "411060.KS"
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        market_price = data.get('regularMarketPrice')
        market_time = data.get('regularMarketTime')
        if market_price is None:
            market_price = data.get('previousClose')
        if market_price is None:
            raise ValueError(f"Yahoo Finance: '{symbol}'의 유효한 시장 가격을 찾을 수 없습니다.")
        # :경고: 참고: navPrice는 거의 항상 None일 것이므로,
        # 의존하지 않고 market_price와 time만 반환합니다.
        return market_price, market_time
    except Exception as e:
        raise RuntimeError(f"KRX 골드 ETF 가격 조회 실패: {type(e).__name__} - {e}")
# 2. Yahoo Finance 가격 조회 (국제 금, 환율)
def get_yahoo_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        price = data.get('regularMarketPrice')
        if price is None:
            price = data.get('previousClose')
        if price is None:
            raise ValueError(f"Yahoo Finance: '{symbol}'에 대한 가격 데이터가 누락되었습니다.")
        return price
    except Exception as e:
        raise RuntimeError(f"Yahoo Finance '{symbol}' 데이터 조회 실패: {type(e).__name__} - {e}")
# 3. 모든 데이터 가져오기
def get_gold_and_fx_data():
    usd_krw = get_yahoo_price("USDKRW=X")  # 원/달러 환율
    gold_usd = get_yahoo_price("GC=F")     # 국제 금 (1 온스 당 USD)
    market_price, market_time = get_korean_gold_data() # 국내 ETF 가격
    return market_price, usd_krw, gold_usd, market_time
# ---------- 데이터 처리 및 분석 ----------
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
# :경고: (핵심 수정) calc_premium: 이론적 NAV를 직접 계산
def calc_premium():
    """
    국제 금 시세와 환율을 기준으로 이론적 NAV를 계산하고,
    국내 ETF 시장 가격과 비교하여 프리미엄(괴리율)을 계산합니다.
    """
    market_price, usd_krw, gold_usd, market_time = get_gold_and_fx_data()
    # 1. 국제 금 1g당 달러 가격 계산
    gold_usd_per_gram = gold_usd / TROY_OUNCE_TO_GRAM
    # 2. 국제 금 1g당 원화 가격 계산 (이것이 "이론적 NAV")
    theoretical_nav = gold_usd_per_gram * usd_krw
    # 3. 프리미엄(괴리율) 계산: (실제 시장가 / 이론적 NAV) - 1
    #    (market_price / theoretical_nav - 1) * 100
    premium = (market_price / theoretical_nav - 1) * 100
    return {
        "korean": market_price,        # 국내 ETF 시장가 (원)
        "international_krw": theoretical_nav, # 국제 금 1g 이론가 (원)
        "usd_krw": usd_krw,             # 환율 (원/달러)
        "gold_usd": gold_usd,           # 국제 금 (달러/온스)
        "premium": premium,           # 괴리율 (%)
        "market_time": market_time,     # ETF 시장 시간
        "warning_msg": ":흰색_확인_표시: 이론적 NAV 기준 계산" # 이제 경고가 아님
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
다음은 최근 7일간의 ETF 괴리율 데이터입니다. (괴리율 = (국내 ETF 가격 / 국제 금 1g 원화환산가) - 1)
{json.dumps(history[-7:], ensure_ascii=False, indent=2)}
오늘의 주요 데이터:
{today_msg}
이 데이터를 기반으로 ACE KRX금현물 ETF의 괴리율(프리미엄) 상승/하락 원인과 간단한 투자 관점 요약을 3줄 이내로 설명해줘.
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
# ⚠️ (핵심 수정) main: 'premium is None' 분기 제거
def main():
    try:
        today = datetime.date.today().isoformat()
        # 1. (수정) calc_premium()은 이제 항상 유효한 값을 반환 (데이터 조회 실패 시 예외 발생)
        info = calc_premium()
        history = load_history()
        current_premium = info["premium"]
        change = 0.0
        final_timestamp = info["market_time"]
        # 2. (수정) 'premium is None' 분기 로직이 더 이상 필요 없음.
        #    계산이 실패하면 get_gold_and_fx_data() 단계에서 예외가 발생함.
        # 유효한 현재 데이터만 히스토리에 저장
        if history and history[-1]["date"] == today:
            history[-1] = {"date": today, "premium": round(current_premium, 2)}
        else:
            history.append({"date": today, "premium": round(current_premium, 2)})
        save_history(history)
        prev_premium_data = [h for h in history if h["date"] != today]
        prev = prev_premium_data[-1]["premium"] if prev_premium_data else info["premium"]
        change = info["premium"] - prev
        last7 = [x["premium"] for x in history[-7:]]
        avg7 = sum(last7)/len(last7) if last7 else 0
        level = "고평가" if info["premium"] > avg7 else "저평가"
        trend = ":상승세인_차트: 상승세" if change > 0 else ":하락세인_차트: 하락세"
        # 최종 집계 시간 문자열 생성
        if isinstance(final_timestamp, int):
            time_str = f"실시간 ({timestamp_to_kst(final_timestamp)})"
        elif isinstance(final_timestamp, str): # (이 로직은 이제 사용되지 않을 수 있음)
            time_str = f"최근 기록 ({final_timestamp})"
        else:
            time_str = f"현재 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')})"
        # 텔레그램 메시지 구성
        msg_data = (
            f":날짜: {today} ACE KRX금현물 ETF 괴리율 알림\n"
            f"기준 일시: {time_str}\n"
            f"{info['warning_msg']}\n"
            f"국내 ETF 시장가 (주당): {info['korean']:,.0f}원\n"
            f"국제 금 1g 이론가 (NAV): {info['international_krw']:,.0f}원\n"
            f"국제 금시세 (oz): ${info['gold_usd']:,.2f}\n"
            f"환율: {info['usd_krw']:,.2f}원/$\n"
            f":오른쪽을_가리키는_손_모양: ETF 괴리율: {info['premium']:+.2f}% ({change:+.2f}% vs 전일)\n"
            f"최근 7일 평균 대비: {level} ({avg7:.2f}%) {trend}"
        )
        ai_summary = analyze_with_ai(msg_data, history)
        full_msg = f"{msg_data}\n\n:로봇_얼굴: AI 요약:\n{ai_summary}"
        send_telegram_text(full_msg)
        graph_buf = create_graph(history)
        if graph_buf:
            send_telegram_photo(graph_buf, caption=":상승세인_차트: 최근 7일 ETF 괴리율 추세")
    except Exception as e:
        try:
            # :경고: (수정) 오류 메시지에도 'traceback'을 포함하면 디버깅에 더 좋습니다.
            import traceback
            error_msg = f":불: 치명적인 오류 발생: {type(e).__name__} - {e}\n\n{traceback.format_exc()}"
            send_telegram_text(error_msg[:4000]) # 텔레그램 최대 길이 제한
        except Exception as telegram_error:
            print(f"ERROR: 최종 오류 알림 발송 실패: {telegram_error}")
            print(f"Original Exception: {e}")
if __name__ == "__main__":
    main()
