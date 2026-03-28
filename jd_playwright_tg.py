name: JD Playwright Login (ChatID Version)

on:
  workflow_dispatch:

jobs:
  run_login:
    runs-on: ubuntu-latest
    env:
      TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
      TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}  # 修改此处引用
      PYTHONUNBUFFERED: 1

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install Playwright
        run: |
          pip install playwright requests
          playwright install chromium --with-deps

      - name: Execute Script
        run: python jd_playwright_tg.py
