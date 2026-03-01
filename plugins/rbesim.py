import logging
import random
import string
import asyncio
import traceback
import json
import urllib.parse
import re
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
        domains = ["gmail.com", "outlook.com", "yahoo.com", "163.com", "baldur.edu.kg", "zenvex.edu.pl"]
        return f"{user}@{random.choice(domains)}"

    @staticmethod
    def get_oob_code(session, email):
        """步骤 1：触发邮件并截取 oobCode"""
        logger.info(f"[Rbesim] 步骤1: 正在为 {email} 触发登录邮件请求...")
        encoded_email = urllib.parse.quote(email)
        url = f"https://prod-rbesim.com/auth/send-email?email={encoded_email}"
        
        headers = {
            "Host": "prod-rbesim.com",
            "user-agent": "okhttp/4.9.2",
            "accept-encoding": "gzip",
            "content-length": "0"
        }
        
        try:
            resp = session.post(url, headers=headers, timeout=15)
            if not resp.ok:
                return None, f"请求发送邮件失败 (HTTP {resp.status_code}): {resp.text}"
            
            data = resp.json()
            auth_link = data.get("link")
            if not auth_link:
                return None, "响应中没有找到 link 字段！"
            
            # 提取 oobCode
            match = re.search(r'oobCode(?:%3D|=)([^%&]+)', auth_link)
            if match:
                oob_code = match.group(1)
                logger.info(f"[Rbesim] 成功提取 oobCode: {oob_code[:10]}...")
                return oob_code, "成功"
            else:
                return None, "正则匹配 oobCode 失败！"
                
        except Exception as e:
            return None, f"网络请求异常: {str(e)}"

    @staticmethod
    def get_firebase_token(session, email, oob_code):
        """步骤 2：用 oobCode 兑换 Firebase idToken"""
        logger.info(f"[Rbesim] 步骤2: 正在使用 oobCode 换取 idToken...")
        api_key = "AIzaSyDSQtoo2mwKFxq5mgq9G5qx1vyDP2kdlBI"
        url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/emailLinkSignin?key={api_key}"
        
        headers = {
            "Content-Type": "application/json",
            "X-Android-Package": "com.kitemobile",
            "X-Android-Cert": "9139793793EC1D50C7E82B93FF7FEE5B957791E1",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; RMX2117 Build/QP1A.190711.020)",
        }
        
        payload = {
            "email": email,
            "oobCode": oob_code,
            "clientType": "CLIENT_TYPE_ANDROID"
        }

        try:
            resp = session.post(url, headers=headers, json=payload, timeout=15)
            if not resp.ok:
                return None, f"Firebase登录失败 (HTTP {resp.status_code}): {resp.text}"
                
            data = resp.json()
            id_token = data.get('idToken')
            if id_token:
                logger.info(f"[Rbesim] 成功获取 idToken。")
                return id_token, "成功"
            else:
                return None, "响应数据中不包含 idToken"
                
        except Exception as e:
            return None, f"网络请求异常: {str(e)}"

    @staticmethod
    def run_process():
        """执行完整的全自动化流水线"""
        session = get_safe_session(test_url="https://prod-rbesim.com", timeout=10)
        email = RbesimLogic.generate_random_email()
        
        # --- [步骤 1] 拿 oobCode ---
        oob_code, msg1 = RbesimLogic.get_oob_code(session, email)
        if not oob_code:
            return False, f"❌ **第一步 (获取 oobCode) 失败**\n📧 邮箱: `{email}`\n⚠️ 原因: `{msg1}`"
            
        # --- [步骤 2] 换 idToken ---
        id_token, msg2 = RbesimLogic.get_firebase_token(session, email, oob_code)
        if not id_token:
            return False, f"❌ **第二步 (换取 Token) 失败**\n📧 邮箱: `{email}`\n⚠️ 原因: `{msg2}`"

        # --- [步骤 3] 请求最终的 eSIM 接口 ---
        logger.info(f"[Rbesim] 步骤3: 携带新 Token 请求 esim-deliver 接口...")
        url = "https://prod-rbesim.com/esim-deliver"
        headers = {
            "Host": "prod-rbesim.com",
            "authorization": id_token, # 这里注入最新获取的 token
            "content-length": "0",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/4.9.2"
        }
        params = {"email": email}
        
        try:
            resp = session.post(url, headers=headers, params=params, timeout=20)
            
            # 格式化返回值以便于显示
            result_text = resp.text
            try:
                result_text = json.dumps(resp.json(), indent=2, ensure_ascii=False)
            except: pass
                
            if resp.ok:
                return True, f"🎉 **全自动提取成功 (HTTP {resp.status_code})**\n📧 邮箱: `{email}`\n\n📦 **服务器发货响应**:\n`{result_text[:1500]}`"
            else:
                return False, f"⚠️ **提取被拒 (HTTP {resp.status_code})**\n📧 邮箱: `{email}`\n\n📦 **错误信息**:\n`{result_text[:1500]}`"
                
        except Exception as e:
            return False, f"❌ **最终请求失败 (超时或网络异常)**: {str(e)}"

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
        f"📡 **RB eSIM 提取助手 (全自动版)**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"流程说明：\n"
        f"1️⃣ 随机生成邮箱并向服务器发送注册请求\n"
        f"2️⃣ 截获注册链接中的安全码 (oobCode)\n"
        f"3️⃣ 动态换取 Firebase 登录凭证 (idToken)\n"
        f"4️⃣ 携带新鲜凭证请求 eSIM 发货\n\n"
        f"点击下方按钮，启动全自动流水线 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 启动全自动提取", callback_data="rbesim_start")],
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
        await query.edit_message_text(
            "⏳ **正在执行全自动任务...**\n"
            "📡 正在与服务器进行 Token 交换和鉴权，请稍候约 5~10 秒...", 
            parse_mode='Markdown'
        )
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
    print("🔌 RB eSIM (全自动免过期版) 插件已加载")
