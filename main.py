import asyncio
import base58
import sys
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.rpc.async_api import AsyncClient
import aiohttp
from aiogram import F

# توكن البوت
BOT_TOKEN = "7428227318:AAG8CY-yZmB-1Vpc1-6WfZ3HT8aT_DNi5kY"

# قائمة RPC URLs
RPC_URLS = [
    "https://mainnet.helius-rpc.com/?api-key=98a1181b-f456-4689-9902-0d42ed128cb1",
    "https://mainnet.helius-rpc.com/?api-key=78bacaf8-98fc-4651-b665-531d048dbc60",
    "https://mainnet.helius-rpc.com/?api-key=4a1443a2-50f7-4d0b-bf15-028f0dcbdeb8",
    "https://solana-mainnet.g.alchemy.com/v2/A9xPBcSGQkSIa9owFAab88-KbrZWw7iL",
    "https://solana-mainnet.g.alchemy.com/v2/QMBCCev_Ig1zGFssTed57KsriUzCryCj",
]

current_rpc_index = 0
BASE58_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# حالة المعالجة لكل مستخدم
user_status = {}

# تعريف البوت والديسباتشر
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def validate_solana_key(key: str) -> bool:
    """التحقق من صحة مفتاح Solana"""
    try:
        decoded = base58.b58decode(key)
        return len(decoded) == 64
    except:
        return False

async def check_wallet_activity(key: str) -> dict:
    """فحص نشاط المحفظة"""
    global current_rpc_index
    
    if not validate_solana_key(key):
        return {"active": False, "error": "مفتاح غير صالح"}
    
    try:
        secret_key = base58.b58decode(key)
        keypair = Keypair.from_secret_key(secret_key)
        address = str(keypair.public_key)
        
        # تجربة كل RPC حتى نجد واحد يعمل
        for i in range(len(RPC_URLS)):
            try:
                rpc_index = (current_rpc_index + i) % len(RPC_URLS)
                client = AsyncClient(RPC_URLS[rpc_index])
                
                # الحصول على الرصيد وسجل المعاملات
                balance_response = await client.get_balance(PublicKey(address))
                signatures_response = await client.get_signatures_for_address(
                    PublicKey(address), limit=1
                )
                
                await client.close()
                
                balance = balance_response['result']['value'] / 1_000_000_000
                has_transactions = len(signatures_response['result']) > 0
                
                current_rpc_index = (rpc_index + 1) % len(RPC_URLS)
                
                return {
                    "active": True,
                    "address": address,
                    "balance": balance,
                    "has_transactions": has_transactions,
                    "is_active": balance > 0 or has_transactions
                }
                
            except Exception as e:
                continue
        
        return {"active": False, "error": "فشل الاتصال بـ RPC"}
        
    except Exception as e:
        return {"active": False, "error": str(e)}

async def smart_key_fix(user_id: str, bad_key: str):
    """الإصلاح الذكي للمفتاح"""
    if len(bad_key) not in [87, 88]:
        yield "error", "يجب أن يكون طول المفتاح 87 أو 88 حرفاً"
        return
    
    user_status[user_id] = {
        "is_fixing": True,
        "found_count": 0,
        "total_checked": 0,
        "results": []
    }
    
    results = []
    
    # 1. فحص إضافة حرف مفقود (إذا كان طول المفتاح 87)
    if len(bad_key) == 87:
        total_keys = (len(bad_key) + 1) * len(BASE58_CHARS)
        checked_keys = 0
        
        for i in range(len(bad_key) + 1):
            prefix = bad_key[:i]
            suffix = bad_key[i:]
            
            for char in BASE58_CHARS:
                checked_keys += 1
                candidate = prefix + char + suffix
                
                user_status[user_id]["total_checked"] = checked_keys
                yield "progress", f"🔍 فحص إضافة حرف مفقود: {checked_keys}/{total_keys}"
                
                if validate_solana_key(candidate):
                    activity = await check_wallet_activity(candidate)
                    if activity.get("active") and activity.get("is_active"):
                        results.append({
                            "key": candidate,
                            "address": activity["address"],
                            "balance": activity["balance"]
                        })
                        user_status[user_id]["found_count"] = len(results)
                        yield "found", f"✅ تم العثور على مفتاح نشط! ({len(results)})"
                
                await asyncio.sleep(0.01)  # تأخير قصير لمنع rate limiting
    
    # 2. تجربة تغيير حرف واحد
    total_keys_one = len(bad_key) * (len(BASE58_CHARS) - 1)
    checked_keys_one = 0
    
    for i in range(len(bad_key)):
        prefix = bad_key[:i]
        suffix = bad_key[i+1:]
        
        for char in BASE58_CHARS:
            if char == bad_key[i]:
                continue
            
            checked_keys_one += 1
            candidate = prefix + char + suffix
            
            user_status[user_id]["total_checked"] += 1
            total_checked = user_status[user_id]["total_checked"]
            yield "progress", f"🔍 فحص تغيير حرف واحد: {total_checked}"
            
            if validate_solana_key(candidate):
                activity = await check_wallet_activity(candidate)
                if activity.get("active") and activity.get("is_active"):
                    results.append({
                        "key": candidate,
                        "address": activity["address"],
                        "balance": activity["balance"]
                    })
                    user_status[user_id]["found_count"] = len(results)
                    yield "found", f"✅ تم العثور على مفتاح نشط! ({len(results)})"
            
            await asyncio.sleep(0.01)
    
    # 3. تجربة تغيير حرفين متجاورين (عينة فقط للسرعة)
    total_keys_two = (len(bad_key) - 1) * len(BASE58_CHARS) * 5  # عينة 5 أحرف فقط لكل موضع
    checked_keys_two = 0
    
    for i in range(len(bad_key) - 1):
        prefix = bad_key[:i]
        suffix = bad_key[i+2:]
        
        for j in range(len(BASE58_CHARS)):
            if j % 10 != 0:  # نأخذ عينة فقط (كل 10 أحرف)
                continue
                
            a = BASE58_CHARS[j]
            for k in range(len(BASE58_CHARS)):
                if k % 10 != 0:  # نأخذ عينة فقط
                    continue
                    
                b = BASE58_CHARS[k]
                checked_keys_two += 1
                candidate = prefix + a + b + suffix
                
                user_status[user_id]["total_checked"] += 1
                total_checked = user_status[user_id]["total_checked"]
                yield "progress", f"🔍 فحص تغيير حرفين: {total_checked}"
                
                if validate_solana_key(candidate):
                    activity = await check_wallet_activity(candidate)
                    if activity.get("active") and activity.get("is_active"):
                        results.append({
                            "key": candidate,
                            "address": activity["address"],
                            "balance": activity["balance"]
                        })
                        user_status[user_id]["found_count"] = len(results)
                        yield "found", f"✅ تم العثور على مفتاح نشط! ({len(results)})"
                
                await asyncio.sleep(0.01)
    
    user_status[user_id]["is_fixing"] = False
    user_status[user_id]["results"] = results
    
    if results:
        yield "complete", results
    else:
        yield "complete", "❌ لم يتم العثور على مفاتيح نشطة"

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """بدء البوت"""
    welcome_text = """
    *🔧 Solana Key Fixer Bot*
    
    أرسل لي مفتاح Solana الخاص (Base58) وسأقوم بـ:
    1. إصلاح المفتاح الذكي (إذا كان به أحرف ناقصة أو خاطئة)
    2. البحث عن المفتاح الصالح والنشط
    3. عرض العنوان والرصيد
    
    *الميزات:*
    • فحص نشاط المحفظة (رصيد + معاملات)
    • تحديث التقدم في رسالة واحدة
    • عرض النتائج بصيغة Markdown
    
    *أرسل المفتاح الآن...*
    """
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(F.text)
async def process_key(message: Message):
    """معالجة المفتاح المرسل"""
    user_id = str(message.from_user.id)
    bad_key = message.text.strip()
    
    # إلغاء أي عملية سابقة
    if user_id in user_status and user_status[user_id].get("is_fixing"):
        await message.answer("⚠️ لديك عملية جارية بالفعل. يرجى الانتظار...")
        return
    
    # فحص المفتاح مباشرة أولاً
    activity = await check_wallet_activity(bad_key)
    if activity.get("active"):
        if activity.get("is_active"):
            result_text = f"""
            *✅ المفتاح صالح ونشط!*
            
            *المفتاح:* `{bad_key}`
            *العنوان:* `{activity['address']}`
            *الرصيد:* `{activity['balance']:.9f} SOL`
            *لديه معاملات:* {'نعم' if activity['has_transactions'] else 'لا'}
            
            المحفظة نشطة ولها رصيد أو معاملات.
            """
        else:
            result_text = f"""
            *ℹ️ المفتاح صالح ولكنه غير نشط*
            
            *المفتاح:* `{bad_key}`
            *العنوان:* `{activity['address']}`
            *الرصيد:* `{activity['balance']:.9f} SOL`
            *لديه معاملات:* {'نعم' if activity['has_transactions'] else 'لا'}
            
            المحفظة ليس لها رصيد أو معاملات.
            """
        await message.answer(result_text, parse_mode="Markdown")
        return
    
    # إذا كان المفتاح غير صالح، نبدأ عملية الإصلاح
    await message.answer(f"*🔍 بدء الإصلاح الذكي للمفتاح...*\n\nالمفتاح المرسل: `{bad_key}`", parse_mode="Markdown")
    
    # إنشاء رسالة التقدم
    progress_msg = await message.answer("*⏳ جاري المعالجة...*\n\n🔍 المحافظ الصالحة: 0\n📊 تم فحص: 0", parse_mode="Markdown")
    
    # تشغيل عملية الإصلاح
    found_keys = []
    try:
        async for status_type, status_data in smart_key_fix(user_id, bad_key):
            if status_type == "progress":
                # تحديث رسالة التقدم
                found_count = user_status[user_id]["found_count"]
                total_checked = user_status[user_id]["total_checked"]
                update_text = f"*⏳ جاري المعالجة...*\n\n🔍 المحافظ الصالحة: {found_count}\n📊 تم فحص: {total_checked}\n\n{status_data}"
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=progress_msg.message_id,
                    text=update_text,
                    parse_mode="Markdown"
                )
            
            elif status_type == "found":
                found_count = user_status[user_id]["found_count"]
                update_text = f"*⏳ جاري المعالجة...*\n\n✅ {status_data}\n📊 تم فحص: {user_status[user_id]['total_checked']}"
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=progress_msg.message_id,
                    text=update_text,
                    parse_mode="Markdown"
                )
            
            elif status_type == "complete":
                if isinstance(status_data, list) and status_data:
                    # عرض النتائج
                    results_text = f"*🎉 تم الانتهاء!*\n\nتم العثور على {len(status_data)} مفتاح نشط:\n\n"
                    
                    for i, result in enumerate(status_data, 1):
                        results_text += f"*المفتاح {i}:*\n"
                        results_text += f"`{result['key']}`\n"
                        results_text += f"*العنوان:* `{result['address']}`\n"
                        results_text += f"*الرصيد:* `{result['balance']:.9f} SOL`\n\n"
                    
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=progress_msg.message_id,
                        text=results_text,
                        parse_mode="Markdown"
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=progress_msg.message_id,
                        text="*❌ لم يتم العثور على مفاتيح نشطة*\n\nلم أتمكن من إيجاد أي مفتاح صالح ونشط من الاحتمالات.",
                        parse_mode="Markdown"
                    )
            
            elif status_type == "error":
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=progress_msg.message_id,
                    text=f"*❌ خطأ:* {status_data}",
                    parse_mode="Markdown"
                )
                return
                
    except Exception as e:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            text=f"*❌ حدث خطأ غير متوقع:*\n\n{str(e)}",
            parse_mode="Markdown"
        )
    finally:
        if user_id in user_status:
            user_status[user_id]["is_fixing"] = False

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    """إلغاء العملية الحالية"""
    user_id = str(message.from_user.id)
    
    if user_id in user_status and user_status[user_id].get("is_fixing"):
        user_status[user_id]["is_fixing"] = False
        await message.answer("✅ تم إلغاء العملية الحالية.")
    else:
        await message.answer("⚠️ لا توجد عملية جارية.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """عرض المساعدة"""
    help_text = """
    *🔧 Solana Key Fixer Bot - المساعدة*
    
    *الأوامر المتاحة:*
    /start - بدء البوت وعرض التعليمات
    /help - عرض هذه الرسالة
    /cancel - إلغاء العملية الحالية
    
    *كيفية الاستخدام:*
    1. أرسل مفتاح Solana الخاص (Base58)
    2. سيقوم البوت بفحص المفتاح مباشرة
    3. إذا كان المفتاح غير صالح، سيقوم بالإصلاح الذكي
    4. يتم تحديث التقدم في رسالة واحدة
    5. سيتم عرض النتائج النهائية
    
    *ملاحظات:*
    • المفاتيح النشطة هي التي لها رصيد أو معاملات
    • يتم حفظ النتائج في رسالة واحدة فقط
    • العملية قد تستغرق بعض الوقت
    
    *أرسل المفتاح الآن للبدء...*
    """
    await message.answer(help_text, parse_mode="Markdown")

async def main():
    """الدالة الرئيسية"""
    print("🚀 Solana Key Fixer Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # تثبيت المكتبات المطلوبة
    required_packages = [
        "aiogram",
        "solana",
        "base58",
        "aiohttp"
    ]
    
    print("📦 تأكد من تثبيت المكتبات المطلوبة:")
    for package in required_packages:
        print(f"  pip install {package}")
    
    # تشغيل البوت
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 إيقاف البوت...")
    except Exception as e:
        print(f"❌ خطأ: {e}")
