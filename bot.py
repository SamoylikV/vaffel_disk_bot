import asyncio
import os
import requests
import logging

bot_token = os.getenv("BOT_TOKEN")
BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter


class Form(StatesGroup):
    city = State()
    point = State()
    date = State()
    upload = State()
    supplier = State()
    invoice = State()

cities = ["Апатиты", "Вологда", "Тагил", "Кировск", "Мурманск", "Санкт-Петербург", "Краснодар"]
spb_points = ["Гороховая", "Ветеранов", "Восстания", "Комендантский", "Лето", "Невский"]
krasnodar_points = ["Дзержинского, 95", "Гондаря, 99", "Колхозная 5/2"]


BASE_FOLDER_ID = 242069


def get_children(folder_id):
    r = requests.get(
        f"{BITRIX_WEBHOOK}disk.folder.getchildren",
        params={"id": str(folder_id)},
    )
    r.raise_for_status()
    return r.json().get("result", [])


def find_folder(parent_id, name):
    for item in get_children(parent_id):
        if item["TYPE"] == "folder" and item["NAME"] == name:
            return item["ID"]
    return None


def create_folder(parent_id, name):
    r = requests.post(
        f"{BITRIX_WEBHOOK}disk.folder.addsubfolder",
        data={"id": str(parent_id), "data[NAME]": name},
    )
    r.raise_for_status()
    return r.json()["result"]["ID"]


def ensure_folder_path(base_id, *names):
    current_id = base_id
    for name in names:
        folder_id = find_folder(current_id, name)
        if folder_id is None:
            folder_id = create_folder(current_id, name)
        current_id = folder_id
    return current_id


def upload_file(folder_id, filepath):
    filename = os.path.basename(filepath)
    r = requests.post(
        f"{BITRIX_WEBHOOK}disk.folder.uploadfile",
        data={"id": str(folder_id), "fileName": filename},
    )
    r.raise_for_status()
    upload_url = r.json()["result"]["uploadUrl"]
    with open(filepath, "rb") as f:
        requests.post(upload_url, files={"file": f}).raise_for_status()


bot = Bot(token=bot_token)
dp = Dispatcher(storage=MemoryStorage())


@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=city, callback_data=f"city_{city}")] for city in cities
    ])
    await message.answer("Выберите город:", reply_markup=keyboard)
    await state.set_state(Form.city)

@dp.callback_query(F.data.startswith("city_"))
async def city_selected(callback: types.CallbackQuery, state: FSMContext):
    city = callback.data.split("_", 1)[1]
    await state.update_data(city=city)
    if city == "Санкт-Петербург":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=point, callback_data=f"point_{point}")] for point in spb_points
        ] + [[types.InlineKeyboardButton(text="Назад", callback_data="back_city")]])
        await callback.message.edit_text("Выберите точку:", reply_markup=keyboard)
        await state.set_state(Form.point)
    elif city == "Краснодар":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=point, callback_data=f"point_{point}")] for point in krasnodar_points
        ] + [[types.InlineKeyboardButton(text="Назад", callback_data="back_city")]])
        await callback.message.edit_text("Выберите точку:", reply_markup=keyboard)
        await state.set_state(Form.point)
    else:
        await state.update_data(point=city)
        await select_date(callback.message, state)

@dp.callback_query(F.data.startswith("point_"))
async def point_selected(callback: types.CallbackQuery, state: FSMContext):
    point = callback.data.split("_", 1)[1]
    logging.info(f"Point selected: {point}")
    await state.update_data(point=point)
    await select_date(callback.message, state)

async def select_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city = data.get("city")
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%Y_%m_%d") for i in range(-2, 3)]
    options = dates + ["вне диапазона дат"]
    back_callback = "back_point" if city in ["Санкт-Петербург", "Краснодар"] else "back_city"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=option, callback_data=f"date_{option}")] for option in options
    ] + [[types.InlineKeyboardButton(text="Назад", callback_data=back_callback)]])
    new_text = "Выберите дату:"
    if message.text != new_text or message.reply_markup != keyboard:
        await message.edit_text(new_text, reply_markup=keyboard)
    await state.set_state(Form.date)

@dp.callback_query(F.data.startswith("date_"))
async def date_selected(callback: types.CallbackQuery, state: FSMContext):
    date = callback.data.split("_", 1)[1]
    await state.update_data(date=date)
    await callback.message.edit_text("Загрузите фотографии накладных. Отправьте /done когда закончите.")
    await state.set_state(Form.upload)

@dp.message(F.photo, Form.upload)
async def handle_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer("Фото принято. Отправьте еще или /done")

@dp.message(Command("done"), Form.upload)
async def done_uploading(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("photos"):
        await message.answer("Нет загруженных фото.")
        return
    await message.answer("Введите название поставщика:")
    await state.set_state(Form.supplier)

@dp.message(StateFilter(Form.supplier))
async def supplier_entered(message: types.Message, state: FSMContext):
    await state.update_data(supplier=message.text)
    await message.answer("Введите номер накладной:")
    await state.set_state(Form.invoice)

@dp.message(StateFilter(Form.invoice))
async def invoice_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    supplier = data["supplier"]
    invoice = message.text
    city = data["city"]
    point = data["point"]
    date = data["date"]

    target_folder_id = ensure_folder_path(BASE_FOLDER_ID, city, point, date)
    if target_folder_id is None:
        await message.answer("Ошибка при создании папки.")
        await state.clear()
        return

    for i, file_id in enumerate(data["photos"], 1):
        file = await bot.get_file(file_id)
        file_path = file.file_path
        filename = f"{supplier}_{invoice}_{i}.jpg"

        with open(filename, "wb") as f:
            await bot.download_file(file_path, f)

        try:
            upload_file(target_folder_id, filename)
        except Exception as e:
            logging.error(f"Ошибка загрузки {filename}: {e}")
        finally:
            os.remove(filename)

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Начать заново", callback_data="restart")]
    ])
    await message.answer("Все фото загружены.", reply_markup=keyboard)
    await state.clear()
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Начать заново", callback_data="restart")]
    ])
    await message.answer("Все фото загружены.", reply_markup=keyboard)
    await state.clear()

@dp.callback_query(F.data == "back_city")
async def back_to_city(callback: types.CallbackQuery, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=city, callback_data=f"city_{city}")] for city in cities
    ])
    await callback.message.edit_text("Выберите город:", reply_markup=keyboard)
    await state.set_state(Form.city)

@dp.callback_query(F.data == "back_point")
async def back_to_point(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    city = data.get("city")
    if city in ["Санкт-Петербург", "Краснодар"]:
        points = spb_points if city == "Санкт-Петербург" else krasnodar_points
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=point, callback_data=f"point_{point}")] for point in points
        ] + [[types.InlineKeyboardButton(text="Назад", callback_data="back_city")]])
        await callback.message.edit_text("Выберите точку:", reply_markup=keyboard)
        await state.set_state(Form.point)
    else:
        await back_to_city(callback, state)

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=city, callback_data=f"city_{city}")] for city in cities
    ])
    await callback.message.edit_text("Выберите город:", reply_markup=keyboard)
    await state.set_state(Form.city)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())