import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

# 导入工具
from utils.database import user_manager, ADMIN_ID

# 导入插件
from plugins import yanci
from plugins import flexiroam  # <--- 新增这行

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ 错误：未找到 TG_BOT_TOKEN")
    sys.exit(1)

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_auth = user_manager.is_authorized(user.id)
    is_admin = (str(user.id) == str(ADMIN_ID))

    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"状态: {'✅ 已获授权' if is_auth else '🚫 未获授权'}\n\n"
    )

    keyboard = []

    if is_auth:
        text += "请选择要运行的功能模块："
        # === 功能列表 ===
        keyboard.append([InlineKeyboardButton("🌏 Yanci 抢单助手", callback_data="plugin_yanci_entry")])
        keyboard.append([InlineKeyboardButton("🌐 Flexiroam 助手", callback_data="plugin_flexi_entry")]) # <--- 新增按钮
    else:
        text += "您目前没有使用权限，请点击下方按钮申请。"
        keyboard.append([InlineKeyboardButton("📝 申请使用权限", callback_data="global_request_auth")])

    if is_admin:
         keyboard.append([InlineKeyboardButton("👮 全局管理", callback_data="admin_global")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ================= 全局回调处理 =================

async def main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    
    data = query.data
    
    if data == "main_menu_root":
        await start(update, context)
        return

    # 申请权限
    if data == "global_request_auth":
        if not ADMIN_ID:
            await query.edit_message_text("❌ 未配置管理员 ID。")
            return
        if user_manager.is_authorized(user.id):
            await query.edit_message_text("✅ 您已有权限。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]))
            return

        admin_text = f"📩 **权限申请**\n👤 {user.full_name}\n🆔 `{user.id}`\n🔗 @{user.username}"
        admin_kb = [[InlineKeyboardButton("✅ 通过", callback_data=f"global_agree_{user.id}"), InlineKeyboardButton("❌ 拒绝", callback_data=f"global_deny_{user.id}")]]
        
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode='Markdown')
            await query.edit_message_text("✅ 申请已发送，等待审核。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]))
        except Exception as e:
            logger.error(f"申请失败: {e}")
            await query.edit_message_text("❌ 发送失败。")
        return

    # 管理员操作
    if data.startswith("global_agree_"):
        if str(user.id) != str(ADMIN_ID): return
        target_uid = data.split("_")[-1]
        user_manager.authorize_user(target_uid, username=f"User_{target_uid}")
        await query.edit_message_text(f"✅ 已授权 `{target_uid}`", parse_mode='Markdown')
        try: await context.bot.send_message(chat_id=target_uid, text="🎉 权限申请已通过！/start 刷新。")
        except: pass
        return

    if data.startswith("global_deny_"):
        if str(user.id) != str(ADMIN_ID): return
        target_uid = data.split("_")[-1]
        await query.edit_message_text(f"❌ 已拒绝 `{target_uid}`", parse_mode='Markdown')
        try: await context.bot.send_message(chat_id=target_uid, text="⚠️ 权限申请被拒绝。")
        except: pass
        return

    if data == "admin_global":
        if str(user.id) != str(ADMIN_ID): return
        stats = user_manager.get_all_stats()
        text = f"👮 **管理面板**\n用户数: {len(stats)}\n回复 ID 可进行操作。"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode='Markdown')

async def post_init(application):
    await application.bot.set_my_commands([BotCommand("start", "打开主菜单")])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. 注册主程序
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_global$"))
    
    # 2. 加载插件
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)  # <--- 注册新插件
    
    print("✅ 机器人已启动 (Yanci + Flexiroam)...")
    application.run_polling()

if __name__ == '__main__':
    main()
