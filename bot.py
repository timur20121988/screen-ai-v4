import logging
import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = "8603673892:AAEA5WVXfCu29aO09zkMVKfCDWCBQ4ph4i8"
ADMIN_ID = 8414510938
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

class UserStates(StatesGroup):
    waiting_for_password = State()

# Config Management
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"password": DEFAULT_PASSWORD, "installer_path": None}

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
            [KeyboardButton(text="🔑 Сменить пароль")],
            [KeyboardButton(text="📤 Загрузить установщик")],
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
async def ask_password(message: types.Message, state: FSMContext):
    await message.answer("🔒 Введите пароль для доступа:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserStates.waiting_for_password)

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
    await state.set_state(AdminStates.waiting_for_password)

@dp.message(AdminStates.waiting_for_password, F.from_user.id == ADMIN_ID)
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

async def main():
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
