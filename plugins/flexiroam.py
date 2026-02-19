import logging
import requests
import random
import asyncio
import traceback
import json
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

# ================= 状态常量 =================
FLEXI_STATE_NONE = 0
FLEXI_STATE_WAIT_BIN = 2
FLEXI_STATE_WAIT_LOGIN_EMAIL = 5
FLEXI_STATE_WAIT_LOGIN_PASSWORD = 6

# ================= Flexiroam 核心逻辑 =================
JWT_APP_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJjbGllbnRfaWQiOjQsImZpcnN0X25hbWUiOiJUcmF2ZWwiLCJsYXN0X25hbWUiOiJBcHAiLCJlbWFpbCI6InRyYXZlbGFwcEBmbGV4aXJvYW0uY29tIiwidHlwZSI6IkNsaWVudCIsImFjY2Vzc190eXBlIjoiQXBwIiwidXNlcl9hY2NvdW50X2lkIjo2LCJ1c2VyX3JvbGUiOiJWaWV3ZXIiLCJwZXJtaXNzaW9uIjpbXSwiZXhwaXJlIjoxODc5NjcwMjYwfQ.-RtM_zNG-zBsD_S2oOEyy4uSbqR7wReAI92gp9uh-0Y"

class FlexiroamLogic:
    @staticmethod
    def get_session():
        session = get_safe_session(test_url="https://www.flexiroam.com", timeout=10)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        })
        return session

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
    def init_web_session(session, app_token):
        """用 App Token 换取 Web 的 CSRF 和 Cookie"""
        try:
            headers = {"referer": "https://www.flexiroam.com/en-us/home"}
            res_csrf = session.get("https://www.flexiroam.com/api/auth/csrf", headers=headers, timeout=15)
            csrf_token = res_csrf.json().get("csrfToken")
            if not csrf_token: return False, "CSRF 获取失败"

            url = "https://www.flexiroam.com/api/auth/callback/credentials?"
            headers_cre = {
                "content-type": "application/x-www-form-urlencoded", 
                "referer": "https://www.flexiroam.com/en-us/login"
            }
            data = {
                "token": app_token, "redirect": "false", 
                "csrfToken": csrf_token, "callbackUrl": "https://www.flexiroam.com/en-us/login"
            }
            res_auth = session.post(url, headers=headers_cre, data=data, timeout=15)
            
            if res_auth.status_code == 200: return True, "Web Session Ready"
            return False, f"Session 交换失败: {res_auth.status_code}"
        except Exception as e: return False, str(e)

    @staticmethod
    def get_plans(session):
        try:
            res = session.get("https://www.flexiroam.com/en-us/my-plans", headers={"rsc": "1", "referer": "https://www.flexiroam.com/en-us/profile"}, timeout=20)
            for line in res.text.splitlines():
                if '{"plans":[' in line:
                    start = line.find('{"plans":[')
                    json_str = line[start:]
                    if not json_str.endswith("}"): json_str += "}"
                    try: return True, json.loads(json_str)
                    except: pass
            return False, "Plans Not Found (可能登录失效)"
        except Exception as e: return False, str(e)

    @staticmethod
    def luhn_checksum(card_number):
        digits = [int(d) for d in card_number]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9: digits[i] -= 9
        return sum(digits) % 10

    @staticmethod
    def generate_card_number(bin_prefix):
        length = 16
        while True:
            card_number = bin_prefix + ''.join(str(random.randint(0, 9)) for _ in range(length - len(bin_prefix) - 1))
            check_digit = (10 - FlexiroamLogic.luhn_checksum(card_number + "0")) % 10
            full_card_number = card_number + str(check_digit)
            if FlexiroamLogic.luhn_checksum(full_card_number) == 0: return full_card_number

    @staticmethod
    def redeem_code(session, token, email, custom_bin):
        """
        [优化版] 尝试领卡：基于最新抓包特征，增加 OPTIONS 预检请求并对齐 Headers
        """
        url_check = "https://prod-enduserservices.flexiroam.com/api/user/redemption/check/eligibility"
        url_conf = "https://prod-enduserservices.flexiroam.com/api/user/redemption/confirm"
        
        # 1. 严格对齐抓包中的 HTTP Headers
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "authorization": "Bearer " + token,
            "content-type": "application/json",
            "lang": "en-us",
            "origin": "https://www.flexiroam.com",
            "priority": "u=1, i",
            "referer": "https://www.flexiroam.com/en-us/profile",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        }

        # 2. 模拟浏览器的 CORS OPTIONS 预检请求头
        options_headers = headers.copy()
        if "authorization" in options_headers: del options_headers["authorization"]
        if "content-type" in options_headers: del options_headers["content-type"]
        if "lang" in options_headers: del options_headers["lang"]
        options_headers["access-control-request-headers"] = "authorization,content-type,lang"
        options_headers["access-control-request-method"] = "POST"

        for i in range(3):
            card_num = FlexiroamLogic.generate_card_number(custom_bin)
            try:
                # === 步骤一：验证资格 (Check Eligibility) ===
                # 模拟浏览器行为：先发 OPTIONS 预检
                session.options(url_check, headers=options_headers, timeout=5)
                
                payload_check = {"email": email, "lookup_value": card_num}
                res_check = session.post(url_check, headers=headers, json=payload_check, timeout=10)
                rj_check = res_check.json()

                if "processing" in str(rj_check).lower(): 
                    return True, "Pending Order Exists" 
                
                if "Data Plan" in str(rj_check) and "data" in rj_check:
                    redemption_id = rj_check["data"].get("redemption_id")
                    if redemption_id:
                        
                        # === 步骤二：确认兑换 (Confirm) ===
                        # 模拟浏览器行为：确认前同样进行 OPTIONS 预检
                        session.options(url_conf, headers=options_headers, timeout=5)
                        
                        payload_conf = {"redemption_id": redemption_id}
                        res_conf = session.post(url_conf, headers=headers, json=payload_conf, timeout=10)
                        rj_conf = res_conf.json()
                        
                        if rj_conf.get("message") == "Redemption confirmed":
                            return True, f"Success (Card: {card_num[:6]}****)"
                        else:
                            logger.warning(f"[Flexi] Redemption confirm rejected: {rj_conf}")
                            
            except Exception as e:
                logger.error(f"[Flexi] Redeem Error: {e}")
            
            # 加入随机时延，降低自动化特征
            time.sleep(random.uniform(1.5, 3.5))
        
        return False, "Failed (Safe Retry Limit)"

    @staticmethod
    def start_plan(session, token, plan_id):
        try:
            url = "https://prod-planservices.flexiroam.com/api/plan/start"
            headers = {
                "authorization": "Bearer " + token, "content-type": "application/json",
                "lang": "en-us", "origin": "https://www.flexiroam.com", 
                "referer": "https://www.flexiroam.com/en-us/my-plans"
            }
            res = session.post(url, headers=headers, json={"sim_plan_id": int(plan_id)}, timeout=15)
            if res.status_code == 200 or "data" in res.json(): return True, "Plan Started"
            return False, f"Failed: {res.text}"
        except Exception as e: return False, f"Error: {e}"

# ================= 监控任务管理 =================
class MonitoringManager:
    def __init__(self):
        self.tasks = {} 

    def start_monitor(self, user_id, context, session, token, email, custom_bin):
        self.stop_monitor(user_id)
        task = asyncio.create_task(self._monitor_loop(user_id, context, session, token, email, custom_bin))
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

    async def _monitor_loop(self, user_id, context, session, token, email, custom_bin):
        logger.info(f"[Flexiroam] 用户 {user_id} 开始监控 (BIN: {custom_bin})...")
        day_get_count = 0
        last_get_time = datetime.now() - timedelta(hours=8)
        
        try:
            asyncio.create_task(self._keep_alive_session(session))

            while True:
                try:
                    res, plans_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
                    
                    if not res:
                        logger.warning(f"获取套餐失败，可能 Session 过期")
                        await asyncio.sleep(60)
                        continue
                    
                    plans_list = plans_data.get("plans", [])
                    active_plans = [p for p in plans_list if p["status"] == 'Active']
                    inactive_plans = [p for p in plans_list if p["status"] == 'In-active']
                    
                    total_active_pct = sum(p["circleChart"]["percentage"] for p in active_plans)
                    inactive_count = len(inactive_plans)
                    
                    # === 自动激活逻辑 ===
                    if total_active_pct <= 30 and inactive_count > 0:
                        target_id = inactive_plans[0]["planId"]
                        try: await context.bot.send_message(user_id, f"📉 [Flexi] 流量低 ({total_active_pct}%)，尝试激活 ID:{target_id}...")
                        except: pass
                        
                        ok, res_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token, target_id)
                        if ok:
                            try: await context.bot.send_message(user_id, "✅ [Flexi] 自动激活成功！")
                            except: pass
                            await asyncio.sleep(10)
                            continue
                    
                    # === 自动领卡逻辑 ===
                    current_time = datetime.now()
                    if inactive_count < 2 and day_get_count < 5:
                        if (current_time - last_get_time) >= timedelta(minutes=5):
                            try: await context.bot.send_message(user_id, f"📦 [Flexi] 库存不足 ({inactive_count})，尝试使用自定义 BIN 领卡...")
                            except: pass
                            
                            r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, token, email, custom_bin)
                            
                            if r_ok:
                                day_get_count += 1
                                last_get_time = current_time
                                try: await context.bot.send_message(user_id, f"✅ [Flexi] 领卡成功！(今日第 {day_get_count} 张)")
                                except: pass
                                
                                if total_active_pct <= 30:
                                    await asyncio.sleep(5)
                                    _, new_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
                                    for np in new_data.get("plans", []):
                                        if np["status"] == 'In-active':
                                             await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, token, np["planId"])
                                             break
                            else:
                                last_get_time = current_time 
                
                except asyncio.CancelledError: raise
                except Exception as e: logger.error(f"Flexi Loop Error: {e}")
                
                await asyncio.sleep(180)

        except asyncio.CancelledError:
            logger.info(f"Flexi Monitor {user_id} stopped.")

    async def _keep_alive_session(self, session):
        try:
            while True:
                await asyncio.sleep(1000)
                try: 
                    await asyncio.get_running_loop().run_in_executor(None, lambda: session.get("https://www.flexiroam.com/api/auth/session", timeout=10))
                except: pass
        except asyncio.CancelledError: pass

monitor_manager = MonitoringManager()

# ================= 交互逻辑 =================

async def flexiroam_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['flexi_state'] = FLEXI_STATE_NONE
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 未授权", show_alert=True)
        return

    if not user_manager.get_plugin_status("flexiroam") and user.id != ADMIN_ID:
        await update.callback_query.edit_message_text(
            "🛑 **该项目目前维护中**\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='Markdown'
        )
        return

    welcome_text = (
        f"🌐 **Flexiroam 自动化助手 (登录版)**\n"
        f"当前状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"请选择操作："
    )
    keyboard = [
        [InlineKeyboardButton("🔑 登录账号并自动领卡", callback_data="flexi_login_task")],
        [InlineKeyboardButton("📊 后台监控管理", callback_data="flexi_monitor_menu")],
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
        monitor_manager.start_monitor(user.id, context, monitor_data['session'], monitor_data['token'], monitor_data['email'], monitor_data['custom_bin'])
        await query.edit_message_text("✅ **后台监控已启动！**\n机器人将在流量不足时使用您配置的 BIN 自动激活新套餐。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

    if data == "flexi_login_task":
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_BIN
        await query.edit_message_text("💳 **请输入用于兑换验证的 6位自定义卡 BIN：**\n(例如：`540449`，请直接回复纯数字)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_flexi_entry")]]), parse_mode='Markdown')
        return

async def process_flexi_login_flow(message, context, user, session, email, password, custom_bin):
    """通用的 [登录 -> Web Session -> 领卡 -> 激活] 流程"""
    try:
        if isinstance(message, str): 
             status_msg = await context.bot.send_message(user.id, "⏳ 正在登录...")
        else:
             status_msg = message

        app_token = None
        for i in range(3):
            l_ok, l_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.login, session, email, password)
            if l_ok:
                app_token = l_data['token']
                break
            await asyncio.sleep(2)
            
        if not app_token:
            await status_msg.edit_text(f"❌ 登录失败 (请检查密码)。")
            return

        await status_msg.edit_text("✅ App 登录成功，正在初始化 Web 环境...")

        w_ok, w_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.init_web_session, session, app_token)
        if not w_ok:
            await status_msg.edit_text(f"❌ Web 初始化失败: {w_msg}")
            return

        await status_msg.edit_text(f"🎁 正在使用自定义 BIN ({custom_bin}) 尝试兑换福利...")
        r_ok, r_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.redeem_code, session, app_token, email, custom_bin)
        status_text = f"✅ 兑换: {r_msg}" if r_ok else f"⚠️ 兑换: {r_msg}"
        
        await status_msg.edit_text(f"{status_text}\n⏳ 正在查找未激活的套餐...")
        await asyncio.sleep(3) 
        
        _, plans_data = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_plans, session)
        target_id = None
        
        if isinstance(plans_data, dict):
            for p in plans_data.get("plans", []):
                if p["status"] == 'In-active':
                    target_id = p["planId"]
                    break
        
        act_text = "⚠️ 无待激活套餐"
        if target_id:
            await status_msg.edit_text(f"{status_text}\n⏳ 正在激活 ID: {target_id} ...")
            s_ok, s_msg = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.start_plan, session, app_token, target_id)
            act_text = "✅ 激活成功" if s_ok else f"⚠️ 激活失败: {s_msg}"
        else:
            if r_ok: act_text = "⚠️ 兑换成功但未找到 Plan (可能因接口延迟)"
        
        # 保存监控数据（包含 custom_bin）
        context.user_data['flexi_monitor_data'] = {'session': session, 'token': app_token, 'email': email, 'custom_bin': custom_bin}
        
        await status_msg.edit_text(
            f"🎉 **流程结束**\n{status_text}\n{act_text}\n\n📡 **是否启动后台监控？**\n(流量<30%自动激活 + 库存不足自动补货)", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 启动监控", callback_data="flexi_start_monitor_confirm")]]), 
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 流程异常: {e}")

async def flexiroam_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('flexi_state', FLEXI_STATE_NONE)
    text = update.message.text.strip()
    user = update.effective_user

    # BIN 输入
    if state == FLEXI_STATE_WAIT_BIN:
        if not text.isdigit() or len(text) < 6:
            await update.message.reply_text("❌ BIN 格式错误，请输入至少6位纯数字。")
            return
        context.user_data['flexi_custom_bin'] = text
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_LOGIN_EMAIL
        await update.message.reply_text(f"✅ 卡 BIN 设置为: `{text}`\n🔑 **请输入已注册的 Flexiroam 邮箱地址：**", parse_mode='Markdown')
        return

    # 登录邮箱输入
    if state == FLEXI_STATE_WAIT_LOGIN_EMAIL:
        if "@" not in text:
            await update.message.reply_text("❌ 邮箱格式错误")
            return
        context.user_data['flexi_login_email'] = text
        context.user_data['flexi_state'] = FLEXI_STATE_WAIT_LOGIN_PASSWORD
        await update.message.reply_text(f"✅ 登录邮箱: `{text}`\n🔑 **请输入密码：**", parse_mode='Markdown')
        return

    # 登录密码输入
    if state == FLEXI_STATE_WAIT_LOGIN_PASSWORD:
        password = text
        email = context.user_data.get('flexi_login_email')
        custom_bin = context.user_data.get('flexi_custom_bin')
        context.user_data['flexi_state'] = FLEXI_STATE_NONE
        
        status_msg = await update.message.reply_text("🚀 开始登录及领卡任务...")
        session = await asyncio.get_running_loop().run_in_executor(None, FlexiroamLogic.get_session)
        asyncio.create_task(process_flexi_login_flow(status_msg, context, user, session, email, password, custom_bin))
        return

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(flexiroam_callback, pattern="^flexi_.*"))
    application.add_handler(CallbackQueryHandler(flexiroam_menu, pattern="^plugin_flexi_entry$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), flexiroam_text_handler), group=1)
    print("🔌 Flexiroam (Login + Custom BIN) 插件已加载")
