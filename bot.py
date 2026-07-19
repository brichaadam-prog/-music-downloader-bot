import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
import yt_dlp
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Установите переменную окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Папка для временных файлов
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def search_youtube(query):
    """Ищет трек на YouTube и возвращает информацию"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch5',
        'extract_flat': False,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)

            if 'entries' in info:
                entries = info['entries']
            else:
                entries = [info]

            results = []
            for entry in entries[:5]:
                if entry:
                    duration = entry.get('duration', 0)
                    duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "?"
                    results.append({
                        'id': entry['id'],
                        'title': entry.get('title', 'Без названия'),
                        'uploader': entry.get('uploader', 'Неизвестен'),
                        'duration': duration_str,
                        'url': f"https://youtube.com/watch?v={entry['id']}"
                    })
            return results
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return []


def download_audio(video_id, title):
    """Скачивает audio с YouTube"""
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:50]
    output_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}_{video_id}.mp3")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'quiet': True,
        'no_warnings': True,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtube.com/watch?v={video_id}"])

        # Находим скачанный файл
        for file in os.listdir(DOWNLOAD_DIR):
            if video_id in file and file.endswith('.mp3'):
                return os.path.join(DOWNLOAD_DIR, file)
        return None
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        return None


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🎵 <b>Music Downloader Bot</b>\n\n"
        "Отправь мне название трека, и я найду и скачаю его с YouTube!\n\n"
        "<i>Пример: Skrillex Bangarang</i>",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 <b>Как пользоваться:</b>\n\n"
        "1. Отправь название трека\n"
        "2. Выбери из найденных вариантов\n"
        "3. Получи файл в лучшем качестве!\n\n"
        "⚠️ Бот может "засыпать" на Render — первый запрос может занять 1-2 минуты.",
        parse_mode=ParseMode.HTML
    )


@dp.message(F.text)
async def search_track(message: types.Message):
    query = message.text.strip()

    if len(query) < 2:
        await message.answer("❌ Слишком короткий запрос. Введи название трека.")
        return

    # Показываем статус поиска
    status_msg = await message.answer("🔍 Ищу трек на YouTube...")

    results = await asyncio.to_thread(search_youtube, query)

    if not results:
        await status_msg.edit_text("❌ Ничего не найдено. Попробуй другое название.")
        return

    # Создаём кнопки с результатами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for i, track in enumerate(results):
        btn_text = f"{i+1}. {track['title'][:40]} | {track['duration']}"
        callback_data = f"dl:{track['id']}:{track['title'][:30]}"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=btn_text, callback_data=callback_data)
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔄 Новый поиск", callback_data="new_search")
    ])

    await status_msg.edit_text(
        f"🎵 <b>Найдено {len(results)} треков:</b>\n\n"
        f"<i>Нажми на трек, чтобы скачать</i>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(F.data.startswith("dl:"))
async def download_callback(callback: types.CallbackQuery):
    data = callback.data.split(":", 2)
    video_id = data[1]
    title = data[2]

    await callback.answer("⏳ Начинаю скачивание...")

    # Убираем клавиатуру
    await callback.message.edit_text(
        f"⬇️ <b>Скачиваю:</b> {title}\n\n"
        f"<i>Это может занять 30-60 секунд...</i>",
        parse_mode=ParseMode.HTML
    )

    # Скачиваем
    file_path = await asyncio.to_thread(download_audio, video_id, title)

    if not file_path or not os.path.exists(file_path):
        await callback.message.edit_text(
            f"❌ <b>Не удалось скачать:</b> {title}\n\n"
            f"Возможно, трек заблокирован или требуется авторизация.",
            parse_mode=ParseMode.HTML
        )
        return

    # Проверяем размер файла
    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:  # 50 MB лимит Telegram
        await callback.message.edit_text(
            f"⚠️ <b>Файл слишком большой</b> ({file_size // 1024 // 1024} MB)\n"
            f"Лимит Telegram: 50 MB",
            parse_mode=ParseMode.HTML
        )
        os.remove(file_path)
        return

    # Отправляем файл
    await callback.message.edit_text(
        f"📤 <b>Отправляю файл...</b>",
        parse_mode=ParseMode.HTML
    )

    try:
        audio = types.FSInputFile(file_path)
        await bot.send_audio(
            chat_id=callback.message.chat.id,
            audio=audio,
            title=title,
            performer="YouTube Music",
            caption=f"🎵 {title}\n\n<i>Скачано через @MusicDownloaderBot</i>"
        )

        # Удаляем сообщение о загрузке
        await callback.message.delete()

    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка отправки:</b> {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )
    finally:
        # Удаляем временный файл
        if os.path.exists(file_path):
            os.remove(file_path)


@dp.callback_query(F.data == "new_search")
async def new_search_callback(callback: types.CallbackQuery):
    await callback.answer("Отправь новое название трека")
    await callback.message.edit_text(
        "🎵 <b>Отправь название трека для нового поиска</b>",
        parse_mode=ParseMode.HTML
    )


async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
