# 🪙 금치 프리미엄 알리미 (Gold Premium Notifier)

매일 **아침 8시**, 국제 금 시세와 한국 금 시세를 비교하여  
한국 금 프리미엄(금치 프리미엄)을 **텔레그램으로 자동 알림**하는 봇입니다.

---

## 🚀 기능 요약

- 국제 금 시세 (USD 기준) 자동 수집  
- 한국 금 시세 (KRW 기준) 자동 수집  
- 환율(KRW/USD) 자동 반영  
- 한국 금 프리미엄 비율 계산  
- 매일 오전 8시에 **텔레그램 메시지 자동 발송**
- 💡 AI 분석 기능: 최근 변동 추세 요약 및 간단한 시장 분석 코멘트 자동 포함  

---

## ⚙️ 구성 요소

- **Python 3.9+**
- **라이브러리**  
  ```bash
  pip install requests python-telegram-bot beautifulsoup4 schedule openai
