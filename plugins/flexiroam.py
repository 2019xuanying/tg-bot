import logging
import requests
import random
import asyncio
import traceback
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入通用工具
from utils.database import user_manager, ADMIN_ID

logger = logging.getLogger(__name__)

# ================= 状态常量 (加前缀防止冲突) =================
FLEXI_STATE_NONE = 0
FLEXI_STATE_WAIT_MANUAL_EMAIL = 3
FLEXI_STATE_WAIT_MANUAL_PASSWORD = 4
FLEXI_STATE_WAIT_LOGIN_EMAIL = 5      # 新增：等待登录邮箱
FLEXI_STATE_WAIT_LOGIN_PASSWORD = 6   # 新增：等待登录密码

# ================= 代理配置 (内置) =================
PROXY_POOL = [
    "38.106.2.177:20168:lvOznlJ4Go:TXM8eo0FgA",
    "38.98.15.36:38267:qyYh0nPhnz:tvAagTMg9q",
    "38.98.15.148:45383:8BJmo81Cj0:gu4V0pWb29",
    "38.106.2.18:63381:sQFTHWgdQ6:Hbs0Y5k1YP",
    "38.135.189.179:8889:VC8xE2Rdx5:xrkldZw7q7"
]

class ProxyManager:
    @staticmethod
    def parse_proxy(proxy_line):
        try:
            parts = proxy_line.strip().split(':')
            if len(parts) != 4: return None
            ip, port, user, password = parts
            return f"socks5://{user}:{password}@{ip}:{port}"
        except: return None

    @staticmethod
    def get_random_proxy():
        if not PROXY_POOL: return None
        return ProxyManager.parse_proxy(random.choice(PROXY_POOL))
    
    @staticmethod
    def configure_session(session):
        proxy_url = ProxyManager.get_random_proxy()
        if proxy_url:
            session.proxies = {'http': proxy_url, 'https': proxy_url}
            return True
        return False

# ================= Flexiroam 核心逻辑 =================
JWT_APP_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJjbGllbnRfaWQiOjQsImZpcnN0X25hbWUiOiJUcmF2ZWwiLCJsYXN0X25hbWUiOiJBcHAiLCJlbWFpbCI6InRyYXZlbGFwcEBmbGV4aXJvYW0uY29tIiwidHlwZSI6IkNsaWVudCIsImFjY2Vzc190eXBlIjoiQXBwIiwidXNlcl9hY2NvdW50X2lkIjo2LCJ1c2VyX3JvbGUiOiJWaWV3ZXIiLCJwZXJtaXNzaW9uIjpbXSwiZXhwaXJlIjoxODc5NjcwMjYwfQ.-RtM_zNG-zBsD_S2oOEyy4uSbqR7wReAI92gp9uh-0Y"
CARDBIN = "528911"

class FlexiroamLogic:
    @staticmethod
    def get_session():
        session = requests.Session()
        ProxyManager.configure_session(session)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        })
        return session

    @staticmethod
    def get_random_identity():
        """生成随机身份信息以规避风控"""
        first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
        last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris"]
        # 常见国家代码：美国、英国、德国、法国、意大利、加拿大、澳大利亚、新加坡、马来西亚、日本
        countries = ["US", "GB", "DE", "FR", "IT", "CA", "AU", "SG", "MY", "JP"]
        
        return {
            "first_name": random.choice(first_names),
            "last_name": random.choice(last_names),
            "country": random.choice(countries)
        }

    @staticmethod
    def register(session, email, password):
        """提交注册请求"""
        url = "https://prod-enduserservices.flexiroam.com/api/registration/request/create"
        headers = {
            "authorization": "Bearer " + JWT_APP_TOKEN,
            "content-type": "application/json",
            "lang": "en-us",
            "origin": "https://www.flexiroam.com",
            "referer": "https://www.flexiroam.com/en-us/signup"
        }
        
        # 使用随机身份
        identity = FlexiroamLogic.get_random_identity()
        
        payload = {
            "email": email,
            "password": password,
            "first_name": identity["first_name"],
            "last_name": identity["last_name"],
            "home_country_code": identity["country"],
            "language_preference": "en-us"
        }
        try:
            res = session.post(url, headers=headers, json=payload, timeout=20)
            return res.status_code in [200, 201], res.text
        except Exception as e: return False, str(e)

    @staticmethod
    def login(session, email, password):
        url = "https://prod-enduserservices.flexiroam.com/api/user/login"
        headers = {
            "authorization": "Bearer " + JWT_APP_TOKEN,
            "content-type": "application/json",
            "user-agent": "Flexiroam/3.0.0 (iPhone; iOS 16.0; Scale/3.00)"
        }
        data = {
            "email": email, "password": password, 
            "device_udid": "iPhone17,2", "device_model": "iPhone17,2", 
            "device_platform": "ios", "device_version": "18.3.1", 
            "have_esim_supported_device": 1, "notification_token": "undefined"
        }
        try:
            res = session.post(url, headers=headers, json=data, timeout=20)
            rj = res.json()
            if rj.get("message") == "Login Successful": return True, rj["data"]
            return False, rj.get("message", res.text)
        except Exception as e: return False, str(e)

    @staticmethod
    def get_plans(session):
        try:
            res = session.get("https://www.flexiroam.com/en-us/my-plans", headers={"rsc": "1"}, timeout=20)
            for line in res.text.splitlines():
                if '{"plans":[' in line:
                    start = line.find('{"plans":[')
                    json_str = line[start:]
                    if not json_str.endswith("}"): json_str += "}"
                    try: return True, json.loads(json_str)
                    except: pass
            return False, "Plans Not Found"
        except Exception as e: return False, str(e)

    @staticmethod
    def luhn_checksum(card_number):
        digits = [int(d) for d in card_number]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9: digits[i] -= 9
        return sum(digits) % 10

    @staticmethod
    def generate_card_number():
        bin_prefix = CARDBIN
        length = 16
        while True:
            card_number = bin_prefix + ''.join(str(random.randint(0, 9)) for _ in range(length - len(bin_prefix) - 1))
            check_digit = (10 - FlexiroamLogic.luhn_checksum(card_number + "0")) % 10
            full_card_number = card_number + str(check_digit)
            if FlexiroamLogic.luhn_checksum(full_card_number) == 0: return full_card_number

    @staticmethod
    def redeem_code(session, token, email):
        card_num = FlexiroamLogic.generate_card_number()
        try:
            url_check = "https://prod-enduserservices.flexiroam.com/api/user/redemption/check/eligibility"
            headers = {"authorization": "Bearer " + token, "content-type": "application/json", "lang": "en-us"}
            payload = {"email": email, "lookup_value": card_num}
            res = session.post(url_check, headers=headers, json=payload, timeout=15)
            rj = res.json()
            
            if "processing" in str(rj).lower(): return False, "Processing"
            if "Data Plan" not in str(rj): return False, f"Check Failed: {rj.get('message')}"
            
            redemption_id = rj["data"]["redemption_id"]
            
            url_conf = "https://prod-enduserservices.flexiroam.com/api/user/redemption/confirm"
            res = session.post(url_conf, headers=headers, json={"redemption_id": redemption_id}, timeout=15)
            rj = res.json()
            if rj.get("message") == "Redemption confirmed": return True, "Success"
            return False, f"Confirm Failed: {rj.get('message')}"
        except Exception as e: return False, f"Error: {e}"

    @staticmethod
    def start_plan(session, token, plan_id=None):
        try:
            if not plan_id:
                res, data = FlexiroamLogic.get_plans(session)
                if res:
                    for p in data.get("plans", []):
                        if p["status"] == 'In-active':
                            plan_id = p["planId"]
                            break
            
            if not plan_id: return False, "No inactive plan found"

            url = "https://prod-planservices.flexiroam.com/api/plan/start"
            headers = {
                "authorization": "Bearer " + token, "content-type": "application/json",
                "lang": "en-us", "origin": "https://www.flexiroam.com", "referer": "https://www.flexiroam.com/en-us/my-plans"
            }
            res = session.post(url, headers=headers, json={"sim_plan_id": int(plan_id)}, timeout=15)
            if res.status_code == 200 or "data" in res.json(): return True, "Plan Started"
            return False, f"Start Failed: {res.text}"
        except Exception as e: return False, f"Activate Error: {e}"

# ================= 监控任务管理 =================
class MonitoringManager:
    def __init__(self):
        self.tasks = {} # user_id -> task

    def start_monitor(self, user_id, context, session, token, email):
        self.stop_monitor(user_id)
        task = asyncio.create_task(self._monitor_loop(user_id, context, session, token, email))
        self.tasks[user_id] = task
        return True

    def stop_monitor(self, user_id):
        if user_id in self.tasks:
            self.tasks[user_id].cancel()
            del self.tasks[user_id]
            return True
        return False
    
    def is_monitoring(self, user_id):
        return user_id in self.tasks

    async def _monitor_loop(self, user_id, context, session, token, email):
        logger.info(f"[Flexiroam] 用户 {user_id} 开始监控...")
        day_get_count = 0
        last_get_time = datetime.now() - timedelta(hours=8)
        
        try:
            while True:
                try:
                    try: session.get("https://www.flexiroam.com/api/auth/session", timeout=10)
                    except: pass

                    res, plans_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
                    if not res:
                        await asyncio.sleep(30)
                        continue
                    
                    plans_list = plans_data.get("plans", [])
                    active_plans = [p for p in plans_list if p["status"] == 'Active']
                    inactive_plans = [p for p in plans_list if p["status"] == 'In-active']
                    
                    total_active_pct = sum(p["circleChart"]["percentage"] for p in active_plans)
                    inactive_count = len(inactive_plans)
                    
                    # 自动激活
                    if total_active_pct <= 30 and inactive_count > 0:
                        target_id = inactive_plans[0]["planId"]
                        try: await context.bot.send_message(user_id, f"📉 [Flexi] 流量告急 ({total_active_pct}%)，激活新套餐...")
                        except: pass
                        
                        ok, res_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token, target_id)
                        if ok:
                            try: await context.bot.send_message(user_id, "✅ [Flexi] 自动激活成功！")
                            except: pass
                            await asyncio.sleep(10)
                            continue
                    
                    # 自动补货
                    current_time = datetime.now()
                    if inactive_count < 2 and day_get_count < 5:
                        if (current_time - last_get_time) >= timedelta(minutes=1):
                            try: await context.bot.send_message(user_id, f"📦 [Flexi] 库存不足 ({inactive_count})，自动领卡...")
                            except: pass
                            
                            r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, token, email)
                            if r_ok:
                                day_get_count += 1
                                last_get_time = current_time
                                try: await context.bot.send_message(user_id, f"✅ [Flexi] 领卡成功！(今日第 {day_get_count} 张)")
                                except: pass
                                await asyncio.sleep(5)
                                if total_active_pct <= 30:
                                    await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token)
                
                except asyncio.CancelledError: raise
                except Exception as e: logger.error(f"Flexi Monitor error {user_id}: {e}")
                
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info(f"Flexi Monitor {user_id} stopped.")

monitor_manager = MonitoringManager()

# ================= 交互逻辑 (适配模块化) =================

async def flexiroam_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """插件入口菜单"""
    user = update.effective_user
    context.user_data['flexi_state'] = FLEXI_STATE_NONE # 状态重置
    
    # 鉴权
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 未授权", show_alert=True)
        return

    welcome_text = (
        f"🌐 **Flexiroam 自动化助手**\n"
        f"当前状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"请选择操作："
    )
    keyboard = [
        [InlineKeyboardButton("🚀 开始新任务 (注册)", callback_data="flexi_start_task")],
        [InlineKeyboardButton("🔑 登录账号", callback_data="flexi_login_task")],
        [InlineKeyboardButton("📊 监控管理", callback_data="flexi_monitor_menu")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def flexiroam_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    if data == "flexi_monitor_menu":
        is_running = monitor_manager.is_monitoring(user.id)
        status = "✅ 运行中" if is_running else "⏹ 已停止"
        keyboard = []
        if is_running: keyboard.append([InlineKeyboardButton("🛑 停止监控", callback_data="flexi_stop_monitor")])
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")])
        await query.edit_message_text(f"📊 **监控状态**\n状态: {status}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "flexi_stop_monitor":
        monitor_manager.stop_monitor(user.id)
        await query.edit_message_text("🛑 监控已停止。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]))
        return

    if data == "flexi_start_monitor_confirm":
        monitor_data = context.user_data.get('flexi_monitor_data')
        if not monitor_data:
            await query.edit_message_text("⚠️ 会话已过期，请重新运行任务。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]))
            return
        monitor_manager.start_monitor(user.id, context, monitor_data['session'], monitor_data['token'], monitor_data['email'])
        await query.edit_message_text("✅ **后台监控已启动！**\n机器人将在流量不足时自动激活新套餐。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    if data == "flexi_start_task":
        if not user_manager.get_config("bot_active", True) and user.id != ADMIN_ID:
             await query.edit_message_text("⚠️ 维护中。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]))
             return
        
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_MANUAL_EMAIL
        await query.edit_message_text("📧 **请输入新的 Flexiroam 邮箱地址：**\n(请直接回复消息)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    # === 新增：登录入口 ===
    if data == "flexi_login_task":
        if not user_manager.get_config("bot_active", True) and user.id != ADMIN_ID:
             await query.edit_message_text("⚠️ 维护中。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]))
             return
        
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_LOGIN_EMAIL
        await query.edit_message_text("🔑 **请输入已注册的邮箱地址：**\n(请直接回复消息)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    if data == "flexi_manual_verify_done":
        task_data = context.user_data.get('flexi_pending_task')
        if not task_data:
            await query.edit_message_text("⚠️ 会话过期。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]))
            return
        del context.user_data['flexi_pending_task']
        await query.edit_message_text("✅ 收到确认，正在登录...")
        await finish_flexiroam_task(query.message, context, user, task_data['session'], task_data['email'], task_data['password'])
        return

async def run_flexiroam_task(message, context, user, email, password):
    try:
        user_manager.increment_usage(user.id, user.first_name)
        status_msg = await message.reply_text("⏳ 初始化环境...")
        session = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_session)
        
        # 1. 提交注册
        await status_msg.edit_text(f"🚀 **提交注册**\n📧 `{email}`\n(使用随机身份以规避风控)", parse_mode='Markdown')
        reg_ok, reg_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.register, session, email, password)
        if not reg_ok:
            await status_msg.edit_text(f"❌ 注册失败: {reg_msg}")
            return

        # 2. 暂停，等待人工验证
        await status_msg.edit_text(
            f"📩 **注册成功！请去邮箱点击链接验证**\n验证完成后点击下方按钮。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 我已完成验证", callback_data="flexi_manual_verify_done")]]),
            parse_mode='Markdown'
        )
        # 保存状态
        context.user_data['flexi_pending_task'] = {'session': session, 'email': email, 'password': password}

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 异常: {e}")

async def finish_flexiroam_task(message, context, user, session, email, password):
    """注册后的收尾流程"""
    try:
        app_token = None
        for i in range(3):
            l_ok, l_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.login, session, email, password)
            if l_ok:
                app_token = l_data['token']
                break
            await asyncio.sleep(2)
            
        if not app_token:
            await message.edit_text(f"❌ 登录失败 (请确认已点击验证链接)。")
            return

        await message.edit_text("🎁 正在兑换新手福利...")
        r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, app_token, email)
        
        status_text = f"✅ 兑换成功" if r_ok else f"⚠️ 兑换: {r_msg}"
        await message.edit_text(f"{status_text}\n⏳ 正在激活流量包...")
        
        await asyncio.sleep(3) 
        s_ok, s_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, app_token)
        
        context.user_data['flexi_monitor_data'] = {'session': session, 'token': app_token, 'email': email}
        act_text = "✅ 激活成功" if s_ok else f"⚠️ 激活: {s_msg}"
        
        await message.edit_text(
            f"🎉 **Flexiroam 任务完成！**\n{status_text}\n{act_text}\n\n📡 **启动后台监控？**\n(当流量<30%自动激活新套餐)", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 启动监控", callback_data="flexi_start_monitor_confirm")]]), 
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(traceback.format_exc())
        await message.edit_text(f"💥 异常: {e}")

async def run_flexiroam_login_task(message, context, user, email, password):
    """直接登录流程"""
    try:
        user_manager.increment_usage(user.id, user.first_name)
        status_msg = await message.reply_text("⏳ 正在登录...")
        session = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_session)
        
        l_ok, l_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.login, session, email, password)
        
        if not l_ok:
            await status_msg.edit_text(f"❌ 登录失败: {l_data}\n请检查账号密码是否正确。")
            return
            
        app_token = l_data['token']
        await status_msg.edit_text("✅ 登录成功！\n🎁 正在检查/兑换新手福利...")
        
        r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, app_token, email)
        status_text = f"✅ 兑换成功" if r_ok else f"⚠️ 兑换: {r_msg}"
        
        await status_msg.edit_text(f"{status_text}\n⏳ 正在激活流量包...")
        
        s_ok, s_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, app_token)
        
        context.user_data['flexi_monitor_data'] = {'session': session, 'token': app_token, 'email': email}
        act_text = "✅ 激活成功" if s_ok else f"⚠️ 激活: {s_msg}"
        
        await status_msg.edit_text(
            f"🎉 **操作完成！**\n{status_text}\n{act_text}\n\n📡 **启动后台监控？**\n(当流量<30%自动激活新套餐)", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 启动监控", callback_data="flexi_start_monitor_confirm")]]), 
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 异常: {e}")

async def flexiroam_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('flexi_state', FLEXI_STATE_NONE)
    text = update.message.text.strip()
    user = update.effective_user

    # --- 注册流程 ---
    if state == FLEXI_STATE_WAIT_MANUAL_EMAIL:
        if "@" not in text or "." not in text:
            await update.message.reply_text("❌ 邮箱无效，请重新输入。")
            return
        context.user_data['flexi_temp_email'] = text
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_MANUAL_PASSWORD
        await update.message.reply_text(f"✅ 注册邮箱: `{text}`\n🔑 **请设置密码：**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    if state == FLEXI_STATE_WAIT_MANUAL_PASSWORD:
        password = text
        email = context.user_data.get('flexi_temp_email')
        if not email:
            context.user_data['flexi_state'] = FLEXI_STATE_NONE
            await update.message.reply_text("⚠️ 流程异常，请重试。")
            return
        context.user_data['flexi_state'] = FLEXI_STATE_NONE
        await update.message.reply_text(f"✅ 密码已设置\n🚀 正在注册 Flexiroam...")
        asyncio.create_task(run_flexiroam_task(update.message, context, user, email, password))
        return

    # --- 登录流程 ---
    if state == FLEXI_STATE_WAIT_LOGIN_EMAIL:
        if "@" not in text or "." not in text:
            await update.message.reply_text("❌ 邮箱无效，请重新输入。")
            return
        context.user_data['flexi_login_email'] = text
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_LOGIN_PASSWORD
        await update.message.reply_text(f"✅ 登录邮箱: `{text}`\n🔑 **请输入密码：**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    if state == FLEXI_STATE_WAIT_LOGIN_PASSWORD:
        password = text
        email = context.user_data.get('flexi_login_email')
        if not email:
            context.user_data['flexi_state'] = FLEXI_STATE_NONE
            await update.message.reply_text("⚠️ 流程异常，请重试。")
            return
        context.user_data['flexi_state'] = FLEXI_STATE_NONE
        await update.message.reply_text(f"✅ 密码已接收\n🚀 正在登录...")
        asyncio.create_task(run_flexiroam_login_task(update.message, context, user, email, password))
        return

# ================= 注册函数 =================
def register_handlers(application):
    # 注册回调
    application.add_handler(CallbackQueryHandler(flexiroam_callback, pattern="^flexi_.*"))
    application.add_handler(CallbackQueryHandler(flexiroam_menu, pattern="^plugin_flexi_entry$"))
    # 注册文本 (需配合状态机)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), flexiroam_text_handler))
    print("🔌 Flexiroam 插件已加载")
