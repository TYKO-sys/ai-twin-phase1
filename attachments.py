"""attachments.py - Telegram attachment handlers for AI Twin"""
import os, logging
from pathlib import Path
log = logging.getLogger("attachments")
ATTACH_DIR = Path.home() / "ai-twin-memory" / "attachments"

def _sanitize_filename(name):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe[:100] if safe else "attachment"

def _save_attachment(bot, file_id, filename):
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    file_info = bot.get_file(file_id)
    downloaded = bot.download_file(file_info.file_path)
    safe_name = _sanitize_filename(filename)
    filepath = ATTACH_DIR / safe_name
    counter = 1
    while filepath.exists():
        filepath = ATTACH_DIR / f"{filepath.stem}_{counter}{filepath.suffix}"
        counter += 1
    filepath.write_bytes(downloaded)
    log.info(f"Attachment saved: {filepath.name} ({len(downloaded)} bytes)")
    return str(filepath)

def _safe_reply(bot, message, text):
    try: bot.reply_to(message, text)
    except Exception as e: log.error(f"Reply failed: {e}")

def _save_note(text):
    try:
        from tools import save_note
        save_note(text)
    except: pass

def register(bot, allowed_user_id):
    @bot.message_handler(content_types=["document"])
    def handle_document(message):
        try:
            if message.from_user.id != allowed_user_id: return
            filename = message.document.file_name or f"document_{message.message_id}"
            saved = _save_attachment(bot, message.document.file_id, filename)
            _save_note(f"User sent attachment: {filename}. Saved to attachments/{os.path.basename(saved)}.")
            _safe_reply(bot, message, f"got the file - {filename}. saved it. what do you need me to do with it?")
        except Exception as e:
            log.error(f"Document handler error: {e}")
            _safe_reply(bot, message, "could not save that file. try sending it again.")
    @bot.message_handler(content_types=["photo"])
    def handle_photo(message):
        try:
            if message.from_user.id != allowed_user_id: return
            photo = message.photo[-1]
            saved = _save_attachment(bot, photo.file_id, f"photo_{message.message_id}.jpg")
            _save_note(f"User sent a photo. Saved to attachments/{os.path.basename(saved)}.")
            _safe_reply(bot, message, "got the photo. saved it. what is it of?")
        except Exception as e: log.error(f"Photo handler error: {e}")
    @bot.message_handler(content_types=["voice"])
    def handle_voice(message):
        try:
            if message.from_user.id != allowed_user_id: return
            saved = _save_attachment(bot, message.voice.file_id, f"voice_{message.message_id}.ogg")
            _save_note(f"User sent a voice note. Saved to attachments/{os.path.basename(saved)}.")
            _safe_reply(bot, message, "got the voice note. saved it. (cannot transcribe yet)")
        except Exception as e: log.error(f"Voice handler error: {e}")
    @bot.message_handler(content_types=["sticker"])
    def handle_sticker(message):
        try:
            if message.from_user.id != allowed_user_id: return
            _safe_reply(bot, message, "lol")
        except: pass
    log.info("Attachment handlers registered")
