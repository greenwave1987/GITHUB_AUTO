import os
from datetime import datetime
# 将 requests 替换为 curl_cffi 的 requests
from curl_cffi import requests

# 从 GitHub Secrets 读取配置
COOKIES_STR = os.getenv("DOMAIN_COOKIE") 
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
BASE_URL = "https://dash.domain.digitalplat.org/_panel_api/api"

def send_tg(message):
    if TG_BOT_TOKEN and TG_CHAT_ID:
        # 飞往 TG 的接口一般不会被 cf 拦截，保持常规请求即可
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            # 简单使用原生的方式发通知
            import json
            import urllib.request
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: 
            print(f"TG 发送失败: {e}")

def process_account(cookie, index):
    # 模拟高度逼真的浏览器头部
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "pragma": "no-cache",
        "sec-gpc": "1",
        "cookie": cookie.strip()
    }
    
    report = f"👤 **账号 # {index}**\n"
    try:
        # --- 1. 获取该账号下所有域名 ---
        # 加上 impersonate 模拟 Chrome 指纹，补充 Referer 防护
        domains_url = f"{BASE_URL}/domains"
        account_headers = headers.copy()
        account_headers["Referer"] = "https://dash.domain.digitalplat.org/domains"
        
        res = requests.get(
            domains_url, 
            headers=account_headers, 
            impersonate="chrome124", 
            timeout=15
        )
        
        # 如果获取列表时就 403，直接抛出，免得解析报错
        if res.status_code == 403:
            return report + "❌ 请求被 WAF 拦截 (403 防爬虫触发)，请更新 Cookie 或检查 WAF 状态。\n"
            
        data = res.json()
        if not data.get("ok"):
            return report + "❌ 登录失效或获取域名失败\n"

        domains = data.get("domains", [])
        if not domains:
            return report + "❓ 该账号下无域名\n"

        for d in domains:
            domain_name = d['domain']
            expiry_str = d['expiry_date'] # 格式如 "20261120"
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
            remaining_days = (expiry_date - datetime.now()).days
            
            item_info = f"- `{domain_name}`: 剩余 `{remaining_days}` 天 "
            
            # --- 2. 判断是否需要续期 (少于100天) ---
            if remaining_days < 100:
                renew_url = f"{BASE_URL}/domains/{domain_name}/renew"
                
                # 动态构造当前域名的 Referer，防止防刷系统校验
                renew_headers = headers.copy()
                renew_headers["Referer"] = f"https://dash.domain.digitalplat.org/domains/{domain_name}"
                
                renew_res = requests.post(
                    renew_url,
                    headers=renew_headers,
                    json={"renewal_type": "free", "years": 1},
                    impersonate="chrome124",  # 关键：全量模拟浏览器 JA3 指纹
                    timeout=15
                )
                
                if renew_res.status_code == 200 and renew_res.json().get("ok"):
                    item_info += "✅ **已续期**\n"
                elif renew_res.status_code == 403:
                    item_info += "⚠️ **续期被 WAF 拦截 (403)**\n"
                else:
                    item_info += "⚠️ **续期失败**\n"
            else:
                item_info += "😴 状态良好\n"
            
            report += item_info
        return report + "\n"

    except Exception as e:
        return report + f"💥 运行异常: {str(e)}\n\n"

if __name__ == "__main__":
    if not COOKIES_STR:
        print("未找到 DOMAIN_COOKIES")
        exit(1)

    # 支持换行或逗号分隔多个 Cookie
    cookie_list = [c for c in COOKIES_STR.replace(',', '\n').split('\n') if c.strip()]
    final_report = "🌐 **域名轮询检查报告**\n\n"
    
    for i, ck in enumerate(cookie_list, 1):
        final_report += process_account(ck, i)
    
    print(final_report)
    send_tg(final_report)
