import asyncio
import logging
import os
import json
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo, LabeledPrice, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "1780309782:kovRk5ZPCxt_frYbc7wfq2Rg5GPfMJ3ObcG"
ADMIN_USERNAMES = ["richie", "boros", "onewino"]
WEBAPP_URL = "https://onewin-bot-5x1w.onrender.com"
CHANNEL_URL = "https://catup.lol/onewinn"
NFT_PAYMENT_URL = "https://catup.lol/onewino"

# Курс подарков: звёзды за подарок (можно менять)
GIFT_STAR_RATE = 1  # 1 звезда = 1 балансный балл

db = Database("/tmp/casino.db")


class AdminStates(StatesGroup):
    waiting_add_balance_user = State()
    waiting_add_balance_amount = State()
    waiting_promo_name = State()
    waiting_promo_activations = State()
    waiting_promo_stars = State()
    waiting_broadcast_text = State()


class UserStates(StatesGroup):
    waiting_nft_confirm = State()
    waiting_nft_amount = State()
    waiting_activate_promo = State()
    waiting_withdraw_amount = State()


def is_admin(username: str) -> bool:
    if not username:
        return False
    return username.lower() in [a.lower() for a in ADMIN_USERNAMES]


async def get_main_keyboard(user_id: int):
    webapp_url = f"{WEBAPP_URL}?user_id={user_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Открыть казино", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit_menu")],
    ])
    return keyboard


async def start_handler(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username or "", user.first_name or "")
    balance = db.get_balance(user.id)

    text = (
        f"🎰 <b>1Win</b>\n\n"
        f"Добро пожаловать, {user.first_name}!\n"
        f"Баланс: <b>{balance} ⭐</b>\n\n"
        f"📢 Подпишись на наш канал: {CHANNEL_URL}\n\n"
        f"Выбери действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=await get_main_keyboard(user.id))


# ============================================================
# ПРИЁМ ПОДАРКОВ (Premium Gifts)
# ============================================================

async def gift_handler(message: types.Message, bot: Bot):
    """
    Обрабатывает входящие премиум-подарки (gift).
    Telegram присылает их как сервисное сообщение types.Message
    с полем message.gift (GiftInfo) начиная с Bot API 7.x
    """
    user = message.from_user
    if not user:
        return

    # Убедимся что пользователь есть в базе
    db.add_user(user.id, user.username or "", user.first_name or "")

    gift = message.gift  # GiftInfo object
    if gift is None:
        return

    # Звёздная стоимость подарка
    star_count = getattr(gift, "star_count", None) or getattr(gift.gift, "star_count", 0)

    if star_count and star_count > 0:
        credited = int(star_count * GIFT_STAR_RATE)
        db.add_balance(user.id, credited)
        new_balance = db.get_balance(user.id)

        # Уведомление отправителю
        try:
            await bot.send_message(
                user.id,
                f"🎁 <b>Подарок получен!</b>\n\n"
                f"За Premium-подарок тебе зачислено: <b>+{credited} ⭐</b>\n"
                f"Новый баланс: <b>{new_balance} ⭐</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify gift sender {user.id}: {e}")

        # Лог для админов
        logger.info(f"Gift from user {user.id} (@{user.username}): {star_count} stars → +{credited} balance")
    else:
        try:
            await bot.send_message(
                user.id,
                f"🎁 Подарок получен, но его стоимость не определена. "
                f"Обратись к администратору для зачисления.",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ============================================================
# DEPOSIT MENU
# ============================================================

async def deposit_menu_handler(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Пополнить звёздами", callback_data="deposit_stars")],
        [InlineKeyboardButton(text="🎁 Пополнить NFT подарком", callback_data="deposit_nft")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])
    await callback.message.edit_text(
        "💰 <b>Пополнение баланса</b>\n\nВыберите способ пополнения:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


async def deposit_stars_handler(callback: types.CallbackQuery, bot: Bot):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 ⭐ → 100 баланс", callback_data="pay_stars_100")],
        [InlineKeyboardButton(text="300 ⭐ → 300 баланс", callback_data="pay_stars_300")],
        [InlineKeyboardButton(text="500 ⭐ → 500 баланс", callback_data="pay_stars_500")],
        [InlineKeyboardButton(text="1000 ⭐ → 1000 баланс", callback_data="pay_stars_1000")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="deposit_menu")],
    ])
    await callback.message.edit_text(
        "⭐ <b>Пополнение звёздами</b>\n\nВыберите сумму:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


async def pay_stars_amount_handler(callback: types.CallbackQuery, bot: Bot):
    amount = int(callback.data.split("_")[2])
    user = callback.from_user

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=f"Пополнение {amount} ⭐",
        description=f"Зачисление {amount} звёзд на баланс в 1Win Casino",
        payload=f"deposit_{user.id}_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} ⭐", amount=amount)],
    )
    await callback.answer()


async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


async def successful_payment_handler(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    parts = payload.split("_")
    if len(parts) == 3 and parts[0] == "deposit":
        user_id = int(parts[1])
        amount = int(parts[2])
        db.add_balance(user_id, amount)
        new_balance = db.get_balance(user_id)
        await message.answer(
            f"✅ Оплата прошла успешно!\n"
            f"Зачислено: +{amount} ⭐\n"
            f"Баланс: {new_balance} ⭐"
        )


async def deposit_nft_handler(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я отправил NFT", callback_data="nft_sent")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="deposit_menu")],
    ])
    await callback.message.edit_text(
        f"🎁 <b>Пополнение NFT подарком</b>\n\n"
        f"1. Перейди по ссылке: {NFT_PAYMENT_URL}\n"
        f"2. Отправь NFT подарок администратору\n"
        f"3. Нажми кнопку <b>«Я отправил NFT»</b>\n\n"
        f"⚠️ После отправки администратор проверит и зачислит баланс.",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


async def nft_sent_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_nft_amount)
    await callback.message.edit_text("📝 Укажите сумму NFT подарка (в звёздах):\n(Напишите число)")
    await callback.answer()


async def nft_amount_handler(message: types.Message, state: FSMContext, bot: Bot):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return

    user = message.from_user
    request_id = db.create_nft_request(user.id, amount)
    await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_nft_{request_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_nft_{request_id}"),
        ]
    ])

    for admin_username in ADMIN_USERNAMES:
        try:
            admin_id = db.get_user_id_by_username(admin_username)
            if admin_id:
                await bot.send_message(
                    admin_id,
                    f"📬 <b>Новая заявка на пополнение NFT</b>\n\n"
                    f"Пользователь: @{user.username or user.first_name}\n"
                    f"ID: {user.id}\n"
                    f"Сумма: {amount} ⭐\n"
                    f"Заявка #{request_id}",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_username}: {e}")

    await message.answer(
        f"✅ Заявка отправлена админам.\n"
        f"Ожидай зачисления.\n\n"
        f"Заявка #{request_id} на {amount} ⭐"
    )


async def approve_nft_handler(callback: types.CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    request_id = int(callback.data.split("_")[2])
    request = db.get_nft_request(request_id)

    if not request:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return

    if request["status"] != "pending":
        await callback.answer("⚠️ Заявка уже обработана", show_alert=True)
        return

    user_id = request["user_id"]
    amount = request["amount"]
    db.update_nft_request_status(request_id, "approved")
    db.add_balance(user_id, amount)
    new_balance = db.get_balance(user_id)

    try:
        await bot.send_message(user_id, f"✅ Тебе зачислено +{amount}⭐\nБаланс: {new_balance}⭐")
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Одобрено</b> @{callback.from_user.username}",
        parse_mode="HTML"
    )
    await callback.answer("✅ Баланс зачислен")


async def reject_nft_handler(callback: types.CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    request_id = int(callback.data.split("_")[2])
    request = db.get_nft_request(request_id)

    if not request:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return

    db.update_nft_request_status(request_id, "rejected")

    try:
        await bot.send_message(request["user_id"], f"❌ Ваша заявка #{request_id} отклонена.")
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>Отклонено</b> @{callback.from_user.username}",
        parse_mode="HTML"
    )
    await callback.answer("❌ Заявка отклонена")


async def request_withdraw_handler(message: types.Message, state: FSMContext, bot: Bot):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введите корректную сумму.")
        return
    amount = int(message.text.strip())
    if amount < 1000:
        await message.answer("❌ Минимальная сумма вывода 1000★.")
        return
    user = message.from_user
    balance = db.get_balance(user.id)
    if balance < amount:
        await message.answer("❌ Недостаточно звёзд на балансе.")
        return
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_withdraw_{user.id}_{amount}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_withdraw_{user.id}_{amount}"),
        ]
    ])
    for admin_username in ADMIN_USERNAMES:
        try:
            admin_id = db.get_user_id_by_username(admin_username)
            if admin_id:
                await bot.send_message(
                    admin_id,
                    f"💸 <b>Запрос на вывод</b>\n\n"
                    f"👤 Имя: {user.first_name}\n"
                    f"🔗 Юзернейм: @{user.username}\n"
                    f"💰 Сумма: {amount}★\n"
                    f"💼 Баланс: {balance}★",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    await message.answer("✅ Заявка на вывод отправлена администратору. Ожидайте.")


async def approve_withdraw_handler(callback: types.CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return
    parts = callback.data.split("_")
    user_id = int(parts[2])
    amount = int(parts[3])
    if not db.deduct_balance(user_id, amount):
        await callback.message.edit_text("❌ Недостаточно средств у пользователя.")
        return
    await callback.message.edit_text(f"✅ Вывод {amount}★ подтверждён.")
    try:
        await bot.send_message(user_id, f"✅ Ваш вывод на {amount}★ подтверждён!")
    except:
        pass
    await callback.answer()


async def reject_withdraw_handler(callback: types.CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return
    parts = callback.data.split("_")
    user_id = int(parts[2])
    amount = int(parts[3])
    await callback.message.edit_text(f"❌ Вывод {amount}★ отклонён.")
    try:
        await bot.send_message(user_id, f"❌ Ваш запрос на вывод {amount}★ отклонён.")
    except:
        pass
    await callback.answer()


async def webapp_data_handler(message: types.Message, state: FSMContext, bot: Bot):
    if not message.web_app_data:
        return
    data = json.loads(message.web_app_data.data)
    if data.get('action') == 'withdraw':
        message.text = str(data['amount'])
        await request_withdraw_handler(message, state, bot)


async def back_main_handler(callback: types.CallbackQuery):
    user = callback.from_user
    balance = db.get_balance(user.id)
    text = (
        f"🎰 <b>1Win</b>\n\n"
        f"Баланс: <b>{balance} ⭐</b>\n\nВыбери действие:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=await get_main_keyboard(user.id))
    await callback.answer()


# ============================================================
# ADMIN PANEL
# ============================================================

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс пользователю", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="💎 Выдать себе баланс", callback_data="admin_self_balance")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_list_promos")],
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin_broadcast")],
    ])


async def admin_handler(message: types.Message):
    if not is_admin(message.from_user.username):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return

    await message.answer(
        "🔧 <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


async def admin_add_balance_handler(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_add_balance_user)
    await callback.message.edit_text("👤 Введите @username пользователя для пополнения баланса:")
    await callback.answer()


async def admin_add_balance_user_handler(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        return
    username = message.text.strip().lstrip("@")
    await state.update_data(target_username=username)
    await state.set_state(AdminStates.waiting_add_balance_amount)
    await message.answer(f"💰 Введите сумму для @{username}:")


async def admin_add_balance_amount_handler(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.username):
        return
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return

    data = await state.get_data()
    username = data["target_username"]
    user_id = db.get_user_id_by_username(username)

    if not user_id:
        await message.answer(f"❌ Пользователь @{username} не найден в базе.")
        await state.clear()
        return

    db.add_balance(user_id, amount)
    new_balance = db.get_balance(user_id)
    await state.clear()

    try:
        await bot.send_message(user_id, f"✅ Тебе зачислено +{amount}⭐\nБаланс: {new_balance}⭐")
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    await message.answer(
        f"✅ Пользователю @{username} зачислено {amount} ⭐\n"
        f"Новый баланс: {new_balance} ⭐"
    )


async def admin_self_balance_handler(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.update_data(target_username=callback.from_user.username)
    await state.set_state(AdminStates.waiting_add_balance_amount)
    await callback.message.edit_text("💰 Введите сумму для зачисления себе:")
    await callback.answer()


async def admin_create_promo_handler(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_promo_name)
    await callback.message.edit_text(
        "🎟 <b>Создание промокода</b>\n\nВведите название (только буквы и цифры):",
        parse_mode="HTML"
    )
    await callback.answer()


async def admin_promo_name_handler(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        return
    name = message.text.strip().upper()
    if not name.isalnum():
        await message.answer("❌ Промокод должен содержать только буквы и цифры.")
        return
    if db.promo_exists(name):
        await message.answer("❌ Промокод с таким именем уже существует.")
        return
    await state.update_data(promo_name=name)
    await state.set_state(AdminStates.waiting_promo_activations)
    await message.answer(f"🔢 Промокод: <b>{name}</b>\n\nВведите количество активаций:", parse_mode="HTML")


async def admin_promo_activations_handler(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        return
    try:
        activations = int(message.text.strip())
        if activations <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(promo_activations=activations)
    await state.set_state(AdminStates.waiting_promo_stars)
    await message.answer("⭐ Введите количество звёзд которые даёт промокод:")


async def admin_promo_stars_handler(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.username):
        return
    try:
        stars = int(message.text.strip())
        if stars <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return

    data = await state.get_data()
    name = data["promo_name"]
    activations = data["promo_activations"]
    db.create_promo(name, activations, stars)
    await state.clear()

    await message.answer(
        f"✅ <b>Промокод создан!</b>\n\n"
        f"Код: <code>{name}</code>\n"
        f"Активаций: {activations}\n"
        f"Даёт: {stars} ⭐",
        parse_mode="HTML"
    )


async def admin_list_promos_handler(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    promos = db.get_all_promos()
    if not promos:
        await callback.message.edit_text(
            "📋 Промокодов нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
            ])
        )
        await callback.answer()
        return

    text = "📋 <b>Список промокодов:</b>\n\n"
    for p in promos:
        text += f"• <code>{p['name']}</code> — {p['stars']}⭐ (активаций: {p['used']}/{p['max_activations']})\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# ============================================================
# РАССЫЛКА ВСЕМ
# ============================================================

async def admin_broadcast_handler(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    users_count = db.get_all_users_count()
    await state.set_state(AdminStates.waiting_broadcast_text)
    await callback.message.edit_text(
        f"📣 <b>Рассылка</b>\n\n"
        f"Пользователей в базе: <b>{users_count}</b>\n\n"
        f"Напишите текст сообщения для рассылки.\n"
        f"Поддерживается HTML-разметка (<b>bold</b>, <i>italic</i>, <code>code</code>).\n\n"
        f"Или отправьте /cancel для отмены.",
        parse_mode="HTML"
    )
    await callback.answer()


async def admin_broadcast_text_handler(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.username):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=admin_keyboard())
        return

    broadcast_text = message.html_text if message.text else None
    if not broadcast_text:
        await message.answer("❌ Отправьте текстовое сообщение.")
        return

    await state.clear()

    all_user_ids = db.get_all_user_ids()
    total = len(all_user_ids)

    status_msg = await message.answer(
        f"📣 <b>Рассылка запущена...</b>\n\n"
        f"Всего пользователей: {total}\n"
        f"Отправлено: 0 / {total}",
        parse_mode="HTML"
    )

    sent = 0
    failed = 0

    for i, uid in enumerate(all_user_ids):
        try:
            await bot.send_message(
                uid,
                f"📣 <b>Сообщение от администрации 1Win</b>\n\n{broadcast_text}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for user {uid}: {e}")
            failed += 1

        # Обновляем статус каждые 20 пользователей
        if (i + 1) % 20 == 0 or (i + 1) == total:
            try:
                await status_msg.edit_text(
                    f"📣 <b>Рассылка...</b>\n\n"
                    f"Отправлено: {sent} / {total}\n"
                    f"Ошибок: {failed}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Небольшая задержка чтобы не словить flood
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Всего: {total}\n"
        f"Успешно: {sent}\n"
        f"Не доставлено: {failed}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin_back")]
        ])
    )


async def admin_back_handler(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "🔧 <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )
    await callback.answer()


# ============================================================
# MAIN
# ============================================================

async def main():
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    bot = Bot(
        token=BOT_TOKEN,
        session=AiohttpSession(
            api=TelegramAPIServer.from_base("https://bot.catup.lol")
        )
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Basic commands
    dp.message.register(start_handler, Command("start"))
    dp.message.register(admin_handler, Command("admin"))

    # Gift handler — срабатывает на сервисные сообщения с подарком
    dp.message.register(gift_handler, F.gift.as_("gift"))

    # Callback handlers
    dp.callback_query.register(deposit_menu_handler, F.data == "deposit_menu")
    dp.callback_query.register(deposit_stars_handler, F.data == "deposit_stars")
    dp.callback_query.register(pay_stars_amount_handler, F.data.startswith("pay_stars_"))
    dp.callback_query.register(deposit_nft_handler, F.data == "deposit_nft")
    dp.callback_query.register(nft_sent_handler, F.data == "nft_sent")
    dp.callback_query.register(approve_nft_handler, F.data.startswith("approve_nft_"))
    dp.callback_query.register(reject_nft_handler, F.data.startswith("reject_nft_"))
    dp.callback_query.register(approve_withdraw_handler, F.data.startswith("approve_withdraw_"))
    dp.callback_query.register(reject_withdraw_handler, F.data.startswith("reject_withdraw_"))
    dp.callback_query.register(back_main_handler, F.data == "back_main")

    # Admin callbacks
    dp.callback_query.register(admin_add_balance_handler, F.data == "admin_add_balance")
    dp.callback_query.register(admin_self_balance_handler, F.data == "admin_self_balance")
    dp.callback_query.register(admin_create_promo_handler, F.data == "admin_create_promo")
    dp.callback_query.register(admin_list_promos_handler, F.data == "admin_list_promos")
    dp.callback_query.register(admin_broadcast_handler, F.data == "admin_broadcast")
    dp.callback_query.register(admin_back_handler, F.data == "admin_back")

    # State handlers
    dp.message.register(nft_amount_handler, UserStates.waiting_nft_amount)
    dp.message.register(request_withdraw_handler, UserStates.waiting_withdraw_amount)
    dp.message.register(webapp_data_handler, F.web_app_data)
    dp.message.register(admin_add_balance_user_handler, AdminStates.waiting_add_balance_user)
    dp.message.register(admin_add_balance_amount_handler, AdminStates.waiting_add_balance_amount)
    dp.message.register(admin_promo_name_handler, AdminStates.waiting_promo_name)
    dp.message.register(admin_promo_activations_handler, AdminStates.waiting_promo_activations)
    dp.message.register(admin_promo_stars_handler, AdminStates.waiting_promo_stars)
    dp.message.register(admin_broadcast_text_handler, AdminStates.waiting_broadcast_text)

    # Payment handlers
    dp.pre_checkout_query.register(pre_checkout_handler)
    dp.message.register(successful_payment_handler, F.successful_payment)

    logger.info("Bot started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
