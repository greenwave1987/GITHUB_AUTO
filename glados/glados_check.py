import os
import json
import time
import requests
import base64
from nacl import encoding, public
from playwright.sync_api import sync_playwright

# ---------- 配置与常量 ----------
LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console/account"
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

def encrypt_secret(public_key: str, secret_value: str) -> str:
    """使用 GitHub 公钥加密 Secret"""
    public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def update_secret(name, value):
    print(f"[STEP] 🔐 准备加密并更新 GitHub Secret: {name}")
    headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github+json"}
    
    # 1. 获取公钥
    key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
    key_resp = requests.get(key_url, headers=headers).json()
    if "key" not in key_resp:
        print(f"❌ 获取公钥失败: {key_resp}")
        return

    # 2. 加密数据
    encrypted_value = encrypt_secret(key_resp["key"], value)
    
    # 3. 更新 Secret
    put_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{name}"
    put_data = {"encrypted_value": encrypted_value, "key_id": key_resp["key_id"]}
    r = requests.put(put_url, headers=headers, json=put_data)
    print(f"[RESULT] Secret {name} 更新状态码: {r.status_code}")

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
        # 增加 explicit wait 确保页面 API 已经准备好
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
            email = email.strip()
            print(f"\n>>> 处理账号: {email}")
            current_storage = local_storage_list[index] if index < len(local_storage_list) else None

            context = browser.new_context(storage_state=current_storage, viewport={"width": 1920, "height": 1080}, user_agent="Mozilla/5.0 Chrome/128.0.0.0")
            page = context.new_page()

            try:
                # 1. 登录校验
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
                
                # 2. 签到逻辑 (登录后立即执行)
                if check_session_by_points(page):
                    print(f"✅ 账号 {email} 在线，准备签到")
                    page.evaluate('fetch("https://glados.cloud/api/user/checkin", {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({token:"glados.cloud"})})')
                    tg_send(f"🎉 账号 {email} 签到完成")
                    final_storage_list.append(context.storage_state())
                else:
                    print(f"❌ 账号 {email} 状态异常，跳过保存")
                    # 即使失败也保留旧状态避免列表错位
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
