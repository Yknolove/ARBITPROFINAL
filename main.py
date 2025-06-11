import os
import logging
import asyncio
import ccxt.async_support as ccxt
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook, start_polling, start_polling
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-domain.com/webhook
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8443))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# In-memory user settings
user_settings = {}

# CCXT async exchange classes mapping
exchange_classes = {
    'binance': ccxt.binance,
    'bybit': ccxt.bybit,
    'bitget': ccxt.bitget
}

async def init_exchange_clients():
    clients = {}
    for name, cls in exchange_classes.items():
        clients[name] = cls({'enableRateLimit': True})
    return clients

async def close_exchange_clients(clients):
    for client in clients.values():
        try:
            await client.close()
        except Exception as e:
            logging.warning(f"Error closing client: {e}")

async def arbitrage_task():
    clients = await init_exchange_clients()
    try:
        while True:
            if not user_settings:
                await asyncio.sleep(60)
                continue
            for user_id, settings in user_settings.items():
                user_exch = settings['exchange']
                buy_rate = settings['buy_rate']
                sell_rate = settings['sell_rate']
                max_volume = settings['max_volume']
                try:
                    ticker_buy = await clients[user_exch].fetch_ticker('USDT/UAH')
                    ask = ticker_buy.get('ask')
                except Exception as e:
                    logging.error(f"Error fetching ticker for {user_exch}: {e}")
                    continue
                if ask is None:
                    continue
                for other_name, client in clients.items():
                    if other_name == user_exch:
                        continue
                    try:
                        ticker_sell = await client.fetch_ticker('USDT/UAH')
                        bid = ticker_sell.get('bid')
                    except Exception as e:
                        logging.error(f"Error fetching ticker for {other_name}: {e}")
                        continue
                    if bid is None:
                        continue
                    if ask <= buy_rate and bid >= sell_rate:
                        profit_unit = bid - ask
                        volume = max_volume
                        profit_total = profit_unit * volume
                        text = (
                            f"🔔 *Arbitrage opportunity!*\n"
                            f"Купить на {user_exch.capitalize()} по {ask} UAH/USDT\n"
                            f"Продать на {other_name.capitalize()} по {bid} UAH/USDT\n"
                            f"Объем: {volume} USDT\n"
                            f"Прибыль: {profit_total:.2f} UAH"
                        )
                        urls = {
                            'binance': 'https://p2p.binance.com/ru/trade/USDT?fiat=UAH',
                            'bybit': 'https://www.bybit.com/ru-ua/c2c',
                            'bitget': 'https://www.bitget.com/ru/p2p/USDT'
                        }
                        markup = InlineKeyboardMarkup().add(
                            InlineKeyboardButton("Открыть P2P", url=urls.get(other_name))
                        )
                        try:
                            await bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown', reply_markup=markup)
                        except Exception as e:
                            logging.error(f"Error sending message to {user_id}: {e}")
            await asyncio.sleep(60)
    finally:
        await close_exchange_clients(clients)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    text = """🤖 *Добро пожаловать в ArbitPRO!* 🤖

Этот бот уведомляет об арбитражных возможностях между биржами Binance, Bybit и Bitget.

Команды:
/set_filters <exchange> <buy_rate> <sell_rate> - установить фильтр для USDT/UAH
Пример: /set_filters Binance 41.20 42.50
/my_settings - показать текущие настройки фильтра
"""
    await message.reply(text, parse_mode='Markdown')

@dp.message_handler(commands=['set_filters'])
async def set_filters(message: types.Message):
    args = message.text.split()
    if len(args) != 4:
        await message.reply(
            "Использование: /set_filters <exchange> <buy_rate> <sell_rate>\n"
            "Пример: /set_filters Binance 41.20 42.50"
        )
        return
    name = args[1].lower()
    if name not in exchange_classes:
        await message.reply("Неподдерживаемая биржа. Доступные: Binance, Bybit, Bitget.")
        return
    try:
        buy_rate = float(args[2])
        sell_rate = float(args[3])
    except ValueError:
        await message.reply("Неправильный формат курсов. Пожалуйста, введите числа, например 41.20")
        return
    user_settings[message.from_user.id] = {
        'exchange': name,
        'buy_rate': buy_rate,
        'sell_rate': sell_rate,
        'max_volume': 100.0
    }
    await message.reply(
        f"Фильтр установлен:\nБиржа: {name.capitalize()}\n"
        f"Покупать ≤ {buy_rate}\nПродавать ≥ {sell_rate}\nМакс объем: $100"
    )

@dp.message_handler(commands=['my_settings'])
async def my_settings(message: types.Message):
    settings = user_settings.get(message.from_user.id)
    if not settings:
        await message.reply("Вы еще не установили фильтр. Используйте /set_filters.")
    else:
        await message.reply(
            f"Ваш фильтр:\nБиржа: {settings['exchange'].capitalize()}\n"
            f"Покупать ≤ {settings['buy_rate']}\n"
            f"Продавать ≥ {settings['sell_rate']}\n"
            f"Макс объем: ${settings['max_volume']}",
            parse_mode='Markdown'
        )

async def on_startup(dp):
    logging.info("Starting arbitrage task...")
    if WEBHOOK_URL:
        logging.info(f"Setting webhook: {WEBHOOK_URL}")
        await bot.set_webhook(WEBHOOK_URL)
    else:
        logging.info("No WEBHOOK_URL, skipping manual webhook removal")
    asyncio.create_task(arbitrage_task())

async def on_shutdown(dp):
    logging.info("Shutting down...")
    if WEBHOOK_URL:
        await bot.delete_webhook()
    await bot.close()

if __name__ == '__main__':
    if WEBHOOK_URL:
        start_webhook(
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            host='0.0.0.0',
            port=PORT,
        )
    else:
        start_polling(dp, skip_updates=True, reset_webhook=True, on_startup=on_startup, on_shutdown=on_shutdown)
