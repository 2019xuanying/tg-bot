#!/bin/bash
# ========================================================
# Nomad Telegram Bot 一键部署脚本 (集成 ipdeep 动态代理)
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
import re
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置文件 (将由部署脚本替换) =================
BOT_TOKEN = "REPLACE_BOT_TOKEN"
ADMIN_ID = REPLACE_ADMIN_ID
REQUIRED_GROUP_ID = "REPLACE_GROUP_ID"
GROUP_LINK = "REPLACE_GROUP_LINK"

bot = telebot.TeleBot(BOT_TOKEN)

# ================= 内存状态管理 =================
sys_state = {
    "is_active": True,
    "banned_users": set()
}

# ================= 动态代理 API 拉取逻辑 =================
def fetch_dynamic_proxy():
    api_url = "https://api.ipdeep.com/api/Pro/DynamicIp/GetIpByGenerateLink?id=1107NmExMzI2NjcxMDIwOTA0MDIyMDk0"
    try:
        resp = requests.get(api_url, timeout=10)
        match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]+\b', resp.text)
        if match:
            return f"socks5://{match.group()}"
        else:
            print(f"[-] 代理 API 返回异常或未匹配到 IP: {resp.text}")
            return None
    except Exception as e:
        print(f"[-] 请求代理 API 失败: {e}")
        return None

# ================= 底层 Crypto 引擎与 NomadBot =================
def get_crypto_param(p1, p2, p3, p4):
    combined = p1 + p2 + p3 + p4
    combined += "=" * ((4 - len(combined) % 4) % 4)
    first_decode_bytes = base64.b64decode(combined)
    padding_len = (4 - len(first_decode_bytes) % 4) % 4
    first_decode_bytes += b"=" * padding_len
    return base64.b64decode(first_decode_bytes)

FINAL_AES_KEY = get_crypto_param("TURVeVl6", "TTRNell5", "TXpGak5", "ETXpNZw")
FINAL_AES_IV  = get_crypto_param("WVRWa1lq", "RXpORGM1", "T1dNeFlt", "RTFZdw")

FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
DEVICE_PROFILES = [
    "Samsung,SM-S918B,Android 14",
    "Google,Pixel 7 Pro,Android 13",
    "Xiaomi,2210132G,Android 13",
    "OnePlus,LE2120,Android 12"
]

class NomadBot:
    def __init__(self, proxy=None):
        self.base_url = "https://api.getnomad.app"
        self.session = requests.Session()
        
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
            print(f"[*] 已挂载 SOCKS5 代理: {proxy}")
            
        self.device_id = str(uuid.uuid4())
        self.device_info = random.choice(DEVICE_PROFILES)
        
        self.session.headers.update({
            "Host": "api.getnomad.app",
            "Accept-Language": "zh-Hans",
            "x-app-ver": "10.8.1",
            "x-device-info": self.device_info, 
            "x-request-source": "android",
            "x-channel-id": "nomad-android",
            "User-Agent": "Ktor client",
            "Content-Type": "application/json",
            "Accept": "application/json,application/json",
            "Connection": "Keep-Alive"
        })

    def _get_security_headers(self):
        payload = {
            "timestamp": int(time.time()),
            "token": str(uuid.uuid4()),
            "x-device-token": self.device_id
        }
        json_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        page_token = hmac.new(FINAL_AES_KEY, json_bytes, hashlib.sha256).hexdigest()
        cipher = AES.new(FINAL_AES_KEY, AES.MODE_CBC, FINAL_AES_IV)
        padded_data = pad(json_bytes, AES.block_size, style='pkcs7')
        app_tag = base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')
        return {
            "x-page-token": page_token,
            "x-app-tag": app_tag,
            "x-device-token": self.device_id
        }

    def generate_identity(self, email):
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        password = "Nomad" + ''.join(random.choices(string.digits, k=4)) + "A1!" 
        return {"email": email, "password": password, "first_name": first_name, "last_name": last_name}

    def step1_request_otp(self, user):
        url = f"{self.base_url}/account/api/v3/user/get_verification_code"
        payload = {"email": user['email'], "validation_case": "sign_up"}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code == 200:
            return "otp_sent"
        try:
            err = resp.json()
            if err.get("code") == 2002:
                return self._sign_in(user['email'], user['password'])
        except: pass
        return False

    def _sign_in(self, email, password):
        url = f"{self.base_url}/account/api/v3/user/sign_in"
        payload = {"email": email, "password": password}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code == 200:
            token = resp.json().get("data", {}).get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
                return "signed_in"
        return False

    def step2_check_otp(self, email, code):
        url = f"{self.base_url}/account/api/v3/user/check_verification_code"
        payload = {"email": email, "code": code}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        return resp.status_code == 200

    def step3_sign_up(self, user, code):
        url = f"{self.base_url}/account/api/v3/user/sign_up"
        payload = {
            "email": user['email'], "password": user['password'],
            "verification_code": code, "first_name": user['first_name'],
            "last_name": user['last_name'], "subscribe_to_feed": True
        }
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code == 200:
            token = resp.json().get("data", {}).get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
                return True
        return False

    def step3_5_get_trial_plans(self):
        url = f"{self.base_url}/product/api/v3/trial/get_trial_plan_info"
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json={}, headers=headers, verify=False)
        if resp.status_code != 200: return None
        plans = resp.json().get("data", {}).get("trial_plans")
        if not plans: return None
        offers = []
        for p in plans:
            code = p.get("country_code") or p.get("region_code", "??")
            plan = p.get("plan", {})
            offers.append({
                "code": code,
                "offer_id": plan.get("id", ""),
                "name": plan.get("product", {}).get("name", code)
            })
        return offers

    def step4_create_order(self, offer_id, coverage):
        url = f"{self.base_url}/order/api/v3/order/create_master_order"
        payload = {
            "offered_products": [{"offered_id": offer_id, "quantity": 1, "coverage": coverage}],
            "currency": "USD", "discount": {},
            "device": {"type": "Android", "id": self.device_id}
        }
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code == 202:
            return resp.json().get("data", {}).get("master_order_id")
        return None

    def step5_get_esim_details(self, master_id):
        url = f"{self.base_url}/order/api/v3/order/get_master_orders"
        payload = {"master_order_ids": [master_id], "product_categories": ["esim"]}
        headers = self.session.headers.copy()
        headers.update(self._get_security_headers())
        resp = self.session.post(url, json=payload, headers=headers, verify=False)
        if resp.status_code == 200:
            try:
                orders = resp.json()['data']['master_orders'][0]['orders'][0]
                esim = orders['esim_info']
                return {
                    'plan_name': orders['plan_info']['name'],
                    'iccid': esim['iccid'],
                    'qr_data': esim['qr_data'],
                    'smdp_url': esim['smdp_url']
                }
            except: pass
        return None

# ================= 中间件与权限校验 =================
def is_user_banned(user_id):
    return int(user_id) in sys_state["banned_users"]

def check_group_membership(user_id):
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
    if str(user_id) == str(ADMIN_ID):
        markup.row(InlineKeyboardButton("⚙️ 管理员控制面板", callback_data="open_admin_panel"))
        
    bot.send_message(user_id, "👋 欢迎使用 Nomad eSIM 助手！", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if str(message.from_user.id) != str(ADMIN_ID): return
    markup = InlineKeyboardMarkup()
    status_text = "🟢 运行中 (点击维护)" if sys_state["is_active"] else "🔴 维护中 (点击开启)"
    markup.row(InlineKeyboardButton(status_text, callback_data="admin_toggle_status"))
    markup.row(InlineKeyboardButton("🚫 封禁用户", callback_data="admin_ban"), InlineKeyboardButton("🔓 解封用户", callback_data="admin_unban"))
    markup.row(InlineKeyboardButton("📡 测试 ipdeep 代理接口", callback_data="admin_test_api"))
    
    msg_text = "👨‍💻 **超级管理员面板**\n\n系统当前已接管 ipdeep 动态代理 API，每次派发会自动拉取新 IP。"
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
        
    elif call.data == "admin_test_api" and str(user_id) == str(ADMIN_ID):
        bot.answer_callback_query(call.id, "正在请求 API...")
        proxy = fetch_dynamic_proxy()
        if proxy:
            bot.send_message(user_id, f"✅ 接口正常！\n返回节点: `{proxy}`", parse_mode="Markdown")
        else:
            bot.send_message(user_id, "❌ 接口异常，未提取到有效代理 IP。")

def process_email_step(message):
    email = message.text.strip()
    
    bot.send_message(message.chat.id, "🛡️ 正在通过 ipdeep 接口拉取动态代理节点...")
    current_proxy = fetch_dynamic_proxy()
    
    if not current_proxy:
        bot.send_message(message.chat.id, "❌ 错误：动态代理 API 拉取失败。可能是余额不足或 IP 白名单限制，请联系管理员。")
        return
        
    bot.send_message(message.chat.id, f"✅ 成功获取动态节点: `{current_proxy}`\n⏳ 正在生成环境特征并发起请求...", parse_mode="Markdown")
    
    nomad_bot = NomadBot(proxy=current_proxy)
    
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
            return bot.send_message(message.chat.id, "❌ 未获取到可用试用套餐。")
        
        plan = plans[0]
        bot.send_message(message.chat.id, f"✅ 注册成功！\n🌍 正在为您申请: {plan['name']}")
        
        master_id = nomad_bot.step4_create_order(plan['offer_id'], plan['code'])
        if master_id:
            bot.send_message(message.chat.id, "🔄 订单处理中，等待5秒提取 eSIM...")
            time.sleep(5)
            esim_info = nomad_bot.step5_get_esim_details(master_id)
            if esim_info:
                msg = f"🎉 **eSIM 提取成功！**\n\n🌍 套餐: `{esim_info['plan_name']}`\n📍 ICCID: `{esim_info['iccid']}`\n🔗 LPA: `{esim_info['qr_data']}`\n🌐 SM-DP+: `{esim_info['smdp_url']}`"
                bot.send_message(message.chat.id, msg, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ 获取安装信息失败。")
        else:
            bot.send_message(message.chat.id, "❌ 订单创建失败。")
    else:
        bot.send_message(message.chat.id, "❌ 验证码校验失败或注册异常。")

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
