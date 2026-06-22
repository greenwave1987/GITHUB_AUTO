import os
import asyncio
from datetime import datetime
# 引入 playwright
from playwright.async_api import async_playwright

COOKIES_STR = os.getenv("DOMAIN_COOKIE") 
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
BASE_URL = "https://dash.domain.digitalplat.org/_panel_api/api"

def send_tg(message):
    if TG_BOT_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            import json, urllib.request
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: print(f"TG 发送失败: {e}")

# 解析 Cookie 字符串为 Playwright 格式
def parse_cookie_to_playwright(cookie_str, domain_host="dash.domain.digitalplat.org"):
    playwright_cookies = []
    pairs = cookie_str.strip().split(';')
    for pair in pairs:
        if '=' in pair:
            name, value = pair.split('=', 1)
            playwright_cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": domain_host,
                "path": "/"
            })
    return playwright_cookies

async def process_account(context, cookie_str, index):
    report = f"👤 **账号 # {index}**\n"
    
    # 为当前账号创建一个独立的隔离页面（携带该账号的 Cookie）
    account_context = await context.browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    cookies = parse_cookie_to_playwright(cookie_str)
    await account_context.add_cookies(cookies)
    
    page = await account_context.new_page()
    
    try:
        # 先让浏览器正常访问一次主页，让 WAF 放行并建立会话
        await page.goto("https://dash.domain.digitalplat.org/domains", timeout=30000, wait_until="networkidle")
        
        # 使用浏览器内部环境执行 fetch，天然携带完美的浏览器环境和过墙凭证
        fetch_domains_script = f"""
        async () => {{
            const res = await fetch("{BASE_URL}/domains", {{
                headers: {{ "accept": "application/json" }}
            }});
            return {{ status: res.status, text: await res.text() }};
        }}
        """
        
        result = await page.evaluate(fetch_domains_script)
        
        if result["status"] == 403:
            await account_context.close()
            return report + "❌ 浏览器请求仍被 WAF 拦截 (403)，可能 IP 被彻底拉黑或 Cookie 绑定了原 IP。\n"
            
        import json
        data = json.loads(result["text"])
        if not data.get("ok"):
            await account_context.close()
            return report + "❌ 登录失效或获取域名失败\n"

        domains = data.get("domains", [])
        if not domains:
            await account_context.close()
            return report + "❓ 该账号下无域名\n"

        for d in domains:
            domain_name = d['domain']
            expiry_str = d['expiry_date']
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
            remaining_days = (expiry_date - datetime.now()).days
            
            item_info = f"- `{domain_name}`: 剩余 `{remaining_days}` 天 "
            
            if remaining_days < 100:
                # 同样在浏览器内部上下文中跑续期 Fetch
                renew_script = f"""
                async () => {{
                    const res = await fetch("{BASE_URL}/domains/{domain_name}/renew", {{
                        method: "POST",
                        headers: {{ "content-type": "application/json" }},
                        body: JSON.stringify({{ "renewal_type": "free", "years": 1 }})
                    }});
                    return {{ status: res.status, text: await res.text() }};
                }}
                """
                renew_result = await page.evaluate(renew_script)
                
                if renew_result["status"] == 200 and json.loads(renew_result["text"]).get("ok"):
                    item_info += "✅ **已续期**\n"
                else:
                    item_info += f"⚠️ **续期失败 (Status: {renew_result['status']})**\n"
            else:
                item_info += "😴 状态良好\n"
            
            report += item_info

    except Exception as e:
        report += f"💥 运行异常: {str(e)}\n\n"
    finally:
        await account_context.close()
        
    return report + "\n"

async def main():
    if not COOKIES_STR:
        print("未找到 DOMAIN_COOKIES")
        exit(1)

    cookie_list = [c for c in COOKIES_STR.replace(',', '\n').split('\n') if c.strip()]
    final_report = "🌐 **域名轮询检查报告 (Playwright 驱动)**\n\n"
    
    async with async_playwright() as p:
        # 启动 chromium 浏览器
        browser = await p.chromium.launch(headless=True)
        # 创建一个占位 context 传递句柄
        context = await browser.new_context()
        context.browser = browser
        
        for i, ck in enumerate(cookie_list, 1):
            final_report += await process_account(context, ck, i)
            
        await browser.close()
    
    print(final_report)
    send_tg(final_report)

if __name__ == "__main__":
    asyncio.run(main())
