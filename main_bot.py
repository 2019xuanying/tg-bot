import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# 导入工具
from utils.database import user_manager, ADMIN_ID

# 导入插件
from plugins import yanci
from plugins import flexiroam
from plugins import jetfi
from plugins import travelgoogoo
from plugins import rbesim
from plugins import kitesim
from plugins import ivideo

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

# 定义状态常量
ADMIN_STATE_NONE = 0
ADMIN_WAIT_PROXY_LIST = 101

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['admin_state'] = ADMIN_STATE_NONE

    is_auth = user_manager.is_authorized(user.id)
    is_admin = (str(user.id) == str(ADMIN_ID))

    # 获取插件状态
    yanci_status = user_manager.get_plugin_status("yanci")
    flexi_status = user_manager.get_plugin_status("flexiroam")
    jetfi_status = user_manager.get_plugin_status("jetfi") 
    rbesim_status = user_manager.get_plugin_status("rbesim")
    kitesim_status = user_manager.get_plugin_status("kitesim")
    ivideo_status = user_manager.get_plugin_status("ivideo")

    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"状态: {'✅ 已获授权' if is_auth else '🚫 未获授权'}\n\n"
    )

    keyboard = []

    if is_auth:
        text += "请选择要运行的功能模块："
        
        yanci_btn = "🌏 Yanci 助手" if yanci_status else "🌏 Yanci (维护中)"
        flexi_btn = "🌐 Flexiroam 助手" if flexi_status else "🌐 Flexiroam (维护中)"
        jetfi_btn = "🚙 JetFi 助手" if jetfi_status else "🚙 JetFi (维护中)" 
        rbesim_btn = "📡 RB eSIM 提取" if rbesim_status else "📡 RB eSIM (维护中)" 
        kitesim_btn = "🪁 Kite eSIM 爆破" if kitesim_status else "🪁 Kite eSIM (维护中)"
        ivideo_btn = "📹 iVideo 下单" if ivideo_status else "📹 iVideo (维护中)"

        keyboard.append([InlineKeyboardButton(yanci_btn, callback_data="plugin_yanci_entry")])
        keyboard.append([InlineKeyboardButton(flexi_btn, callback_data="plugin_flexi_entry")])
        keyboard.append([InlineKeyboardButton(jetfi_btn, callback_data="plugin_jetfi_entry")])
        keyboard.append([InlineKeyboardButton(rbesim_btn, callback_data="plugin_rbesim_entry")])
        keyboard.append([InlineKeyboardButton(kitesim_btn, callback_data="plugin_kitesim_entry")]) 
        keyboard.append([InlineKeyboardButton(ivideo_btn, callback_data="plugin_ivideo_entry")])
        keyboard.append([InlineKeyboardButton("🏝 TravelGooGoo 扫码", callback_data="plugin_travel_entry")])
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
    
    if data == "main_menu_root":
        await start(update, context)
        return

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
        except Exception:
            await query.edit_message_text("❌ 发送失败。")
        return

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

    # ================= 管理员后台 =================
    
    if data == "admin_menu_main":
        if str(user.id) != str(ADMIN_ID): return
        context.user_data['admin_state'] = ADMIN_STATE_NONE
        
        text = "👮 **管理员控制台**"
        keyboard = [
            [InlineKeyboardButton("🔧 项目开关控制", callback_data="admin_ctrl_plugins")],
            [InlineKeyboardButton("🌍 代理池管理", callback_data="admin_ctrl_proxies")],
            [InlineKeyboardButton("👥 用户授权管理", callback_data="admin_ctrl_users")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_ctrl_plugins":
        if str(user.id) != str(ADMIN_ID): return
        y_status = user_manager.get_plugin_status("yanci")
        f_status = user_manager.get_plugin_status("flexiroam")
        j_status = user_manager.get_plugin_status("jetfi") 
        r_status = user_manager.get_plugin_status("rbesim")
        k_status = user_manager.get_plugin_status("kitesim")
        i_status = user_manager.get_plugin_status("ivideo")
        
        text = "🔧 **项目运行状态控制**\n点击按钮切换状态。"
        keyboard = [
            [InlineKeyboardButton(f"Yanci: {'🟢' if y_status else '🔴'}", callback_data="admin_toggle_yanci")],
            [InlineKeyboardButton(f"Flexi: {'🟢' if f_status else '🔴'}", callback_data="admin_toggle_flexiroam")],
            [InlineKeyboardButton(f"JetFi: {'🟢' if j_status else '🔴'}", callback_data="admin_toggle_jetfi")],
            [InlineKeyboardButton(f"RB eSIM: {'🟢' if r_status else '🔴'}", callback_data="admin_toggle_rbesim")],
            [InlineKeyboardButton(f"Kite: {'🟢' if k_status else '🔴'}", callback_data="admin_toggle_kitesim")],
            [InlineKeyboardButton(f"iVideo: {'🟢' if i_status else '🔴'}", callback_data="admin_toggle_ivideo")],
            [InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data.startswith("admin_toggle_"):
        plugin_key = data.replace("admin_toggle_", "")
        user_manager.toggle_plugin(plugin_key)
        query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    if data == "admin_ctrl_proxies":
        if str(user.id) != str(ADMIN_ID): return
        proxy_list = user_manager.get_proxies()
        use_proxy = user_manager.get_config("use_proxy", True)
        text = f"🌍 **代理池管理**\n\n状态: {'🟢 已开启' if use_proxy else '🔴 已关闭'}\n数量: {len(proxy_list)} 个"
        keyboard = [
            [InlineKeyboardButton(f"开关: {'关闭' if use_proxy else '开启'}", callback_data="admin_proxy_toggle")],
            [InlineKeyboardButton("📥 批量导入", callback_data="admin_proxy_import")],
            [InlineKeyboardButton("🗑 清空代理", callback_data="admin_proxy_clear")],
            [InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_proxy_toggle":
        current = user_manager.get_config("use_proxy", True)
        user_manager.set_config("use_proxy", not current)
        query.data = "admin_ctrl_proxies"
        await main_callback(update, context)
        return

    if data == "admin_proxy_clear":
        user_manager.clear_proxies()
        await query.answer("代理池已清空", show_alert=True)
        query.data = "admin_ctrl_proxies"
        await main_callback(update, context)
        return

    if data == "admin_proxy_import":
        context.user_data['admin_state'] = ADMIN_WAIT_PROXY_LIST
        await query.edit_message_text("📥 **请直接回复代理列表**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="admin_ctrl_proxies")]]), parse_mode='Markdown')
        return

    if data == "admin_ctrl_users":
        if str(user.id) != str(ADMIN_ID): return
        users = user_manager.get_all_users()
        text = "👥 **用户列表**"
        keyboard = []
        for uid, info in users.items():
            if str(uid) == str(ADMIN_ID): continue 
            if not info.get('authorized'): continue
            name = info.get('name', 'Unknown')
            count = info.get('count', 0)
            keyboard.append([InlineKeyboardButton(f"❌ {name[:6]}.. ({count}次)", callback_data=f"admin_revoke_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data.startswith("admin_revoke_"):
        target_uid = data.split("_")[-1]
        user_manager.revoke_user(target_uid)
        await query.answer(f"已移除权限", show_alert=True)
        query.data = "admin_ctrl_users"
        await main_callback(update, context)
        return

async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if str(user.id) != str(ADMIN_ID): return
    state = context.user_data.get('admin_state', ADMIN_STATE_NONE)
    
    if state == ADMIN_WAIT_PROXY_LIST:
        text = update.message.text
        lines = text.strip().split('\n')
        new_proxies = [l.strip() for l in lines if ":" in l]
        if new_proxies:
            user_manager.add_proxies(new_proxies)
            msg = f"✅ 成功导入 {len(new_proxies)} 个代理！"
        else:
            msg = "⚠️ 未识别到有效格式。"
        context.user_data['admin_state'] = ADMIN_STATE_NONE
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_ctrl_proxies")]]))
        return

async def post_init(application):
    await application.bot.set_my_commands([BotCommand("start", "打开主菜单")])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_.*"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_text_handler), group=0)
    
    # 注册插件
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)
    jetfi.register_handlers(application)
    travelgoogoo.register_handlers(application)
    rbesim.register_handlers(application)
    kitesim.register_handlers(application)
    ivideo.register_handlers(application)

    print("✅ 机器人已启动")
    application.run_polling()

if __name__ == '__main__':
    main()
