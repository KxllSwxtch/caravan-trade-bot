import time
import requests
import datetime
import locale
import random
from rate_limiter import calcus_rate_limiter, panauto_rate_limiter

PROXY_URL = "http://B01vby:GBno0x@45.118.250.2:8000"
proxies = {"http": PROXY_URL, "https": PROXY_URL}
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def format_number(number):
    return locale.format_string("%d", int(number), grouping=True)


def calculate_age(year, month):
    """
    Рассчитывает возрастную категорию автомобиля по классификации calcus.ru.

    :param year: Год выпуска автомобиля
    :param month: Месяц выпуска автомобиля
    :return: Возрастная категория ("0-3", "3-5", "5-7", "7-0")
    """
    # Убираем ведущий ноль у месяца, если он есть
    month = int(month.lstrip("0")) if isinstance(month, str) else int(month)

    current_date = datetime.datetime.now()
    car_date = datetime.datetime(year=int(year), month=month, day=1)

    age_in_months = (
        (current_date.year - car_date.year) * 12 + current_date.month - car_date.month
    )

    if age_in_months < 36:
        return "0-3"
    elif 36 <= age_in_months < 60:
        return "3-5"
    elif 60 <= age_in_months < 84:
        return "5-7"
    else:
        return "7-0"


def get_customs_fees_manual(engine_volume, car_price, car_age, engine_type=1, power=1):
    """
    Запрашивает расчёт таможенных платежей с сайта calcus.ru с rate limiting.
    :param engine_volume: Объём двигателя (куб. см)
    :param car_price: Цена авто в вонах
    :param car_age: Возрастная категория авто
    :param engine_type: Тип двигателя (1 - бензин, 2 - дизель, 3 - гибрид, 4 - электромобиль)
    :param power: Мощность двигателя в л.с. (по умолчанию 1 для обратной совместимости)
    :return: JSON с результатами расчёта или None при ошибке
    """
    def make_request():
        url = "https://calcus.ru/calculate/Customs"

        payload = {
            "owner": 1,  # Физлицо
            "age": car_age,  # Возрастная категория
            "engine": engine_type,  # Тип двигателя (по умолчанию 1 - бензин)
            "power": power,  # Лошадиные силы (реальное значение для расчёта утильсбора)
            "power_unit": 1,  # Тип мощности (1 - л.с.)
            "value": int(engine_volume),  # Объём двигателя
            "price": int(car_price),  # Цена авто в KRW
            "curr": "KRW",  # Валюта
        }

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://calcus.ru/",
            "Origin": "https://calcus.ru",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    # Use rate limiter with retry logic
    result = calcus_rate_limiter.execute_with_retry(make_request)

    if result is None:
        print(f"[CALCUS API ERROR] Failed to get customs fees after all retries for engine_volume={engine_volume}, car_price={car_price} (manual age={car_age})")
        print(f"[CALCUS API ERROR] This usually indicates the calcus.ru API is rate limiting us or temporarily unavailable")

    return result


def get_customs_fees(engine_volume, car_price, car_year, car_month, engine_type=1, power=1):
    """
    Запрашивает расчёт таможенных платежей с сайта calcus.ru с rate limiting.
    :param engine_volume: Объём двигателя (куб. см)
    :param car_price: Цена авто в вонах
    :param car_year: Год выпуска авто
    :param car_month: Месяц выпуска авто
    :param engine_type: Тип двигателя (1 - бензин, 2 - дизель, 3 - гибрид, 4 - электромобиль)
    :param power: Мощность двигателя в л.с. (по умолчанию 1 для обратной совместимости)
    :return: JSON с результатами расчёта или None при ошибке
    """
    def make_request():
        url = "https://calcus.ru/calculate/Customs"

        payload = {
            "owner": 1,  # Физлицо
            "age": calculate_age(car_year, car_month),  # Возрастная категория
            "engine": engine_type,  # Тип двигателя (по умолчанию 1 - бензин)
            "power": power,  # Лошадиные силы (реальное значение для расчёта утильсбора)
            "power_unit": 1,  # Тип мощности (1 - л.с.)
            "value": int(engine_volume),  # Объём двигателя
            "price": int(car_price),  # Цена авто в KRW
            "curr": "KRW",  # Валюта
        }

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://calcus.ru/",
            "Origin": "https://calcus.ru",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    # Use rate limiter with retry logic
    result = calcus_rate_limiter.execute_with_retry(make_request)

    if result is None:
        calculated_age = calculate_age(car_year, car_month)
        print(f"[CALCUS API ERROR] Failed to get customs fees after all retries for year={car_year}, month={car_month}, engine_volume={engine_volume} (calculated age={calculated_age})")
        print(f"[CALCUS API ERROR] This usually indicates the calcus.ru API is rate limiting us or temporarily unavailable")

    return result


def clean_number(value):
    """Очищает строку от пробелов и преобразует в число"""
    return int(float(value.replace(" ", "").replace(",", ".")))


def get_pan_auto_data(car_id):
    """
    Запрашивает данные об автомобиле с pan-auto.ru API.
    Возвращает данные о машине включая HP и предрассчитанные таможенные платежи.

    :param car_id: ID автомобиля на Encar (например, "40925064")
    :return: dict с данными или None если машина не найдена
    """
    def make_request():
        url = f"https://zefir.pan-auto.ru/api/cars/{car_id}/"

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "*/*",
            "Accept-Language": "en,ru;q=0.9",
            "Origin": "https://pan-auto.ru",
            "Referer": "https://pan-auto.ru/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

        response = requests.get(url, headers=headers, timeout=10)

        # Return None for 404 (car not found)
        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()

    try:
        result = panauto_rate_limiter.execute_with_retry(make_request)

        if result is None:
            print(f"[PAN-AUTO] Car {car_id} not found on pan-auto.ru")
            return None

        # Extract relevant data from response
        pan_auto_data = {
            "id": result.get("id"),
            "hp": result.get("hp"),
            "displacement": result.get("displacement"),
            "fuelType": result.get("fuelType"),
            "manufacturer": result.get("manufacturer", {}).get("translation", ""),
            "model": result.get("model", {}).get("translation", ""),
            "mileage": result.get("mileage"),
            "year": result.get("formYear"),
            "costs": result.get("costs", {}).get("RUB", {}),
            "carAge": result.get("carAge"),
            "badge": result.get("badge"),
            "badgeDetail": result.get("badgeDetail"),
        }

        print(f"[PAN-AUTO] Found car {car_id}: {pan_auto_data['manufacturer']} {pan_auto_data['model']}, HP: {pan_auto_data['hp']}")
        return pan_auto_data

    except Exception as e:
        print(f"[PAN-AUTO ERROR] Failed to get data for car {car_id}: {e}")
        return None


def generate_encar_photo_url(photo_path):
    """
    Формирует правильный URL для фотографий Encar.
    Пример результата: https://ci.encar.com/carpicture02/pic3902/39027097_006.jpg
    """

    base_url = "https://ci.encar.com"
    photo_url = f"{base_url}/{photo_path}"

    return photo_url
