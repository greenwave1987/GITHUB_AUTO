import os
import requests
from datetime import datetime

# 配置信息
COOKIE = os.getenv("DOMAIN_COOKIE")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
DOMAIN_NAME = "hyz.qzz.io"
BASE_URL = "https://dash.domain.digitalplat.org/_panel_api/api"

def send_tg_notification(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 TG 通知参数，跳过发送。")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": f"🌐 **域名续期脚本通知**\n\n{message}", "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"发送 TG 通知失败: {e}")

def check_and_renew():
    if not COOKIE:
        msg = "❌ 错误: 未找到 DOMAIN_COOKIE 环境变量"
        print(msg)
        send_tg_notification(msg)
        return

    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36",
        "cookie": COOKIE,
        "Referer": f"https://dash.domain.digitalplat.org/domains/{DOMAIN_NAME}"
    }

    try:
        # 1. 查询状态
        response = requests.get(f"{BASE_URL}/domains", headers=headers)
        data = response.json()
        
        if not data.get("ok"):
            msg = f"❌ 查询失败，请检查 Cookie！\n响应内容: {data}"
            print(msg)
            send_tg_notification(msg)
            return

        domain_info = next((d for d in data['domains'] if d['domain'] == DOMAIN_NAME), None)
        if not domain_info:
            msg = f"❌ 未在账户中找到域名: {DOMAIN_NAME}"
            send_tg_notification(msg)
            return

        # 2. 计算日期
        expiry_str = domain_info['expiry_date']
        expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
        remaining_days = (expiry_date - datetime.now()).days
        status_msg = f"域名: `{DOMAIN_NAME}`\n剩余天数: `{remaining_days}` 天\n到期日期: `{expiry_str}`"

        # 3. 判断续期
        if remaining_days < 100:
            renew_res = requests.post(
                f"{BASE_URL}/domains/{DOMAIN_NAME}/renew", 
                headers=headers, 
                json={"renewal_type": "free", "years": 1}
            )
            if renew_res.status_code == 200:
                final_msg = f"✅ 续期请求成功！\n{status_msg}\n接口返回: {renew_res.text}"
            else:
                final_msg = f"⚠️ 续期请求异常！状态码: {renew_res.status_code}\n{status_msg}"
        else:
            final_msg = f"ℹ️ 运行正常，有效期充足。\n{status_msg}"
        
        print(final_msg)
        send_tg_notification(final_msg)

    except Exception as e:
        error_msg = f"🔥 程序运行发生异常: {str(e)}"
        print(error_msg)
        send_tg_notification(error_msg)

if __name__ == "__main__":
    check_and_renew()
