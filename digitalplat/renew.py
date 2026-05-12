import os
import requests
from datetime import datetime

# 从 GitHub Secrets 读取配置
# 多个 Cookie 请在 Secret 中换行输入
COOKIES_STR = os.getenv("DOMAIN_COOKIE") 
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
BASE_URL = "https://dash.domain.digitalplat.org/_panel_api/api"

def send_tg(message):
    if TG_BOT_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try: requests.post(url, json=payload)
        except: print("TG 发送失败")

def process_account(cookie, index):
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5)",
        "cookie": cookie.strip()
    }
    
    report = f"👤 **账号 # {index}**\n"
    try:
        # 1. 获取该账号下所有域名
        res = requests.get(f"{BASE_URL}/domains", headers=headers)
        data = res.json()
        
        if not data.get("ok"):
            return report + "❌ 登录失效或请求失败\n"

        domains = data.get("domains", [])
        if not domains:
            return report + "❓ 该账号下无域名\n"

        for d in domains:
            domain_name = d['domain']
            expiry_str = d['expiry_date']
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
            remaining_days = (expiry_date - datetime.now()).days
            
            item_info = f"- `{domain_name}`: 剩余 `{remaining_days}` 天 "
            
            # 2. 判断是否需要续期 (少于100天)
            if remaining_days < 100:
                renew_res = requests.post(
                    f"{BASE_URL}/domains/{domain_name}/renew",
                    headers=headers,
                    json={"renewal_type": "free", "years": 1}
                )
                if renew_res.status_code == 200:
                    item_info += "✅ **已续期**\n"
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
