import os
import time
import json
import base64
import requests
from playwright.sync_api import sync_playwright
from nacl import public, encoding

EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")

def die(msg):
    raise RuntimeError(msg)

# ================= GitHub Secret =================
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value: str):
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 REPO / REPO_TOKEN，跳过 Secret 回写")
            return

        headers = {
            "Authorization": f"token {REPO_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        r = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
            headers=headers,
            timeout=30
        )
        r.raise_for_status()
        key = r.json()

        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())

        r = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={
                "encrypted_value": base64.b64encode(encrypted).decode(),
                "key_id": key["key_id"]
            },
            timeout=30
        )
        r.raise_for_status()
        print("✅ Secret 更新完成")

# ================= 主逻辑 =================
class GLaDOSAuto:
    # ---------- Telegram ----------
    def tg_send(self, text):
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text},
            timeout=10
        )

    def tg_wait_code(self, since_ts, timeout=300):
        print("📡 等待 Telegram 新验证码")
        offset = None
        start = time.time()

        while time.time() - start < timeout:
            r = requests.get(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=20
            ).json()

            for item in r.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                text = msg.get("text", "")
                date = msg.get("date", 0)

                if date <= since_ts:
                    continue

                if text.startswith("/code"):
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        print("✅ 收到【新】验证码:", code)
                        return code

            time.sleep(5)

        die("⛔ Telegram 验证码等待超时")

    # ---------- 登录判断 ----------
    def is_logged_in(self, page) -> bool:
        try:
            status = page.evaluate("""
            async () => {
                const r = await fetch("/api/user/checkin", {
                    method: "POST",
                    headers: { "content-type": "application/json" },
                    body: JSON.stringify({ token: "glados.cloud" }),
                    credentials: "include"
                });
                return r.status;
            }
            """)
            return status == 200
        except Exception:
            return False

    # ---------- 登录 ----------
    def login(self, page):
        print("🔐 执行验证码登录")
        page.goto("https://glados.cloud/login")
        page.wait_for_load_state("networkidle")

        page.fill("input[type='email']", EMAIL)
        send_ts = int(time.time())

        page.locator("button").first.click()

        self.tg_send(
            "📨 GLaDOS 登录验证码已发送\n"
            "请回复指令：\n"
            "/code 123456"
        )

        code = self.tg_wait_code(send_ts)

        page.fill("input[type='text']", code)
        page.locator("button").nth(1).click()
        page.wait_for_load_state("networkidle")

    # ---------- 保存 state（⚠️ 只能在已登录后） ----------
    def save_state(self, context):
        state = context.storage_state()
        raw = json.dumps(state, ensure_ascii=False)
        print("💾 保存【已登录】storage_state")
        SecretUpdater("GLADOS_LOCAL").update(raw)

    # ---------- 签到 ----------
    def checkin(self, page):
        print("🚀 执行签到")
        res = page.evaluate("""
        async () => {
            const r = await fetch("https://glados.cloud/api/user/checkin", {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({ token: "glados.cloud" }),
                credentials: "include"
            });
            return r.json();
        }
        """)
        print("📊 签到返回:", res)

    # ---------- 主入口 ----------
    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            if GLADOS_LOCAL:
                print("♻️ 使用缓存 session")
                context = browser.new_context(
                    storage_state=json.loads(GLADOS_LOCAL)
                )
            else:
                print("🆕 新建 session")
                context = browser.new_context()

            page = context.new_page()
            page.goto("https://glados.cloud")
            page.wait_for_load_state("networkidle")

            if not self.is_logged_in(page):
                self.login(page)

            if not self.is_logged_in(page):
                die("❌ 登录失败，终止")

            # ✅ 只有确认登录成功，才保存
            self.save_state(context)

            # ✅ 再签到
            self.checkin(page)

            browser.close()

# ================= 启动 =================
if __name__ == "__main__":
    if not EMAIL:
        die("缺少 GLADOS_EMAIL")
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        die("缺少 Telegram 配置")

    GLaDOSAuto().run()
