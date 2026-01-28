import os
import time
import json
import base64
import requests
from playwright.sync_api import sync_playwright, TimeoutError

GLADOS_EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
REPO_TOKEN = os.getenv("REPO_TOKEN")
REPO = os.getenv("REPO")
SECRET_NAME = "GLADOS_LOCAL"

def die(msg):
    send_tg(msg)
    raise RuntimeError(msg)

def send_tg(text, photo=None):
    if photo:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT_ID, "caption": text},
            files={"photo": open(photo, "rb")}
        )
    else:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": text}
        )

def wait_tg_code(timeout=300):
    send_tg("📩 请发送验证码：/code 123456")
    offset = None
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10}
        ).json()
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message", {}).get("text", "")
            if msg.startswith("/code"):
                return msg.split()[-1]
        time.sleep(2)
    die("❌ 等待邮箱验证码超时")

def update_secret(value_b64):
    url = f"https://api.github.com/repos/{REPO}/actions/secrets/{SECRET_NAME}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    r = requests.put(url, headers=headers, json={"encrypted_value": value_b64, "key_id": "dummy"})
    if r.status_code not in (201, 204):
        die(f"❌ Secret 回写失败 {r.status_code}")

def has_valid_cookie(context):
    for c in context.cookies():
        if c["name"] == "koa:sess":
            return True
    return False

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context()

        # 注入 session
        raw = os.getenv("GLADOS_LOCAL")
        if raw:
            try:
                state = json.loads(base64.b64decode(raw).decode())
                context.add_cookies(state.get("cookies", []))
                context.set_storage_state(state)
                print("♻️ 注入 Secret session")
            except Exception:
                print("⚠️ Secret 解码失败")

        page = context.new_page()
        page.goto("https://glados.cloud/console", timeout=60000)
        time.sleep(3)

        if not has_valid_cookie(context):
            print("🔐 session 无效，执行登录")
            send_tg("🔐 GLaDOS 需要登录，准备发送邮箱验证码")

            page.goto("https://glados.cloud/login", timeout=60000)

            page.wait_for_selector("input[type=email]")
            page.fill("input[type=email]", GLADOS_EMAIL)

            # 点击发送邮箱验证码
            page.click("button:has-text('Send Code')")
            send_tg("📨 已点击【发送邮箱验证码】，请查收邮箱")

            code = wait_tg_code()

            page.wait_for_selector("input[type=number]")
            page.fill("input[type=number]", code)
            page.click("button:has-text('Login')")

            time.sleep(5)

        # 登录后校验 cookie
        if not has_valid_cookie(context):
            page.screenshot(path="login_fail.png", full_page=True)
            send_tg("❌ 登录失败", "login_fail.png")
            die("登录失败")

        page.screenshot(path="login_ok.png", full_page=True)
        send_tg("✅ 登录成功", "login_ok.png")

        # 保存 storage_state
        state = context.storage_state()
        state_b64 = base64.b64encode(json.dumps(state).encode()).decode()
        update_secret(state_b64)

        # 签到
        page.goto("https://glados.cloud/api/user/checkin")
        resp = page.evaluate("""
            () => fetch("/api/user/checkin", {
                method: "POST",
                headers: {"content-type": "application/json"},
                body: JSON.stringify({token: "glados.cloud"})
            }).then(r => r.json())
        """)

        msg = f"checkin:{time.strftime('%Y-%m-%d')} | 获得 {resp.get('points', 0)} | 总积分 {resp.get('balance', 0)}"
        send_tg(msg)

        browser.close()

if __name__ == "__main__":
    run()
