import logging
import re
import os
from dotenv import load_dotenv
load_dotenv()
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import google.generativeai as genai
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ========== НАСТРОЙКИ ==========
# Вставь сюда свой токен от BotFather
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Вставь сюда свой API ключ от Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# ================================

# Настройка Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Словарь для хранения истории чатов
chat_histories = {}

# Создаём папку для временных файлов
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

def format_text(text):
    """Форматирует текст из markdown в HTML для Telegram"""
    # Заголовки ### Текст -> <b>Текст</b>
    text = re.sub(r'###\s+(.+)', r'<b>\1</b>', text)
    # Жирный текст **текст** -> <b>текст</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Списки: заменим "* " в начале строки на "• "
    text = re.sub(r'^\s*\*\s+', '• ', text, flags=re.MULTILINE)
    # Курсив *текст* -> <i>текст</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    return text

async def send_long_message(context, chat_id, text, parse_mode='HTML'):
    """Отправляет длинное сообщение, разбивая на части если нужно"""
    max_length = 4000
    if len(text) > max_length:
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        for part in parts:
            await context.bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=parse_mode
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_histories[chat_id] = []
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="Привет! Я бот с Gemini AI.\n\n"
             "Я умею:\n"
             "📝 Общаться и помнить контекст беседы\n"
             "📷 Анализировать картинки\n"
             "📄 Читать PDF и текстовые файлы\n"
             "🎤 Распознавать голосовые сообщения\n\n"
             "Команды:\n"
             "/clear - очистить историю диалога\n"
             "/start - начать заново"
    )

# Команда /clear
async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_histories[chat_id] = []
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ История диалога очищена!"
    )

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text
    
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        chat_histories[chat_id].append({
            'role': 'user',
            'parts': [user_message]
        })
        
        chat = model.start_chat(history=chat_histories[chat_id][:-1])
        response = chat.send_message(user_message)
        bot_reply = response.text
        
        chat_histories[chat_id].append({
            'role': 'model',
            'parts': [bot_reply]
        })
        
        formatted_reply = format_text(bot_reply)
        await send_long_message(context, chat_id, formatted_reply)
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Произошла ошибка: {str(e)}"
        )

# Обработка изображений
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Получаем фото (берём самое качественное)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        # Сохраняем во временную папку
        file_path = TEMP_DIR / f"{photo.file_id}.jpg"
        await file.download_to_drive(file_path)
        
        # Загружаем в Gemini
        uploaded_file = genai.upload_file(file_path)
        
        # Получаем подпись к фото если есть
        caption = update.message.caption or "Что на этом изображении?"
        
        # Отправляем запрос с картинкой
        chat = model.start_chat(history=chat_histories[chat_id])
        response = chat.send_message([caption, uploaded_file])
        bot_reply = response.text
        
        # Сохраняем в историю
        chat_histories[chat_id].append({
            'role': 'user',
            'parts': [f"[Изображение]: {caption}"]
        })
        chat_histories[chat_id].append({
            'role': 'model',
            'parts': [bot_reply]
        })
        
        formatted_reply = format_text(bot_reply)
        await send_long_message(context, chat_id, formatted_reply)
        
        # Удаляем временный файл
        os.remove(file_path)
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка при обработке изображения: {str(e)}"
        )

# Обработка документов (PDF, TXT, DOCX и т.д.)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        document = update.message.document
        file = await context.bot.get_file(document.file_id)
        
        # Сохраняем файл
        file_path = TEMP_DIR / document.file_name
        await file.download_to_drive(file_path)
        
        # Загружаем в Gemini
        uploaded_file = genai.upload_file(file_path)
        
        # Получаем вопрос пользователя или используем стандартный
        caption = update.message.caption or "Проанализируй этот документ и расскажи о его содержании."
        
        # Отправляем запрос
        chat = model.start_chat(history=chat_histories[chat_id])
        response = chat.send_message([caption, uploaded_file])
        bot_reply = response.text
        
        # Сохраняем в историю
        chat_histories[chat_id].append({
            'role': 'user',
            'parts': [f"[Документ {document.file_name}]: {caption}"]
        })
        chat_histories[chat_id].append({
            'role': 'model',
            'parts': [bot_reply]
        })
        
        formatted_reply = format_text(bot_reply)
        await send_long_message(context, chat_id, formatted_reply)
        
        # Удаляем временный файл
        os.remove(file_path)
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка при обработке документа: {str(e)}"
        )

# Обработка голосовых сообщений
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        
        # Сохраняем голосовое сообщение
        file_path = TEMP_DIR / f"{voice.file_id}.ogg"
        await file.download_to_drive(file_path)
        
        # Загружаем в Gemini
        uploaded_file = genai.upload_file(file_path)
        
        # Отправляем на обработку
        prompt = "Распознай речь из этого аудиофайла и ответь на вопрос или просьбу."
        chat = model.start_chat(history=chat_histories[chat_id])
        response = chat.send_message([prompt, uploaded_file])
        bot_reply = response.text
        
        # Сохраняем в историю
        chat_histories[chat_id].append({
            'role': 'user',
            'parts': ["[Голосовое сообщение]"]
        })
        chat_histories[chat_id].append({
            'role': 'model',
            'parts': [bot_reply]
        })
        
        formatted_reply = format_text(bot_reply)
        await send_long_message(context, chat_id, formatted_reply)
        
        # Удаляем временный файл
        os.remove(file_path)
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка при обработке голосового сообщения: {str(e)}"
        )

# Главная функция
if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('clear', clear_history))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    print("Бот запущен со всеми возможностями!")
    application.run_polling()