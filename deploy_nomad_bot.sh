#!/bin/bash
# ========================================================
# Nomad Telegram Bot 一键部署脚本
# ========================================================

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}>>> 欢迎使用 Nomad Bot 一键部署脚本 <<<${NC}"

# 获取配置信息
read -p "请输入您的 Telegram Bot Token: " BOT_TOKEN
read -p "请输入超级管理员的 Telegram User ID: " ADMIN_ID
read -p "请输入强制加入的群组 ID (包含符号如 -100xxx，无限制填 0): " GROUP_ID
read -p "请输入官方群组链接 (如 https://t.me/xxx): " GROUP_LINK

echo -e "${YELLOW}[*] 正在更新系统依赖并安装 Python3 ...${NC}"
sudo apt update && sudo apt install python3 python3-pip python3-venv -y

APP_DIR="/opt/nomad_bot"
echo -e "${YELLOW}[*] 创建工作目录 ${APP_DIR} ...${NC}"
sudo mkdir -p ${APP_DIR}
sudo chown -R $USER:$USER ${APP_DIR}
cd ${APP_DIR}

echo -e "${YELLOW}[*] 设置 Python 虚拟环境 ...${NC}"
python3 -m venv venv
source venv/bin/activate

echo -e "${YELLOW}[*] 安装 Python 依赖包 ...${NC}"
pip install pyTelegramBotAPI pycryptodome requests "requests[socks]" urllib3

echo -e "${YELLOW}[*] 正在生成核心代码 ...${NC}"
cat << 'EOF' > bot.py

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import requests
import base64
import hmac
import hashlib
import uuid
import json
import urllib3
import os
import random
import string
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置文件 (将由部署脚本替换) =================
BOT_TOKEN = "REPLACE_BOT_TOKEN"
ADMIN_ID = REPLACE_ADMIN_ID
REQUIRED_GROUP_ID = REPLACE_GROUP_ID
GROUP_LINK = "REPLACE_GROUP_LINK"

bot = telebot.TeleBot(BOT_TOKEN)

# ================= 内存状态管理 =================
PROXY_FILE = "proxies.txt"
sys_state = {
    "is_active": True,
    "banned_users": set(),
    "proxies": [] 
}

# 启动时自动读取本地保存的代理配置
if os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, "r", encoding="utf-8") as f:
        sys_state["proxies"] = [line.strip() for line in f if line.strip()]

# ================= 底层 Crypto 引擎与 NomadBot (保持原有缩进) =================
# ... (保留您原来的 get_crypto_param 和 NomadBot 类定义，这部分不需要改动) ...

# ================= 中间件与权限校验 =================
def is_user_banned(user_id):
    return int(user_id) in sys_state["banned_users"]

def check_group_membership(user_id):
    # 修复 ID 对比漏洞：强制统一转换为字符串对比
    if str(user_id) == str(ADMIN_ID) or str(REQUIRED_GROUP_ID) == "0":
        return True
    try:
        chat_member = bot.get_chat_member(REQUIRED_GROUP_ID, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"验证进群失败: {e}")
        return False

# ================= 核心交互逻辑 =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        return bot.send_message(user_id, "❌ 您已被管理员封禁。")
    if not sys_state["is_active"] and str(user_id) != str(ADMIN_ID):
        return bot.send_message(user_id, "🔧 系统维护中，暂时关闭服务。")
    if not check_group_membership(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 点击加入官方群组", url=GROUP_LINK))
        markup.add(InlineKeyboardButton("🔄 我已加入，刷新状态", callback_data="check_join"))
        bot.send_message(user_id, "⚠️ **使用限制**\n您必须先加入我们的官方群组才能使用此机器人！", parse_mode="Markdown", reply_markup=markup)
        return
        
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🚀 提取 eSIM", callback_data="start_esim"))
    
    # 修复：直接向管理员展示配置面板气泡接口
    if str(user_id) == str(ADMIN_ID):
        markup.row(InlineKeyboardButton("⚙️ 管理员控制面板 (代理/封禁)", callback_data="open_admin_panel"))
        
    bot.send_message(user_id, "👋 欢迎使用 Nomad eSIM 助手！", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if str(message.from_user.id) != str(ADMIN_ID): 
        return
    markup = InlineKeyboardMarkup()
    status_text = "🟢 运行中 (点击维护)" if sys_state["is_active"] else "🔴 维护中 (点击开启)"
    markup.row(InlineKeyboardButton(status_text, callback_data="admin_toggle_status"))
    markup.row(InlineKeyboardButton("🚫 封禁用户", callback_data="admin_ban"), 
               InlineKeyboardButton("🔓 解封用户", callback_data="admin_unban"))
    markup.row(InlineKeyboardButton("🌐 添加代理配置", callback_data="admin_add_proxy"), 
               InlineKeyboardButton("🗑️ 清空代理", callback_data="admin_clear_proxy"))
    
    msg_text = f"👨‍💻 **超级管理员面板**\n\n当前有效代理节点数量: `{len(sys_state['proxies'])}`\n建议添加格式: `socks5://user:pass@ip:port`"
    bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    
    if call.data == "check_join":
        if check_group_membership(user_id):
            bot.answer_callback_query(call.id, "✅ 验证通过！")
            send_welcome(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ 您还未加入群组！", show_alert=True)
            
    elif call.data == "start_esim":
        msg = bot.send_message(user_id, "📝 请回复您的测试邮箱地址：")
        bot.register_next_step_handler(msg, process_email_step)
        
    # 管理员相关回调校验，统一转 String 判断
    elif call.data == "open_admin_panel" and str(user_id) == str(ADMIN_ID):
        bot.answer_callback_query(call.id)
        admin_panel(call.message)
        
    elif call.data == "admin_toggle_status" and str(user_id) == str(ADMIN_ID):
        sys_state["is_active"] = not sys_state["is_active"]
        bot.answer_callback_query(call.id, "状态已切换")
        admin_panel(call.message)
        
    elif call.data == "admin_ban" and str(user_id) == str(ADMIN_ID):
        msg = bot.send_message(user_id, "请输入要封禁的用户ID:")
        bot.register_next_step_handler(msg, lambda m: sys_state["banned_users"].add(int(m.text.strip())) or bot.send_message(user_id, f"✅ 已封禁 {m.text}"))
        
    elif call.data == "admin_unban" and str(user_id) == str(ADMIN_ID):
        msg = bot.send_message(user_id, "请输入要解封的用户ID:")
        bot.register_next_step_handler(msg, lambda m: sys_state["banned_users"].discard(int(m.text.strip())) or bot.send_message(user_id, f"✅ 已解封 {m.text}"))
        
    elif call.data == "admin_add_proxy" and str(user_id) == str(ADMIN_ID):
        msg = bot.send_message(user_id, "请输入 SOCKS5 代理 (例如: socks5://user:pass@ip:port):")
        bot.register_next_step_handler(msg, add_proxy_step)
        
    elif call.data == "admin_clear_proxy" and str(user_id) == str(ADMIN_ID):
        sys_state["proxies"] = []
        if os.path.exists(PROXY_FILE):
            os.remove(PROXY_FILE)
        bot.answer_callback_query(call.id, "✅ 代理池已清空", show_alert=True)

def add_proxy_step(message):
    new_proxy = message.text.strip()
    if new_proxy not in sys_state["proxies"]:
        sys_state["proxies"].append(new_proxy)
        # 修复：写入到文件，实现重启不丢失
        with open(PROXY_FILE, "a", encoding="utf-8") as f:
            f.write(new_proxy + "\n")
    bot.send_message(message.chat.id, f"✅ 配置成功！当前代理池总计容量: {len(sys_state['proxies'])}")

def process_email_step(message):
    email = message.text.strip()
    if not sys_state["proxies"]:
        bot.send_message(message.chat.id, "❌ 错误：管理员尚未配置 SOCKS5 代理节点。为防服务器 IP 被风控，操作中止。请管理员点击主菜单【⚙️ 管理员控制面板】添加。")
        return
    current_proxy = random.choice(sys_state["proxies"])
    bot.send_message(message.chat.id, f"🛡️ 正在通过加密隧道节点建立连接...")
    
    nomad_bot = NomadBot(proxy=current_proxy)
    bot.send_message(message.chat.id, "⏳ 正在生成环境特征并发起请求...")
    
    user = nomad_bot.generate_identity(email=email)
    result = nomad_bot.step1_request_otp(user)
    
    if result == "otp_sent":
        msg = bot.send_message(message.chat.id, "✅ 验证码已发送，请直接回复您收到的验证码：")
        bot.register_next_step_handler(msg, process_otp_step, nomad_bot, user)
    else:
        bot.send_message(message.chat.id, "❌ 发送失败，目标邮箱或网络节点受限。")

def process_otp_step(message, nomad_bot, user):
    code = message.text.strip()
    bot.send_message(message.chat.id, "⏳ 正在校验并在后台静默申请首个可用 0 元套餐...")
    
    if nomad_bot.step2_check_otp(user['email'], code) and nomad_bot.step3_sign_up(user, code):
        plans = nomad_bot.step3_5_get_trial_plans()
        if not plans:
            return bot.send_message(message.chat.id, "❌ 该账户未能获取到可用的试用套餐。")
        
        plan = plans[0]
        bot.send_message(message.chat.id, f"✅ 登录成功！\n🌍 正在为您配置网络文件: {plan['name']}")
        
        master_id = nomad_bot.step4_create_order(plan['offer_id'], plan['code'])
        if master_id:
            bot.send_message(message.chat.id, "🔄 后台派发中，请等待约 5 秒钟...")
            time.sleep(5)
            esim_info = nomad_bot.step5_get_esim_details(master_id)
            if esim_info:
                msg = f"🎉 **提取大成功！**\n\n🌍 目标套餐: `{esim_info['plan_name']}`\n📍 硬件串号 (ICCID): `{esim_info['iccid']}`\n🔗 LPA 激活码: `{esim_info['qr_data']}`\n🌐 接入服务器: `{esim_info['smdp_url']}`"
                bot.send_message(message.chat.id, msg, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ 创建已通过，但解析安装数据失败。")
        else:
            bot.send_message(message.chat.id, "❌ 创建订单环节被阻拦，请检查节点质量。")
    else:
        bot.send_message(message.chat.id, "❌ 校验未能通过或注册流程中断。")

if __name__ == '__main__':
    print("Bot is starting...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

EOF

# 替换配置变量
sed -i "s/REPLACE_BOT_TOKEN/$BOT_TOKEN/g" bot.py
sed -i "s/REPLACE_ADMIN_ID/$ADMIN_ID/g" bot.py
sed -i "s/REPLACE_GROUP_ID/$GROUP_ID/g" bot.py
sed -i "s|REPLACE_GROUP_LINK|$GROUP_LINK|g" bot.py

echo -e "${YELLOW}[*] 配置 Systemd 守护进程 ...${NC}"
sudo bash -c "cat << 'EOF' > /etc/systemd/system/nomadbot.service
[Unit]
Description=Nomad Telegram Bot Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

echo -e "${YELLOW}[*] 启动并设置开机自启 ...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable nomadbot
sudo systemctl start nomadbot

echo -e "${GREEN}========================================================${NC}"
echo -e "${GREEN}部署完成！${NC}"
echo -e "你可以使用以下命令查看日志："
echo -e "  sudo journalctl -u nomadbot -f -n 50"
echo -e "${GREEN}========================================================${NC}"
