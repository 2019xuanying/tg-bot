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
from plugins import ivideo  # <--- 新增 iVideo 插件导入

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

# 定义状态
ADMIN_STATE_NONE = 0
ADMIN_WAIT_PROXY_LIST = 101

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['admin_state'] = ADMIN_STATE_NONE # 重置管理状态

    is_auth = user_manager.is_authorized(user.id)
    is_admin = (str(user.id) == str(ADMIN_ID))

    # 动态检查插件状态
    yanci_status = user_manager.get_plugin_status("yanci")
    flexi_status = user_manager.get_plugin_status("flexiroam")
    jetfi_status = user_manager.get_plugin_status("jetfi") 
    rbesim_status = user_manager.get_plugin_status("rbesim")
    kitesim_status = user_manager.get_plugin_status("kitesim")
    ivideo_status = user_manager.get_plugin_status("ivideo") # <--- 新增状态检查

    text = (
        f"🤖 **聚合控制中心**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"状态: {'✅ 已获授权' if is_auth else '🚫 未获授权'}\n\n"
    )

    keyboard = []

    if is_auth:
        text += "请选择要运行的功能模块："
        
        yanci_btn_text = "🌏 Yanci 下单助手" if yanci_status else "🌏 Yanci (维护中)"
        flexi_btn_text = "🌐 Flexiroam 助手" if flexi_status else "🌐 Flexiroam (维护中)"
        jetfi_btn_text = "🚙 JetFi 助手" if jetfi_status else "🚙 JetFi (维护中)" 
        rbesim_btn_text = "📡 RB eSIM 提取" if rbesim_status else "📡 RB eSIM (维护中)" 
        kitesim_btn_text = "🪁 Kite eSIM 爆破" if kitesim_status else "🪁 Kite eSIM (维护中)"
        ivideo_btn_text = "📹 iVideo 0元下单" if ivideo_status else "📹 iVideo (维护中)" # <--- 新增按钮文本

        keyboard.append([InlineKeyboardButton(yanci_btn_text, callback_data="plugin_yanci_entry")])
        keyboard.append([InlineKeyboardButton(flexi_btn_text, callback_data="plugin_flexi_entry")])
        keyboard.append([InlineKeyboardButton(jetfi_btn_text, callback_data="plugin_jetfi_entry")])
        keyboard.append([InlineKeyboardButton(rbesim_btn_text, callback_data="plugin_rbesim_entry")])
        keyboard.append([InlineKeyboardButton(kitesim_btn_text, callback_data="plugin_kitesim_entry")]) 
        keyboard.append([InlineKeyboardButton(ivideo_btn_text, callback_data="plugin_ivideo_entry")]) # <--- 新增按钮
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

    # 权限申请逻辑
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
            await query.edit_message_text("❌ 发送失败。")
        return

    # 管理员审批逻辑
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
        i_status = user_manager.get_plugin_status("ivideo") # <--- 新增状态
        
        text = "🔧 **项目运行状态控制**\n点击按钮切换 开启/关闭 状态。"
        keyboard = [
            [InlineKeyboardButton(f"Yanci: {'🟢 开启' if y_status else '🔴 关闭'}", callback_data="admin_toggle_yanci")],
            [InlineKeyboardButton(f"Flexiroam: {'🟢 开启' if f_status else '🔴 关闭'}", callback_data="admin_toggle_flexi")],
            [InlineKeyboardButton(f"JetFi: {'🟢 开启' if j_status else '🔴 关闭'}", callback_data="admin_toggle_jetfi")],
            [InlineKeyboardButton(f"RB eSIM: {'🟢 开启' if r_status else '🔴 关闭'}", callback_data="admin_toggle_rbesim")],
            [InlineKeyboardButton(f"Kite eSIM: {'🟢 开启' if k_status else '🔴 关闭'}", callback_data="admin_toggle_kitesim")],
            [InlineKeyboardButton(f"iVideo: {'🟢 开启' if i_status else '🔴 关闭'}", callback_data="admin_toggle_ivideo")], # <--- 新增控制按钮
            [InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 插件开关切换逻辑
    plugin_toggles = ["yanci", "flexi", "jetfi", "rbesim", "kitesim", "ivideo"] # <--- 加入 ivideo
    for p in plugin_toggles:
        if data == f"admin_toggle_{p}":
            # 数据库键名为 ivideo
            db_key = "flexiroam" if p == "flexi" else p
            user_manager.toggle_plugin(db_key)
            update.callback_query.data = "admin_ctrl_plugins"
            await main_callback(update, context)
            return

    # 代理池管理
    if data == "admin_ctrl_proxies":
        if str(user.id) != str(ADMIN_ID): return
        proxy_list = user_manager.get_proxies()
        use_proxy = user_manager.get_config("use_proxy", True)
        text = (
            f"🌍 **代理池管理**\n\n"
            f"当前状态: {'🟢 已开启' if use_proxy else '🔴 已关闭'}\n"
            f"代理数量: {len(proxy_list)} 个\n\n"
            f"支持格式:\n1. `ip:port:user:pass` (SOCKS5)\n2. `ip:port` (HTTP)\n"
        )
        keyboard = [
            [InlineKeyboardButton(f"开关: {'点击关闭' if use_proxy else '点击开启'}", callback_data="admin_proxy_toggle")],
            [InlineKeyboardButton("📥 批量导入代理", callback_data="admin_proxy_import")],
            [InlineKeyboardButton("🗑 清空代理池", callback_data="admin_proxy_clear")],
            [InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data == "admin_proxy_toggle":
        current = user_manager.get_config("use_proxy", True)
        user_manager.set_config("use_proxy", not current)
        update.callback_query.data = "admin_ctrl_proxies"
        await main_callback(update, context)
        return

    if data == "admin_proxy_clear":
        user_manager.clear_proxies()
        await query.answer("代理池已清空", show_alert=True)
        update.callback_query.data = "admin_ctrl_proxies"
        await main_callback(update, context)
        return

    if data == "admin_proxy_import":
        context.user_data['admin_state'] = ADMIN_WAIT_PROXY_LIST
        text = "📥 **请直接回复代理列表**\n\n每行一个，支持两种格式混用。"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="admin_ctrl_proxies")]]), parse_mode='Markdown')
        return

    # 用户管理
    if data == "admin_ctrl_users":
        if str(user.id) != str(ADMIN_ID): return
        users = user_manager.get_all_users()
        text = "👥 **用户列表 (点击按钮移除授权)**\n"
        keyboard = []
        for uid, info in users.items():
            if str(uid) == str(ADMIN_ID): continue 
            if not info.get('authorized'): continue
            name = info.get('name', 'Unknown')
            count = info.get('count', 0)
            btn_text = f"❌ 移除 {name[:6]}.. (次数:{count})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_revoke_{uid}")])
        if not keyboard: text += "\n暂无其他授权用户。"
        keyboard.append([InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data.startswith("admin_revoke_"):
        target_uid = data.split("_")[-1]
        user_manager.revoke_user(target_uid)
        await query.answer(f"已移除用户 {target_uid} 的权限", show_alert=True)
        update.callback_query.data = "admin_ctrl_users"
        await main_callback(update, context)
        return

async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if str(user.id) != str(ADMIN_ID): return 

    state = context.user_data.get('admin_state', ADMIN_STATE_NONE)
    if state == ADMIN_WAIT_PROXY_LIST:
        text = update.message.text
        lines = text.strip().split('\n')
        new_proxies = [l.strip() for l in lines if l.strip() and len(l.split(':')) in [2, 4]]
        if new_proxies:
            user_manager.add_proxies(new_proxies)
            msg = f"✅ 成功导入 {len(new_proxies)} 个代理！"
        else:
            msg = "⚠️ 未识别到有效代理格式。"
        context.user_data['admin_state'] = ADMIN_STATE_NONE
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回代理管理", callback_data="admin_ctrl_proxies")]]))
        return

async def post_init(application):
    await application.bot.set_my_commands([BotCommand("start", "打开主菜单")])

# ================= 启动逻辑 =================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 注册核心处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_.*"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_text_handler), group=0)
    
    # 加载所有插件
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)
    jetfi.register_handlers(application)
    travelgoogoo.register_handlers(application)
    rbesim.register_handlers(application)
    kitesim.register_handlers(application)
    ivideo.register_handlers(application)  # <--- 新增 iVideo 处理器注册

    print("✅ 机器人已启动 (聚合控制中心已就绪)...")
    application.run_polling()

if __name__ == '__main__':
    main()
