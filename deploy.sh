#!/bin/bash

# 定义颜色，让输出更好看
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
PLAIN='\033[0m'

# 检查是否为 root 用户
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}错误: 必须使用 root 用户运行此脚本！${PLAIN}" 
   exit 1
fi

echo -e "${GREEN}======================================${PLAIN}"
echo -e "${GREEN}      部署脚本      ${PLAIN}"
echo -e "${GREEN}======================================${PLAIN}"

# =========================================================
# 1. 交互式输入
# =========================================================
echo -e "${YELLOW}[1/6] 请输入配置信息...${PLAIN}"

read -p "请输入您的 Telegram Bot Token: " BOT_TOKEN
# 简单的非空检查
while [[ -z "$BOT_TOKEN" ]]; do
    echo -e "${RED}Token 不能为空，请重新输入！${PLAIN}"
    read -p "请输入您的 Telegram Bot Token: " BOT_TOKEN
done

read -p "请输入管理员 User ID (Admin ID): " ADMIN_ID
while [[ -z "$ADMIN_ID" ]]; do
    echo -e "${RED}ID 不能为空，请重新输入！${PLAIN}"
    read -p "请输入管理员 User ID: " ADMIN_ID
done

# =========================================================
# 2. 准备目录
# =========================================================
WORK_DIR="/root/tg_bot"

# 检测当前目录下是否有准备好的文件，如果有则复制过去
CURRENT_DIR=$(pwd)
if [ "$CURRENT_DIR" != "$WORK_DIR" ]; then
    if [ -f "requirements.txt" ]; then
        echo -e "${GREEN}发现当前目录下有 requirements.txt，准备复制到部署目录...${PLAIN}"
        mkdir -p "$WORK_DIR"
        cp "requirements.txt" "$WORK_DIR/"
    fi
    if [ -f "main_bot.py" ]; then
        echo -e "${GREEN}发现当前目录下有 main_bot.py，准备复制到部署目录...${PLAIN}"
        mkdir -p "$WORK_DIR"
        cp "main_bot.py" "$WORK_DIR/"
    fi
fi

if [ ! -d "$WORK_DIR" ]; then
    echo -e "创建目录 ${WORK_DIR}..."
    mkdir -p "$WORK_DIR"
fi
cd "$WORK_DIR"

# =========================================================
# 3. 写入 .env 文件
# =========================================================
echo -e "${YELLOW}[2/6] 自动生成配置文件...${PLAIN}"
# 使用 EOF 将刚才输入的变量写入文件
cat > .env <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
EOF
echo -e "${GREEN}.env 文件已生成！${PLAIN}"

# =========================================================
# 4. 检查 requirements.txt
# =========================================================
echo -e "${YELLOW}[3/6] 检查依赖列表...${PLAIN}"

if [ -f "requirements.txt" ]; then
    echo -e "${GREEN}✅ 检测到已存在 requirements.txt，将使用现有文件。${PLAIN}"
else
    echo -e "${YELLOW}⚠️ 未检测到 requirements.txt，正在生成默认文件...${PLAIN}"
    cat > requirements.txt <<EOF
python-telegram-bot
python-dotenv
requests
schedule
EOF
fi

# =========================================================
# 5. 安装系统级依赖
# =========================================================
echo -e "${YELLOW}[4/6] 安装 Python 环境...${PLAIN}"
# 确保安装了 venv 模块
apt-get update -y
apt-get install -y python3 python3-pip python3-venv python3-full

# =========================================================
# 6. 配置 Python 虚拟环境并安装依赖
# =========================================================
echo -e "${YELLOW}[5/6] 安装 Python 库...${PLAIN}"

# 如果已存在 venv，先清理一下以防万一
if [ -d "venv" ]; then
    echo "清理旧的虚拟环境..."
    rm -rf venv
fi

# 创建新的虚拟环境
python3 -m venv venv
# 激活环境
source venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装依赖
echo "正在安装依赖，请稍候..."
pip install -r requirements.txt

# =========================================================
# 7. 配置 Systemd 服务
# =========================================================
echo -e "${YELLOW}[6/6] 配置后台服务...${PLAIN}"
SERVICE_FILE="/etc/systemd/system/yanci_bot.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORK_DIR}
# 加载环境变量
EnvironmentFile=${WORK_DIR}/.env
# 使用虚拟环境中的 python 执行
ExecStart=${WORK_DIR}/venv/bin/python3 ${WORK_DIR}/main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 重载并启动
systemctl daemon-reload
systemctl enable yanci_bot.service
systemctl restart yanci_bot.service

echo -e "${GREEN}======================================${PLAIN}"
echo -e "${GREEN}   🎉 部署完成！${PLAIN}"
echo -e "${GREEN}   Token 已自动填入 .env${PLAIN}"
echo -e "${GREEN}   已使用您的 requirements.txt${PLAIN}"
echo -e "${GREEN}   服务状态: $(systemctl is-active yanci_bot.service)${PLAIN}"
echo -e "${GREEN}======================================${PLAIN}"
