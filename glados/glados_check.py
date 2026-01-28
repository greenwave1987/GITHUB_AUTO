import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

EMAIL = os.environ["GLADOS_EMAIL"]
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
REPO_TOKEN = os.environ["REPO_TOKEN"]

def die(msg):
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send(text):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text}
    )

def tg_wait_code():
    tg_send("📩 请回复 **邮箱验证码**")
    offset = None
    while True:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 60}
        ).json()
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            if "text" in u.get("message", {}):
                code = u["message"]["text"].strip()
                if code.isdigit():
                    return code
        time.sleep(2)

def update_secret(name, value):
    tg_send("🔐 更新 GitHub Secret：GLADOS_LOCAL")
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/secrets/{name}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    requests.put(api, headers=headers, json={"encrypted_value": value, "key_id": "dummy"})

def inject_local(page, local_data):
    page.add_init_script(
        f"""() => {{
            const data = {json.dumps(local_data)};
            for (const k in data) localStorage.setItem(k, data[k]);
        }}"""
    )

def check_console_valid(page):
    page.goto(CONSOLE_URL, timeout=30000)
    page.wait_for_timeout(3000)
    return "当前套餐是" in page.content()

def save_screenshot(page, name):
    path = f"/tmp/{name}.png"
    page.screenshot(path=path, full_page=True)
    with open(path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT_ID},
            files={"photo": f}
        )

def login_flow(page):
    page.goto(LOGIN_URL)
    page.fill("#email", EMAIL)

    tg_send("⚠️ 即将发送邮箱验证码")
    page.click("button:has-text('Get Code')")

    code = tg_wait_code()
    page.fill("#mailcode", code)
    page.click("button[type=submit]")

    page.wait_for_load_state("networkidle")
    time.sleep(3)

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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # STEP 1: 尝试已有 localStorage
        local_raw = os.environ.get("GLADOS_LOCAL")
        if local_raw:
            inject_local(page, json.loads(local_raw))
            if check_console_valid(page):
                tg_send("✅ 使用已有 session 成功")
            else:
                tg_send("❌ session 无效，重新登录")
                login_flow(page)
        else:
            tg_send("❌ 无 session，执行登录")
            login_flow(page)

        if not check_console_valid(page):
            save_screenshot(page, "login_failed")
            die("❌ 登录失败，未进入控制台")

        save_screenshot(page, "login_success")

        # 保存 localStorage
        local_data = page.evaluate("() => Object.assign({}, localStorage)")
        update_secret("GLADOS_LOCAL", json.dumps(local_data))

        # 签到
        do_checkin(page)
        tg_send("🎉 GLaDOS 签到完成")

        browser.close()

if __name__ == "__main__":
    run()
