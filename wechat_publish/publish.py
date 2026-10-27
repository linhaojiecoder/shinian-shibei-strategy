#!/usr/bin/env python3
"""
慢富十倍·复利策略 · 公众号自动发草稿脚本
====================================================
流程：
  1. 读 app_1.0/src/data.json（当天收盘数据）
  2. 生成「说真话散户视角」点评文案
  3. 用 Chrome headless 截图复盘报告顶部当封面
  4. 转成公众号 HTML（微信只认内联样式）
  5. 上传封面到微信素材库 → draft/add 建草稿
  6. 幂等去重：同一天只建一篇草稿（防止复盘自动化重复触发导致刷屏）

用法：
  python3 wechat_publish/publish.py          # 正常发布（建草稿）
  python3 wechat_publish/publish.py --dry    # 只生成文章+封面，不调微信接口
  python3 wechat_publish/publish.py --force  # 忽略去重锁，强制重发

依赖：仅标准库 + Chrome（截图用）。无需 pip install。

配置：wechat_publish/config.local.json（从 .example 复制并填 AppID/AppSecret）
"""
import json
import os
import sys
import time
import datetime
import subprocess
import urllib.request
import urllib.parse
import uuid

BASE = "/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24"
DATA = os.path.join(BASE, "app_1.0", "src", "data.json")
REPORT_HTML = os.path.join(BASE, "backtest_data", "复盘报告.html")
PUB_DIR = os.path.join(BASE, "wechat_publish")
CONFIG = os.path.join(PUB_DIR, "config.local.json")
LOCK_FILE = os.path.join(PUB_DIR, "published_lock.json")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

DRY = "--dry" in sys.argv
FORCE = "--force" in sys.argv


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def load_config():
    if not os.path.exists(CONFIG):
        log(f"❌ 缺少配置 {CONFIG}")
        log("   请复制 config.local.json.example 为 config.local.json 并填入 AppID/AppSecret")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


# ---------- 1. 读数据 ----------
def load_data():
    with open(DATA) as f:
        return json.load(f)


# ---------- 2. 生成点评文案（说真话散户视角） ----------
def build_commentary(d):
    L = d["latest_state"]
    s = d["summary"]
    latest = d["latest_date"]
    action = d["today_action"]
    total = L["total"]
    today_pnl = L.get("today_pnl", 0)
    asset_change = L.get("asset_change", 0)
    total_ret = s["total_ret"]
    holdings = L.get("holdings", {})

    # 当日涨跌
    day_pct = (today_pnl / (total - today_pnl) * 100) if (total - today_pnl) else 0
    day_word = "涨" if today_pnl >= 0 else "跌"
    day_color_word = "红" if today_pnl >= 0 else "绿"

    # 持仓概况
    hold_lines = []
    for name, h in holdings.items():
        pnl = h.get("total_pnl", 0)
        pct = (pnl / (h["shares"] * h["cost"]) * 100) if h.get("cost") else 0
        arrow = "↑" if pnl >= 0 else "↓"
        hold_lines.append(f"{name}：{arrow} {pct:+.2f}%（{pnl/10000:+.1f}万）")
    hold_text = "；".join(hold_lines) if hold_lines else "当前空仓"

    # 今日操作
    action_text = action.get("title", "继续持有")
    action_detail = action.get("detail", "")

    # 五标的动量（判断市场温度）
    signals = d.get("signals", [])
    mom_list = [s["mom"] for s in signals]
    positive_cnt = sum(1 for m in mom_list if m > 0)
    market_temp = "冰点" if positive_cnt == 0 else ("偏冷" if positive_cnt <= 1 else ("中性" if positive_cnt <= 2 else ("偏热" if positive_cnt <= 3 else "过热")))

    title = f"{latest} 复盘｜今日{day_word}{abs(day_pct):.2f}%，{action_text}"

    # 说真话风格的点评正文（结构化，后面转 HTML）
    paras = [
        f"今天账户{day_word}了 {abs(today_pnl)/10000:.2f} 万（{day_pct:+.2f}%），总资产 ¥{total/10000:,.0f} 万。这一天又是{day_color_word}的，但先别急着高兴或者慌，咱把账拆开看。",
        f"累计收益 {total_ret:+.2f}%，从 2014 年 300 万本金滚到现在。数字看着唬人，但那是十二年复利堆出来的，不是一天两天的事。今天这点波动，在长期曲线里就是个小数点。",
        f"持仓就俩：{hold_text}。",
        f"今日操作：{action_text}。{action_detail}",
        f"五标的动量全在 0 轴下方趴着，市场温度是「{market_temp}」。这种时候策略老老实实不动手，就是最好的动作。散户最容易亏在「手痒」上——没信号硬找信号，没机会硬做机会。",
        f"说句实话：这套东西不性感，不抓涨停，也不会让你一夜暴富。它赚的就是「少犯错」的钱。你要的是慢慢变富，那就得接受它大部分时间看起来「什么都没做」。",
    ]
    return title, paras, action_text


# ---------- 3. 截图封面 ----------
def capture_cover(latest):
    cover_path = os.path.join(PUB_DIR, f"cover_{latest}.png")
    if os.path.exists(cover_path):
        log(f"封面已存在，跳过截图：{cover_path}")
        return cover_path
    # 公众号封面比例 2.35:1（约 900×383）。截取报告顶部标题+三卡+预告条区域，
    # 用较矮的视口 + 较小 device-scale，保证裁出来是横版、信息不被压扁。
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--allow-file-access-from-files",
        "--window-size=1000,426", "--force-device-scale-factor=2",
        f"--screenshot={cover_path}",
        "--virtual-time-budget=8000",
        f"file://{REPORT_HTML}",
    ]
    log("截图封面中...")
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if os.path.exists(cover_path) and os.path.getsize(cover_path) > 10000:
        log(f"✅ 封面截图成功：{cover_path}（{os.path.getsize(cover_path)//1024}KB）")
        return cover_path
    log(f"⚠️ 截图失败：{r.stderr.decode()[-200:]}")
    return None


# ---------- 4. 转公众号 HTML（内联样式） ----------
def build_article_html(title, paras, d):
    """把点评文案转成公众号可用的 HTML（内联样式，微信会过滤 class/style 之外的东西）"""
    L = d["latest_state"]
    total = L["total"]
    today_pnl = L.get("today_pnl", 0)
    total_ret = d["summary"]["total_ret"]
    holdings = L.get("holdings", {})

    RED = "#e24b4a"
    GREEN = "#1d9e75"
    up = RED if today_pnl >= 0 else GREEN

    # 持仓表格
    rows = ""
    for name, h in holdings.items():
        pnl = h.get("total_pnl", 0)
        cost = h.get("cost", 0)
        pct = (pnl / (h["shares"] * cost) * 100) if cost else 0
        color = RED if pnl >= 0 else GREEN
        rows += f'<tr><td style="padding:8px;border-bottom:1px solid #eee;">{name}</td>' \
                f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{h["shares"]:,}</td>' \
                f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{cost:.4f}</td>' \
                f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:right;color:{color};font-weight:bold;">{pct:+.2f}%</td></tr>'

    # 顶部数据卡
    html = f'''
<section style="margin:0 0 20px;">
  <h1 style="font-size:22px;font-weight:bold;margin:0 0 4px;color:#1a1a1a;">慢富十倍 · 复利策略 每日复盘</h1>
  <p style="font-size:13px;color:#999;margin:0;">慢慢变富，与时间为友 · A股 ETF 动量轮动</p>
</section>

<section style="background:#f7f8fa;border-radius:12px;padding:16px;margin:0 0 16px;">
  <div style="font-size:13px;color:#666;">今日盈亏</div>
  <div style="font-size:28px;font-weight:bold;color:{up};margin:4px 0;">{today_pnl:+,.0f}</div>
  <div style="font-size:13px;color:#666;">总资产 ¥{total:,.0f} · 累计收益 <span style="color:{up};">{total_ret:+.2f}%</span></div>
</section>

<section style="margin:0 0 20px;">
  <h2 style="font-size:17px;font-weight:bold;color:#1a1a1a;margin:0 0 12px;border-left:4px solid {up};padding-left:10px;">今日点评</h2>
  {''.join(f'<p style="font-size:15px;line-height:1.8;color:#333;margin:0 0 14px;">{p}</p>' for p in paras)}
</section>

<section style="margin:0 0 20px;">
  <h2 style="font-size:17px;font-weight:bold;color:#1a1a1a;margin:0 0 12px;border-left:4px solid #333;padding-left:10px;">当前持仓</h2>
  <table style="width:100%;border-collapse:collapse;font-size:14px;">
    <tr style="background:#f7f8fa;">
      <th style="padding:8px;text-align:left;border-bottom:1px solid #eee;">标的</th>
      <th style="padding:8px;text-align:right;border-bottom:1px solid #eee;">份额</th>
      <th style="padding:8px;text-align:right;border-bottom:1px solid #eee;">成本</th>
      <th style="padding:8px;text-align:right;border-bottom:1px solid #eee;">盈亏</th>
    </tr>
    {rows}
  </table>
</section>

<section style="font-size:12px;color:#bbb;margin:24px 0 0;padding-top:12px;border-top:1px solid #eee;">
  数据口径：不复权真实价 · 自动生成，仅供个人复盘参考，不构成投资建议。
</section>
'''
    return html


# ---------- 5. 微信 API ----------
class WechatClient:
    def __init__(self, cfg):
        self.appid = cfg["appid"]
        self.secret = cfg["secret"]
        self.token = None
        self.token_expire = 0

    def _req(self, url, data=None, is_json=True, timeout=30):
        headers = {}
        body = None
        if data is not None:
            if is_json:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            else:
                body = data
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_token(self):
        if self.token and time.time() < self.token_expire:
            return self.token
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.appid}&secret={self.secret}"
        r = self._req(url)
        if "access_token" not in r:
            raise RuntimeError(f"获取 token 失败：{r}")
        self.token = r["access_token"]
        self.token_expire = time.time() + int(r.get("expires_in", 7200)) - 300
        return self.token

    def upload_cover(self, img_path):
        """上传永久图片素材，返回 thumb_media_id"""
        token = self.get_token()
        boundary = uuid.uuid4().hex
        filename = os.path.basename(img_path)
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        if "media_id" not in data:
            raise RuntimeError(f"封面上传失败：{data}")
        return data["media_id"]

    def add_draft(self, title, digest, html_body, thumb_media_id, author):
        token = self.get_token()
        payload = {
            "articles": [{
                "title": title,
                "author": author,
                "digest": digest,
                "content": html_body,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
            }]
        }
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
        r = self._req(url, payload)
        if "media_id" not in r:
            raise RuntimeError(f"建草稿失败：{r}")
        return r["media_id"]


# ---------- 6. 幂等去重锁 ----------
def check_lock(latest):
    """同一天已建草稿则跳过。返回 (是否跳过, 锁内容)"""
    if FORCE:
        return False, None
    if not os.path.exists(LOCK_FILE):
        return False, None
    with open(LOCK_FILE) as f:
        lock = json.load(f)
    return lock.get("date") == latest, lock


def write_lock(latest, media_id):
    with open(LOCK_FILE, "w") as f:
        json.dump({"date": latest, "media_id": media_id, "time": datetime.datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


def main():
    log("=" * 50)
    log("慢富十倍 · 公众号自动发草稿")

    d = load_data()
    latest = d["latest_date"]
    title, paras, action_text = build_commentary(d)

    log(f"数据截至 {latest}，标题：{title}")

    # 幂等去重
    skip, lock = check_lock(latest)
    if skip:
        log(f"⏭️ 今天（{latest}）已建过草稿（media_id={lock.get('media_id')}），跳过。")
        log("   如需重发，用 --force。")
        return

    # 生成文章 HTML
    html_body = build_article_html(title, paras, d)
    article_file = os.path.join(PUB_DIR, f"article_{latest}.html")
    with open(article_file, "w") as f:
        f.write(html_body)
    log(f"✅ 文章已生成：{article_file}")

    # 截图封面
    cover = capture_cover(latest)

    if DRY:
        log("--dry 模式：只生成文章+封面，不调微信接口。")
        log(f"   文章：{article_file}")
        log(f"   封面：{cover}")
        return

    # 调微信接口
    cfg = load_config()
    client = WechatClient(cfg)
    try:
        log("上传封面...")
        thumb_id = client.upload_cover(cover)
        log(f"✅ 封面 media_id = {thumb_id}")

        digest = paras[0][:50]  # 摘要取第一段前50字
        log("建草稿...")
        media_id = client.add_draft(title, digest, html_body, thumb_id, cfg.get("author", "慢富十倍"))
        log(f"✅ 草稿已建好：media_id = {media_id}")
        log("📱 去手机公众号后台 → 内容管理 → 草稿箱 → 点「发表」即可（约10秒）")

        write_lock(latest, media_id)
    except Exception as e:
        log(f"❌ 发布失败：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
