import os
import sys
import time
import json
import base64
import requests
from playwright.sync_api import sync_playwright
from nacl import public, encoding

sys.stdout.reconfigure(line_buffering=True)

# ================== 环境变量 ==================
EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")

REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")

# ================== 工具 ==================
def die(msg):
    raise RuntimeError(msg)

def now():
    return time.strftime("%H:%M:%S")

# ================== GitHub Secret 更新器 ==================
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"[{now()}] 🔐 SecretUpdater init: {name}")

    def update(self, value):
        if not REPO or not REPO_TOKEN:
            print(f"[{now()}] ⚠ 未配置 REPO / REPO_TOKEN，跳过 Secret 更新")
            return

        headers = {
            "Authorization": f"token {REPO_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        print(f"[{now()}] 🌐 获取 Secret 公钥")
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
            headers=headers,
            timeout=30
        )
        r.raise_for_status()
        key = r.json()

        print(f"[{now()}] 🔑 加密 Secret")
        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())

        print(f"[{now()}] 📤 回写 Secret: {self.name}")
        r = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={
                "encrypted_value": base64.b64encode(encrypted).decode(),
                "key_id": key["key_id"]
            },
            timeout=30
        )

        print(f"[{now()}] ✅ Secret 更新完成 HTTP {r.status_code}")

# ================== 主逻辑 ==================
class GLaDOSAuto:

    def log(self, msg):
        print(f"[{now()}] {msg}", flush=True)

    # ---------- Telegram ----------
    def tg_send(self, text):
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text
        }, timeout=10)
        self.log(f"📬 TG send HTTP {r.status_code}")

    def tg_wait_code(self, start_ts, timeout=300):
        self.log("📡 等待 Telegram 新验证码")

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
                date = msg.get("date", 0)

                # ❗ 只接受「发送提示消息之后」的新验证码
                if date <= start_ts:
                    continue

                if text.startswith("/code"):
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到【新】验证码: {code}")
                        return code

            self.log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)

        die("⛔ Telegram 验证码等待超时")

    # ---------- localStorage ----------
    def inject_local(self, context, encoded):
        self.log("♻️ 注入 localStorage")
        raw = base64.b64decode(encoded).decode()
        data = json.loads(raw)

        script = f"""
            () => {{
                const data = {json.dumps(data)};
                for (const k in data) {{
                    localStorage.setItem(k, data[k]);
                }}
            }}
        """
        context.add_init_script(script)

    def dump_local(self, page):
        self.log("💾 导出 localStorage")
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

        raw = json.dumps(data, ensure_ascii=False)
        return base64.b64encode(raw.encode()).decode()

    # ---------- 状态判断 ----------
    def is_logged_in(self, page):
        res = page.evaluate("""
            () => fetch("https://glados.cloud/api/user/profile", {
                credentials: "include"
            }).then(r => r.json())
        """)
        self.log(f"🔍 登录态检测: {res}")
        return res.get("code") == 0

    # ---------- 登录 ----------
    def login_with_code(self, page):
        self.log("STEP: 打开登录页")
        page.goto("https://glados.cloud/login", timeout=60000)

        self.log("STEP: 输入邮箱")
        page.fill("input#email", EMAIL)

        self.log("STEP: 点击 Get Code")
        page.click("button:has-text('Get Code')")
        time.sleep(2)

        ts = int(time.time())
        self.tg_send(
            "📨 GLaDOS 登录验证码已发送\n"
            "请回复指令：\n"
            "/code 123456"
        )

        code = self.tg_wait_code(ts)

        self.log("STEP: 填入验证码")
        page.fill("input#mailcode", code)

        self.log("STEP: 点击 Login")
        page.click("button:has-text('Login')")
        time.sleep(3)

    # ---------- 签到 ----------
    def checkin(self, page):
        self.log("🚀 执行签到")
        res = page.evaluate("""
            () => fetch("https://glados.cloud/api/user/checkin", {
                method: "POST",
                headers: {
                    "content-type": "application/json;charset=UTF-8"
                },
                body: JSON.stringify({ token: "glados.cloud" }),
                credentials: "include"
            }).then(r => r.json())
        """)
        self.log(f"📊 签到返回: {res}")

    # ---------- 主入口 ----------
    def run(self):
        if not EMAIL:
            die("❌ 缺少 GLADOS_EMAIL")
        if not TG_BOT_TOKEN or not TG_CHAT_ID:
            die("❌ 缺少 TG_BOT_TOKEN / TG_CHAT_ID")

        self.log("STEP 1: 启动 Playwright")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            if GLADOS_LOCAL:
                self.inject_local(context, GLADOS_LOCAL)

            page = context.new_page()
            page.goto("https://glados.cloud/login")

            if not self.is_logged_in(page):
                self.log("🔐 需要重新登录")
                self.login_with_code(page)

            if not self.is_logged_in(page):
                die("❌ 登录失败")

            encoded = self.dump_local(page)
            SecretUpdater("GLADOS_LOCAL").update(encoded)

            self.checkin(page)
            browser.close()

# ================== 启动 ==================
if __name__ == "__main__":
    GLaDOSAuto().run()
