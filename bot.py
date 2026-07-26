# ============================================================
# TakemiX Shop Bot v1.5
# + Integrity Hash check
# + HWID Reset Count (1 user reset + unlimited admin)
# + resethashall (mass reset)
# ============================================================

import telebot
from telebot import types
from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import string
import json
import os
from datetime import datetime, timedelta
import threading
import time

# ============================================================
# КОНФИГ
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8881951544:AAGUUpJeJXcv6kE__YecGUTTuwRs8frMgB8")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8607868320"))
SHEET_ID = os.environ.get("SHEET_ID", "1VJt5zaXjfz_XF6TWVeBpn-oZGq7qhY41jKaDkSbe_LI")
CREDENTIALS_FILE = "credentials.json"
SETTINGS_FILE = "settings.json"

API_SECRET = os.environ.get("API_SECRET", "TakemiX_S3cr3t_2026_ChangeMe")
API_PORT = int(os.environ.get("PORT", 5000))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1003916624439"))

# ============================================================
# НАСТРОЙКИ
# ============================================================

DEFAULT_SETTINGS = {
    "prices": {"7": 300, "30": 500, "forever": 800},
    "payment": {
        "bank": "Сбербанк",
        "card": "1234 5678 9012 3456",
        "name": "Иван И.",
        "extra": "После оплаты пришли скрин чека сюда 📸"
    },
    "killswitch": False
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                return data
        except:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

settings = load_settings()

def build_payment_info():
    p = settings.get("payment", DEFAULT_SETTINGS["payment"])
    return (
        f"💳 Реквизиты для оплаты:\n\n"
        f"Банк: {p['bank']}\n"
        f"Карта: {p['card']}\n"
        f"Получатель: {p['name']}\n\n"
        f"{p['extra']}"
    )

# ============================================================
# GOOGLE SHEETS
# ============================================================

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

def get_sheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def read_all_keys():
    sheet = get_sheet()
    rows = sheet.get_all_records()
    result = []
    for i, row in enumerate(rows):
        # Счётчик сбросов HWID (по умолчанию 0)
        reset_count_raw = str(row.get("HWID_RESET_COUNT", "0")).strip()
        try:
            reset_count = int(reset_count_raw) if reset_count_raw else 0
        except:
            reset_count = 0

        result.append({
            "KEY": str(row.get("KEY", "")).strip(),
            "HWID": str(row.get("HWID", "")).strip(),
            "EXPIRES": str(row.get("EXPIRES", "")).strip(),
            "STATUS": str(row.get("STATUS", "")).strip(),
            "CREATED": str(row.get("CREATED", "")).strip(),
            "INTEGRITY_HASH": str(row.get("INTEGRITY_HASH", "")).strip(),
            "HWID_RESET_COUNT": reset_count,
            "ROW": i + 2
        })
    return result

def find_key(key_value):
    key_value = key_value.strip()
    for row in read_all_keys():
        if row["KEY"] == key_value:
            return row
    return None

def add_new_key(key, expires, status="active"):
    sheet = get_sheet()
    created = datetime.now().strftime("%Y-%m-%d")
    sheet.append_row([key, "", expires, status, created, "", "0"])

def update_hwid(key, hwid):
    row_data = find_key(key)
    if not row_data:
        return False
    sheet = get_sheet()
    sheet.update_cell(row_data["ROW"], 2, hwid)
    return True

def update_status(key, status):
    row_data = find_key(key)
    if not row_data:
        return False
    sheet = get_sheet()
    sheet.update_cell(row_data["ROW"], 4, status)
    return True

def update_expires(key, new_expires):
    row_data = find_key(key)
    if not row_data:
        return False
    sheet = get_sheet()
    sheet.update_cell(row_data["ROW"], 3, new_expires)
    return True

def update_integrity_hash(key, ihash):
    row_data = find_key(key)
    if not row_data:
        return False
    sheet = get_sheet()
    sheet.update_cell(row_data["ROW"], 6, ihash)
    return True

def update_reset_count(key, count):
    row_data = find_key(key)
    if not row_data:
        return False
    sheet = get_sheet()
    sheet.update_cell(row_data["ROW"], 7, str(count))
    return True

# ============================================================
# ГЕНЕРАЦИЯ КЛЮЧЕЙ
# ============================================================

def generate_key():
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return "TAKEMI-" + "-".join(parts)

def calc_expires(days):
    if str(days).lower() == "forever":
        return "forever"
    try:
        n = int(days)
        return (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return "forever"

# ============================================================
# BOT INIT
# ============================================================

bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}
pending_payments = {}

def is_admin(user_id):
    return int(user_id) == ADMIN_ID

def create_one_time_invite():
    try:
        expire_time = int((datetime.now() + timedelta(hours=24)).timestamp())
        invite = bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=expire_time,
            name=f"Auto-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        return invite.invite_link
    except Exception as e:
        print(f"[ERROR] create_one_time_invite: {e}")
        return None

# ============================================================
# ЮЗЕРСКИЕ КОМАНДЫ
# ============================================================

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    p = settings["prices"]
    text = (
        "👋 Привет! Я бот TakemiX Hack.\n\n"
        "⏰ Работаю с 11:00 до 01:00 МСК\n\n"
        "💰 Тарифы:\n"
        f"🔹 7 дней   — {p['7']}₽\n"
        f"🔹 30 дней  — {p['30']}₽\n"
        f"🔹 Навсегда — {p['forever']}₽\n\n"
        "📋 Команды:\n"
        "/buy — Купить ключ\n"
        "/mykey — Инфо о моём ключе\n"
        "/resetmyhwid — Сбросить HWID (1 раз)\n"
        "/help — Помощь"
    )
    bot.send_message(msg.chat.id, text)

@bot.message_handler(commands=["help"])
def cmd_help(msg):
    text = (
        "🆘 Помощь\n\n"
        "1️⃣ Купить ключ:\n"
        "   /buy → выбери тариф → оплати → пришли скрин\n\n"
        "2️⃣ Активация:\n"
        "   Запусти чит → введи ключ прямо в чите\n"
        "   Чит АВТОМАТИЧЕСКИ привяжет HWID!\n\n"
        "3️⃣ Проверка ключа:\n"
        "   /mykey_check КЛЮЧ\n\n"
        "4️⃣ Сменил ПК?\n"
        "   /resetmyhwid КЛЮЧ (можно только 1 раз!)\n"
        "   Дальше — только через @xxTAKEMIxx\n\n"
        "❓ Вопросы: @xxTAKEMIxx"
    )
    bot.send_message(msg.chat.id, text)

@bot.message_handler(commands=["buy"])
def cmd_buy(msg):
    p = settings["prices"]
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"7 дней — {p['7']}₽", callback_data="buy_7"),
        types.InlineKeyboardButton(f"30 дней — {p['30']}₽", callback_data="buy_30"),
        types.InlineKeyboardButton(f"Навсегда — {p['forever']}₽", callback_data="buy_forever")
    )
    bot.send_message(msg.chat.id, "💰 Выбери тариф:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_buy(call):
    tariff = call.data.replace("buy_", "")
    user_id = call.from_user.id
    price = settings["prices"].get(tariff, "?")
    tariff_names = {"7": "7 дней", "30": "30 дней", "forever": "Навсегда"}
    tariff_name = tariff_names.get(tariff, tariff)

    text = (
        f"✅ Ты выбрал: {tariff_name} ({price}₽)\n\n"
        f"{build_payment_info()}\n\n"
        "После оплаты пришли сюда 📸 скрин чека."
    )
    bot.send_message(call.message.chat.id, text)
    user_state[user_id] = {"action": "waiting_check", "tariff": tariff}
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["photo"])
def handle_photo(msg):
    user_id = msg.from_user.id
    state = user_state.get(user_id)
    if not state or state.get("action") != "waiting_check":
        return

    tariff = state["tariff"]
    price = settings["prices"].get(tariff, "?")
    tariff_names = {"7": "7 дней", "30": "30 дней", "forever": "Навсегда"}
    tariff_name = tariff_names.get(tariff, tariff)

    pending_payments[user_id] = {
        "tariff": tariff,
        "username": msg.from_user.username or "no_username",
        "first_name": msg.from_user.first_name or "",
        "check_file_id": msg.photo[-1].file_id
    }
    user_state.pop(user_id, None)

    bot.send_message(msg.chat.id, "✅ Чек получен! Ожидай подтверждения.")

    admin_text = (
        "💰 <b>НОВАЯ ОПЛАТА</b>\n\n"
        f"От: @{pending_payments[user_id]['username']}\n"
        f"ID: <code>{user_id}</code>\n"
        f"Тариф: <b>{tariff_name}</b> ({price}₽)\n\n"
        f"Подтвердить: /approve {user_id}\n"
        f"Отклонить: /reject {user_id}"
    )
    bot.send_photo(ADMIN_ID, msg.photo[-1].file_id, caption=admin_text, parse_mode="HTML")

@bot.message_handler(commands=["mykey_check"])
def cmd_mykey_check(msg):
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "❌ Формат: /mykey_check КЛЮЧ")
        return
    key = parts[1].strip().upper()
    try:
        row = find_key(key)
        if not row:
            bot.send_message(msg.chat.id, "❌ Ключ не найден.")
            return
        text = (
            f"🔑 Информация о ключе\n\n"
            f"Ключ: <code>{row['KEY']}</code>\n"
            f"HWID: <code>{row['HWID'] or 'не привязан'}</code>\n"
            f"Срок: {row['EXPIRES']}\n"
            f"Статус: {row['STATUS']}\n"
            f"Сбросов HWID: {row['HWID_RESET_COUNT']}/1\n"
            f"Создан: {row['CREATED']}"
        )
        bot.send_message(msg.chat.id, text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка: {e}")

@bot.message_handler(commands=["mykey"])
def cmd_mykey(msg):
    bot.send_message(msg.chat.id, "🔑 Проверка: /mykey_check КЛЮЧ")

@bot.message_handler(commands=["support"])
def cmd_support(msg):
    bot.send_message(msg.chat.id, "🆘 Пиши: @xxTAKEMIxx")

# ============================================================
# ЮЗЕРСКАЯ КОМАНДА СБРОСА HWID (1 раз в жизни)
# ============================================================

@bot.message_handler(commands=["resetmyhwid"])
def cmd_resetmyhwid(msg):
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(
            msg.chat.id,
            "🔄 <b>Сброс HWID</b>\n\n"
            "Формат: <code>/resetmyhwid КЛЮЧ</code>\n\n"
            "⚠️ Можно использовать <b>только 1 раз в жизни</b>!\n"
            "Если сменишь ПК ещё раз — обратись к @xxTAKEMIxx",
            parse_mode="HTML"
        )
        return

    key = parts[1].strip().upper()
    try:
        row = find_key(key)
        if not row:
            bot.send_message(msg.chat.id, "❌ Ключ не найден.")
            return

        if row["STATUS"].lower() == "banned":
            bot.send_message(msg.chat.id, "🚫 Этот ключ забанен.")
            return

        # Проверка счётчика
        reset_count = row["HWID_RESET_COUNT"]
        if reset_count >= 1:
            bot.send_message(
                msg.chat.id,
                f"❌ <b>Лимит сбросов исчерпан!</b>\n\n"
                f"Ты уже использовал сброс HWID для этого ключа.\n"
                f"Обратись к @xxTAKEMIxx для дополнительного сброса.",
                parse_mode="HTML"
            )
            return

        # Проверка что HWID вообще был привязан
        if not row["HWID"]:
            bot.send_message(msg.chat.id, "ℹ️ HWID ещё не привязан — сбрасывать нечего.")
            return

        # Сброс HWID + увеличение счётчика
        update_hwid(key, "")
        update_reset_count(key, reset_count + 1)

        bot.send_message(
            msg.chat.id,
            f"✅ <b>HWID сброшен!</b>\n\n"
            f"Ключ: <code>{key}</code>\n"
            f"Сбросов использовано: <b>1/1</b>\n\n"
            f"Теперь можешь запустить чит на новом ПК.\n"
            f"⚠️ Больше сбросить самому не получится!",
            parse_mode="HTML"
        )

        # Уведомление админу
        try:
            bot.send_message(
                ADMIN_ID,
                f"🔄 ЮЗЕР СБРОСИЛ HWID\n\n"
                f"От: @{msg.from_user.username or 'no_username'} (ID: {msg.from_user.id})\n"
                f"Ключ: <code>{key}</code>\n"
                f"Старый HWID: <code>{row['HWID']}</code>\n"
                f"Сбросов: 1/1",
                parse_mode="HTML"
            )
        except:
            pass

    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка: {e}")# ============================================================
# АДМИНСКИЕ КОМАНДЫ (ключи)
# ============================================================

@bot.message_handler(commands=["genkey"])
def cmd_genkey(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Формат: /genkey <срок>")
        return
    days = parts[1].strip().lower()
    key = generate_key()
    expires = calc_expires(days)
    try:
        add_new_key(key, expires)
        bot.send_message(msg.chat.id, f"✅ Ключ создан!\n\nКлюч: <code>{key}</code>\nСрок: {expires}", parse_mode="HTML")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка: {e}")

@bot.message_handler(commands=["approve"])
def cmd_approve(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Формат: /approve <user_id>")
        return
    try:
        target_id = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "❌ user_id должен быть числом")
        return

    payment = pending_payments.get(target_id)
    if not payment:
        bot.send_message(msg.chat.id, "❌ Нет ожидающей оплаты")
        return

    tariff = payment["tariff"]
    key = generate_key()
    expires = calc_expires(tariff)
    try:
        add_new_key(key, expires)
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка: {e}")
        return

    tariff_names = {"7": "7 дней", "30": "30 дней", "forever": "Навсегда"}
    tariff_name = tariff_names.get(tariff, tariff)

    invite_link = create_one_time_invite()

    try:
        message_text = (
            f"🎉 Оплата подтверждена!\n\n"
            f"🔑 Твой ключ: <code>{key}</code>\n"
            f"📅 Тариф: <b>{tariff_name}</b>\n"
            f"⏰ Срок: {expires}\n\n"
        )

        if invite_link:
            message_text += (
                f"📥 Скачай программу тут:\n{invite_link}\n\n"
                f"⚠️ <b>Ссылка одноразовая</b> — работает только для тебя!\n"
                f"⏱ Действует 24 часа.\n\n"
            )
        else:
            message_text += "⚠️ Ссылка на канал не создалась. Напиши @xxTAKEMIxx\n\n"

        message_text += (
            f"📝 Как использовать:\n"
            f"1. Перейди по ссылке → вступи в канал\n"
            f"2. Скачай <b>TakemiX.exe</b>\n"
            f"3. Запусти чит → введи ключ\n"
            f"4. HWID привяжется автоматически ✅\n\n"
            f"ℹ️ Если сменишь ПК — можешь сбросить HWID <b>1 раз</b>\n"
            f"командой /resetmyhwid"
        )

        bot.send_message(target_id, message_text, parse_mode="HTML", disable_web_page_preview=True)

        bot.send_message(
            msg.chat.id,
            f"✅ Ключ + ссылка отправлены юзеру {target_id}\n\n"
            f"Ключ: <code>{key}</code>\n"
            f"Ссылка: {invite_link or 'не создалась'}",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Не отправлено: {e}\nКлюч: {key}")

    pending_payments.pop(target_id, None)

@bot.message_handler(commands=["reject"])
def cmd_reject(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        return
    try:
        target_id = int(parts[1])
    except:
        return
    if target_id in pending_payments:
        try:
            bot.send_message(target_id, "❌ Оплата не подтверждена. Свяжись @xxTAKEMIxx")
        except:
            pass
        pending_payments.pop(target_id, None)
        bot.send_message(msg.chat.id, "✅ Отклонено")

@bot.message_handler(commands=["ban"])
def cmd_ban(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        return
    key = parts[1].strip().upper()
    if update_status(key, "banned"):
        bot.send_message(msg.chat.id, f"✅ {key} забанен")
    else:
        bot.send_message(msg.chat.id, "❌ Не найден")

@bot.message_handler(commands=["unban"])
def cmd_unban(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        return
    key = parts[1].strip().upper()
    if update_status(key, "active"):
        bot.send_message(msg.chat.id, f"✅ {key} разбанен")

# АДМИНСКИЙ СБРОС HWID (без ограничений, счётчик НЕ сбрасывается)
@bot.message_handler(commands=["resethwid"])
def cmd_resethwid(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Формат: /resethwid КЛЮЧ")
        return
    key = parts[1].strip().upper()
    if update_hwid(key, ""):
        bot.send_message(msg.chat.id, f"✅ HWID сброшен для {key}\n(счётчик юзера НЕ сброшен)")
    else:
        bot.send_message(msg.chat.id, "❌ Не найден")

# АДМИНСКИЙ СБРОС HWID + ОБНУЛЕНИЕ СЧЁТЧИКА
@bot.message_handler(commands=["resethwidforce"])
def cmd_resethwidforce(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(
            msg.chat.id,
            "Формат: /resethwidforce КЛЮЧ\n\n"
            "Сбросит HWID И обнулит счётчик юзера.\n"
            "Юзер снова сможет использовать /resetmyhwid."
        )
        return
    key = parts[1].strip().upper()
    try:
        if update_hwid(key, "") and update_reset_count(key, 0):
            bot.send_message(
                msg.chat.id,
                f"✅ HWID сброшен для {key}\n"
                f"✅ Счётчик обнулён (0/1)\n\n"
                f"Юзер снова может использовать /resetmyhwid"
            )
        else:
            bot.send_message(msg.chat.id, "❌ Не найден")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ {e}")

# СБРОС INTEGRITY HASH (одному ключу)
@bot.message_handler(commands=["resethash"])
def cmd_resethash(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Формат: /resethash КЛЮЧ")
        return
    key = parts[1].strip().upper()
    if update_integrity_hash(key, ""):
        bot.send_message(msg.chat.id, f"✅ Integrity hash сброшен для {key}\n(при след. запуске сохранится новый)")
    else:
        bot.send_message(msg.chat.id, "❌ Ключ не найден")

# СБРОС INTEGRITY HASH ВСЕМ (для обновления версии чита)
@bot.message_handler(commands=["resethashall"])
def cmd_resethashall(msg):
    if not is_admin(msg.from_user.id):
        return

    parts = msg.text.split()
    if len(parts) != 2 or parts[1].lower() != "confirm":
        bot.send_message(
            msg.chat.id,
            "⚠️ <b>Сбросить хеш ВСЕМ ключам?</b>\n\n"
            "Это нужно при выпуске новой версии чита.\n"
            "Все юзеры получат новый эталонный хеш при следующем запуске.\n\n"
            "Для подтверждения напиши:\n"
            "<code>/resethashall confirm</code>",
            parse_mode="HTML"
        )
        return

    try:
        all_keys = read_all_keys()
        count = 0
        errors = 0

        for k in all_keys:
            if k["INTEGRITY_HASH"]:
                try:
                    update_integrity_hash(k["KEY"], "")
                    count += 1
                except:
                    errors += 1

        bot.send_message(
            msg.chat.id,
            f"✅ <b>Готово!</b>\n\n"
            f"Сброшено: <b>{count}</b> ключей\n"
            f"Ошибок: {errors}\n\n"
            f"Все юзеры получат новый эталонный хеш при следующем запуске чита.",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ Ошибка: {e}")

@bot.message_handler(commands=["stats"])
def cmd_stats(msg):
    if not is_admin(msg.from_user.id):
        return
    try:
        all_keys = read_all_keys()
        total = len(all_keys)
        active = sum(1 for k in all_keys if k["STATUS"].lower() == "active")
        banned = sum(1 for k in all_keys if k["STATUS"].lower() == "banned")
        with_hwid = sum(1 for k in all_keys if k["HWID"])
        with_hash = sum(1 for k in all_keys if k["INTEGRITY_HASH"])
        used_reset = sum(1 for k in all_keys if k["HWID_RESET_COUNT"] >= 1)
        ks = "🔴 ВКЛ" if settings.get("killswitch", False) else "🟢 ВЫКЛ"
        bot.send_message(
            msg.chat.id,
            f"📊 Статистика:\n\n"
            f"Всего: {total}\n"
            f"Активных: {active}\n"
            f"Забаненных: {banned}\n"
            f"С HWID: {with_hwid}\n"
            f"С Hash: {with_hash}\n"
            f"Использовали сброс: {used_reset}\n"
            f"Ждут оплаты: {len(pending_payments)}\n\n"
            f"🔴 KillSwitch: {ks}"
        )
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ {e}")

@bot.message_handler(commands=["list"])
def cmd_list(msg):
    if not is_admin(msg.from_user.id):
        return
    try:
        all_keys = read_all_keys()
        text = "🔑 Ключи:\n\n"
        for k in all_keys[-20:]:
            icon = "✅" if k["STATUS"].lower() == "active" else "🚫"
            hwid_display = k["HWID"][:20] if k["HWID"] else "не привязан"
            hash_display = "✓" if k["INTEGRITY_HASH"] else "✗"
            reset_display = f"{k['HWID_RESET_COUNT']}/1"
            text += f"{icon} <code>{k['KEY']}</code>\n"
            text += f"   HWID: {hwid_display} | Hash: {hash_display} | Reset: {reset_display}\n"
            text += f"   Срок: {k['EXPIRES']}\n\n"
        bot.send_message(msg.chat.id, text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(msg.chat.id, f"⚠️ {e}")

@bot.message_handler(commands=["setprice"])
def cmd_setprice(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) != 3:
        return
    tariff = parts[1].strip().lower()
    if tariff not in ("7", "30", "forever"):
        return
    try:
        price = int(parts[2])
    except:
        return
    settings["prices"][tariff] = price
    save_settings(settings)
    bot.send_message(msg.chat.id, f"✅ {tariff} = {price}₽")

@bot.message_handler(commands=["setname"])
def cmd_setname(msg):
    if not is_admin(msg.from_user.id):
        return
    new_name = msg.text.replace("/setname", "", 1).strip()
    if not new_name:
        return
    if "payment" not in settings:
        settings["payment"] = DEFAULT_SETTINGS["payment"].copy()
    settings["payment"]["name"] = new_name
    save_settings(settings)
    bot.send_message(msg.chat.id, f"✅ Получатель: {new_name}")

@bot.message_handler(commands=["setcard"])
def cmd_setcard(msg):
    if not is_admin(msg.from_user.id):
        return
    new_card = msg.text.replace("/setcard", "", 1).strip()
    if not new_card:
        return
    if "payment" not in settings:
        settings["payment"] = DEFAULT_SETTINGS["payment"].copy()
    settings["payment"]["card"] = new_card
    save_settings(settings)
    bot.send_message(msg.chat.id, f"✅ Карта: {new_card}")

@bot.message_handler(commands=["setbank"])
def cmd_setbank(msg):
    if not is_admin(msg.from_user.id):
        return
    new_bank = msg.text.replace("/setbank", "", 1).strip()
    if not new_bank:
        return
    if "payment" not in settings:
        settings["payment"] = DEFAULT_SETTINGS["payment"].copy()
    settings["payment"]["bank"] = new_bank
    save_settings(settings)
    bot.send_message(msg.chat.id, f"✅ Банк: {new_bank}")

@bot.message_handler(commands=["showpay"])
def cmd_showpay(msg):
    if not is_admin(msg.from_user.id):
        return
    bot.send_message(msg.chat.id, f"Текущие реквизиты:\n\n{build_payment_info()}")

@bot.message_handler(commands=["killswitch"])
def cmd_killswitch(msg):
    if not is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) == 1:
        status = settings.get("killswitch", False)
        status_text = "🔴 ВКЛЮЧЕН" if status else "🟢 ВЫКЛЮЧЕН"
        bot.send_message(msg.chat.id, f"KillSwitch: {status_text}\n\n/killswitch on|off")
        return
    action = parts[1].lower()
    if action == "on":
        settings["killswitch"] = True
        save_settings(settings)
        bot.send_message(msg.chat.id, "🔴 KILLSWITCH ВКЛ! Чит выключится у всех.")
    elif action == "off":
        settings["killswitch"] = False
        save_settings(settings)
        bot.send_message(msg.chat.id, "🟢 KillSwitch выключен.")

@bot.message_handler(commands=["testlink"])
def cmd_testlink(msg):
    if not is_admin(msg.from_user.id):
        return
    link = create_one_time_invite()
    if link:
        bot.send_message(msg.chat.id, f"✅ Тестовая ссылка:\n{link}", disable_web_page_preview=True)
    else:
        bot.send_message(msg.chat.id, "❌ Не удалось создать")

@bot.message_handler(commands=["adminhelp"])
def cmd_adminhelp(msg):
    if not is_admin(msg.from_user.id):
        return
    text = (
        "👑 Админские команды:\n\n"
        "🔑 Ключи:\n"
        "/genkey 7|30|forever — создать\n"
        "/ban КЛЮЧ — забанить\n"
        "/unban КЛЮЧ — разбанить\n\n"
        "🔄 HWID:\n"
        "/resethwid КЛЮЧ — сброс HWID (счётчик НЕ трогает)\n"
        "/resethwidforce КЛЮЧ — сброс HWID + обнулить счётчик\n\n"
        "🔐 Integrity Hash:\n"
        "/resethash КЛЮЧ — сброс для одного\n"
        "/resethashall confirm — сброс ВСЕМ (при обновлении чита)\n\n"
        "💰 Заказы:\n"
        "/approve USER_ID\n"
        "/reject USER_ID\n\n"
        "💳 Реквизиты:\n"
        "/setname /setcard /setbank /showpay\n\n"
        "⚙️ Цены:\n"
        "/setprice 7 350\n\n"
        "🔴 БЕЗОПАСНОСТЬ:\n"
        "/killswitch on|off\n\n"
        "📥 Канал:\n"
        "/testlink\n\n"
        "📊 Инфо:\n"
        "/stats /list"
    )
    bot.send_message(msg.chat.id, text)

# ============================================================
# HTTP API ДЛЯ ЧИТА
# ============================================================

app = Flask(__name__)

def check_auth(req):
    return req.headers.get("X-API-Secret", "") == API_SECRET

@app.route("/", methods=["GET"])
def api_root():
    return jsonify({"status": "ok", "service": "TakemiX API"})

@app.route("/api/activate", methods=["POST"])
def api_activate():
    if not check_auth(request):
        return jsonify({"status": "error", "message": "unauthorized"}), 403

    if settings.get("killswitch", False):
        return jsonify({"status": "error", "message": "killswitch"}), 403

    try:
        data = request.get_json()
        key = str(data.get("key", "")).strip().upper()
        hwid = str(data.get("hwid", "")).strip().upper()
        ihash = str(data.get("hash", "")).strip().upper()

        if not key or not hwid:
            return jsonify({"status": "error", "message": "missing_data"}), 400

        row = find_key(key)
        if not row:
            return jsonify({"status": "error", "message": "key_not_found"}), 404
        if row["STATUS"].lower() == "banned":
            return jsonify({"status": "error", "message": "key_banned"}), 403

        current_hwid = row["HWID"]
        if current_hwid and current_hwid != hwid:
            return jsonify({"status": "error", "message": "hwid_mismatch"}), 403

        if row["EXPIRES"].lower() != "forever":
            try:
                exp = datetime.strptime(row["EXPIRES"], "%Y-%m-%d %H:%M:%S")
                if exp < datetime.now():
                    return jsonify({"status": "error", "message": "expired"}), 403
            except:
                pass

        # Привязка HWID (если ещё не был)
        if not current_hwid:
            update_hwid(key, hwid)
            try:
                bot.send_message(ADMIN_ID, f"🔑 АВТО-АКТИВАЦИЯ\nКлюч: <code>{key}</code>\nHWID: <code>{hwid}</code>", parse_mode="HTML")
            except:
                pass

        # Сохранение integrity hash (если ещё не был)
        current_hash = row["INTEGRITY_HASH"]
        if ihash and not current_hash:
            update_integrity_hash(key, ihash)
            try:
                bot.send_message(ADMIN_ID, f"🔐 INTEGRITY HASH сохранён\nКлюч: <code>{key}</code>\nHash: <code>{ihash[:16]}...</code>", parse_mode="HTML")
            except:
                pass

        return jsonify({"status": "ok", "expires": row["EXPIRES"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/check", methods=["POST"])
def api_check():
    if not check_auth(request):
        return jsonify({"status": "error", "message": "unauthorized"}), 403

    if settings.get("killswitch", False):
        return jsonify({"status": "error", "message": "killswitch"}), 403

    try:
        data = request.get_json()
        key = str(data.get("key", "")).strip().upper()
        hwid = str(data.get("hwid", "")).strip().upper()
        ihash = str(data.get("hash", "")).strip().upper()

        row = find_key(key)
        if not row:
            return jsonify({"status": "error", "message": "key_not_found"}), 404
        if row["STATUS"].lower() == "banned":
            return jsonify({"status": "error", "message": "key_banned"}), 403
        if row["HWID"] and row["HWID"] != hwid:
            return jsonify({"status": "error", "message": "hwid_mismatch"}), 403

        # ПРОВЕРКА ЦЕЛОСТНОСТИ
        stored_hash = row["INTEGRITY_HASH"]
        if stored_hash and ihash and stored_hash != ihash:
            try:
                bot.send_message(ADMIN_ID, f"⚠️ INTEGRITY FAIL\nКлюч: <code>{key}</code>\nOжидался: <code>{stored_hash[:16]}...</code>\nПришёл: <code>{ihash[:16]}...</code>", parse_mode="HTML")
            except:
                pass
            return jsonify({"status": "error", "message": "integrity_fail"}), 403

        if row["EXPIRES"].lower() != "forever":
            try:
                exp = datetime.strptime(row["EXPIRES"], "%Y-%m-%d %H:%M:%S")
                if exp < datetime.now():
                    return jsonify({"status": "error", "message": "expired"}), 403
            except:
                pass

        return jsonify({"status": "ok", "expires": row["EXPIRES"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask():
    app.run(host="0.0.0.0", port=API_PORT, debug=False, use_reloader=False)

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("TakemiX Shop Bot v1.5")
    print("=" * 50)
    print(f"Bot Token: {BOT_TOKEN[:20]}...")
    print(f"Admin ID: {ADMIN_ID}")
    print(f"Sheet ID: {SHEET_ID}")
    print(f"Channel ID: {CHANNEL_ID}")
    print(f"API Port: {API_PORT}")
    print()

    try:
        print("Проверка Google Sheets...")
        sheet = get_sheet()
        print(f"✅ Подключение OK! Таблица: {sheet.title}")
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        input("Enter для выхода...")
        exit(1)

    print()
    print("🌐 Запуск Flask API...")
    api_thread = threading.Thread(target=run_flask, daemon=True)
    api_thread.start()
    time.sleep(1)
    print(f"✅ API работает на порту {API_PORT}")
    print()
    print("✅ Бот запущен!")
    print("=" * 50)

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        print("\nБот остановлен.")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        input("Enter для выхода...")