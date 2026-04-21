import os
import json
import time
import requests
import base64
import random
import matplotlib.pyplot as plt
from datetime import datetime
from nacl import encoding, public
from playwright.sync_api import sync_playwright

# ================= 配置 =================
HOST='glados.cloud'
ENV_NAME='GLADOS'
LOGIN_URL = f"https://{HOST}/login"
CONSOLE_URL = f"https://{HOST}/console/account"

API_MAP = {
    "status": f"https://{HOST}/api/user/status",
    "points": f"https://{HOST}/api/user/points",
    "checkin": f"https://{HOST}/api/user/checkin",
    "traffic": f"https://{HOST}/api/user/traffic",
    "assets": f"https://{HOST}/api/user/assets"
}

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

def tg_wait_code(email, send_time, timeout=300):
    """等待用户在TG回复验证码"""
    masked = mask_email(email)
    tg_send(f"📨 <b>{ENV_NAME} 验证码请求</b>\n账号: <code>{masked}</code>\n请在 {timeout//60} 分钟内回复：\n<code>/code 123456</code>")

    offset = None
    start_wait = time.time()
    while time.time() - start_wait < timeout:
        try:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 10}, timeout=15).json()
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                text = msg.get("text", "")
                if text.startswith("/code"):
                    # 校验消息时间，防止读取旧验证码
                    if msg.get("date", 0) >= int(send_time):
                        code = text.replace("/code", "").strip()
                        print(f"收到验证码: {code}")
                        return code
        except Exception as e:
            print(f"轮询TG验证码出错: {e}")
        time.sleep(5)
    print(f"等待验证码超时 ({masked})")
    return None

def api_fetch(page, url, method="GET", body=None):
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
    recent_history = list(reversed(history))[:15]
    dates = [datetime.fromtimestamp(i['time']/1000).strftime('%m-%d') for i in recent_history]
    balances = [float(i.get('change', 0)) / 100 if float(i.get('change', 0)) < 0 else float(i.get('change', 0)) for i in recent_history]
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
    if not (REPO_TOKEN and GITHUB_REPO): return
    headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers).json()
        public_key = key_resp["key"]
        key_id = key_resp["key_id"]
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

# ================= 核心流程 =================

def process_account(browser, email, current_storage):
    masked = mask_email(email)
    context = browser.new_context(
        storage_state=current_storage,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    try:
        page.goto(CONSOLE_URL, wait_until="networkidle")
        status_data = api_fetch(page, API_MAP["status"])
        
        # 登录失效判断
        if not status_data or status_data.get('code') == -2:
            print(f"[{masked}] Session失效，尝试登录...")
            page.goto(LOGIN_URL)
            page.fill("#email", email)
            click_time = time.time()
            page.click("button:has-text('Get Code')")
            
            code = tg_wait_code(email, click_time)
            if not code: 
                print(f"[{masked}] 未能获取验证码，跳过")
                return None
            
            page.fill("#mailcode", code)
            page.click("button[type=submit]")
            
            # --- 修复点：放宽匹配路径，并增加网络空闲等待 ---
            try:
                page.wait_for_url("**/console**", timeout=30000, wait_until="networkidle")
                print(f"[{masked}] 登录跳转成功")
            except Exception as e:
                print(f"[{masked}] 登录跳转超时，尝试强制继续...")

        # 执行签到
        checkin_res = api_fetch(page, API_MAP["checkin"], "POST", {"token": HOST})
        msg = "✅ 签到成功" if checkin_res.get("code") == 0 else "⚠️ 今日已签到"
        
        # 获取汇总数据
        if status_data and status_data.get('code') == -2:
            status_data = api_fetch(page, API_MAP["status"]).get("data", {})
        if status_data and status_data.get('code') == -100:
            msg += f"\n⚠️ {status_data.get('boarding')}，需要激活码！"
        url = ""
        if status_data and status_data.get('code') == 0:
            d = status_data["data"]
            site = d.get("site")
            
            if site == "glados.network":
                # 结构：/userId/code/port/glados.yaml
                url = f"https://update.glados-config.com/mihomo/{d['userId']}/{d['code']}/{d['port']}/glados.yaml"
                
            elif site == "railgun.info":
                # 结构：/固定ID/password/full.yaml
                url = f"https://update.railgunx.com/mihomo/e2308c94/{d['password']}/full.yaml"
            
            else:
                url = "未知站点结构"
            
            ##print(url)

        points_data = api_fetch(page, API_MAP["points"])
        traffic_data = api_fetch(page, API_MAP["traffic"]).get("data", {})

        left_days = status_data.get("leftDays") or api_fetch(page, API_MAP["assets"]).get("data", {}).get("days", 0)
        total_pts = points_data.get("points", 0)
        used_gb = traffic_data.get("today", 0) / (1024**3)
        limit_gb = traffic_data.get("limit", 0) / 100

        summary = (
            f"👤 账号: {masked}\n"
            f"{msg}\n"
            f"⏳ 剩余: {int(float(left_days))} 天\n"
            f"📊 流量: {used_gb:.2f}G / {limit_gb:.0f}G\n"
            f"💰 积分: {int(float(total_pts))}\n"
            f"🔗 订阅: {url}"
        )

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
    print(f"🚀 {ENV_NAME} 自动化任务启动")
    local_raw = os.environ.get(f"{ENV_NAME}_LOCAL", "{}")
    try:
        storage_dict = json.loads(local_raw)
    except:
        storage_dict = {}

    new_storage_dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for index, email in enumerate(EMAILS):
            if index > 0:
                wait = random.randint(30, 60)
                print(f"等待 {wait}s 后处理下一账号...")
                time.sleep(wait)
            
            res_state = process_account(browser, email, storage_dict.get(email))
            if res_state:
                new_storage_dict[email] = res_state
        browser.close()

    if new_storage_dict and json.dumps(new_storage_dict) != local_raw:
        update_github_secret(json.dumps(new_storage_dict))

if __name__ == "__main__":
    run()
