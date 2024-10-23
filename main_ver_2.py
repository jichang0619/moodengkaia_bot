import telegram
from telegram.ext import ApplicationBuilder, CommandHandler
import requests
from dotenv import load_dotenv
import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta  # 이 줄을 수정했습니다
import csv
from telegram import Update
from telegram.ext import ContextTypes

# CSV 파일 초기화
CSV_FILE = 'transaction_log.csv'

# .env 파일 로드
load_dotenv()

token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat_id = os.environ.get('chat_id')

# 이벤트 시작과 끝 블록 넘버 설정 (이 값들은 외부에서 설정 가능) average block time = 1.0s
START_BLOCK = 167429702
END_BLOCK = 168034504

# 스왑 주소 설정 (업데이트됨)
SWAP_ADDRESSES = [
    "0xf50782a24afcb26acb85d086cf892bfffb5731b5",  # 스왑 스캐너
    "0x8d1179873ff63da28642b333569b993ef7796abd",  # 드래곤 스왑
    "0xd9ffa5dd8b595b904f76e3e7d71e4f85c3afa9ae",  # 드래곤 스왑
    "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df",  # Moodeng Contract
    "0xea9cb97ed3d711afd07f1ba91b568627d12b6f9f",  # 드래곤 스왑
    "0x4e7bbe1279c8ca0098698ee1f47d0b1ad246d44a"   # KLAY SWAP 
]

MOODENG_ADDRESS = "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df"

def initialize_csv():
    # 파일이 없으면 헤더를 작성
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['type', 'from_address', 'to_address', 'amount'])

class TelegramBot:
    def __init__(self, name, token, chat_id):
        self.core = telegram.Bot(token)
        self.application = ApplicationBuilder().token(token).build()
        self.id = chat_id
        self.name = name
        self.last_command_time = {}  # 각 사용자의 마지막 명령어 실행 시간을 저장할 딕셔너리

    async def send_message(self, text, parse_mode=None):
        if self.id:
            await self.core.send_message(chat_id=self.id, text=text, parse_mode=parse_mode)
        else:
            print("Chat ID not set")

    def add_handler(self, cmd, func):
        self.application.add_handler(CommandHandler(cmd, func))

    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
    
    def add_handler(self, cmd, func):
        # 핸들러에 쿨다운 체크 래퍼 추가
        self.application.add_handler(CommandHandler(cmd, self.cooldown_wrapper(func)))

    def cooldown_wrapper(self, func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            current_time = datetime.now()
            if user_id in self.last_command_time:
                last_time = self.last_command_time[user_id]
                if current_time - last_time < timedelta(seconds=60):
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="Please wait 60 seconds before using this command again.",
                        parse_mode='Markdown'
                    )
                    return
            self.last_command_time[user_id] = current_time
            await func(update, context)
        return wrapper

async def get_transfers(page):
    url = f"https://api-cypress.klaytnscope.com/v2/tokens/{MOODENG_ADDRESS}/transfers?page={page}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('result', [])
            else:
                print(f"Error fetching transfers: {response.status}")
                return []

async def find_start_page_and_index():
    page = 1
    while True:
        transfers = await get_transfers(page)
        if not transfers:
            return None, None
        
        # 각 페이지는 이미 내림차순으로 정렬되어 있으므로 추가 정렬 불필요
        first_block = int(transfers[0]['blockNumber'])  # 페이지의 가장 최신 블록 (가장 큰 숫자)
        last_block = int(transfers[-1]['blockNumber'])  # 페이지의 가장 오래된 블록 (가장 작은 숫자)
        
        if START_BLOCK < last_block:
            page += 1
            await asyncio.sleep(2.5)
            continue
        
        if START_BLOCK <= first_block and START_BLOCK >= last_block:
            for index, transfer in enumerate(transfers):
                block_number = int(transfer['blockNumber'])
                if block_number < START_BLOCK:
                    return page, index
        
        if START_BLOCK > first_block:
            return page, 0  # 페이지의 모든 블록이 START_BLOCK보다 크면 0 인덱스 반환
        
        await asyncio.sleep(2.5)

async def process_transfers():
    start_page, start_index = await find_start_page_and_index()
    if start_page is None:
        raise Exception("Failed to find a suitable starting point")

    transactions = {}

    # 1페이지부터 start_page까지 순회
    for page in range(1, start_page + 1):
        transfers = await get_transfers(page)

        if page == 1 and start_page == 1:
            # start_page가 1이면 0부터 start_index까지만 처리
            for transfer in transfers[:start_index]:
                await update_transaction_data(transfer, transactions)      
        elif page == start_page:
            # start_page에서는 0부터 start_index까지 처리
            for transfer in transfers[:start_index]:
                await update_transaction_data(transfer, transactions)
        else:
            # 이전 페이지들은 모든 거래를 처리
            for transfer in transfers:
                await update_transaction_data(transfer, transactions)
        await asyncio.sleep(2.5)
        
    return transactions

async def update_transaction_data(transfer, transactions):
    from_address = transfer['fromAddress'].lower()
    to_address = transfer['toAddress'].lower()
    amount = int(transfer['amount']) / 10**int(transfer['decimals'])

    # 거래 상태 구분
    transaction_type = None

    # 두 주소가 스왑 주소인지 확인
    if from_address in SWAP_ADDRESSES and to_address in SWAP_ADDRESSES:
        transaction_type = 'skip'
    elif from_address in SWAP_ADDRESSES:
        transaction_type = 'buy'
        if to_address not in transactions:
            transactions[to_address] = {'buy': 0, 'sell': 0}
        transactions[to_address]['buy'] += amount
    elif to_address in SWAP_ADDRESSES:
        transaction_type = 'sell'
        if from_address not in transactions:
            transactions[from_address] = {'buy': 0, 'sell': 0}
        transactions[from_address]['sell'] += amount

    # CSV 파일에 거래 상태 기록
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([transaction_type, from_address, to_address, amount])

# CSV 파일 초기화 호출
initialize_csv()

async def load_rankings():
    try:
        with open('moodeng_rankings.json', 'r') as f:
            data = json.load(f)
            return data
    except FileNotFoundError:
        return {"rankings": []}

async def update_rankings():
    try:
        previous_data = await load_rankings()
        transactions = await process_transfers()

        current_rankings = {item['address']: item for item in previous_data['rankings']}

        for address, data in transactions.items():
            net_purchase = data['buy'] - data['sell']
            if address in current_rankings:
                current_rankings[address]['net_purchase'] += net_purchase
            else:
                current_rankings[address] = {'address': address, 'net_purchase': net_purchase}

        sorted_rankings = sorted(current_rankings.values(), key=lambda x: x['net_purchase'], reverse=True)

        new_data = {
            'last_updated': datetime.now().isoformat(),
            'start_block': START_BLOCK,
            'end_block': END_BLOCK,
            'rankings': sorted_rankings
        }

        # 새로운 데이터를 기존 데이터 리스트에 추가
        if 'history' not in previous_data:
            previous_data['history'] = []
        previous_data['history'].append(new_data)

        with open('moodeng_rankings.json', 'w') as f:
            json.dump(previous_data, f, indent=2)

        return sorted_rankings[:10]
    except Exception as e:
        print(f"Error updating rankings: {str(e)}")
        return None

async def rankings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        rankings = await update_rankings()
        
        if rankings is None:
            await context.bot.send_message(chat_id=chat_id, text="순위 업데이트 중 오류가 발생했습니다.", parse_mode='Markdown')
            return

        message = "🏆 Net Purchase Ranking (Top 10)\n\n"
        for i, ranking in enumerate(rankings, 1):
            message += f"{i}. `{ranking['address'][:6]}...{ranking['address'][-4:]}`: {ranking['net_purchase']:.2f}\n"
    
        message += f"\n🛒 [BUY MOODENG](https://swapscanner.io/pro/swap?from=0x0000000000000000000000000000000000000000&to=0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df&chartReady=true)"""
        message += f"\n💡 Net purchase amount is calculated as the total purchase volume minus the sell volume through swaps from {START_BLOCK} to {END_BLOCK}."
        message += f"\n💡 API 네트워크 상황에 따라 정확하지 않을 수 있으니 참고만 해주세요. 최종 순위는 트랜잭션 추가 검토 후 정확하게 집계하겠습니다."
        message += f"\n💡 Please note that it may not be accurate depending on the API network situation. The final ranking will be accurately tallied after additional transaction review."
        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    except Exception as e:
        print(f"Error in rankings_command: {e}")
        await context.bot.send_message(chat_id=chat_id, text="순위 정보를 가져오는 중 오류가 발생했습니다.", parse_mode='Markdown')

async def proc_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_message = get_moodeng_price()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=price_message,
        parse_mode='Markdown'
    )
    
def format_market_cap(value):
    if value >= 1_000_000:
        return f"{value/1_000_000:.2f}M"
    elif value >= 1_000:
        return f"{value/1_000:.2f}k"
    else:
        return f"{value:.2f}"

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

async def proc_price(update, context):
    price_message = get_moodeng_price()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=price_message,
        parse_mode='Markdown'
    )

async def main():
    moodeng_kaia_bot = TelegramBot("kaia_bot", token, chat_id)
    moodeng_kaia_bot.add_handler("price", proc_price)
    moodeng_kaia_bot.add_handler("rankings", rankings_command)

    await moodeng_kaia_bot.start()

    while True:
        await asyncio.sleep(1)
        
if __name__ == '__main__':
    asyncio.run(main())