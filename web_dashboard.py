"""
Web 仪表盘 —— 手机浏览器实时监控冲榜进度。

使用 Python 内置 http.server + JSON 文件状态共享,
无需任何额外依赖。

用法:
    python web_dashboard.py                    # 默认端口 8080
    python web_dashboard.py --port 9090        # 指定端口
    python web_dashboard.py --bind 0.0.0.0     # 允许局域网访问

冲榜时自动写入状态文件, 浏览器打开即可查看实时进度。
"""

import argparse
import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

# 状态文件路径 (由 BatchPlayer 写入)
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".batch_stats.json")

# ── HTML 模板 ──

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="3">
<title>PJSK Auto Player - 冲榜仪表盘</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9;
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; padding: 20px;
}}
.container {{ max-width: 600px; width: 100%; }}
h1 {{ font-size: 1.5rem; color: #58a6ff; text-align: center; margin: 16px 0 8px; }}
.subtitle {{ text-align: center; color: #8b949e; font-size: 0.85rem; margin-bottom: 20px; }}
.card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 20px; margin-bottom: 16px;
}}
.card-title {{ font-size: 0.75rem; text-transform: uppercase; color: #8b949e; letter-spacing: 0.5px; margin-bottom: 12px; }}
.stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.8rem; font-weight: 700; color: #f0f6fc; }}
.stat-label {{ font-size: 0.75rem; color: #8b949e; margin-top: 2px; }}
.big-stat .stat-value {{ font-size: 2.5rem; }}
.running {{ color: #3fb950; }} .stopped {{ color: #f85149; }}
.log-box {{
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    padding: 12px; font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.8rem; max-height: 240px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-all;
    color: #7d8590; line-height: 1.5;
}}
.footer {{ text-align: center; color: #484f58; font-size: 0.75rem; margin-top: 8px; }}
</style>
</head>
<body>
<div class="container">
<h1>🎵 PJSK Auto Player</h1>
<p class="subtitle" id="status">冲榜仪表盘 · <span class="{status_class}">{status_text}</span></p>

<div class="card">
    <div class="card-title">进度</div>
    <div class="stat-grid">
        <div class="stat big-stat">
            <div class="stat-value">{songs_played}</div>
            <div class="stat-label">已完成 / {target_label}</div>
        </div>
        <div class="stat">
            <div class="stat-value">{songs_failed}</div>
            <div class="stat-label">失败</div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-title">运行</div>
    <div class="stat-grid">
        <div class="stat">
            <div class="stat-value">{elapsed:.0f}s</div>
            <div class="stat-label">运行时间</div>
        </div>
        <div class="stat">
            <div class="stat-value">{avg_time:.1f}s</div>
            <div class="stat-label">平均每首</div>
        </div>
        <div class="stat">
            <div class="stat-value">{fps:.1f}</div>
            <div class="stat-label">FPS</div>
        </div>
        <div class="stat">
            <div class="stat-value">{latency_comp}ms</div>
            <div class="stat-label">延迟补偿</div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-title">操作</div>
    <div class="stat-grid">
        <div class="stat">
            <div class="stat-value">{total_taps}</div>
            <div class="stat-label">点击</div>
        </div>
        <div class="stat">
            <div class="stat-value">{total_flicks}</div>
            <div class="stat-label">Flick</div>
        </div>
        <div class="stat">
            <div class="stat-value">{total_holds}</div>
            <div class="stat-label">长按</div>
        </div>
        <div class="stat">
            <div class="stat-value">{total_frames}</div>
            <div class="stat-label">帧数</div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-title">日志</div>
    <div class="log-box">{log_text}</div>
</div>

<div class="footer">
    自动刷新 (3s) · v{version}
</div>
</div>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。"""

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = self._render()
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/stats.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self._get_stats_json().encode())
        elif self.path == "/api/stop":
            self._write_action("stop")
            self._redirect("/")
        else:
            self.send_response(404)
            self.end_headers()

    def _render(self) -> str:
        """渲染 HTML 页面。"""
        stats = self._get_stats()

        return HTML.format(
            status_class="running" if stats.get("running") else "stopped",
            status_text="运行中 🔥" if stats.get("running") else "已停止 ⏹",
            songs_played=stats.get("songs_played", 0),
            target_label=f"{stats.get('target', 0)} 首" if stats.get("target", 0) > 0 else "∞",
            songs_failed=stats.get("songs_failed", 0),
            elapsed=stats.get("elapsed_seconds", 0),
            avg_time=stats.get("avg_song_time", 0),
            fps=stats.get("fps", 0),
            latency_comp=stats.get("latency_comp_ms", 0),
            total_taps=stats.get("total_taps", 0),
            total_flicks=stats.get("total_flicks", 0),
            total_holds=stats.get("total_holds", 0),
            total_frames=stats.get("total_frames", 0),
            log_text=self._escape_html(stats.get("log", "-")),
            version=stats.get("version", "3.1.0"),
        )

    def _get_stats(self) -> dict:
        """从状态文件读取统计数据。"""
        default = {
            "running": False, "songs_played": 0, "songs_failed": 0,
            "elapsed_seconds": 0, "avg_song_time": 0, "fps": 0,
            "latency_comp_ms": 0, "total_taps": 0, "total_flicks": 0,
            "total_holds": 0, "total_frames": 0, "log": "", "target": 0,
            "version": "3.1.0",
        }
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, "r") as f:
                    return {**default, **json.load(f)}
        except (json.JSONDecodeError, OSError):
            pass
        return default

    def _get_stats_json(self) -> str:
        return json.dumps(self._get_stats(), ensure_ascii=False)

    def _write_action(self, action: str):
        """写入控制指令 (供 BatchPlayer 读取)。"""
        action_file = os.path.join(os.path.dirname(STATS_FILE), ".batch_action.json")
        try:
            with open(action_file, "w") as f:
                json.dump({"action": action, "timestamp": time.time()}, f)
        except OSError:
            pass

    def _redirect(self, path: str):
        self.send_response(302)
        self.send_header("Location", path)
        self.end_headers()

    def _escape_html(self, text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;"))

    def log_message(self, format, *args):
        """静默日志。"""
        pass


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """启动 HTTP 服务器。"""
    server = HTTPServer((host, port), DashboardHandler)
    print(f"🌐 PJSK 冲榜仪表盘: http://{host}:{port}")
    print(f"   手机浏览器打开此地址即可实时监控")
    print(f"   按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n仪表盘已停止")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="PJSK Auto Player - Web 仪表盘")
    parser.add_argument("--port", type=int, default=8080, help="端口 (默认: 8080)")
    parser.add_argument("--bind", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    args = parser.parse_args()

    run_server(host=args.bind, port=args.port)


if __name__ == "__main__":
    main()
