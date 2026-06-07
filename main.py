import os
import asyncio
import logging
from telethon import TelegramClient, events, Button, functions, types, utils
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, UserAlreadyParticipantError
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID: int = int(os.getenv("API_ID", "38720187"))
API_HASH: str = os.getenv("API_HASH", "a5c27bc42b391f32db86befcabc68094")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8756001910:AAGJyZQJDukIO9wUz8_MrIMS3ruZt3AXdXM")
ADMIN_ID: int = int(os.getenv("OWNER_ID", "6668195885"))

SESSIONS_DIR = 'sessions'
MEDIA_DIR = 'media_files'

for d in [SESSIONS_DIR, MEDIA_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

user_states = {}
active_calls = {}
pending_media = {}

bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)


def get_saved_accounts():
    accounts = []
    if os.path.exists(SESSIONS_DIR):
        for file in os.listdir(SESSIONS_DIR):
            if file.endswith('.session'):
                accounts.append(file.replace('.session', ''))
    return accounts


def main_buttons():
    return [
        [Button.inline("➕ اضافة حساب", b"login")],
        [Button.inline("📺 التشغيل", b"play_mode")],
        [Button.inline("📞 صعود اتصال", b"call_up"), Button.inline("📴 نزول اتصال", b"call_down")],
        [Button.url("👨‍💻 مطور البوت", "https://t.me/c3cccc3c")],
        [Button.inline("👁 عرض حساباتي", b"show_accs"), Button.inline("🗑 مسح حساب", b"delete_acc")]
    ]


async def get_chat_entity(client, chat_link):
    chat_entity = None
    try:
        if 't.me/+' in chat_link or 't.me/joinchat/' in chat_link:
            invite_hash = chat_link.split('/')[-1].replace('+', '')
            try:
                result = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
                chat_entity = result.chats[0]
            except UserAlreadyParticipantError:
                invite_info = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
                if isinstance(invite_info, types.ChatInviteAlready):
                    chat_entity = invite_info.chat
                else:
                    async for dialog in client.iter_dialogs():
                        if dialog.name == invite_info.title:
                            chat_entity = dialog.entity
                            break
            except Exception as e:
                logger.error(f"Error joining private link: {e}")
        else:
            chat_entity = await client.get_entity(chat_link)
            try:
                await client(functions.channels.JoinChannelRequest(channel=chat_entity))
            except UserAlreadyParticipantError:
                pass
            except Exception as e:
                logger.info(f"Join error: {e}")
    except Exception as e:
        logger.error(f"Error getting chat entity: {e}")

    return chat_entity


async def join_and_play_media(phone, chat_link, media_path, is_video=False):
    session_path = os.path.join(SESSIONS_DIR, phone)
    client = TelegramClient(session_path, API_ID, API_HASH, receive_updates=False)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error(f"Session for {phone} is not authorized.")
        await client.disconnect()
        return False

    try:
        chat_entity = await get_chat_entity(client, chat_link)
        if not chat_entity:
            await client.disconnect()
            return False

        peer_id = utils.get_peer_id(chat_entity)
        call = PyTgCalls(client)

        try:
            await call.start()

            if is_video:
                stream = MediaStream(
                    media_path,
                    audio_parameters=AudioQuality.STUDIO,
                    video_parameters=VideoQuality.FHD_1080p,
                )
            else:
                stream = MediaStream(
                    media_path,
                    audio_parameters=AudioQuality.STUDIO,
                )

            await call.play(peer_id, stream)

            active_calls[phone] = {
                'call': call,
                'client': client,
                'chat_entity': chat_entity,
                'peer_id': peer_id,
                'link': chat_link,
                'media_path': media_path
            }
            logger.info(f"Account {phone} playing media in call successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to play media for {phone}: {e}")
            try:
                await call.stop()
            except:
                pass
            await client.disconnect()
            return False

    except Exception as e:
        logger.error(f"General error for {phone}: {str(e)}")
        try:
            await client.disconnect()
        except:
            pass
        return False


async def join_and_call(phone, chat_link):
    session_path = os.path.join(SESSIONS_DIR, phone)
    client = TelegramClient(session_path, API_ID, API_HASH, receive_updates=False)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error(f"Session for {phone} is not authorized.")
        await client.disconnect()
        return False

    try:
        chat_entity = await get_chat_entity(client, chat_link)
        if not chat_entity:
            await client.disconnect()
            return False

        peer_id = utils.get_peer_id(chat_entity)
        call = PyTgCalls(client)

        try:
            await call.start()
            await call.play(
                peer_id,
                MediaStream(
                    'http://docs.evostream.com/sample_content/assets/sintel.mp4',
                    audio_parameters=AudioQuality.STUDIO,
                )
            )
            active_calls[phone] = {
                'call': call,
                'client': client,
                'chat_entity': chat_entity,
                'peer_id': peer_id,
                'link': chat_link
            }
            logger.info(f"Account {phone} joined call successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to play stream for {phone}: {e}")
            try:
                await call.stop()
            except:
                pass
            await client.disconnect()
            return False

    except Exception as e:
        logger.error(f"General error for {phone}: {str(e)}")
        try:
            await client.disconnect()
        except:
            pass
        return False


async def leave_call(phone, chat_link=None):
    if phone not in active_calls:
        return False

    call_data = active_calls[phone]
    call = call_data['call']
    client = call_data['client']

    try:
        if hasattr(call, 'stop') and callable(call.stop):
            await call.stop()

        if chat_link and call_data.get('chat_entity'):
            chat_entity = call_data['chat_entity']
            try:
                await client(functions.channels.LeaveChannelRequest(channel=chat_entity))
                logger.info(f"Account {phone} left chat {chat_link}")
            except:
                pass

        await client.disconnect()
        del active_calls[phone]
        logger.info(f"Account {phone} disconnected successfully")
        return True

    except Exception as e:
        logger.error(f"Error leaving call for {phone}: {e}")
        try:
            await client.disconnect()
            del active_calls[phone]
        except:
            pass
        return False


@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    if event.sender_id != ADMIN_ID:
        return
    await event.respond("ok :", buttons=main_buttons())


@bot.on(events.CallbackQuery)
async def callback_handler(event):
    if event.sender_id != ADMIN_ID:
        return

    data = event.data

    if data == b"login":
        accounts = get_saved_accounts()
        if len(accounts) >= 1:
            await event.answer(
                "يمكنك إضافة حساب واحد فقط . قم بمسح الحساب الحالي أولاً .",
                alert=True
            )
            return
        user_states[event.sender_id] = {'step': 'phone'}
        await event.edit(
            "أرسل لي رقم الهاتف مع رمز الدولة (مثال: +9647801234567) :",
            buttons=[Button.inline("إلغاء", b"cancel")]
        )

    elif data == b"cancel":
        user_states.pop(event.sender_id, None)
        pending_media.pop(event.sender_id, None)
        await event.edit("تم الإلغاء .", buttons=main_buttons())

    elif data == b"play_mode":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا يوجد حساب مضاف . أضف حساباً أولاً !", alert=True)
            return
        user_states[event.sender_id] = {'step': 'waiting_media'}
        await event.edit(
            "📺 وضع التشغيل\n\n"
            "أرسل لي فيديو 🎬 أو بصمة صوتية 🎙 أو ملف صوتي 🎵\n"
            "وسأقوم بتشغيله في الاتصال .",
            buttons=[Button.inline("❌ إلغاء", b"cancel")]
        )

    elif data == b"show_accs":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد لديك حسابات .", alert=True)
            return

        text = "📋 حساباتك :\n\n"
        for acc in accounts:
            status = "🟢 نشط في اتصال" if acc in active_calls else "⚪ غير نشط"
            text += f"• {acc} — {status}\n"

        await event.edit(text, buttons=[[Button.inline("🔙 باگ", b"back_main")]])

    elif data == b"back_main":
        await event.edit("ok :", buttons=main_buttons())

    elif data == b"delete_acc":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد حسابات .", alert=True)
            return
        buttons = [[Button.inline(f"🗑 {acc}", f"del_{acc}".encode())] for acc in accounts]
        buttons.append([Button.inline("🔙 باگ", b"cancel")])
        await event.edit("اختر الحساب للمسح :", buttons=buttons)

    elif data.startswith(b"del_"):
        acc_name = data.decode().replace("del_", "")
        session_path = os.path.join(SESSIONS_DIR, f"{acc_name}.session")
        if os.path.exists(session_path):
            os.remove(session_path)
            active_calls.pop(acc_name, None)
            await event.answer(f"تم مسح الحساب {acc_name} بنجاح .", alert=True)
            await event.edit("ok :", buttons=main_buttons())
        else:
            await event.answer("الحساب غير موجود !", alert=True)

    elif data == b"call_up":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا يوجد حساب مضاف !", alert=True)
            return
        user_states[event.sender_id] = {'step': 'join_link'}
        await event.edit("أرسل رابط القناة أو الگروب :", buttons=[Button.inline("❌ إلغاء", b"cancel")])

    elif data == b"call_down":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا يوجد حساب مضاف !", alert=True)
            return
        user_states[event.sender_id] = {'step': 'leave_link'}
        await event.edit("أرسل رابط القناة أو الگروب :", buttons=[Button.inline("❌ إلغاء", b"cancel")])


@bot.on(events.NewMessage)
async def message_handler(event):
    if event.sender_id != ADMIN_ID:
        return

    state = user_states.get(event.sender_id)
    if not state:
        return

    step = state.get('step')

    # ── وضع التشغيل: استقبال الميديا ──
    if step == 'waiting_media':
        has_media = (
            event.message.video or
            event.message.document or
            event.message.voice or
            event.message.audio
        )

        if has_media:
            msg = await event.respond("⏳ جاري حفظ الملف ...")
            try:
                if event.message.video:
                    ext = '.mp4'
                    is_video = True
                elif event.message.voice:
                    ext = '.ogg'
                    is_video = False
                else:
                    ext = '.mp3'
                    is_video = False

                file_path = os.path.join(MEDIA_DIR, f"media_{event.sender_id}{ext}")
                await bot.download_media(event.message, file=file_path)

                pending_media[event.sender_id] = {
                    'path': file_path,
                    'is_video': is_video
                }
                user_states[event.sender_id] = {'step': 'waiting_play_link'}

                await msg.delete()
                kind_text = "الفيديو" if is_video else "الصوت"
                await event.respond(
                    f"✅ تم حفظ {kind_text} !\n\n"
                    "أرسل رابط الگروب الذي تريد في الاتصال تشغيله :",
                    buttons=[Button.inline("❌ إلغاء", b"cancel")]
                )
            except Exception as e:
                await msg.delete()
                await event.respond(f"❌ خطأ في حفظ الملف: {str(e)}", buttons=main_buttons())
                user_states.pop(event.sender_id, None)
        else:
            await event.respond(
                "❗ أرسل فيديو 🎬 أو بصمة صوتية 🎙 أو ملف صوتي 🎵 فقط .",
                buttons=[Button.inline("❌ إلغاء", b"cancel")]
            )
        return

    # ── وضع التشغيل: استقبال رابط الگروب وبدء التشغيل ──
    if step == 'waiting_play_link':
        link = event.text.strip() if event.text else None
        if not link:
            await event.respond("❗ أرسل الرابط نصاً .", buttons=[Button.inline("❌ إلغاء", b"cancel")])
            return

        media_info = pending_media.get(event.sender_id)
        if not media_info:
            await event.respond("❌ لم أجد الملف . ابدأ من جديد .", buttons=main_buttons())
            user_states.pop(event.sender_id, None)
            return

        accounts = get_saved_accounts()
        if not accounts:
            await event.respond("❌ لا يوجد حساب مضاف !", buttons=main_buttons())
            user_states.pop(event.sender_id, None)
            pending_media.pop(event.sender_id, None)
            return

        status_msg = await event.respond("⏳ جاري الصعود للاتصال وتشغيل الميديا ...")
        phone = accounts[0]
        success = await join_and_play_media(phone, link, media_info['path'], media_info['is_video'])

        await status_msg.delete()
        if success:
            kind = "الفيديو" if media_info['is_video'] else "الصوت"
            await event.respond(
                f"✅ تم ! {kind} يشتغل الآن في الاتصال 🎶",
                buttons=main_buttons()
            )
        else:
            await event.respond(
                "❌ فشل الصعود للاتصال .\n"
                "تأكد من أن الرابط صحيح وأن الاتصال نشط في الگروب .",
                buttons=main_buttons()
            )

        user_states.pop(event.sender_id, None)
        pending_media.pop(event.sender_id, None)
        return

    # ── إضافة الحساب: رقم الهاتف ──
    if step == 'phone':
        phone = event.text.strip()
        session_path = os.path.join(SESSIONS_DIR, phone)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        try:
            send_code = await client.send_code_request(phone)
            user_states[event.sender_id] = {
                'step': 'code',
                'phone': phone,
                'phone_code_hash': send_code.phone_code_hash,
                'client': client
            }
            await event.respond(
                f"تم إرسال الكود الى {phone}\n"
                "أرسل لي الكود الذي وصلك بأرقام مفصولة بنقاط (مثال: 1.2.3.4.5) :",
                buttons=[Button.inline("❌ إلغاء", b"cancel")]
            )
        except Exception as e:
            await event.respond(f"❌ خطأ: {str(e)}", buttons=main_buttons())
            user_states.pop(event.sender_id)

    # ── إضافة الحساب: كود التحقق ──
    elif step == 'code':
        code = event.text.strip().replace('.', '').replace(' ', '')
        phone = state['phone']
        phone_code_hash = state['phone_code_hash']
        client = state['client']

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            await event.respond(f"✅ تم تسجيل الحساب وحفظه : {phone}", buttons=main_buttons())
            user_states.pop(event.sender_id)
            await client.disconnect()
        except SessionPasswordNeededError:
            user_states[event.sender_id]['step'] = '2fa'
            await event.respond(
                "🔐 الحساب محمي بتحقق خطوتين .\nأرسل كلمة السر :",
                buttons=[Button.inline("❌ إلغاء", b"cancel")]
            )
        except PhoneCodeInvalidError:
            await event.respond("❌ الكود غير صحيح . أرسله من جديد :", buttons=[Button.inline("❌ إلغاء", b"cancel")])
        except Exception as e:
            await event.respond(f"❌ خطأ: {str(e)}")
            user_states.pop(event.sender_id)

    # ── إضافة الحساب: التحقق بخطوتين ──
    elif step == '2fa':
        password = event.text.strip()
        phone = state['phone']
        client = state['client']

        try:
            await client.sign_in(password=password)
            await event.respond(f"✅ تم تسجيل الحساب وحفظه بنجاح : {phone}", buttons=main_buttons())
            user_states.pop(event.sender_id)
            await client.disconnect()
        except PasswordHashInvalidError:
            await event.respond("❌ كلمة السر خطأ . حاول مجدداً :", buttons=[Button.inline("❌ إلغاء", b"cancel")])
        except Exception as e:
            await event.respond(f"❌ خطأ: {str(e)}")
            user_states.pop(event.sender_id)

    # ── صعود اتصال ──
    elif step == 'join_link':
        link = event.text.strip()
        accounts = get_saved_accounts()
        if not accounts:
            await event.respond("❌ لا توجد حسابات للصعود !")
            user_states.pop(event.sender_id)
            return

        status_msg = await event.respond("⏳ جاري الصعود للمكالمة الصوتية ...")
        phone = accounts[0]
        success = await join_and_call(phone, link)

        await status_msg.delete()
        if success:
            await event.respond("✅ تم الصعود للمكالمة بنجاح 📞", buttons=main_buttons())
        else:
            await event.respond(
                "❌ فشل الصعود . تأكد من أن الرابط صحيح وأن الاتصال نشط .",
                buttons=main_buttons()
            )
        user_states.pop(event.sender_id)

    # ── نزول اتصال ──
    elif step == 'leave_link':
        link = event.text.strip()
        status_msg = await event.respond("⏳ جاري نزول الحساب من المكالمة ...")

        leave_count = 0
        for phone in list(active_calls.keys()):
            if active_calls[phone]['link'] == link:
                if await leave_call(phone, link):
                    leave_count += 1

        await status_msg.delete()
        if leave_count:
            await event.respond("✅ تم نزول الحساب من المكالمة بنجاح 📴", buttons=main_buttons())
        else:
            await event.respond("❌ الحساب ليس في هذه المكالمة .", buttons=main_buttons())
        user_states.pop(event.sender_id)


if __name__ == '__main__':
    print("✅ تم تشغيل البوت .")
    bot.run_until_disconnected()
