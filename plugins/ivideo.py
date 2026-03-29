import logging
import requests
import datetime
import re
import random
import string
import asyncio
import traceback
import html
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session
from utils.mail import MailTm

logger = logging.getLogger(__name__)

# ================= 核心业务逻辑 =================

class iVideoBotCore:
    def __init__(self):
        # 使用框架提供的代理安全 session
        self.session = get_safe_session(test_url="https://www.ivideo.com.tw", timeout=10)
        self.base_url = 'https://www.ivideo.com.tw'
        
        # 模拟真实浏览器行为，增加更严格的防风控 Headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1'
        })
        
        self.member_id = None
        self.exchanged_id = None
        self.current_user_data = {}

    def generate_random_user(self, email):
        first_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=5))
        last_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=7))
        
        user_data = {
            'email': email,
            'name': f"{first_name} {last_name}",
            'mobile': "09" + ''.join(random.choices(string.digits, k=8)),
            'password': "Wang" + ''.join(random.choices(string.digits, k=6)) + "."
        }
        
        self.current_user_data = user_data
        return user_data

    def register_flow(self):
        d = self.current_user_data
        try:
            # Step 1
            step1_url = urljoin(self.base_url, '/sign-up/SignUp_Step1.php')
            self.session.headers.update({'Referer': urljoin(self.base_url, '/sign-up/SignUp_Step1.php')})
            self.session.post(step1_url, data={
                'member_type_id': '', 'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': d['email'], 'name': d['name']
            }, timeout=15)

            # Step 3
            step3_url = urljoin(self.base_url, '/sign-up/SignUp_Step3.php')
            self.session.headers.update({
                'Referer': step1_url,
                'Origin': self.base_url
            })
            payload = {
                'birthday': '3/3/1992', 'member_type_id': '1', 'country_code': '886', 'country_id': '112',
                'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': d['email'], 'name': d['name'], 'mobile_phone': d['mobile'],
                'password1': d['password'], 'password2': d['password'],
                'line_id': '', 'recommend_email': ''
            }
            resp = self.session.post(step3_url, data=payload, timeout=15)
            
            if "成功" in resp.text or resp.status_code in [200, 302]:
                return True, "注册请求成功"
            return False, "注册提交状态未知"
        except Exception as e:
            return False, f"注册请求异常: {e}"

    def activate_account(self, activation_url):
        try:
            self.session.get(activation_url, timeout=15)
            return True, "激活请求执行完毕"
        except Exception as e:
            return False, f"激活请求异常: {e}"

    def login(self):
        email = self.current_user_data['email']
        password = self.current_user_data['password']
        login_url = urljoin(self.base_url, '/member/ajax.php')
        
        self.session.headers.update({
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': urljoin(self.base_url, '/member/login.php'),
            'Origin': self.base_url
        })
        try:
            resp = self.session.post(login_url, data={
                'uid': email, 'pwd': password, 'w': '1920', 'h': '1080', 'win_ver': 'Win11'
            }, timeout=15)
            self.session.headers.pop('X-Requested-With', None)
            
            if resp.text.strip() == '1':
                return True, "登录成功"
            return False, f"登录失败: {resp.text}"
        except Exception as e:
            return False, f"登录异常: {e}"

    def redeem_coupon(self, code='IGCODE30'):
        url = urljoin(self.base_url, '/member/dsc_ticket.php')
        self.session.headers.update({
            'Referer': urljoin(self.base_url, '/member/dsc_ticket.php'),
            'Origin': self.base_url
        })
        try:
            resp = self.session.post(url, data={'ticket_code': '', 'serial_no': code}, timeout=15)
            if "成功" in resp.text or "success" in resp.text.lower():
                return True, "优惠券兑换成功"
            
            err_match = re.search(r"alert\(['\"](.*?)['\"]\)", resp.text)
            err_msg = err_match.group(1) if err_match else "优惠券无效或已被领完"
            return False, f"兑换失败: {err_msg}"
        except Exception as e:
            return False, f"兑换发生异常: {e}"

    def final_checkout(self, film_id='51489'):
        tw_tz = datetime.timezone(datetime.timedelta(hours=8))
        today = datetime.datetime.now(tw_tz).strftime('%Y-%m-%d')
        
        try:
            # === 1. 初始化结账 ===
            init_url = urljoin(self.base_url, '/order/check_out_sim.php')
            self.session.headers.update({
                'Referer': urljoin(self.base_url, '/member/dsc_ticket.php'),
                'Origin': self.base_url
            })
            res_init = self.session.post(init_url, data={
                'film_id': film_id, 'stock_type_id': '19', 
                'item_type': '1', 'order_qty': '1', 'days': '1'
            }, timeout=15)
            
            match_member = re.search(r'name="member_id"\s+value="([^"]+)"', res_init.text, re.I)
            if match_member:
                self.member_id = match_member.group(1)
            else:
                return False, "未能在结账页找到 Member ID"

            soup_init = BeautifulSoup(res_init.text, 'html.parser')
            coupon_radio = soup_init.find('input', {'type': 'radio', 'name': 'exchanged_id'})
            if coupon_radio and coupon_radio.get('value'):
                self.exchanged_id = coupon_radio.get('value')
            else:
                match = re.search(r'name=["\']exchanged_id["\'].*?value=["\'](\d+)["\']', res_init.text, re.I | re.S)
                if match: self.exchanged_id = match.group(1)
                else: return False, "未能找到优惠券ID，可能账户无券"

            # === 2. 模拟进入 Step 3 ===
            step3_url = urljoin(self.base_url, '/order/check_out_step3.php')
            self.session.headers.update({'Referer': init_url})
            step3_payload = {
                'p_location_id': '00019147', 'rent_location': '00019147',
                'member_id': self.member_id, 'currency': 'T',
                'Latest_Date': today, 'shipping_date': today, 'order_type': 'esim',
                'portal': 'T', 'sale_price[]': '27', 'order_qty[]': '1', 'days[]': '1',
                'subTotal[]': '27', 'film_id[]': film_id, 'cupon_type': '-1',
                'cupon': '', 'exchanged_id': self.exchanged_id, 'btn_ok': '下一步',
                'enable_date[]': today
            }
            res_step3 = self.session.post(step3_url, data=step3_payload, timeout=15)
            soup_step3 = BeautifulSoup(res_step3.text, 'html.parser')

            notice_input = soup_step3.find('input', {'name': 'notice[]'})
            notice = notice_input.get('value', '').strip() if notice_input else ''

            # === 2.5. 获取 Token ===
            token_ajax_url = urljoin(self.base_url, f'/order/ajax.php?cmd=token_id&lang=T&member_id={self.member_id}')
            self.session.headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': step3_url
            })
            token_res = self.session.get(token_ajax_url, timeout=15)
            self.session.headers.pop('X-Requested-With', None)
            
            token_id = token_res.text.strip()
            if not token_id.isdigit(): return False, "获取防重放 Token 失败"

            # === 3. 送出最终订单 ===
            finish_url = urljoin(self.base_url, '/order/check_out_finish.php')
            self.session.headers.update({
                'Referer': step3_url,
                'Origin': self.base_url
            })
            finish_payload = {
                'token_id': token_id, 'p_location_id': '00019147', 'rent_location': '00019147',
                'shipping_date': today, 'currency': 'T', 'member_id': self.member_id,
                'order_type': 'esim', 'portal': 'T', 'film_id[]': film_id, 'stock_type_id[]': '19',
                'order_qty[]': '1', 'days[]': '1', 'sale_price[]': '27', 'discount_price[]': '27',
                'description[]': '27', 'notice[]': notice, 'exchanged_id': self.exchanged_id, 
                'ticket_redeem': '27', 'email': self.current_user_data['email'],
                'nextstep': '確定購買', 'total_point': '0', 'total_sale_point': '0',
                'pay_point': '0', 'invoice_point': '0', 'receipt_point': '27', 
                'descID': 'C', 'pay_type': '', 'S_Fee': '0',
                'enable_date[]': today
            }
            final_res = self.session.post(finish_url, data=finish_payload, timeout=15)
            
            if "check_out_success" in final_res.url or "成功" in final_res.text or "Order Success" in final_res.text or "結帳完成" in final_res.text:
                return True, "0元下单全流程成功"
                
            err_match = re.search(r"alert\(['\"](.*?)['\"]\)", final_res.text)
            if err_match:
                err_detail = err_match.group(1)
            else:
                title_match = re.search(r"<title>(.*?)</title>", final_res.text, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title_text = title_match.group(1).strip()
                    err_detail = f"请求被拦截，重定向至网页: [{title_text}]"
                else:
                    err_detail = "页面未包含明确错误信息(可能被WAF拦截)"
            
            final_path = final_res.url.split('/')[-1]
            return False, f"状态异常 | {err_detail} | 返回URL: {final_path}"
        except Exception as e:
            return False, f"结账流程异常: {e}"

# ================= 异步自动化流程协调器 =================

async def run_ivideo_task(message, context, user):
    await message.edit_text("🏗 **[iVideo] 正在初始化环境...**\n⏳ 正在申请 Mail.tm 临时邮箱...", parse_mode='Markdown')
    
    # 1. 申请临时邮箱
    email, mail_token = await asyncio.get_running_loop().run_in_executor(None, MailTm.create_account)
    if not email or not mail_token:
        await message.edit_text("❌ **初始化失败**\n无法获取临时邮箱 (Mail.tm API 繁忙或失败)，请稍后重试。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_ivideo_entry")]]))
        return
        
    user_manager.increment_usage(user.id, user.first_name)
    bot = iVideoBotCore()
    user_data = bot.generate_random_user(email)
    
    await message.edit_text(f"🚀 **自动账号生成成功**\n📧 账号: `{email}`\n🔑 密码: `{user_data['password']}`\n⏳ 正在提交注册...", parse_mode='Markdown')

    # 2. 提交注册
    reg_ok, reg_msg = await asyncio.get_running_loop().run_in_executor(None, bot.register_flow)
    if not reg_ok:
        await message.edit_text(f"❌ **注册失败**: {reg_msg}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_ivideo_entry")]]))
        return
        
    await message.edit_text(f"📩 **注册请求已发送！**\n⏳ 正在自动监听邮箱，寻找激活链接 (最长 2 分钟)...", parse_mode='Markdown')

    # 3. 监听激活邮件
    activation_link = None
    start_time = datetime.datetime.now()
    loops = 0
    while (datetime.datetime.now() - start_time).total_seconds() < 120:
        try:
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            if mails:
                for mail in mails:
                    subject = mail.get('subject', '')
                    if "啟動" in subject and "iVideo" in subject:
                        mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, mail.get('id'))
                        if mail_detail:
                            body = mail_detail.get('body', '')
                            match = re.search(r'(https?://www\.ivideo\.com\.tw/member/activate\.php\?k=[a-zA-Z0-9]+)', body)
                            if match:
                                activation_link = match.group(1)
                                break
        except Exception as e:
            logger.warning(f"[iVideo] 读取激活邮件异常: {e}")

        if activation_link: break
        
        loops += 1
        if loops % 3 == 0:
            elapsed = int((datetime.datetime.now() - start_time).total_seconds())
            try: await message.edit_text(f"📩 **注册请求已发送！**\n⏳ 正在死守收件箱，寻找激活链接...\n(已等待 {elapsed} 秒，最长 120 秒)", parse_mode='Markdown')
            except: pass
            
        await asyncio.sleep(5)

    if not activation_link:
        await message.edit_text("❌ **等待超时**\n未能在 2 分钟内收到激活邮件。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_ivideo_entry")]]))
        return

    await message.edit_text(f"🔗 **捕获到激活链接！**\n⏳ 正在激活并尝试登录...", parse_mode='Markdown')

    # 4. 激活 & 登录 & 领券 & 下单
    act_ok, act_msg = await asyncio.get_running_loop().run_in_executor(None, bot.activate_account, activation_link)
    if not act_ok:
        await message.edit_text(f"❌ **激活失败**: {act_msg}")
        return

    log_ok, log_msg = await asyncio.get_running_loop().run_in_executor(None, bot.login)
    if not log_ok:
        await message.edit_text(f"❌ **登录失败**: {log_msg}")
        return

    await message.edit_text(f"🎁 **登录成功，正在兑换优惠券与结账...**", parse_mode='Markdown')
    
    cpn_ok, cpn_msg = await asyncio.get_running_loop().run_in_executor(None, bot.redeem_coupon, 'IGCODE30')
    if not cpn_ok:
        await message.edit_text(f"❌ **兑换环节中断**: {cpn_msg}")
        return

    chk_ok, chk_msg = await asyncio.get_running_loop().run_in_executor(None, bot.final_checkout, '51489')
    if not chk_ok:
        await message.edit_text(f"❌ **结账环节中断**: {chk_msg}")
        return

    await message.edit_text(f"🎉 **0元下单成功！**\n📧 账号: `{email}`\n⏳ 正在死守收件箱，等待发货邮件...", parse_mode='Markdown')

    # 5. 监听发货邮件
    esim_data = None
    wait_delivery_start = datetime.datetime.now()
    loops = 0
    while (datetime.datetime.now() - wait_delivery_start).total_seconds() < 300: # 等待发货最多 5 分钟
        try:
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            if mails:
                for mail in mails:
                    subject = mail.get('subject', '')
                    if "送達通知" in subject and "eSIM" in subject:
                        mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, mail.get('id'))
                        if mail_detail:
                            body = mail_detail.get('body', '')
                            
                            esim_info = {}
                            
                            lpa_match = re.search(r'(1\$[\w\.\-]+\$[\w\.\-\=]+)', body)
                            if lpa_match: esim_info['lpa'] = lpa_match.group(1)
                            
                            # 【修复】增加 `\\` 到排除列表，防止匹配到被转义的引号末尾的斜杠
                            qr_exact = re.search(r'(https?://www\.ivideo\.com\.tw/userfiles/qrcode/[^"\'\s>\\]+)', body)
                            if qr_exact:
                                esim_info['qr'] = qr_exact.group(1).rstrip('\\')
                            else:
                                img_matches = re.findall(r'<img[^>]+src=["\']?(https?://[^"\'\\>\s]+)["\']?', body)
                                for img in img_matches:
                                    if 'logo' not in img.lower() and 'icon' not in img.lower() and 'spacer' not in img.lower():
                                        esim_info['qr'] = img.rstrip('\\')
                                        break
                                    
                            if 'lpa' in esim_info or 'qr' in esim_info:
                                esim_data = esim_info
                                break
        except Exception as e:
            logger.warning(f"[iVideo] 读取发货邮件异常: {e}")

        if esim_data: break
        
        loops += 1
        if loops % 3 == 0:
            elapsed = int((datetime.datetime.now() - wait_delivery_start).total_seconds())
            try: await message.edit_text(f"🎉 **0元下单成功！**\n📧 账号: `{email}`\n⏳ 正在死守收件箱，等待发货邮件...\n(已等待 {elapsed} 秒，最长 300 秒)", parse_mode='Markdown')
            except: pass

        await asyncio.sleep(5)

    # 6. 发送最终结果
    if esim_data:
        lpa_str = esim_data.get('lpa', '未找到LPA文本')
        final_text = (
            f"✅ **iVideo eSIM 全自动提取成功！**\n\n"
            f"📧 **账号**: `{email}`\n"
            f"🔑 **密码**: `{user_data['password']}`\n\n"
            f"📡 **安装代码 (LPA)**:\n`{html.escape(lpa_str)}`"
        )
        await context.bot.send_message(chat_id=user.id, text=final_text, parse_mode='Markdown')
        
        if esim_data.get('qr'):
            qr_url = esim_data.get('qr')
            try:
                await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption="📷 官方 eSIM 二维码")
            except Exception as e:
                logger.error(f"[iVideo] 发送官方二维码图片失败: {e}")
                await context.bot.send_message(chat_id=user.id, text=f"🔗 官方二维码链接: [点击查看]({qr_url})", parse_mode='Markdown')
        elif lpa_str and lpa_str.startswith("1$"):
            qr_url = f"https://quickchart.io/qr?text={quote(lpa_str)}&size=400&margin=2"
            try:
                await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption="📷 eSIM 二维码\n(基于 LPA 自动生成，可直接扫描安装)")
            except Exception as e:
                logger.error(f"[iVideo] 发送动态二维码图片失败: {e}")
                await context.bot.send_message(chat_id=user.id, text=f"🔗 扫描二维码: [点击查看图片]({qr_url})", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=user.id, text=f"⚠️ **下单已成功，但 5 分钟内未检测到发货邮件**\n\n您的账号:\n📧 `{email}`\n🔑 `{user_data['password']}`\n请自行保管并稍后登录官网或邮箱检查。", parse_mode='Markdown')

# ================= 菜单与交互 =================

async def ivideo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("ivideo") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text("🛑 **维护中**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode='Markdown')
        return

    text = (
        f"🇹🇼 **iVideo 自动化助手**\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"该流程将全程自动:\n1. 获取临时邮箱注册\n2. 截获激活邮件\n3. 领取代金券\n4. 购买0元商品 (ID: 51489)\n5. 截获发货邮件推送QR/LPA"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 一键全自动薅羊毛", callback_data="ivideo_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def ivideo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    if not user_manager.is_authorized(user.id): return
    if not user_manager.get_plugin_status("ivideo") and str(user.id) != str(ADMIN_ID): return

    if query.data == "ivideo_start":
        asyncio.create_task(run_ivideo_task(query.message, context, user))

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(ivideo_callback, pattern="^ivideo_.*"))
    application.add_handler(CallbackQueryHandler(ivideo_menu, pattern="^plugin_ivideo_entry$"))
    print("🔌 iVideo (自动收信+提取版) 插件已加载")
