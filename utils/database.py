import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 获取管理员 ID
ADMIN_ID = os.getenv("TG_ADMIN_ID")
try:
    if ADMIN_ID:
        ADMIN_ID = int(ADMIN_ID)
except ValueError:
    ADMIN_ID = None

class UserManager:
    FILE_PATH = 'user_data.json'

    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.FILE_PATH):
            return {"users": {}, "config": {"send_qr": True, "bot_active": True}}
        try:
            with open(self.FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "config" not in data:
                    data["config"] = {"send_qr": True, "bot_active": True}
                return data
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return {"users": {}, "config": {"send_qr": True, "bot_active": True}}

    def _save(self):
        try:
            with open(self.FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def authorize_user(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": True, "count": 0, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["authorized"] = True
            if username: self.data["users"][uid]["name"] = username
        self._save()
        return True

    def revoke_user(self, user_id):
        uid = str(user_id)
        if uid in self.data["users"]:
            self.data["users"][uid]["authorized"] = False
            self._save()
            return True
        return False

    def is_authorized(self, user_id):
        if ADMIN_ID and user_id == ADMIN_ID:
            return True
        uid = str(user_id)
        user = self.data["users"].get(uid)
        return user and user.get("authorized", False)

    def increment_usage(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": False, "count": 1, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["count"] += 1
            if username: self.data["users"][uid]["name"] = username
        self._save()

    def get_all_stats(self):
        return self.data["users"]
    
    def get_config(self, key, default=None):
        return self.data["config"].get(key, default)

    def set_config(self, key, value):
        if "config" not in self.data:
            self.data["config"] = {}
        self.data["config"][key] = value
        self._save()

# 创建单例实例供外部导入
user_manager = UserManager()