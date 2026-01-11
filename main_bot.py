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
from plugins import flexiroam

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

    # 动态检查插件状态
    yanci_status = user_manager.get_plugin_status("yanci")
    flexi_status = user_manager.get_plugin_status("flexiroam")

    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"状态: {'✅ 已获授权' if is_auth else '🚫 未获授权'}\n\n"
    )

    keyboard = []

    if is_auth:
        text += "请选择要运行的功能模块："
        
        # === 动态渲染按钮 ===
        yanci_btn_text = "🌏 Yanci 抢单助手" if yanci_status else "🌏 Yanci (维护中)"
        flexi_btn_text = "🌐 Flexiroam 助手" if flexi_status else "🌐 Flexiroam (维护中)"
        
        keyboard.append([InlineKeyboardButton(yanci_btn_text, callback_data="plugin_yanci_entry")])
        keyboard.append([InlineKeyboardButton(flexi_btn_text, callback_data="plugin_flexi_entry")])
    else:
        text += "您目前没有使用权限，请点击下方按钮申请。"
        keyboard.append([InlineKeyboardButton("📝 申请使用权限", callback_data="global_request_auth")])

    if is_admin:
         keyboard.append([InlineKeyboardButton("👮 管理员后台", callback_data="admin_menu_main")])

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
    
    # 返回主菜单
    if data == "main_menu_root":
        await start(update, context)
        return

    # === 权限申请逻辑 ===
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

    # === 管理员审批逻辑 ===
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

    # ================= 管理员后台逻辑 =================
    
    # 1. 管理员主菜单
    if data == "admin_menu_main":
        if str(user.id) != str(ADMIN_ID): return
        stats = user_manager.get_all_users()
        total_users = len(stats)
        active_users = sum(1 for u in stats.values() if u.get('authorized'))
        
        text = (
            f"👮 **管理员控制台**\n\n"
            f"👥 总用户: {total_users}\n"
            f"✅ 授权用户: {active_users}\n"
        )
        keyboard = [
            [InlineKeyboardButton("🔧 项目开关控制", callback_data="admin_ctrl_plugins")],
            [InlineKeyboardButton("👥 用户授权管理", callback_data="admin_ctrl_users")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 2. 项目开关控制
    if data == "admin_ctrl_plugins":
        if str(user.id) != str(ADMIN_ID): return
        
        # 获取当前状态
        y_status = user_manager.get_plugin_status("yanci")
        f_status = user_manager.get_plugin_status("flexiroam")
        
        text = "🔧 **项目运行状态控制**\n点击按钮切换 开启/关闭 状态。\n关闭后用户将无法进入该功能。"
        keyboard = [
            [InlineKeyboardButton(f"Yanci: {'🟢 开启' if y_status else '🔴 关闭'}", callback_data="admin_toggle_yanci")],
            [InlineKeyboardButton(f"Flexiroam: {'🟢 开启' if f_status else '🔴 关闭'}", callback_data="admin_toggle_flexi")],
            [InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_toggle_yanci":
        user_manager.toggle_plugin("yanci")
        # 刷新界面
        await main_callback(update, context) 
        # 为了让递归调用生效，我们需要把 data 改回 admin_ctrl_plugins
        update.callback_query.data = "admin_ctrl_plugins" 
        await main_callback(update, context)
        return

    if data == "admin_toggle_flexi":
        user_manager.toggle_plugin("flexiroam")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    # 3. 用户管理列表
    if data == "admin_ctrl_users":
        if str(user.id) != str(ADMIN_ID): return
        
        users = user_manager.get_all_users()
        text = "👥 **用户列表 (点击按钮移除授权)**\n"
        keyboard = []
        
        for uid, info in users.items():
            if str(uid) == str(ADMIN_ID): continue # 不显示自己
            if not info.get('authorized'): continue # 只显示已授权的
            
            name = info.get('name', 'Unknown')
            count = info.get('count', 0)
            btn_text = f"❌ 移除 {name[:6]}.. (次数:{count})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_revoke_{uid}")])
        
        if not keyboard:
            text += "\n暂无其他授权用户。"

        keyboard.append([InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 4. 执行移除操作
    if data.startswith("admin_revoke_"):
        target_uid = data.split("_")[-1]
        user_manager.revoke_user(target_uid)
        await query.answer(f"已移除用户 {target_uid} 的权限", show_alert=True)
        # 刷新列表
        update.callback_query.data = "admin_ctrl_users"
        await main_callback(update, context)
        return

async def post_init(application):
    await application.bot.set_my_commands([BotCommand("start", "打开主菜单")])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. 注册主程序
    application.add_handler(CommandHandler("start", start))
    # 更新回调正则，匹配新的 admin 指令
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_.*"))
    
    # 2. 加载插件
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)
    
    print("✅ 机器人已启动 (Yanci + Flexiroam)...")
    application.run_polling()

if __name__ == '__main__':
    main()
