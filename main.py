import os
import time
import logging
import asyncio
from telethon import TelegramClient, events, Button, functions, types, utils
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
    UserAlreadyParticipantError,
)
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID", "38720187"))
API_HASH = os.getenv("API_HASH", "a5c27bc42b391f32db86befcabc68094")
BOT_TOKEN = os.getenv(
    "BOT_TOKEN", "8756001910:AAGJyZQJDukIO9wUz8_MrIMS3ruZt3AXdXM"
)
ADMIN_ID = int(os.getenv("OWNER_ID", "6668195885"))

SESSIONS_DIR = "sessions"
MEDIA_DIR = "media_files"

for _d in [SESSIONS_DIR, MEDIA_DIR]:
    if not os.path.exists(_d):
        os.makedirs(_d)

user_states = {}
active_calls = {}
pending_media = {}

# ==============================================================================
# كاش الملفات المحمّلة مسبقاً - نفس فكرة Aliis
# المفتاح: file_unique_id | القيمة: مسار الملف المحفوظ
# ==============================================================================
file_cache: dict[str, str] = {}

# الحجم الافتراضي للـ chunk عند التحميل: 512KB بدلاً من 128KB الافتراضي
CHUNK_SIZE = 2 ** 19  # 512 KB

bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


def get_saved_accounts():
    accounts = []
    if os.path.exists(SESSIONS_DIR):
        for file in os.listdir(SESSIONS_DIR):
            if file.endswith(".session"):
                accounts.append(file.replace(".session", ""))
    return accounts


def main_buttons():
    return [
        [Button.inline("اضافة حساب", b"login")],
        [Button.inline("التشغيل", b"play_mode")],
        [
            Button.inline("صعود اتصال", b"call_up"),
            Button.inline("نزول اتصال", b"call_down"),
        ],
        [Button.url("مطور البوت", "https://t.me/c3cccc3c")],
        [
            Button.inline("عرض حساباتي", b"show_accs"),
            Button.inline("مسح حساب", b"delete_acc"),
        ],
    ]


# ==============================================================================
# دالة التحميل السريع - مع chunks كبيرة + كاش + تقدم حي
# مستوحاة من نظام التحميل في مشروع Aliis
# ==============================================================================
async def fast_download(message, status_msg) -> tuple[str, bool] | None:
    """
    تحميل سريع بـ chunks حجمها 512KB مع:
    - كاش يمنع إعادة تحميل نفس الملف
    - تحديث تقدم التحميل كل 5 ثواني
    - إرجاع (مسار_الملف, هل_فيديو)
    """
    # تحديد نوع الملف
    media = message.video or message.document or message.voice or message.audio
    if not media:
        return None

    is_video = bool(message.video) or (
        message.document
        and getattr(message.document, "mime_type", "").startswith("video/")
    )

    if message.video:
        ext = ".mp4"
    elif message.voice:
        ext = ".ogg"
    else:
        ext = ".mp3"

    # file_unique_id = معرّف فريد للملف مستقل عن الرسالة (نفس فكرة Aliis)
    file_unique_id = getattr(media, "id", None)

    # --- فحص الكاش أولاً ---
    if file_unique_id and file_unique_id in file_cache:
        cached_path = file_cache[file_unique_id]
        if os.path.exists(cached_path):
            logger.info(f"ملف موجود في الكاش: {cached_path}")
            await status_msg.edit("✅ الملف موجود مسبقاً , جاري التشغيل ...")
            return cached_path, is_video

    file_size = getattr(media, "size", 0) or 0
    file_path = os.path.join(MEDIA_DIR, f"file_{file_unique_id}{ext}")

    start_time = time.time()
    last_update = [0.0]  # قائمة لتجاوز قيود الـ closure

    def format_size(n: int) -> str:
        if n >= 1024 ** 2:
            return f"{n / 1024 ** 2:.1f} MB"
        elif n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} B"

    def format_eta(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}ث"
        return f"{seconds // 60}د {seconds % 60}ث"

    # --- التحميل بـ chunks 512KB ---
    downloaded = 0
    try:
        with open(file_path, "wb") as f:
            async for chunk in bot.iter_download(message.media, request_size=CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)

                # تحديث التقدم كل 5 ثواني فقط (لا تعطل التليغرام بطلبات كثيرة)
                now = time.time()
                if now - last_update[0] >= 5:
                    last_update[0] = now
                    elapsed = now - start_time or 1e-6
                    speed = downloaded / elapsed
                    if file_size > 0:
                        percent = downloaded * 100 / file_size
                        eta = format_eta(int((file_size - downloaded) / (speed or 1)))
                        progress_text = (
                            f"⬇️ جاري التحميل ...\n"
                            f"{format_size(downloaded)} / {format_size(file_size)}"
                            f"  ({percent:.1f}%)\n"
                            f"⚡ السرعة: {format_size(int(speed))}/ث\n"
                            f"⏱ الوقت المتبقي: {eta}"
                        )
                    else:
                        progress_text = (
                            f"⬇️ جاري التحميل ...\n"
                            f"{format_size(downloaded)}"
                            f" | ⚡ {format_size(int(speed))}/ث"
                        )
                    try:
                        await status_msg.edit(progress_text)
                    except Exception:
                        pass

        total_time = round(time.time() - start_time, 2)
        logger.info(f"تم التحميل في {total_time}ث: {file_path}")

        # حفظ في الكاش
        if file_unique_id:
            file_cache[file_unique_id] = file_path

        return file_path, is_video

    except Exception as e:
        # مسح الملف الجزئي لو صار خطأ
        if os.path.exists(file_path):
            os.remove(file_path)
        raise e


# ==============================================================================
# باقي الكود بدون تغيير
# ==============================================================================

async def get_chat_entity(client, chat_link):
    chat_entity = None
    try:
        if "t.me/+" in chat_link or "t.me/joinchat/" in chat_link:
            invite_hash = chat_link.split("/")[-1].replace("+", "")
            try:
                result = await client(
                    functions.messages.ImportChatInviteRequest(hash=invite_hash)
                )
                chat_entity = result.chats[0]
            except UserAlreadyParticipantError:
                invite_info = await client(
                    functions.messages.CheckChatInviteRequest(hash=invite_hash)
                )
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
                await client(
                    functions.channels.JoinChannelRequest(channel=chat_entity)
                )
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
                "call": call,
                "client": client,
                "chat_entity": chat_entity,
                "peer_id": peer_id,
                "link": chat_link,
                "media_path": media_path,
            }
            logger.info(f"Account {phone} playing media in call successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to play media for {phone}: {e}")
            try:
                await call.stop()
            except Exception:
                pass
            await client.disconnect()
            return False

    except Exception as e:
        logger.error(f"General error for {phone}: {str(e)}")
        try:
            await client.disconnect()
        except Exception:
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
                    "http://docs.evostream.com/sample_content/assets/sintel.mp4",
                    audio_parameters=AudioQuality.STUDIO,
                ),
            )
            active_calls[phone] = {
                "call": call,
                "client": client,
                "chat_entity": chat_entity,
                "peer_id": peer_id,
                "link": chat_link,
            }
            logger.info(f"Account {phone} joined call successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to play stream for {phone}: {e}")
            try:
                await call.stop()
            except Exception:
                pass
            await client.disconnect()
            return False

    except Exception as e:
        logger.error(f"General error for {phone}: {str(e)}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return False


async def leave_call(phone, chat_link=None):
    if phone not in active_calls:
        return False

    call_data = active_calls[phone]
    call = call_data["call"]
    client = call_data["client"]

    try:
        if hasattr(call, "stop") and callable(call.stop):
            await call.stop()

        if chat_link and call_data.get("chat_entity"):
            chat_entity = call_data["chat_entity"]
            try:
                await client(
                    functions.channels.LeaveChannelRequest(channel=chat_entity)
                )
                logger.info(f"Account {phone} left chat {chat_link}")
            except Exception:
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
        except Exception:
            pass
        return False


@bot.on(events.NewMessage(pattern="/start"))
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
                "يمكنك إضافة حساب واحد فقط . قم بمسح الحساب الحالي اولا .",
                alert=True,
            )
            return
        user_states[event.sender_id] = {"step": "phone"}
        await event.edit(
            "ارسل لي رقم الهاتف مع رمز الدولة (مثال: +9647801234567) :",
            buttons=[Button.inline("الغاء", b"cancel")],
        )

    elif data == b"cancel":
        user_states.pop(event.sender_id, None)
        pending_media.pop(event.sender_id, None)
        await event.edit("تم الالغاء .", buttons=main_buttons())

    elif data == b"play_mode":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا يوجد حساب مضاف . اضف حسابا اولا !", alert=True)
            return
        user_states[event.sender_id] = {"step": "waiting_media"}
        await event.edit(
            "وضع التشغيل\n\n"
            "ارسل لي فيديو او بصمة صوتية او ملف صوتي\n"
            "وساقوم بتشغيله في الاتصال .",
            buttons=[Button.inline("الغاء", b"cancel")],
        )

    elif data == b"show_accs":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد لديك حسابات .", alert=True)
            return

        text = "حساباتك :\n\n"
        for acc in accounts:
            status = "نشط في اتصال" if acc in active_calls else "غير نشط"
            text += f"- {acc} : {status}\n"

        await event.edit(text, buttons=[[Button.inline("باگ", b"back_main")]])

    elif data == b"back_main":
        await event.edit("ok :", buttons=main_buttons())

    elif data == b"delete_acc":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد حسابات .", alert=True)
            return
        buttons = [
            [Button.inline(acc, f"del_{acc}".encode())] for acc in accounts
        ]
        buttons.append([Button.inline("باگ", b"cancel")])
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
        user_states[event.sender_id] = {"step": "join_link"}
        await event.edit(
            "ارسل رابط القناة او الگروب :",
            buttons=[Button.inline("الغاء", b"cancel")],
        )

    elif data == b"call_down":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا يوجد حساب مضاف !", alert=True)
            return
        user_states[event.sender_id] = {"step": "leave_link"}
        await event.edit(
            "ارسل رابط القناة او الگروب :",
            buttons=[Button.inline("الغاء", b"cancel")],
        )


@bot.on(events.NewMessage)
async def message_handler(event):
    if event.sender_id != ADMIN_ID:
        return

    state = user_states.get(event.sender_id)
    if not state:
        return

    step = state.get("step")

    if step == "waiting_media":
        has_media = (
            event.message.video
            or event.message.document
            or event.message.voice
            or event.message.audio
        )

        if has_media:
            msg = await event.respond("⬇️ جاري التحميل ...")
            try:
                # ===== التحميل السريع (بدلاً من download_media البطيء) =====
                result = await fast_download(event.message, msg)
                if not result:
                    raise Exception("تعذّر استخراج الملف")

                file_path, is_video = result

                pending_media[event.sender_id] = {
                    "path": file_path,
                    "is_video": is_video,
                }
                user_states[event.sender_id] = {"step": "waiting_play_link"}

                await msg.delete()
                kind_text = "الفيديو" if is_video else "الصوت"
                await event.respond(
                    f"✅ تم حفظ {kind_text} !\n\n"
                    "ارسل رابط الگروب الذي تريد في الاتصال تشغيله :",
                    buttons=[Button.inline("الغاء", b"cancel")],
                )
            except Exception as e:
                await msg.delete()
                await event.respond(
                    f"خطا في حفظ الملف: {str(e)}", buttons=main_buttons()
                )
                user_states.pop(event.sender_id, None)
        else:
            await event.respond(
                "ارسل فيديو او بصمة صوتية او ملف صوتي فقط .",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
        return

    if step == "waiting_play_link":
        link = event.text.strip() if event.text else None
        if not link:
            await event.respond(
                "ارسل الرابط نصا .",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
            return

        media_info = pending_media.get(event.sender_id)
        if not media_info:
            await event.respond(
                "لم اجد الملف . ابدا من جديد .", buttons=main_buttons()
            )
            user_states.pop(event.sender_id, None)
            return

        accounts = get_saved_accounts()
        if not accounts:
            await event.respond("لا يوجد حساب مضاف !", buttons=main_buttons())
            user_states.pop(event.sender_id, None)
            pending_media.pop(event.sender_id, None)
            return

        status_msg = await event.respond("جاري الصعود للاتصال وتشغيل الميديا ...")
        phone = accounts[0]
        success = await join_and_play_media(
            phone, link, media_info["path"], media_info["is_video"]
        )

        await status_msg.delete()
        if success:
            kind = "الفيديو" if media_info["is_video"] else "الصوت"
            await event.respond(
                f"تم ! {kind} يشتغل الان في الاتصال",
                buttons=main_buttons(),
            )
        else:
            await event.respond(
                "فشل الصعود للاتصال .\n"
                "تاكد من ان الرابط صحيح وان الاتصال نشط في الگروب .",
                buttons=main_buttons(),
            )

        user_states.pop(event.sender_id, None)
        pending_media.pop(event.sender_id, None)
        return

    if step == "phone":
        phone = event.text.strip()
        session_path = os.path.join(SESSIONS_DIR, phone)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        try:
            send_code = await client.send_code_request(phone)
            user_states[event.sender_id] = {
                "step": "code",
                "phone": phone,
                "phone_code_hash": send_code.phone_code_hash,
                "client": client,
            }
            await event.respond(
                f"تم ارسال الكود الى {phone}\n"
                "ارسل لي الكود بارقام مفصولة بنقاط (مثال: 1.2.3.4.5) :",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
        except Exception as e:
            await event.respond(f"خطا: {str(e)}", buttons=main_buttons())
            user_states.pop(event.sender_id)

    elif step == "code":
        code = event.text.strip().replace(".", "").replace(" ", "")
        phone = state["phone"]
        phone_code_hash = state["phone_code_hash"]
        client = state["client"]

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            await event.respond(
                f"تم تسجيل الحساب وحفظه : {phone}", buttons=main_buttons()
            )
            user_states.pop(event.sender_id)
            await client.disconnect()
        except SessionPasswordNeededError:
            user_states[event.sender_id]["step"] = "2fa"
            await event.respond(
                "الحساب محمي بتحقق خطوتين .\nارسل كلمة السر :",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
        except PhoneCodeInvalidError:
            await event.respond(
                "الكود غير صحيح . ارسله من جديد :",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
        except Exception as e:
            await event.respond(f"خطا: {str(e)}")
            user_states.pop(event.sender_id)

    elif step == "2fa":
        password = event.text.strip()
        phone = state["phone"]
        client = state["client"]

        try:
            await client.sign_in(password=password)
            await event.respond(
                f"تم تسجيل الحساب وحفظه بنجاح : {phone}", buttons=main_buttons()
            )
            user_states.pop(event.sender_id)
            await client.disconnect()
        except PasswordHashInvalidError:
            await event.respond(
                "كلمة السر خطا . حاول مجددا :",
                buttons=[Button.inline("الغاء", b"cancel")],
            )
        except Exception as e:
            await event.respond(f"خطا: {str(e)}")
            user_states.pop(event.sender_id)

    elif step == "join_link":
        link = event.text.strip()
        accounts = get_saved_accounts()
        if not accounts:
            await event.respond("لا توجد حسابات للصعود !")
            user_states.pop(event.sender_id)
            return

        status_msg = await event.respond("جاري الصعود للمكالمة الصوتية ...")
        phone = accounts[0]
        success = await join_and_call(phone, link)

        await status_msg.delete()
        if success:
            await event.respond("تم الصعود للمكالمة بنجاح", buttons=main_buttons())
        else:
            await event.respond(
                "فشل الصعود . تاكد من ان الرابط صحيح وان الاتصال نشط .",
                buttons=main_buttons(),
            )
        user_states.pop(event.sender_id)

    elif step == "leave_link":
        link = event.text.strip()
        status_msg = await event.respond("جاري نزول الحساب من المكالمة ...")

        leave_count = 0
        for phone in list(active_calls.keys()):
            if active_calls[phone]["link"] == link:
                if await leave_call(phone, link):
                    leave_count += 1

        await status_msg.delete()
        if leave_count:
            await event.respond(
                "تم نزول الحساب من المكالمة بنجاح", buttons=main_buttons()
            )
        else:
            await event.respond(
                "الحساب ليس في هذه المكالمة .", buttons=main_buttons()
            )
        user_states.pop(event.sender_id)


if __name__ == "__main__":
    print("تم تشغيل البوت .")
    bot.run_until_disconnected()
