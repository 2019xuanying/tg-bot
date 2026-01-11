#!/bin/bash

# ==========================================
#  自动部署脚本 (支持一键安装)
# ==========================================

# 定义颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
PLAIN='\033[0m'

# 检查 Root 权限
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}错误: 请使用 root 用户运行此脚本！${PLAIN}" 
   exit 1
fi

echo -e "${GREEN}======================================${PLAIN}"
echo -e "${GREEN}      开始部署 Yanci Bot      ${PLAIN}"
echo -e "${GREEN}======================================${PLAIN}"

# 0. 停止旧服务
echo -e "${YELLOW}[0/6] 检查并清理旧进程...${PLAIN}"
systemctl stop yanci_bot.service >/dev/null 2>&1
systemctl disable yanci_bot.service >/dev/null 2>&1

# 1. 获取配置信息
echo -e "${YELLOW}[1/6] 配置机器人信息...${PLAIN}"
read -p "请输入您的 Telegram Bot Token: " INPUT_TOKEN
while [[ -z "$INPUT_TOKEN" ]]; do
    echo -e "${RED}Token 不能为空！${PLAIN}"
    read -p "请输入您的 Telegram Bot Token: " INPUT_TOKEN
done

read -p "请输入管理员 UID (数字ID): " INPUT_ADMIN_ID
while [[ -z "$INPUT_ADMIN_ID" ]]; do
    echo -e "${RED}ID 不能为空！${PLAIN}"
    read -p "请输入管理员 UID: " INPUT_ADMIN_ID
done

# 2. 准备工作目录与代码
WORK_DIR="/root/tg_bot"
REPO_URL="https://github.com/2019xuanying/tg-bot.git"

echo -e "${YELLOW}[2/6] 同步程序文件...${PLAIN}"
mkdir -p "$WORK_DIR"

# 逻辑判断：是本地文件部署，还是远程拉取部署？
if [ -f "main_bot.py" ]; then
    # 情况A：用户手动上传了文件到当前目录
    echo "📂 检测到本地文件，正在复制..."
    cp "main_bot.py" "$WORK_DIR/"
    [ -d "utils" ] && cp -r "utils" "$WORK_DIR/"
    [ -d "plugins" ] && cp -r "plugins" "$WORK_DIR/"
    [ -f "requirements.txt" ] && cp "requirements.txt" "$WORK_DIR/"
else
    # 情况B：用户使用 curl 一键安装，本地无文件 -> 从 Git 拉取
    echo "☁️ 本地无代码，正在从 GitHub 拉取最新源码..."
    
    # 确保安装 git
    if ! command -v git &> /dev/null; then
        echo "安装 Git..."
        apt-get update -y >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
    fi

    # 克隆到临时目录并移动
    rm -rf /tmp/tg_bot_temp
    git clone "$REPO_URL" /tmp/tg_bot_temp
    
    if [ -f "/tmp/tg_bot_temp/main_bot.py" ]; then
        cp -r /tmp/tg_bot_temp/* "$WORK_DIR/"
        echo -e "✅ 代码拉取成功！"
    else
        echo -e "${RED}❌ 代码拉取失败，请检查网络或仓库地址！${PLAIN}"
        exit 1
    fi
    rm -rf /tmp/tg_bot_temp
fi

cd "$WORK_DIR"

# 3. 生成配置文件 (.env)
echo -e "${YELLOW}[3/6] 生成配置文件 (.env)...${PLAIN}"
cat > .env <<EOF
TG_BOT_TOKEN=${INPUT_TOKEN}
TG_ADMIN_ID=${INPUT_ADMIN_ID}
EOF
echo -e "✅ .env 配置已生成"

# 4. 检查并修复依赖列表
echo -e "${YELLOW}[4/6] 检查依赖列表...${PLAIN}"
if [ -f "requirements.txt" ] && ! grep -q "DOCTYPE" "requirements.txt" && ! grep -q "404" "requirements.txt"; then
    echo -e "✅ 使用现有依赖列表。"
else
    echo -e "${YELLOW}⚠️ 重建默认依赖列表...${PLAIN}"
    cat > requirements.txt <<EOF
python-telegram-bot
python-dotenv
requests
schedule
EOF
fi

# 5. 安装 Python 环境与依赖
echo -e "${YELLOW}[5/6] 安装环境依赖...${PLAIN}"
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-pip python3-venv python3-full >/dev/null 2>&1

# 重置虚拟环境
if [ -d "venv" ]; then rm -rf venv; fi
python3 -m venv venv
source venv/bin/activate

# 安装库
pip install --upgrade pip >/dev/null 2>&1
echo "正在安装 Python 库..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 依赖安装失败！${PLAIN}"
    exit 1
fi

# 6. 配置并启动 Systemd 服务
echo -e "${YELLOW}[6/6] 启动后台服务...${PLAIN}"
SERVICE_FILE="/etc/systemd/system/yanci_bot.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORK_DIR}
EnvironmentFile=${WORK_DIR}/.env
ExecStart=${WORK_DIR}/venv/bin/python3 ${WORK_DIR}/main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable yanci_bot.service
systemctl restart yanci_bot.service

# 最终检查
sleep 3
STATUS=$(systemctl is-active yanci_bot.service)

echo -e "${GREEN}======================================${PLAIN}"
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}   🎉 部署成功！${PLAIN}"
    echo -e "   代码已安装至: ${WORK_DIR}"
    echo -e "   服务状态: 运行中"
else
    echo -e "${RED}   ⚠️ 启动失败，请运行: journalctl -u yanci_bot.service -e${PLAIN}"
fi
echo -e "${GREEN}======================================${PLAIN}"
