import logging
import asyncio
import re
import random
import string
import datetime
import html
import time
import traceback
from urllib.parse import urljoin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session
from utils.mail import MailTm

logger = logging.getLogger(__name__)

class IVideoLogic:
    def __init__(self, session):
        self.session = session
        self.base_url = 'https://www.ivideo.com.tw'
        
        # 模拟真实浏览器行为
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Connection': 'keep-alive',
        })
        
        self.member_id = None
        self.exchanged_id = None
        self.current_user_data = {}

    def generate_random_user(self, email):
        """生成随机的注册资料"""
        first_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=5))
        last_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=7))
        
        user_data = {
            'email': email,
            'name': f"{first_name} {last_name}",
            'mobile': "09" + ''.join(random.choices(string.digits, k=8)), # 台湾手机号格式
            'password': "Wang" + ''.join(random.choices(string.digits, k=6)) + "." # 满足复杂度的密码
        }
        
        self.current_user_data = user_data
        logger.info(f"[*] 生成身份 -> 姓名: {user_data['name']} | 邮箱: {user_data['email']}")
        return user_data

    def register_flow(self):
        """执行全自动注册流程 (Step 1 -> 3)"""
        d = self.current_user_data
        try:
            # Step 1
            step1_url = urljoin(self.base_url, '/sign-up/SignUp_Step1.php')
            self.session.post(step1_url, data={
                'member_type_id': '', 'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': d['email'], 'name': d['name']
            }, timeout=15)

            # Step 3
            step3_url = urljoin(self.base_url, '/sign-up/SignUp_Step3.php')
            payload = {
                'birthday': '3/3/1992', 'member_type_id': '1', 'country_code': '886', 'country_id': '112',
                'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': d['email'], 'name': d['name'], 'mobile_phone': d['mobile'],
                'password1': d['password'], 'password2': d['password'],
                'line_id': '', 'recommend_email': ''
            }
            resp = self.session.post(step3_url, data=payload, timeout=15)
            
            if "成功" in resp.text or resp.status_code in [200, 302]:
                return True, "注册成功，已发送验证邮件"
            return False, "注册提交返回状态未知"
        except Exception as e:
            logger.error(f"[-] 注册请求异常: {e}")
            return False, str(e)

    def extract_activation_link(self, body):
        """正则提取邮件中的激活链接"""
        match = re.search(r'(https://www\.ivideo\.com\.tw/member/activate\.php\?k=[a-zA-Z0-9]+)', body)
        return match.group(1) if match else None

    def activate_account(self, activation_url):
        """代为请求激活链接"""
        try:
            self.session.get(activation_url, timeout=15)
            return True
        except Exception as e:
            logger.error(f"[-] 激活请求异常: {e}")
            return False

    def login(self):
        """执行登录"""
        email = self.current_user_data['email']
        password = self.current_user_data['password']
        login_url = urljoin(self.base_url, '/member/ajax.php')
        
        self.session.headers.update({'X-Requested-With': 'XMLHttpRequest'})
        try:
            resp = self.session.post(login_url, data={
                'uid': email, 'pwd': password, 'w': '1920', 'h': '1080', 'win_ver': 'Win11'
            }, timeout=15)
            self.session.headers.pop('X-Requested-With', None)
            
            if resp.text.strip() == '1':
                return True, "登录成功"
            return False, f"登录失败: {resp.text[:50]}"
        except Exception as e:
            return False, str(e)

    def redeem_coupon(self, code='IGCODE30'):
        """执行兑换动作"""
        url = urljoin(self.base_url, '/member/dsc_ticket.php')
        try:
            redeem_resp = self.session.post(url, data={'ticket_code': '', 'serial_no': code}, timeout=15)
            if "成功" in redeem_resp.text or "success" in redeem_resp.text.lower():
                return True, "优惠券兑换成功"
            return False, f"兑换失败: {redeem_resp.text[:50]}"
        except Exception as e:
            return False, str(e)

    def final_checkout(self, film_id='51489'):
        """执行结账，动态获取 AJAX Token (无 BS4 依赖纯正则版)"""
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        try:
            # === 1. 初始化结账 ===
            init_url = urljoin(self.base_url, '/order/check_out_sim.php')
            res_init = self.session.post(init_url, data={
                'film_id': film_id, 'stock_type_id': '19', 
                'item_type': '1', 'order_qty': '1', 'days': '1'
            }, timeout=15)
            
            # 提取 Member ID
            match_member = re.search(r'name="member_id"\s+value="([^"]+)"', res_init.text, re.I)
            if match_member:
                self.member_id = match_member.group(1)
            else:
                return False, "未能提取 Member ID"

            # 提取 Exchanged ID (优惠券流水号)
            match_exch = re.search(r'name=["\']exchanged_id["\'].*?value=["\'](\d+)["\']', res_init.text, re.I | re.S)
            if not match_exch:
                match_exch = re.search(r'value=["\'](\d+)["\'][^>]*name=["\']exchanged_id["\']', res_init.text, re.I | re.S)
            
            if match_exch:
                self.exchanged_id = match_exch.group(1)
            else:
                return False, "未能提取优惠券流水 ID (exchanged_id)"

            # === 2. 模拟进入 Step 3 结算确认页 ===
            step3_url = urljoin(self.base_url, '/order/check_out_step3.php')
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

            # 提取 Notice
            notice_match = re.search(r'name=["\']notice\[\]["\'][^>]*value=["\']([^"\']*)["\']', res_step3.text, re.I)
            if not notice_match:
                notice_match = re.search(r'value=["\']([^"\']*)["\'][^>]*name=["\']notice\[\]["\']', res_step3.text, re.I)
            notice = notice_match.group(1).strip() if notice_match else ''

            # === 2.5. 通过 AJAX 接口获取真正的 Token ===
            token_ajax_url = urljoin(self.base_url, f'/order/ajax.php?cmd=token_id&lang=T&member_id={self.member_id}')
            self.session.headers.update({'X-Requested-With': 'XMLHttpRequest'})
            token_res = self.session.get(token_ajax_url, timeout=15)
            self.session.headers.pop('X-Requested-With', None)
            
            token_id = token_res.text.strip()
            if not token_id.isdigit():
                return False, f"获取 Token 失败，非预期数据: {token_id[:20]}"

            # === 3. 送出最终订单 ===
            finish_url = urljoin(self.base_url, '/order/check_out_finish.php')
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
            
            if "check_out_success" in final_res.url or "成功" in final_res.text or "Order Success" in final_res.text:
                return True, "0元下单全流程成功"
            return False, "最终提交状态异常"
                
        except Exception as e:
            logger.error(f"[-] 结账流程发生异常: {traceback.format_exc()}")
            return False, str(e)

    @staticmethod
    def extract_esim_info(html_content):
        """解析发货邮件中的 eSIM QR 和 LPA 代码"""
        if not html_content or not isinstance(html_content, str): return None
        info = {}
        
        # 提取 LPA 字符串
        lpa_match = re.search(r'(LPA:1\$[\w\.\-]+\$[\w\.\-]+)', html_content)
        if lpa_match:
            info['lpa_str'] = lpa_match.group(1)
        else:
            # 兼容分体式 SM-DP+ 和 激活码
            smdp_match = re.search(r'SM-DP\+Address.*?([a-zA-Z0-9\.\-]+)', html_content, re.IGNORECASE | re.DOTALL)
            code_match = re.search(r'Activation Code.*?([a-zA-Z0-9\.\-]+)', html_content, re.IGNORECASE | re.DOTALL)
            if smdp_match and code_match:
                info['lpa_str'] = f"LPA:1${smdp_match.group(1).strip()}${code_match.group(1).strip()}"

        # 提取 QR 码图片链接 (寻找 quickchart 或其他 img src)
        qr_match = re.search(r'(https?://quickchart\.io/qr\?[^"\'\s>]+)', html_content)
        if qr_match:
            info['qr_url'] = qr_match.group(1).replace('&amp;', '&')
        else:
            img_candidates = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content)
            for img_url in img_candidates:
                if 'qr' in img_url.lower() or 'barcode' in img_url.lower():
                    info['qr_url'] = img_url
                    break

        return info if info else None

# ================= 任务调度流 =================

async def run_ivideo_task(message, context, user):
    try:
        # 1. 初始化会话与邮箱
        session = await asyncio.get_running_loop().run_in_executor(None, get_safe_session, "https://www.ivideo.com.tw", 10)
        email, mail_token = await asyncio.get_running_loop().run_in_executor(None, MailTm.create_account)
        
        if not email or not mail_token:
            await message.edit_text("❌ <b>初始化失败</b>\n无法获取 Mail.tm 临时邮箱，请稍后重试。", parse_mode='HTML')
            return

        logic = IVideoLogic(session)
        user_data = logic.generate_random_user(email)
        
        await message.edit_text(f"⏳ <b>正在自动注册 iVideo 账户...</b>\n📧 邮箱: <code>{html.escape(email)}</code>", parse_mode='HTML')
        
        # 2. 提交注册
        reg_ok, reg_msg = await asyncio.get_running_loop().run_in_executor(None, logic.register_flow)
        if not reg_ok:
            await message.edit_text(f"❌ <b>注册提交失败</b>\n{html.escape(reg_msg)}", parse_mode='HTML')
            return

        # 3. 轮询邮箱等待激活
        await message.edit_text(f"📩 <b>已发送激活邮件！</b>\n⏳ 正在自动监听收件箱 (最多等2分钟)...", parse_mode='HTML')
        activation_link = None
        
        start_time = time.time()
        while time.time() - start_time < 120:
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            if mails:
                for m in mails:
                    if "iVideo" in m.get('subject', ''):
                        mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, m.get('id'))
                        if mail_detail:
                            activation_link = logic.extract_activation_link(mail_detail.get('body', ''))
                            if activation_link:
                                break
            if activation_link:
                break
            await asyncio.sleep(4)

        if not activation_link:
            await message.edit_text("❌ <b>超时未收到激活邮件。</b>\n任务已终止。", parse_mode='HTML')
            return

        # 4. 点击激活链接
        await message.edit_text(f"✅ <b>邮箱激活成功！</b>\n⏳ 正在登录并提取防重放 Token...", parse_mode='HTML')
        await asyncio.get_running_loop().run_in_executor(None, logic.activate_account, activation_link)

        # 5. 登录并绑定资料
        login_ok, login_msg = await asyncio.get_running_loop().run_in_executor(None, logic.login)
        if not login_ok:
            await message.edit_text(f"❌ <b>登录失败</b>: {html.escape(login_msg)}", parse_mode='HTML')
            return

        # 6. 兑换 Code
        redeem_ok, redeem_msg = await asyncio.get_running_loop().run_in_executor(None, logic.redeem_coupon, 'IGCODE30')
        if not redeem_ok:
            await message.edit_text(f"❌ <b>优惠码兑换失败</b>: {html.escape(redeem_msg)}", parse_mode='HTML')
            return

        # 7. 结账下单
        await message.edit_text(f"🛒 <b>正在进行最终 0 元下单结算...</b>", parse_mode='HTML')
        checkout_ok, checkout_msg = await asyncio.get_running_loop().run_in_executor(None, logic.final_checkout)

        if not checkout_ok:
            await message.edit_text(f"❌ <b>结账异常</b>: {html.escape(checkout_msg)}", parse_mode='HTML')
            return

        # 8. 等待并提取发货邮件 (新增自动化取码逻辑)
        await message.edit_text(
            f"🎉 <b>0元下单成功！</b>\n"
            f"📧 邮箱: <code>{html.escape(email)}</code>\n"
            f"⏳ <b>正在监听发货邮件，提取 eSIM 代码 (最多等待5分钟)...</b>\n"
            f"<i>(请勿关闭此对话)</i>", 
            parse_mode='HTML'
        )
        
        esim_data = None
        wait_mail_start = time.time()
        
        while time.time() - wait_mail_start < 300: 
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            if mails:
                for m in mails:
                    subject = m.get('subject', '')
                    # iVideo eSIM 发货邮件通常带有 eSIM, QR code, Order 等字样
                    if any(k in subject for k in ["eSIM", "QR", "訂單", "Order"]):
                        mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, m.get('id'))
                        if mail_detail:
                            extracted = logic.extract_esim_info(mail_detail.get('body', ''))
                            if extracted and extracted.get('lpa_str'):
                                esim_data = extracted
                                break
            if esim_data: break
            await asyncio.sleep(5)

        # 9. 结果展示
        if esim_data:
            lpa_str = esim_data.get('lpa_str', '未知')
            final_text = (
                f"✅ <b>iVideo eSIM 提取成功！</b>\n\n"
                f"👤 姓名: <code>{html.escape(user_data['name'])}</code>\n"
                f"📧 邮箱: <code>{html.escape(user_data['email'])}</code>\n"
                f"🔑 密码: <code>{html.escape(user_data['password'])}</code>\n\n"
                f"📡 <b>LPA 激活串</b>: \n<code>{html.escape(lpa_str)}</code>\n\n"
                f"祝您使用愉快！"
            )
            # 发送最终文本
            await context.bot.send_message(chat_id=user.id, text=final_text, parse_mode='HTML')
            
            # 尝试发送二维码图片
            qr_url = esim_data.get('qr_url')
            if user_manager.get_config("send_qr", True) and qr_url:
                try:
                    await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption="📷 eSIM 二维码")
                except Exception as e:
                    logger.error(f"发图失败: {e}")
                    await context.bot.send_message(chat_id=user.id, text="⚠️ 二维码图片解析发送失败，请直接复制上方 LPA 激活。")
        else:
            final_text = (
                f"✅ <b>订单处理成功，但暂未收到发货邮件。</b>\n\n"
                f"👤 姓名: <code>{html.escape(user_data['name'])}</code>\n"
                f"📧 邮箱: <code>{html.escape(user_data['email'])}</code>\n"
                f"🔑 密码: <code>{html.escape(user_data['password'])}</code>\n\n"
                f"可能由于服务商延迟发信，您可以稍后使用以上账密登录官网获取二维码。"
            )
            await context.bot.send_message(chat_id=user.id, text=final_text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"iVideo Task Error: {traceback.format_exc()}")
        await message.edit_text(f"💥 <b>系统错误</b>: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

# ================= 菜单与交互 =================

async def ivideo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """iVideo 插件入口"""
    user = update.effective_user
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("ivideo") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 <b>该功能目前维护中</b>\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='HTML'
        )
        return

    text = (
        f"📼 <b>iVideo 自动下单助手 (Pro版)</b>\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"此模块将全自动执行以下流程：\n"
        f"1️⃣ 随机生成台籍身份与临时邮箱\n"
        f"2️⃣ 轮询验证邮件并激活账户\n"
        f"3️⃣ 底层接口提取防重放 Token\n"
        f"4️⃣ 绑定折扣券进行 0元 极速结算\n"
        f"5️⃣ 监听发货邮件并自动解析 LPA 代码"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 一键全自动生成并提取 eSIM", callback_data="ivideo_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def ivideo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    if not user_manager.is_authorized(user.id): return
    if not user_manager.get_plugin_status("ivideo") and str(user.id) != str(ADMIN_ID): return

    if data == "ivideo_start":
        user_manager.increment_usage(user.id, user.first_name)
        await query.edit_message_text(
            "⏳ <b>正在为您调度 iVideo 提取节点...</b>\n请稍等片刻...", 
            parse_mode='HTML'
        )
        asyncio.create_task(run_ivideo_task(query.message, context, user))
        return

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(ivideo_callback, pattern="^ivideo_.*"))
    application.add_handler(CallbackQueryHandler(ivideo_menu, pattern="^plugin_ivideo_entry$"))
    print("🔌 iVideo (全自动接码版) 插件已加载")
