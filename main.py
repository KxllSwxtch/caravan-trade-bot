import json
import telebot
import os
import re
import requests
import locale
import logging
import urllib.parse
import random

from concurrent.futures import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from database import (
    create_tables,
    get_orders,
    get_all_orders,
    add_order,
    update_user_phone,
    update_order_status_in_db,
    delete_order_from_db,
    update_user_name,
    update_user_name,
    update_user_subscription,
    delete_favorite_car,
    get_all_users,
    add_user,
    get_hp_from_specs,
    save_hp_to_specs,
)
from bs4 import BeautifulSoup
from io import BytesIO
from telebot import types
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs
from utils import (
    generate_encar_photo_url,
    clean_number,
    get_customs_fees,
    calculate_age,
    format_number,
    get_customs_fees_manual,
    get_pan_auto_data,
)

CALCULATE_CAR_TEXT = "Рассчитать Автомобиль (Encar.com, KBChaChaCha.com, KCar.com)"
CHANNEL_USERNAME = "crvntrade"
BOT_TOKEN = os.getenv("BOT_TOKEN")

load_dotenv()
bot_token = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(bot_token)

# Set locale for number formatting
locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

# Storage for the last error message ID
last_error_message_id = {}

# global variables
car_data = {}
car_id_external = ""
total_car_price = 0
krw_rub_rate = 0
rub_to_krw_rate = 0
usd_rate = 0
users = set()
user_data = {}

car_month = None
car_year = None

vehicle_id = None
vehicle_no = None

usd_to_krw_rate = 0
usd_to_rub_rate = 0

usdt_to_krw_rate = 0

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/113.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.128 Safari/537.36",
]


################## КОД ДЛЯ СТАТУСОВ
# Храним заказы пользователей
pending_orders = {}
user_contacts = {}
user_names = {}

# Храним данные о машинах, ожидающих ввода HP от пользователя
pending_hp_calculations = {}

MANAGERS = [
    728438182,  # Дима (Я)
    973407169,  # Сергей
    519638945,  # Rlnjl
    5159872963,  # Олег
]

ORDER_STATUSES = {
    "1": "🚗 Авто выкуплен (на базе)",
    "2": "🚢 Отправлен в порт г. Пусан на погрузку",
    "3": "🌊 В пути во Владивосток",
    "4": "🛃 Таможенная очистка",
    "5": "📦 Погрузка до МСК",
    "6": "🚛 Доставляется клиенту",
}

faq_data = {
    "Депозит": [
        {
            "question": "100.000₽ — за услуги или в счёт авто?",
            "answer": "💬 100.000 рублей — это *не* стоимость услуги. Эта сумма будет вычтена на Российской стороне при окончательном расчёте.",
        },
    ],
}


@bot.callback_query_handler(func=lambda call: call.data.startswith("add_favorite_"))
def add_favorite_car(call):
    global car_data
    user_id = call.message.chat.id

    if not car_data or "name" not in car_data:
        bot.answer_callback_query(
            call.id, "🚫 Ошибка: Данные о машине отсутствуют.", show_alert=True
        )
        return

    # Проверяем, есть ли авто уже в избранном
    existing_orders = get_orders(user_id)
    if any(order["id"] == car_data.get("car_id") for order in existing_orders):
        bot.answer_callback_query(call.id, "✅ Этот автомобиль уже в избранном.")
        return

    # Получаем данные пользователя
    user = bot.get_chat(user_id)
    user_name = user.username if user.username else "Неизвестно"

    # Проверяем, есть ли сохранённый номер телефона пользователя
    phone_number = user_contacts.get(user_id, "Неизвестно")

    # Формируем объект заказа
    order_data = {
        "user_id": user_id,
        "car_id": car_data.get("car_id", "Нет ID"),
        "title": car_data.get("name", "Неизвестно"),
        "price": f"₩{format_number(car_data.get('car_price', 0))}",
        "link": car_data.get("link", "Нет ссылки"),
        "year": car_data.get("year", "Неизвестно"),
        "month": car_data.get("month", "Неизвестно"),
        "mileage": car_data.get("mileage", "Неизвестно"),
        "fuel": car_data.get("fuel", "Неизвестно"),
        "engine_volume": car_data.get("engine_volume", "Неизвестно"),
        "transmission": car_data.get("transmission", "Неизвестно"),
        "images": car_data.get("images", []),
        "status": "🔄 Не заказано",
        "total_cost_usd": car_data.get("total_cost_usd", 0),
        "total_cost_krw": car_data.get("total_cost_krw", 0),
        "total_cost_rub": car_data.get("total_cost_rub", 0),
        "user_name": user_name,  # ✅ Добавляем user_name
        "phone_number": phone_number,  # ✅ Добавляем phone_number (если нет, "Неизвестно")
    }

    # Логируем, чтобы проверить, какие данные отправляем в БД
    print(f"✅ Добавляем заказ: {order_data}")

    # Сохраняем в базу
    add_order(order_data)

    # Подтверждаем пользователю
    bot.answer_callback_query(
        call.id, "⭐ Автомобиль добавлен в избранное!", show_alert=True
    )


@bot.message_handler(commands=["my_cars"])
def show_favorite_cars(message):
    user_id = message.chat.id
    orders = get_orders(user_id)  # Берём заказы из БД

    if not orders:
        bot.send_message(user_id, "❌ У вас нет сохранённых автомобилей.")
        return

    for car in orders:
        car_id = car["car_id"]  # Используем car_id вместо id
        car_title = car["title"]
        car_status = car["status"]
        car_link = car["link"]
        car_year = car["year"]
        car_month = car["month"]
        car_mileage = car["mileage"]
        car_engine_volume = car["engine_volume"]
        car_transmission = car["transmission"]
        total_cost_usd = car["total_cost_usd"]
        total_cost_krw = car["total_cost_krw"]
        total_cost_rub = car["total_cost_rub"]

        # Формируем текст сообщения
        # ${format_number(total_cost_usd)} |
        response_text = (
            f"🚗 *{car_title} ({car_id})*\n\n"
            f"📅 {car_month}/{car_year} | ⚙️ {car_transmission}\n"
            f"🔢 Пробег: {car_mileage} | 🏎 Объём: {format_number(car_engine_volume)} cc\n\n"
            f"Стоимость авто под ключ:\n"
            f"₩{format_number(total_cost_krw)} | {format_number(total_cost_rub)} ₽\n\n"
            f"📌 *Статус:* {car_status}\n\n"
            f"[🔗 Ссылка на автомобиль]({car_link})\n\n"
            f"Консультация с менеджерами:\n\n"
            f"▪️ +82-10-2889-2307 (Олег)\n"
            f"▪️ +82-10-5812-2515 (Дмитрий)\n"
        )

        # Создаём клавиатуру
        keyboard = types.InlineKeyboardMarkup()
        if car_status == "🔄 Не заказано":
            keyboard.add(
                types.InlineKeyboardButton(
                    f"📦 Заказать {car_title}",
                    callback_data=f"order_car_{car_id}",
                )
            )
        keyboard.add(
            types.InlineKeyboardButton(
                "❌ Удалить авто из списка", callback_data=f"delete_car_{car_id}"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Вернуться в главное меню", callback_data="main_menu"
            )
        )

        bot.send_message(
            user_id, response_text, parse_mode="Markdown", reply_markup=keyboard
        )


@bot.callback_query_handler(func=lambda call: call.data == "show_orders")
def callback_show_orders(call):
    """Обработчик кнопки 'Посмотреть список заказов'"""
    manager_id = call.message.chat.id
    print(f"📋 Менеджер {manager_id} нажал 'Посмотреть список заказов'")

    # ✅ Вызываем show_orders() с переданным сообщением из callback-запроса
    show_orders(call.message)


def notify_managers(order):
    """Отправляем информацию о заказе всем менеджерам"""
    print(f"📦 Отправляем заказ менеджерам: {order}")

    # Создаём клавиатуру с кнопкой "Посмотреть список заказов"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "📋 Посмотреть список заказов", callback_data="show_orders"
        )
    )

    order_title = order.get("title", "Без названия")
    order_link = order.get("link", "#")
    user_name = order.get("user_name", "Неизвестный")
    user_id = order.get("user_id", None)
    phone_number = order.get("phone_number", "Не указан")

    user_mention = f"[{user_name}](tg://user?id={user_id})" if user_id else user_name

    message_text = (
        f"🚨 *Новый заказ!*\n\n"
        f"🚗 [{order_title}]({order_link})\n"
        f"👤 Заказчик: {user_mention}\n"
        f"📞 Контакт: {phone_number}\n"
        f"📌 *Статус:* 🕒 Ожидает подтверждения\n"
    )

    for manager_id in MANAGERS:
        bot.send_message(
            manager_id,
            message_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("order_car_"))
def order_car(call):
    user_id = call.message.chat.id
    car_id = call.data.split("_")[-1]

    # Получаем авто из базы
    user_orders = get_orders(user_id)
    order_found = None

    for order in user_orders:
        if str(order["car_id"]) == str(car_id):
            order_found = order
            break
        else:
            print(f"❌ Автомобиль {car_id} не совпадает с {order['car_id']}")

    if not order_found:
        print(f"❌ Ошибка: авто {car_id} не найдено в базе!")
        bot.send_message(user_id, "❌ Ошибка: автомобиль не найден.")
        return

    # ✅ Проверяем, есть ли ФИО у пользователя
    if user_id not in user_names:
        print(f"📝 Запрашиваем ФИО у {user_id}")
        bot.send_message(
            user_id,
            "📝 Введите ваше *ФИО* для оформления заказа:",
            parse_mode="Markdown",
        )

        # Сохраняем ID заказа в `pending_orders`
        pending_orders[user_id] = car_id
        return

    # ✅ Если ФИО уже есть, проверяем телефон
    if user_id not in user_contacts:
        print(f"📞 Запрашиваем телефон у {user_id}")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = types.KeyboardButton("📞 Отправить номер", request_contact=True)
        markup.add(button)

        bot.send_message(
            user_id,
            "📲 Для оформления заказа, пожалуйста, отправьте номер телефона, "
            "на который зарегистрирован WhatsApp или Telegram.",
            reply_markup=markup,
        )

        # Сохраняем ID заказа в `pending_orders`
        pending_orders[user_id] = car_id
        return

    # ✅ Если ФИО и телефон уже есть → обновляем заказ
    phone_number = user_contacts[user_id]
    full_name = user_names[user_id]

    update_order_status(car_id, "🕒 Ожидает подтверждения")
    update_order_status_in_db(order_found["id"], "🕒 Ожидает подтверждения")

    bot.send_message(
        user_id,
        f"✅ Ваш заказ на {order_found['title']} оформлен!\n"
        f"📌 Статус: 🕒 Ожидает подтверждения\n"
        f"📞 Контакт для связи: {phone_number}\n"
        f"👤 ФИО: {full_name}",
        callback_data="show_orders",
    )

    # ✅ Добавляем ФИО в заказ перед отправкой менеджерам
    order_found["user_name"] = full_name
    notify_managers(order_found)


# Обработчик получения номера телефона
@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    if not message.contact or not message.contact.phone_number:
        bot.send_message(user_id, "❌ Ошибка: номер телефона не передан.")
        return

    user_id = message.chat.id
    phone_number = message.contact.phone_number

    # Сохраняем номер телефона
    user_contacts[user_id] = phone_number
    bot.send_message(user_id, f"✅ Ваш номер {phone_number} сохранён!")

    # Проверяем, есть ли ожидаемый заказ
    if user_id not in pending_orders:
        bot.send_message(user_id, "✅ Ваш номер сохранён, но активного заказа нет.")
        return

    if user_id in pending_orders:
        car_id = pending_orders[user_id]  # Берём car_id из `pending_orders`
        print(f"📦 Пользователь {user_id} подтвердил заказ автомобиля {car_id}")

        # Получаем заказанное авто из базы
        user_orders = get_orders(user_id)
        order_found = None

        for order in user_orders:
            if str(order["car_id"]).strip() == str(car_id).strip():
                order_found = order
                break

        if not order_found:
            bot.send_message(user_id, "❌ Ошибка: автомобиль не найден в базе данных.")
            return

        # Добавляем `user_id` в order_found, если его нет
        order_found["user_id"] = user_id
        order_found["phone_number"] = (
            phone_number  # ✅ Сохраняем номер телефона в заказе
        )

        print(
            f"🛠 Обновляем телефон {phone_number} для user_id={user_id}, order_id={order_found['id']}"
        )
        update_user_phone(user_id, phone_number, order_found["id"])
        update_order_status_in_db(order_found["id"], "🕒 Ожидает подтверждения")

        bot.send_message(
            user_id,
            f"✅ Ваш заказ на {order_found['title']} оформлен!\n"
            f"📌 Статус: 🕒 Ожидает подтверждения\n"
            f"📞 Контакт: {phone_number}",
        )

        notify_managers(order_found)


@bot.message_handler(
    func=lambda message: not message.text.startswith("/")
    and message.chat.id in pending_orders
)
def handle_full_name(message):
    user_id = message.chat.id
    full_name = message.text.strip()

    # ❌ Если ФИО пустое, просим ввести заново
    if not full_name:
        bot.send_message(
            user_id, "❌ ФИО не может быть пустым. Введите ваше ФИО ещё раз:"
        )
        return

    # ✅ Сохраняем ФИО
    user_names[user_id] = full_name
    bot.send_message(user_id, f"✅ Ваше ФИО '{full_name}' сохранено!")

    # Проверяем, есть ли ожидаемый заказ
    car_id = pending_orders[user_id]  # Берём car_id из `pending_orders`
    print(
        f"📦 Пользователь {user_id} подтвердил заказ автомобиля {car_id} с ФИО {full_name}"
    )

    # Получаем заказанное авто из базы
    user_orders = get_orders(user_id)
    order_found = next(
        (
            order
            for order in user_orders
            if str(order["car_id"]).strip() == str(car_id).strip()
        ),
        None,
    )

    if not order_found:
        bot.send_message(user_id, "❌ Ошибка: автомобиль не найден в базе данных.")
        return

    # ✅ Обновляем статус заказа и добавляем ФИО в БД
    import hashlib

    def convert_car_id(car_id):
        if car_id.isdigit():
            return int(car_id)  # Если уже число, просто вернуть его
        else:
            return int(hashlib.md5(car_id.encode()).hexdigest(), 16) % (
                10**9
            )  # Преобразуем в число

    # Пример использования
    numeric_car_id = convert_car_id(car_id)

    update_order_status_in_db(order_found["id"], "🕒 Ожидает подтверждения")
    update_user_name(user_id, full_name)

    # ✅ Проверяем, есть ли уже телефон пользователя
    if user_id not in user_contacts:
        print(f"📞 Запрашиваем телефон у {user_id}")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = types.KeyboardButton("📞 Отправить номер", request_contact=True)
        markup.add(button)

        bot.send_message(
            user_id,
            "📲 Теперь отправьте ваш *номер телефона*, на который зарегистрирован WhatsApp или Telegram.",
            reply_markup=markup,
            parse_mode="Markdown",
        )
        return  # Ждём телефон, дальше не идём

    # ✅ Если телефон уже есть → завершаем оформление
    phone_number = user_contacts[user_id]

    bot.send_message(
        user_id,
        f"✅ Ваш заказ на {order_found['title']} оформлен!\n"
        f"📌 Статус: 🕒 Ожидает подтверждения\n"
        f"📞 Контакт: {phone_number}\n"
        f"👤 ФИО: {full_name}",
    )

    # ✅ Отправляем информацию менеджерам
    order_found["user_name"] = full_name
    print(f"📦 Перед отправкой менеджерам заказ: {order_found}")  # Отладка
    notify_managers(order_found)

    # ✅ Удаляем `pending_orders`
    del pending_orders[user_id]


# Функция оформления заказа
def process_order(user_id, car_id, username, phone_number):
    # Достаём авто из списка
    car = next(
        (car for car in user_orders.get(user_id, []) if car["id"] == car_id), None
    )

    if not car:
        bot.send_message(user_id, "❌ Ошибка: автомобиль не найден.")
        return

    car_title = car.get("title", "Неизвестно")
    car_link = car.get("link", "Нет ссылки")

    # Менеджер, которому отправлять заявку
    manager_chat_id = MANAGERS[0]  # Здесь нужно указать ID менеджера

    # Сообщение менеджеру
    manager_text = (
        f"📢 *Новый заказ на автомобиль!*\n\n"
        f"🚗 {car_title}\n"
        f"🔗 [Ссылка на автомобиль]({car_link})\n\n"
        f"🔹 Username: @{username if username else 'Не указан'}\n"
        f"📞 Телефон: {phone_number if phone_number else 'Не указан'}\n"
    )

    bot.send_message(manager_chat_id, manager_text, parse_mode="Markdown")

    # Обновляем статус авто
    car["status"] = "🕒 Ожидает подтверждения"
    bot.send_message(
        user_id,
        f"✅ Ваш заказ на {car_title} оформлен! Менеджер скоро свяжется с вами.",
    )


@bot.message_handler(commands=["orders"])
def show_orders(message):
    manager_id = message.chat.id

    # Проверяем, является ли пользователь менеджером
    if manager_id not in MANAGERS:
        bot.send_message(manager_id, "❌ У вас нет доступа к заказам.")
        return

    # Загружаем все заказы из базы данных
    orders = get_all_orders()

    if not orders:
        bot.send_message(manager_id, "📭 Нет активных заказов.")
        return

    for idx, order in enumerate(orders, start=1):
        order_id = order.get("id", "Неизвестно")
        car_title = order.get("title", "Без названия")
        user_id = order.get("user_id")
        user_name = order.get("user_name", "Неизвестный")
        phone_number = order.get("phone_number", "Неизвестно")
        car_status = order.get("status", "🕒 Ожидает подтверждения")
        car_link = order.get("link", "#")
        car_id = order.get("car_id", "Неизвестно")

        if car_status == "🔄 Не заказано":
            car_status = "🕒 Ожидает подтверждения"

        user_mention = (
            f"[{user_name}](tg://user?id={user_id})" if user_id else user_name
        )

        response_text = (
            # f"📦 *Заказ #{idx}*\n"
            f"🚗 *{car_title}* (ID: {car_id})\n\n"
            f"👤 Заказчик: {user_mention}\n"
            f"📞 Телефон: *{phone_number}*\n\n"
            f"📌 *Статус:* {car_status}\n\n"
            f"[🔗 Ссылка на автомобиль]({car_link})"
        )

        # Создаем клавиатуру
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                f"📌 Обновить статус ({car_title})",
                callback_data=f"update_status_{order_id}",
            ),
            types.InlineKeyboardButton(
                f"🗑 Удалить заказ ({car_title})",
                callback_data=f"delete_order_{order_id}",
            ),
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Вернуться в главное меню ", callback_data="main_menu"
            )
        )

        bot.send_message(
            manager_id,
            response_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("update_status_"))
def update_order_status(call):
    manager_id = call.message.chat.id
    order_id = call.data.split("_")[-1]  # ❗ Здесь приходит ID заказа, а не car_id

    print(f"🔍 Менеджер {manager_id} пытается обновить статус заказа {order_id}")

    # Получаем заказы из базы
    orders = get_all_orders()  # ✅ Загружаем все заказы
    # print(f"📦 Все заказы из базы: {orders}")  # Логируем заказы

    # 🛠 Теперь ищем по `id`, а не по `car_id`
    order_found = next(
        (order for order in orders if str(order["id"]) == str(order_id)), None
    )

    if not order_found:
        print(f"❌ Ошибка: заказ {order_id} не найден!")
        bot.answer_callback_query(call.id, "❌ Ошибка: заказ не найден.")
        return

    user_id = order_found["user_id"]
    car_id = order_found["car_id"]  # ✅ Берём car_id

    # 🔥 Генерируем кнопки статусов
    keyboard = types.InlineKeyboardMarkup()
    for status_code, status_text in ORDER_STATUSES.items():
        keyboard.add(
            types.InlineKeyboardButton(
                status_text,
                callback_data=f"set_status_{user_id}_{order_id}_{status_code}",
            )
        )

    bot.send_message(manager_id, "📌 Выберите новый статус:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_car_"))
def delete_favorite_callback(call):
    user_id = call.message.chat.id
    car_id = call.data.split("_")[2]  # Получаем ID авто

    delete_favorite_car(user_id, car_id)  # Удаляем авто из БД

    bot.answer_callback_query(call.id, "✅ Авто удалено из списка!")
    bot.delete_message(
        call.message.chat.id, call.message.message_id
    )  # Удаляем сообщение с авто


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_order_"))
def delete_order(call):
    manager_id = call.message.chat.id
    order_id = call.data.split("_")[-1]

    print(f"🗑 Менеджер {manager_id} хочет удалить заказ {order_id}")

    # Удаляем заказ из базы
    delete_order_from_db(order_id)

    bot.answer_callback_query(call.id, "✅ Заказ удалён!")
    bot.send_message(manager_id, f"🗑 Заказ {order_id} успешно удалён.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_status_"))
def set_new_status(call):
    manager_id = call.message.chat.id

    print(f"🔄 Получен `callback_data`: {call.data}")  # Логирование данных

    # Разбиваем callback_data
    _, _, user_id, order_id, status_code = call.data.split("_", 4)

    if not user_id.isdigit():
        print(f"❌ Ошибка: user_id некорректный: {user_id}")
        bot.answer_callback_query(call.id, "❌ Ошибка: неверный ID пользователя.")
        return

    user_id = int(user_id)

    # Проверяем статус
    if status_code not in ORDER_STATUSES:
        print(f"❌ Ошибка: неверный код статуса: {status_code}")
        bot.answer_callback_query(call.id, "❌ Ошибка: неверный статус.")
        return

    new_status = ORDER_STATUSES[status_code]  # Получаем текст статуса по коду

    print(
        f"🔄 Менеджер {manager_id} меняет статус заказа {order_id} для {user_id} на {new_status}"
    )

    # Получаем все заказы
    orders = get_all_orders()
    # print(f"📦 Все заказы пользователя {user_id}: {orders}")  # Логируем

    # 🛠 Ищем заказ по `id`
    order_found = next(
        (order for order in orders if str(order["id"]) == str(order_id)), None
    )

    if not order_found:
        print(f"❌ Ошибка: заказ {order_id} не найден!")
        bot.answer_callback_query(call.id, "❌ Ошибка: заказ не найден.")
        return

    # Обновляем статус заказа в БД
    update_order_status_in_db(order_id, new_status)

    # Уведомляем клиента
    bot.send_message(
        user_id,
        f"📢 *Обновление статуса заказа!*\n\n"
        f"🚗 [{order_found['title']}]({order_found['link']})\n"
        f"📌 Новый статус:\n*{new_status}*",
        parse_mode="Markdown",
    )

    # Подтверждаем менеджеру
    bot.answer_callback_query(call.id, f"✅ Статус обновлён на {new_status}!")

    # Обновляем заказы у менеджеров
    show_orders(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith("place_order_"))
def place_order(call):
    user_id = call.message.chat.id
    order_id = call.data.split("_")[-1]

    # Проверяем, есть ли этот заказ
    if order_id not in user_orders:
        bot.answer_callback_query(call.id, "❌ Ошибка: заказ не найден.")
        return

    order = user_orders[order_id]

    # Создаём кнопку "Обновить статус" (только для менеджеров)
    keyboard = types.InlineKeyboardMarkup()
    if user_id in MANAGERS:
        keyboard.add(
            types.InlineKeyboardButton(
                "📌 Обновить статус", callback_data=f"update_status_{order_id}"
            )
        )

    bot.send_message(
        user_id,
        f"📢 *Заказ оформлен!*\n\n"
        f"🚗 [{order['title']}]({order['link']})\n"
        f"👤 Клиент: [{order['user_name']}](tg://user?id={order['user_id']})\n"
        f"📌 *Текущий статус:* {order['status']}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    bot.answer_callback_query(call.id, "✅ Заказ отправлен менеджерам!")


################## КОД ДЛЯ СТАТУСОВ


@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription(call):
    user_id = call.from_user.id
    chat_member = bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)

    if chat_member.status in ["member", "administrator", "creator"]:
        bot.answer_callback_query(
            call.id, "✅ Подписка оформлена! Вы можете продолжить расчёты."
        )
        # Установить подписку для пользователя в БД
        update_user_subscription(user_id, True)
    else:
        bot.answer_callback_query(
            call.id,
            "🚫 Вы не подписались на канал! Оформите подписку, чтобы продолжить.",
        )


# ==================== HP INPUT HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("hp_input_"))
def handle_hp_input(call):
    """Обработчик выбора HP через кнопки"""
    global car_data, car_id_external, pending_hp_calculations

    user_id = call.from_user.id

    if user_id not in pending_hp_calculations:
        bot.answer_callback_query(call.id, "⚠️ Сессия расчёта истекла. Попробуйте снова.")
        return

    data = pending_hp_calculations[user_id]
    action = call.data.replace("hp_input_", "")

    if action == "cancel":
        del pending_hp_calculations[user_id]
        bot.answer_callback_query(call.id, "❌ Расчёт отменён")
        bot.edit_message_text(
            "❌ Расчёт отменён.",
            call.message.chat.id,
            call.message.message_id
        )
        return

    if action == "manual":
        bot.answer_callback_query(call.id, "✏️ Введите мощность в л.с.")
        bot.edit_message_text(
            f"✏️ Введите мощность двигателя в л.с. (число от 50 до 1000):\n\n"
            f"Автомобиль: <b>{data['car_title']}</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
        # Ставим флаг, что ожидаем ручной ввод
        pending_hp_calculations[user_id]["waiting_manual_input"] = True
        return

    # Получаем HP из callback data (например, "150" из "hp_input_150")
    try:
        hp = int(action)
    except ValueError:
        bot.answer_callback_query(call.id, "⚠️ Ошибка выбора HP")
        return

    bot.answer_callback_query(call.id, f"✅ Выбрано: {hp} л.с.")

    # Продолжаем расчёт с выбранным HP
    complete_calculation_with_hp(user_id, hp, call.message.chat.id)


def complete_calculation_with_hp(user_id, hp, chat_id):
    """Завершает расчёт с указанным HP"""
    global car_data, car_id_external, pending_hp_calculations

    if user_id not in pending_hp_calculations:
        bot.send_message(chat_id, "⚠️ Сессия расчёта истекла. Попробуйте снова.")
        return

    data = pending_hp_calculations[user_id]

    try:
        # Получаем таможенные платежи с реальным HP
        response = get_customs_fees(
            data["car_engine_displacement"],
            data["price_krw"],
            int(data["formatted_car_year"]),
            data["car_month"],
            engine_type=(
                1 if data["fuel_type"] == "가솔린" else 2 if data["fuel_type"] == "디젤" else 3
            ),
            power=hp,
        )

        if response is None:
            bot.send_message(
                chat_id,
                "❌ Временная ошибка при расчете таможенных платежей. Сервис calcus.ru перегружен. Попробуйте через несколько минут.",
            )
            del pending_hp_calculations[user_id]
            return

        # Таможенные платежи
        customs_fee = clean_number(response["sbor"])
        customs_duty = clean_number(response["tax"])
        recycling_fee = clean_number(response["util"])

        rub_to_krw_rate = data["rub_to_krw_rate"]
        price_rub = data["price_rub"]
        price_krw = data["price_krw"]

        # Расчет итоговой стоимости
        total_cost = (
            price_rub
            + (440000 / rub_to_krw_rate)
            + (1300000 / rub_to_krw_rate)
            + customs_fee
            + customs_duty
            + recycling_fee
            + 100000
        )

        total_cost_krw = (
            price_krw
            + 440000
            + 1300000
            + (customs_fee * rub_to_krw_rate)
            + (customs_duty * rub_to_krw_rate)
            + (recycling_fee * rub_to_krw_rate)
            + (100000 * rub_to_krw_rate)
        )

        # Сохраняем данные
        car_data["total_cost_krw"] = total_cost_krw
        car_data["total_cost_rub"] = total_cost
        car_data["car_price_krw"] = price_krw
        car_data["car_price_rub"] = price_rub
        car_data["encar_fee_krw"] = 440000
        car_data["encar_fee_rub"] = 440000 / rub_to_krw_rate
        car_data["delivery_fee_krw"] = 1300000
        car_data["delivery_fee_rub"] = 1300000 / rub_to_krw_rate
        car_data["customs_duty_rub"] = customs_duty
        car_data["customs_duty_krw"] = customs_duty * rub_to_krw_rate
        car_data["customs_fee_rub"] = customs_fee
        car_data["customs_fee_krw"] = customs_fee * rub_to_krw_rate
        car_data["util_fee_rub"] = recycling_fee
        car_data["util_fee_krw"] = recycling_fee * rub_to_krw_rate
        car_data["broker_fee_rub"] = 100000
        car_data["broker_fee_krw"] = 100000 * rub_to_krw_rate
        car_data["hp"] = hp

        car_id_external = data["car_id_external"]

        # Формирование сообщения результата
        result_message = (
            f"❯ <b>{data['car_title']}</b>\n\n"
            f"▪️ Возраст: <b>{data['age_formatted']}</b> <i>(дата регистрации: {data['month']}/{data['year']})</i>\n"
            f"▪️ Пробег: <b>{data['formatted_mileage']}</b>\n"
            f"▪️ Объём двигателя: <b>{data['engine_volume_formatted']}</b>\n"
            f"▪️ Мощность: <b>{hp} л.с.</b>\n"
            f"▪️ КПП: <b>{data['formatted_transmission']}</b>\n\n"
            f"💰 <b>Курс Рубля к Воне: ₩{rub_to_krw_rate:.2f}</b>\n\n"
            f"1️⃣ Стоимость автомобиля:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
            f"2️⃣ Комиссия Encar:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['encar_fee_krw'])}</b> | <b>{format_number(car_data['encar_fee_rub'])} ₽</b>\n\n"
            f"3️⃣ Доставка до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['delivery_fee_krw'])}</b> | <b>{format_number(car_data['delivery_fee_rub'])} ₽</b>\n\n"
            f"4️⃣ Единая таможенная ставка:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
            f"5️⃣ Таможенное оформление:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
            f"6️⃣ Утилизационный сбор:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n"
            f"7️⃣ Услуги брокера:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['broker_fee_krw'])}</b> | <b>{format_number(car_data['broker_fee_rub'])} ₽</b>\n\n"
            f"🟰 Итого под ключ: \n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
            f"🔗 <a href='{data['preview_link']}'>Ссылка на автомобиль</a>\n\n"
            "Если данное авто попадает под санкции, пожалуйста уточните возможность отправки в вашу страну у наших менеджеров:\n\n"
            f"▪️ +82-10-2889-2307 (Олег)\n"
            f"▪️ +82-10-5812-2515 (Дмитрий)\n\n"
            "🔗 <a href='https://t.me/crvntrade'>Официальный телеграм канал</a>\n"
        )

        # Клавиатура
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(
            "⭐ Добавить в избранное",
            callback_data=f"add_favorite_{data['car_id_external']}",
        ))

        # Если пользователь менеджер - добавляем кнопку сохранения HP
        if user_id in MANAGERS:
            keyboard.add(types.InlineKeyboardButton(
                f"💾 Сохранить HP ({hp} л.с.) для этой модели",
                callback_data=f"save_hp_{data['manufacturer']}_{data['model']}_{data['car_engine_displacement']}_{data['fuel_type_ru']}_{hp}",
            ))

        keyboard.add(types.InlineKeyboardButton(
            "Технический Отчёт об Автомобиле",
            callback_data="technical_card",
        ))
        keyboard.add(types.InlineKeyboardButton(
            "Выплаты по ДТП",
            callback_data="technical_report",
        ))
        keyboard.add(types.InlineKeyboardButton(
            "Написать менеджеру (Олег)", url="https://t.me/KaMik_23"
        ))
        keyboard.add(types.InlineKeyboardButton(
            "Написать менеджеру (Дима)", url="https://t.me/Pako_000"
        ))
        keyboard.add(types.InlineKeyboardButton(
            "Расчёт другого автомобиля",
            callback_data="calculate_another",
        ))
        keyboard.add(types.InlineKeyboardButton(
            "Главное меню",
            callback_data="main_menu",
        ))

        # Отправляем фото
        car_photos = data.get("car_photos", [])
        media_group = []
        for photo_url in sorted(car_photos) if car_photos else []:
            try:
                response = requests.get(photo_url)
                if response.status_code == 200:
                    photo = BytesIO(response.content)
                    media_group.append(types.InputMediaPhoto(photo))
                    if len(media_group) == 10:
                        bot.send_media_group(chat_id, media_group)
                        media_group.clear()
            except Exception as e:
                print(f"Ошибка при обработке фото {photo_url}: {e}")

        if media_group:
            bot.send_media_group(chat_id, media_group)

        # Сохраняем данные для избранного
        car_data["car_id"] = data["car_id"]
        car_data["name"] = data["car_title"]
        car_data["images"] = car_photos if isinstance(car_photos, list) else []
        car_data["link"] = data["preview_link"]
        car_data["year"] = data["year"]
        car_data["month"] = data["month"]
        car_data["mileage"] = data["formatted_mileage"]
        car_data["engine_volume"] = data["car_engine_displacement"]
        car_data["transmission"] = data["formatted_transmission"]
        car_data["car_price"] = price_krw
        car_data["user_name"] = data.get("user_name")
        car_data["first_name"] = data.get("first_name")
        car_data["last_name"] = data.get("last_name")

        bot.send_message(
            chat_id,
            result_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        # Удаляем данные о pending расчёте
        del pending_hp_calculations[user_id]

    except Exception as e:
        print(f"Ошибка при завершении расчёта с HP: {e}")
        bot.send_message(chat_id, f"❌ Ошибка при расчёте: {e}")
        if user_id in pending_hp_calculations:
            del pending_hp_calculations[user_id]


@bot.callback_query_handler(func=lambda call: call.data.startswith("save_hp_"))
def handle_save_hp(call):
    """Обработчик сохранения HP в базу данных (только для менеджеров)"""
    user_id = call.from_user.id

    if user_id not in MANAGERS:
        bot.answer_callback_query(call.id, "⚠️ Только менеджеры могут сохранять HP")
        return

    # Парсим callback data: save_hp_Manufacturer_Model_Volume_FuelType_HP
    parts = call.data.replace("save_hp_", "").split("_")
    if len(parts) < 5:
        bot.answer_callback_query(call.id, "⚠️ Ошибка данных")
        return

    hp = int(parts[-1])
    fuel_type = parts[-2]
    engine_volume = int(parts[-3])
    model = parts[-4]
    manufacturer = "_".join(parts[:-4])  # На случай если в названии есть _

    try:
        save_hp_to_specs(manufacturer, model, engine_volume, fuel_type, hp, user_id)
        bot.answer_callback_query(
            call.id,
            f"✅ HP {hp} л.с. сохранён для {manufacturer} {model}",
            show_alert=True
        )
        # Обновляем кнопку
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None  # Убираем кнопку сохранения
        )
    except Exception as e:
        print(f"Ошибка сохранения HP: {e}")
        bot.answer_callback_query(call.id, f"⚠️ Ошибка сохранения: {e}")


# ==================== END HP INPUT HANDLERS ====================


def is_user_subscribed(user_id):
    """Проверяет, подписан ли пользователь на канал."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?chat_id={CHANNEL_USERNAME}&user_id={user_id}"
    response = requests.get(url).json()
    return response.get("ok") and response.get("result", {}).get("status") in [
        "member",
        "administrator",
        "creator",
    ]


def print_message(message):
    print("\n\n##############")
    print(f"{message}")
    print("##############\n\n")
    return None


# Функция для установки команд меню
def set_bot_commands():
    commands = [
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("exchange_rates", "Курсы валют"),
        types.BotCommand("my_cars", "Мои избранные автомобили"),
        types.BotCommand("orders", "Список заказов (для менеджеров)"),
        types.BotCommand("stats", "Статистика (для менеджеров)"),
    ]

    # Проверяем, является ли пользователь менеджером
    user_id = bot.get_me().id
    if user_id in MANAGERS:
        commands.extend(
            [
                types.BotCommand("orders", "Просмотр всех заказов (для менеджеров)"),
            ]
        )
    bot.set_my_commands(commands)


@bot.message_handler(commands=["stats"])
def stats_command(message):
    # Ограничение доступа: только менеджеры могут просматривать статистику
    if message.chat.id not in MANAGERS:
        bot.send_message(message.chat.id, "❌ У вас нет доступа к статистике.")
        return

    # Получаем список пользователей из базы данных
    try:
        users_list = (
            get_all_users()
        )  # Функция get_all_users() должна быть реализована в модуле database.py
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Ошибка получения данных о пользователях.")
        return

    if not users_list:
        bot.send_message(message.chat.id, "Нет зарегистрированных пользователей.")
        return

    # Формируем красивый вывод статистики
    lines = ["📊 Статистика пользования ботом:\n"]
    for user in users_list:
        lines.append(
            f"👤 {user.get('first_name', 'Не указано')}\n"
            f"💬 <b>Никнейм:</b> @{user.get('username', 'Не указан')}\n"
            f"⏰ <b>Дата начала пользования:</b> {user.get('timestamp', 'Не указано')}\n"
            "————————————"
        )
    output = "\n".join(lines)

    # Если сообщение слишком длинное, разбиваем его на части (максимум ~4000 символов, учитывая лимит Telegram)
    max_length = 4000
    parts = []
    while len(output) > max_length:
        split_index = output.rfind("\n", 0, max_length)
        if split_index == -1:
            split_index = max_length
        parts.append(output[:split_index])
        output = output[split_index:]
    parts.append(output)

    for part in parts:
        bot.send_message(message.chat.id, part, parse_mode="HTML")


def get_usdt_to_krw_rate():
    global usdt_to_krw_rate

    # URL для получения курса USDT к KRW
    url = "https://api.coinbase.com/v2/exchange-rates?currency=USDT"
    response = requests.get(url)
    data = response.json()

    # Извлечение курса KRW
    krw_rate = data["data"]["rates"]["KRW"]
    usdt_to_krw_rate = float(krw_rate) - 11

    print(f"Курс USDT к KRW -> {str(usdt_to_krw_rate)}")

    return float(krw_rate) + 8


def get_rub_to_krw_rate():
    global rub_to_krw_rate

    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en,ru;q=0.9,en-CA;q=0.8,la;q=0.7,fr;q=0.6,ko;q=0.5',
        'origin': 'https://m.search.naver.com',
        'priority': 'u=1, i',
        'referer': 'https://m.search.naver.com/',
        'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    }

    params = {
        'key': 'calculator',
        'pkid': '141',
        'q': '환율',
        'where': 'm',
        'u1': 'keb',
        'u6': 'standardUnit',
        'u7': '0',
        'u3': 'RUB',
        'u4': 'KRW',
        'u8': 'down',
        'u2': '1',
    }

    try:
        response = requests.get('https://ts-proxy.naver.com/content/qapirender.nhn',
                               params=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        # Extract the KRW value from the response
        if 'country' not in data or len(data['country']) < 2:
            raise ValueError("Invalid response structure")

        krw_value_str = data['country'][1]['value']
        rate_value = float(krw_value_str)

        if rate_value <= 0:
            raise ValueError("Invalid rate value <= 0")

        # Вычитаем 0.8 и округляем до 2 знаков после запятой
        rub_to_krw_rate = round(rate_value - 0.8, 2)

        print(f"RUB → KRW rate fetched: {rate_value} (adjusted: {rub_to_krw_rate})")
        return rub_to_krw_rate

    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"Error getting RUB → KRW rate: {e}")
        # Return last known good rate if we have one, otherwise use a fallback rate
        if rub_to_krw_rate and rub_to_krw_rate > 0:
            return rub_to_krw_rate
        return 15.50  # Fallback rate if everything fails


def get_currency_rates():
    global usd_rate, usd_to_krw_rate, usd_to_rub_rate, rub_to_krw_rate

    print_message("ПОЛУЧАЕМ КУРСЫ ВАЛЮТ")

    get_rub_to_krw_rate()
    # get_usd_to_krw_rate()

    rates_text = (
        # f"USD → KRW: <b>{usd_to_krw_rate:.2f} ₩</b>\n"
        f"RUB → KRW: <b>{rub_to_krw_rate:.2f} ₽</b>\n"
        # f"USD → RUB: <b>{usd_to_rub_rate:.2f} ₽</b>"
    )

    return rates_text


# Функция для получения курсов валют с API
def get_usd_to_krw_rate():
    global usd_to_krw_rate

    url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Проверяем успешность запроса
        data = response.json()

        # Получаем курс и добавляем +25 KRW
        usd_to_krw = data.get("usd", {}).get("krw", 0) - 15
        usd_to_krw_rate = usd_to_krw

        print(f"Курс USD → KRW: {usd_to_krw_rate}")
    except requests.RequestException as e:
        print(f"Ошибка при получении курса USD → KRW: {e}")
        usd_to_krw_rate = None


def get_usd_to_rub_rate():
    global usd_to_rub_rate

    url = "https://mosca.moscow/api/v1/rate/"
    headers = {
        "Access-Token": "JI_piVMlX9TsvIRKmduIbZOWzLo-v2zXozNfuxxXj4_MpsUKd_7aQS16fExzA7MVFCVVoAAmrb_-aMuu_UIbJA"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Проверяем успешность запроса
        data = response.json()

        # Получаем курс USD → RUB
        usd_to_rub = data["buy"] + 2.57
        usd_to_rub_rate = usd_to_rub

        print(f"Курс USD → RUB: {usd_to_rub_rate}")
    except requests.RequestException as e:
        print(f"Ошибка при получении курса USD → RUB: {e}")
        usd_to_rub_rate = None


# Обработчик команды /cbr
@bot.message_handler(commands=["exchange_rates"])
def cbr_command(message):
    try:
        rates_text = get_currency_rates()

        # Создаем клавиатуру с кнопкой для расчета автомобиля
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "Рассчитать стоимость автомобиля", callback_data="calculate_another"
            )
        )

        # Отправляем сообщение с курсами и клавиатурой
        bot.send_message(
            message.chat.id, rates_text, reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(
            message.chat.id, "Не удалось получить курсы валют. Попробуйте позже."
        )
        print(f"Ошибка при получении курсов валют: {e}")


def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(
        types.KeyboardButton(CALCULATE_CAR_TEXT),
        types.KeyboardButton("Ручной расчёт"),
        types.KeyboardButton("Вопрос/Ответ"),
    )
    keyboard.add(
        types.KeyboardButton("Написать менеджеру"),
        types.KeyboardButton("О нас"),
        types.KeyboardButton("Telegram-канал"),
        types.KeyboardButton("Instagram"),
    )
    return keyboard


# Start command handler
@bot.message_handler(commands=["start"])
def send_welcome(message):
    get_currency_rates()

    user_first_name = message.from_user.first_name
    welcome_message = (
        f"Здравствуйте, {user_first_name}!\n\n"
        "Я бот компании Caravan Trade. Я помогу вам рассчитать стоимость понравившегося вам автомобиля из Южной Кореи до РФ.\n\n"
        "Выберите действие из меню ниже."
    )

    # Логотип компании
    logo_url = "https://res.cloudinary.com/dt0nkqowc/image/upload/v1743227158/Caravan%20Trade/logo_full_qiyqzr.jpg"

    # Отправляем логотип перед сообщением
    bot.send_photo(
        message.chat.id,
        photo=logo_url,
    )

    # Отправляем приветственное сообщение
    bot.send_message(message.chat.id, welcome_message, reply_markup=main_menu())


# Error handling function
def send_error_message(message, error_text):
    global last_error_message_id

    # Remove previous error message if it exists
    if last_error_message_id.get(message.chat.id):
        try:
            bot.delete_message(message.chat.id, last_error_message_id[message.chat.id])
        except Exception as e:
            logging.error(f"Error deleting message: {e}")

    # Send new error message and store its ID
    error_message = bot.reply_to(message, error_text, reply_markup=main_menu())
    last_error_message_id[message.chat.id] = error_message.id
    logging.error(f"Error sent to user {message.chat.id}: {error_text}")


def get_car_info(url):
    global car_id_external, vehicle_no, vehicle_id, car_year, car_month

    if "fem.encar.com" in url:
        car_id_match = re.findall(r"\d+", url)
        car_id = car_id_match[0]
        car_id_external = car_id

        url = f"https://api.encar.com/v1/readside/vehicle/{car_id}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "http://www.encar.com/",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

        response = requests.get(url, headers=headers).json()

        # Информация об автомобиле
        car_make = response["category"]["manufacturerEnglishName"]  # Марка
        car_model = response["category"]["modelGroupEnglishName"]  # Модель
        car_trim = response["category"]["gradeDetailEnglishName"] or ""  # Комплектация

        car_title = f"{car_make} {car_model} {car_trim}"  # Заголовок

        # Получаем все необходимые данные по автомобилю
        car_price = str(response["advertisement"]["price"])
        car_date = response["category"]["yearMonth"]
        year = car_date[2:4]
        month = car_date[4:]
        car_year = year
        car_month = month

        # Пробег (форматирование)
        mileage = response["spec"]["mileage"]
        formatted_mileage = f"{mileage:,} км"

        # Тип КПП
        transmission = response["spec"]["transmissionName"]
        formatted_transmission = "Автомат" if "오토" in transmission else "Механика"

        car_engine_displacement = str(response["spec"]["displacement"])
        car_type = response["spec"]["bodyName"]
        fuel_type = response["spec"]["fuelName"]

        # Список фотографий (берем первые 10)
        car_photos = [
            generate_encar_photo_url(photo["path"]) for photo in response["photos"][:10]
        ]
        car_photos = [url for url in car_photos if url]

        # Дополнительные данные
        vehicle_no = response["vehicleNo"]
        vehicle_id = response["vehicleId"]

        # Форматируем
        formatted_car_date = f"01{month}{year}"
        formatted_car_type = "crossover" if car_type == "SUV" else "sedan"

        print_message(
            f"ID: {car_id}\nType: {formatted_car_type}\nDate: {formatted_car_date}\nCar Engine Displacement: {car_engine_displacement}\nPrice: {car_price} KRW"
        )

        return [
            car_price,
            car_engine_displacement,
            formatted_car_date,
            car_title,
            formatted_mileage,
            formatted_transmission,
            car_photos,
            year,
            month,
            fuel_type,
        ]
    elif "kbchachacha.com" in url:
        url = f"https://www.kbchachacha.com/public/car/detail.kbc?carSeq={car_id_external}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en,ru;q=0.9,en-CA;q=0.8,la;q=0.7,fr;q=0.6,ko;q=0.5",
            "Connection": "keep-alive",
        }

        response = requests.get(url=url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        # Находим JSON в <script type="application/ld+json">
        json_script = soup.find("script", {"type": "application/ld+json"})
        if json_script:
            json_data = json.loads(json_script.text.strip())

            # Извлекаем данные
            car_name = json_data.get("name", "Неизвестная модель")
            car_images = json_data.get("image", [])[:10]  # Берем первые 10 фото
            car_price = json_data.get("offers", {}).get("price", "Не указано")

            # Находим таблицу с информацией
            table = soup.find("table", {"class": "detail-info-table"})
            if table:
                rows = table.find_all("tr")

                # Достаём данные
                car_number = None
                car_year = None
                car_mileage = None
                car_fuel = None
                car_engine_displacement = None

                for row in rows:
                    headers = row.find_all("th")
                    values = row.find_all("td")

                    for th, td in zip(headers, values):
                        header_text = th.text.strip()
                        value_text = td.text.strip()

                        if header_text == "차량정보":  # Номер машины
                            car_number = value_text
                        elif header_text == "연식":  # Год выпуска
                            car_year = value_text
                        elif header_text == "주행거리":  # Пробег
                            car_mileage = value_text
                        elif header_text == "연료":  # Топливо
                            car_fuel = value_text
                        elif header_text == "배기량":  # Объем двигателя
                            car_engine_displacement = value_text
            else:
                print("❌ Таблица информации не найдена")

            car_info = {
                "name": car_name,
                "car_price": car_price,
                "images": car_images,
                "number": car_number,
                "year": car_year,
                "mileage": car_mileage,
                "fuel": car_fuel,
                "engine_volume": car_engine_displacement,
                "transmission": "오토",
            }

            return car_info
        else:
            print(
                "❌ Не удалось найти JSON-данные в <script type='application/ld+json'>"
            )
    elif "kcar" in url:
        print("🔍 Парсим KCar.com...")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en,ru;q=0.9,en-CA;q=0.8,la;q=0.7,fr;q=0.6,ko;q=0.5",
            "Referer": "https://www.kcar.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }

        response = requests.get(url, headers=headers)
        json_response = response.json()

        data = json_response.get("data", {})

        car_name = data.get("rvo", {}).get("carWhlNm", "")
        car_price = data.get("rvo", {}).get("npriceFullType", "")
        car_mileage = data.get("rvo", {}).get("milg", "")
        car_engine_displacement = data.get("rvo", {}).get("engdispmnt", "")
        transmission = data.get("rvo", {}).get("trnsmsncdNm", "")
        car_number = data.get("rvo", {}).get("cno", "")

        car_images = data.get("photoList", [])

        # Фильтруем фото, у которых есть "sortOrdr", и сортируем по этому значению
        sorted_images = sorted(
            [photo for photo in car_images if photo.get("sortOrdr")],
            key=lambda x: int(x["sortOrdr"]),
        )

        # Берём первые 10 и достаём ссылки
        car_image_urls = [photo["elanPath"] for photo in sorted_images[:10]]

        car_year = data.get("rvo", {}).get(
            "fstCarRegYm", ""
        )  # Приходит в таком формате 202211

        year = car_year[0:4]
        month = car_year[4:]

        car_fuel = data.get("rvo", {}).get("fuelTypecdNm", "")

        car_insurance_history = data.get("carHistoryAccList", [])
        own_damage_total = 0
        other_damage_total = 0

        if len(car_insurance_history) > 0:
            for record in car_insurance_history:
                own_damage_total += record.get("reprEstmCost2", 0)
                other_damage_total += record.get("reprEstmCost1", 0)

        car_info = {
            "name": car_name,
            "car_price": car_price,
            "images": car_image_urls,
            "number": car_number,
            "year": year,
            "month": month,
            "mileage": car_mileage,
            "fuel": car_fuel,
            "engine_volume": car_engine_displacement,
            "transmission": transmission,
            "own_damage_total": own_damage_total,
            "other_damage_total": other_damage_total,
        }

        return car_info


# Function to calculate the total cost
def calculate_cost(link, message):
    global car_data, car_id_external, car_month, car_year, krw_rub_rate, eur_rub_rate, rub_to_krw_rate, usd_rate, usdt_to_krw_rate

    try:
        # Get current rates
        rate = get_currency_rates()
        krw_rate = get_rub_to_krw_rate()
        usdt_rate = get_usdt_to_krw_rate()

        if not krw_rate or krw_rate <= 0:
            bot.send_message(
                message.chat.id,
                "❌ Ошибка получения курса валют. Пожалуйста, попробуйте позже.",
                parse_mode="HTML",
            )
            return

        rub_to_krw_rate = krw_rate  # Update global rate

        bot.send_message(
            message.chat.id,
            "✅ Подгружаю актуальный курс валют и делаю расчёты. ⏳ Пожалуйста подождите...",
            parse_mode="Markdown",
        )

        print_message("ЗАПРОС НА РАСЧЁТ АВТОМОБИЛЯ")

        # Отправляем сообщение и сохраняем его ID
        processing_message = bot.send_message(
            message.chat.id, "Обрабатываю данные... ⏳"
        )

        car_id = None
        car_title = ""

        if "fem.encar.com" in link:
            car_id_match = re.findall(r"\d+", link)
            if car_id_match:
                car_id = car_id_match[0]  # Use the first match of digits
                car_id_external = car_id
                link = f"https://fem.encar.com/cars/detail/{car_id}"
            else:
                send_error_message(message, "🚫 Не удалось извлечь carid из ссылки.")
                return

        elif "kbchachacha.com" in link or "m.kbchachacha.com" in link:
            parsed_url = urlparse(link)
            query_params = parse_qs(parsed_url.query)
            car_id = query_params.get("carSeq", [None])[0]

            if car_id:
                car_id_external = car_id
                link = (
                    f"https://www.kbchachacha.com/public/car/detail.kbc?carSeq={car_id}"
                )
            else:
                send_error_message(message, "🚫 Не удалось извлечь carSeq из ссылки.")
                return

        elif "kcar.com" in link or "m.kcar.com" in link:
            parsed_url = urlparse(link)
            query_params = parse_qs(parsed_url.query)

            if "i_sCarCd" in query_params:
                car_id = query_params["i_sCarCd"][0]
                car_id_external = car_id
                link = f"https://api.kcar.com/bc/car-info-detail-of-ng?i_sCarCd={car_id}&i_sPassYn=N&bltbdKnd=CM050"
            else:
                send_error_message(
                    message, "🚫 Не удалось извлечь ID автомобиля из ссылки KCar."
                )
                return

        else:
            # Извлекаем carid с URL encar
            parsed_url = urlparse(link)
            query_params = parse_qs(parsed_url.query)
            car_id = query_params.get("carid", [None])[0]

        # Если ссылка с encar
        if "fem.encar.com" in link:
            # Сначала проверяем pan-auto.ru для получения HP и предрассчитанных таможенных платежей
            pan_auto_data = get_pan_auto_data(car_id)

            if pan_auto_data and pan_auto_data.get("hp") and pan_auto_data.get("costs"):
                # Используем данные pan-auto.ru напрямую
                try:
                    costs = pan_auto_data["costs"]
                    hp = pan_auto_data["hp"]

                    # Получаем базовую информацию о машине из pan-auto
                    car_title = f"{pan_auto_data.get('manufacturer', '')} {pan_auto_data.get('model', '')} {pan_auto_data.get('badge', '')}".strip()
                    car_engine_displacement = pan_auto_data.get("displacement", 0)
                    engine_volume_formatted = f"{format_number(car_engine_displacement)} cc"

                    # Стоимость авто в KRW (carPriceEncar - это цена в вонах)
                    price_krw = int(costs.get("carPriceEncar", 0))
                    price_rub = float(costs.get("carPrice", 0))

                    # Таможенные платежи из pan-auto
                    customs_fee = float(costs.get("clearanceCost", 0))  # Таможенное оформление
                    customs_duty = float(costs.get("customsDuty", 0))  # Таможенная пошлина
                    recycling_fee = float(costs.get("utilizationFee", 0))  # Утильсбор

                    # Форматируем возраст
                    car_age = pan_auto_data.get("carAge", 1)
                    age_formatted = (
                        "до 3 лет" if car_age <= 1 else
                        "от 3 до 5 лет" if car_age == 2 else
                        "от 5 до 7 лет" if car_age == 3 else
                        "от 7 лет"
                    )

                    # Получаем год из pan-auto (формат "2023")
                    year_full = pan_auto_data.get("year", "2023")
                    year = str(year_full)[-2:] if year_full else "23"
                    month = "01"  # pan-auto не даёт точный месяц

                    # Пробег
                    mileage_km = pan_auto_data.get("mileage", 0)
                    formatted_mileage = f"{format_number(mileage_km)} км"

                    # КПП (не указана в pan-auto, ставим по умолчанию)
                    formatted_transmission = "Автомат"

                    # Фото (используем encar API для фото)
                    result = get_car_info(link)
                    if result:
                        car_photos = result[6] if len(result) > 6 else []
                    else:
                        car_photos = []

                    preview_link = f"https://fem.encar.com/cars/detail/{car_id}"

                    # Расчет итоговой стоимости с нашими фиксированными ставками
                    # Используем таможенные платежи из pan-auto, но свои комиссии
                    total_cost = (
                        price_rub  # Стоимость автомобиля в рублях (из pan-auto)
                        + (440000 / rub_to_krw_rate)  # Комиссия Encar
                        + (1300000 / rub_to_krw_rate)  # Доставка до Владивостока
                        + customs_fee  # Таможенное оформление (из pan-auto)
                        + customs_duty  # Таможенная пошлина (из pan-auto)
                        + recycling_fee  # Утильсбор (из pan-auto)
                        + 100000  # Услуги брокера
                    )

                    total_cost_krw = (
                        price_krw  # Стоимость автомобиля
                        + 440000  # Комиссия Encar
                        + 1300000  # Доставка до Владивостока
                        + (customs_fee * rub_to_krw_rate)  # Таможенное оформление
                        + (customs_duty * rub_to_krw_rate)  # Таможенная пошлина
                        + (recycling_fee * rub_to_krw_rate)  # Утильсбор
                        + (100000 * rub_to_krw_rate)  # Услуги брокера
                    )

                    # Сохраняем данные
                    car_data["total_cost_krw"] = total_cost_krw
                    car_data["total_cost_rub"] = total_cost
                    car_data["car_price_krw"] = price_krw
                    car_data["car_price_rub"] = price_rub
                    car_data["encar_fee_krw"] = 440000
                    car_data["encar_fee_rub"] = 440000 / rub_to_krw_rate
                    car_data["delivery_fee_krw"] = 1300000
                    car_data["delivery_fee_rub"] = 1300000 / rub_to_krw_rate
                    car_data["customs_duty_rub"] = customs_duty
                    car_data["customs_duty_krw"] = customs_duty * rub_to_krw_rate
                    car_data["customs_fee_rub"] = customs_fee
                    car_data["customs_fee_krw"] = customs_fee * rub_to_krw_rate
                    car_data["util_fee_rub"] = recycling_fee
                    car_data["util_fee_krw"] = recycling_fee * rub_to_krw_rate
                    car_data["broker_fee_rub"] = 100000
                    car_data["broker_fee_krw"] = 100000 * rub_to_krw_rate

                    # Формирование сообщения результата с HP
                    result_message = (
                        f"❯ <b>{car_title}</b>\n\n"
                        f"▪️ Возраст: <b>{age_formatted}</b> <i>(год выпуска: {year_full})</i>\n"
                        f"▪️ Пробег: <b>{formatted_mileage}</b>\n"
                        f"▪️ Объём двигателя: <b>{engine_volume_formatted}</b>\n"
                        f"▪️ Мощность: <b>{hp} л.с.</b>\n"
                        f"▪️ КПП: <b>{formatted_transmission}</b>\n\n"
                        f"💰 <b>Курс Рубля к Воне: ₩{rub_to_krw_rate:.2f}</b>\n\n"
                        f"1️⃣ Стоимость автомобиля:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
                        f"2️⃣ Комиссия Encar:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['encar_fee_krw'])}</b> | <b>{format_number(car_data['encar_fee_rub'])} ₽</b>\n\n"
                        f"3️⃣ Доставка до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['delivery_fee_krw'])}</b> | <b>{format_number(car_data['delivery_fee_rub'])} ₽</b>\n\n"
                        f"4️⃣ Единая таможенная ставка:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
                        f"5️⃣ Таможенное оформление:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
                        f"6️⃣ Утилизационный сбор:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n"
                        f"7️⃣ Услуги брокера:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['broker_fee_krw'])}</b> | <b>{format_number(car_data['broker_fee_rub'])} ₽</b>\n\n"
                        f"🟰 Итого под ключ: \n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
                        f"🔗 <a href='{preview_link}'>Ссылка на автомобиль</a>\n\n"
                        "Если данное авто попадает под санкции, пожалуйста уточните возможность отправки в вашу страну у наших менеджеров:\n\n"
                        f"▪️ +82-10-2889-2307 (Олег)\n"
                        f"▪️ +82-10-5812-2515 (Дмитрий)\n\n"
                        "🔗 <a href='https://t.me/crvntrade'>Официальный телеграм канал</a>\n"
                    )

                    # Клавиатура
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.add(types.InlineKeyboardButton(
                        "⭐ Добавить в избранное",
                        callback_data=f"add_favorite_{car_id_external}",
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Технический Отчёт об Автомобиле",
                        callback_data="technical_card",
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Выплаты по ДТП",
                        callback_data="technical_report",
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Написать менеджеру (Олег)", url="https://t.me/KaMik_23"
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Написать менеджеру (Дима)", url="https://t.me/Pako_000"
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Расчёт другого автомобиля",
                        callback_data="calculate_another",
                    ))
                    keyboard.add(types.InlineKeyboardButton(
                        "Главное меню",
                        callback_data="main_menu",
                    ))

                    # Отправляем фото
                    media_group = []
                    for photo_url in sorted(car_photos) if car_photos else []:
                        try:
                            response = requests.get(photo_url)
                            if response.status_code == 200:
                                photo = BytesIO(response.content)
                                media_group.append(types.InputMediaPhoto(photo))
                                if len(media_group) == 10:
                                    bot.send_media_group(message.chat.id, media_group)
                                    media_group.clear()
                        except Exception as e:
                            print(f"Ошибка при обработке фото {photo_url}: {e}")

                    if media_group:
                        bot.send_media_group(message.chat.id, media_group)

                    # Сохраняем данные для избранного
                    car_data["car_id"] = car_id
                    car_data["name"] = car_title
                    car_data["images"] = car_photos if isinstance(car_photos, list) else []
                    car_data["link"] = preview_link
                    car_data["year"] = year
                    car_data["month"] = month
                    car_data["mileage"] = formatted_mileage
                    car_data["engine_volume"] = car_engine_displacement
                    car_data["transmission"] = formatted_transmission
                    car_data["car_price"] = price_krw
                    car_data["user_name"] = message.from_user.username
                    car_data["first_name"] = message.from_user.first_name
                    car_data["last_name"] = message.from_user.last_name
                    car_data["hp"] = hp

                    bot.send_message(
                        message.chat.id,
                        result_message,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                    )

                    bot.delete_message(message.chat.id, processing_message.message_id)
                    return  # Выходим, т.к. расчёт завершён

                except Exception as e:
                    print(f"[PAN-AUTO] Ошибка при использовании данных pan-auto.ru: {e}")
                    # Продолжаем с обычным расчётом через calcus.ru

            # Если pan-auto.ru не дал данных, используем стандартный путь
            result = get_car_info(link)
            (
                car_price,
                car_engine_displacement,
                formatted_car_date,
                car_title,
                formatted_mileage,
                formatted_transmission,
                car_photos,
                year,
                month,
                fuel_type,
            ) = result

            preview_link = f"https://fem.encar.com/cars/detail/{car_id}"

        # Если ссылка с kbchacha
        if "kbchachacha.com" in link:
            result = get_car_info(link)

            car_title = result["name"]

            match = re.search(r"(\d{2})년(\d{2})월", result["year"])
            if match:
                car_year = match.group(1)
                car_month = match.group(2)  # Получаем двухзначный месяц
            else:
                car_year = "Не найдено"
                car_month = "Не найдено"

            month = car_month
            year = car_year

            car_engine_displacement = re.sub(r"[^\d]", "", result["engine_volume"])
            car_engine_displacement = (
                2200 if result["fuel"] == "디젤" else car_engine_displacement
            )

            car_price = int(result["car_price"]) / 10000
            formatted_car_date = f"01{car_month}{match.group(1)}"
            formatted_mileage = result["mileage"]
            formatted_transmission = (
                "Автомат" if "오토" in result["transmission"] else "Механика"
            )
            car_photos = result["images"]

            fuel_type = "가솔린"

            preview_link = (
                f"https://www.kbchachacha.com/public/car/detail.kbc?carSeq={car_id}"
            )

        if "kcar" in link:
            result = get_car_info(link)

            car_title = result["name"]

            month = result["month"]
            year = result["year"]

            car_month = month
            car_year = year[2:]

            car_engine_displacement = re.sub(r"\D+", "", result["engine_volume"])
            car_price = int(result["car_price"]) / 10000

            car_photos = result["images"]

            fuel_type = "가솔린"

            # Форматируем дату
            formatted_car_date = (
                f"01{car_month}{car_year[-2:]}"
                if car_year != "Не найдено"
                else "Не найдено"
            )

            # Форматируем пробег
            formatted_mileage = format_number(result["mileage"]) + " км"

            # Определяем КПП
            formatted_transmission = (
                "Автомат" if "오토" in result["transmission"] else "Механика"
            )

            preview_link = (
                f"https://www.kcar.com/bc/detail/carInfoDtl?i_sCarCd={car_id}"
            )

            own_car_insurance_payments = result["own_damage_total"]
            other_car_insurance_payments = result["other_damage_total"]

        if not car_price and car_engine_displacement and formatted_car_date:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "Написать менеджеру (Олег)", url="https://t.me/KaMik_23"
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Написать менеджеру (Дима)", url="https://t.me/Pako_000"
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )
            bot.send_message(
                message.chat.id, "Ошибка", parse_mode="Markdown", reply_markup=keyboard
            )
            bot.delete_message(message.chat.id, processing_message.message_id)
            return

        if car_price and car_engine_displacement and formatted_car_date:
            try:
                car_engine_displacement = int(car_engine_displacement)

                # Форматирование данных
                formatted_car_year = f"20{car_year}"
                engine_volume_formatted = f"{format_number(car_engine_displacement)} cc"

                age = calculate_age(int(formatted_car_year), car_month)

                age_formatted = (
                    "до 3 лет"
                    if age == "0-3"
                    else (
                        "от 3 до 5 лет"
                        if age == "3-5"
                        else "от 5 до 7 лет" if age == "5-7" else "от 7 лет"
                    )
                )

                # Safety check for division
                if rub_to_krw_rate <= 0:
                    raise ValueError("Invalid currency rate")

                # Конвертируем стоимость авто в рубли
                price_krw = int(car_price) * 10000
                price_rub = price_krw / rub_to_krw_rate

                # Определяем производителя и модель для поиска HP в базе
                # car_title уже содержит Make Model Trim
                car_title_parts = car_title.split() if car_title else []
                manufacturer = car_title_parts[0] if len(car_title_parts) > 0 else "Unknown"
                model = car_title_parts[1] if len(car_title_parts) > 1 else "Unknown"

                # Определяем тип топлива для поиска HP
                fuel_type_ru = "Бензин" if fuel_type == "가솔린" else "Дизель" if fuel_type == "디젤" else "Гибрид"

                # Проверяем, есть ли сохранённый HP в базе данных
                stored_hp = get_hp_from_specs(manufacturer, model, car_engine_displacement, fuel_type_ru)

                if stored_hp is None:
                    # HP не найден - нужно запросить у пользователя
                    # Сохраняем данные о машине для продолжения расчёта после ввода HP
                    pending_hp_calculations[message.from_user.id] = {
                        "car_id": car_id,
                        "car_id_external": car_id_external,
                        "link": link,
                        "preview_link": preview_link,
                        "car_title": car_title,
                        "car_engine_displacement": car_engine_displacement,
                        "engine_volume_formatted": engine_volume_formatted,
                        "price_krw": price_krw,
                        "price_rub": price_rub,
                        "formatted_car_year": formatted_car_year,
                        "car_year": car_year,
                        "car_month": car_month,
                        "month": month,
                        "year": year,
                        "age": age,
                        "age_formatted": age_formatted,
                        "formatted_mileage": formatted_mileage,
                        "formatted_transmission": formatted_transmission,
                        "car_photos": car_photos,
                        "fuel_type": fuel_type,
                        "fuel_type_ru": fuel_type_ru,
                        "manufacturer": manufacturer,
                        "model": model,
                        "rub_to_krw_rate": rub_to_krw_rate,
                        "message_chat_id": message.chat.id,
                        "processing_message_id": processing_message.message_id,
                        "user_name": message.from_user.username,
                        "first_name": message.from_user.first_name,
                        "last_name": message.from_user.last_name,
                    }

                    # Создаём клавиатуру с вариантами HP
                    hp_keyboard = types.InlineKeyboardMarkup(row_width=3)
                    hp_buttons = [
                        types.InlineKeyboardButton("100 л.с.", callback_data="hp_input_100"),
                        types.InlineKeyboardButton("150 л.с.", callback_data="hp_input_150"),
                        types.InlineKeyboardButton("180 л.с.", callback_data="hp_input_180"),
                        types.InlineKeyboardButton("200 л.с.", callback_data="hp_input_200"),
                        types.InlineKeyboardButton("250 л.с.", callback_data="hp_input_250"),
                        types.InlineKeyboardButton("300 л.с.", callback_data="hp_input_300"),
                    ]
                    hp_keyboard.add(*hp_buttons)
                    hp_keyboard.add(types.InlineKeyboardButton(
                        "✏️ Ввести вручную",
                        callback_data="hp_input_manual"
                    ))
                    hp_keyboard.add(types.InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data="hp_input_cancel"
                    ))

                    bot.send_message(
                        message.chat.id,
                        f"⚠️ <b>Для расчёта утилизационного сбора нужна мощность двигателя (л.с.)</b>\n\n"
                        f"Автомобиль: <b>{car_title}</b>\n"
                        f"Объём двигателя: <b>{engine_volume_formatted}</b>\n\n"
                        "Выберите мощность или введите вручную:",
                        parse_mode="HTML",
                        reply_markup=hp_keyboard
                    )

                    bot.delete_message(message.chat.id, processing_message.message_id)
                    return  # Ждём ввода HP от пользователя

                # Используем HP из базы (гарантированно есть, т.к. иначе запросили бы у пользователя)
                power = stored_hp

                response = get_customs_fees(
                    car_engine_displacement,
                    price_krw,
                    int(formatted_car_year),
                    car_month,
                    engine_type=(
                        1 if fuel_type == "가솔린" else 2 if fuel_type == "디젤" else 3
                    ),
                    power=power,
                )

                if response is None:
                    bot.send_message(
                        message.chat.id,
                        "❌ Временная ошибка при расчете таможенных платежей. Сервис calcus.ru перегружен. Попробуйте через несколько минут.",
                        reply_markup=types.ReplyKeyboardRemove()
                    )
                    return

                # Таможенный сбор
                customs_fee = clean_number(response["sbor"])
                customs_duty = clean_number(response["tax"])
                recycling_fee = clean_number(response["util"])

                # Расчет итоговой стоимости автомобиля в рублях
                total_cost = (
                    price_rub  # Стоимость автомобиля
                    + (440000 / rub_to_krw_rate)  # Комиссия Encar
                    + (1300000 / rub_to_krw_rate)  # Доставка до Владивостока
                    + customs_fee  # Таможенный сбор
                    + customs_duty  # Таможенная пошлина
                    + recycling_fee  # Утильсбор
                    + 100000  # Услуги брокера
                )

                total_cost_krw = (
                    price_krw  # Стоимость автомобиля
                    + 440000  # Комиссия Encar
                    + 1300000  # Доставка до Владивостока
                    + (customs_fee * rub_to_krw_rate)  # Таможенный сбор
                    + (customs_duty * rub_to_krw_rate)  # Таможенная пошлина
                    + (recycling_fee * rub_to_krw_rate)  # Утильсбор
                    + (100000 * rub_to_krw_rate)  # Услуги брокера
                )

                # Общая сумма под ключ до Владивостока
                car_data["total_cost_krw"] = total_cost_krw
                car_data["total_cost_rub"] = total_cost

                # Стоимость автомобиля
                car_data["car_price_krw"] = price_krw
                car_data["car_price_rub"] = price_rub

                # Комиссия Encar
                car_data["encar_fee_krw"] = 440000
                car_data["encar_fee_rub"] = 440000 / rub_to_krw_rate

                # Доставка до Владивостока
                car_data["delivery_fee_krw"] = 1300000
                car_data["delivery_fee_rub"] = 1300000 / rub_to_krw_rate

                # Расходы по РФ
                car_data["customs_duty_rub"] = customs_duty
                car_data["customs_duty_krw"] = customs_duty * rub_to_krw_rate

                car_data["customs_fee_rub"] = customs_fee
                car_data["customs_fee_krw"] = customs_fee * rub_to_krw_rate

                car_data["util_fee_rub"] = recycling_fee
                car_data["util_fee_krw"] = recycling_fee * rub_to_krw_rate

                car_data["broker_fee_rub"] = 100000
                car_data["broker_fee_krw"] = 100000 * rub_to_krw_rate

                car_insurance_payments_chutcha = ""
                if "kcar" in link:
                    own_insurance_text = (
                        f"₩{format_number(own_car_insurance_payments)}"
                        if isinstance(own_car_insurance_payments, int)
                        else "Нет"
                    )
                    other_insurance_text = (
                        f"₩{format_number(other_car_insurance_payments)}"
                        if isinstance(other_car_insurance_payments, int)
                        else "Нет"
                    )

                    car_insurance_payments_chutcha = (
                        f"▪️ Страховые выплаты по данному автомобилю:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>{own_insurance_text}</b>\n"
                        f"▪️ Страховые выплаты другому автомобилю:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>{other_insurance_text}</b>\n\n"
                    )

                # Формирование сообщения результата
                # f"💵 <b>Курс USDT к Воне: ₩{format_number(usdt_to_krw_rate)}</b>\n\n"
                result_message = (
                    f"❯ <b>{car_title}</b>\n\n"
                    f"▪️ Возраст: <b>{age_formatted}</b> <i>(дата регистрации: {month}/{year})</i>\n"
                    f"▪️ Пробег: <b>{formatted_mileage}</b>\n"
                    f"▪️ Объём двигателя: <b>{engine_volume_formatted}</b>\n"
                    f"▪️ КПП: <b>{formatted_transmission}</b>\n\n"
                    f"💰 <b>Курс Рубля к Воне: ₩{rub_to_krw_rate:.2f}</b>\n\n"
                    # f"▪️ Стоимость автомобиля в Корее:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(price_krw)}</b>\n\n"
                    # f"▪️ Стоимость автомобиля под ключ до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(total_cost_krw)}</b> | <b>{format_number(total_cost)} ₽</b>\n\n"
                    f"1️⃣ Стоимость автомобиля:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
                    f"2️⃣ Комиссия Encar:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['encar_fee_krw'])}</b> | <b>{format_number(car_data['encar_fee_rub'])} ₽</b>\n\n"
                    f"3️⃣ Доставка до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['delivery_fee_krw'])}</b> | <b>{format_number(car_data['delivery_fee_rub'])} ₽</b>\n\n"
                    f"4️⃣ Единая таможенная ставка:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
                    f"5️⃣ Таможенное оформление:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
                    f"6️⃣ Утилизационный сбор:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n"
                    f"7️⃣ Услуги брокера:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['broker_fee_krw'])}</b> | <b>{format_number(car_data['broker_fee_rub'])} ₽</b>\n\n"
                    f"🟰 Итого под ключ: \n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
                    f"{car_insurance_payments_chutcha}"
                    f"🔗 <a href='{preview_link}'>Ссылка на автомобиль</a>\n\n"
                    "Если данное авто попадает под санкции, пожалуйста уточните возможность отправки в вашу страну у наших менеджеров:\n\n"
                    f"▪️ +82-10-2889-2307 (Олег)\n"
                    f"▪️ +82-10-5812-2515 (Дмитрий)\n\n"
                    "🔗 <a href='https://t.me/crvntrade'>Официальный телеграм канал</a>\n"
                )

                # Клавиатура с дальнейшими действиями
                keyboard = types.InlineKeyboardMarkup()
                # keyboard.add(
                #     types.InlineKeyboardButton("Детали расчёта", callback_data="detail")
                # )

                # Кнопка для добавления в избранное
                keyboard.add(
                    types.InlineKeyboardButton(
                        "⭐ Добавить в избранное",
                        callback_data=f"add_favorite_{car_id_external}",
                    )
                )

                if "fem.encar.com" in link:
                    keyboard.add(
                        types.InlineKeyboardButton(
                            "Технический Отчёт об Автомобиле",
                            callback_data="technical_card",
                        )
                    )
                    keyboard.add(
                        types.InlineKeyboardButton(
                            "Выплаты по ДТП",
                            callback_data="technical_report",
                        )
                    )
                keyboard.add(
                    types.InlineKeyboardButton(
                        "Написать менеджеру (Олег)", url="https://t.me/KaMik_23"
                    )
                )
                keyboard.add(
                    types.InlineKeyboardButton(
                        "Написать менеджеру (Дима)", url="https://t.me/Pako_000"
                    )
                )
                keyboard.add(
                    types.InlineKeyboardButton(
                        "Расчёт другого автомобиля",
                        callback_data="calculate_another",
                    )
                )
                keyboard.add(
                    types.InlineKeyboardButton(
                        "Главное меню",
                        callback_data="main_menu",
                    )
                )

                # Отправляем до 10 фотографий
                media_group = []
                for photo_url in sorted(car_photos):
                    try:
                        response = requests.get(photo_url)
                        if response.status_code == 200:
                            photo = BytesIO(response.content)  # Загружаем фото в память
                            media_group.append(
                                types.InputMediaPhoto(photo)
                            )  # Добавляем в список

                            # Если набрали 10 фото, отправляем альбом
                            if len(media_group) == 10:
                                bot.send_media_group(message.chat.id, media_group)
                                media_group.clear()  # Очищаем список для следующей группы
                        else:
                            print(
                                f"Ошибка загрузки фото: {photo_url} - {response.status_code}"
                            )
                    except Exception as e:
                        print(f"Ошибка при обработке фото {photo_url}: {e}")

                # Отправка оставшихся фото, если их меньше 10
                if media_group:
                    bot.send_media_group(message.chat.id, media_group)

                car_data["car_id"] = car_id
                car_data["name"] = car_title
                car_data["images"] = car_photos if isinstance(car_photos, list) else []
                car_data["link"] = preview_link
                car_data["year"] = year
                car_data["month"] = month
                car_data["mileage"] = formatted_mileage
                car_data["engine_volume"] = car_engine_displacement
                car_data["transmission"] = formatted_transmission
                car_data["car_price"] = price_krw
                car_data["user_name"] = message.from_user.username
                car_data["first_name"] = message.from_user.first_name
                car_data["last_name"] = message.from_user.last_name

                bot.send_message(
                    message.chat.id,
                    result_message,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

                bot.delete_message(
                    message.chat.id, processing_message.message_id
                )  # Удаляем сообщение о передаче данных в обработку

            except ValueError as e:
                bot.send_message(
                    message.chat.id,
                    f"❌ Ошибка при расчёте стоимости: {e}",
                    parse_mode="HTML",
                )
                bot.delete_message(message.chat.id, processing_message.message_id)

        else:
            send_error_message(
                message,
                "🚫 Произошла ошибка при получении данных. Проверьте ссылку и попробуйте снова.",
            )
            bot.delete_message(message.chat.id, processing_message.message_id)

    except Exception as e:
        bot.send_message(
            message.chat.id, f"❌ Ошибка при получении данных: {e}", parse_mode="HTML"
        )
        bot.delete_message(message.chat.id, processing_message.message_id)


# Function to get insurance total
def get_insurance_total():
    global car_id_external, vehicle_no, vehicle_id

    print_message("[ЗАПРОС] ТЕХНИЧЕСКИЙ ОТЧËТ ОБ АВТОМОБИЛЕ")

    formatted_vehicle_no = urllib.parse.quote(str(vehicle_no).strip())
    url = f"https://api.encar.com/v1/readside/record/vehicle/{str(vehicle_id)}/open?vehicleNo={formatted_vehicle_no}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "http://www.encar.com/",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

        response = requests.get(url, headers)
        json_response = response.json()

        # Форматируем данные
        damage_to_my_car = json_response["myAccidentCost"]
        damage_to_other_car = json_response["otherAccidentCost"]

        print(
            f"Выплаты по представленному автомобилю: {format_number(damage_to_my_car)}"
        )
        print(f"Выплаты другому автомобилю: {format_number(damage_to_other_car)}")

        return [format_number(damage_to_my_car), format_number(damage_to_other_car)]

    except Exception as e:
        print(f"Произошла ошибка при получении данных: {e}")
        return ["", ""]


def get_technical_card():
    global vehicle_id

    url = f"https://api.encar.com/v1/readside/inspection/vehicle/{vehicle_id}"

    print(vehicle_id)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "http://www.encar.com/",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

        response = requests.get(url, headers=headers)
        json_response = response.json() if response.status_code == 200 else None

        if not json_response:
            return "❌ Ошибка: не удалось получить данные. Проверьте ссылку."

        master = json_response.get("master", {}).get("detail", {})
        if not master:
            return "❌ Ошибка: данные о транспортном средстве не найдены."

        vehicle_id = json_response.get("vehicleId", "Не указано")
        model_year = (master.get("modelYear") or "Не указано").strip()
        vin = master.get("vin", "Не указано")
        first_registration_date = master.get("firstRegistrationDate", "Не указано")
        registration_date = master.get("registrationDate", "Не указано")
        mileage = f"{int(master.get('mileage', 0)):,}".replace(",", " ") + " км"

        transmission_data = master.get("transmissionType")
        transmission = (
            transmission_data.get("title") if transmission_data else "Не указано"
        )

        color_data = master.get("colorType")
        color = color_data.get("title") if color_data else "Не указано"

        car_state_data = master.get("carStateType")
        car_state = car_state_data.get("title") if car_state_data else "Не указано"

        motor_type = master.get("motorType", "Не указано")

        accident = "❌ Нет" if not master.get("accdient", False) else "⚠️ Да"
        simple_repair = "❌ Нет" if not master.get("simpleRepair", False) else "⚠️ Да"
        waterlog = "❌ Нет" if not master.get("waterlog", False) else "⚠️ Да"
        tuning = "❌ Нет" if not master.get("tuning", False) else "⚠️ Да"

        # Переводы
        translations = {
            "오토": "Автоматическая",
            "수동": "Механическая",
            "자가보증": "Собственная гарантия",
            "양호": "Хорошее состояние",
            "무채색": "Нейтральный",
            "적정": "В норме",
            "없음": "Нет",
            "누유": "Утечка",
            "불량": "Неисправность",
            "미세누유": "Незначительная утечка",
            "양호": "В хорошем состоянии",
            "주의": "Требует внимания",
            "교환": "Замена",
            "부족": "Недостаточный уровень",
            "정상": "Нормально",
            "작동불량": "Неисправна",
            "소음": "Шум",
            "작동양호": "Работает хорошо",
        }

        def translate(value):
            return translations.get(value, value)

        # Проверка состояния узлов
        inners = json_response.get("inners", [])
        nodes_status = {}

        for inner in inners:
            for child in inner.get("children", []):
                type_code = child.get("type", {}).get("code", "")
                status_type = child.get("statusType")
                status = (
                    translate(status_type.get("title", "Не указано"))
                    if status_type
                    else "Не указано"
                )

                nodes_status[type_code] = status

        output = (
            f"🚗 <b>Основная информация об автомобиле</b>\n"
            f"	•	ID автомобиля: {vehicle_id}\n"
            f"	•	Год выпуска: {model_year}\n"
            f"	•	Дата первой регистрации: {first_registration_date}\n"
            f"	•	Дата регистрации в системе: {registration_date}\n"
            f"	•	VIN: {vin}\n"
            f"	•	Пробег: {mileage}\n"
            f"	•	Тип трансмиссии: {translate(transmission)} ({transmission})\n"
            f"	•	Тип двигателя: {motor_type}\n"
            f"	•	Состояние автомобиля: {translate(car_state)} ({car_state})\n"
            f"	•	Цвет: {translate(color)} ({color})\n"
            f"	•	Тюнинг: {tuning}\n"
            f"	•	Автомобиль попадал в ДТП: {accident}\n"
            f"	•	Были ли простые ремонты: {simple_repair}\n"
            f"	•	Затопление: {waterlog}\n"
            f"\n⸻\n\n"
            f"⚙️ <b>Проверка основных узлов</b>\n"
            f"	•	Двигатель: ✅ {nodes_status.get('s001', 'Не указано')}\n"
            f"	•	Трансмиссия: ✅ {nodes_status.get('s002', 'Не указано')}\n"
            f"	•	Работа двигателя на холостом ходу: ✅ {nodes_status.get('s003', 'Не указано')}\n"
            f"	•	Утечка масла двигателя: {'❌ Нет' if nodes_status.get('s004', '없음') == 'Нет' else '⚠️ Да'} ({nodes_status.get('s004', 'Не указано')})\n"
            f"	•	Уровень масла в двигателе: ✅ {nodes_status.get('s005', 'Не указано')}\n"
            f"	•	Утечка охлаждающей жидкости: {'❌ Нет' if nodes_status.get('s006', '없음') == 'Нет' else '⚠️ Да'} ({nodes_status.get('s006', 'Не указано')})\n"
            f"	•	Уровень охлаждающей жидкости: ✅ {nodes_status.get('s007', 'Не указано')}\n"
            f"	•	Система подачи топлива: ✅ {nodes_status.get('s008', 'Не указано')}\n"
            f"	•	Автоматическая коробка передач: ✅ {nodes_status.get('s009', 'Не указано')}\n"
            f"	•	Утечка масла в АКПП: {'❌ Нет' if nodes_status.get('s010', '없음') == 'Нет' else '⚠️ Да'} ({nodes_status.get('s010', 'Не указано')})\n"
            f"	•	Работа АКПП на холостом ходу: ✅ {nodes_status.get('s011', 'Не указано')}\n"
            f"	•	Система сцепления: ✅ {nodes_status.get('s012', 'Не указано')}\n"
            f"	•	Карданный вал и подшипники: ✅ {nodes_status.get('s013', 'Не указано')}\n"
            f"	•	Редуктор: ✅ {nodes_status.get('s014', 'Не указано')}\n"
        )

        return output

    except requests.RequestException as e:
        return f"❌ Ошибка при получении данных: {e}"


# Вопрос/Ответ
@bot.message_handler(func=lambda msg: msg.text == "Вопрос/Ответ")
def handle_faq(message):
    markup = types.InlineKeyboardMarkup()
    for topic in faq_data:
        markup.add(
            types.InlineKeyboardButton(topic, callback_data=f"faq_topic:{topic}")
        )
    bot.send_message(message.chat.id, "Выберите тему:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "faq_back")
def handle_faq_back(call):
    markup = types.InlineKeyboardMarkup()
    for topic in faq_data.keys():
        markup.add(
            types.InlineKeyboardButton(topic, callback_data=f"faq_topic:{topic}")
        )

    bot.edit_message_text(
        "📚 *Выберите тему из списка:*",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("faq_topic:"))
def handle_faq_topic(call):
    topic = call.data.split(":")[1]
    questions = faq_data.get(topic, [])

    markup = types.InlineKeyboardMarkup()
    for i, q in enumerate(questions):
        markup.add(
            types.InlineKeyboardButton(
                q["question"], callback_data=f"faq_question:{topic}:{i}"
            )
        )

    # Добавляем кнопку "Вернуться к темам"
    markup.add(
        types.InlineKeyboardButton("🔙 Вернуться к темам", callback_data="faq_back")
    )

    bot.edit_message_text(
        f"🔹 *{topic}* — выберите вопрос:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("faq_question:"))
def handle_faq_question(call):
    _, topic, index = call.data.split(":")
    index = int(index)
    question_data = faq_data[topic][index]

    text = f"❓ *{question_data['question']}*\n\n{question_data['answer']}"
    bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад к вопросам", callback_data=f"faq_topic:{topic}"
        )
    )
    bot.send_message(
        call.message.chat.id, text="Выберите действие", reply_markup=markup
    )


# Callback query handler
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    global car_data, car_id_external, usd_rate

    if call.data.startswith("detail"):
        print_message("[ЗАПРОС] ДЕТАЛИЗАЦИЯ РАСЧËТА")

        detail_message = (
            f"1️⃣ Стоимость автомобиля:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
            f"2️⃣ Комиссия Encar:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['encar_fee_krw'])}</b> | <b>{format_number(car_data['encar_fee_rub'])} ₽</b>\n\n"
            f"3️⃣ Доставка до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['delivery_fee_krw'])}</b> | <b>{format_number(car_data['delivery_fee_rub'])} ₽</b>\n\n"
            f"4️⃣ Единая таможенная ставка:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
            f"5️⃣ Таможенное оформление:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
            f"6️⃣ Утилизационный сбор:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n"
            f"7️⃣ Услуги брокера:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['broker_fee_krw'])}</b> | <b>{format_number(car_data['broker_fee_rub'])} ₽</b>\n\n"
            f"🟰 Итого под ключ: \n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
            f"🚚 <b>Доставку до вашего города уточняйте у менеджеров:</b>\n"
            f"▪️ +82-10-2889-2307 (Олег)\n"
            f"▪️ +82-10-5812-2515 (Дмитрий)\n"
            # f"▪️ +82 10-5128-8082 (Александр)\n\n"
        )

        # Inline buttons for further actions
        keyboard = types.InlineKeyboardMarkup()

        if call.data.startswith("detail_manual"):
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another_manual",
                )
            )
        else:
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )

        keyboard.add(
            types.InlineKeyboardButton("Главное меню", callback_data="main_menu")
        )

        bot.send_message(
            call.message.chat.id,
            detail_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    elif call.data == "technical_card":
        print_message("[ЗАПРОС] ТЕХНИЧЕСКАЯ ОТЧËТ ОБ АВТОМОБИЛЕ")

        technical_card_output = get_technical_card()

        bot.send_message(
            call.message.chat.id,
            "Запрашиваю отчёт по автомобилю. Пожалуйста подождите ⏳",
        )

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "Рассчитать стоимость другого автомобиля",
                callback_data="calculate_another",
            )
        )
        keyboard.add(
            types.InlineKeyboardButton("Главное меню", callback_data="main_menu")
        )
        bot.send_message(
            call.message.chat.id,
            technical_card_output,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    elif call.data == "technical_report":
        bot.send_message(
            call.message.chat.id,
            "Запрашиваю отчёт по ДТП. Пожалуйста подождите ⏳",
        )

        # Retrieve insurance information
        insurance_info = get_insurance_total()

        # Проверка на наличие ошибки
        if (
            insurance_info is None
            or "Нет данных" in insurance_info[0]
            or "Нет данных" in insurance_info[1]
        ):
            error_message = (
                "Не удалось получить данные о страховых выплатах. \n\n"
                f'<a href="https://fem.encar.com/cars/report/accident/{car_id_external}">🔗 Посмотреть страховую историю вручную 🔗</a>\n\n\n'
                f"<b>Найдите две строки:</b>\n\n"
                f"보험사고 이력 (내차 피해) - Выплаты по представленному автомобилю\n"
                f"보험사고 이력 (타차 가해) - Выплаты другим участникам ДТП"
            )

            # Inline buttons for further actions
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/KaMik_23"
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/KaMik_23"
                )
            )

            # Отправка сообщения об ошибке
            bot.send_message(
                call.message.chat.id,
                error_message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            current_car_insurance_payments = (
                "0" if len(insurance_info[0]) == 0 else insurance_info[0]
            )
            other_car_insurance_payments = (
                "0" if len(insurance_info[1]) == 0 else insurance_info[1]
            )

            # Construct the message for the technical report
            tech_report_message = (
                f"Страховые выплаты по представленному автомобилю: \n<b>{current_car_insurance_payments} ₩</b>\n\n"
                f"Страховые выплаты другим участникам ДТП: \n<b>{other_car_insurance_payments} ₩</b>\n\n"
                f'<a href="https://fem.encar.com/cars/report/inspect/{car_id_external}">🔗 Ссылка на схему повреждений кузовных элементов 🔗</a>'
            )

            # Inline buttons for further actions
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/KaMik_23"
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/KaMik_23"
                )
            )
            keyboard.add(
                types.InlineKeyboardButton("Главное меню", callback_data="main_menu")
            )

            bot.send_message(
                call.message.chat.id,
                tech_report_message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    elif call.data == "calculate_another":
        bot.send_message(
            call.message.chat.id,
            "Пожалуйста, введите ссылку на автомобиль с сайта (encar.com, kbchachacha.com, kcar.com)",
        )

    elif call.data == "calculate_another_manual":
        # Запрашиваем возраст автомобиля
        keyboard = types.ReplyKeyboardMarkup(
            resize_keyboard=True, one_time_keyboard=True
        )
        keyboard.add("До 3 лет", "От 3 до 5 лет")
        keyboard.add("От 5 до 7 лет", "Более 7 лет")
        keyboard.add("Главное меню")

        msg = bot.send_message(
            call.message.chat.id,
            "Выберите возраст автомобиля:",
            reply_markup=keyboard,
        )
        bot.register_next_step_handler(msg, process_car_age)

    elif call.data == "main_menu":
        bot.send_message(call.message.chat.id, "Главное меню", reply_markup=main_menu())

    elif call.data == "show_faq":
        show_faq(call.message)


def process_car_age(message):
    user_input = message.text.strip()

    # Проверяем ввод
    age_mapping = {
        "До 3 лет": "0-3",
        "От 3 до 5 лет": "3-5",
        "От 5 до 7 лет": "5-7",
        "Более 7 лет": "7-0",
    }

    if user_input == "Главное меню":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=main_menu())
        return

    elif user_input not in age_mapping:
        bot.send_message(message.chat.id, "Пожалуйста, выберите возраст из списка.")
        return

    # Сохраняем возраст авто
    user_data[message.chat.id] = {"car_age": age_mapping[user_input]}

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Главное меню"))

    # Запрашиваем объем двигателя
    bot.send_message(
        message.chat.id,
        "Введите объем двигателя в см³ (например, 1998):",
        reply_markup=markup,
    )
    bot.register_next_step_handler(message, process_engine_volume)


def process_engine_volume(message):
    user_input = message.text.strip()

    # Проверяем, что введено число
    if user_input == "Главное меню":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=main_menu())
        return
    elif not user_input.isdigit():
        bot.send_message(
            message.chat.id, "Пожалуйста, введите корректный объем двигателя в см³."
        )
        bot.register_next_step_handler(message, process_engine_volume)
        return

    # Сохраняем объем двигателя
    user_data[message.chat.id]["engine_volume"] = int(user_input)

    # Запрашиваем тип топлива
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Бензин"), types.KeyboardButton("Дизель"))
    markup.add(types.KeyboardButton("Главное меню"))

    bot.send_message(
        message.chat.id,
        "Выберите тип топлива:",
        reply_markup=markup,
    )
    bot.register_next_step_handler(message, process_fuel_type)


def process_fuel_type(message):
    user_input = message.text.strip()

    # Проверяем выбор типа топлива
    if user_input == "Главное меню":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=main_menu())
        return
    elif user_input not in ["Бензин", "Дизель"]:
        bot.send_message(message.chat.id, "Пожалуйста, выберите тип топлива из списка.")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("Бензин"), types.KeyboardButton("Дизель"))
        markup.add(types.KeyboardButton("Главное меню"))
        bot.send_message(
            message.chat.id,
            "Выберите тип топлива:",
            reply_markup=markup,
        )
        bot.register_next_step_handler(message, process_fuel_type)
        return

    # Сопоставляем тип топлива с числовым значением
    fuel_type_mapping = {
        "Бензин": 1,
        "Дизель": 2,
    }

    # Сохраняем тип топлива
    user_data[message.chat.id]["fuel_type"] = fuel_type_mapping[user_input]

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Главное меню"))

    # Запрашиваем стоимость авто
    bot.send_message(
        message.chat.id,
        "Введите стоимость автомобиля в корейских вонах (например, 15000000):",
        reply_markup=markup,
    )
    bot.register_next_step_handler(message, process_car_price)


def process_car_price(message):
    global usd_to_krw_rate, usd_to_rub_rate

    # Получаем актуальный курс валют
    get_currency_rates()
    get_rub_to_krw_rate()
    get_usdt_to_krw_rate()

    user_input = message.text.strip()

    # Проверяем, что введено число
    if user_input == "Главное меню":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=main_menu())
        return
    elif not user_input.isdigit():
        bot.send_message(
            message.chat.id,
            "Пожалуйста, введите корректную стоимость автомобиля в вонах.",
        )
        bot.register_next_step_handler(message, process_car_price)
        return

    # Сохраняем стоимость автомобиля
    user_data[message.chat.id]["car_price_krw"] = int(user_input)

    # Извлекаем данные пользователя
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}

    if "car_age" not in user_data[message.chat.id]:
        bot.send_message(message.chat.id, "Произошла ошибка, попробуйте снова.")
        return  # Прерываем выполнение, если возраст не установлен

    age_group = user_data[message.chat.id]["car_age"]
    engine_volume = user_data[message.chat.id]["engine_volume"]
    car_price_krw = user_data[message.chat.id]["car_price_krw"]
    engine_type = user_data[message.chat.id].get(
        "fuel_type", 1
    )  # По умолчанию бензин (1)

    # Получаем название типа топлива для вывода
    fuel_type_name = "Бензин" if engine_type == 1 else "Дизель"

    # Преобразуем возрастную группу в читаемый формат
    age_display = {
        "0-3": "До 3 лет",
        "3-5": "От 3 до 5 лет",
        "5-7": "От 5 до 7 лет",
        "7-0": "Более 7 лет",
    }.get(age_group, age_group)

    price_krw = car_price_krw
    price_rub = price_krw / rub_to_krw_rate

    response = get_customs_fees_manual(
        engine_volume,
        price_krw,
        age_group,
        engine_type=engine_type,
    )

    if response is None:
        bot.send_message(
            message.chat.id,
            "❌ Временная ошибка при расчете таможенных платежей. Сервис calcus.ru перегружен. Попробуйте через несколько минут.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    # Таможенный сбор
    customs_fee = clean_number(response["sbor"])
    customs_duty = clean_number(response["tax"])
    recycling_fee = clean_number(response["util"])

    # Расчет итоговой стоимости автомобиля в рублях
    total_cost = (
        price_rub  # Стоимость автомобиля
        + (440000 / rub_to_krw_rate)  # Комиссия Encar
        + (1300000 / rub_to_krw_rate)  # Доставка до Владивостока
        + customs_fee  # Таможенный сбор
        + customs_duty  # Таможенная пошлина
        + recycling_fee  # Утильсбор
        + 100000  # Услуги брокера
    )

    total_cost_krw = (
        price_krw  # Стоимость автомобиля
        + 440000  # Комиссия Encar
        + 1300000  # Доставка до Владивостока
        + (customs_fee * rub_to_krw_rate)  # Таможенный сбор
        + (customs_duty * rub_to_krw_rate)  # Таможенная пошлина
        + (recycling_fee * rub_to_krw_rate)  # Утильсбор
        + (100000 * rub_to_krw_rate)  # Услуги брокера
    )

    # Общая сумма под ключ до Владивостока
    car_data["total_cost_krw"] = total_cost_krw
    car_data["total_cost_rub"] = total_cost

    # Стоимость автомобиля
    car_data["car_price_krw"] = price_krw
    car_data["car_price_rub"] = price_rub

    # Комиссия Encar
    car_data["encar_fee_krw"] = 440000
    car_data["encar_fee_rub"] = 440000 / rub_to_krw_rate

    # Доставка до Владивостока
    car_data["delivery_fee_krw"] = 1300000
    car_data["delivery_fee_rub"] = 1300000 / rub_to_krw_rate

    # Расходы по РФ
    car_data["customs_duty_rub"] = customs_duty
    car_data["customs_duty_krw"] = customs_duty * rub_to_krw_rate

    car_data["customs_fee_rub"] = customs_fee
    car_data["customs_fee_krw"] = customs_fee * rub_to_krw_rate

    car_data["util_fee_rub"] = recycling_fee
    car_data["util_fee_krw"] = recycling_fee * rub_to_krw_rate

    car_data["broker_fee_rub"] = 100000
    car_data["broker_fee_krw"] = 100000 * rub_to_krw_rate

    # Формируем сообщение с расчетом стоимости
    result_message = (
        f"💰 Курс Рубля к Воне: <b>₩{rub_to_krw_rate:.2f}</b>\n\n"
        f"🚗 Параметры автомобиля:\n"
        f"▪️ Возраст: <b>{age_display}</b>\n"
        f"▪️ Объем двигателя: <b>{engine_volume} см³</b>\n"
        f"▪️ Тип топлива: <b>{fuel_type_name}</b>\n\n"
        f"1️⃣ Стоимость автомобиля:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
        f"2️⃣ Комиссия Encar:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['encar_fee_krw'])}</b> | <b>{format_number(car_data['encar_fee_rub'])} ₽</b>\n\n"
        f"3️⃣ Доставка до Владивостока:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['delivery_fee_krw'])}</b> | <b>{format_number(car_data['delivery_fee_rub'])} ₽</b>\n\n"
        f"4️⃣ Единая таможенная ставка:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
        f"5️⃣ Таможенное оформление:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
        f"6️⃣ Утилизационный сбор:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n"
        f"7️⃣ Брокерские услуги:\n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['broker_fee_krw'])}</b> | <b>{format_number(car_data['broker_fee_rub'])} ₽</b>\n\n"
        f"🟰 Итого под ключ: \n\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0<b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
        f"🚚 <b>Доставку до вашего города уточняйте у менеджеров:</b>\n"
        f"▪️ +82-10-2889-2307 (Олег)\n"
        f"▪️ +82-10-5812-2515 (Дмитрий)\n"
        # f"▪️ +82 10-5128-8082 (Александр)\n\n"
    )

    # Клавиатура с дальнейшими действиями
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Рассчитать другой автомобиль", callback_data="calculate_another_manual"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "👨‍💼 Связаться с менеджером (Олег)", url="https://t.me/KaMik_23"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "👨‍💼 Связаться с менеджером (Дима)", url="https://t.me/Pako_000"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )

    # Отправляем сообщение пользователю
    bot.send_message(
        message.chat.id,
        result_message,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    # Очищаем данные пользователя после расчета
    del user_data[message.chat.id]


# Обработчик ручного ввода HP (должен быть перед catch-all handler)
@bot.message_handler(func=lambda msg: msg.from_user.id in pending_hp_calculations and pending_hp_calculations.get(msg.from_user.id, {}).get("waiting_manual_input"))
def handle_manual_hp_input(message):
    """Обработчик ручного ввода HP от пользователя"""
    user_id = message.from_user.id

    if user_id not in pending_hp_calculations:
        return

    text = message.text.strip()

    # Проверяем, что введено число
    try:
        hp = int(text)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ Пожалуйста, введите число (мощность в л.с.).\n"
            "Например: 150"
        )
        return

    # Проверяем диапазон
    if hp < 50 or hp > 1000:
        bot.send_message(
            message.chat.id,
            "⚠️ Мощность должна быть от 50 до 1000 л.с.\n"
            "Пожалуйста, введите корректное значение."
        )
        return

    # HP валидный - продолжаем расчёт
    pending_hp_calculations[user_id]["waiting_manual_input"] = False
    complete_calculation_with_hp(user_id, hp, message.chat.id)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_message = message.text.strip()

    # Проверяем нажатие кнопки "Рассчитать автомобиль"
    if user_message == CALCULATE_CAR_TEXT:
        # Сохраняем данные пользователя в базу данных
        user_info = {
            "id": message.chat.id,
            "first_name": message.from_user.first_name,
            "username": message.from_user.username,
            "timestamp": message.date,  # Unix timestamp
        }
        add_user(user_info)  # Функция для сохранения пользователя в базу

        bot.send_message(
            message.chat.id,
            "Пожалуйста, введите ссылку на автомобиль с одного из сайтов (encar.com, kbchachacha.com, kcar.com):",
        )

    elif user_message == "Ручной расчёт":
        # Запрашиваем возраст автомобиля
        keyboard = types.ReplyKeyboardMarkup(
            resize_keyboard=True, one_time_keyboard=True
        )
        keyboard.add("До 3 лет", "От 3 до 5 лет")
        keyboard.add("От 5 до 7 лет", "Более 7 лет")
        keyboard.add("Главное меню")

        bot.send_message(
            message.chat.id,
            "Выберите возраст автомобиля:",
            reply_markup=keyboard,
        )
        bot.register_next_step_handler(message, process_car_age)

    elif user_message == "Вопрос/Ответ":
        show_faq(message)

    elif re.match(
        r"^https?://(www|fem)\.encar\.com/.*|^https?://(www\.)?kbchachacha\.com/.*|^https?://m\.kbchachacha\.com/.*|^https?://(www|m)\.kcar\.com/.*",
        user_message,
    ):
        calculate_cost(user_message, message)

    elif user_message == "Написать менеджеру":
        managers_list = [
            {"name": "Олег ", "whatsapp": "https://wa.me/821028892307"},
            {"name": "Дмитрий ", "whatsapp": "https://wa.me/821058122515"},
            # {"name": "Александр", "whatsapp": "https://wa.me/821068766801"},
        ]

        # Формируем сообщение со списком менеджеров
        message_text = "Вы можете связаться с одним из наших менеджеров:\n\n"
        for manager in managers_list:
            message_text += f"[{manager['name']}]({manager['whatsapp']})\n"

        # Отправляем сообщение с использованием Markdown
        bot.send_message(message.chat.id, message_text, parse_mode="Markdown")

    elif user_message == "О нас":
        about_message = """
💎 CARAVAN TRADE - высококачественные услуги и гарантированная надежность в экспорте автомобилей из Южной Кореи.

▫️Работать с нами выгодно. Итоговая стоимость равна цене автомобиля на площадке, его транспортировки и таможенному сбору
▫️Предоставляем все необходимые документы на всех этапах работы. Мы не оставляем наших клиентов в неведении.
▫️Работаем исключительно по договору. Оплата оговоренных платежей по официальным инвойсам
▫️Для оценки привлекательности авто из Кореи, мы бесплатно предоставим вам подборку из предложений, отвечающих вашим критериям. Также проведем технический осмотр автомобиля.

Наши офисы:
🚩 Южная Корея, Incheon, Michuhol-gu Maesohol-ro 262, офис 8023
"""
        bot.send_message(message.chat.id, about_message)

    elif user_message == "Telegram-канал":
        channel_link = "https://t.me/crvntrade"
        bot.send_message(
            message.chat.id, f"Подписывайтесь на наш Telegram-канал: {channel_link}"
        )

    elif user_message == "Instagram":
        instagram_link = "https://www.instagram.com/crvn.trade/"
        bot.send_message(
            message.chat.id,
            f"Instagram компании Caravan Trade: {instagram_link}",
        )

    elif user_message == "Tik-Tok":
        tiktok_link = "https://www.tiktok.com/@crvn.trade"
        bot.send_message(
            message.chat.id, f"TikTok профиль компании Caravan Trade: {tiktok_link}"
        )

    else:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, введите ссылку на автомобиль с сайта (encar.com, kbchachacha.com, kcar.com)",
        )


# Run the bot
if __name__ == "__main__":
    create_tables()
    # set_bot_commands()

    # Обновляем курс каждые 12 часов
    scheduler = BackgroundScheduler()
    scheduler.add_job(get_usdt_to_krw_rate, "interval", hours=12)
    scheduler.add_job(get_currency_rates, "interval", minutes=5)
    scheduler.start()

    bot.polling(non_stop=True)
