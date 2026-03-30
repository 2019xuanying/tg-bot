import logging
import base64
import hmac
import hashlib
import time
import uuid
import json
import requests
import random
import string
import asyncio
import traceback
import html
from urllib.parse import quote
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

NOMAD_STATE_NONE = 0
NOMAD_STATE_WAIT_EMAIL = 1
NOMAD_STATE_WAIT_OTP = 2

# ================= 动态算号器 (底层 Crypto 引擎) =================
def get_crypto_param(p1, p2, p3, p4):
    combined = p1 + p2 + p3 + p4
    combined += "=" * ((4 - len(combined) % 4) % 4)
    first_decode_bytes = base64.b64decode(combined)
    padding_len = (4 - len(first_decode_bytes) % 4) % 4
    first_decode_bytes += b"=" * padding_len
    return base64.b64decode(first_decode_bytes)

FINAL_AES_KEY = get_crypto_param("TURVeVl6", "TTRNell5", "TXpGak5", "ETXpNZw")
FINAL_AES_IV  = get_crypto_param("WVRWa1lq", "RXpORGM1", "T1dNeFlt", "RTFZdw")

# ================= 伪装数据池 (用于绕过特征风控) =================
FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson"]

# 真实的市面主流安卓机型指纹库
DEVICE_PROFILES = [
    "Samsung,SM-S918B,Android 14",     # S23 Ultra
    "Google,Pixel 7 Pro,Android 13",   # Pixel 7 Pro
    "Xiaomi,2210132G,Android 13",      # Xiaomi 13
    "OnePlus,LE2120,Android 12",       # OnePlus 9 Pro
    "vivo,V2050,Android 11",           # vivo X60
    "OPPO,PEXM00,Android 11",          # OPPO Reno6
    "motorola,XT2125-4,Android 12",    # Moto G100
    "TCL,T508N,Android 13"             # 原设备
]

# ================= 核心业务逻辑 =================
class NomadBotCore:
    def __init__(self):
        self.base_url = "https://api.getnomad.app"
        # 使用框架统一的代理 Session
        self.session = get_safe_session(test_url="https://api.getnomad.app", timeout=10)
        
        # 1. 每次运行生成全新的硬件指纹
        self.device_id = str(uuid.uuid4())
        self.device_info = random.choice(DEVICE_PROFILES)
        
        # 2. 注入伪装的 Header
        self.session.headers.update({
            "Host": "api.getnomad.app",
            "Accept-Language": "zh-Hans",
            "x-app-ver": "10.8.1",          # 版本号必须固定最新
            "x-device-info": self.device_info, # 注入随机抽取的手机型号
            "x-request-source": "android",
            "x-channel-id": "nomad-android",
            "User-Agent": "Ktor client",
            "Content-Type": "application/json",
            "Accept": "application/json,application/json",
            "Connection": "Keep-Alive"
        })
        logger.info(f"[*] 已生成伪装设备: {self.device_info} | UUID: {self.device_id[:8]}...")

    def _get_security_headers(self):
        """动态生成防篡改签名"""
        payload = {
            "timestamp": int(time.time()),
            "token": str(uuid.uuid4()),
            "x-device-token": self.device_id
        }
        json_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')

        page_token = hmac.new(FINAL_AES_KEY, json_bytes, hashlib.sha256).hexdigest()
        cipher = AES.new(FINAL_AES_KEY, AES.MODE_CBC, FINAL_AES_IV)
        padded_data = pad(json_bytes, AES.block_size, style='pkcs7')
        app_tag = base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

        return {
            "x-page-token": page_token,
            "x-app-tag": app_tag,
            "x-device-token": self.device_id
        }

    def generate_identity(self, email):
        """生成随机的逼真人设"""
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        # 随机生成一个包含大小写字母和数字的复杂密码
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + "A1!"
        
        logger.info(f"[*] 已生成伪装人设: {first_name} {last_name}")
        return {
            "email": email, 
            "password": password,
            "first_name": first_name,
            "last_name": last_name
        }

    def step1_request_otp(self, email):
        url = f"{self.base_url}/account/api/v3/user/get_verification_code"
        payload = {"email": email, "validation_case": "sign_up"}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                return True, "验证码已发送"
            return False, f"发送失败 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"请求异常: {e}"

    def step2_check_otp(self, email, code):
        url = f"{self.base_url}/account/api/v3/user/check_verification_code"
        payload = {"email": email, "code": code}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                return True, "验证码校验通过"
            return False, f"校验失败 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"请求异常: {e}"

    def step3_sign_up(self, user, code):
        url = f"{self.base_url}/account/api/v3/user/sign_up"
        payload = {
            "email": user['email'],
            "password": user['password'],
            "verification_code": code,
            "first_name": user['first_name'],
            "last_name": user['last_name'],
            "subscribe_to_feed": True
        }
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                token = resp.json().get("data", {}).get("access_token")
                if token:
                    self.session.headers.update({"Authorization": f"Bearer {token}"})
                    return True, "注册成功"
            return False, f"注册失败: {resp.text}"
        except Exception as e:
            return False, f"请求异常: {e}"

    def step3_5_warmup(self):
        url = f"{self.base_url}/product/api/v3/trial/get_trial_plan_info"
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        try:
            resp = self.session.post(url, json={}, headers=headers, timeout=15)
            if resp.status_code == 200:
                return True, "预热完成"
            return False, "预热异常"
        except Exception as e:
            return False, f"请求异常: {e}"

    def step4_create_order(self, offer_id="c78816f2-245b-4300-9c31-7769df5b7c79"):
        url = f"{self.base_url}/order/api/v3/order/create_master_order"
        payload = {
            "offered_products": [
                {"offered_id": offer_id, "quantity": 1, "coverage": "CN"}
            ],
            "currency": "USD",
            "discount": {},
            "device": {"type": "Android", "id": self.device_id}
        }
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())

        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 202:
                master_id = resp.json().get("data", {}).get("master_order_id")
                return True, master_id
            
            err_msg = resp.text
            if "5005" in err_msg:
                err_msg += "\n\n💡 **提示**: 触发 5005 风控！此邮箱后缀或当前代理 IP 已被官方判定为薅羊毛黑名单，请更换真实大厂邮箱及干净代理重新尝试。"
            return False, err_msg
        except Exception as e:
            return False, f"请求异常: {e}"

    def step5_get_esim(self, master_id):
        url = f"{self.base_url}/order/api/v3/order/get_master_orders"
        payload = {
            "master_order_ids": [master_id],
            "product_categories": ["esim"]
        }
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())

        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                orders = resp.json()['data']['master_orders'][0]['orders'][0]
                esim = orders['esim_info']
                return True, {
                    "name": orders['plan_info']['name'],
                    "iccid": esim['iccid'],
                    "lpa": esim['qr_data']
                }
            return False, f"提取失败: {resp.text}"
        except Exception as e:
            return False, f"解析异常: {e}"

# ================= 交互与调度逻辑 =================

async def nomad_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['nomad_state'] = NOMAD_STATE_NONE
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("nomad") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text("🛑 **维护中**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode='Markdown')
        return

    text = (
        f"🌍 **Nomad 0元试用助手**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"⚠️ **【极其重要】**\n"
        f"官方风控极严！**绝对不可使用临时邮箱！**\n"
        f"请务必准备真实的 Gmail, Outlook 等大厂邮箱，并且保证当前机器人的代理 IP 干净，否则大概率触发 5005 风控错误。"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 手动输入邮箱获取", callback_data="nomad_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def nomad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    if not user_manager.is_authorized(user.id): return
    if not user_manager.get_plugin_status("nomad") and str(user.id) != str(ADMIN_ID): return

    if query.data == "nomad_start":
        context.user_data['nomad_state'] = NOMAD_STATE_WAIT_EMAIL
        await query.edit_message_text(
            "📝 **请输入您准备好的真实邮箱：**\n"
            "(系统将向此邮箱发送注册验证码)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_nomad_entry")]]),
            parse_mode='Markdown'
        )

async def process_nomad_flow(status_msg, context, user, email, otp_code):
    bot = context.user_data.get('nomad_bot')
    user_identity = context.user_data.get('nomad_user_data')
    if not bot or not user_identity:
        await status_msg.edit_text("⚠️ 会话已过期，请重新发起任务。")
        return

    try:
        # Step 2
        await status_msg.edit_text("⏳ [2/6] 正在校验验证码...")
        ok, msg = await asyncio.get_running_loop().run_in_executor(None, bot.step2_check_otp, email, otp_code)
        if not ok:
            await status_msg.edit_text(f"❌ **验证码错误或失效**\n{msg}")
            return

        # Step 3
        await status_msg.edit_text(f"⏳ [3/6] 正在提交注册数据 (伪装身份: {user_identity['first_name']})...")
        ok, msg = await asyncio.get_running_loop().run_in_executor(None, bot.step3_sign_up, user_identity, otp_code)
        if not ok:
            await status_msg.edit_text(f"❌ **注册失败**\n{msg}")
            return

        # Step 3.5 (引入随机延迟防风控)
        await status_msg.edit_text(f"⏳ [4/6] 正在预热账号绕过风控 (伪装机型: {bot.device_info.split(',')[0]})...")
        await asyncio.sleep(random.uniform(1.5, 3.0))
        await asyncio.get_running_loop().run_in_executor(None, bot.step3_5_warmup)
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # Step 4
        await status_msg.edit_text("⏳ [5/6] 正在发起 0 元订单请求...")
        ok, master_id_or_err = await asyncio.get_running_loop().run_in_executor(None, bot.step4_create_order)
        if not ok:
            await status_msg.edit_text(f"❌ **下单失败**\n{master_id_or_err}")
            return

        # Step 5
        await status_msg.edit_text("⏳ [6/6] 订单处理中，等待 5 秒钟...")
        await asyncio.sleep(5)
        ok, esim_dict = await asyncio.get_running_loop().run_in_executor(None, bot.step5_get_esim, master_id_or_err)
        
        if not ok:
            await status_msg.edit_text(f"⚠️ **订单已创建，但提取详情失败**\n{esim_dict}\n请登录 App 查收。")
            return

        # 成功，推送二维码
        lpa_str = esim_dict.get('lpa', '')
        final_text = (
            f"🎉 **白嫖大成功！**\n\n"
            f"📧 **账号**: `{email}`\n"
            f"🔑 **密码**: `{user_identity['password']}`\n\n"
            f"🌍 **套餐**: {esim_dict.get('name')}\n"
            f"📍 **ICCID**: `{esim_dict.get('iccid')}`\n"
            f"📡 **LPA 代码**:\n`{html.escape(lpa_str)}`\n\n"
            f"*(注: 提取成功后，您也可以随时登录 App 查看)*"
        )
        await status_msg.edit_text(final_text, parse_mode='Markdown')

        if lpa_str and lpa_str.startswith("1$"):
            qr_url = f"https://quickchart.io/qr?text={quote(lpa_str)}&size=400&margin=2"
            try:
                await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption="📷 Nomad eSIM 二维码\n(基于 LPA 自动生成)")
            except:
                await context.bot.send_message(chat_id=user.id, text=f"🔗 扫描二维码: [点击查看图片]({qr_url})", parse_mode='Markdown')

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 发生异常: {e}")
    finally:
        # 清理上下文
        context.user_data.pop('nomad_state', None)
        context.user_data.pop('nomad_bot', None)

async def nomad_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('nomad_state', NOMAD_STATE_NONE)
    text = update.message.text.strip()
    user = update.effective_user

    # 步骤 A: 用户输入邮箱
    if state == NOMAD_STATE_WAIT_EMAIL:
        if "@" not in text or "." not in text:
            await update.message.reply_text("⚠️ 邮箱格式错误，请重新输入真实的邮箱：")
            return
            
        status_msg = await update.message.reply_text(f"⏳ [1/6] 正在向 `{text}` 发送验证码...", parse_mode='Markdown')
        
        bot = NomadBotCore()
        ok, msg = await asyncio.get_running_loop().run_in_executor(None, bot.step1_request_otp, text)
        
        if ok:
            # 记录会话数据
            context.user_data['nomad_bot'] = bot
            context.user_data['nomad_email'] = text
            context.user_data['nomad_user_data'] = bot.generate_identity(text)
            context.user_data['nomad_state'] = NOMAD_STATE_WAIT_OTP
            await status_msg.edit_text(f"✅ **验证码已发送！**\n\n请前往 `{text}` 查收邮件，并将 **验证码** (通常为字母/数字组合) 回复给机器人：", parse_mode='Markdown')
        else:
            await status_msg.edit_text(f"❌ 发送失败: {msg}")
            context.user_data['nomad_state'] = NOMAD_STATE_NONE
        return

    # 步骤 B: 用户输入验证码 (支持字母数字组合)
    if state == NOMAD_STATE_WAIT_OTP:
        cleaned_text = text.replace(" ", "")
        if not cleaned_text.isalnum() or len(cleaned_text) < 4:
            await update.message.reply_text("⚠️ 验证码格式错误，请重新输入（通常为包含字母和数字的组合）：")
            return
            
        email = context.user_data.get('nomad_email')
        status_msg = await update.message.reply_text("🚀 验证码已收到，正在执行自动化过风控下单流程...")
        user_manager.increment_usage(user.id, user.first_name)
        
        # 挂起防阻塞协程
        asyncio.create_task(process_nomad_flow(status_msg, context, user, email, cleaned_text))
        return

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(nomad_callback, pattern="^nomad_.*"))
    application.add_handler(CallbackQueryHandler(nomad_menu, pattern="^plugin_nomad_entry$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), nomad_text_handler), group=4)
    print("🔌 Nomad (AES/HMAC 过风控升级版) 插件已加载")
