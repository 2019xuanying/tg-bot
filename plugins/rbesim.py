import logging
import random
import string
import asyncio
import traceback
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

class RbesimLogic:
    @staticmethod
    def generate_random_email():
        """随机生成一个邮箱地址"""
        chars = string.ascii_lowercase + string.digits
        user = ''.join(random.choice(chars) for _ in range(10))
        domains = ["gmail.com", "outlook.com", "yahoo.com", "163.com", "baldur.edu.kg"]
        return f"{user}@{random.choice(domains)}"

    @staticmethod
    def run_process():
        # 使用框架提供的代理 session
        session = get_safe_session(test_url="https://prod-rbesim.com", timeout=10)
        url = "https://prod-rbesim.com/esim-deliver"
        
        # 用户提供的固定 Authorization JWT Token
        jwt_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjJjMjdhZmY1YzlkNGU1MzVkNWRjMmMwNWM1YTE2N2FlMmY1NjgxYzIiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vcmVkbGF6ZXItcHJvZCIsImF1ZCI6InJlZGxhemVyLXByb2QiLCJhdXRoX3RpbWUiOjE3NzIzMzI5OTIsInVzZXJfaWQiOiJXamlLS2xUUmFPTjBOV3c4WmFsYjQzTjdxcWcxIiwic3ViIjoiV2ppS0tsVFJhT04wTld3OFphbGI0M043cXFnMSIsImlhdCI6MTc3MjMzMjk5MiwiZXhwIjoxNzcyMzM2NTkyLCJlbWFpbCI6InNyZHR5ZHlvY2lkeWlAYmFsZHVyLmVkdS5rZyIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmaXJlYmFzZSI6eyJpZGVudGl0aWVzIjp7ImVtYWlsIjpbInNyZHR5ZHlvY2lkeWlAYmFsZHVyLmVkdS5rZyJdfSwic2lnbl9pbl9wcm92aWRlciI6InBhc3N3b3JkIn19.bnmASt8PRVtysPHnmeKu45U-wr6EKb-OxlYQw41Sy-ZG5Qlc90DbSOuDyzk3hilaGrk43YvdicS6jp2mERVBUVm8tN4g6X4O278103apMvpZ1iTnOh9cr2sxH2wKR4eq7sHQi64P06Y_59BZN40o9GdttZpysNeo9r8T-dhw6VRVIDwg0Sbs1d8k6nwual1q5fyh7BhAyisQo1a08Oqnxj0Ho9oU23gDXeqJ9nHa56-b1qbq4U8XYm75vERDflcX-iEjvOc-2EJQZNKoCrHWWepjqeoXPh1StbK84PbCEj93KnGUTAEBVSyWVnCZP7xd01aoCccZGjCfZjXbVuAr4w"
        
        headers = {
            "Host": "prod-rbesim.com",
            "authorization": jwt_token,
            "content-length": "0",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/4.9.2"
        }
        
        email = RbesimLogic.generate_random_email()
        params = {"email": email}
        
        try:
            logger.info(f"[Rbesim] 正在请求提取 eSIM, 使用邮箱: {email}")
            resp = session.post(url, headers=headers, params=params, timeout=15)
            
            # 尝试格式化返回的 JSON 以便于在 TG 中展示
            result_text = resp.text
            try:
                result_text = json.dumps(resp.json(), indent=2, ensure_ascii=False)
            except:
                pass
                
            if resp.ok:
                return True, f"✅ **提取成功 (HTTP {resp.status_code})**\n📧 随机邮箱: `{email}`\n\n📦 **服务器响应**:\n`{result_text[:1500]}`"
            else:
                return False, f"⚠️ **提取失败 (HTTP {resp.status_code})**\n📧 随机邮箱: `{email}`\n\n📦 **错误信息**:\n`{result_text[:1500]}`"
                
        except Exception as e:
            return False, f"网络异常或请求超时: {str(e)}"

# ================= 交互处理 =================

async def rbesim_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """RB eSIM 插件入口菜单"""
    user = update.effective_user
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("rbesim") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 **该功能目前维护中**\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='Markdown'
        )
        return

    text = (
        f"📡 **RB eSIM 提取助手**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"点击下方按钮，系统将自动生成随机邮箱并发起提取请求。"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 一键随机提取 eSIM", callback_data="rbesim_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def rbesim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    if not user_manager.is_authorized(user.id): return
    if not user_manager.get_plugin_status("rbesim") and str(user.id) != str(ADMIN_ID): return

    if data == "rbesim_start":
        user_manager.increment_usage(user.id, user.first_name)
        await query.edit_message_text("⏳ **正在生成随机邮箱并向服务器发送请求...**", parse_mode='Markdown')
        asyncio.create_task(run_rbesim_task(query.message, context))
        return

async def run_rbesim_task(message, context):
    try:
        # 在 Executor 中运行同步网络请求，防止阻塞机器人的主事件循环
        success, result = await asyncio.get_running_loop().run_in_executor(None, RbesimLogic.run_process)
        keyboard = [[InlineKeyboardButton("🔙 返回 RB eSIM 菜单", callback_data="plugin_rbesim_entry")]]
        await message.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 **系统内部错误**: {str(e)}", parse_mode='Markdown')

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(rbesim_callback, pattern="^rbesim_.*"))
    application.add_handler(CallbackQueryHandler(rbesim_menu, pattern="^plugin_rbesim_entry$"))
    print("🔌 RB eSIM 插件已加载")
