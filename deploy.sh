#!/bin/bash

# ================= 配置区 =================
# ⚠️ 必须指向包含 plugins/ 和 utils/ 文件夹的 GitHub 根目录 Raw 地址
REPO_URL="https://raw.githubusercontent.com/2019xuanying/tg-bot/main"
INSTALL_DIR="/root/tg_bot"

# ================= 脚本逻辑 =================

if [[ $EUID -ne 0 ]]; then
   echo "❌ 错误：请使用 root 权限运行此脚本！" 
   exit 1
fi

echo "======================================"
echo "   多功能机器人 - 模块化部署脚本"
echo "======================================"

# 1. 环境安装
echo "[1/5] 安装 Python 环境..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv curl

# 2. 准备目录结构 (关键步骤)
echo "[2/5] 创建目录结构..."
mkdir -p "$INSTALL_DIR/utils"
mkdir -p "$INSTALL_DIR/plugins"
cd "$INSTALL_DIR" || exit

# 创建空的 __init__.py 以便 Python 识别为包
touch "$INSTALL_DIR/utils/__init__.py"
touch "$INSTALL_DIR/plugins/__init__.py"

# 3. 下载文件 (逐个下载以保持兼容性)
echo "[3/5] 拉取最新代码..."

# 下载根目录文件
curl -s -o main_bot.py "$REPO_URL/main_bot.py"
curl -s -o requirements.txt "$REPO_URL/requirements.txt"

# 下载 utils 工具包
curl -s -o utils/database.py "$REPO_URL/utils/database.py"
curl -s -o utils/mail.py "$REPO_URL/utils/mail.py"

# 下载 plugins 插件
curl -s -o plugins/yanci.py "$REPO_URL/plugins/yanci.py"

echo "      ✅ 文件下载完成。"

# 4. 虚拟环境
echo "[4/5] 安装依赖..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 5. 生成服务配置
echo "[5/5] 配置 Systemd..."
# 检查是否已有配置
if [ ! -f ".env" ]; then
    echo "TG_BOT_TOKEN=" >> .env
    echo "TG_ADMIN_ID=" >> .env
    echo "⚠️  请手动编辑 $INSTALL_DIR/.env 填入 Token！"
fi

SERVICE_FILE="/etc/systemd/system/yanci_bot.service"
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Modular Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
# 注意：这里启动的是 main_bot.py
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable yanci_bot
systemctl restart yanci_bot

echo "======================================"
echo "   🎉 部署完成！"
echo "   主程序: main_bot.py"
echo "======================================"
