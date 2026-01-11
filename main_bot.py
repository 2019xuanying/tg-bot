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
# from plugins import other_script 

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

# ================= 主菜单逻辑 (全局大门) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_auth = user_manager.is_authorized(user.id)
    is_admin = (str(user.id) == str(ADMIN_ID))

    # 1. 欢迎语
    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"状态: {'✅ 已获授权' if is_auth else '🚫 未获授权'}\n\n"
    )

    keyboard = []

    # 2. 根据权限显示不同菜单
    if is_auth:
        text += "请选择要运行的功能模块："
        # === 已授权用户可见的功能 ===
        keyboard.append([InlineKeyboardButton("🌏 Yanci 抢单助手", callback_data="plugin_yanci_entry")])
        # keyboard.append([InlineKeyboardButton("📱 其他项目", callback_data="plugin_other_entry")])
    else:
        text += "您目前没有使用权限，请点击下方按钮申请。"
        # === 未授权用户只能看到申请按钮 ===
        keyboard.append([InlineKeyboardButton("📝 申请使用权限", callback_data="global_request_auth")])

    # 3. 管理员入口 (总是可见)
    if is_admin:
         keyboard.append([InlineKeyboardButton("👮 全局管理", callback_data="admin_global")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ================= 全局回调处理 (申请/审批) =================

async def main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理主程序的通用回调"""
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    
    data = query.data
    
    if data == "main_menu_root":
        await start(update, context)
        return

    # === 1. 用户点击申请 ===
    if data == "global_request_auth":
        if not ADMIN_ID:
            await query.edit_message_text("❌ 系统错误：未配置管理员 ID，无法提交申请。")
            return

        # 再次检查是否已经授权（防止重复申请）
        if user_manager.is_authorized(user.id):
            await query.edit_message_text("✅ 您已经拥有权限，请点击返回刷新菜单。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]))
            return

        # 给管理员发消息
        admin_text = (
            f"📩 **收到新的权限申请**\n\n"
            f"👤 用户: {user.full_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"🔗 账号: @{user.username if user.username else '无'}"
        )
        admin_keyboard = [
            [
                InlineKeyboardButton("✅ 通过", callback_data=f"global_agree_{user.id}"),
                InlineKeyboardButton("❌ 拒绝", callback_data=f"global_deny_{user.id}")
            ]
        ]
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID, 
                text=admin_text, 
                reply_markup=InlineKeyboardMarkup(admin_keyboard), 
                parse_mode='Markdown'
            )
            await query.edit_message_text(
                "✅ **申请已发送**\n\n请耐心等待管理员审核。\n审核通过后，机器人会通知您。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]])
            )
        except Exception as e:
            logger.error(f"发送申请失败: {e}")
            await query.edit_message_text("❌ 发送申请失败，请联系管理员。")
        return

    # === 2. 管理员点击通过 ===
    if data.startswith("global_agree_"):
        # 鉴权：只有管理员能点
        if str(user.id) != str(ADMIN_ID):
            await query.answer("🚫 你不是管理员", show_alert=True)
            return

        target_uid = data.split("_")[-1]
        
        # 写入数据库
        user_manager.authorize_user(target_uid, username=f"User_{target_uid}")
        
        # 更新管理员界面
        await query.edit_message_text(f"✅ **已授权** 用户 `{target_uid}`\n处理人: {user.first_name}", parse_mode='Markdown')
        
        # 通知用户
        try:
            await context.bot.send_message(chat_id=target_uid, text="🎉 **恭喜！**\n您的权限申请已通过。\n\n请输入 /start 刷新菜单使用功能。")
        except:
            pass # 用户可能删除了对话
        return

    # === 3. 管理员点击拒绝 ===
    if data.startswith("global_deny_"):
        if str(user.id) != str(ADMIN_ID):
            await query.answer("🚫 你不是管理员", show_alert=True)
            return

        target_uid = data.split("_")[-1]
        
        await query.edit_message_text(f"❌ **已拒绝** 用户 `{target_uid}`\n处理人: {user.first_name}", parse_mode='Markdown')
        
        try:
            await context.bot.send_message(chat_id=target_uid, text="⚠️ 您的权限申请已被管理员拒绝。")
        except:
            pass
        return
        
    if data == "admin_global":
        if str(user.id) != str(ADMIN_ID): return
        
        stats = user_manager.get_all_stats()
        count_auth = sum(1 for u in stats.values() if u.get('authorized'))
        
        text = (
            f"👮 **全局管理面板**\n\n"
            f"总用户数: {len(stats)}\n"
            f"授权用户: {count_auth}\n\n"
            f"如需管理具体用户，请直接回复机器人用户的 ID 进行添加/删除 (待实现高级命令)。"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]])
        )

async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "打开主菜单"),
    ])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. 注册主程序 Handler (包括全局申请逻辑)
    # 注意 pattern 匹配 global_ 开头的回调
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_global$"))
    
    # 2. 🔌 加载插件
    yanci.register_handlers(application)
    
    print("✅ 机器人已启动 (全局授权模式)...")
    application.run_polling()

if __name__ == '__main__':
    main()
