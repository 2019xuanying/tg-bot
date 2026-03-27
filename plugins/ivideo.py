import logging
import asyncio
import re
import random
import string
import datetime
import urllib.parse
import html
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
        self.member_id = None
        self.exchanged_id = None
        self.current_user_data = {}

    def generate_random_user(self, email):
        """生成随机的注册资料"""
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        first_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=5))
        last_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=7))
        
        user_data = {
            'email': email,
            'name': f"{first_name} {last_name}",
            'mobile': "09" + ''.join(random.choices(string.digits, k=8)), # 模拟台湾手机号格式
            'password': "Wang" + ''.join(random.choices(string.digits, k=6)) + "."
        }
        self.current_user_data = user_data
        logger.info(f"[*] 生成随机身份: {user_data['name']} | {user_data['email']}")
        return user_data

    def register_flow(self):
        """执行全自动注册流程 (Step 1 -> 3)"""
        d = self.current_user_data
        
        # Step 1
        self.session.post(f"{self.base_url}/sign-up/SignUp_Step1.php", data={
            'member_type_id': '', 'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
            'email': d['email'], 'name': d['name']
        }, timeout=15)

        # Step 3
        step3_url = f"{self.base_url}/sign-up/SignUp_Step3.php"
        payload = {
            'birthday': '3/3/1992', 'member_type_id': '1', 'country_code': '886', 'country_id': '112',
            'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
            'email': d['email'], 'name': d['name'], 'mobile_phone': d['mobile'],
            'password1': d['password'], 'password2': d['password'],
            'line_id': '', 'recommend_email': ''
        }
        resp = self.session.post(step3_url, data=payload, timeout=15)
        if "成功" in resp.text or resp.status_code == 200:
            return True
        return False

    def extract_activation_link(self, body):
        """正则提取邮件中的激活链接"""
        match = re.search(r'(https://www\.ivideo\.com\.tw/member/activate\.php\?k=[a-zA-Z0-9]+)', body)
        return match.group(1) if match else None

    def login_and_extract(self):
        """登录并提取关键 ID"""
        login_url = f"{self.base_url}/member/ajax.php"
        self.session.post(login_url, data={
            'uid': self.current_user_data['email'], 'pwd': self.current_user_data['password'], 
            'w': '1920', 'h': '1080', 'win_ver': 'Win11'
        }, headers={'X-Requested-With': 'XMLHttpRequest'}, timeout=15)
        
        # 使用正则表达式替代 BeautifulSoup 以降低依赖
        res = self.session.get(f"{self.base_url}/member/modify_member.php", timeout=15)
        
        match = re.search(r'name="member_id"[^>]*value="(\d+)"', res.text)
        if not match:
            match = re.search(r'value="(\d+)"[^>]*name="member_id"', res.text)
            
        if match:
            self.member_id = match.group(1)
            return True
        return False

    def redeem_coupon_and_get_id(self, code='IGCODE30'):
        """兑换并提取流水 ID"""
        url = f"{self.base_url}/member/dsc_ticket.php"
        self.session.post(url, data={'serial_no': code}, timeout=15)
        
        res = self.session.get(url, timeout=15)
        match = re.search(rf'value="(\d+)".*?{code}', res.text, re.I | re.S)
        if match:
            self.exchanged_id = match.group(1)
            return True
        return False

    def final_checkout(self, film_id='51489'):
        """执行最终下单"""
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        step3_payload = {
            'p_location_id': '00019147', 'rent_location': '00019147',
            'member_id': self.member_id, 'currency': 'T',
            'Latest_Date': today, 'shipping_date': today, 'order_type': 'esim',
            'portal': 'T', 'sale_price[]': '27', 'order_qty[]': '1', 'days[]': '1',
            'subTotal[]': '27', 'film_id[]': film_id, 'cupon_type': '-1',
            'cupon': '', 'exchanged_id': self.exchanged_id, 'btn_ok': '下一步'
        }
        res_step3 = self.session.post(f"{self.base_url}/order/check_out_step3.php", data=step3_payload, timeout=20)
        
        # 提取 token_id 和 notice
        token_match = re.search(r'name="token_id"[^>]*value="([^"]+)"', res_step3.text)
        if not token_match: 
            token_match = re.search(r'value="([^"]+)"[^>]*name="token_id"', res_step3.text)
            
        notice_match = re.search(r'name="notice\[\]"[^>]*value="([^"]*)"', res_step3.text)
        if not notice_match: 
            notice_match = re.search(r'value="([^"]*)"[^>]*name="notice\[\]"', res_step3.text)
            
        if not token_match:
            return False, "未能提取到结算的 token_id"
            
        token_id = token_match.group(1)
        notice = notice_match.group(1) if notice_match else ""

        finish_payload = {
            'token_id': token_id, 'p_location_id': '00019147', 'rent_location': '00019147',
            'shipping_date': today, 'currency': 'T', 'member_id': self.member_id,
            'order_type': 'esim', 'portal': 'T', 'film_id[]': film_id, 'stock_type_id[]': '19',
            'order_qty[]': '1', 'days[]': '1', 'sale_price[]': '27', 'discount_price[]': '27',
            'description[]': '27', 'notice[]': notice, 'exchanged_id': self.exchanged_id,
            'ticket_redeem': '27', 'email': self.current_user_data['email'],
            'nextstep': '確定購買', 'receipt_point': '27', 'descID': 'C'
        }
        
        final_res = self.session.post(f"{self.base_url}/order/check_out_finish.php", data=finish_payload, timeout=20)
        
        # 验证结账结果
        if "完成" in final_res.text or "成功" in final_res.text or "訂單編號" in final_res.text:
            return True, "下单成功"
        return False, "未能确认结账结果，请稍后检查邮箱"

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
        reg_ok = await asyncio.get_running_loop().run_in_executor(None, logic.register_flow)
        if not reg_ok:
            await message.edit_text(f"❌ <b>注册提交失败</b>\n目标服务器拒绝了注册请求。", parse_mode='HTML')
            return

        # 3. 轮询邮箱等待激活
        await message.edit_text(f"📩 <b>已发送激活邮件！</b>\n⏳ 正在自动监听收件箱 (最多等2分钟)...", parse_mode='HTML')
        activation_link = None
        
        for _ in range(30): # 2分钟超时
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
        await asyncio.get_running_loop().run_in_executor(None, session.get, activation_link)
        await message.edit_text(f"✅ <b>邮箱激活成功！</b>\n⏳ 正在提取会员 ID 与优惠券...", parse_mode='HTML')

        # 5. 登录并绑定资料
        login_ok = await asyncio.get_running_loop().run_in_executor(None, logic.login_and_extract)
        if not login_ok:
            await message.edit_text("❌ <b>登录或提取 Member ID 失败。</b>", parse_mode='HTML')
            return

        # 6. 兑换 Code
        redeem_ok = await asyncio.get_running_loop().run_in_executor(None, logic.redeem_coupon_and_get_id, 'IGCODE30')
        if not redeem_ok:
            await message.edit_text("❌ <b>优惠码兑换失败，可能已被系统限制或活动结束。</b>", parse_mode='HTML')
            return

        # 7. 结账下单
        await message.edit_text(f"🛒 <b>正在进行最终 0 元下单结算...</b>", parse_mode='HTML')
        checkout_ok, checkout_msg = await asyncio.get_running_loop().run_in_executor(None, logic.final_checkout)

        if checkout_ok:
            result_text = (
                f"🎉 <b>iVideo 下单全流程成功！</b>\n\n"
                f"👤 <b>姓名</b>: <code>{html.escape(user_data['name'])}</code>\n"
                f"📧 <b>邮箱</b>: <code>{html.escape(user_data['email'])}</code>\n"
                f"🔑 <b>密码</b>: <code>{html.escape(user_data['password'])}</code>\n\n"
                f"💡 <i>请登录此邮箱或前往官网查收您的 eSIM 订单。</i>"
            )
            keyboard = [[InlineKeyboardButton("🔙 返回 iVideo 菜单", callback_data="plugin_ivideo_entry")]]
            await message.edit_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        else:
            await message.edit_text(f"❌ <b>结账异常</b>: {checkout_msg}", parse_mode='HTML')

    except Exception as e:
        logger.error(f"iVideo Task Error: {e}", exc_info=True)
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
        f"📼 <b>iVideo 自动下单助手</b>\n"
        f"状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"此模块将全自动帮您生成信息 -> 获取验证码 -> 激活账户 -> 绑定 30 元折扣券 -> 完成结算！"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 一键生成随机账户并下单", callback_data="ivideo_start")],
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
    print("🔌 iVideo 助手插件已加载")
