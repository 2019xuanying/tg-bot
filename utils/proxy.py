import requests
import random
import logging
from utils.database import user_manager

logger = logging.getLogger(__name__)

class ProxyManager:
    @staticmethod
    def parse_proxy(proxy_str):
        """
        解析代理字符串，支持两种格式：
        1. ip:port:user:pass -> socks5://user:pass@ip:port
        2. ip:port -> http://ip:port
        """
        try:
            parts = proxy_str.strip().split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                return f"socks5://{user}:{password}@{ip}:{port}"
            elif len(parts) == 2:
                ip, port = parts
                return f"http://{ip}:{port}"
            else:
                return None
        except:
            return None

    @staticmethod
    def fetch_proxies_from_api(count=5):
        """
        核心方法：调用站大爷 API 获取代理 IP
        """
        api_config = user_manager.get_proxy_api()
        api_id = api_config.get("api_id")
        api_akey = api_config.get("api_akey")
        
        if not api_id or not api_akey:
            return False, "未配置 API 参数 (api 或 akey 为空)"

        url = f"http://open.zdaye.com/ShortProxy/GetIP/?api={api_id}&akey={api_akey}&count={count}&timespan=3&type=3"
        
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            code = str(data.get("code"))
            if code == "10001":
                proxy_list = data.get("data", {}).get("proxy_list", [])
                if not proxy_list:
                    return False, "API 返回成功，但列表为空"
                
                # 提取 ip:port 并加入数据库
                new_proxies = [f"{p['ip']}:{p['port']}" for p in proxy_list]
                user_manager.add_proxies(new_proxies)
                logger.info(f"✅ 成功从 API 获取到 {len(new_proxies)} 个新代理。")
                return True, f"成功获取 {len(new_proxies)} 个代理"
            else:
                msg = data.get('msg', '未知错误')
                logger.error(f"❌ API 提取失败: {msg} (Code: {code})")
                return False, f"API 拒绝: {msg} (错误码: {code})"
                
        except Exception as e:
            logger.error(f"❌ 请求代理 API 异常: {e}")
            return False, f"网络请求异常: {str(e)}"

    @staticmethod
    def get_configured_session(test_url="https://www.google.com", timeout=10):
        """
        核心方法：获取一个配置好代理的 Session。
        支持代理池耗尽时，自动通过 API 补货。
        """
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        use_proxy = user_manager.get_config("use_proxy", True)
        if not use_proxy:
            return session

        raw_proxies = user_manager.get_proxies()
        
        # === 智能补货机制 ===
        if not raw_proxies:
            logger.info("⚠️ 代理池为空，尝试从 API 自动提取新代理...")
            success, _ = ProxyManager.fetch_proxies_from_api(count=5)
            if success:
                raw_proxies = user_manager.get_proxies() # 重新获取
            else:
                logger.warning("代理池为空且 API 提取失败，降级为直连模式。")
                return session

        max_retries = 5
        candidates = random.sample(raw_proxies, min(len(raw_proxies), max_retries * 2)) 
        
        tried_count = 0
        for proxy_str in candidates:
            if tried_count >= max_retries:
                break
            
            formatted_proxy = ProxyManager.parse_proxy(proxy_str)
            if not formatted_proxy:
                continue

            proxies_dict = {'http': formatted_proxy, 'https': formatted_proxy}
            
            try:
                test_sess = requests.Session()
                test_sess.proxies = proxies_dict
                resp = test_sess.get(test_url, timeout=timeout)
                
                if resp.status_code == 200:
                    logger.info(f"✅ 代理连接成功: {formatted_proxy}")
                    session.proxies = proxies_dict
                    return session
            except Exception as e:
                logger.error(f"⚠️ 代理 {proxy_str} 失效: {type(e).__name__} - {str(e)}")
                # 可以在这里加入自动剔除失效代理的逻辑
            
            tried_count += 1

        logger.error(f"❌ 所有 {tried_count} 次代理尝试均失败，降级为【服务器直连】模式。")
        return session

get_safe_session = ProxyManager.get_configured_session
        
        # 1. 基础 Header
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        # 2. 检查全局开关
        use_proxy = user_manager.get_config("use_proxy", True)
        if not use_proxy:
            # logger.info("代理开关已关闭，使用直连模式。") 
            return session

        # 3. 获取代理列表
        raw_proxies = user_manager.get_proxies()
        if not raw_proxies:
            logger.warning("代理列表为空，使用直连模式。")
            return session

        # 4. 尝试连接 (最多5次)
        max_retries = 5
        candidates = random.sample(raw_proxies, min(len(raw_proxies), max_retries * 2)) 
        
        tried_count = 0
        for proxy_str in candidates:
            if tried_count >= max_retries:
                break
            
            formatted_proxy = ProxyManager.parse_proxy(proxy_str)
            if not formatted_proxy:
                continue

            # 配置临时代理进行测试
            proxies_dict = {'http': formatted_proxy, 'https': formatted_proxy}
            
            try:
                # logger.info(f"正在尝试代理 ({tried_count+1}/{max_retries}): {proxy_str} ...")
                test_sess = requests.Session()
                test_sess.proxies = proxies_dict
                
                # 增加 verify=False 避免部分代理 SSL 握手问题导致失败，仅测试连通性
                # 注意：这可能会有安全警告，但在测试代理连通性时是可以接受的
                resp = test_sess.get(test_url, timeout=timeout)
                
                if resp.status_code == 200:
                    logger.info(f"✅ 代理连接成功: {formatted_proxy}")
                    session.proxies = proxies_dict
                    return session
            except Exception as e:
                # === 修改处：打印详细错误信息以便排查 ===
                # 常见错误：
                # 1. ProxyError: 代理无法连接 (IP死的/端口不对)
                # 2. ConnectTimeout: 超时
                # 3. SSLError: 代理不支持 HTTPS 握手
                logger.error(f"⚠️ 代理 {proxy_str} 失败: {type(e).__name__} - {str(e)}")
            
            tried_count += 1

        # 5. 降级处理
        logger.error(f"❌ 所有 {tried_count} 次代理尝试均失败，降级为【服务器直连】模式。")
        return session

# 方便外部调用
get_safe_session = ProxyManager.get_configured_session
