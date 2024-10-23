import telegram
from telegram.ext import ApplicationBuilder, CommandHandler
import requests
from dotenv import load_dotenv
import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

# .env 파일 로드
load_dotenv()

token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat_id = os.environ.get('chat_id')

# 이벤트 시작 블록 넘버 설정
START_BLOCK = 167429702

# JSON 파일 경로
TRANSFERS_JSON = 'moodeng_transfers_2.json'
RANKINGS_JSON = 'moodeng_rankings_2.json'

# 스왑 주소 설정
SWAP_ADDRESSES = [
    "0xf50782a24afcb26acb85d086cf892bfffb5731b5",  # 스왑 스캐너
    "0x8d1179873ff63da28642b333569b993ef7796abd",  # 드래곤 스왑
    "0xd9ffa5dd8b595b904f76e3e7d71e4f85c3afa9ae",  # 새로 추가된 주소
    "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df",  # 드래곤 스왑
    "0xea9cb97ed3d711afd07f1ba91b568627d12b6f9f",  # 드래곤 스왑
    "0x4e7bbe1279c8ca0098698ee1f47d0b1ad246d44a"   # KLAY SWAP 
]

MOODENG_ADDRESS = "0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df"

class TelegramBot:
    def __init__(self, name, token, chat_id):
        self.core = telegram.Bot(token)
        self.application = ApplicationBuilder().token(token).build()
        self.id = chat_id
        self.name = name
        self.last_command_time = {}

    async def send_message(self, text, parse_mode=None):
        if self.id:
            await self.core.send_message(chat_id=self.id, text=text, parse_mode=parse_mode)
        else:
            print("Chat ID not set")

    def add_handler(self, cmd, func):
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

    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

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


async def save_transfers():
    """전송 데이터를 수집하고 JSON 파일로 저장. 이전 데이터와 중복되는 시점에서 중단"""
    try:
        # 기존 데이터 로드 또는 새로운 딕셔너리 생성
        transfers_data = {}
        if os.path.exists(TRANSFERS_JSON):
            try:
                with open(TRANSFERS_JSON, 'r') as f:
                    transfers_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Error reading {TRANSFERS_JSON}, starting with empty data")
                transfers_data = {}
        else:
            # 파일이 없으면 빈 JSON 파일 생성
            with open(TRANSFERS_JSON, 'w') as f:
                json.dump({}, f)

        # 기존 데이터의 parent hash 집합 생성
        existing_hashes = set(transfers_data.keys())
        
        page = 1
        new_data_found = False  # 새로운 데이터가 추가되었는지 추적
        
        while True:
            transfers = await get_transfers(page)
            if not transfers:
                break

            found_duplicate = False
            for transfer in transfers:
                block_number = int(transfer['blockNumber'])
                
                # START_BLOCK보다 작거나 같은 블록을 만나면 종료
                if block_number <= START_BLOCK:
                    found_duplicate = True
                    break

                # parentHash 확인
                parent_hash = transfer['parentHash']
                
                # 이미 존재하는 hash를 만나면 종료
                if parent_hash in existing_hashes:
                    found_duplicate = True
                    break
                
                # 새로운 데이터 추가
                if parent_hash not in transfers_data:
                    transfers_data[parent_hash] = {
                        'from_address': transfer['fromAddress'].lower(),
                        'to_address': transfer['toAddress'].lower(),
                        'amount': int(transfer['amount']) / 10**int(transfer['decimals']),
                        'block_number': block_number
                    }
                    new_data_found = True

            # 중복 데이터를 찾았거나 START_BLOCK 이하의 블록을 만났다면 종료
            if found_duplicate:
                break

            page += 1
            await asyncio.sleep(2.5)

        # 새로운 데이터가 있을 때만 파일 저장
        if new_data_found:
            with open(TRANSFERS_JSON, 'w') as f:
                json.dump(transfers_data, f, indent=2)

        return transfers_data
    except Exception as e:
        print(f"Error saving transfers: {e}")
        return None

async def update_rankings():
    """전송 데이터를 분석하여 거래 유형을 추가하고 순위 업데이트"""
    try:
        # 전송 데이터 파일이 없으면 빈 파일 생성
        if not os.path.exists(TRANSFERS_JSON):
            with open(TRANSFERS_JSON, 'w') as f:
                json.dump({}, f)

        # 순위 데이터 파일이 없으면 빈 파일 생성
        if not os.path.exists(RANKINGS_JSON):
            with open(RANKINGS_JSON, 'w') as f:
                json.dump({
                    'last_updated': datetime.now().isoformat(),
                    'start_block': START_BLOCK,
                    'rankings': []
                }, f, indent=2)

        # 전송 데이터 로드
        with open(TRANSFERS_JSON, 'r') as f:
            transfers_data = json.load(f)

        # 지갑별 거래량 계산 및 거래 유형 추가
        wallet_stats = {}
        updated_transfers = {}
        
        for tx_hash, tx_data in transfers_data.items():
            from_address = tx_data['from_address']
            to_address = tx_data['to_address']
            amount = tx_data['amount']
            
            # 거래 유형 분류 및 데이터 업데이트
            tx_type = 'unknown'
            if from_address in SWAP_ADDRESSES and to_address in SWAP_ADDRESSES:
                tx_type = 'skip'
            elif from_address in SWAP_ADDRESSES:
                tx_type = 'buy'
                if to_address not in wallet_stats:
                    wallet_stats[to_address] = {'buy': 0, 'sell': 0}
                wallet_stats[to_address]['buy'] += amount
            elif to_address in SWAP_ADDRESSES:
                tx_type = 'sell'
                if from_address not in wallet_stats:
                    wallet_stats[from_address] = {'buy': 0, 'sell': 0}
                wallet_stats[from_address]['sell'] += amount

            # 기존 데이터에 거래 유형 추가
            updated_transfers[tx_hash] = {
                **tx_data,  # 기존 데이터 유지
                'transaction_type': tx_type  # 거래 유형 추가
            }

        # 업데이트된 전송 데이터 저장
        with open(TRANSFERS_JSON, 'w') as f:
            json.dump(updated_transfers, f, indent=2)

        # 순매수량 계산 및 정렬
        rankings = []
        for address, stats in wallet_stats.items():
            net_purchase = stats['buy'] - stats['sell']
            rankings.append({
                'address': address,
                'net_purchase': net_purchase,
                'buy': stats['buy'],
                'sell': stats['sell']
            })

        rankings.sort(key=lambda x: x['net_purchase'], reverse=True)

        # 순위 데이터 저장
        ranking_data = {
            'last_updated': datetime.now().isoformat(),
            'start_block': START_BLOCK,
            'rankings': rankings
        }

        with open(RANKINGS_JSON, 'w') as f:
            json.dump(ranking_data, f, indent=2)

        return rankings[:10]  # 상위 10개만 반환
    except Exception as e:
        print(f"Error updating rankings: {e}")
        return None    

async def rankings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        # 먼저 전송 데이터 수집
        await context.bot.send_message(
            chat_id=chat_id,
            text="데이터를 수집하고 있습니다. 잠시만 기다려주세요...",
            parse_mode='Markdown'
        )
        
        transfers_data = await save_transfers()
        if transfers_data is None:
            await context.bot.send_message(
                chat_id=chat_id,
                text="데이터 수집 중 오류가 발생했습니다.",
                parse_mode='Markdown'
            )
            return
            
        # 순위 업데이트
        rankings = await update_rankings()
        
        if rankings is None:
            await context.bot.send_message(
                chat_id=chat_id,
                text="순위 업데이트 중 오류가 발생했습니다.",
                parse_mode='Markdown'
            )
            return

        message = "🏆 Net Purchase Ranking (Top 10)\n\n"
        for i, ranking in enumerate(rankings, 1):
            message += f"{i}. `{ranking['address'][:6]}...{ranking['address'][-4:]}`: {ranking['net_purchase']:.2f}\n"
    
        message += f"\n🛒 [BUY MOODENG](https://swapscanner.io/pro/swap?from=0x0000000000000000000000000000000000000000&to=0xedcad4bd04f59e8fcc7c5fc7547e5112ae9923df&chartReady=true)"
        message += f"\n💡 Net purchase amount is calculated as the total purchase volume minus the sell volume through swaps from block {START_BLOCK}."
        message += f"\n💡 API 네트워크 상황에 따라 정확하지 않을 수 있으니 참고만 해주세요. 최종 순위는 트랜잭션 추가 검토 후 정확하게 집계하겠습니다."
        message += f"\n💡 Please note that it may not be accurate depending on the API network situation. The final ranking will be accurately tallied after additional transaction review."
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"Error in rankings_command: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="순위 정보를 가져오는 중 오류가 발생했습니다.",
            parse_mode='Markdown'
        )
        
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

def format_market_cap(value):
    if value >= 1_000_000:
        return f"{value/1_000_000:.2f}M"
    elif value >= 1_000:
        return f"{value/1_000:.2f}k"
    else:
        return f"{value:.2f}"

async def proc_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
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