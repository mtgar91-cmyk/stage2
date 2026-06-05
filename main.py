import os
import asyncio
import logging
from telethon import TelegramClient, events, Button, functions, types, utils
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, UserAlreadyParticipantError
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID: int = int(os.getenv("API_ID", "38720187"))
API_HASH: str = os.getenv("API_HASH", "a5c27bc42b391f32db86befcabc68094")
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8561472222:AAFt61q6PyYYueHRScMZ4sJDE4CjZfGIC_0")
ADMIN_ID: int = int(os.getenv("OWNER_ID", "6668195885"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@helium/heliumdb?sslmode=disable")

SESSIONS_DIR = 'sessions'
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

user_states = {}
active_calls = {}
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
        [Button.inline("اضافة حساب", b"login")],
        [Button.inline("صعود اتصال", b"call_up"), Button.inline("نزول اتصال", b"call_down")],
        [Button.url("مطور البوت", "https://t.me/d_k7k")],
        [Button.inline("عرض حساباتي", b"show_accs"), Button.inline("مسح حساب", b"delete_acc")]
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
        user_states[event.sender_id] = {'step': 'phone'}
        await event.edit("أرسل لي رقم الهاتف مع رمز الدولة:", buttons=[Button.inline("إلغاء", b"cancel")])

    elif data == b"cancel":
        user_states.pop(event.sender_id, None)
        await event.edit("تم الإلغاء .", buttons=main_buttons())

    elif data == b"show_accs":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد لديك حسابات .", alert=True)
            return

        text = "حساباتك :\n"
        for acc in accounts:
            text += f"• {acc}\n"

        back_buttons = [[Button.inline("باگ", b"back_main")]]
        await event.edit(text, buttons=back_buttons)

    elif data == b"back_main":
        await event.edit("ok :", buttons=main_buttons())

    elif data == b"delete_acc":
        accounts = get_saved_accounts()
        if not accounts:
            await event.answer("لا توجد حسابات .", alert=True)
            return
        buttons = [[Button.inline(acc, f"del_{acc}".encode())] for acc in accounts]
        buttons.append([Button.inline("باگ", b"cancel")])
        await event.edit("ok :", buttons=buttons)

    elif data.startswith(b"del_"):
        acc_name = data.decode().replace("del_", "")
        session_path = os.path.join(SESSIONS_DIR, f"{acc_name}.session")
        if os.path.exists(session_path):
            os.remove(session_path)
            active_calls.pop(acc_name, None)
            await event.answer(f"- تم مسح الحساب {acc_name} بنجاح .", alert=True)
            await event.edit("ok :", buttons=main_buttons())

    elif data == b"call_up":
        user_states[event.sender_id] = {'step': 'join_link'}
        await event.edit("دزلي رابط القناة او الگروب :", buttons=[Button.inline("إلغاء", b"cancel")])

    elif data == b"call_down":
        user_states[event.sender_id] = {'step': 'leave_link'}
        await event.edit("دزلي رابط القناة او الگروب :", buttons=[Button.inline("إلغاء", b"cancel")])

@bot.on(events.NewMessage)
async def message_handler(event):
    if event.sender_id != ADMIN_ID or event.sender_id not in user_states:
        return

    state = user_states[event.sender_id]
    step = state.get('step')

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
            await event.respond(f"تم إرسال الكود الى {phone} \nارسل لي الكود الذي وصلك بأرقام مفصولة :", buttons=[Button.inline("إلغاء", b"cancel")])
        except Exception as e:
            await event.respond(f"خطأ: {str(e)}", buttons=main_buttons())
            user_states.pop(event.sender_id)

    elif step == 'code':
        code = event.text.strip()
        phone = state['phone']
        phone_code_hash = state['phone_code_hash']
        client = state['client']

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            await event.respond(f"- تم تسجيل الحساب وحفظة : {phone}")
            user_states.pop(event.sender_id)
            await client.disconnect()
        except SessionPasswordNeededError:
            user_states[event.sender_id]['step'] = '2fa'
            await event.respond("- ارسل لي التحقق بخطوتين :", buttons=[Button.inline("إلغاء", b"cancel")])
        except PhoneCodeInvalidError:
            await event.respond("- الكود غير صحيح .", buttons=[Button.inline("إلغاء", b"cancel")])
        except Exception as e:
            await event.respond(f"خطأ: {str(e)}")
            user_states.pop(event.sender_id)

    elif step == '2fa':
        password = event.text.strip()
        phone = state['phone']
        client = state['client']

        try:
            await client.sign_in(password=password)
            await event.respond(f"- تم تسجيل الحساب وحفظة بنجاح : {phone}")
            user_states.pop(event.sender_id)
            await client.disconnect()
        except PasswordHashInvalidError:
            await event.respond("كلمة السر غير خطأ .", buttons=[Button.inline("إلغاء", b"cancel")])
        except Exception as e:
            await event.respond(f"خطأ: {str(e)}")
            user_states.pop(event.sender_id)

    elif step == 'join_link':
        link = event.text.strip()
        accounts = get_saved_accounts()
        if not accounts:
            await event.respond("لا توجد حسابات للصعود !")
            user_states.pop(event.sender_id)
            return

        status_msg = await event.respond(f"بدأت بنجاح !\n- {len(accounts)} حساب سيقوم بالصعود للمكالمة الصوتية .")

        success_count = 0
        for acc in accounts:
            if await join_and_call(acc, link):
                success_count += 1
            await asyncio.sleep(2)

        await status_msg.delete()
        await event.respond(f"- اكتملت العملية ! عدد الحسابات التي صعدت بنجاح: {success_count}")
        user_states.pop(event.sender_id)

    elif step == 'leave_link':
        link = event.text.strip()
        status_msg = await event.respond(f"- جاري نزول الحسابات تدريجياً .")

        leave_count = 0
        for phone in list(active_calls.keys()):
            if active_calls[phone]['link'] == link:
                if await leave_call(phone, link):
                    leave_count += 1

        await status_msg.delete()
        await event.respond(f"أكتملت ! {leave_count} حساب نزل من المكالمة بنجاح .")
        user_states.pop(event.sender_id)

if __name__ == '__main__':
    print("تم تشغيل .")
    bot.run_until_disconnected()
