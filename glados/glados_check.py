import os
import json
import time
import base64
import re
import requests
from playwright.sync_api import sync_playwright

GLADOS_URL = "https://glados.cloud"
TG_API = "https://api.telegram.org"

def die(msg):
    raise RuntimeError(msg)

def log(msg):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TG_BOT_TOKEN")
        self.chat_id = os.getenv("TG_CHAT_ID")
        if not self.token or not self.chat_id:
            die("❌ 缺少 TG_BOT_TOKEN / TG_CHAT_ID")

        self.base = f"{TG_API}/bot{self.token}"
        self.offset = None

    def send(self, text):
        requests.post(f"{self.base}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": text
        })

    def get_code(self, max_wait=150):
        start = time.time()
        while time.time() - start < max_wait:
            params = {"timeout": 10}
            if self.offset is not None:
                params["offset"] = self.offset + 1

            r = requests.get(f"{self.base}/getUpdates", params=params).json()
            log(f"📥 TG updates raw: {r}")

            for upd in r.get("result", []):
                self.offset = upd["update_id"]
                msg = upd.get("message", {}).get("text", "")
                m = re.search(r"/code\s+(\d{4,8})", msg)
                if m:
                    return m.group(1)

            log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)

        die("❌ 超时未收到 TG 验证码")

class GLaDOSAuto:
    def __init__(self):
        self.email = os.getenv("GLADOS_EMAIL")
        if not self.email:
            die("❌ 缺少 GLADOS_EMAIL")

        self.local_env = os.getenv("GLADOS_LOCAL")
        self.tg = TelegramBot()

    # ✅ 关键修复点：不再给 add_init_script 传第二个参数
    def inject_local(self, context):
        data = json.loads(base64.b64decode(self.local_env).decode())
        js = f"""
            (() => {{
                const data = {json.dumps(data)};
                localStorage.clear();
                for (const k in data) {{
                    localStorage.setItem(k, data[k]);
                }}
            }})();
        """
        context.add_init_script(js)

    def dump_local(self, page):
        data = page.evaluate("""
            () => {
                const o = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    o[k] = localStorage.getItem(k);
                }
                return o;
            }
        """)
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        print(f"::set-env name=GLADOS_LOCAL::{encoded}")

    def login_with_code(self, page):
        log("STEP 2: 打开登录页")
        page.goto(f"{GLADOS_URL}/login")

        log("STEP 3: 输入邮箱")
        page.fill("input[type=email]", self.email)

        log("STEP 4: 点击 Get Code")
        page.click("text=Get Code")

        log("📨 GLaDOS 登录验证码已发送")
        self.tg.send(
            "📨 GLaDOS 登录验证码已发送\n"
            "请回复指令：\n"
            "/code 123456"
        )

        code = self.tg.get_code()
        log(f"✅ 收到【新】验证码: {code}")

        log("STEP 5: 填入验证码")
        page.fill("input[type=number]", code)

        log("STEP 6: 点击 Login")
        page.click("text=Login")
        page.wait_for_timeout(3000)

    def checkin(self, page):
        log("🚀 执行签到")
        result = page.evaluate("""
            () => fetch("https://glados.cloud/api/user/checkin", {
                method: "POST",
                credentials: "include",
                headers: {
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json;charset=UTF-8"
                },
                body: JSON.stringify({ token: "glados.cloud" })
            }).then(r => r.json())
        """)
        log(f"📊 签到返回: {result}")

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            log("STEP 1: 启动 Playwright")

            if self.local_env:
                log("♻️ 尝试使用缓存登录")
                self.inject_local(context)

            page = context.new_page()
            page.goto(GLADOS_URL)

            if not self.local_env:
                self.login_with_code(page)

            if not page.evaluate("() => localStorage.length > 0"):
                die("❌ 登录失败：localStorage 未生成")

            self.dump_local(page)
            self.checkin(page)
            browser.close()

if __name__ == "__main__":
    GLaDOSAuto().run()
