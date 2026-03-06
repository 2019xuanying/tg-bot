import logging
import random
import string
import asyncio
import traceback
import json
import urllib.parse
import re
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session
from utils.mail import MailTm

logger = logging.getLogger(__name__)

class RbesimLogic:
    @staticmethod
    def trigger_email(session, email):
        """步骤 1：请求业务后端，向目标邮箱发送登录验证邮件"""
        logger.info(f"[*] Step 1: Triggering login email request for {email}...")
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
                logger.error(f"[-] Failed to send email request (HTTP {resp.status_code}): {resp.text}")
                return False
            logger.info("[+] Trigger successful! Backend accepted the email request.")
            return True
        except Exception as e:
            logger.error(f"[-] Network request exception in Step 1: {str(e)}")
            return False

    @staticmethod
    async def wait_for_oobcode(session, mail_token, timeout=120, check_interval=5):
        """步骤 2：登录邮箱轮询接收邮件，并正则提取 oobCode"""
        logger.info(f"[*] Step 2: Waiting to receive oobCode via email...")
        import time
        start_time = time.time()
        received_count = 0
        last_subject = ""
        
        while time.time() - start_time < timeout:
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            if mails:
                received_count = len(mails)
                logger.info(f"[+] Found {received_count} emails in the inbox. Parsing...")
                
                for mail in mails:
                    # 获取最新的一封邮件
                    mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, mail.get('id'))
                    if mail_detail:
                        body = mail_detail.get('body', '')
                        last_subject = mail_detail.get('subject', 'No Subject')
                        logger.info(f"[*] Checking email with subject: {last_subject}")
                        
                        # 更健壮的正则：Firebase oobCode 只包含字母、数字、下划线和连字符
                        match = re.search(r'oobCode(?:%3D|=)([A-Za-z0-9_-]+)', body)
                        if match:
                            oob_code = match.group(1)
                            logger.info(f"[+] Successfully extracted fresh oobCode: {oob_code[:15]}...")
                            return oob_code, "成功"
                            
                        # 新增逻辑：处理 SendGrid 追踪链接
                        sg_match = re.search(r'(https?://[^\s"\'<>]+sendgrid\.net/ls/click[^\s"\'<>]+)', body)
                        if sg_match:
                            tracking_url = sg_match.group(1)
                            logger.info(f"[*] Found SendGrid tracking link. Resolving redirect...")
                            try:
                                def resolve_url():
                                    return session.get(tracking_url, timeout=15, allow_redirects=True)
                                resp = await asyncio.get_running_loop().run_in_executor(None, resolve_url)
                                
                                # 从最终重定向的 URL 中提取 oobCode
                                final_url = resp.url
                                oob_match = re.search(r'oobCode(?:%3D|=)([A-Za-z0-9_-]+)', final_url)
                                if oob_match:
                                    oob_code = oob_match.group(1)
                                    logger.info(f"[+] Successfully extracted oobCode from resolved URL: {oob_code[:15]}...")
                                    return oob_code, "成功"
                                else:
                                    logger.warning(f"[-] Resolved URL does not contain oobCode: {final_url}")
                            except Exception as e:
                                logger.error(f"[-] Failed to resolve tracking link: {e}")
                        else:
                            logger.warning("[-] Email body does not contain oobCode or SendGrid tracking link.")
            
            await asyncio.sleep(check_interval)
            
        if received_count > 0:
            logger.warning(f"[-] Timeout. Received emails, but no oobCode found. Last subject: {last_subject}")
            return None, f"收到了邮件 (标题: {last_subject[:15]})，但里面没有包含 oobCode，可能格式已变。"
            
        logger.warning("[-] Timeout waiting for email! Inbox is completely empty.")
        return None, "等待超时。邮箱里一封信都没有 (目标网站可能拦截/屏蔽了 Mail.tm 临时邮箱域名)。"

    @staticmethod
    def get_firebase_token(session, email, oob_code):
        """步骤 3：使用 oobCode 向 Firebase 换取身份令牌 (idToken)"""
        logger.info(f"[*] Step 3: Exchanging oobCode for Firebase idToken...")
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
                logger.error(f"[-] Firebase login failed (HTTP {resp.status_code}): {resp.text}")
                return None
                
            data = resp.json()
            id_token = data.get('idToken')
            if id_token:
                logger.info(f"[+] Login flow automated successfully!")
                logger.info(f"[+] Obtained idToken: \n{id_token[:80]}......")
                return id_token
            else:
                logger.error("[-] Response data does not contain idToken")
                return None
                
        except Exception as e:
            logger.error(f"[-] Token exchange failed: {str(e)}")
            return None

    @staticmethod
    async def run_process():
        """执行完整的全自动化流水线"""
        session = await asyncio.get_running_loop().run_in_executor(None, get_safe_session, "https://prod-rbesim.com", 10)
        
        # 1. 自动生成 MailTm 临时邮箱
        email, mail_token = await asyncio.get_running_loop().run_in_executor(None, MailTm.create_account)
        if not email or not mail_token:
            return False, "❌ <b>初始化失败</b>\n无法获取临时邮箱 (Mail.tm API 繁忙或失败)，请稍后重试。"

        logger.info(f"[*] Successfully generated temporary email: {email}")

        # --- [步骤 1] 触发邮件 ---
        trigger_ok = await asyncio.get_running_loop().run_in_executor(None, RbesimLogic.trigger_email, session, email)
        if not trigger_ok:
            return False, f"❌ <b>第一步 (发送登录邮件) 失败</b>\n📧 邮箱: <code>{html.escape(email)}</code>\n⚠️ 请检查日志或代理连接。"
            
        # --- [步骤 2] 等待并提取 oobCode ---
        await asyncio.sleep(3) # Give email delivery some buffer time
        oob_code, wait_msg = await RbesimLogic.wait_for_oobcode(session, mail_token)
        if not oob_code:
            return False, f"❌ <b>第二步 (获取验证码) 失败</b>\n📧 发送至: <code>{html.escape(email)}</code>\n⚠️ 原因: <code>{html.escape(wait_msg)}</code>"

        # --- [步骤 3] 换 idToken ---
        id_token = await asyncio.get_running_loop().run_in_executor(None, RbesimLogic.get_firebase_token, session, email, oob_code)
        if not id_token:
            return False, f"❌ <b>第三步 (换取 Token) 失败</b>\n📧 邮箱: <code>{html.escape(email)}</code>"

        # --- [步骤 4] 请求最终的 eSIM 接口 ---
        logger.info(f"[*] Step 4: Requesting esim-deliver with new Token...")
        url = "https://prod-rbesim.com/esim-deliver"
        headers = {
            "Host": "prod-rbesim.com",
            "authorization": id_token, # 注入最新获取的 token
            "content-length": "0",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/4.9.2"
        }
        params = {"email": email}
        
        try:
            resp = await asyncio.get_running_loop().run_in_executor(None, session.post, url, headers, params, 20)
            
            if resp.ok:
                # 尝试用正则提取标准 LPA (例如: 1$smdp.com$0000-0000-0000)
                lpa_match = re.search(r'(1\$[\w\.\-]+\$[\w\.\-]+)', resp.text)
                
                if lpa_match:
                    lpa_info = lpa_match.group(1)
                else:
                    # 如果没匹配到 LPA，可能是 JSON 格式变了，截取部分原始返回以免消息超长
                    lpa_info = f"未能自动解析，原始数据：\n{resp.text[:500]}"
                
                msg = (
                    f"🎉 <b>全自动提取成功！</b>\n"
                    f"📧 <b>邮箱</b>: <code>{html.escape(email)}</code>\n\n"
                    f"📡 <b>LPA 安装代码</b>:\n<code>{html.escape(lpa_info)}</code>\n\n"
                    f"🔑 <b>Firebase Token</b>:\n<code>{html.escape(id_token)}</code>"
                )
                return True, msg
            else:
                return False, f"⚠️ <b>提取被拒 (HTTP {resp.status_code})</b>\n📧 邮箱: <code>{html.escape(email)}</code>\n\n📦 <b>错误信息</b>:\n<code>{html.escape(resp.text[:500])}</code>"
                
        except Exception as e:
            return False, f"❌ <b>最终请求失败 (超时或网络异常)</b>: <code>{html.escape(str(e))}</code>"

# ================= 交互处理 =================

async def rbesim_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """RB eSIM 插件入口菜单"""
    user = update.effective_user
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("rbesim") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 <b>该功能目前维护中</b>\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='HTML'
        )
        return

    text = (
        f"📡 <b>RB eSIM 提取助手</b>\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"流程说明：\n"
        f"1️⃣ 自动获取 Mail.tm 临时邮箱\n"
        f"2️⃣ 触发登录验证邮件并自动监听收件箱\n"
        f"3️⃣ 追踪跳转并换取 Firebase idToken\n"
        f"4️⃣ 携带凭证请求发货，提取 LPA 代码\n\n"
        f"点击下方按钮，启动全自动流水线 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 启动全自动提取", callback_data="rbesim_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

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
            "⏳ <b>正在执行全自动任务...</b>\n"
            "📡 正在获取临时邮箱并与服务器进行交互，此过程可能需要 15~60 秒，请耐心等待...", 
            parse_mode='HTML'
        )
        asyncio.create_task(run_rbesim_task(query.message, context))
        return

async def run_rbesim_task(message, context):
    try:
        success, result = await RbesimLogic.run_process()
        keyboard = [[InlineKeyboardButton("🔙 返回 RB eSIM 菜单", callback_data="plugin_rbesim_entry")]]
        await message.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 <b>系统内部错误</b>: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(rbesim_callback, pattern="^rbesim_.*"))
    application.add_handler(CallbackQueryHandler(rbesim_menu, pattern="^plugin_rbesim_entry$"))
    print("🔌 RB eSIM (Mail.tm 自动收信版) 插件已加载")
