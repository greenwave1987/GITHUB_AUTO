import os
import time
import sys
import json
import base64
import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")
REPO_TOKEN = os.getenv("REPO_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

def die(msg):
    raise RuntimeError(msg)

for k, v in {
    "GLADOS_EMAIL": EMAIL,
    "TG_BOT_TOKEN": TG_BOT_TOKEN,
    "TG_CHAT_ID": TG_CHAT_ID,
    "REPO_TOKEN": REPO_TOKEN,
    "GITHUB_REPOSITORY": GITHUB_REPOSITORY,
}.items():
    if not v:
        die(f"❌ 缺少环境变量 {k}")

class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------------- Telegram ----------------
    def tg_send(self, text):
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text},
            timeout=10
        )
        if r.status_code != 200:
            die("❌ Telegram 消息发送失败")

    def tg_wait_code(self, timeout=300):
        notify_ts = int(time.time())

        self.tg_send(
            "📨 GLaDOS 登录验证码已发送\n"
            "请回复指令：\n"
            "/code 123456"
        )

        offset = None
        start = time.time()

        while time.time() - start < timeout:
            r = requests.get(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            ).json()

            self.log(f"📥 TG updates raw: {r}")

            for item in r.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                text = msg.get("text", "")
                msg_time = msg.get("date", 0)

                if msg_time <= notify_ts:
                    continue

                if text.startswith("/code"):
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到【新】验证码: {code}")
                        return code

            self.log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)

        die("⛔ 等待 Telegram 验证码超时")

    # ---------------- GitHub Secret ----------------
    def save_secret(self, name, value):
        owner, repo = GITHUB_REPOSITORY.split("/")
        api = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets"
        headers = {
            "Authorization": f"Bearer {REPO_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

        r = requests.get(f"{api}/public-key", headers=headers)
        if r.status_code != 200:
            die("❌ 获取 GitHub public-key 失败")

        key = r.json()["key"]
        key_id = r.json()["key_id"]

        from nacl import public, encoding
        pk = public.PublicKey(key.encode(), encoding.Base64Encoder())
        sealed = public.SealedBox(pk).encrypt(value.encode())
        encrypted = base64.b64encode(sealed).decode()

        r = requests.put(
            f"{api}/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id}
        )

        if r.status_code not in (201, 204):
            die(f"❌ 写入 Secret 失败: {r.text}")

        self.log("🔐 GLADOS_LOCAL 已更新到 GitHub Secrets")

    # ---------------- Playwright ----------------
    def inject_local(self, page):
        raw = base64.b64decode(GLADOS_LOCAL).decode()
        data = json.loads(raw)

        page.add_init_script("""
            (data) => {
                for (const [k, v] of Object.entries(data)) {
                    localStorage.setItem(k, v);
                }
            }
        """, data)

    def export_and_save_local(self, page):
        self.log("💾 导出并保存最新 localStorage")
        raw = page.evaluate("() => JSON.stringify(localStorage)")
        encoded = base64.b64encode(raw.encode()).decode()
        self.save_secret("GLADOS_LOCAL", encoded)

    # ---------------- 主流程 ----------------
    def run(self):
        self.log("STEP 1: 启动 Playwright")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                if GLADOS_LOCAL:
                    self.log("♻️ 尝试使用缓存登录")
                    self.inject_local(page)
                    page.goto("https://glados.cloud/console", timeout=60000)
                    time.sleep(3)

                    if page.url.startswith("https://glados.cloud/console"):
                        self.log("✅ 缓存登录成功")
                        self.export_and_save_local(page)
                        self.checkin(page)
                        return

                    self.log("⚠️ 缓存失效，回退验证码登录")

                self.login_with_code(page)
                self.export_and_save_local(page)
                self.checkin(page)

            finally:
                browser.close()

    def login_with_code(self, page):
        self.log("STEP 2: 打开登录页")
        page.goto("https://glados.cloud/login", timeout=60000)

        self.log("STEP 3: 输入邮箱")
        page.fill("input#email", EMAIL)

        self.log("STEP 4: 点击 Get Code")
        page.click("button:has-text('Get Code')")
        time.sleep(3)

        code = self.tg_wait_code()

        self.log("STEP 5: 填入验证码")
        page.fill("input#mailcode", code)

        self.log("STEP 6: 点击 Login")
        page.click("button:has-text('Login')")
        page.wait_for_url("**/console", timeout=30000)

        self.log("✅ 验证码登录成功")

    def checkin(self, page):
        self.log("🚀 执行签到")
        result = page.evaluate("""
            () => fetch("https://glados.cloud/api/user/checkin", {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({ token: "glados.cloud" }),
                credentials: "include"
            }).then(r => r.json())
        """)
        self.log(f"📊 签到结果: {result}")

if __name__ == "__main__":
    GLaDOSAuto().run()
