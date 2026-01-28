import os
import time
import sys
from playwright.sync_api import sync_playwright

# ===== 实时日志 =====
sys.stdout.reconfigure(line_buffering=True)

EMAIL = os.getenv("GLADOS_EMAIL")

if not EMAIL:
    raise RuntimeError("缺少环境变量 GLADOS_EMAIL")


class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def run(self):
        self.log("STEP 1: 启动 Playwright")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                self.login_request_code(page)
                self.log("⏸ 已发送验证码，等待下一步（TG 接入）")
            finally:
                browser.close()

    def login_request_code(self, page):
        self.log("STEP 2: 打开登录页")
        page.goto("https://glados.cloud/login", timeout=60000)

        self.log("STEP 3: 输入邮箱")
        page.fill("input#email", EMAIL)

        self.log("STEP 4: 点击 Get Code")
        page.click("button:has-text('Get Code')")

        time.sleep(3)

        self.log("✅ 验证码已请求（请检查邮箱）")

        # 调试用：保存当前页面状态
        self.dump_debug(page, "after_get_code")

    def dump_debug(self, page, name):
        self.log(f"📸 Dump debug: {name}")
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=f"{name}.png")


if __name__ == "__main__":
    GLaDOSAuto().run()
