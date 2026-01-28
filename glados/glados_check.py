import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console"
POINTS_API = "https://glados.cloud/api/user/points"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

EMAIL = os.environ["GLADOS_EMAIL"]
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
REPO_TOKEN = os.environ["REPO_TOKEN"]

def die(msg):
    print(f"[FATAL] {msg}")
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send( text):
    print(f"[STEP] 📤 尝试发送 Telegram 消息")
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": text
    }, timeout=10)

    print(f"[STEP] 📬 TG HTTP 状态码: {resp.status_code}")
    print(f"[STEP] 📬 TG 返回内容: {resp.text}")

    if resp.status_code != 200:
        die("❌ Telegram 消息发送失败（见上方返回）")

def tg_wait_code( timeout=300):
    print(f"[STEP] 📡 开始轮询 Telegram 验证码")
    tg_send(
        "📨 GLaDOS 登录验证码已发送\n"
        "请回复指令：\n"
        "/code 123456"
    )

    offset = None
    start = time.time()

    while time.time() - start < timeout:
        # 获取更新
        resp = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10},
            timeout=15
        ).json()

        print(f"[STEP] 📥 TG updates raw: {resp}")

        for item in resp.get("result", []):
            # 更新 offset, 避免重复处理相同的消息
            offset = item["update_id"] + 1
            msg = item.get("message", {}).get("text", "")

            if msg.startswith("/code"):
                code = msg.replace("/code", "").strip()
                if code.isdigit():
                    print(f"[STEP] ✅ 收到验证码: {code}")
                    return code

        print(f"[STEP] ⌛ 仍未收到验证码，5 秒后重试")
        time.sleep(5)

    die("⛔ Telegram 验证码等待超时")

def update_secret(name, value):
    print(f"[STEP] 更新 GitHub Secret: {name}")
    tg_send("🔐 更新 GitHub Secret：GLADOS_LOCAL")
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

def inject_local(page, local_data):
    print("[STEP] 注入 localStorage")
    page.add_init_script(
        f"""() => {{
            const data = {json.dumps(local_data)};
            for (const k in data) localStorage.setItem(k, data[k]);
        }}"""
    )
    print(f"[OK] 注入 localStorage 条目数: {len(local_data)}")

# 🔥 新的 session 校验逻辑（points API）
def check_session_by_points(page):
    print("[STEP] 使用 /api/user/points 校验 session")
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
        if result and isinstance(result, dict):
            print(f"[OK] session 有效，points 返回: {result}")
            return True
        print("[RESULT] session 无效（无返回数据）")
        return False
    except Exception as e:
        print(f"[ERROR] points 校验异常: {e}")
        return False

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
            page.goto(CONSOLE_URL)
            page.wait_for_load_state("networkidle")
            time.sleep(10)
            if check_session_by_points(page):
                tg_send("✅ 使用已有 session 成功")
            else:
                tg_send("❌ session 无效，重新登录")
                login_flow(page)
        else:
            print("[INFO] 未检测到 GLADOS_LOCAL")
            tg_send("❌ 无 session，执行登录")
            login_flow(page)

        print("[STEP] 最终 session 校验")
        if not check_session_by_points(page):
            save_screenshot(page, "login_failed")
            die("❌ 登录失败，points 校验未通过")

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
