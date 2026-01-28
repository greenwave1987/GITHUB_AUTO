import os
import time
import json
import base64
import requests
from playwright.sync_api import sync_playwright

EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")

def die(msg):
    raise RuntimeError(msg)

class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------- Telegram ----------
    def tg_send(self, text):
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text
        }, timeout=10)

    def tg_wait_code(self, after_ts, timeout=300):
        self.log("📡 等待 Telegram 新验证码")

        offset = None
        start = time.time()

        while time.time() - start < timeout:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            ).json()

            self.log(f"📥 TG updates raw: {resp}")

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                text = msg.get("text", "")
                date = msg.get("date", 0)

                # ⭐ 关键：只接受「发送 Get Code 之后」的消息
                if date <= after_ts:
                    continue

                if text.startswith("/code"):
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到【新】验证码: {code}")
                        return code

            self.log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)

        die("⛔ Telegram 验证码超时")

    # ---------- localStorage ----------
    def inject_local(self, page):
        if not GLADOS_LOCAL:
            return False

        data = json.loads(base64.b64decode(GLADOS_LOCAL).decode())

        page.add_init_script("""
            (data) => {
                for (const k in data) {
                    localStorage.setItem(k, data[k]);
                }
            }
        """, data)

        self.log("♻️ 已注入 GLADOS_LOCAL")
        return True

    def save_local(self, page):
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

        if not data:
            die("❌ localStorage 为空")

        encoded = base64.b64encode(
            json.dumps(data, ensure_ascii=False).encode()
        ).decode()

        self.log("✅ 登录态已生成，请保存到 GLADOS_LOCAL")
        print(encoded)

    # ---------- 主流程 ----------
    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # ① 尝试复用登录态
            used = self.inject_local(page)
            page.goto("https://glados.cloud", timeout=60000)
            time.sleep(3)

            if used and "login" not in page.url.lower():
                self.log("🎉 使用缓存登录成功")
                return

            self.log("➡️ 需要验证码登录")

            # ② 请求验证码
            page.goto("https://glados.cloud/login")
            page.fill("#email", EMAIL)

            send_ts = int(time.time())
            page.click("button:has-text('Get Code')")
            self.log("📨 已请求验证码")

            self.tg_send(
                "📨 GLaDOS 登录验证码已发送\n"
                "请回复：\n"
                "/code 123456"
            )

            # ③ 等验证码
            code = self.tg_wait_code(send_ts)

            # ④ 提交验证码
            page.fill("#mailcode", code)
            page.click("button:has-text('Login')")

            # ⑤ 等 localStorage 写入
            for _ in range(10):
                if page.evaluate("() => localStorage.length") > 0:
                    self.save_local(page)
                    self.log("🎉 登录成功")
                    return
                page.wait_for_timeout(1000)

            die("❌ 登录失败：localStorage 未生成")

if __name__ == "__main__":
    GLaDOSAuto().run()
