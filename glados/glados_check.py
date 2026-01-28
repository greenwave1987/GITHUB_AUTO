import os
import time
import sys
import requests
from playwright.sync_api import sync_playwright

# ===== 实时日志 =====
sys.stdout.reconfigure(line_buffering=True)

EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not EMAIL:
    raise RuntimeError("缺少 GLADOS_EMAIL")
if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise RuntimeError("缺少 TG_BOT_TOKEN / TG_CHAT_ID")


class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------- Telegram ----------
    def tg_send(self, text):
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text
        })

    def tg_wait_code(self, timeout=300):
        self.log("📡 开始轮询 Telegram 验证码")
        self.tg_send("📨 GLaDOS 登录验证码已发送\n请回复：\n/code 123456")

        offset = None
        start = time.time()

        while time.time() - start < timeout:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10}
            ).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {}).get("text", "")

                if msg.startswith("/code"):
                    code = msg.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到验证码: {code}")
                        return code

            self.log("⌛ 等待 TG 验证码中…")
            time.sleep(5)

        raise RuntimeError("⛔ Telegram 验证码等待超时")

    # ---------- 主流程 ----------
    def run(self):
        self.log("STEP 1: 启动 Playwright")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                self.request_code(page)
                code = self.tg_wait_code()
                self.submit_code(page, code)
                self.log("🎉 登录流程完成（已验证）")
            finally:
                browser.close()

    def request_code(self, page):
        self.log("STEP 2: 打开登录页")
        page.goto("https://glados.cloud/login", timeout=60000)

        self.log("STEP 3: 输入邮箱")
        page.fill("input#email", EMAIL)

        self.log("STEP 4: 点击 Get Code")
        page.click("button:has-text('Get Code')")

        time.sleep(3)
        self.log("✅ 验证码已发送到邮箱")

    def submit_code(self, page, code):
        self.log("STEP 5: 填入验证码")
        page.fill("input#mailcode", code)

        self.log("STEP 6: 点击 Login")
        page.click("button:has-text('Login')")

        time.sleep(3)

        token = page.evaluate("""
            () => localStorage.getItem("token")
               || localStorage.getItem("user")
        """)

        if not token:
            self.dump_debug(page, "login_failed")
            raise RuntimeError("❌ 登录失败：未生成 localStorage")

        self.log("✅ 登录成功（localStorage 已生成）")

    def dump_debug(self, page, name):
        self.log(f"📸 Dump debug: {name}")
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=f"{name}.png")


if __name__ == "__main__":
    GLaDOSAuto().run()
