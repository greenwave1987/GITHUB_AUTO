import os
import json
import time
import requests
import base64
import random
import matplotlib.pyplot as plt
from datetime import datetime
from nacl import encoding, public
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ================= 配置 =================
HOST = 'railgun.info'
ENV_NAME = 'RAILGUN'
LOGIN_URL = f"https://{HOST}/login"
CONSOLE_URL = f"https://{HOST}/console/account"

# API 路径
API_MAP = {
    "status": f"https://{HOST}/api/user/status",
    "points": f"https://{HOST}/api/user/points",
    "checkin": f"https://{HOST}/api/user/checkin",
    "traffic": f"https://{HOST}/api/user/traffic",
    "assets": f"https://{HOST}/api/user/assets"
}

# 环境变量读取（增加默认值处理）
EMAILS = [e.strip() for e in os.environ.get(f"{ENV_NAME}_EMAIL", "").split(",") if e.strip()]
TG_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
REPO_TOKEN = os.environ.get("REPO_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")

# ================= 工具函数 =================

def mask_email(email):
    if not email or "@" not in email: return email
    prefix, domain = email.split('@')
    return f"{prefix[:2]}**{prefix[-1]}@{domain}" if len(prefix) > 2 else f"{prefix[0]}**@{domain}"

def tg_send(text):
    if not (TG_TOKEN and TG_CHAT_ID): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"发送TG消息失败: {e}")

def tg_send_photo(photo_path, caption):
    if not (TG_TOKEN and TG_CHAT_ID): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as photo:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption}, files={"photo": photo}, timeout=20)
    except Exception as e:
        print(f"发送TG图片失败: {e}")

# ================= 逻辑核心 =================

def api_fetch(page, url, method="GET", body=None):
    """封装 Page 内部的 Fetch 调用"""
    js_code = f"""
    async () => {{
        try {{
            const options = {{
                method: "{method}",
                headers: {{"Content-Type": "application/json"}}
            }};
            if ("{method}" === "POST" && {json.dumps(body)}) {{
                options.body = JSON.stringify({json.dumps(body)});
            }}
            const r = await fetch("{url}", options);
            return r.ok ? await r.json() : {{code: -1, msg: "HTTP Error " + r.status}};
        }} catch (e) {{
            return {{code: -1, msg: e.message}};
        }}
    }}
    """
    return page.evaluate(js_code)

def generate_trend_chart(points_data, email):
    history = points_data.get("history", [])
    if not history: return None

    # 取最近15次记录
    recent_history = list(reversed(history))[:15]
    dates = [datetime.fromtimestamp(i['time']/1000).strftime('%m-%d') for i in recent_history]
    balances = [float(i.get('change', 0)) for i in recent_history]

    plt.figure(figsize=(10, 5))
    plt.plot(dates, balances, marker='o', color='#2196F3', linewidth=2)
    plt.fill_between(dates, balances, color='#2196F3', alpha=0.1)
    plt.title(f"Points History: {mask_email(email)}")
    plt.grid(True, linestyle="--", alpha=0.3)
    
    img_path = f"trend_{email.split('@')[0]}.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

def update_github_secret(new_value):
    """更新 GitHub Secrets"""
    if not (REPO_TOKEN and GITHUB_REPO): return
    headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        key_resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key", headers=headers).json()
        public_key = key_resp["key"]
        key_id = key_resp["key_id"]

        # 加密
        pk = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(pk)
        encrypted = base64.b64encode(sealed_box.encrypt(new_value.encode("utf-8"))).decode("utf-8")

        requests.put(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{ENV_NAME}_LOCAL",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id}
        )
        print("Successfully updated GitHub Secret.")
    except Exception as e:
        print(f"Update Secret Failed: {e}")

# ================= 主程序 =================

def process_account(browser, email, current_storage):
    masked = mask_email(email)
    context = browser.new_context(
        storage_state=current_storage,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    try:
        # 1. 登录检测
        page.goto(CONSOLE_URL, wait_until="networkidle")
        points_check = api_fetch(page, API_MAP["points"])
        
        if points_check.get('code') != 0:
            print(f"[{masked}] Session 过期，尝试登录...")
            page.goto(LOGIN_URL)
            page.fill("#email", email)
            click_time = time.time()
            page.click("button:has-text('Get Code')")
            
            from __main__ import tg_wait_code # 保持原有的TG等待逻辑
            code = tg_wait_code(email, click_time)
            if not code: return None
            
            page.fill("#mailcode", code)
            page.click("button[type=submit]")
            page.wait_for_url("**/console/account")

        # 2. 执行签到
        checkin_res = api_fetch(page, API_MAP["checkin"], "POST", {"token": HOST})
        msg = "✅ 签到成功" if checkin_res.get("code") == 0 else "⚠️ 今日已签到"
        
        # 3. 获取汇总信息
        status_data = api_fetch(page, API_MAP["status"]).get("data", {})
        points_data = api_fetch(page, API_MAP["points"])
        traffic_data = api_fetch(page, API_MAP["traffic"]).get("data", {})

        # 数据解析
        left_days = status_data.get("leftDays") or api_fetch(page, API_MAP["assets"]).get("data", {}).get("days", 0)
        total_pts = points_data.get("points", 0)
        used_gb = traffic_data.get("today", 0) / (1024**3)
        limit_gb = traffic_data.get("limit", 0) / 100

        summary = (
            f"<b>👤 账号: {masked}</b>\n"
            f"结果: {msg}\n"
            f"⏳ 剩余: {int(float(left_days))} 天\n"
            f"📊 流量: {used_gb:.2f}G / {limit_gb:.0f}G\n"
            f"💰 积分: {int(float(total_pts))}"
        )

        # 4. 生成报表
        chart_path = generate_trend_chart(points_data, email)
        if chart_path:
            tg_send_photo(chart_path, summary)
            os.remove(chart_path)
        else:
            tg_send(summary)

        return context.storage_state()

    except Exception as e:
        print(f"[{masked}] 运行出错: {str(e)}")
        return current_storage
    finally:
        context.close()

def run():
    print(f"🚀 {ENV_NAME} 自动化任务启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    local_raw = os.environ.get(f"{ENV_NAME}_LOCAL", "{}")
    try:
        storage_dict = json.loads(local_raw)
    except:
        storage_dict = {}

    new_storage_dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        
        for email in EMAILS:
            # 随机延迟避免触发WAF
            if len(EMAILS) > 1:
                wait = random.randint(30, 60)
                print(f"等待 {wait}s 后处理下一账号...")
                time.sleep(wait)
            
            res_state = process_account(browser, email, storage_dict.get(email))
            if res_state:
                new_storage_dict[email] = res_state
        
        browser.close()

    # 如果 Session 有更新，同步至 GitHub
    if json.dumps(new_storage_dict) != local_raw:
        update_github_secret(json.dumps(new_storage_dict))

if __name__ == "__main__":
    run()
