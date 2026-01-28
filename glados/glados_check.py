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
    print(f"[FATAL] {msg}")
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send(text):
    print(f"[TG] {text}")
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text}
    )

def tg_wait_code():
    print("[STEP] 等待 TG 输入邮箱验证码")
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
                print(f"[TG] 收到消息: {code}")
                if code.isdigit():
                    print("[OK] 验证码格式正确")
                    return code
        time.sleep(2)

def update_secret(name, value):
    print(f"[STEP] 更新 GitHub Secret: {name}")
    tg_send("🔐 更新 GitHub Secret：GLADOS_LOCAL")
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/secrets/{name}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    r = requests.put(api, headers=headers, json={"encrypted_value": value, "key_id": "dummy"})
    print(f"[RESULT] Secret 更新状态码: {r.status_code}")

def inject_local(page, local_data):
    print("[STEP] 注入 localStorage")
    page.add_init_script(
        f"""() => {{
            const data = {json.dumps(local_data)};
            for (const k in data) localStorage.setItem(k, data[k]);
        }}"""
    )
    print(f"[OK] 注入 localStorage 条目数: {len(local_data)}")

def check_console_valid(page):
    print("[STEP] 访问控制台校验 session")
    page.goto(CONSOLE_URL, timeout=30000)
    page.wait_for_timeout(30000)
    ok = "当前套餐是" in page.content()
    print(f"[RESULT] 控制台校验结果: {'有效' if ok else '无效'}")
    return ok

def save_screenshot(page, name):
    print(f"[STEP] 保存截图: {name}")
    path = f"/tmp/{name}.png"
    page.screenshot(path=path, full_page=True)
    with open(path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT_ID},
            files={"photo": f}
        )
    print(f"[OK] 截图已发送 TG: {name}")

def login_flow(page):
    print("[STEP] 打开登录页面")
    page.goto(LOGIN_URL)

    print("[STEP] 输入邮箱")
    page.fill("#email", EMAIL)

    tg_send("⚠️ 即将发送邮箱验证码")
    print("[STEP] 点击 Get Code")
    page.click("button:has-text('Get Code')")

    code = tg_wait_code()
    print(f"[STEP] 输入验证码: {code}")
    page.fill("#mailcode", code)

    print("[STEP] 点击 Login")
    page.click("button[type=submit]")

    print("[WAIT] 等待登录完成")
    page.wait_for_load_state("networkidle")
    time.sleep(3)

def do_checkin(page):
    print("[STEP] 执行签到请求")
    page.evaluate(
        """() => fetch("https://glados.cloud/api/user/checkin", {
            method: "POST",
            credentials: "include",
            headers: {"content-type": "application/json"},
            body: JSON.stringify({token: "glados.cloud"})
        })"""
    )
    print("[OK] 签到请求已发送")

def run():
    print("====== GLaDOS 自动签到开始 ======")
    with sync_playwright() as p:
        print("[STEP 1] 启动 Playwright")
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        local_raw = os.environ.get("GLADOS_LOCAL")
        if local_raw:
            print("[INFO] 检测到 GLADOS_LOCAL，尝试复用 session")
            inject_local(page, json.loads(local_raw))
            if check_console_valid(page):
                tg_send("✅ 使用已有 session 成功")
            else:
                tg_send("❌ session 无效，重新登录")
                login_flow(page)
        else:
            print("[INFO] 未检测到 GLADOS_LOCAL")
            tg_send("❌ 无 session，执行登录")
            login_flow(page)

        print("[STEP] 最终校验控制台")
        if not check_console_valid(page):
            save_screenshot(page, "login_failed")
            die("❌ 登录失败，未进入控制台")

        save_screenshot(page, "login_success")

        print("[STEP] 读取 localStorage")
        local_data = page.evaluate("() => Object.assign({}, localStorage)")
        print(f"[OK] localStorage 条目数: {len(local_data)}")

        update_secret("GLADOS_LOCAL", json.dumps(local_data))

        do_checkin(page)
        tg_send("🎉 GLaDOS 签到完成")

        browser.close()
        print("====== GLaDOS 自动签到结束 ======")

if __name__ == "__main__":
    run()
