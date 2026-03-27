import logging
import random
import string
import asyncio
import traceback
import datetime
import re
import html
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session
from utils.mail import MailTm

logger = logging.getLogger(__name__)

class IVideoLogic:
    BASE_URL = 'https://www.ivideo.com.tw'

    @staticmethod
    def generate_random_user(domain="zenvex.edu.pl"):
        """生成随机的注册资料"""
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        first_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=5))
        last_name = ''.join(random.choices(string.ascii_uppercase, k=1)) + ''.join(random.choices(string.ascii_lowercase, k=7))
        
        return {
            'email': f"{random_str}@{domain}",
            'name': f"{first_name} {last_name}",
            'mobile': "09" + ''.join(random.choices(string.digits, k=8)),
            'password': "Wang" + ''.join(random.choices(string.digits, k=6)) + "."
        }

    @staticmethod
    async def run_process(status_msg, context):
        """核心业务流"""
        session = await asyncio.get_running_loop().run_in_executor(None, get_safe_session, "https://www.ivideo.com.tw", 10)
        
        # 1. 获取临时邮箱
        await status_msg.edit_text("⏳ 正在申请临时邮箱 (Mail.tm)...")
        email, mail_token = await asyncio.get_running_loop().run_in_executor(None, MailTm.create_account)
        if not email:
            return False, "无法获取临时邮箱，API 繁忙。"

        user_data = IVideoLogic.generate_random_user(domain=email.split('@')[1])
        user_data['email'] = email # 修正为生成的 Mail.tm 邮箱
        
        # 2. 提交注册
        await status_msg.edit_text(f"📝 正在注册身份: <code>{user_data['name']}</code>...")
        try:
            # Step 1
            await asyncio.get_running_loop().run_in_executor(None, lambda: session.post(urljoin(IVideoLogic.BASE_URL, '/sign-up/SignUp_Step1.php'), data={
                'member_type_id': '', 'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': user_data['email'], 'name': user_data['name']
            }))
            
            # Step 3
            payload = {
                'birthday': '3/3/1992', 'member_type_id': '1', 'country_code': '886', 'country_id': '112',
                'gender': '男', 'year': '1992', 'month': '3', 'day': '3',
                'email': user_data['email'], 'name': user_data['name'], 'mobile_phone': user_data['mobile'],
                'password1': user_data['password'], 'password2': user_data['password'],
                'line_id': '', 'recommend_email': ''
            }
            await asyncio.get_running_loop().run_in_executor(None, lambda: session.post(urljoin(IVideoLogic.BASE_URL, '/sign-up/SignUp_Step3.php'), data=payload))
        except Exception as e:
            return False, f"注册请求提交失败: {str(e)}"

        # 3. 自动监听激活邮件
        await status_msg.edit_text("📩 注册已提交，正在等待激活邮件...")
        activation_link = None
        start_time = datetime.datetime.now()
        while (datetime.datetime.now() - start_time).seconds < 120:
            mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
            for m in mails:
                detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, m['id'])
                if detail and ("Activate" in detail['body'] or "驗證" in detail['body'] or "SignUp_Step4" in detail['body']):
                    match = re.search(r'href="(https?://[^"]+SignUp_Step4\.php[^"]+)"', detail['body'])
                    if match:
                        activation_link = match.group(1).replace('&amp;', '&')
                        break
            if activation_link: break
            await asyncio.sleep(5)

        if not activation_link:
            return False, "激活邮件超时未收到。"

        # 4. 执行激活
        await status_msg.edit_text("🔗 捕获到激活链接，正在验证账户...")
        await asyncio.get_running_loop().run_in_executor(None, lambda: session.get(activation_link))

        # 5. 登录并下单
        await status_msg.edit_text("🔑 正在登录并准备下单...")
        try:
            # Login
            session.post(urljoin(IVideoLogic.BASE_URL, '/member/ajax.php'), data={
                'uid': user_data['email'], 'pwd': user_data['password'], 'w': '1920', 'h': '1080', 'win_ver': 'Win11'
            }, headers={'X-Requested-With': 'XMLHttpRequest'})
            
            # Extract member_id
            res = session.get(urljoin(IVideoLogic.BASE_URL, '/member/modify_member.php'))
            soup = BeautifulSoup(res.text, 'lxml')
            member_id = soup.find('input', {'name': 'member_id'}).get('value')
            
            # Redeem Coupon
            session.post(urljoin(IVideoLogic.BASE_URL, '/member/dsc_ticket.php'), data={'serial_no': 'IGCODE30'})
            res_coupon = session.get(urljoin(IVideoLogic.BASE_URL, '/member/dsc_ticket.php'))
            exchanged_id = re.search(r'value="(\d+)".*?IGCODE30', res_coupon.text, re.I | re.S).group(1)
            
            # Checkout
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            film_id = '51489'
            step3_payload = {
                'p_location_id': '00019147', 'rent_location': '00019147',
                'member_id': member_id, 'currency': 'T', 'Latest_Date': today, 'shipping_date': today,
                'order_type': 'esim', 'portal': 'T', 'sale_price[]': '27', 'order_qty[]': '1',
                'days[]': '1', 'subTotal[]': '27', 'film_id[]': film_id, 'cupon_type': '-1',
                'cupon': '', 'exchanged_id': exchanged_id, 'btn_ok': '下一步'
            }
            res_step3 = session.post(urljoin(IVideoLogic.BASE_URL, '/order/check_out_step3.php'), data=step3_payload)
            soup_s3 = BeautifulSoup(res_step3.text, 'lxml')
            token_id = soup_s3.find('input', {'name': 'token_id'}).get('value')
            notice = soup_s3.find('input', {'name': 'notice[]'}).get('value')

            finish_payload = {
                'token_id': token_id, 'p_location_id': '00019147', 'rent_location': '00019147',
                'shipping_date': today, 'currency': 'T', 'member_id': member_id,
                'order_type': 'esim', 'portal': 'T', 'film_id[]': film_id, 'stock_type_id[]': '19',
                'order_qty[]': '1', 'days[]': '1', 'sale_price[]': '27', 'discount_price[]': '27',
                'description[]': '27', 'notice[]': notice, 'exchanged_id': exchanged_id,
                'ticket_redeem': '27', 'email': user_data['email'], 'nextstep': '确定购买', 'receipt_point': '27', 'descID': 'C'
            }
            final_res = session.post(urljoin(IVideoLogic.BASE_URL, '/order/check_out_finish.php'), data=finish_payload)
            
            if "完成" in final_res.text:
                return True, f"🎉 <b>iVideo 下单成功！</b>\n📧 账号: <code>{user_data['email']}</code>\n🔑 密码: <code>{user_data['password']}</code>\n\n请在 1-5 分钟后留意该邮箱收到的 eSIM QR Code 邮件。"
            else:
                return False, "下单最后一步失败，可能优惠券失效或库存不足。"
        except Exception as e:
            return False, f"流程执行异常: {str(e)}"

# ================= 交互处理 =================

async def ivideo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user_manager.is_authorized(user.id): return
    
    text = (
        f"📹 <b>iVideo 自动化下单助手</b>\n"
        f"此插件将全自动完成：注册 -> 自动邮件激活 -> 兑换 IGCODE30 优惠券 -> 下单。\n\n"
        f"完成后请登录该邮箱查看发货二维码。"
    )
    keyboard = [[InlineKeyboardButton("🚀 立即一键下单", callback_data="ivideo_start")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def ivideo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "ivideo_start":
        user_manager.increment_usage(query.from_user.id, query.from_user.first_name)
        status_msg = await query.edit_message_text("⏳ 正在初始化 iVideo 全自动流程...")
        success, result = await IVideoLogic.run_process(status_msg, context)
        
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="plugin_ivideo_entry")]]
        if success:
            await status_msg.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        else:
            await status_msg.edit_text(f"❌ <b>任务失败</b>\n原因: {result}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

def register_handlers(app):
    app.add_handler(CallbackQueryHandler(ivideo_menu, pattern="^plugin_ivideo_entry$"))
    app.add_handler(CallbackQueryHandler(ivideo_callback, pattern="^ivideo_.*"))
    print("🔌 iVideo 全自动下单插件已加载")
