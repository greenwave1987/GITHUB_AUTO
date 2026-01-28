import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

# ---------- 配置与常量 ----------
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

def tg_send(text):
    print(f"[STEP] 📤 尝试发送 Telegram 消息")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage" # 修正了变量名错误
    resp = requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": text
    }, timeout=10)

    print(f"[STEP] 📬 TG HTTP 状态码: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[ERROR] TG 返回内容: {resp.text}")
        # 不在这里调 die，防止死循环

def tg_wait_code(timeout=300):
    print(f"[STEP] 📡 开始轮询 Telegram 验证码")
    tg_send(
        "📨 GLaDOS 登录验证码已发送\n"
        "请回复指令：\n"
        "/code 123456"
    )

    offset = None
    start = time.time()

    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            ).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {}).get("text", "")

                if msg.startswith("/code"):
                    code = msg.replace("/code", "").strip()
                    if code.isdigit():
                        print(f"[STEP] ✅ 收到验证码: {code}")
                        return code
        except Exception as e:
            print(f"[ERROR] 获取 TG 更新失败: {e}")

        time.sleep(5)

    die("⛔ Telegram 验证码等待超时")

def update_secret(name, value):
    print(f"[STEP] 更新 GitHub Secret: {name}")
    tg_send(f"🔐 更新 GitHub Secret：{name}")
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/secrets/{name}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    # 注意：在实际 GitHub Actions 中，更新 Secret 需要先加密。
    # 此处保持原逻辑，但提醒：直接 PUT 可能会因未加密而失败（除非 API 另有配置）
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
        if result and isinstance(result, dict) and result.get('code') == 0:
            print(f"[OK] session 有效，points 返回成功")
            return True
        print(f"[RESULT] session 无效: {result}")
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
    time.sleep(5)

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
        # --- 参考 open_browser 方法修改的启动部分 ---
        print("[STEP] 启动 Playwright 浏览器 (Anti-Fingerprint)")
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
        
        # 模拟真实的浏览器环境
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        # ------------------------------------------

        local_raw = os.environ.get("GLADOS_LOCAL")
        if local_raw:
            print("[INFO] 检测到 GLADOS_LOCAL，尝试复用 session")
            # 在访问页面前注入，或者先访问域名再注入
           
            inject_local(page, json.loads(local_raw))
            page.goto(CONSOLE_URL)
           
            page.wait_for_load_state("networkidle", timeout=60000)
            time.sleep(5)
            if "login" in page.url.lower():
                print(f"当前 url:{page.url}")
                save_screenshot(page, "session_failed")
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

        # 保存最新的 localStorage
        print("[STEP] 读取 localStorage")
        local_data = page.evaluate("() => Object.assign({}, localStorage)")
        update_secret("GLADOS_LOCAL", json.dumps(local_data))

        do_checkin(page)
        tg_send("🎉 GLaDOS 签到完成")

        browser.close()
        print("====== GLaDOS 自动签到结束 ======")

if __name__ == "__main__":
    run()
