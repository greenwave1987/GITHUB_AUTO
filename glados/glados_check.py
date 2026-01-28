import os
import time
import json
import base64
import requests
from nacl import public, encoding
from playwright.sync_api import sync_playwright

# ---------- 环境变量 ----------
EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")  # GitHub Secret

if not EMAIL or not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise RuntimeError("❌ 缺少必填环境变量 EMAIL/TG_BOT_TOKEN/TG_CHAT_ID")


# ---------- Secret 回写 ----------
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value: str):
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 REPO/REPO_TOKEN，跳过 Secret 更新")
            return

        headers = {
            "Authorization": f"token {REPO_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        # 获取公钥
        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers, timeout=30)
        r.raise_for_status()
        key = r.json()

        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())
        payload = {
            "encrypted_value": base64.b64encode(encrypted).decode(),
            "key_id": key["key_id"]
        }

        r = requests.put(f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}", headers=headers, json=payload, timeout=30)
        print(f"✅ Secret 更新完成，HTTP {r.status_code}")


# ---------- Telegram ----------
def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram 发送失败: {resp.text}")


def tg_wait_code(start_time: int, timeout=300):
    """
    轮询 Telegram 获取验证码，只取 start_time 之后的新消息
    """
    tg_send("📨 GLaDOS 登录验证码已发送\n请回复指令：/code 123456")
    offset = None
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                            params={"offset": offset, "timeout": 10}, timeout=15).json()
        for item in resp.get("result", []):
            offset = item["update_id"] + 1
            msg = item.get("message", {})
            msg_time = msg.get("date", 0)
            text = msg.get("text", "")
            if msg_time < start_time:
                continue
            if text.startswith("/code"):
                code = text.replace("/code", "").strip()
                if code.isdigit():
                    print(f"✅ 收到【新】验证码: {code}")
                    return code
        time.sleep(5)
    raise RuntimeError("⛔ Telegram 验证码等待超时")


# ---------- 签到结果处理 ----------
def parse_checkin_only(resp: dict):
    for item in resp.get("list", []):
        if item.get("business", "").startswith("system:checkin:"):
            date = item["business"].split(":")[-1]
            change = float(item.get("change", 0))
            balance = float(item.get("balance", 0))
            change_str = str(int(change)) if change.is_integer() else str(change)
            balance_str = str(int(balance)) if balance.is_integer() else str(balance)
            return f"checkin:{date} | 获得 {change_str} | 总积分 {balance_str}"
    return "未找到签到记录"


# ---------- GLaDOS 自动化 ----------
class GLaDOSAuto:
    def __init__(self):
        self.storage_state = GLADOS_LOCAL or None

    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def run(self):
        self.log("STEP 1: 启动 Playwright")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = None
            page = None
            try:
                if self.storage_state:
                    try:
                        self.log("♻️ 尝试使用缓存 session")
                        context = browser.new_context(storage_state=json.loads(self.storage_state))
                        page = context.new_page()
                        page.goto("https://glados.cloud/login", timeout=60000)
                        self.log("✅ 使用缓存登录成功")
                    except Exception:
                        self.log("⚠ 注意：无法直接解密，默认重新登录")
                        context = browser.new_context()
                        page = context.new_page()
                        self.login(page)
                else:
                    context = browser.new_context()
                    page = context.new_page()
                    self.login(page)

                # 登录完成后更新 storage_state 并回写 Secret
                self.storage_state = json.dumps(context.storage_state())
                SecretUpdater("GLADOS_LOCAL").update(self.storage_state)

                # 执行签到
                self.checkin(page)

            finally:
                browser.close()

    def login(self, page):
        self.log("🔐 执行登录")
        page.goto("https://glados.cloud/login", timeout=60000)
        page.fill("input#email", EMAIL)
        page.click("button:has-text('Get Code')")
        start_time = int(time.time())
        code = tg_wait_code(start_time)
        page.fill("input#mailcode", code)
        page.click("button:has-text('Login')")
        time.sleep(3)
        # 检查是否登录成功
        token = page.evaluate('''() => localStorage.getItem("token")''')
        if not token:
            # Dump 页面方便调试
            with open("login_failed.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path="login_failed.png")
            raise RuntimeError("❌ 登录失败")
        self.log("✅ 登录成功")

    def checkin(self, page):
        self.log("🚀 执行签到")
        resp = page.evaluate("""
            () => fetch("https://glados.cloud/api/user/checkin", {
                method: "POST",
                headers: {
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json;charset=UTF-8"
                },
                body: JSON.stringify({token:"glados.cloud"}),
            }).then(r => r.json())
        """)
        result_str = parse_checkin_only(resp)
        self.log(f"📊 签到返回: {result_str}")
        tg_send(f"🎉 GLaDOS 签到结果:\n{result_str}")


if __name__ == "__main__":
    GLaDOSAuto().run()
