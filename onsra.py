import os
import re
import asyncio
import io
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TPE1
from PIL import Image
import qrcode
from pyzbar.pyzbar import decode
from pdf2image import convert_from_path

TOKEN = "8774038631:AAFvx1Su_tjdc7cIO35y4oGf1c-B5AY2wpM"
BOT_NAME = "Onsra Evrensel Asistan"
SUPPORT_URL = "https://t.me/OnsraAdam"
download_cache = {} 

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Şarkı Ara (İsimle)", callback_data="mode_name")],
        [InlineKeyboardButton("🔗 Link ile İndir", callback_data="mode_link")],
        [InlineKeyboardButton("📄 Fotoğraftan PDF Yap", callback_data="mode_pdf")],
        [InlineKeyboardButton("🖼️ PDF'den Görsel Yap", callback_data="mode_pdf_to_img")],
        [InlineKeyboardButton("🔳 QR Kod Oluştur/Oku", callback_data="mode_qr")],
        [InlineKeyboardButton("👑 Destek & İletişim", url=SUPPORT_URL)]
    ])

def back_home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Geri", callback_data="main_menu"), 
         InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        f"Merhaba! Onsra Evrensel Asistan aktif. Hangi işlemi yapmak istersiniz?",
        reply_markup=main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        context.user_data.clear()
        await query.edit_message_text("Ana Menüye dönüldü. İşlem seçin:", reply_markup=main_menu_keyboard())
    
    elif data == "mode_name":
        context.user_data['waiting_for'] = 'name'
        await query.edit_message_text("Şarkı veya Sanatçı adını yazın:", reply_markup=back_home_keyboard())
    
    elif data == "mode_link":
        context.user_data['waiting_for'] = 'link'
        await query.edit_message_text("Medya linkini buraya yapıştırın:", reply_markup=back_home_keyboard())
    
    elif data == "mode_pdf":
        context.user_data['waiting_for'] = 'pdf_image'
        context.user_data['pdf_images'] = []
        keyboard = [[InlineKeyboardButton("✅ PDF'i Oluştur", callback_data="pdf_ask_name")],
                    [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
        await query.edit_message_text("PDF için fotoğrafları gönderin.", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "pdf_ask_name":
        if not context.user_data.get('pdf_images'):
            await query.answer("Önce fotoğraf gönderin!", show_alert=True)
            return
        context.user_data['waiting_for'] = 'pdf_name_input'
        await query.edit_message_text("PDF dosyasının ismini yazın:", reply_markup=back_home_keyboard())
    
    elif data == "mode_pdf_to_img":
        context.user_data['waiting_for'] = 'pdf_file'
        await query.edit_message_text("Lütfen PDF dosyasını gönderin:", reply_markup=back_home_keyboard())
    
    elif data == "mode_qr":
        context.user_data['waiting_for'] = 'qr_input'
        await query.edit_message_text("QR Modu: Metin yazın veya QR fotoğrafı atın.", reply_markup=back_home_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting_for = context.user_data.get('waiting_for')
    text = update.message.text.strip() if update.message.text else ""
    
    link_match = re.search(r'(https?://[^\s]+)', text)
    if link_match and waiting_for != 'pdf_name_input':
        context.user_data['target'] = link_match.group(0)
        context.user_data['is_link'] = True
        keyboard = [[InlineKeyboardButton("🎧 MP3", callback_data="mp3"), InlineKeyboardButton("📺 MP4", callback_data="mp4")],
                    [InlineKeyboardButton("🏠 İptal", callback_data="main_menu")]]
        await update.message.reply_text("Link algılandı! Format seçin:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if waiting_for == 'pdf_name_input':
        await create_pdf(update, context, text)
    elif waiting_for == 'qr_input' and text:
        await generate_qr(update, context, text)
    elif waiting_for == 'name':
        context.user_data['target'] = text
        context.user_data['is_link'] = False
        keyboard = [[InlineKeyboardButton("🎧 MP3", callback_data="mp3"), InlineKeyboardButton("📺 MP4", callback_data="mp4")],
                    [InlineKeyboardButton("🏠 İptal", callback_data="main_menu")]]
        await update.message.reply_text(f"{text} için format seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting_for = context.user_data.get('waiting_for')
    chat_id = update.effective_chat.id

    if waiting_for == 'pdf_image':
        file = await update.message.photo[-1].get_file()
        path = f"pdf_{chat_id}_{len(context.user_data['pdf_images'])}.jpg"
        await file.download_to_drive(path)
        context.user_data['pdf_images'].append(path)
        keyboard = [[InlineKeyboardButton("✅ PDF'i Oluştur", callback_data="pdf_ask_name")],
                    [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
        await update.message.reply_text(f"{len(context.user_data['pdf_images'])}. fotoğraf eklendi.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif waiting_for == 'qr_input':
        status = await update.message.reply_text("QR taranıyor...")
        try:
            file = await update.message.photo[-1].get_file()
            img_bytes = await file.download_as_bytearray()
            img = Image.open(io.BytesIO(img_bytes))
            decoded = decode(img)
            if decoded:
                res = decoded[0].data.decode('utf-8')
                await status.edit_text(f"QR Okundu: {res}", reply_markup=main_menu_keyboard())
            else:
                await status.edit_text("QR bulunamadı. Lütfen net bir fotoğraf atın.", reply_markup=back_home_keyboard())
        except Exception as e:
            await status.edit_text(f"Hata: {e}", reply_markup=main_menu_keyboard())

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for') == 'pdf_file' and update.message.document.mime_type == 'application/pdf':
        status = await update.message.reply_text("Sayfalar dönüştürülüyor...")
        pdf_file = await update.message.document.get_file()
        pdf_path = f"temp_{update.effective_chat.id}.pdf"
        await pdf_file.download_to_drive(pdf_path)
        try:
            images = convert_from_path(pdf_path)
            for i, image in enumerate(images):
                buf = io.BytesIO(); image.save(buf, format='JPEG'); buf.seek(0)
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=buf, caption=f"Sayfa {i+1}")
            await update.message.reply_text("Dönüşüm tamamlandı.", reply_markup=main_menu_keyboard())
        finally:
            if os.path.exists(pdf_path): os.remove(pdf_path)
            context.user_data.clear()

async def create_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_name):
    images = context.user_data.get('pdf_images', [])
    status = await update.message.reply_text("PDF hazırlanıyor...")
    safe_name = "".join([c for c in custom_name if c.isalnum() or c in (' ', '_', '-')]).strip()
    pdf_path = f"{safe_name}.pdf"
    try:
        img_list = [Image.open(p).convert('RGB') for p in images]
        img_list[0].save(pdf_path, save_all=True, append_images=img_list[1:])
        with open(pdf_path, 'rb') as f:
            await context.bot.send_document(chat_id=update.effective_chat.id, document=f, caption=f"Hazır. Onsra Evrensel Asistan")
        await update.message.reply_text("PDF gönderildi. Başka ne yapalım?", reply_markup=main_menu_keyboard())
    finally:
        for img in images: 
            if os.path.exists(img): os.remove(img)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        context.user_data.clear()
        await status.delete()

async def generate_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    qr = qrcode.make(text)
    buf = io.BytesIO(); qr.save(buf, format='PNG'); buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=f"QR Hazır. Onsra Evrensel Asistan")
    await update.message.reply_text("Başka bir işlem seçin:", reply_markup=main_menu_keyboard())

async def download_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    format_choice = query.data
    target = context.user_data.get('target')
    is_link = context.user_data.get('is_link', False)
    await query.answer()
    status = await query.edit_message_text("İndirme başladı...")
    ydl_opts = {'outtmpl': '%(title)s.%(ext)s', 'quiet': True, 'format': 'bestaudio/best' if format_choice == 'mp3' else 'best[ext=mp4]/best'}
    if format_choice == 'mp3': ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target if is_link else f"ytsearch1:{target}", download=True)
            if 'entries' in info: info = info['entries'][0]
            fname = ydl.prepare_filename(info)
            if format_choice == 'mp3': fname = fname.rsplit('.', 1)[0] + ".mp3"
        
        with open(fname, 'rb') as f:
            if format_choice == 'mp3':
                try:
                    audio = MP3(fname, ID3=ID3); audio.add_tags(); audio.tags.add(TPE1(encoding=3, text=BOT_NAME)); audio.save()
                except: pass
                await context.bot.send_audio(chat_id=update.effective_chat.id, audio=f, performer=BOT_NAME, title=info.get('title'))
            else:
                await context.bot.send_video(chat_id=update.effective_chat.id, video=f, caption=f"Onsra Evrensel Asistan")
        
        await query.message.reply_text("İşlem tamamlandı.", reply_markup=main_menu_keyboard())
        await status.delete()
        if os.path.exists(fname): os.remove(fname)
    except:
        await update.effective_chat.send_message("Hata oluştu.", reply_markup=main_menu_keyboard())
    finally:
        context.user_data.clear()

def main():
    app = Application.builder().token(TOKEN).connect_timeout(60).read_timeout(60).write_timeout(300).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(mode_|main_menu|pdf_ask_name)"))
    app.add_handler(CallbackQueryHandler(download_choice, pattern="^(mp3|mp4)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

