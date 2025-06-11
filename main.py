import os
import logging
import asyncio
import ccxt.async_support as ccxt
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN   = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://your-app.onrender.com/webhook
WEBHOOK_PATH = "/webhook"
PORT        = int(os.getenv("PORT", 8443))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(bot)

# In-memory user settings
user_settings = {}

# CCXT async exchange classes mapping
exchange_classes = {
    'binance': ccxt.binance,
    'bybit':   ccxt.bybit,
    'bitget':  ccxt.bitget
}

# Set up aiohttp web application and routes
app = web.Application()
# Health check endpoint
async def handle_root(request):
    return web.Response(text="OK")
app.router.add_get("/", handle_root)
# Webhook endpoint
app.router.add_post(WEBHOOK_PATH, dp.webhook_handler)
# Assign web app to dispatcher
dp.web_app = app

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
                exch     = settings['exchange']
                buy_rate = settings['buy_rate']
                sell_rate= settings['sell_rate']
                max_vol  = settings['max_volume']
                try:
                    ticker_buy = await clients[exch].fetch_ticker('USDT/UAH')
                    ask = ticker_buy.get('ask')
                except Exception:
                    continue
                if ask is None:
                    continue
                for other, client in clients.items():
                    if other == exch:
                        continue
                    try:
                        ticker_sell = await client.fetch_ticker('USDT/UAH')
                        bid = ticker_sell.get('bid')
                    except Exception:
                        continue
                    if bid is None:
                        continue
                    if ask <= buy_rate and bid >= sell_rate:
                        profit = (bid - ask) * max_vol
                        text = (
                            f"🔔 *Arbitrage opportunity!*\n"
                            f"Купить на {exch.capitalize()} по {ask} UAH/USDT\n"
                            f"Продать на {other.capitalize()} по {bid} UAH/USDT\n"
                            f"Объем: {max_vol} USDT\n"
                            f"Прибыль: {profit:.2f} UAH"
                        )
                        urls = {
                            'binance': 'https://p2p.binance.com/ru/trade/USDT?fiat=UAH',
                            'bybit':   'https://www.bybit.com/ru-ua/c2c',
                            'bitget':  'https://www.bitget.com/ru/p2p/USDT'
                        }
                        markup = InlineKeyboardMarkup().add(
                            InlineKeyboardButton("Открыть P2P", url=urls.get(other))
                        )
                        await bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown', reply_markup=markup)
            await asyncio.sleep(60)
    finally:
        await close_exchange_clients(clients)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.reply(
        "🤖 *Добро пожаловать в ArbitPRO!* 🤖\n\n"
        "Команды:\n"
        "/set_filters <exchange> <buy_rate> <sell_rate> — установить фильтр\n"
        "Пример: /set_filters Binance 41.20 42.50\n"
        "/my_settings — показать текущие настройки",
        parse_mode='Markdown'
    )

@dp.message_handler(commands=['set_filters'])
async def set_filters(message: types.Message):
    parts = message.text.split()
    if len(parts) != 4:
        return await message.reply("Использование: /set_filters <exchange> <buy_rate> <sell_rate>")
    name = parts[1].lower()
    if name not in exchange_classes:
        return await message.reply("Доступные: Binance, Bybit, Bitget")
    try:
        b, s = float(parts[2]), float(parts[3])
    except Exception:
        return await message.reply("Неверный формат цен. Пример: /set_filters Binance 41.20 42.50")
    user_settings[message.from_user.id] = {
        'exchange':   name,
        'buy_rate':   b,
        'sell_rate':  s,
        'max_volume': 100.0
    }
    await message.reply(f"Фильтр установлен: {name.capitalize()}, buy≤{b}, sell≥{s}, max=100 USDT")

@dp.message_handler(commands=['my_settings'])
async def my_settings(message: types.Message):
    settings = user_settings.get(message.from_user.id)
    if not settings:
        return await message.reply("Фильтр не установлен. /set_filters")
    await message.reply(
        f"Биржа: {settings['exchange'].capitalize()}, buy≤{settings['buy_rate']}, "
        f"sell≥{settings['sell_rate']}, max={settings['max_volume']}",
        parse_mode='Markdown'
    )

async def on_startup(dp):
    logging.info("Setting webhook and starting arbitrage task")
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(arbitrage_task())

async def on_shutdown(dp):
    logging.info("Deleting webhook and closing bot")
    await bot.delete_webhook()
    await bot.close()

if __name__ == "__main__":
    logging.info("Starting webhook mode")
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host="0.0.0.0",
        port=PORT,
        skip_updates=True,
    )
