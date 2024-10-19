import telegram
from telegram.ext import ApplicationBuilder, CommandHandler
import requests
from dotenv import load_dotenv
import os

# .env 파일 로드
load_dotenv()

token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat_id = os.environ.get('chat_id')

class TelegramBot:
    def __init__(self, name, token, chat_id):
        self.core = telegram.Bot(token)
        self.application = ApplicationBuilder().token(token).build()
        self.id = chat_id
        self.name = name

    def send_message(self, text, parse_mode=None):
        if self.id:
            self.core.send_message(chat_id=self.id, text=text, parse_mode=parse_mode)
        else:
            print("Chat ID not set")

    def stop(self):
        self.application.stop()

    def add_handler(self, cmd, func):
        self.application.add_handler(CommandHandler(cmd, func))

    def start(self):
        self.application.run_polling()

def format_market_cap(value):
    if value >= 1_000_000:
        return f"{value/1_000_000:.2f}M"
    elif value >= 1_000:
        return f"{value/1_000:.2f}k"
    else:
        return f"{value:.2f}"

# 가격 정보를 가져오는 함수
def get_moodeng_price():
    url = "https://api.swapscanner.io/v1/tokens/prices"
    moodeng_address = "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df"
    kaia_address = "0x0000000000000000000000000000000000000000"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if moodeng_address in data:
            md_price = float(data[moodeng_address])
            kaia_price = float(data[kaia_address])
            md_kaia_price = md_price/kaia_price
            market_cap = md_price * 1_000_000_000
            formatted_market_cap = format_market_cap(market_cap)
            
            # 포맷팅된 메시지 생성
            message = f"""
[MOODENG](https://moodengkaia.com)
[CA](https://kaiascope.com/token/{moodeng_address}) : `{moodeng_address}`
💵 Price: ${md_price:.8f}
💰 Market Cap: ${formatted_market_cap}
📊 MOODENG/KAIA: {md_kaia_price:.8f}
🛒 [BUY MOODENG](https://swapscanner.io/pro/swap?from=0x0000000000000000000000000000000000000000&to=0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df&chartReady=true)
"""
            return message
        else:
            return "MOODENG 가격 정보를 찾을 수 없습니다."
    except requests.RequestException as e:
        return f"가격 정보를 가져오는 데 실패했습니다: {str(e)}"

# /price 명령어 처리 함수
async def proc_price(update, context):
    price_message = get_moodeng_price()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=price_message,
        parse_mode='Markdown'
    )

# 봇 설정
moodeng_kaia_bot = TelegramBot("kaia_bot", token, chat_id)

# 명령어 처리 추가
moodeng_kaia_bot.add_handler("price", proc_price)

# 봇 시작
moodeng_kaia_bot.start()