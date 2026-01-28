import os
import time
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---- 强制 stdout 实时输出 ----
sys.stdout.reconfigure(line_buffering=True)

EMAIL = os.getenv("GLADOS_EMAIL")
PASSWORD = os.getenv("GLADOS_PASSWORD")

if not EMAIL or not PASSWORD:
    raise RuntimeError("缺少环境变量 GLADOS_EMAIL / GLADOS_PASSWORD")


class GLaDOSAuto:

    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def run(self):
        self.log("STEP 1: 启动浏览器")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                self.login(page)
                self.checkin(page)
                self.log("✅ 全流程完成")
            finally:
                browser.close()

    # ---------------- 登录 ----------------
    def login(self, page):
        self.log("STEP 2: 打开登录页")
        page.goto("https://glados.network/login", timeout=60000)

        self.log("STEP 3: 输入邮箱 & 密码")
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", PASSWORD)

        self.log("STEP 4: 点击登录")
        page.click("button[type=submit]")

        time.sleep(3)

        self.log(f"当前 URL: {page.url}")

        # ✅ 正确判断：localStorage token
        token = page.evaluate("""
            () => localStorage.getItem("token") 
               || localStorage.getItem("user")
        """)

        if not token:
            self.dump_debug(page, "login_failed")
            raise RuntimeError("登录失败：localStorage 未生成 token")

        self.log("✅ 登录成功（检测到 localStorage token）")

    # ---------------- 签到 ----------------
    def checkin(self, page):
        self.log("STEP 5: 打开签到页面")
        page.goto("https://glados.network/console/checkin", timeout=60000)

        try:
            self.log("STEP 6: 等待签到按钮")
            page.wait_for_selector("button", timeout=10000)
        except PlaywrightTimeout:
            self.dump_debug(page, "checkin_page_timeout")
            raise RuntimeError("签到页加载失败")

        text = page.inner_text("body")

        if "Checked" in text or "已签到" in text:
            self.log("🎉 今日已签到")
            return

        self.log("STEP 7: 点击签到按钮")
        page.click("button")

        time.sleep(2)

        self.log("STEP 8: 校验签到结果")
        text = page.inner_text("body")

        if "success" in text.lower() or "已签到" in text:
            self.log("🎉 签到成功")
        else:
            self.dump_debug(page, "checkin_failed")
            raise RuntimeError("签到失败")

    # ---------------- Debug dump ----------------
    def dump_debug(self, page, name):
        self.log(f"❌ 失败，开始 dump 调试信息: {name}")

        html_path = f"{name}.html"
        png_path = f"{name}.png"

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())

        page.screenshot(path=png_path)

        self.log(f"已保存 {html_path}")
        self.log(f"已保存 {png_path}")


if __name__ == "__main__":
    GLaDOSAuto().run()
