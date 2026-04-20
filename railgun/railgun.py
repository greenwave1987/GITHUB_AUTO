import os
import json
import time
import requests
import base64
import random
from nacl import encoding, public
from playwright.sync_api import sync_playwright
import matplotlib.pyplot as plt
from datetime import datetime

# ================= 配置 =================
LOGIN_URL = "https://railgun.info/login"
CONSOLE_URL = "https://railgun.info/console/account"

STATUS_API = "https://railgun.info/api/user/status"
POINTS_API = "https://railgun.info/api/user/points"
CHECKIN_API = "https://railgun.info/api/user/checkin"
TRAFFIC_API = "https://railgun.info/api/user/traffic"

EMAILS = os.environ["GLADOS_EMAIL"].split(",")

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]

REPO_TOKEN = os.environ["REPO_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPOSITORY"]

# ================= 工具函数 =================

def mask_email(email):
    """脱敏账号显示，只显前两位和最后一位，中间以**替代"""
    if not email or "@" not in email:
        return email
    prefix = email.split('@')[0]
    domain = email.split('@')[1]
    if len(prefix) <= 2:
        return f"{prefix[0]}**@{domain}"
    return f"{prefix[:2]}**{prefix[-1]}@{domain}"

def tg_send(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)

def tg_send_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(
            url,
            data={"chat_id": TG_CHAT_ID, "caption": caption},
            files={"photo": photo},
            timeout=20
        )

# ================= 趋势图 =================

def generate_trend_chart(points_data, email):
    history = points_data.get("history", [])
    if not history:
        return None

    dates = [
        datetime.fromtimestamp(i['time']/1000).strftime('%m-%d')
        for i in reversed(history)
    ]
    balances = [
        val if val >= 0 else val / 100
        for i in reversed(history)
        for val in [float(i.get('change', 0))]
    ]

    plt.figure(figsize=(10,5))
    plt.plot(dates, balances, marker='o', linewidth=2)
    plt.fill_between(dates, balances, alpha=0.2)
    
    # 图表标题也使用脱敏邮箱
    masked = mask_email(email)
    plt.title(f"Points Trend: {masked}")
    plt.xticks(rotation=30)
    plt.grid(True, linestyle="--", alpha=0.5)

    img_path = f"trend_{email.split('@')[0]}.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

# ================= GitHub Secret =================

def encrypt_secret(public_key: str, secret_value: str):
    public_key_obj = public.PublicKey(
        public_key.encode("utf-8"),
        encoding.Base64Encoder()
    )
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def update_secret(name, value):
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
    key_resp = requests.get(key_url, headers=headers).json()

    if "key" not in key_resp:
        return

    encrypted_value = encrypt_secret(key_resp["key"], value)
    put_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{name}"
    put_data = {
        "encrypted_value": encrypted_value,
        "key_id": key_resp["key_id"]
    }
    requests.put(put_url, headers=headers, json=put_data)

# ================= TG验证码 =================

def tg_wait_code(email, send_time, timeout=300):
    masked = mask_email(email)
    tg_send(f"📨 RAILGUN 验证码\n账号: {masked}\n回复：/code 123456")

    offset = None
    start_wait = time.time()
    while time.time() - start_wait < timeout:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10}
            ).json()
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                if msg.get("text", "").startswith("/code"):
                    if msg.get("date", 0) >= int(send_time):
                        return msg.get("text").replace("/code", "").strip()
        except:
            pass
        time.sleep(5)
    return None

# ================= session检查 =================

def check_session_by_points(page):
    try:
        time.sleep(2)
        result = page.evaluate(
            f'''
            async () => {{
                const r = await fetch("{POINTS_API}");
                return r.ok ? await r.json() : null;
            }}
            '''
        )
        print(f"POINTS_API:{result}")
        return result and result.get('code') == 0
    except:
        return False

# ================= 主程序 =================

def run():
    print("====== RAILGUN 自动签到开始 ======")
    local_raw = os.environ.get("RAILGUN_LOCAL", "{}")
    try:
        local_storage_dict = json.loads(local_raw)
        if not isinstance(local_storage_dict, dict):
            local_storage_dict = {}
    except:
        local_storage_dict = {}

    final_storage_dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )

        for email in filter(None, [i.strip() for i in EMAILS]):
            sleep_time = random.randint(60, 120)
            print(f"[WAIT] {sleep_time}s")
            time.sleep(sleep_time)

            email = email.strip()
            masked = mask_email(email)
            print(f"\n>>> {masked}")

            current_storage = local_storage_dict.get(email)
            context = browser.new_context(
                storage_state=current_storage if current_storage else None,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 Chrome/128.0.0.0"
            )

            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            try:
                page.goto(CONSOLE_URL)

                if not check_session_by_points(page):
                    print(f"[{masked}] session失效，开始登录")
                    page.goto(LOGIN_URL)
                    page.fill("#email", email)
                    click_t = time.time()
                    page.click("button:has-text('Get Code')")
                    code = tg_wait_code(email, click_t)

                    if not code:
                        final_storage_dict[email] = current_storage
                        continue

                    page.fill("#mailcode", code)
                    page.click("button[type=submit]")
                    page.wait_for_load_state("networkidle")

                if check_session_by_points(page):
                    print(f"[{masked}] 签到")
                    page.evaluate(
                        f'''
                        fetch("{CHECKIN_API}",{{
                        method:"POST",
                        headers:{{"content-type":"application/json"}},
                        body:JSON.stringify({{token:"railgun.info"}})
                        }})
                        '''
                    )

                    status_json = page.evaluate(f'async () => {{ const r = await fetch("{STATUS_API}"); return await r.json(); }}')
                    print(f"STATUS_API[{status_json}] ")
                    left_days = 0
                    if status_json and status_json.get("code") == 0:
                        left_days = int(float(status_json['data'].get('leftDays', 0)))

                    points_json = page.evaluate(f'async () => {{ const r = await fetch("{POINTS_API}"); return await r.json(); }}')
                    print(f"POINTS_API[{points_json}] ")
                    total_points=0
                    if points_json and points_json.get("code") == 0:
                        total_points = int(float(points_json.get('points', 0)))
                        chart_path = generate_trend_chart(points_json, email)

                    traffic_json = page.evaluate(f'async () => {{ const r = await fetch("{TRAFFIC_API}"); return await r.json(); }}')
                    print(f"TRAFFIC_API[{traffic_json}] ")
                    traffic_info = "未知"
                    if traffic_json and traffic_json.get("code") == 0:
                        t_data = traffic_json.get("data", {})
                        used_gb = t_data.get("today", 0) / (1024**3)
                        limit_gb = t_data.get("limit", 0) / 100 
                        traffic_info = f"{used_gb:.2f} GB / {limit_gb:.0f} GB"

                    
                    summary = (
                        f"🎉 {masked} 签到成功\n"
                        f"⏳ 剩余: {left_days} 天\n"
                        f"📊 流量: {traffic_info}\n"
                        f"💰 积分: {total_points}"
                    )

                    if chart_path:
                        tg_send_photo(chart_path, summary)
                        os.remove(chart_path)
                    else:
                        tg_send(summary)

                    final_storage_dict[email] = context.storage_state()
                else:
                    print(f"[{masked}] 账号状态异常")
                    final_storage_dict[email] = current_storage

            except Exception as e:
                print(f"[{masked}] Error: {e}")
                final_storage_dict[email] = current_storage
            finally:
                context.close()

        browser.close()

    old = os.environ.get("RAILGUN_LOCAL", "{}")
    new = json.dumps(final_storage_dict)
    if old != new:
        update_secret("RAILGUN_LOCAL", new)
    print("====== 任务结束 ======")

if __name__ == "__main__":
    run()
