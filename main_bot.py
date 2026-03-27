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
from plugins import jetfi  # <--- 新增导入
from plugins import travelgoogoo  # <--- 新增
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

# 定义状态
ADMIN_STATE_NONE = 0
ADMIN_WAIT_PROXY_LIST = 101

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['admin_state'] = ADMIN_STATE_NONE # 重置管理状态

    is_auth = user_manager.is_authorized(user.id)
    is_admin = (str(user.id) == str(ADMIN_ID))

    # 动态检查插件状态 (注意：这里前面只能有 4 个空格)
    yanci_status = user_manager.get_plugin_status("yanci")
    flexi_status = user_manager.get_plugin_status("flexiroam")
    jetfi_status = user_manager.get_plugin_status("jetfi") 
    rbesim_status = user_manager.get_plugin_status("rbesim") # <--- 新增状态检查
    kitesim_status = user_manager.get_plugin_status("kitesim")
    kitesim_status = user_manager.get_plugin_status("ivideo")

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
        kitesim_btn_text = "🪁 Kite eSIM 爆破" if kitesim_status else "🪁 Kite eSIM (维护中)" # <--- 新增按钮文本
        kitesim_btn_text = " iVideo eSIM 提取" if kitesim_status else " ivideo eSIM (维护中)"

        keyboard.append([InlineKeyboardButton(yanci_btn_text, callback_data="plugin_yanci_entry")])
        keyboard.append([InlineKeyboardButton(flexi_btn_text, callback_data="plugin_flexi_entry")])
        keyboard.append([InlineKeyboardButton(jetfi_btn_text, callback_data="plugin_jetfi_entry")])
        keyboard.append([InlineKeyboardButton(rbesim_btn_text, callback_data="plugin_rbesim_entry")]) # <--- 新增按钮
        keyboard.append([InlineKeyboardButton(kitesim_btn_text, callback_data="plugin_kitesim_entry")]) 
        keyboard.append([InlineKeyboardButton("🏝 TravelGooGoo 扫码", callback_data="plugin_travel_entry")])
        keyboard.append([InlineKeyboardButton("📹 iVideo 自动下单", callback_data="plugin_ivideo_entry")])
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

    # === 权限申请逻辑 (保持不变) ===
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

    # === 管理员审批逻辑 (保持不变) ===
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
        context.user_data['admin_state'] = ADMIN_STATE_NONE # 清除状态
        
        text = "👮 **管理员控制台**"
        keyboard = [
            [InlineKeyboardButton("🔧 项目开关控制", callback_data="admin_ctrl_plugins")],
            [InlineKeyboardButton("🌍 代理池管理", callback_data="admin_ctrl_proxies")],
            [InlineKeyboardButton("👥 用户授权管理", callback_data="admin_ctrl_users")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 2. 项目开关控制
    if data == "admin_ctrl_plugins":
        if str(user.id) != str(ADMIN_ID): return
        y_status = user_manager.get_plugin_status("yanci")
        f_status = user_manager.get_plugin_status("flexiroam")
        j_status = user_manager.get_plugin_status("jetfi") 
        r_status = user_manager.get_plugin_status("rbesim")
        k_status = user_manager.get_plugin_status("kitesim") # <--- 新增状态
        i_status = user_manager.get_plugin_status("iVideo")
        
        text = "🔧 **项目运行状态控制**\n点击按钮切换 开启/关闭 状态。"
        keyboard = [
            [InlineKeyboardButton(f"Yanci: {'🟢 开启' if y_status else '🔴 关闭'}", callback_data="admin_toggle_yanci")],
            [InlineKeyboardButton(f"Flexiroam: {'🟢 开启' if f_status else '🔴 关闭'}", callback_data="admin_toggle_flexi")],
            [InlineKeyboardButton(f"JetFi: {'🟢 开启' if j_status else '🔴 关闭'}", callback_data="admin_toggle_jetfi")],
            [InlineKeyboardButton(f"RB eSIM: {'🟢 开启' if r_status else '🔴 关闭'}", callback_data="admin_toggle_rbesim")], # <--- 新增控制
            [InlineKeyboardButton(f"Kite eSIM: {'🟢 开启' if k_status else '🔴 关闭'}", callback_data="admin_toggle_kitesim")], # <--- 新增开关
            [InlineKeyboardButton(f"Kite eSIM: {'🟢 开启' if k_status else '🔴 关闭'}", callback_data="admin_toggle_iVideo")],
            [InlineKeyboardButton("🔙 返回上级", callback_data="admin_menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # === 插件开关逻辑 ===
    if data == "admin_toggle_yanci":
        user_manager.toggle_plugin("yanci")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    if data == "admin_toggle_flexi":
        user_manager.toggle_plugin("flexiroam")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    if data == "admin_toggle_jetfi": # <--- 新增切换逻辑
        user_manager.toggle_plugin("jetfi")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    if data == "admin_toggle_rbesim":
        user_manager.toggle_plugin("rbesim")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return
        
    if data == "admin_toggle_kitesim":
        user_manager.toggle_plugin("kitesim")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    if data == "admin_toggle_iVideo":
        user_manager.toggle_plugin("iVideo")
        update.callback_query.data = "admin_ctrl_plugins"
        await main_callback(update, context)
        return

    # 3. 代理池管理 (保持不变)
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
        text = (
            "📥 **请直接回复代理列表**\n\n"
            "每行一个，支持两种格式混用。\n"
            "例如：\n"
            "`1.1.1.1:8080:user:pass`\n"
            "`2.2.2.2:9090`"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="admin_ctrl_proxies")]]), parse_mode='Markdown')
        return

    # 4. 用户管理 (保持不变)
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
    """处理管理员的文本输入 (如导入代理)"""
    user = update.effective_user
    if str(user.id) != str(ADMIN_ID): return # 仅限管理员

    state = context.user_data.get('admin_state', ADMIN_STATE_NONE)
    
    if state == ADMIN_WAIT_PROXY_LIST:
        text = update.message.text
        lines = text.strip().split('\n')
        new_proxies = []
        for line in lines:
            line = line.strip()
            if not line: continue
            # 简单校验格式
            parts = line.split(':')
            if len(parts) in [2, 4]:
                new_proxies.append(line)
        
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
    
    # 1. 注册主程序
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(main_callback, pattern="^main_menu_root$|^global_.*|^admin_.*"))
    
    # 2. 注册管理员文本处理器 (优先级最高 group=0)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_text_handler), group=0)
    
    # 3. 加载插件
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)
    jetfi.register_handlers(application) # <--- 注册新插件
    travelgoogoo.register_handlers(application)
    rbesim.register_handlers(application)
    kitesim.register_handlers(application)
    iVideo.register_handlers(application)

    # === 启动状态打印 ===
    use_proxy = user_manager.get_config("use_proxy", True)
    proxies = user_manager.get_proxies()
    
    print("\n" + "="*30)
    logger.info(f"代理系统状态: {'🟢 开启' if use_proxy else '🔴 关闭'}")
    logger.info(f"当前代理数量: {len(proxies)}")
    print("="*30 + "\n")
    
    print("✅ 机器人已启动 (Yanci + Flexiroam + JetFi)...")
    application.run_polling()

if __name__ == '__main__':
    main()






