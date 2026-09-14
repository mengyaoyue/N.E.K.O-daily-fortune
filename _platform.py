"""猫娘每日关怀 · 本地平台网页（附属网页，仅监听 127.0.0.1）

聊天窗口显示不了图片 → 插件起一个本地小服务，浏览器打开即是
「运势卡 + 今日老婆卡 + 幸运排行 + 货币余额」的平台页面。

零第三方依赖：http.server（ThreadingHTTPServer）+ 纯字符串拼 HTML。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-.]+\.(?:png|jpe?g|gif|webp|bmp|img)$")


def _guess_image_ctype(data: bytes) -> str:
    """按魔数判断图片类型：图站返回的可能是 jpg/png/webp，扩展名不可信。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/png"


_PAGE_CSS = """
body{margin:0;font-family:'Microsoft YaHei',sans-serif;background:#1b1826;color:#e8e4f2;
display:flex;justify-content:center;padding:24px}
.wrap{max-width:860px;width:100%}
h1{font-size:26px;margin:8px 0 4px}
.sub{color:#9a93b5;font-size:14px;margin-bottom:20px}
.cards{display:flex;gap:18px;flex-wrap:wrap}
.card{background:#241f33;border:1px solid #3a3352;border-radius:16px;padding:14px;flex:1;min-width:340px}
.card img{width:100%;border-radius:10px;display:block}
.card h2{font-size:18px;margin:4px 0 10px;color:#c9b9ff}
.card.art img{margin-top:10px;display:none;max-height:600px;object-fit:contain;background:#2a2440}
.news{margin-top:10px;font-size:14px;line-height:1.7;color:#d6d0ea}
.news ol{margin:0;padding-left:22px}
.rank{background:#241f33;border:1px solid #3a3352;border-radius:16px;padding:16px;margin-top:18px}
.rank table{width:100%;border-collapse:collapse;font-size:15px}
.rank td{padding:7px 6px;border-bottom:1px solid #322b4a}
.rank .me{background:#2e2745;border-radius:8px}
.medal{font-size:17px}
button{background:#6c5ce7;color:#fff;border:0;border-radius:10px;padding:8px 18px;font-size:14px;cursor:pointer}
button:hover{background:#7d6ef0}
a{color:#9a8fd8}
"""


def build_index_html(
    today: str,
    fortune_img: str,
    wife_img: str,
    fortune_text: str,
    wife_text: str,
    rank_rows: list[dict[str, Any]],
    user_name: str,
    me: Optional[dict[str, Any]],
    catgirl_name: str = "猫娘",
    art_enabled: bool = True,
    news_enabled: bool = True,
) -> str:
    """拼平台首页 HTML。图片路径是相对 URL（/cards/xxx.png）。"""
    rows_html = ""
    medals = ("🥇", "🥈", "🥉")
    if rank_rows:
        for i, row in enumerate(rank_rows[:10]):
            medal = medals[i] if i < len(medals) else f"{i + 1}"
            me_class = ' class="me"' if me and row.get("user_id") == me.get("user_id") else ""
            rows_html += (
                f"<tr{me_class}><td class='medal'>{medal}</td>"
                f"<td>{row.get('name')}</td>"
                f"<td>累计 {row.get('total_luck', 0):+d}</td>"
                f"<td>今日 {row.get('today', 0):+d}</td></tr>"
            )
    else:
        rows_html = "<tr><td>还没有记录，快来抽第一签喵～</td></tr>"

    coins_html = ""
    if me:
        coins = me.get("coins") or {}
        coins_html = (
            f"<div class='sub'>我的钱包：🪙 银币 {coins.get('silver', 0)}　"
            f"💠 金币 {coins.get('gold', 0)}</div>"
        )

    art_card = ""
    if art_enabled:
        art_card = (
            "<div class='card art'><h2>🎨 随机美图（全年龄）</h2>"
            "<button onclick='loadArt()'>换一张</button>"
            "<img id='artImg' alt='随机美图'>"
            "<div class='sub' id='artStatus'>safebooru 全年龄向，点「换一张」可无上限刷新喵</div></div>"
        )
    news_card = ""
    if news_enabled:
        news_card = (
            "<div class='card'><h2>📰 今日热点</h2>"
            "<button onclick='loadNews()'>刷新</button>"
            "<div class='news' id='newsList'>点「刷新」拉取今日热点喵～</div></div>"
        )

    index_script = (_ART_SCRIPT if art_enabled else "") + (_NEWS_SCRIPT if news_enabled else "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{catgirl_name}的每日关怀平台</title><style>{_PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🐾 {catgirl_name}的每日关怀平台</h1>
<div class="sub">{today}　·　{user_name} 的专属运势与老婆记录</div>
{coins_html}
<div class="cards">
<div class="card"><h2>🔮 今日运势签</h2><img src="{fortune_img}" alt="运势签">
<div class="sub">{fortune_text}</div></div>
<div class="card"><h2>💃 今日老婆</h2><img src="{wife_img}" alt="今日老婆">
<div class="sub">{wife_text}</div></div>
{art_card}
{news_card}
</div>
<div class="rank"><h2>🏆 幸运排行榜（累计）</h2>
<table><tr><td></td><td>用户</td><td>累计幸运</td><td>今日</td></tr>{rows_html}</table></div>
<div class="sub">本页面仅本机可访问（127.0.0.1），由猫娘每日关怀插件提供 · 换一天自动换卡喵～</div>
</div>{index_script}</body></html>"""


_ART_SCRIPT = """<script>
async function loadArt(){
  const st=document.getElementById("artStatus");
  const img=document.getElementById("artImg");
  if(!st||!img)return;
  st.textContent="正在拉图喵…";
  try{
    const r=await fetch("/api/art?t="+Date.now());
    const d=await r.json();
    if(!d.ok){st.textContent="图站没搜到，再点一次喵～";return;}
    img.src=d.img+"?t="+Date.now();
    img.style.display="block";
    st.textContent="已换新图喵（可以继续点，刷新无上限）";
  }catch(e){st.textContent="加载失败："+e;}
}
</script>"""

_NEWS_SCRIPT = """<script>
async function loadNews(){
  const box=document.getElementById("newsList");
  if(!box)return;
  box.textContent="正在拉取热点喵…";
  try{
    const r=await fetch("/api/news?t="+Date.now());
    const d=await r.json();
    if(!d.items||!d.items.length){box.textContent="今日热点没拉到喵，稍后再试。";return;}
    box.innerHTML="<ol>"+d.items.slice(0,10).map(x=>`<li>${x}</li>`).join("")+"</ol>";
  }catch(e){box.textContent="加载失败："+e;}
}
</script>"""


class PlatformServer:
    """本地平台服务：线程化 HTTP 服务器，数据由插件提供（data_provider 回调）。"""

    def __init__(
        self,
        port: int,
        cards_dir: Path,
        data_provider: Callable[[str], dict[str, Any]],
        art_provider: Optional[Callable[[], str]] = None,
        news_provider: Optional[Callable[[], list[str]]] = None,
    ):
        self.port = int(port)
        self.cards_dir = Path(cards_dir)
        self._data_provider = data_provider  # user_id -> {today, fortune_img, wife_img, ...}
        self._art_provider = art_provider    # () -> "/cards/art_xxx.img" or ""
        self._news_provider = news_provider  # () -> [str, ...]
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """启动服务；端口被占用时返回 False（不影响插件主流程）。"""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # 静默访问日志
                pass

            def _send(self, body: bytes, ctype: str):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)
                route = path[0]
                query = path[1] if len(path) > 1 else ""
                if route == "/api/summary":
                    user_id = "local"
                    for kv in query.split("&"):
                        if kv.startswith("user="):
                            user_id = kv[5:] or "local"
                    try:
                        data = outer._data_provider(user_id)
                    except Exception:
                        self.send_error(500)
                        return
                    payload = {
                        "today": data["today"],
                        "user_name": data["user_name"],
                        "fortune_img": data["fortune_img"],
                        "wife_img": data["wife_img"],
                        "fortune_text": data["fortune_text"],
                        "wife_text": data["wife_text"],
                        "rank_rows": data["rank_rows"],
                        "coins": (data.get("me") or {}).get("coins", {"silver": 0, "gold": 0}),
                        "art_enabled": bool(data.get("art_enabled", True)),
                        "news_enabled": bool(data.get("news_enabled", True)),
                    }
                    self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                elif route == "/api/art":
                    img = ""
                    if outer._art_provider is not None:
                        try:
                            img = outer._art_provider() or ""
                        except Exception:
                            img = ""
                    payload = {"ok": bool(img), "img": img}
                    self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                elif route == "/api/news":
                    items: list[str] = []
                    if outer._news_provider is not None:
                        try:
                            items = list(outer._news_provider() or [])
                        except Exception:
                            items = []
                    payload = {"items": items}
                    self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                elif route in ("/", "/index.html"):
                    user_id = "local"
                    for kv in query.split("&"):
                        if kv.startswith("user="):
                            user_id = kv[5:] or "local"
                    try:
                        data = outer._data_provider(user_id)
                    except Exception:
                        self.send_error(500)
                        return
                    body = build_index_html(
                        data["today"], data["fortune_img"], data["wife_img"],
                        data["fortune_text"], data["wife_text"], data["rank_rows"],
                        data["user_name"], data.get("me"), data["catgirl_name"],
                        art_enabled=bool(data.get("art_enabled", True)),
                        news_enabled=bool(data.get("news_enabled", True)),
                    ).encode("utf-8")
                    self._send(body, "text/html; charset=utf-8")
                elif route.startswith("/cards/"):
                    name = route[len("/cards/"):]
                    if not _FILE_NAME_RE.match(name):
                        self.send_error(404)
                        return
                    file_path = outer.cards_dir / name
                    if not file_path.is_file():
                        self.send_error(404)
                        return
                    body = file_path.read_bytes()
                    self._send(body, _guess_image_ctype(body))
                else:
                    self.send_error(404)

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            return False
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="neko-fortune-platform"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
