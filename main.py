import asyncio
import logging
import json
import os
import hashlib
from typing import Dict, List, Set
from dotenv import load_dotenv
from telethon import TelegramClient, errors
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder 
from bs4 import BeautifulSoup
import aiohttp
import re 

# ================= Configuration =================
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load from .env
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CONFIG_FILE = "config.json"

# ================= Data Structures =================
class Config:
    def __init__(self):
        self.sources: Dict[str, List[str]] = {"channels": [], "sites": []}
        self.keywords: List[str] = []
        self.target_channel: str = None
        self.sent_hashes: Set[str] = set()
        self.load()

    def clean_sources(self):
        """Удаляет целевой канал из источников"""
        if self.target_channel and self.target_channel in self.sources['channels']:
            self.sources['channels'].remove(self.target_channel)

    def load(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                self.sources = data.get("sources", {"channels": [], "sites": []})
                self.keywords = data.get("keywords", [])
                self.target_channel = data.get("target_channel")
                self.sent_hashes = set(data.get("sent_hashes", []))
                self.clean_sources()
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Config load error: {e}, using defaults")

    def save(self):
        self.clean_sources()
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "sources": self.sources,
                "keywords": self.keywords,
                "target_channel": self.target_channel,
                "sent_hashes": list(self.sent_hashes)
            }, f, indent=2)

config = Config()
parsing_active = False
parsing_task = None
awaiting_target_channel = False
awaiting_source = False

# ================= Telegram Clients =================
userbot = TelegramClient('userbot_session', API_ID, API_HASH)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= Keyboard =================
def menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Вернуться в меню")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить источник", callback_data="add_source"),
        InlineKeyboardButton(text="📋 Список источников", callback_data="list_sources")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Удалить источник", callback_data="remove_source"),
        InlineKeyboardButton(text="🎯 Ключевые слова", callback_data="set_keywords")
    )
    builder.row(
        InlineKeyboardButton(text="📡 Установить целевой канал", callback_data="set_target"),
        InlineKeyboardButton(text="🔄 Статус", callback_data="status")
    )
    builder.row(
        InlineKeyboardButton(text="▶ Запуск парсинга", callback_data="start_parsing"),
        InlineKeyboardButton(text="⏹ Стоп парсинга", callback_data="stop_parsing")
    )
    builder.row(
        InlineKeyboardButton(text="🛠 Тест отправки", callback_data="test_send")
    )
    return builder.as_markup()

# ================= Welcome Message =================
WELCOME_MESSAGE = """
🤖 <b>Добро пожаловать в Content Parser Bot!</b>

Этот бот поможет вам:
1. Парсить контент из Telegram-каналов и сайтов
2. Фильтровать сообщения по ключевым словам
3. Автоматически пересылать подходящие сообщения в целевой канал

📌 <b>Как начать:</b>
1. Установите целевой канал (куда бот будет отправлять сообщения)
2. Добавьте источники для парсинга (каналы или сайты)
3. При необходимости укажите ключевые слова для фильтрации
4. Запустите парсинг!

Нажмите /start для отображения меню управления.
"""

# ================= Message Wrapper =================
async def send_message_with_menu(chat_id: int, text: str, parse_mode=None):
    """Отправляет сообщение с кнопкой 'Вернуться в меню'"""
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=menu_keyboard()
    )

# ================= Parsing Utilities =================
def get_message_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def contains_keywords(text: str, keywords: List[str]) -> bool:
    if not text or not keywords:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)

def remove_hyperlinks(text: str) -> str:
    """Удаляет гиперссылки из текста, оставляя только текст ссылки"""
    if not text:
        return text
    
    # Удаляем markdown ссылки [текст](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Удаляем HTML ссылки <a href="url">текст</a>
    text = re.sub(r'<a\s+href="[^"]+">([^<]+)</a>', r'\1', text)
    
    # Удаляем простые URL (http://example.com)
    text = re.sub(r'https?://\S+', '', text)
    
    return text.strip()

async def parse_sites():
    if not config.target_channel:
        logger.warning("Target channel not set, skipping sites parsing")
        return

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        for site in config.sources["sites"]:
            try:
                logger.info(f"Parsing site: {site}")
                async with session.get(site) as resp:
                    if resp.status != 200:
                        logger.warning(f"Site {site} returned status {resp.status}")
                        continue

                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    for element in soup(['script', 'style', 'nav', 'footer']):
                        element.decompose()
                    
                    text = ' '.join(soup.stripped_strings)
                    if not text:
                        logger.warning(f"No text content found on {site}")
                        continue
                        
                    snippet = text[:1000]
                    msg_hash = get_message_hash(snippet)

                    if msg_hash not in config.sent_hashes:
                        if not config.keywords or contains_keywords(text, config.keywords):
                            message_text = f"{snippet}..."
                            if len(message_text) > 4000:
                                message_text = message_text[:4000] + "..."

                            try:
                                await userbot.send_message(
                                    config.target_channel,
                                    message_text,
                                    link_preview=False
                                )
                                config.sent_hashes.add(msg_hash)
                                config.save()
                                logger.info(f"Successfully sent content from {site}")
                            except errors.FloodWaitError as e:
                                logger.error(f"Flood wait error: {e}, sleeping for {e.seconds} seconds")
                                await asyncio.sleep(e.seconds)
                            except Exception as e:
                                logger.error(f"Error sending message from {site}: {e}")
            except Exception as e:
                logger.error(f"Error parsing site {site}: {e}")

async def parse_channels():
    if not config.target_channel:
        logger.warning("Target channel not set, skipping channels parsing")
        return

    for channel in config.sources["channels"]:
        try:
            logger.info(f"Parsing channel: {channel}")
            async for msg in userbot.iter_messages(channel, limit=50):
                if not parsing_active:
                    logger.info("Parsing stopped by user")
                    return
                
                if not msg.message and not msg.media:
                    continue
                    
                clean_content = msg.text or msg.caption or ""
                # Удаляем гиперссылки из контента
                clean_content = remove_hyperlinks(clean_content)
                msg_hash = get_message_hash(clean_content + str(msg.media))
                
                if msg_hash not in config.sent_hashes:
                    if not config.keywords or contains_keywords(clean_content, config.keywords):
                        try:
                            if msg.media:
                                if isinstance(msg.media, MessageMediaPhoto):
                                    await userbot.send_file(
                                        config.target_channel,
                                        msg.media.photo,
                                        caption=clean_content[:1024] if clean_content else None
                                    )
                                elif isinstance(msg.media, MessageMediaDocument):
                                    await userbot.send_file(
                                        config.target_channel,
                                        msg.media.document,
                                        caption=clean_content[:1024] if clean_content else None
                                    )
                                else:
                                    await userbot.forward_messages(
                                        config.target_channel,
                                        msg
                                    )
                            else:
                                message_text = clean_content[:4000]
                                await userbot.send_message(
                                    config.target_channel,
                                    message_text,
                                    link_preview=False
                                )
                            
                            config.sent_hashes.add(msg_hash)
                            config.save()
                            logger.info(f"Successfully forwarded message from {channel}")
                        except errors.FloodWaitError as e:
                            logger.error(f"Flood wait error: {e}, sleeping for {e.seconds} seconds")
                            await asyncio.sleep(e.seconds)
                        except Exception as e:
                            logger.error(f"Error forwarding message from {channel}: {e}")
                            try:
                                if clean_content:
                                    await userbot.send_message(
                                        config.target_channel,
                                        clean_content[:4000],
                                        link_preview=False
                                    )
                            except Exception as fallback_error:
                                logger.error(f"Fallback sending also failed: {fallback_error}")

        except errors.ChannelPrivateError:
            logger.error(f"Channel {channel} is private or you're banned")
        except errors.ChannelInvalidError:
            logger.error(f"Channel {channel} is invalid or doesn't exist")
        except Exception as e:
            logger.error(f"Error parsing channel {channel}: {e}")

async def parsing_loop():
    global parsing_active
    parsing_active = True
    logger.info("Parsing loop started")
    
    while parsing_active:
        try:
            await asyncio.gather(
                parse_sites(),
                parse_channels(),
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Parsing error: {e}")
        
        sleep_time = 60 if parsing_active else 5
        logger.info(f"Sleeping for {sleep_time} seconds")
        await asyncio.sleep(sleep_time)

# ================= Bot Handlers =================
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    # Отправляем приветственное сообщение
    await send_message_with_menu(
        message.chat.id,
        WELCOME_MESSAGE,
        parse_mode="HTML"
    )
    
    # Отправляем основное меню
    await message.answer(
        "Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )

@dp.callback_query(F.data == "status")
async def show_status(callback: types.CallbackQuery):
    await callback.answer()
    status_text = (
        f"📊 <b>Статус:</b>\n\n"
        f"• Целевой канал: {config.target_channel or 'не задан'}\n"
        f"• Каналов в источниках: {len(config.sources['channels'])}\n"
        f"• Сайтов в источниках: {len(config.sources['sites'])}\n"
        f"• Ключевых слов: {len(config.keywords) or 'не заданы'}\n"
        f"• Найдено сообщений: {len(config.sent_hashes)}\n"
        f"• Парсинг: {'активен' if parsing_active else 'не активен'}"
    )
    await callback.message.edit_text(status_text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())

@dp.callback_query(F.data == "start_parsing")
async def start_parsing_handler(callback: types.CallbackQuery):
    global parsing_task, parsing_active
    
    if not config.target_channel:
        await callback.answer("❌ Сначала укажите целевой канал!", show_alert=True)
        return
        
    if parsing_active:
        await callback.answer("Парсинг уже запущен!", show_alert=True)
        return
    
    parsing_active = True
    parsing_task = asyncio.create_task(parsing_loop(), name="parsing_loop")
    await callback.answer("✅ Парсинг запущен!")
    await show_status(callback)

@dp.callback_query(F.data == "stop_parsing")
async def stop_parsing_handler(callback: types.CallbackQuery):
    global parsing_active
    
    if not parsing_active:
        await callback.answer("Парсинг не активен!", show_alert=True)
        return
    
    parsing_active = False
    if parsing_task:
        parsing_task.cancel()
    await callback.answer("⏹ Парсинг остановлен!")
    await show_status(callback)

@dp.callback_query(F.data == "test_send")
async def test_send_handler(callback: types.CallbackQuery):
    if not config.target_channel:
        await callback.answer("❌ Целевой канал не установлен!", show_alert=True)
        return
    
    try:
        await userbot.send_message(
            config.target_channel,
            "✅ Тестовое сообщение от парсера\n\n"
            "Это сообщение подтверждает, что бот может отправлять сообщения в указанный канал."
        )
        await callback.answer("Тестовое сообщение отправлено!", show_alert=True)
        await send_message_with_menu(
            callback.message.chat.id,
            "✅ Тестовое сообщение успешно отправлено в целевой канал!"
        )
    except Exception as e:
        error_msg = f"❌ Ошибка отправки: {str(e)}"
        logger.error(error_msg)
        await send_message_with_menu(
            callback.message.chat.id,
            error_msg
        )

@dp.callback_query(F.data == "set_target")
async def set_target_handler(callback: types.CallbackQuery):
    global awaiting_target_channel
    await callback.answer()
    awaiting_target_channel = True
    await send_message_with_menu(
        callback.message.chat.id,
        "Отправьте @username канала, куда бот будет отправлять результаты.\n"
        "Пример: @mytargetchannel\n\n"
        "Бот должен быть администратором в этом канале!\n\n"
        f"Текущий: {config.target_channel or 'не задан'}"
    )

@dp.callback_query(F.data == "add_source")
async def add_source_handler(callback: types.CallbackQuery):
    global awaiting_source
    await callback.answer()
    awaiting_source = True
    await send_message_with_menu(
        callback.message.chat.id,
        "Отправьте ссылку на источник для парсинга:\n"
        "- Для Telegram канала: @username или t.me/username\n"
        "- Для сайта: http://example.com или https://example.com\n\n"
        "⚠️ Не используйте целевой канал как источник!"
    )

@dp.callback_query(F.data == "remove_source")
async def remove_source_handler(callback: types.CallbackQuery):
    await callback.answer()
    
    if not config.sources["channels"] and not config.sources["sites"]:
        await send_message_with_menu(
            callback.message.chat.id,
            "Нет добавленных источников"
        )
        return
    
    builder = InlineKeyboardBuilder()
    for source in config.sources["channels"] + config.sources["sites"]:
        builder.row(InlineKeyboardButton(
            text=f"❌ Удалить {source[:20]}{'...' if len(source) > 20 else ''}",
            callback_data=f"remove_{hashlib.md5(source.encode()).hexdigest()}"
        ))
    
    await callback.message.answer(
        "Выберите источник для удаления:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("remove_"))
async def confirm_remove_handler(callback: types.CallbackQuery):
    await callback.answer()
    source_hash = callback.data.split("_")[1]
    
    for source_type in ["channels", "sites"]:
        for source in config.sources[source_type][:]:
            if hashlib.md5(source.encode()).hexdigest() == source_hash:
                config.sources[source_type].remove(source)
                config.save()
                await send_message_with_menu(
                    callback.message.chat.id,
                    f"✅ Источник {source} удален"
                )
                await list_sources_handler(callback)
                return
    
    await send_message_with_menu(
        callback.message.chat.id,
        "❌ Источник не найден"
    )

@dp.callback_query(F.data == "list_sources")
async def list_sources_handler(callback: types.CallbackQuery):
    await callback.answer()
    config.clean_sources()
    
    sources_text = []
    if config.sources['channels']:
        sources_text.append("📢 <b>Телеграм каналы:</b>\n" + "\n".join(f"• {ch}" for ch in config.sources['channels']))
    else:
        sources_text.append("📢 <b>Телеграм каналы:</b> Нет")
    
    if config.sources['sites']:
        sources_text.append("🌐 <b>Веб-сайты:</b>\n" + "\n".join(f"• {site}" for site in config.sources['sites']))
    else:
        sources_text.append("🌐 <b>Веб-сайты:</b> Нет")
    
    status_text = (
        "📋 <b>Текущие настройки</b>\n\n"
        f"🎯 <b>Целевой канал:</b> {config.target_channel or 'Не задан'}\n\n"
        f"🔍 <b>Ключевые слова:</b> {', '.join(config.keywords) or 'Не заданы'}\n\n"
        + "\n\n".join(sources_text)
    )
    
    await callback.message.edit_text(
        status_text, 
        parse_mode="HTML", 
        reply_markup=get_main_menu_keyboard()
    )

@dp.callback_query(F.data == "set_keywords")
async def set_keywords_handler(callback: types.CallbackQuery):
    await callback.answer()
    await send_message_with_menu(
        callback.message.chat.id,
        "Отправьте ключевые слова через запятую.\n"
        "Пример: bitcoin,криптовалюта,blockchain\n\n"
        "Для парсинга всех сообщений без фильтрации отправьте \"-\"\n\n"
        f"Текущие: {', '.join(config.keywords) if config.keywords else 'не заданы'}"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    global awaiting_target_channel, awaiting_source
    text = message.text.strip()

    if message.text == "Вернуться в меню":
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard()
        )
        awaiting_target_channel = False
        awaiting_source = False
        return
    
    if awaiting_target_channel:
        channel = message.text.strip()
        if not channel.startswith('@'):
            await send_message_with_menu(
                message.chat.id,
                "Имя канала должно начинаться с @. Попробуйте еще раз."
            )
            return
            
        try:
            entity = await userbot.get_entity(channel)
            if not entity:
                raise ValueError("Канал не найден")
                
            config.target_channel = channel
            config.save()
            await send_message_with_menu(
                message.chat.id,
                f"✅ Целевой канал установлен: {channel}"
            )
            awaiting_target_channel = False
        except Exception as e:
            await send_message_with_menu(
                message.chat.id,
                f"❌ Ошибка: {str(e)}\n"
                "Убедитесь что:\n"
                "1. Бот добавлен в канал как администратор\n"
                "2. Вы указали правильный @username канала\n"
                "Попробуйте еще раз."
            )
        return
    
    elif awaiting_source:
        source = message.text.strip()
        
        if source.startswith(('http://', 'https://')):
            if source in config.sources['sites']:
                await send_message_with_menu(
                    message.chat.id,
                    "Этот сайт уже добавлен!"
                )
                return
                
            config.sources['sites'].append(source)
            config.save()
            await send_message_with_menu(
                message.chat.id,
                f"✅ Сайт добавлен: {source}"
            )
            
        elif source.startswith(('@', 't.me/')):
            if source.startswith('t.me/'):
                source = '@' + source.split('/')[-1]
                
            if source == config.target_channel:
                await send_message_with_menu(
                    message.chat.id,
                    "Нельзя добавлять целевой канал как источник!"
                )
                return
                
            if source in config.sources['channels']:
                await send_message_with_menu(
                    message.chat.id,
                    "Этот канал уже добавлен!"
                )
                return
                
            try:
                entity = await userbot.get_entity(source)
                if not entity:
                    raise ValueError("Канал не найден")
                    
                config.sources['channels'].append(source)
                config.save()
                await send_message_with_menu(
                    message.chat.id,
                    f"✅ Канал добавлен: {source}"
                )
            except Exception as e:
                await send_message_with_menu(
                    message.chat.id,
                    f"❌ Ошибка: {str(e)}\n"
                    "Убедитесь что:\n"
                    "1. Бот имеет доступ к каналу\n"
                    "2. Вы указали правильный @username канала\n"
                    "Попробуйте еще раз."
                )
        else:
            await send_message_with_menu(
                message.chat.id,
                "Неправильный формат источника.\n"
                "Для Telegram канала используйте @username или t.me/username\n"
                "Для сайта используйте http:// или https://"
            )
        awaiting_source = False
        return
    
    elif any(word in message.text.lower() for word in ["ключевые слова", "keywords"]):
        if message.text.strip() == "-":
            config.keywords = []
            config.save()
            await send_message_with_menu(
                message.chat.id,
                "✅ Фильтрация по ключевым словам отключена"
            )
        else:
            keywords = [kw.strip() for kw in message.text.split(',') if kw.strip()]
            config.keywords = keywords
            config.save()
            await send_message_with_menu(
                message.chat.id,
                f"✅ Ключевые слова установлены: {', '.join(keywords)}"
            )
        return
    
    await send_message_with_menu(
        message.chat.id,
        "Используйте кнопки меню для управления ботом"
    )

async def main():
    await userbot.start()
    logger.info("Userbot started")
    
    await dp.start_polling(bot)
    logger.info("Bot started")

if __name__ == "__main__":
    asyncio.run(main())