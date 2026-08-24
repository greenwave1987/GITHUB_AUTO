import os
import asyncio
import json
import urllib.request
import io
from datetime import datetime

from playwright.async_api import async_playwright


COOKIES_STR = os.getenv("DOMAIN_COOKIE")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

BASE_URL = "https://dash.domain.digitalplat.org/_panel_api/api"


def send_tg_photo(caption, image_bytes):
    """通过 sendPhoto 接口发送带有文字说明的图片到 Telegram"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"

    # 构建 multipart/form-data 请求体
    body = []
    
    # 1. 添加入参 chat_id
    body.append(f"--{boundary}".encode("utf-8"))
    body.append(f'Content-Disposition: form-data; name="chat_id"'.encode("utf-8"))
    body.append(b"")
    body.append(str(TG_CHAT_ID).encode("utf-8"))

    # 2. 添加入参 caption
    body.append(f"--{boundary}".encode("utf-8"))
    body.append(f'Content-Disposition: form-data; name="caption"'.encode("utf-8"))
    body.append(b"")
    body.append(caption.encode("utf-8"))

    # 3. 添加入参 parse_mode
    body.append(f"--{boundary}".encode("utf-8"))
    body.append(f'Content-Disposition: form-data; name="parse_mode"'.encode("utf-8"))
    body.append(b"")
    body.append(b"Markdown")

    # 4. 添加图片文件二进制数据
    body.append(f"--{boundary}".encode("utf-8"))
    body.append(f'Content-Disposition: form-data; name="photo"; filename="screenshot.png"'.encode("utf-8"))
    body.append(b"Content-Type: image/png")
    body.append(b"")
    body.append(image_bytes)

    # 结束标志
    body.append(f"--{boundary}--".encode("utf-8"))
    body.append(b"")

    payload = b"\r\n".join(body)

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"TG图片发送失败: {e}")


def parse_cookie_to_playwright(
        cookie_str,
        domain_host="dash.domain.digitalplat.org"
):
    cookies = []
    for item in cookie_str.strip().split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": domain_host,
            "path": "/"
        })
    return cookies


async def process_account(
        browser,
        cookie_str,
        index
):
    report = f"👤 **账号 #{index}**\n"
    screenshot_bytes = None

    account_context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800}  # 显式设定尺寸以保障截图清晰
    )

    await account_context.add_cookies(
        parse_cookie_to_playwright(cookie_str)
    )

    page = await account_context.new_page()

    try:
        await page.goto(
            "https://dash.domain.digitalplat.org/domains",
            timeout=30000,
            wait_until="networkidle"
        )

        # 可以在获取 API 前或处理完后截图，此处直接对当前域名页面截图
        screenshot_bytes = await page.screenshot(full_page=True)

        result = await page.evaluate(
            """
            async (url)=>{
                const res = await fetch(url, {
                    headers: { "accept": "application/json" }
                });
                return {
                    status: res.status,
                    text: await res.text()
                };
            }
            """,
            f"{BASE_URL}/domains"
        )

        if result["status"] == 403:
            return report + "❌ WAF拦截 403\n", screenshot_bytes

        try:
            data = json.loads(result["text"])
        except:
            return report + "❌ JSON解析失败\n", screenshot_bytes

        if not data.get("ok"):
            return report + "❌ 登录失效\n", screenshot_bytes

        domains = data.get("domains", [])

        if not domains:
            return report + "❓ 无域名\n", screenshot_bytes

        for d in domains:
            domain = d.get("domain")
            expiry = d.get("expiry_date")

            if not domain:
                continue

            expiry_date = datetime.strptime(expiry, "%Y%m%d")
            days = (expiry_date - datetime.now()).days

            info = f"- `{domain}`: 剩余 `{days}` 天 "

            if days < 100:
                renew_result = await page.evaluate(
                    """
                    async ({url})=>{
                        const res = await fetch(url, {
                            method: "POST",
                            headers: { "content-type": "application/json" },
                            body: JSON.stringify({ renewal_type: "free", years: 1 })
                        });
                        return {
                            status: res.status,
                            text: await res.text()
                        };
                    }
                    """,
                    {"url": f"{BASE_URL}/domains/{domain}/renew"}
                )

                try:
                    renew_data = json.loads(renew_result["text"])
                    if renew_result["status"] == 200 and renew_data.get("ok"):
                        info += "✅ **已续期**\n"
                    else:
                        info += f"⚠️ **续期失败 {renew_result['status']}**\n"
                except:
                    info += "⚠️ 返回异常\n"
            else:
                info += "😴 状态良好\n"

            report += info

    except Exception as e:
        report += f"💥 运行异常: {e}\n"
    finally:
        await account_context.close()

    return report + "\n", screenshot_bytes


async def main():
    if not COOKIES_STR:
        print("未找到 DOMAIN_COOKIE")
        return

    cookie_list = [
        x.strip()
        for x in COOKIES_STR.replace("----", "\n").replace(",", "\n").splitlines()
        if x.strip()
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        for i, ck in enumerate(cookie_list, start=1):
            account_report, screenshot = await process_account(browser, ck, i)
            print(account_report)

            # 每个账号推送一条带有对应截图的报告
            if screenshot:
                send_tg_photo(account_report, screenshot)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
