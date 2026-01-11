#!/bin/bash

# ==========================================
# Yanci Bot 自动部署脚本
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

# 0. 停止旧服务（如果存在）
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

# 2. 准备工作目录
WORK_DIR="/root/tg_bot"
CURRENT_DIR=$(pwd)

echo -e "${YELLOW}[2/6] 同步程序文件...${PLAIN}"

# 如果当前不在工作目录，则进行文件复制
if [ "$CURRENT_DIR" != "$WORK_DIR" ]; then
    mkdir -p "$WORK_DIR"
    
    # 复制主程序
    if [ -f "main_bot.py" ]; then
        cp "main_bot.py" "$WORK_DIR/"
        echo -e "✅ 已复制 main_bot.py"
    else
        echo -e "${RED}⚠️ 当前目录下找不到 main_bot.py，请确保你在项目根目录下运行脚本！${PLAIN}"
    fi

    # 复制关键文件夹 (utils 和 plugins)
    if [ -d "utils" ]; then
        cp -r "utils" "$WORK_DIR/"
        echo -e "✅ 已复制 utils 文件夹"
    fi
    
    if [ -d "plugins" ]; then
        cp -r "plugins" "$WORK_DIR/"
        echo -e "✅ 已复制 plugins 文件夹"
    fi
fi

cd "$WORK_DIR"

# 3. 生成配置文件 (.env)
# 注意：代码中读取的是 TG_ 前缀的变量
echo -e "${YELLOW}[3/6] 生成配置文件 (.env)...${PLAIN}"
cat > .env <<EOF
TG_BOT_TOKEN=${INPUT_TOKEN}
TG_ADMIN_ID=${INPUT_ADMIN_ID}
EOF
echo -e "✅ .env 配置已生成"

# 4. 检查并修复依赖列表 (requirements.txt)
echo -e "${YELLOW}[4/6] 检查依赖列表...${PLAIN}"

# 检查文件是否存在且内容是否正常（排除 404 HTML 错误）
if [ -f "requirements.txt" ] && ! grep -q "DOCTYPE" "requirements.txt" && ! grep -q "404" "requirements.txt"; then
    echo -e "✅ 检测到有效的 requirements.txt，将使用现有文件。"
else
    echo -e "${YELLOW}⚠️ 未检测到有效依赖文件，正在生成默认列表...${PLAIN}"
    cat > requirements.txt <<EOF
python-telegram-bot
python-dotenv
requests
EOF
fi

# 5. 安装 Python 环境与依赖
echo -e "${YELLOW}[5/6] 安装环境依赖...${PLAIN}"

# 安装系统级 Python 工具
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-pip python3-venv python3-full >/dev/null 2>&1

# 重置虚拟环境
if [ -d "venv" ]; then
    rm -rf venv
fi
python3 -m venv venv
source venv/bin/activate

# 升级 pip 并安装库
pip install --upgrade pip >/dev/null 2>&1
echo "正在下载并安装 Python 库 (这可能需要一分钟)..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 依赖安装失败！请检查网络或配置。${PLAIN}"
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
    echo -e "${GREEN}   🎉 部署完成！机器人已成功启动！${PLAIN}"
    echo -e "   服务名称: yanci_bot.service"
    echo -e "   使用命令查看日志: journalctl -u yanci_bot.service -f"
else
    echo -e "${RED}   ⚠️ 启动似乎遇到问题，状态: $STATUS${PLAIN}"
    echo -e "   请运行以下命令查看日志: journalctl -u yanci_bot.service -e"
fi
echo -e "${GREEN}======================================${PLAIN}"
