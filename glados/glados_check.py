import os
import json
import time
import requests
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

def die(msg):
    print(f"[FATAL] {msg}")
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send(text):
    print(f"[STEP] 📤 尝试发送 Telegram 消息")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": text
    }, timeout=10)
    if resp.status_code != 200:
        print(f"[ERROR] TG 返回内容: {resp.text}")

def tg_wait_code(email, send_time, timeout=300):
    """
    send_time: 点击获取验证码时的时间戳（秒）
    """
    print(f"[STEP] 📡 开始轮询 Telegram 验证码 (仅接收 {send_time} 之后的最新消息)")
    tg_send(
        f"📨 GLaDOS 验证码已发送\n"
        f"账号: {email}\n"
        f"请回复：/code 123456"
    )

    offset = None
    start_wait = time.time()

    while time.time() - start_wait < timeout:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            ).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                message = item.get("message", {})
                msg_text = message.get("text", "")
                msg_date = message.get("date", 0) # 获取消息发送的时间戳

                if msg_text.startswith("/code"):
                    # 关键逻辑：判断消息时间是否在点击按钮之后
                    if msg_date >= int(send_time):
                        code = msg_text.replace("/code", "").strip()
                        if code.isdigit():
                            print(f"[STEP] ✅ 收到最新验证码: {code} (消息时间:{msg_date} >= 请求时间:{int(send_time)})")
                            return code
                    else:
                        print(f"[SKIP] 忽略历史验证码: {msg_text} (消息时间:{msg_date} < 请求时间:{int(send_time)})")
        except Exception as e:
            print(f"[ERROR] 获取 TG 更新失败: {e}")

        time.sleep(5)

    die(f"⛔ {email} Telegram 验证码等待超时")

def update_secret(name, value):
    print(f"[STEP] 更新 GitHub Secret: {name}")
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/secrets/{name}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    r = requests.put(
        api,
        headers=headers,
        json={"encrypted_value": value, "key_id": "dummy"}
    )
    print(f"[RESULT] Secret 更新状态码: {r.status_code}")

def check_session_by_points(page):
    try:
        result = page.evaluate(
            f"""async () => {{
                const r = await fetch("{POINTS_API}", {{
                    method: "GET",
                    credentials: "include"
                }});
                if (!r.ok) return null;
                return await r.json();
            }}"""
        )
        return result and isinstance(result, dict) and result.get('code') == 0
    except:
        return False

def login_flow(page, email):
    page.goto(LOGIN_URL)
    page.fill("#email", email)

    # 记录点击前的准确时间戳
    click_time = time.time() 
    print(f"[STEP] 账号 {email} 点击 Get Code，记录时间点: {int(click_time)}")
    page.click("button:has-text('Get Code')")

    # 将时间戳传递给等待函数
    code = tg_wait_code(email, click_time)

    page.fill("#mailcode", code)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    time.sleep(5)

def do_checkin(page):
    page.evaluate(
        """() => fetch("https://glados.cloud/api/user/checkin", {
            method: "POST",
            credentials: "include",
            headers: {"content-type": "application/json"},
            body: JSON.stringify({token: "glados.cloud"})
        })"""
    )

def run():
    print("====== GLaDOS 多账户自动签到开始 ======")
    local_storage_list = []
    local_raw = os.environ.get("GLADOS_LOCAL")
    if local_raw:
        try:
            local_storage_list = json.loads(local_raw)
            if not isinstance(local_storage_list, list):
                local_storage_list = [local_storage_list]
        except:
            local_storage_list = []

    final_storage_list = []

    with sync_playwright() as p:
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--exclude-switches=enable-automation",
            ]
        }
        browser = p.chromium.launch(**launch_args)

        for index, email in enumerate(EMAILS):
            email = email.strip()
            print(f"\n>>> 处理账号: {email}")
            
            current_storage = local_storage_list[index] if index < len(local_storage_list) else None

            context = browser.new_context(
                storage_state=current_storage,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 Chrome/128.0.0.0"
            )
            page = context.new_page()

            try:
                is_logged_in = False
                if current_storage:
                    page.goto(CONSOLE_URL)
                    page.wait_for_load_state("networkidle", timeout=60000)
                    time.sleep(3)
                    if check_session_by_points(page):
                        tg_send(f"✅ 账号 {email} Session 有效")
                        is_logged_in = True

                if not is_logged_in:
                    login_flow(page, email)
                    if not check_session_by_points(page):
                        print(f"❌ 账号 {email} 登录后校验失败")
                        continue
                
                do_checkin(page)
                tg_send(f"🎉 账号 {email} 签到完成")
                final_storage_list.append(context.storage_state())

            except Exception as e:
                print(f"[ERROR] {email} 异常: {e}")
            finally:
                context.close()

        browser.close()

    if final_storage_list:
        update_secret("GLADOS_LOCAL", json.dumps(final_storage_list))
    print("====== GLaDOS 自动签到结束 ======")

if __name__ == "__main__":
    run()
