import asyncio
import os
bot_token = os.getenv("BOT_TOKEN")
yadisk_token = os.getenv("YADISK_TOKEN")

from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter

import yadisk


class Form(StatesGroup):
    city = State()
    point = State()
    date = State()
    upload = State()
    supplier = State()
    invoice = State()

cities = ["Апатиты", "Вологда", "Тагил", "Кировск", "Мурманск", "Санкт-Петербург"]
spb_points = ["Гороховая", "Ветеранов", "Восстания", "Комендантский", "Лето", "Невский"]


bot = Bot(token=bot_token)
dp = Dispatcher(storage=MemoryStorage())
y = yadisk.YaDisk(token=yadisk_token)


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
    else:
        await state.update_data(point=city)
        await select_date(callback.message, state)

@dp.callback_query(F.data.startswith("point_"))
async def point_selected(callback: types.CallbackQuery, state: FSMContext):
    point = callback.data.split("_", 1)[1]
    await state.update_data(point=point)
    await select_date(callback.message, state)

async def select_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city = data.get("city")
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(-2, 3)]
    options = dates + ["вне диапазона дат"]
    back_callback = "back_point" if city == "Санкт-Петербург" else "back_city"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=option, callback_data=f"date_{option}")] for option in options
    ] + [[types.InlineKeyboardButton(text="Назад", callback_data=back_callback)]])
    await message.edit_text("Выберите дату:", reply_markup=keyboard)
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

def ensure_folder(path: str):
    full = f"disk:{path}"
    if not y.exists(full):
        y.mkdir(full)


@dp.message(StateFilter(Form.invoice))
async def invoice_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    supplier = data["supplier"]
    invoice = message.text
    city = data["city"]
    point = data["point"]
    date = data["date"]

    ensure_folder(f"/{city}")
    ensure_folder(f"/{city}/{point}")
    ensure_folder(f"/{city}/{point}/{date}")

    target_dir = f"disk:/{city}/{point}/{date}"

    for i, file_id in enumerate(data["photos"], 1):
        file = await bot.get_file(file_id)
        file_path = file.file_path
        filename = f"{supplier}_{invoice}_{i}.jpg"

        with open(filename, "wb") as f:
            await bot.download_file(file_path, f)

        y.upload(filename, f"{target_dir}/{filename}")
        os.remove(filename)

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
    if city == "Санкт-Петербург":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=point, callback_data=f"point_{point}")] for point in spb_points
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