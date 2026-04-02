import logging
import requests
import json
import time
import uuid
import random
import string
import asyncio
import traceback
import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

# ================= 配置常量 =================
PLAN_MAP = {
    "cn": {"orderComment": "凤鸾春恩车皇宫巡游1天", "dataPlanId": 10006}
}

COMMON_HEADERS = {
    "User-Agent": "JetFi mobile/102 CFNetwork/1410.0.3 Darwin/22.6.0",
    "Content-Type": "application/json",
    "Charset": "UTF-8",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9"
}

# ================= 业务逻辑类 =================

class JetFiLogic:
    @staticmethod
    def generate_random_email():
        chars = string.ascii_lowercase + string.digits
        user = ''.join(random.choice(chars) for _ in range(10))
        domains = ["126.com", "qq.com", "163.com"]
        return f"{user}@{random.choice(domains)}"

    @staticmethod
    def get_session():
        # 使用框架提供的代理 session，自动处理代理轮换
        session = get_safe_session(test_url="https://esim.jetfimobile.com", timeout=10)
        session.headers.update(COMMON_HEADERS)
        return session

    # ===== 新增：协议签名相关 =====
    @staticmethod
    def _canonical_json(data: dict) -> str:
        """
        生成用于签名和发送的 JSON 字符串（避免空格导致签名不一致）
        """
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _build_signature(body_str: str) -> str:
        """
        signature = SHA1(request_body_utf8)
        """
        return hashlib.sha1(body_str.encode("utf-8")).hexdigest()

    @staticmethod
    def api_request(session, url, data, extra_headers=None):
        """
        使用“签名后的原始 body”发送，保证 signature 与 body 一致
        """
        try:
            body_str = JetFiLogic._canonical_json(data)
            signature = JetFiLogic._build_signature(body_str)

            headers = {
                "signature": signature
            }
            if extra_headers:
                headers.update(extra_headers)

            # 注意：这里不用 json=data，改为 data=body_str
            # 否则 requests 可能重新序列化导致签名不匹配
            resp = session.post(url, data=body_str.encode("utf-8"), headers=headers, timeout=15)

            if not resp.ok:
                return {"code": -1, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            try:
                return resp.json()
            except Exception:
                return {"code": -1, "message": f"响应非JSON: {resp.text[:300]}"}

        except Exception as e:
            return {"code": -1, "message": str(e)}

    @staticmethod
    def run_process(plan_key="cn"):
        session = JetFiLogic.get_session()
        plan_info = PLAN_MAP.get(plan_key)

        if not plan_info:
            return False, f"不支持的套餐: {plan_key}"

        email = JetFiLogic.generate_random_email()
        device_id = str(uuid.uuid4()).upper()
        password = "qingziqing11111"

        # 1. 注册
        logger.info(f"[JetFi] 正在注册: {email}")
        reg_res = JetFiLogic.api_request(
            session,
            "https://esim.jetfimobile.com/apis/api/v1/member/register",
            {
                "email": email,
                "password": password,
                "platform": 1,
                "channelCode": "",
                "uniqueDeviceId": device_id
            }
        )

        if reg_res.get("code") != 200:
            return False, f"注册失败: {reg_res.get('message')}"

        virtual_email = reg_res.get("data", {}).get("virtualEmail")

        # 2. 登录
        login_res = JetFiLogic.api_request(
            session,
            "https://esim.jetfimobile.com/apis/api/v1/member/login",
            {
                "email": email,
                "virtualEmail": virtual_email,
                "password": password,
                "platform": 1,
                "type": 1,
                "channelCode": ""
            }
        )

        token = login_res.get("data", {}).get("token")
        if not token:
            return False, f"登录失败: 未获取到 Token, resp={login_res}"

        # 更新 Header 带上 Token
        # 你原写法保留；若后端要求非 Bearer，可改为 Authorization: token
        session.headers.update({"Authorization": f"Bearer {token}"})

        # 3. 获取优惠券
        coupon_res = JetFiLogic.api_request(
            session,
            "https://esim.jetfimobile.com/apis/api/v1/member/coupon/query",
            {
                "entry": "EXCHANGE",
                "platform": 1,
                "pageParam": {"pageNum": 1, "pageSize": 100},
                "language": "zh-Hant-TW"
            }
        )

        valid_coupons = coupon_res.get("data", {}).get("validCoupons", [])
        if not valid_coupons:
            return False, f"无法以优惠价格下单 (无优惠券), resp={coupon_res}"

        promo_code = valid_coupons[0]["promoCode"]

        # 4. 创建订单
        order_payload = {
            "platform": 1,
            "cid": "jetfi",
            "trackingCode": "",
            "userName": "User",
            "surName": "Name",
            "givenName": "Given",
            "phoneNumber": "44440444",
            "email": email,
            "clientBackURL": "https://esim.jetfimobile.com/",
            "orderComment": plan_info["orderComment"],
            "itemDesc": "JetFi-wifi-eSIM",
            "dataPlanId": plan_info["dataPlanId"],
            "promoCode": promo_code,
            "purchaseQuantity": 1,
            "amount": "0",
            "dataPlanType": "DAYPASS",
            "dataPlanBusinessType": "JETFI",
            "language": "zh-Hant-TW",
            "currency": "TWD",
            "paymentType": "NONE",
            "uniqueDeviceId": device_id
        }

        order_res = JetFiLogic.api_request(
            session,
            "https://esim.jetfimobile.com/apis/api/v1/h5/order/create",
            order_payload
        )

        if order_res.get("code") != 200:
            return False, f"下单被拒: {order_res.get('message')}, resp={order_res}"

        # 5. 等待并查询订单
        time.sleep(5)  # 稍微等待后端处理

        query_res = JetFiLogic.api_request(
            session,
            "https://esim.jetfimobile.com/apis/api/v1/h5/order/queryOrderList",
            {
                "trafficType": "ESIM",
                "language": "zh-Hant-TW"
            }
        )

        order_list = query_res.get("data", {}).get("validList", [])
        if not order_list:
            return True, f"下单成功，但暂时未查到订单信息。\n账号: `{email}`\n密码: `{password}`"

        oq = order_list[0]
        result_text = (
            f"✅ **凤鸾春恩车到啦**\n"
            f"📧 账号: `{email}`\n"
            f"🔑 密码: `{password}`\n"
            f"🌍 地区: {oq.get('areaName')}\n"
            f"🎫 套餐: {oq.get('dataPlanName')}\n"
            f"🔢 激活码 (AC): `{oq.get('ac')}`\n"
            f"⏰ 过期时间: {oq.get('expiredTime')}"
        )
        return True, result_text

# ================= 交互处理 =================

async def jetfi_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """JetFi 插件入口菜单"""
    user = update.effective_user

    # 权限与开关检查
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("jetfi") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 **该功能目前维护中**\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='Markdown'
        )
        return

    text = (
        f"🚙 **JetFi助手**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"当前支持套餐: 中国大陆 1天 (自动发车)"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 召唤凤鸾春恩车 (CN)", callback_data="jetfi_start_cn")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def jetfi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    # 二次检查
    if not user_manager.is_authorized(user.id):
        return
    if not user_manager.get_plugin_status("jetfi") and str(user.id) != str(ADMIN_ID):
        await query.edit_message_text(
            "🛑 功能已关闭",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]])
        )
        return

    if data == "jetfi_start_cn":
        # 统计使用次数
        user_manager.increment_usage(user.id, user.first_name)

        await query.edit_message_text(
            "🚙 **正在召唤凤鸾春恩车 (CN)...**\n⏳ 注册账户并申请优惠中，请稍候...",
            parse_mode='Markdown'
        )

        # 异步执行耗时任务
        asyncio.create_task(run_jetfi_task(query.message, context, "cn"))
        return


async def run_jetfi_task(message, context, plan_key):
    try:
        # 在 Executor 中运行同步的 API 请求，防止阻塞 Bot
        success, result = await asyncio.get_running_loop().run_in_executor(
            None, JetFiLogic.run_process, plan_key
        )

        keyboard = [[InlineKeyboardButton("🔙 返回 JetFi 菜单", callback_data="plugin_jetfi_entry")]]

        if success:
            await message.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await message.edit_text(f"❌ **召唤失败**\n原因是: {result}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 **系统错误**: {str(e)}", parse_mode='Markdown')


# ================= 注册函数 =================

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(jetfi_callback, pattern="^jetfi_.*"))
    application.add_handler(CallbackQueryHandler(jetfi_menu, pattern="^plugin_jetfi_entry$"))
    print("🔌 JetFi (Qingzi) 插件已加载")        domains = ["126.com", "qq.com", "163.com"]
        return f"{user}@{random.choice(domains)}"

    @staticmethod
    def get_session():
        # 使用框架提供的代理 session，自动处理代理轮换
        session = get_safe_session(test_url="https://esim.jetfimobile.com", timeout=10)
        session.headers.update(COMMON_HEADERS)
        return session

    @staticmethod
    def api_request(session, url, data):
        try:
            # 这里的 session 已经是配置好代理的了
            resp = session.post(url, json=data, timeout=15)
            if not resp.ok:
                return {"code": -1, "message": f"HTTP {resp.status_code}"}
            return resp.json()
        except Exception as e:
            return {"code": -1, "message": str(e)}

    @staticmethod
    def run_process(plan_key="cn"):
        session = JetFiLogic.get_session()
        plan_info = PLAN_MAP.get(plan_key)
        
        email = JetFiLogic.generate_random_email()
        device_id = str(uuid.uuid4()).upper()
        password = "qingziqing11111"
        
        # 1. 注册
        logger.info(f"[JetFi] 正在注册: {email}")
        reg_res = JetFiLogic.api_request(session, "https://esim.jetfimobile.com/apis/api/v1/member/register", {
            "email": email, "password": password, "platform": 1, "channelCode": "", "uniqueDeviceId": device_id
        })
        
        if reg_res.get("code") != 200:
            return False, f"注册失败: {reg_res.get('message')}"
        
        virtual_email = reg_res.get("data", {}).get("virtualEmail")

        # 2. 登录
        login_res = JetFiLogic.api_request(session, "https://esim.jetfimobile.com/apis/api/v1/member/login", {
            "email": email, "virtualEmail": virtual_email, "password": password, 
            "platform": 1, "type": 1, "channelCode": ""
        })
        token = login_res.get("data", {}).get("token")
        if not token:
            return False, "登录失败: 未获取到 Token"
        
        # 更新 Header 带上 Token
        session.headers.update({"Authorization": f"Bearer {token}"})

        # 3. 获取优惠券
        coupon_res = JetFiLogic.api_request(session, "https://esim.jetfimobile.com/apis/api/v1/member/coupon/query", {
            "entry": "EXCHANGE", "platform": 1, "pageParam": {"pageNum": 1, "pageSize": 100}, "language": "zh-Hant-TW"
        })
        valid_coupons = coupon_res.get("data", {}).get("validCoupons", [])
        if not valid_coupons:
            return False, "无法以优惠价格下单 (无优惠券)"
        promo_code = valid_coupons[0]["promoCode"]

        # 4. 创建订单
        order_payload = {
            "platform": 1, "cid": "jetfi", "trackingCode": "", "userName": "User",
            "surName": "Name", "givenName": "Given", "phoneNumber": "44440444",
            "email": email, "clientBackURL": "https://esim.jetfimobile.com/",
            "orderComment": plan_info["orderComment"],
            "itemDesc": "JetFi-wifi-eSIM",
            "dataPlanId": plan_info["dataPlanId"],
            "promoCode": promo_code, "purchaseQuantity": 1,
            "amount": "0", "dataPlanType": "DAYPASS", "dataPlanBusinessType": "JETFI",
            "language": "zh-Hant-TW", "currency": "TWD", "paymentType": "NONE",
            "uniqueDeviceId": device_id
        }
        
        order_res = JetFiLogic.api_request(session, "https://esim.jetfimobile.com/apis/api/v1/h5/order/create", order_payload)
        if order_res.get("code") != 200:
            return False, f"下单被拒: {order_res.get('message')}"

        # 5. 等待并查询订单
        time.sleep(5) # 稍微等待后端处理
        
        query_res = JetFiLogic.api_request(session, "https://esim.jetfimobile.com/apis/api/v1/h5/order/queryOrderList", {
            "trafficType": "ESIM", "language": "zh-Hant-TW"
        })
        
        order_list = query_res.get("data", {}).get("validList", [])
        if not order_list:
            return True, f"下单成功，但暂时未查到订单信息。\n账号: `{email}`\n密码: `{password}`"
            
        oq = order_list[0]
        result_text = (
            f"✅ **凤鸾春恩车到啦**\n"
            f"📧 账号: `{email}`\n"
            f"🔑 密码: `{password}`\n"
            f"🌍 地区: {oq.get('areaName')}\n"
            f"🎫 套餐: {oq.get('dataPlanName')}\n"
            f"🔢 激活码 (AC): `{oq.get('ac')}`\n"
            f"⏰ 过期时间: {oq.get('expiredTime')}"
        )
        return True, result_text

# ================= 交互处理 =================

async def jetfi_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """JetFi 插件入口菜单"""
    user = update.effective_user
    
    # 权限与开关检查
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("jetfi") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 **该功能目前维护中**\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='Markdown'
        )
        return

    text = (
        f"🚙 **JetFi助手**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"当前支持套餐: 中国大陆 1天 (自动发车)"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 召唤凤鸾春恩车 (CN)", callback_data="jetfi_start_cn")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def jetfi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    # 二次检查
    if not user_manager.is_authorized(user.id):
        return
    if not user_manager.get_plugin_status("jetfi") and str(user.id) != str(ADMIN_ID):
        await query.edit_message_text("🛑 功能已关闭", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]))
        return

    if data == "jetfi_start_cn":
        # 统计使用次数
        user_manager.increment_usage(user.id, user.first_name)
        
        await query.edit_message_text(
            "🚙 **正在召唤凤鸾春恩车 (CN)...**\n⏳ 注册账户并申请优惠中，请稍候...",
            parse_mode='Markdown'
        )
        
        # 异步执行耗时任务
        asyncio.create_task(run_jetfi_task(query.message, context, "cn"))
        return

async def run_jetfi_task(message, context, plan_key):
    try:
        # 在 Executor 中运行同步的 API 请求，防止阻塞 Bot
        success, result = await asyncio.get_running_loop().run_in_executor(
            None, JetFiLogic.run_process, plan_key
        )
        
        keyboard = [[InlineKeyboardButton("🔙 返回 JetFi 菜单", callback_data="plugin_jetfi_entry")]]
        
        if success:
            await message.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await message.edit_text(f"❌ **召唤失败**\n原因是: {result}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 **系统错误**: {str(e)}", parse_mode='Markdown')

# ================= 注册函数 =================

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(jetfi_callback, pattern="^jetfi_.*"))
    application.add_handler(CallbackQueryHandler(jetfi_menu, pattern="^plugin_jetfi_entry$"))
    print("🔌 JetFi (Qingzi) 插件已加载")
