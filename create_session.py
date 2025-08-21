from telethon import TelegramClient

api_id = api_id = 23994880
api_hash = '74f8e2a57e0f9d63cf45b53a5ffee741'
phone = '+79671333376'  # твой номер

client = TelegramClient('userbot_session', api_id, api_hash)

async def main():
    await client.start(phone=phone)  # тут Telethon сам попросит код
    me = await client.get_me()
    print("Вход успешен, привет", me.username)

import asyncio
asyncio.run(main()) 