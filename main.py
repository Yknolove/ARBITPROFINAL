import os
import logging
import asyncio
import ccxt.async_support as ccxt
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# Логирование
logging.basicConfig(level=logging.INFO)

# Переменные окружения
BOT_TOKEN   = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com/webhook
WEBHOOK_PATH= "/webhook"
PORT        = int(os.getenv("PORT", 8443))  # Render default порт для Web Services

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(bot)

# Настройки пользователей (in-memory)
user_settings = {}

# Карта бирж для CCXT
exchange_classes = {
    'binance': ccxt.binance,
    'bybit':   ccxt.bybit,
    'bitget':  ccxt.bitget
}

async def init_exchange_clients():
    clients = {}
    for name, cls in exchange_classes.items():
        clients[name] = cls({'enableRateLimit': True})
    return clients

async def close_exchange_clients(clients):
    for c in clients.values():
        try:
            await c.close()
        except:
            pass

async def arbitrage_task():
    clients = await init_exchange_clients()
    try:
        while True:
            if not user_settings:
                await asyncio.sleep(60)
                continue
            for uid, s in user_settings.items():
                exch, buy, sell, vol = s['exchange'], s['buy_rate'], s['sell_rate'], s['max_volume']
                try:
                    tick = await clients[exch].fetch_ticker('USDT/UAH')
                    ask = tick.get('ask')
                except:
                    continue
                if ask is None:
                    continue
                for other, client in clients.items():
                    if other == exch:
                        continue
                    try:
                        t2 = await client.fetch_ticker('USDT/UAH')
                        bid = t2.get('bid')
                    except:
                        continue
                    if bid is None:
                        continue
                    if ask <= buy and bid >= sell:
                        profit = (bid - ask) * vol
                        text = (
                            f"🔔 *Arbitrage opportunity!*\\n"
                            f"Купить на {exch.capitalize()} по {ask} UAH/USDT\\n"
                            f"Продать на {other.capitalize()} по {bid} UAH/USDT\\n"
                            f"Объем: {vol} USDT\\n"
                            f"Прибыль: {profit:.2f} UAH"
                        )
                        urls = {
                            'binance': 'https://p2p.binance.com/ru/trade/USDT?fiat=UAH',
                            'bybit':   'https://www.bybit.com/ru-ua/c2c',
                            'bitget':  'https://www.bitget.com/ru/p2p/USDT'
                        }
                        markup = InlineKeyboardMarkup().add(
                            InlineKeyboardButton("Открыть P2P", url=urls[other])
                        )
                        await bot.send_message(uid, text, parse_mode='Markdown', reply_markup=markup)
            await asyncio.sleep(60)
    finally:
        await close_exchange_clients(clients)

# /start и меню
@dp.message_handler(commands=['start'])
async def cmd_start(msg: types.Message):
    await msg.reply(
        "🤖 *Добро пожаловать в ArbitPRO!* 🤖\n\n"
        "Команды:\n"
        "/set_filters <exchange> <buy_rate> <sell_rate> — установить фильтр\n"
        "Пример: /set_filters Binance 41.20 42.50\n"
        "/my_settings — показать настройки",
        parse_mode='Markdown'
    )

@dp.message_handler(commands=['set_filters'])
async def set_filters(msg: types.Message):
    parts = msg.text.split()
    if len(parts) != 4:
        return await msg.reply("Использование: /set_filters <exchange> <buy_rate> <sell_rate>")
    name = parts[1].lower()
    if name not in exchange_classes:
        return await msg.reply("Доступные: Binance, Bybit, Bitget")
    try:
        b, s = float(parts[2]), float(parts[3])
    except:
        return await msg.reply("Неверный формат чисел. Пример: /set_filters Binance 41.20 42.50")
    user_settings[msg.from_user.id] = {
        'exchange':   name,
        'buy_rate':   b,
        'sell_rate':  s,
        'max_volume': 100.0
    }
    await msg.reply(f"Фильтр: {name.capitalize()}, buy≤{b}, sell≥{s}, max=100 USDT")

@dp.message_handler(commands=['my_settings'])
async def my_settings(msg: types.Message):
    s = user_settings.get(msg.from_user.id)
    if not s:
        return await msg.reply("Вы ещё не установили фильтр. /set_filters")
    await msg.reply(
        f"Биржа: {s['exchange'].capitalize()}, buy≤{s['buy_rate']}, sell≥{s['sell_rate']}, max={s['max_volume']}",
        parse_mode='Markdown'
    )

# Health-check для Render
async def handle_root(request):
    return web.Response(text="OK")
web_app = web.Application()
web_app.router.add_get("/", handle_root)

# Запуск webhook
async def on_startup(dp):
    logging.info("Setting webhook…")
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(arbitrage_task())

async def on_shutdown(dp):
    logging.info("Deleting webhook and closing…")
    await bot.delete_webhook()
    await bot.close()

if __name__ == '__main__':
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host='0.0.0.0',
        port=PORT,
        web_app=web_app
    )
