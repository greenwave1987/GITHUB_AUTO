"""
Incudal 自动登录脚本
- 自动检测区域跳转（如 ap-southeast-1.console.claw.cloud）
- 等待设备验证批准（30秒）
- 每次登录后自动更新 Cookie
- Telegram 通知
"""

import os
import sys
import time
import base64
import re
import json
import requests
from requests.exceptions import RequestException
import pyotp  # 用于生成 2FA 验证码
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
# ====================== 基础配置 ======================
tg_lines = [
    f"📅 日期：{time.strftime('%Y-%m-%d')}",
    "🖥 GitHub Actions",
]
INSTANCE_IDS = {"greenwave1987":[1223, 753],"jdtaxi":[2013]}

TARGET_URL = "https://incudal.com"
SIGNIN_URL = f"{TARGET_URL}/login"
CONSOLE_URL = "https://incudal.com/console"

TIMEOUT = 15
DELAY = 1

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAIL = "FAIL"

##IN_ENTRY_URL = "https://console.run.claw.cloud"
##SIGNIN_URL = f"{IN_ENTRY_URL}/signin"
DEVICE_VERIFY_WAIT = 30  # Mobile验证 默认等 30 秒
TWO_FACTOR_WAIT = int(os.environ.get("TWO_FACTOR_WAIT", "120"))  # 2FA验证 默认等 120 秒


class Telegram:
    """Telegram 通知"""
    
    def __init__(self):
        self.token = os.environ.get('TG_BOT_TOKEN')
        self.chat_id = os.environ.get('TG_CHAT_ID')
        self.ok = bool(self.token and self.chat_id)
    
    def send(self, msg):
        if not self.ok:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=30
            )
        except:
            pass
    
    def photo(self, path, caption=""):
        if not self.ok or not os.path.exists(path):
            return
        try:
            with open(path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption[:1024]},
                    files={"photo": f},
                    timeout=60
                )
        except:
            pass
    
    def flush_updates(self):
        """刷新 offset 到最新，避免读到旧消息"""
        if not self.ok:
            return 0
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"timeout": 0},
                timeout=10
            )
            data = r.json()
            if data.get("ok") and data.get("result"):
                return data["result"][-1]["update_id"] + 1
        except:
            pass
        return 0
    
    def wait_code(self, timeout=120):
        """
        等待你在 TG 里发 /code 123456
        只接受来自 TG_CHAT_ID 的消息
        """
        if not self.ok:
            return None
        
        # 先刷新 offset，避免读到旧的 /code
        offset = self.flush_updates()
        deadline = time.time() + timeout
        pattern = re.compile(r"^/code\s+(\d{6,8})$")  # 6位TOTP 或 8位恢复码也行
        
        while time.time() < deadline:
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={"timeout": 20, "offset": offset},
                    timeout=30
                )
                data = r.json()
                if not data.get("ok"):
                    time.sleep(2)
                    continue
                
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    if str(chat.get("id")) != str(self.chat_id):
                        continue
                    
                    text = (msg.get("text") or "").strip()
                    m = pattern.match(text)
                    if m:
                        return m.group(1)
            
            except Exception:
                pass
            
            time.sleep(2)
        
        return None


class SecretUpdater:
    """GitHub Secret 更新器"""
    
    def __init__(self):
        self.token = os.environ.get('REPO_TOKEN')
        self.repo = os.environ.get('GITHUB_REPOSITORY')
        self.ok = bool(self.token and self.repo)
        if self.ok:
            print("✅ Secret 自动更新已启用")
        else:
            print("⚠️ Secret 自动更新未启用（需要 REPO_TOKEN）")
    
    def update(self, name, value):
        if not self.ok:
            return False
        try:
            from nacl import encoding, public
            
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            # 获取公钥
            r = requests.get(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key",
                headers=headers, timeout=30
            )
            if r.status_code != 200:
                return False
            
            key_data = r.json()
            pk = public.PublicKey(key_data['key'].encode(), encoding.Base64Encoder())
            encrypted = public.SealedBox(pk).encrypt(value.encode())
            
            # 更新 Secret
            r = requests.put(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                headers=headers,
                json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key_data['key_id']},
                timeout=30
            )
            return r.status_code in [201, 204]
        except Exception as e:
            print(f"更新 Secret 失败: {e}")
            return False


class AutoLogin:
    """自动登录"""
    
    def __init__(self):
        self.server = os.environ.get('PROXY')
        self.username = os.environ.get('GH_USERNAME')
        self.password = os.environ.get('GH_PASSWORD')
        self.gh_session = os.environ.get('GH_SESSION', '').strip()
        self.totp_secret = os.environ.get("GH_2FA_SECRET")
        self.tg = Telegram()
        self.secret = SecretUpdater()
        self.shots = []
        self.logs = []
        self.s = []
        self.n = 0
        
        # 区域相关
        self.detected_region = None  # 检测到的区域，如 "ap-southeast-1"
        self.region_base_url = None  # 检测到的区域基础 URL
        
    def log(self, msg, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STEP": "🔹"}
        line = f"{icons.get(level, '•')} {msg}"
        print(line, flush=True)
        self.logs.append(line)
    
    def shot(self, page, name):
        self.n += 1
        f = f"{self.n:02d}_{name}.png"
        try:
            page.screenshot(path=f)
            self.shots.append(f)
        except:
            pass
        return f
    
    def click(self, page, sels, desc=""):
        for s in sels:
            try:
                el = page.locator(s).first
                if el.is_visible(timeout=3000):
                    el.click()
                    self.log(f"已点击: {desc}", "SUCCESS")
                    return True
            except:
                pass
        return False
    
    def get_session(self, context):
        """提取 Session Cookie"""
        try:
            for c in context.cookies():
                if c['name'] == 'user_session' and 'github' in c.get('domain', ''):
                    return c['value']
        except:
            pass
        return None
    
    def save_user_cookie(self, value):
        """保存新 Cookie"""
        if not value:
            return
        
        self.log(f"新 Cookie: {value[:15]}...{value[-8:]}", "SUCCESS")
        
        # 自动更新 Secret
        if self.secret.update('USER_SESSION', value):
            self.log("已自动更新 USER_SESSION", "SUCCESS")
            self.tg.send("🔑 <b>Cookie 已自动更新</b>\n\n USER_SESSION 已保存")
        else:
            # 通过 Telegram 发送
            self.tg.send(f"""🔑 <b>新 Cookie</b>

请更新 Secret <b>USER_SESSION</b>:
<code>{value}</code>""")
            self.log("已通过 Telegram 发送 Cookie", "SUCCESS")
            
    def save_github_cookie(self, value):
        """保存新 Cookie"""
        if not value:
            return
        
        self.log(f"新 Cookie: {value[:15]}...{value[-8:]}", "SUCCESS")
        
        # 自动更新 Secret
        if self.secret.update('GH_SESSION', value):
            self.log("已自动更新 GH_SESSION", "SUCCESS")
            self.tg.send("🔑 <b>Cookie 已自动更新</b>\n\nGH_SESSION 已保存")
        else:
            # 通过 Telegram 发送
            self.tg.send(f"""🔑 <b>新 Cookie</b>

请更新 Secret <b>GH_SESSION</b>:
<code>{value}</code>""")
            self.log("已通过 Telegram 发送 Cookie", "SUCCESS")
    
    def wait_device(self, page):
        """等待设备验证"""
        self.log(f"需要设备验证，等待 {DEVICE_VERIFY_WAIT} 秒...", "WARN")
        self.shot(page, "设备验证")
        
        self.tg.send(f"""⚠️ <b>需要设备验证</b>

请在 {DEVICE_VERIFY_WAIT} 秒内批准：
1️⃣ 检查邮箱点击链接
2️⃣ 或在 GitHub App 批准""")
        
        if self.shots:
            self.tg.photo(self.shots[-1], "设备验证页面")
        
        for i in range(DEVICE_VERIFY_WAIT):
            time.sleep(1)
            if i % 5 == 0:
                self.log(f"  等待... ({i}/{DEVICE_VERIFY_WAIT}秒)")
                url = page.url
                if 'verified-device' not in url and 'device-verification' not in url:
                    self.log("设备验证通过！", "SUCCESS")
                    self.tg.send("✅ <b>设备验证通过</b>")
                    return True
                try:
                    page.reload(timeout=10000)
                    page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
        
        if all(x not in page.url for x in [
            'device-verification',
            'verified-device'
        ]):
            return True
        
        self.log("设备验证超时", "ERROR")
        self.tg.send("❌ <b>设备验证超时</b>")
        return False
    def wait_two_factor_mobile(self, page):
        """
        完全不 reload 的 GitHub Mobile 2FA 等待
        只被动观察 URL / DOM 变化
        """
        self.log(f"需要两步验证（GitHub Mobile），等待 {TWO_FACTOR_WAIT} 秒...", "WARN")
    
        # 首次截图（立刻发，给你看数字）
        shot = self.shot(page, "two_factor_mobile_init")
        self.tg.send(
            f"⚠️ <b>需要两步验证（GitHub Mobile）</b>\n\n"
            f"请在手机 GitHub App 中批准本次登录\n"
            f"⏳ 等待时间：{TWO_FACTOR_WAIT} 秒"
        )
        if shot:
            self.tg.photo(shot, "两步验证页面（首次）")
    
        start_url = page.url
        deadline = time.time() + TWO_FACTOR_WAIT
        last_shot_at = 0
    
        while time.time() < deadline:
            time.sleep(1)
    
            try:
                url = page.url
            except:
                continue
    
            # ✅ 成功：离开 two-factor 流程
            if "github.com/sessions/two-factor/" not in url:
                self.log("两步验证通过！", "SUCCESS")
                self.tg.send("✅ <b>两步验证通过</b>")
                return True
    
            # ❌ 失败：被 GitHub 主动打回登录页
            if "github.com/login" in url:
                self.log("两步验证失败，被返回登录页", "ERROR")
                self.tg.send("❌ <b>两步验证失败，需要重新登录</b>")
                return False
    
            # 📸 每 10 秒补一张截图（不触发任何请求）
            now = time.time()
            if now - last_shot_at >= 10:
                last_shot_at = now
                sec = int(TWO_FACTOR_WAIT - (deadline - now))
                self.log(f"  等待中... ({sec}/{TWO_FACTOR_WAIT} 秒)")
                shot = self.shot(page, f"two_factor_mobile_{sec}s")
                if shot:
                    self.tg.photo(shot, f"两步验证页面（{sec}s）")
    
        # ⏰ 超时
        self.log("两步验证超时", "ERROR")
        self.tg.send("❌ <b>两步验证超时</b>")
        return False

    def jwait_two_factor_mobile(self, page):
        """等待 GitHub Mobile 两步验证批准，并把数字截图提前发到电报"""
        self.log(f"需要两步验证（GitHub Mobile），等待 {TWO_FACTOR_WAIT} 秒...", "WARN")
        
        # 先截图并立刻发出去（让你看到数字）
        shot = self.shot(page, "两步验证_mobile")
        self.tg.send(f"""⚠️ <b>需要两步验证（GitHub Mobile）</b>

请打开手机 GitHub App 批准本次登录（会让你确认一个数字）。
等待时间：{TWO_FACTOR_WAIT} 秒""")
        if shot:
            self.tg.photo(shot, "两步验证页面（数字在图里）")
        
        # 不要频繁 reload，避免把流程刷回登录页
        for i in range(TWO_FACTOR_WAIT):
            time.sleep(1)
            
            url = page.url
            
            # 如果离开 two-factor 流程页面，认为通过
            if "github.com/sessions/two-factor/" not in url:
                self.log("两步验证通过！", "SUCCESS")
                self.tg.send("✅ <b>两步验证通过</b>")
                return True
            
            # 如果被刷回登录页，说明这次流程断了（不要硬等）
            if "github.com/login" in url:
                self.log("两步验证后回到了登录页，需重新登录", "ERROR")
                return False
            
            # 每 10 秒打印一次，并补发一次截图（防止你没看到数字）
            if i % 10 == 0 and i != 0:
                self.log(f"  等待... ({i}/{TWO_FACTOR_WAIT}秒)")
                shot = self.shot(page, f"两步验证_{i}s")
                if shot:
                    self.tg.photo(shot, f"两步验证页面（第{i}秒）")
            
            # 只在 30 秒、60 秒... 做一次轻刷新（可选，频率很低）
            if i % 30 == 0 and i != 0:
                try:
                    page.reload(timeout=30000)
                    page.wait_for_load_state('domcontentloaded', timeout=30000)
                except:
                    pass
        
        self.log("两步验证超时", "ERROR")
        self.tg.send("❌ <b>两步验证超时</b>")
        return False
    
    def handle_2fa_code_input(self, page):
        """处理 TOTP 验证码输入（通过 Telegram 发送 /code 123456）"""
        self.log("需要输入验证码", "WARN")
        shot = self.shot(page, "两步验证_code")
        
        # 先尝试点击"Use an authentication app"或类似按钮（如果在 mobile 页面）
        try:
            more_options = [
                'a:has-text("Use an authentication app")',
                'a:has-text("Enter a code")',
                'button:has-text("Use an authentication app")',
                '[href*="two-factor/app"]'
            ]
            for sel in more_options:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click()
                        time.sleep(2)
                        page.wait_for_load_state('networkidle', timeout=15000)
                        self.log("已切换到验证码输入页面", "SUCCESS")
                        shot = self.shot(page, "两步验证_code_切换后")
                        break
                except:
                    pass
        except:
            pass
        if shot:
            self.tg.photo(shot, "两步验证页面")
        # 首选计算验证码
        self.log("🔢 正在计算动态验证码 (TOTP)...")
        # 使用密钥生成当前的 6 位验证码
        totp = pyotp.TOTP(self.totp_secret)
        code = None
        
        if self.totp_secret:
            try:
                code = totp.now()
                self.log("已生成 TOTP 验证码", "SUCCESS")
            except Exception:
                code = None
        
        if not code:
            self.log("需要手动输入验证码", "WARN")
            self.tg.send(
                f"🔐 <b>需要验证码登录</b>\n\n"
                f"请发送：<code>/code 123456</code>\n"
                f"等待 {TWO_FACTOR_WAIT} 秒"
            )
            code = self.tg.wait_code(timeout=TWO_FACTOR_WAIT)
        
        if not code:
            self.log("验证码获取失败", "ERROR")
            return False

        # 不打印验证码明文，只提示收到
        self.log(f"   获取到验证码: {code}，正在填入...", "SUCCESS")
        
        # 常见 OTP 输入框 selector（优先级排序）
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[name="app_otp"]',
            'input[name="otp"]',
            'input#app_totp',
            'input#otp',
            'input[inputmode="numeric"]'
        ]
        
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.fill(code)
                    self.log(f"已填入验证码", "SUCCESS")
                    time.sleep(1)
                    
                    # 优先点击 Verify 按钮，不行再 Enter
                    submitted = False
                    verify_btns = [
                        'button:has-text("Verify")',
                        'button[type="submit"]',
                        'input[type="submit"]'
                    ]
                    for btn_sel in verify_btns:
                        try:
                            btn = page.locator(btn_sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                submitted = True
                                self.log("已点击 Verify 按钮", "SUCCESS")
                                break
                        except:
                            pass
                    
                    if not submitted:
                        page.keyboard.press("Enter")
                        self.log("已按 Enter 提交", "SUCCESS")
                    
                    time.sleep(3)
                    page.wait_for_load_state('networkidle', timeout=60000)
                    self.shot(page, "验证码提交后")
                    
                    # 检查是否通过
                    if "github.com/sessions/two-factor/" not in page.url:
                        self.log("验证码验证通过！", "SUCCESS")
                        self.tg.send("✅ <b>验证码验证通过</b>")
                        return True
                    else:
                        self.log("验证码可能错误", "ERROR")
                        self.tg.send("❌ <b>验证码可能错误，请检查后重试</b>")
                        return False
            except:
                pass
        
        self.log("没找到验证码输入框", "ERROR")
        self.tg.send("❌ <b>没找到验证码输入框</b>")
        return False
    
    def login_github(self, page, context):
        """登录 GitHub"""
        self.log("登录 GitHub...", "STEP")
        self.shot(page, "github_登录页")
        
        try:
            page.locator('input[name="login"]').fill(self.username)
            page.locator('input[name="password"]').fill(self.password)
            self.log("已输入凭据")
        except Exception as e:
            self.log(f"输入失败: {e}", "ERROR")
            return False
        
        self.shot(page, "github_已填写")
        
        try:
            page.locator('input[type="submit"], button[type="submit"]').first.click()
        except:
            pass
        
        time.sleep(3)
        page.wait_for_load_state('networkidle', timeout=30000)
        self.shot(page, "github_登录后")
        
        url = page.url
        self.log(f"当前: {url}")
        
        # 设备验证
        if 'verified-device' in url or 'device-verification' in url:
            if not self.wait_device(page):
                return False
            time.sleep(2)
            page.wait_for_load_state('networkidle', timeout=30000)
            self.shot(page, "验证后")
        
        # 2FA
        if 'two-factor' in page.url:
            self.log("需要两步验证！", "WARN")
            self.shot(page, "两步验证")
            
            # GitHub Mobile：等待你在手机上批准
            if 'two-factor/mobile' in page.url:
                if not self.wait_two_factor_mobile(page):
                    return False
                # 通过后等页面稳定
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
            
            else:
                # 其它两步验证方式（TOTP/恢复码等），尝试通过 Telegram 输入验证码
                if not self.handle_2fa_code_input(page):
                    return False
                # 通过后等页面稳定
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
        
        # 错误
        try:
            err = page.locator('.flash-error').first
            if err.is_visible(timeout=2000):
                self.log(f"错误: {err.inner_text()}", "ERROR")
                return False
        except:
            pass
        
        return True
    
    def oauth(self, page):
        """处理 OAuth"""
        if 'github.com/login/oauth/authorize' in page.url:
            self.log("处理 OAuth...", "STEP")
            self.shot(page, "oauth")
            self.click(page, ['button[name="authorize"]', 'button:has-text("Authorize")'], "授权")
            time.sleep(3)
            page.wait_for_load_state('networkidle', timeout=30000)
    
    def wait_redirect(self, page, wait=60):
        """等待重定向并检测区域"""
        self.log("等待重定向...", "STEP")
        for i in range(wait):
            url = page.url
            u = urlparse(url)
            if u.hostname and u.hostname.count('.') >= 3:
                self.detected_region = u.hostname.split('.')[0]
            # 检查是否已跳转到 incudal.com
            if 'incudal' in url and 'login' not in url.lower():
                self.log("重定向成功！", "SUCCESS")
                
                return True
            
            if 'github.com/login/oauth/authorize' in url:
                self.oauth(page)
            
            time.sleep(1)
            if i % 10 == 0:
                self.log(f"  等待... ({i}秒)")
        
        self.log("重定向超时", "ERROR")
        return False
    
    
    def notify(self, ok, err=""):
        if not self.tg.ok:
            return
        
        region_info = f"\n<b>区域:</b> {self.detected_region or '默认'}" if self.detected_region else ""
        
        msg = f"""<b>🤖 Incudal 自动登录</b>

<b>状态:</b> {"✅ 成功" if ok else "❌ 失败"}
<b>用户:</b> {self.username}{region_info}
<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        if err:
            msg += f"\n<b>错误:</b> {err}"
        
        msg += "\n\n<b>日志:</b>\n" + "\n".join(self.logs[-6:])
        
        self.tg.send(msg)
        
        if self.shots:
            if not ok:
                for s in self.shots[-3:]:
                    self.tg.photo(s, s)
            else:
                self.tg.photo(self.shots[-1], "完成")

    # ====================== Session 构建 ======================
    
    def build_session(self, auth, cookies):
        self.log("🔧 构建 requests.Session")
        s = requests.Session()
        s.headers.update({
            "accept": "application/json, text/plain, */*",
            "user-agent": "Mozilla/5.0 Chrome/143.0",
            "referer": TARGET_URL,
            "origin": TARGET_URL,
        })
        if auth:
            s.headers["authorization"] = auth
        for c in cookies or []:
            s.cookies.set(
                c["name"],
                c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/")
            )
        return s
    
    # ====================== API ======================
    
    def safe_json(self, resp):
        try:
            print(resp.json())
            return resp.json()
        except Exception:
            print({"raw": resp.text, "status": resp.status_code})
            return {"raw": resp.text, "status": resp.status_code}
    
    def get_status(self, session):
        self.log("📡 查询签到状态")
        resp = session.get(
            "https://incudal.com/api/checkin/status",
            timeout=TIMEOUT
        )
        self.log(f"↩️ HTTP {resp.status_code}")
        data=self.safe_json(resp)
        # 示例用法
        code_data = None  # 🔹 先初始化

        # 判断 todayCode 是否存在
        if isinstance(data.get("todayCode"), dict):
            code_data = data["todayCode"]
        elif isinstance(data, dict) and "codeType" in data:
            code_data = data
        
        if code_data:
            self.log(f"🟢获得兑换码： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")  # 输出: CPU +50%
            tg_lines.append(f"🟢获得兑换码： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")
        return data
    
    def checkin_and_get_code(self, session):
        self.log("🟢 执行签到")
        resp = session.post(
            "https://incudal.com/api/checkin/checkin",
            timeout=TIMEOUT
        )
        self.log(f"↩️ HTTP {resp.status_code}")
        data = self.safe_json(resp)
        # 示例用法
        code_data = None  # 🔹 先初始化

        # 判断 todayCode 是否存在
        if isinstance(data.get("todayCode"), dict):
            code_data = data["todayCode"]
        elif isinstance(data, dict) and "codeType" in data:
            code_data = data
        
        if code_data:
            self.log(f"🟢获得兑换码： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")  # 输出: CPU +50%
            tg_lines.append(f"🟢获得兑换码： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")
        return code_data.get("redeemCode") 
    
    def decode_redeem(self,code_type, code_value):
        type_map = {
            "c": {"name": "CPU", "unit": "%"},
            "r": {"name": "内存", "unit": "MB"},
            "d": {"name": "硬盘", "unit": "MB"},
            "t": {"name": "流量", "unit": "GB"}
        }
    
        info = type_map.get(code_type)
        if not info:
            return "未知资源"
    
        return f"{info['name']} +{code_value}{info['unit']}"

    def redeem_instance(self, session, redeem_code, instance_id):
        self.log(f"🎁 兑换实例 {instance_id}")
        resp = session.post(
            "https://incudal.com/api/checkin/redeem",
            json={"redeemCode": redeem_code, "instanceId": instance_id},
            timeout=TIMEOUT
        )
        self.log(f"↩️ HTTP {resp.status_code}")

        data = self.safe_json(resp)
        if data.get("details"):
            data["message"]=data["details"]
            return data
        if data.get("error"):
            data["message"]=data["error"]
            return data
        # 示例用法
        code_data = None  # 🔹 先初始化

        # 判断 todayCode 是否存在
        if isinstance(data.get("todayCode"), dict):
            code_data = data["todayCode"]
        elif isinstance(data, dict) and "codeType" in data:
            code_data = data
        
        if code_data:

            self.log(f"🟢兑换结果： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")  # 输出: CPU +50%
            tg_lines.append(f"🟢兑换结果： {self.decode_redeem(code_data['codeType'], code_data['codeValue'])}")
            return code_data
        return data

    def pick_available_proxy(self, timeout=10):
        """
        使用 requests 轮询代理
        返回 (proxy_server | None, msg)
        """
    
        if not self.server:
            self.log("未提供代理列表，使用直连", "INFO")
            return None, "未配置代理，跳过代理检测"
    
        proxies_list = [p.strip() for p in self.server.split(",") if p.strip()]
        self.log(f"🔁 开始轮询代理（共 {len(proxies_list)} 个）", "STEP")
    
        test_url = "https://myip.ipip.net"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
    
        for idx, server in enumerate(proxies_list, 1):
            # 自动补协议
            if not server.startswith(("http://", "https://", "socks5://")):
                server = f"http://{server}"
    
            proxy_cfg = {
                "http": server,
                "https": server,
            }
    
            self.log(f"🌐 测试代理 {idx}/{len(proxies_list)}: {server}", "INFO")
    
            try:
                resp = requests.get(
                    test_url,
                    proxies=proxy_cfg,
                    headers=headers,
                    timeout=timeout,
                    verify=False,          # 防止代理 https 证书问题
                    allow_redirects=True
                )
    
                if resp.status_code == 200 and resp.text.strip():
                    ip_text = resp.text.strip()
                    self.log(f"代理可用: {ip_text}", "SUCCESS")
                    return server, f"当前 IP : {ip_text}"
    
                self.log(f"⚠️ 响应异常: HTTP {resp.status_code}", "WARN")
    
            except RequestException as e:
                self.log(f"❌ 代理失败: {repr(e)}", "WARN")
    
        self.log("🚫 所有代理均不可用，将使用直连", "WARN")
        return None, "🚫 所有代理均不可用，将使用直连"
        
    def detect_proxy_available(self):
        """
        检测代理是否可用
        成功返回 True，失败返回 False
        """
        if not self.server:
            self.log("未配置代理，跳过代理检测", "INFO")
            return False,"未配置代理，跳过代理检测"
    
        self.log("🔍 检测代理可用性...", "STEP")
    
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox'],
                    proxy={"server": self.server}
                )
                context = browser.new_context()
                page = context.new_page()
    
                page.goto("https://myip.ipip.net", timeout=20000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
    
                ip_text = page.text_content("body") or ""
                self.log(f"🌐 当前 IP : {ip_text.strip()}", "SUCCESS")
                
    
                browser.close()
                return True,f"当前 IP : {ip_text.strip()}"
    
        except Exception as e:
            self.log(f"代理不可用: {e}", "WARN")
            return False,f"❌代理不可用: {e}"
    
        
    def run(self):
        start_ts = time.time()
   

        print("\n" + "="*50)
        print("🚀 Incudal 自动登录")
        print("="*50 + "\n")
        
        self.log(f"用户名: {self.username}")
        self.log(f"Session: {'有' if self.gh_session else '无'}")
        self.log(f"密码: {'有' if self.password else '无'}")
        self.log(f"登录入口: {TARGET_URL}")
        
        if not self.username or not self.password:
            self.log("缺少凭据", "ERROR")
            self.notify(False, "凭据未配置")
            sys.exit(1)
        
        auth_token = None

        def on_request(req):
            nonlocal auth_token
            auth = req.headers.get("authorization")
            if auth and "/api/" in req.url:
                auth_token = auth
                self.log("🔑 捕获 Authorization")
            
        
        with sync_playwright() as p:
            use_proxy = False

            if self.server and use_proxy:
                proxy_cfg,proxy_msg=self.pick_available_proxy()
                
                if proxy_cfg:
                    use_proxy = True
                    self.log(proxy_msg, "SUCCESS")
                    tg_lines.append(proxy_msg)
                    
                else:
                    self.log(f"❌ {proxy_msg}，已自动切换为直连", "WARN")
                    self.server = None
            
            launch_args = dict(
                headless=True,
                args=['--no-sandbox']
            )
            
            if use_proxy:
                launch_args["proxy"] = {"server": proxy_cfg}
            
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = context.new_page()
            

            try:
                if not use_proxy:
                    page.goto("https://myip.ipip.net", timeout=20000)
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
        
                    ip_text = page.text_content("body") or ""
                    self.log(f"🌐 当前 IP: {ip_text.strip()}")
                    tg_lines.append(f"🌐 当前 IP: {ip_text.strip()}")
                # 预加载 Cookie
                if self.gh_session:
                    try:
                        context.add_cookies([
                            {'name': 'user_session', 'value': self.gh_session, 'domain': 'github.com', 'path': '/'},
                            {'name': 'logged_in', 'value': 'yes', 'domain': 'github.com', 'path': '/'}
                        ])
                        self.log("已加载 Session Cookie", "SUCCESS")
                    except:
                        self.log("加载 Cookie 失败", "WARN")
                
                # 1. 访问 Incudal 登录入口
                page.on("request", on_request)
                self.log("步骤1: 打开 Incudal 登录页", "STEP")
                page.goto(SIGNIN_URL, timeout=60000)
                ##page.wait_for_load_state('networkidle', timeout=30000)
                time.sleep(2)
                self.shot(page, "Incudal")
                
                # 检查当前 URL，可能已经自动跳转到区域
                current_url = page.url
                self.log(f"当前 URL: {current_url}")
                
                if 'login' not in current_url.lower() and 'incudal' in current_url:
                    self.log("已登录！", "SUCCESS")

                    # 提取并保存新 Cookie
                    new = self.get_session(context)
                    if new:
                        self.save_github_cookie(new)
                    self.notify(True)
                    print("\n✅ 成功！\n")
                    return
                
                # 2. 点击 GitHub
                MAX_RETRY = 3  # 最大重试次数
                RETRY_DELAY = 2  # 每次重试间隔秒数
                self.log(f"步骤2: 点击 GitHub（最大重试{MAX_RETRY}次，每次重试间隔{RETRY_DELAY}秒）", "STEP")
                
                for attempt in range(1, MAX_RETRY + 1):
                    if self.click(page, [
                            'button:has-text("GitHub")',
                            'a:has-text("GitHub")',
                            '[data-provider="github"]'
                        ], "GitHub"):
                        self.log(f"成功点击 GitHub 按钮 (尝试 {attempt})", "INFO")
                        break  # 点击成功，跳出循环
                    else:
                        self.log(f"第 {attempt} 次尝试未找到 GitHub 按钮", "WARNING")
                        if attempt < MAX_RETRY:
                            time.sleep(RETRY_DELAY)  # 等待一会儿再试
                        else:
                            self.log("找不到 GitHub 按钮，重试次数已用完", "ERROR")
                            self.notify(False, "找不到 GitHub 按钮")
                            sys.exit(1)
                
                time.sleep(3)
                page.wait_for_load_state('networkidle', timeout=30000)
                self.shot(page, "点击后")
                
                url = page.url
                self.log(f"当前: {url}")
                
                # 3. GitHub 登录
                self.log("步骤3: GitHub 认证", "STEP")
                
                if 'github.com/login' in url or 'github.com/session' in url:
                    if not self.login_github(page, context):
                        self.shot(page, "登录失败")
                        self.notify(False, "GitHub 登录失败")
                        sys.exit(1)
                elif 'github.com/login/oauth/authorize' in url:
                    self.log("Cookie 有效", "SUCCESS")
                    self.oauth(page)
                
                # 4. 等待重定向（会自动检测区域）
                self.log("步骤4: 等待重定向", "STEP")
                if not self.wait_redirect(page):
                    self.shot(page, "重定向失败")
                    self.notify(False, "重定向失败")
                    sys.exit(1)
                
                self.shot(page, "重定向成功")
                
                # 5. 验证
                self.log("步骤5: 验证", "STEP")
                current_url = page.url
                if 'incudal' not in current_url or 'login' in current_url.lower():
                    self.notify(False, "验证失败")
                    sys.exit(1)
                                
                               
                # 6. 提取并保存新 Cookie
                self.log("步骤6: 更新 Cookie", "STEP")
                new = self.get_session(context)
                if new:
                    self.save_github_cookie(new)
                else:
                    self.log("未获取到新 Cookie", "WARN")
                
                self.notify(True)
                print("\n" + "="*50)
                print("✅ 成功！")
                if self.detected_region:
                    print(f"📍 区域: {self.detected_region}")
                print("="*50 + "\n")
                # 7. 检测签到
                if not auth_token:
                    raise RuntimeError("未捕获 Authorization")
                cookies = context.cookies()
                self.log(f"🍪 获取 cookies：{len(cookies)}")
                
            
                data = {
                    "auth_token": auth_token,
                    "cookies": cookies
                }
            
                json_str = json.dumps(data, ensure_ascii=False)

                self.save_user_cookie(json_str)
                
                session = self.build_session(auth_token, cookies)
                status = self.get_status(session)

                checked_in = status.get("hasCheckedIn", False)
                redeemed = status.get("hasRedeemed", False)
            
                redeem_code = None
                if status.get("todayCode"):
                    redeem_code = status["todayCode"].get("redeemCode")
            
                tg_lines.append(f"📊 初始状态：签到={checked_in}，兑换={redeemed}")
            
                if not checked_in:
                    print("\n🎁 去签到！")
                    redeem_code = self.checkin_and_get_code(session)
            
                if redeemed:
                    print("\n🎁 已兑换！")
                    tg_lines.append("🎉 今日已完成兑换")
                    msgtemp = "\n".join(tg_lines)
                    
                    self.tg.send(
                        f"Incudal 自动签到完成\n\n{msgtemp}\n\n状态:{STATUS_OK}\n耗时:{time.time() - start_ts:.1f}s"
                    )
                    return
            
                if redeem_code:
                    tg_lines.append("\n🎁 <b>实例兑换结果</b>")
                    success = 0
                    level = STATUS_OK
                
                    for iid in INSTANCE_IDS[self.username]:
                        try:
                            data = self.redeem_instance(session, redeem_code, iid)
                            if data.get("success") is True:
                                tg_lines.append(f"- {iid}：成功")
                                success += 1
                            else:
                                tg_lines.append(f"- {iid}：{data.get('message','本次失败')}")
                                level = STATUS_PARTIAL
                        except RequestException:
                            tg_lines.append(f"- {iid}：失败")
                            level = STATUS_FAIL
                        time.sleep(DELAY)
                
                    if success == 0:
                        level = STATUS_FAIL
                    elif success < len(INSTANCE_IDS[self.username]):
                        level = STATUS_PARTIAL
                
                    msgtemp = "\n".join(tg_lines)
                        
                    self.tg.send(
                        f"Incudal 自动签到完成\n\n{msgtemp}\n\n状态:{level}\n耗时:{time.time() - start_ts:.1f}s"
                    )
                    return
                    
                tg_lines.append(f"❌ 未知错误，查看日志！")

            

            
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.shot(page, "异常")
                import traceback
                traceback.print_exc()
                self.notify(False, str(e))
                sys.exit(1)
            finally:
                browser.close()


if __name__ == "__main__":
    AutoLogin().run()
