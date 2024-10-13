import telegram
from telegram.ext import Application, CommandHandler
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
        self.application = Application.builder().token(token).build()
        self.id = chat_id
        self.name = name

    def send_message(self, text):
        if self.id:
            self.core.send_message(chat_id=self.id, text=text)
        else:
            print("Chat ID not set")

    def stop(self):
        self.application.stop()

    def add_handler(self, cmd, func):
        self.application.add_handler(CommandHandler(cmd, func))

    def start(self):
        self.application.run_polling()

# 가격 정보를 가져오는 함수
def get_moodeng_price():
    url = "https://api.swapscanner.io/v1/tokens/prices"
    moodeng_address = "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df"
    kaia_address = "0x0000000000000000000000000000000000000000"
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # 에러 발생 시 예외를 발생시킵니다.
        data = response.json()
        
        if moodeng_address in data:
            md_price = float(data[moodeng_address])
            kaia_price = float(data[kaia_address])
            md_kaia_price = md_price/kaia_price
            return f"${md_price:.8f}", f"{md_kaia_price:.8f}"
        else:
            return "MOODENG 가격 정보를 찾을 수 없습니다."
    except requests.RequestException as e:
        return f"가격 정보를 가져오는 데 실패했습니다: {str(e)}"

# /price 명령어 처리 함수
async def proc_price(update, context):
    md_price, md_kaia_price = get_moodeng_price()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"MOODENG price: {md_price}\nMOODENG/KAIA price: {md_kaia_price}")

# 봇 설정
moodeng_kaia_bot = TelegramBot("kaia_bot", token, chat_id)

# 명령어 처리 추가
moodeng_kaia_bot.add_handler("price", proc_price)

# 봇 시작
moodeng_kaia_bot.start()