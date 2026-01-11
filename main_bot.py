import os
import sys
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

# 导入工具
from utils.database import user_manager, ADMIN_ID

# 导入插件
from plugins import yanci
# from plugins import other_script  <-- 未来在这里加新脚本

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ 错误：未找到 TG_BOT_TOKEN")
    sys.exit(1)

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"请选择要运行的功能模块："
    )
    
    # 动态构建菜单
    keyboard = [
        # 指向 Yanci 插件的入口 callback
        [InlineKeyboardButton("🌏 Yanci 抢单助手", callback_data="plugin_yanci_entry")],
        
        # 未来可以在这里加按钮
        # [InlineKeyboardButton("📱 其他项目", callback_data="plugin_other_entry")],
    ]
    
    # 管理员入口
    if user_manager.is_authorized(user.id) and str(user.id) == str(ADMIN_ID):
         keyboard.append([InlineKeyboardButton("👮 全局管理", callback_data="admin_global")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理主程序的通用回调"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu_root":
        await start(update, context)
        return
        
    if query.data == "admin_global":
        await query.edit_message_text(
            "👮 **全局管理面板**\n目前功能请进入各插件内部管理。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]])
        )

async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "打开主菜单"),
    ])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. 注册主程序 Handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^admin_global$"))
    
    # 2. 🔌 加载插件
    yanci.register_handlers(application)
    # other_script.register_handlers(application)
    
    print("✅ 机器人已启动 (模块化架构)...")
    application.run_polling()

if __name__ == '__main__':
    main()