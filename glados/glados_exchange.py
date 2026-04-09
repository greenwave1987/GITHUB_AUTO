import os
import json
import time
import requests
import base64
from nacl import encoding, public
from playwright.sync_api import sync_playwright

# API 地址
POINTS_API = "https://glados.cloud/api/user/points"
EXCHANGE_API = "https://glados.cloud/api/user/exchange"
CONSOLE_URL = "https://glados.cloud/console/account"

# 环境变量获取
EMAILS = os.environ.get("GLADOS_EMAIL", "").split(",")
TG_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
REPO_TOKEN = os.environ.get("REPO_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")

def tg_send(text):
    if TG_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
        except Exception as e:
            print(f"TG 发送失败: {e}")

def update_secret(name, value):
    """更新 GitHub Secret 保持 session 最新"""
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    try:
        key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers).json()
        
        public_key = key_resp["key"]
        public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(public_key_obj)
        encrypted_value = base64.b64encode(sealed_box.encrypt(value.encode("utf-8"))).decode("utf-8")

        put_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{name}"
        requests.put(put_url, headers=headers, json={
            "encrypted_value": encrypted_value,
            "key_id": key_resp["key_id"]
        })
    except Exception as e:
        print(f"Secret 更新失败: {e}")

def run_exchange():
    print("====== GLaDOS 自动兑换检查开始 ======")
    
    local_raw = os.environ.get("GLADOS_LOCAL", "{}")
    try:
        local_storage_dict = json.loads(local_raw)
    except:
        local_storage_dict = {}

    final_storage_dict = local_storage_dict.copy()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for email in filter(None, [i.strip() for i in EMAILS]):
            print(f"\n>>> 正在检查账号: {email}")
            current_storage = local_storage_dict.get(email)
            
            context = browser.new_context(
                storage_state=current_storage if current_storage else None,
                user_agent="Mozilla/5.0 Chrome/128.0.0.0"
            )
            page = context.new_page()

            try:
                # 1. 进入控制台检查 Session
                page.goto(CONSOLE_URL)
                
                # 获取当前积分
                points_data = page.evaluate(f'async () => {{ const r = await fetch("{POINTS_API}"); return await r.json(); }}')
                
                if points_data.get('code') != 0:
                    print(f"[{email}] Session 已失效，跳过兑换（请先运行签到程序登录）")
                    continue

                total_points = float(points_data.get('points', 0))
                print(f"[{email}] 当前积分: {total_points}")

                # 2. 积分达到 500 执行兑换
                if total_points >= 500:
                    print(f"[{email}] 积分充足，准备兑换 plan500...")
                    
                    exchange_res = page.evaluate(f'''
                        async () => {{
                            const r = await fetch("{EXCHANGE_API}", {{
                                method: "POST",
                                headers: {{"content-type": "application/json;charset=UTF-8"}},
                                body: JSON.stringify({{planType: "plan500"}})
                            }});
                            return await r.json();
                        }}
                    ''')

                    if exchange_res.get('code') == 0:
                        msg = f"🎁 GLaDOS 兑换成功！\n账号: {email}\n消耗: 500 积分\n新增: 100 天"
                        print(msg)
                        tg_send(msg)
                    else:
                        error_msg = exchange_res.get('message', '未知错误')
                        print(f"[{email}] 兑换失败: {error_msg}")
                        tg_send(f"⚠️ GLaDOS 兑换失败\n账号: {email}\n原因: {error_msg}")
                else:
                    print(f"[{email}] 积分不足 500，无需操作。")

                # 更新 Session 状态
                final_storage_dict[email] = context.storage_state()

            except Exception as e:
                print(f"[{email}] 运行异常: {e}")
            finally:
                context.close()

        browser.close()

    # 如果 session 有变动，回写 Secret
    new_storage_raw = json.dumps(final_storage_dict)
    if local_raw != new_storage_raw:
        print("更新本地缓存 Secret...")
        update_secret("GLADOS_LOCAL", new_storage_raw)

    print("\n====== 兑换检查任务结束 ======")

if __name__ == "__main__":
    run_exchange()
