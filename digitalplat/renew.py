import os
import asyncio
import json
import urllib.request
from datetime import datetime
from playwright.async_api import async_playwright

COOKIES_STR=os.getenv("DOMAIN_COOKIE")
TG_BOT_TOKEN=os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID=os.getenv("TG_CHAT_ID")
BASE_URL="https://dash.domain.digitalplat.org/_panel_api/api"

def send_tg(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url=f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload={"chat_id":TG_CHAT_ID,"text":message,"parse_mode":"Markdown"}
    try:
        req=urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type":"application/json"}
        )
        urllib.request.urlopen(req,timeout=10)
    except Exception as e:
        print(f"TG发送失败:{e}")

def parse_cookie_to_playwright(cookie_str,domain_host="dash.domain.digitalplat.org"):
    cookies=[]
    for item in cookie_str.strip().split(";"):
        if "=" not in item:
            continue
        name,value=item.split("=",1)
        cookies.append({
            "name":name.strip(),
            "value":value.strip(),
            "domain":domain_host,
            "path":"/"
        })
    return cookies

async def process_account(browser,cookie_str,index):
    report=f"👤 **账号 #{index}**\n"
    account_context=await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
    await account_context.add_cookies(parse_cookie_to_playwright(cookie_str))
    page=await account_context.new_page()
    try:
        await page.goto(
            "https://dash.domain.digitalplat.org/domains",
            timeout=30000,
            wait_until="networkidle"
        )
        result=await page.evaluate(
            """
            async(url)=>{
                const res=await fetch(url,{
                    headers:{
                        "accept":"application/json"
                    }
                });
                return {
                    status:res.status,
                    text:await res.text()
                };
            }
            """,
            f"{BASE_URL}/domains"
        )
        if result["status"]==403:
            return report+"❌ WAF拦截403\n"
        try:
            data=json.loads(result["text"])
        except:
            return report+"❌ JSON解析失败\n"
        if not data.get("ok"):
            return report+"❌ 登录失效\n"
        domains=data.get("domains",[])
        if not domains:
            return report+"❓ 无域名\n"
        for d in domains:
            domain=d.get("domain")
            expiry=d.get("expiry_date")
            if not domain or not expiry:
                continue
            expiry_date=datetime.strptime(expiry,"%Y%m%d")
            days=(expiry_date-datetime.now()).days
            info=f"- `{domain}`: 剩余 `{days}` 天 "
            if days<100:
                renew_result=await page.evaluate(
                    """
                    async({url})=>{
                        const res=await fetch(url,{
                            method:"POST",
                            headers:{
                                "content-type":"application/json"
                            },
                            body:JSON.stringify({
                                renewal_type:"free",
                                years:1
                            })
                        });
                        return {
                            status:res.status,
                            text:await res.text()
                        };
                    }
                    """,
                    {"url":f"{BASE_URL}/domains/{domain}/renew"}
                )
