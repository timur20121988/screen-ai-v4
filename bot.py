import logging
import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import LabeledPrice, PreCheckoutQuery
import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CONFIG_FILE = "config.json"
DEFAULT_PASSWORD = "88101217"
INSTALLER_DIR = "installer_output"

if not os.path.exists(INSTALLER_DIR):
    os.makedirs(INSTALLER_DIR)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# States
class AdminStates(StatesGroup):
    waiting_for_new_password = State()
    waiting_for_installer = State()
    waiting_for_stars_price = State()
    waiting_for_crypto_price = State()
    waiting_for_trial_installer = State()

class UserStates(StatesGroup):
    waiting_for_password = State()
    waiting_for_payment = State()

# Config Management
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "password": DEFAULT_PASSWORD, 
        "installer_path": None,
        "price_stars": 50,
        "price_crypto_usd": 5,
        "cryptopay_token": "",
        "paid_users": [],
        "trial_installer_path": None,
        "trial_usage": {}
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

config = load_config()

# Keyboards
def get_main_keyboard(user_id):
    buttons = [[KeyboardButton(text="🚀 Скачать ScreenAI")]]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔑 Сменить пароль"), KeyboardButton(text="📤 Загрузить установщик")],
            [KeyboardButton(text="⭐ Цена Stars"), KeyboardButton(text="₿ Цена Crypto (USD)")],
            [KeyboardButton(text="📥 Загрузить TRIAL")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_payment_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Оплатить Stars"), KeyboardButton(text="₿ Оплатить Crypto")],
            [KeyboardButton(text="🎁 Попробовать (20 запросов)")],
            [KeyboardButton(text="🔑 Ввести пароль")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

# --- Common Handlers ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот для раздачи программы ScreenAI.\n\n"
        "Чтобы получить установщик, нажми на кнопку ниже.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(F.text == "🚀 Скачать ScreenAI")
async def ask_payment_option(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_config = load_config()
    
    if user_id == ADMIN_ID or user_id in current_config.get("paid_users", []):
        if current_config["installer_path"] and os.path.exists(current_config["installer_path"]):
            await message.answer("✅ Вы уже приобрели ScreenAI! Отправляю файл...", reply_markup=get_main_keyboard(user_id))
            file = FSInputFile(current_config["installer_path"])
            await message.answer_document(file, caption="ScreenAI Installer")
        else:
            await message.answer("❌ Установщик еще не загружен админом.", reply_markup=get_main_keyboard(user_id))
        return

    price_stars = current_config.get("price_stars", 50)
    price_crypto = current_config.get("price_crypto_usd", 5)
    
    await message.answer(
        f"💳 Для доступа к ScreenAI необходимо оплатить подписку:\n\n"
        f"⭐ **{price_stars} Stars**\n"
        f"₿ **${price_crypto} Crypto**\n\n"
        "Выберите удобный способ оплаты:",
        reply_markup=get_payment_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_payment)

@dp.message(UserStates.waiting_for_payment, F.text == "🔑 Ввести пароль")
async def ask_password(message: types.Message, state: FSMContext):
    await message.answer("🔒 Введите пароль для доступа:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserStates.waiting_for_password)

@dp.message(UserStates.waiting_for_payment, F.text == "🎁 Попробовать (20 запросов)")
async def send_trial_installer(message: types.Message, state: FSMContext):
    current_config = load_config()
    trial_path = current_config.get("trial_installer_path")
    
    if trial_path and os.path.exists(trial_path):
        await message.answer("🚀 Держи пробную версию! У тебя есть 20 запросов к ИИ.", reply_markup=get_main_keyboard(message.from_user.id))
        file = FSInputFile(trial_path)
        await message.answer_document(file, caption="ScreenAI Trial")
        await state.clear()
    else:
        await message.answer("❌ Пробная версия временно недоступна (не загружена админом).")

@dp.message(UserStates.waiting_for_password)
async def check_password(message: types.Message, state: FSMContext):
    current_config = load_config()
    if message.text == current_config["password"]:
        if current_config["installer_path"] and os.path.exists(current_config["installer_path"]):
            await message.answer("✅ Пароль верный! Начинаю отправку...", reply_markup=get_main_keyboard(message.from_user.id))
            file = FSInputFile(current_config["installer_path"])
            await message.answer_document(file, caption="ScreenAI Installer")
            await state.clear()
        else:
            await message.answer("❌ Установщик еще не загружен админом.", reply_markup=get_main_keyboard(message.from_user.id))
            await state.clear()
    else:
        await message.answer("⚠️ Неверный пароль. Попробуйте еще раз.")

# --- Payment Flow Handlers ---

@dp.message(UserStates.waiting_for_payment, F.text == "⭐ Оплатить Stars")
async def pay_with_stars(message: types.Message, state: FSMContext):
    current_config = load_config()
    price = current_config.get("price_stars", 50)
    
    await message.answer_invoice(
        title="ScreenAI Subscription",
        description="Доступ к программе ScreenAI",
        prices=[LabeledPrice(label="XTR", amount=price)],
        provider_token="", # Empty for Stars
        currency="XTR",
        payload=f"stars_payment_{message.from_user.id}"
    )

@dp.pre_checkout_query()
async def on_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_config = load_config()
    
    if "paid_users" not in current_config:
        current_config["paid_users"] = []
    
    if user_id not in current_config["paid_users"]:
        current_config["paid_users"].append(user_id)
        save_config(current_config)
    
    await message.answer("✅ Оплата прошла успешно! Спасибо за покупку.", reply_markup=get_main_keyboard(user_id))
    
    if current_config["installer_path"] and os.path.exists(current_config["installer_path"]):
        file = FSInputFile(current_config["installer_path"])
        await message.answer_document(file, caption="ScreenAI Installer")
    else:
        await message.answer("⚠️ Установщик еще не загружен админом. Обратитесь к поддержке.")
    
    await state.clear()

@dp.message(UserStates.waiting_for_payment, F.text == "₿ Оплатить Crypto")
async def pay_with_crypto(message: types.Message, state: FSMContext):
    token = os.getenv("CRYPTOPAY_TOKEN")
    if not token:
        await message.answer("❌ Оплата через Crypto временно недоступна (не настроен токен).")
        return
    
    current_config = load_config()
    amount = current_config.get("price_crypto_usd", 5)
    
    async with aiohttp.ClientSession() as session:
        url = "https://pay.crypt.bot/api/createInvoice"
        headers = {"Crypto-Pay-API-Token": token}
        data = {
            "asset": "USDT",
            "amount": str(amount),
            "description": "ScreenAI Subscription",
            "payload": str(message.from_user.id)
        }
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    invoice_url = result["result"]["pay_url"]
                    invoice_id = result["result"]["invoice_id"]
                    
                    kb = ReplyKeyboardMarkup(
                        keyboard=[
                            [KeyboardButton(text=f"✅ Проверить оплату:{invoice_id}")],
                            [KeyboardButton(text="🔙 Назад")]
                        ],
                        resize_keyboard=True
                    )
                    
                    await message.answer(
                        f"🚀 Ссылка на оплату в CryptoBot:\n{invoice_url}\n\n"
                        "После оплаты нажмите кнопку ниже для проверки:",
                        reply_markup=kb
                    )
                else:
                    await message.answer(f"❌ Ошибка создания счета: {result.get('error')}")
            else:
                await message.answer("❌ Ошибка соединения с CryptoBot API.")

@dp.message(F.text.startswith("✅ Проверить оплату:"))
async def check_crypto_payment(message: types.Message, state: FSMContext):
    invoice_id = message.text.split(":")[1]
    token = os.getenv("CRYPTOPAY_TOKEN")
    current_config = load_config()
    
    async with aiohttp.ClientSession() as session:
        url = "https://pay.crypt.bot/api/getInvoices"
        headers = {"Crypto-Pay-API-Token": token}
        params = {"invoice_ids": invoice_id}
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok") and result["result"]["items"]:
                    invoice = result["result"]["items"][0]
                    if invoice["status"] == "paid":
                        user_id = message.from_user.id
                        if "paid_users" not in current_config:
                            current_config["paid_users"] = []
                        
                        if user_id not in current_config["paid_users"]:
                            current_config["paid_users"].append(user_id)
                            save_config(current_config)
                        
                        await message.answer("✅ Оплата подтверждена!", reply_markup=get_main_keyboard(user_id))
                        
                        if current_config["installer_path"] and os.path.exists(current_config["installer_path"]):
                            file = FSInputFile(current_config["installer_path"])
                            await message.answer_document(file, caption="ScreenAI Installer")
                        else:
                            await message.answer("⚠️ Установщик еще не загружен админом.")
                        await state.clear()
                    else:
                        await message.answer(f"⚠️ Статус оплаты: {invoice['status']}. Попробуйте позже.")
                else:
                    await message.answer("❌ Счёт не найден или произошла ошибка.")
            else:
                await message.answer("❌ Ошибка соединения с CryptoBot API.")

# --- Admin Handlers ---

@dp.message(F.text == "⚙️ Админ-панель", F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    await message.answer("🛠 Добро пожаловать в Админ-панель:", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text == "🔑 Сменить пароль", F.from_user.id == ADMIN_ID)
async def change_password_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новый пароль:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_for_new_password)

@dp.message(AdminStates.waiting_for_new_password, F.from_user.id == ADMIN_ID)
async def change_password_finish(message: types.Message, state: FSMContext):
    new_password = message.text
    current_config = load_config()
    current_config["password"] = new_password
    save_config(current_config)
    await message.answer(f"✅ Пароль успешно изменен на: `{new_password}`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "📤 Загрузить установщик", F.from_user.id == ADMIN_ID)
async def upload_installer_start(message: types.Message, state: FSMContext):
    await message.answer("Пришлите файл установщика (.exe):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_for_installer)

@dp.message(AdminStates.waiting_for_installer, F.document, F.from_user.id == ADMIN_ID)
async def upload_installer_finish(message: types.Message, state: FSMContext):
    file_id = message.document.file_id
    file_name = message.document.file_name
    file_path = os.path.join(INSTALLER_DIR, file_name)
    
    await message.answer("⏳ Загружаю файл...")
    bot_file = await bot.get_file(file_id)
    await bot.download_file(bot_file.file_path, file_path)
    
    current_config = load_config()
    current_config["installer_path"] = file_path
    save_config(current_config)
    
    await message.answer(f"✅ Установщик `{file_name}` успешно загружен и готов к раздаче!", reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "📥 Загрузить TRIAL", F.from_user.id == ADMIN_ID)
async def upload_trial_start(message: types.Message, state: FSMContext):
    await message.answer("Пришлите файл TRIAL версии (.exe):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_for_trial_installer)

@dp.message(AdminStates.waiting_for_trial_installer, F.document, F.from_user.id == ADMIN_ID)
async def upload_trial_finish(message: types.Message, state: FSMContext):
    file_id = message.document.file_id
    file_name = message.document.file_name
    file_path = os.path.join(INSTALLER_DIR, "trial_" + file_name)
    
    await message.answer("⏳ Загружаю TRIAL файл...")
    bot_file = await bot.get_file(file_id)
    await bot.download_file(bot_file.file_path, file_path)
    
    current_config = load_config()
    current_config["trial_installer_path"] = file_path
    save_config(current_config)
    
    await message.answer(f"✅ TRIAL версия `{file_name}` успешно загружена!", reply_markup=get_admin_keyboard())
    await state.clear()

# --- Price Management Handlers ---

@dp.message(F.text == "⭐ Цена Stars", F.from_user.id == ADMIN_ID)
async def set_stars_price_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новую стоимость в Stars (число):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_for_stars_price)

@dp.message(AdminStates.waiting_for_stars_price, F.from_user.id == ADMIN_ID)
async def set_stars_price_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите целое число.")
        return
    
    new_price = int(message.text)
    current_config = load_config()
    current_config["price_stars"] = new_price
    save_config(current_config)
    await message.answer(f"✅ Цена в Stars изменена на: `{new_price}`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "₿ Цена Crypto (USD)", F.from_user.id == ADMIN_ID)
async def set_crypto_price_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новую стоимость в USD (число):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_for_crypto_price)

@dp.message(AdminStates.waiting_for_crypto_price, F.from_user.id == ADMIN_ID)
async def set_crypto_price_finish(message: types.Message, state: FSMContext):
    try:
        new_price = float(message.text.replace(",", "."))
        current_config = load_config()
        current_config["price_crypto_usd"] = new_price
        save_config(current_config)
        await message.answer(f"✅ Цена в Crypto изменена на: `${new_price}`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите число.")

async def web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="Bot is running!")

    async def verify_hwid(request):
        hwid = request.query.get("hwid")
        
        if not hwid:
            return web.json_response({"allowed": False, "reason": "No HWID provided"})
            
        current_config = load_config()
        
        # HWID can be linked to a paid user, but for now we just track by HWID globally
        trial_usage = current_config.get("trial_usage", {})
        
        # Ensure trial_usage is a dict
        if not isinstance(trial_usage, dict):
            trial_usage = {}
            
        count = trial_usage.get(hwid, 0)
        
        if count < 20:
            trial_usage[hwid] = count + 1
            current_config["trial_usage"] = trial_usage
            save_config(current_config)
            return web.json_response({"allowed": True, "remaining": 20 - (count + 1)})
        else:
            return web.json_response({"allowed": False, "reason": "Limit reached"})
    
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/verify", verify_hwid)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    logger.info(f"Starting health check server on port {port}")
    await site.start()

async def main():
    logger.info("Starting bot...")
    # Run bot and web server concurrently
    await asyncio.gather(
        dp.start_polling(bot),
        web_server()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
