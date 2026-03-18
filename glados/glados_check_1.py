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

# ---------- 配置与常量 ----------
LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console/account"
STATUS_API = "https://glados.cloud/api/user/status"
POINTS_API = "https://glados.cloud/api/user/points"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

EMAILS = os.environ["GLADOS_EMAIL"].split(",")
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
REPO_TOKEN = os.environ["REPO_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPOSITORY"]

def tg_send(text):
    print(f"[STEP] 📤 发送 TG 消息: {text[:20]}...")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)

def tg_send_photo(photo_path, caption):
    """发送图片到 Telegram"""
    print(f"[STEP] 🖼️ 发送趋势图...")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption}, files={"photo": photo}, timeout=20)

def generate_trend_chart(points_data, email):
    """生成积分趋势图"""
    history = points_data.get("history", [])
    if not history: return None
    
    dates = [datetime.fromtimestamp(i['time']/1000).strftime('%m-%d') for i in reversed(history)]
    balances = [float(i['change']) for i in reversed(history)]
    
    plt.figure(figsize=(10, 5))
    plt.plot(dates, balances, marker='o', color='#007bff', linewidth=2)
    plt.fill_between(dates, balances, color='#007bff', alpha=0.1)
    plt.title(f"Points Trend: {email}", fontsize=12)
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    
    img_path = f"trend_{email.split('@')[0]}.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

# ... [保留你原有的 encrypt_secret 和 update_secret 函数] ...

def encrypt_secret(public_key: str, secret_value: str) -> str:
    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def update_secret(name, value):
    headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github+json"}
    key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
    key_resp = requests.get(key_url, headers=headers).json()
    if "key" not in key_resp: return
    encrypted_value = encrypt_secret(key_resp["key"], value)
    put_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{name}"
    put_data = {"encrypted_value": encrypted_value, "key_id": key_resp["key_id"]}
    requests.put(put_url, headers=headers, json=put_data)

def tg_wait_code(email, send_time, timeout=300):
    tg_send(f"📨 GLaDOS 验证码\n账号: {email}\n请回复：/code 123456")
    offset, start_wait = None, time.time()
    while time.time() - start_wait < timeout:
        try:
            resp = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", params={"offset": offset, "timeout": 10}).json()
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                if msg.get("text", "").startswith("/code"):
                    if msg.get("date", 0) >= int(send_time):
                        return msg.get("text").replace("/code", "").strip()
        except: pass
        time.sleep(5)
    return None

def check_session_by_points(page):
    try:
        time.sleep(2)
        result = page.evaluate(f'async () => {{ const r = await fetch("{POINTS_API}"); return r.ok ? await r.json() : null; }}')
        return result and result.get('code') == 0
    except: return False

def run():
    print("====== GLaDOS 自动签到开始 ======")
    local_raw = os.environ.get("GLADOS_LOCAL", "[]")
    try:
        local_storage_list = json.loads(local_raw)
        if not isinstance(local_storage_list, list): local_storage_list = [local_storage_list]
    except: local_storage_list = []

    final_storage_list = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        
        for index, email in enumerate(EMAILS):
            if index < 5:
                continue
            # --- 随机等待，模拟真人操作 ---
            sleep_time = random.randint(60, 120)
            print(f"[WAIT] ⏳ 随机等待 {sleep_time} 秒...")
            time.sleep(sleep_time)
            email = email.strip()
            print(f"\n>>> 处理账号: {email}")
            current_storage = local_storage_list[index] if index < len(local_storage_list) else None

            context = browser.new_context(storage_state=current_storage, viewport={"width": 1920, "height": 1080}, user_agent="Mozilla/5.0 Chrome/128.0.0.0")
            page = context.new_page()

            try:
                page.goto(CONSOLE_URL)
                if not check_session_by_points(page):
                    print(f"[INFO] {email} Session失效，开始登录")
                    page.goto(LOGIN_URL)
                    page.fill("#email", email)
                    click_t = time.time()
                    page.click("button:has-text('Get Code')")
                    code = tg_wait_code(email, click_t)
                    if not code: continue
                    page.fill("#mailcode", code)
                    page.click("button[type=submit]")
                    page.wait_for_load_state("networkidle")
                
                # --- 核心修改：签到 + 获取状态 + 获取积分 ---
                if check_session_by_points(page):
                    print(f"✅ 账号 {email} 在线，开始自动化流程")
                    
                    # 1. 签到
                    page.evaluate(f'fetch("{CHECKIN_API}", {{method:"POST", headers:{{"content-type":"application/json"}}, body:JSON.stringify({{token:"glados.cloud"}}) }})')
                    
                    # 2. 获取剩余天数
                    status_json = page.evaluate(f'async () => {{ const r = await fetch("{STATUS_API}"); return await r.json(); }}')
                    left_days = int(float(status_json['data'].get('leftDays', 0)))
                    
                    # 3. 获取积分历史并绘图
                    points_json = page.evaluate(f'async () => {{ const r = await fetch("{POINTS_API}"); return await r.json(); }}')
                    total_points = int(float(points_json.get('points', 0)))
                    
                    chart_path = generate_trend_chart(points_json, email)
                    
                    # 4. 发送汇总消息
                    summary = f"🎉 账号 {email} 签到完成\n⏳ 剩余天数: {left_days} 天\n💰 当前积分: {total_points}"
                    if chart_path:
                        tg_send_photo(chart_path, summary)
                        os.remove(chart_path) # 发送完删除图片
                    else:
                        tg_send(summary)

                    final_storage_list.append(context.storage_state())
                else:
                    print(f"❌ 账号 {email} 状态异常")
                    final_storage_list.append(current_storage)

            except Exception as e:
                print(f"⚠️ {email} 运行出错: {e}")
                final_storage_list.append(current_storage)
            finally:
                context.close()
        browser.close()

    if final_storage_list:
        update_secret("GLADOS_LOCAL", json.dumps(final_storage_list))
    print("====== 任务结束 ======")

if __name__ == "__main__":
    run()
