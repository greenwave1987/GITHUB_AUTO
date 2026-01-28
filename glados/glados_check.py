import os
import json
import time
from playwright.sync_api import sync_playwright

USER = "user1"
STATE_FILE = f"state_{USER}.json"
GLADOS_URL = "https://glados.cloud"

new_sessions = {}


class GLaDOSAuto:
    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # 1️⃣ 使用缓存 / 新建
            if os.path.exists(STATE_FILE):
                context = browser.new_context(storage_state=STATE_FILE)
                print("♻️ 使用缓存 session")
            else:
                context = browser.new_context()
                print("🆕 新建 session")

            page = context.new_page()
            page.goto(GLADOS_URL)
            page.wait_for_load_state("networkidle")

            # 2️⃣ 登录判断
            if not self.is_logged_in(page):
                self.login(page)

            if not self.is_logged_in(page):
                raise RuntimeError("❌ 登录失败")

            print("✅ 登录确认")

            # 3️⃣ 签到（重点）
            self.checkin(context)

            # 4️⃣ 保存最新 session（不管新旧）
            state = context.storage_state()
            new_sessions[USER] = state

            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)

            print("💾 已更新 storage_state")

            browser.close()

    def is_logged_in(self, page):
        try:
            page.goto(f"{GLADOS_URL}/dashboard", timeout=15000)
            page.wait_for_selector("text=Dashboard", timeout=5000)
            return True
        except Exception:
            return False

    def login(self, page):
        print("🔐 执行登录")
        page.goto(f"{GLADOS_URL}/login")
        page.fill("input[type=email]", os.getenv("GLADOS_EMAIL"))
        page.click("button:has-text('Send')")

        code = input("输入验证码: ")
        page.fill("input[type=text]", code)
        page.click("button:has-text('Login')")

        page.wait_for_load_state("networkidle")
        time.sleep(2)

    def checkin(self, context):
        print("🚀 执行签到")

        resp = context.request.post(
            "https://glados.cloud/api/user/checkin",
            data={"token": "glados.cloud"},
            headers={
                "content-type": "application/json;charset=UTF-8",
                "accept": "application/json, text/plain, */*",
            }
        )

        data = resp.json()
        print("📊 签到返回:", data)

        if data.get("code") not in (0, 1):
            raise RuntimeError("❌ 签到失败")


if __name__ == "__main__":
    GLaDOSAuto().run()
