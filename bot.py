import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
import yt_dlp
import re
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found! Set the environment variable.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Папка для временных файлов
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Получаем URL сервиса Render
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")


def search_youtube(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch5',
        'extract_flat': False,
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
                        'title': entry.get('title', 'No title'),
                        'uploader': entry.get('uploader', 'Unknown'),
                        'duration': duration_str,
                        'url': f"https://youtube.com/watch?v={entry['id']}"
                    })
            return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []


def download_audio(video_id, title):
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
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://youtube.com/watch?v={video_id}"])

        for file in os.listdir(DOWNLOAD_DIR):
            if video_id in file and file.endswith('.mp3'):
                return os.path.join(DOWNLOAD_DIR, file)
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = "🎵 <b>Music Downloader Bot</b>\n\n"
    text += "Send me a track name and I'll find and download it from YouTube!\n\n"
    text += "<i>Example: Skrillex Bangarang</i>"
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = "📖 <b>How to use:</b>\n\n"
    text += "1. Send a track name\n"
    text += "2. Choose from found results\n"
    text += "3. Get the file in best quality!\n\n"
    text += "⚠️ Bot may 'sleep' on Render - first request may take 1-2 minutes."
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(F.text)
async def search_track(message: types.Message):
    query = message.text.strip()

    if len(query) < 2:
        await message.answer("❌ Query too short. Enter a track name.")
        return

    status_msg = await message.answer("🔍 Searching YouTube...")

    results = await asyncio.to_thread(search_youtube, query)

    if not results:
        await status_msg.edit_text("❌ Nothing found. Try another name.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for i, track in enumerate(results):
        btn_text = f"{i+1}. {track['title'][:40]} | {track['duration']}"
        callback_data = f"dl:{track['id']}:{track['title'][:30]}"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=btn_text, callback_data=callback_data)
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔄 New search", callback_data="new_search")
    ])

    text = f"🎵 <b>Found {len(results)} tracks:</b>\n\n"
    text += "<i>Tap a track to download</i>"
    await status_msg.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("dl:"))
async def download_callback(callback: types.CallbackQuery):
    data = callback.data.split(":", 2)
    video_id = data[1]
    title = data[2]

    await callback.answer("⏳ Starting download...")

    text = f"⬇️ <b>Downloading:</b> {title}\n\n"
    text += "<i>This may take 30-60 seconds...</i>"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)

    file_path = await asyncio.to_thread(download_audio, video_id, title)

    if not file_path or not os.path.exists(file_path):
        text = f"❌ <b>Failed to download:</b> {title}\n\n"
        text += "Track may be blocked or requires authorization."
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
        return

    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:
        text = f"⚠️ <b>File too large</b> ({file_size // 1024 // 1024} MB)\n"
        text += "Telegram limit: 50 MB"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
        os.remove(file_path)
        return

    await callback.message.edit_text("📤 <b>Sending file...</b>", parse_mode=ParseMode.HTML)

    try:
        audio = types.FSInputFile(file_path)
        await bot.send_audio(
            chat_id=callback.message.chat.id,
            audio=audio,
            title=title,
            performer="YouTube Music",
            caption=f"🎵 {title}\n\n<i>Downloaded via @MusicDownloaderBot</i>"
        )
        await callback.message.delete()

    except Exception as e:
        logger.error(f"Send error: {e}")
        text = f"❌ <b>Send error:</b> {str(e)[:100]}"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@dp.callback_query(F.data == "new_search")
async def new_search_callback(callback: types.CallbackQuery):
    await callback.answer("Send a new track name")
    await callback.message.edit_text(
        "🎵 <b>Send a track name for new search</b>",
        parse_mode=ParseMode.HTML
    )


async def on_startup(app):
    await bot.set_webhook(f"{RENDER_EXTERNAL_URL}/webhook")
    logger.info(f"Webhook set to {RENDER_EXTERNAL_URL}/webhook")


async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()


async def handle_webhook(request):
    json_str = await request.json()
    update = types.Update(**json_str)
    await dp.feed_update(bot, update)
    return web.Response()


async def health_check(request):
    return web.Response(text="OK")


app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", health_check)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
