"""
PJSK Auto Player — Web 控制台 (MAA 风格)

提供完整的可视化操作界面:
  - 实时仪表盘 (FPS/进度/统计)
  - 启动/停止/暂停控制
  - 实时日志查看
  - 手机画面预览
  - 配置编辑
  - 歌单/编队管理

使用方式:
  python main.py web            # 启动控制台
  python main.py web --port 8080 # 指定端口
"""

import argparse
import base64
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

logger = logging.getLogger("pjsk_web")

# ── 路径 ──
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_FILE = os.path.join(ROOT_DIR, ".batch_stats.json")
ACTION_FILE = os.path.join(ROOT_DIR, ".batch_action.json")

# ── HTML 模板 (单页应用, 现代暗色主题) ──

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PJSK Auto Player</title>
<style>
:root { --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #c9d1d9; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:var(--bg); color:var(--text); height:100vh; display:flex; }

/* ── Layout ── */
.sidebar { width:240px; background:var(--surface); border-right:1px solid var(--border);
  display:flex; flex-direction:column; flex-shrink:0; }
.sidebar-header { padding:20px; border-bottom:1px solid var(--border); }
.sidebar-header h1 { font-size:16px; color:var(--accent); }
.sidebar-header .ver { font-size:11px; color:var(--text-dim); margin-top:4px; }
.nav-item { padding:12px 20px; cursor:pointer; display:flex; align-items:center; gap:10px;
  color:var(--text-dim); font-size:14px; border-left:3px solid transparent; transition:.15s; }
.nav-item:hover { background:#1c2128; color:var(--text); }
.nav-item.active { color:var(--text); border-left-color:var(--accent); background:#1c2128; }
.nav-icon { width:18px; text-align:center; }
.main { flex:1; overflow-y:auto; padding:24px; min-width:0; }
.page { display:none; }
.page.active { display:block; }

/* ── Cards ── */
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:20px; margin-bottom:16px; }
.card-title { font-size:12px; text-transform:uppercase; color:var(--text-dim);
  letter-spacing:.5px; margin-bottom:14px; }
.stat-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px; }
.stat { text-align:center; padding:12px; background:var(--bg); border-radius:6px; }
.stat-val { font-size:24px; font-weight:700; }
.stat-lbl { font-size:11px; color:var(--text-dim); margin-top:2px; }

/* ── Buttons ── */
.btn { padding:8px 20px; border-radius:6px; border:1px solid var(--border);
  cursor:pointer; font-size:13px; font-weight:500; transition:.15s; }
.btn-primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.btn-primary:hover { filter:brightness(1.1); }
.btn-danger { background:var(--red); color:#fff; border-color:var(--red); }
.btn-outline { background:transparent; color:var(--text); }
.btn-outline:hover { background:#1c2128; }
.btn-sm { padding:4px 12px; font-size:12px; }
.controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }

/* ── Log ── */
.log-box { background:#010409; border:1px solid var(--border); border-radius:6px;
  padding:12px; font-family:'SF Mono','Fira Code','Cascadia Code',monospace;
  font-size:12px; max-height:400px; overflow-y:auto; line-height:1.6; }
.log-line { white-space:pre-wrap; word-break:break-all; }
.log-time { color:var(--text-dim); margin-right:8px; }

/* ── Screenshot ── */
.screenshot { max-width:100%; max-height:500px; border-radius:6px;
  border:1px solid var(--border); display:block; margin:0 auto; }

/* ── Form ── */
.form-group { margin-bottom:14px; }
.form-group label { display:block; font-size:12px; color:var(--text-dim); margin-bottom:4px; }
.form-group select, .form-group input[type=text], .form-group input[type=number] {
  width:100%; padding:8px 12px; background:var(--bg); border:1px solid var(--border);
  border-radius:6px; color:var(--text); font-size:13px; }
.form-group select { cursor:pointer; }
.form-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }

/* ── Screenshot page ── */
#screenshot-img { max-width:100%; max-height:70vh; border-radius:8px;
  border:1px solid var(--border); margin:0 auto; display:block; }
.screenshot-info { text-align:center; color:var(--text-dim); font-size:12px; margin-top:8px; }

/* ── Status badge ── */
.badge { display:inline-flex; align-items:center; gap:6px; padding:4px 12px;
  border-radius:12px; font-size:12px; font-weight:500; }
.badge-running { background:rgba(63,185,80,.15); color:var(--green); }
.badge-stopped { background:rgba(139,148,158,.15); color:var(--text-dim); }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.dot-green { background:var(--green); }
.dot-gray { background:var(--text-dim); }

@media(max-width:768px){ .sidebar{width:60px} .sidebar-header h1,.sidebar-header .ver,.nav-item span{display:none} .nav-item{padding:12px;justify-content:center} .main{padding:12px} }
</style>
</head>
<body>

<!-- Sidebar -->
<div class="sidebar">
  <div class="sidebar-header">
    <h1>🎵 PJSK</h1>
    <div class="ver">v3.7.0 — Auto Player</div>
  </div>
  <div class="nav-item active" onclick="showPage('dashboard')">
    <span class="nav-icon">📊</span><span>仪表盘</span>
  </div>
  <div class="nav-item" onclick="showPage('screenshot')">
    <span class="nav-icon">📸</span><span>手机画面</span>
  </div>
  <div class="nav-item" onclick="showPage('scripts')">
    <span class="nav-icon">🎮</span><span>歌单 & 编队</span>
  </div>
  <div class="nav-item" onclick="showPage('settings')">
    <span class="nav-icon">⚙️</span><span>设置</span>
  </div>
  <div class="nav-item" onclick="showPage('about')">
    <span class="nav-icon">ℹ️</span><span>关于</span>
  </div>
</div>

<!-- Main -->
<div class="main">

<!-- Dashboard -->
<div id="page-dashboard" class="page active">
  <div class="controls">
    <span id="status-badge" class="badge badge-stopped"><span class="dot dot-gray"></span>已停止</span>
    <button class="btn btn-primary btn-sm" onclick="apiAction('start')">▶ 启动</button>
    <button class="btn btn-outline btn-sm" onclick="apiAction('stop')">⏹ 停止</button>
    <button class="btn btn-outline btn-sm" onclick="apiAction('pause')">⏸ 暂停</button>
    <button class="btn btn-outline btn-sm" onclick="apiAction('resume')">▶ 继续</button>
  </div>

  <div class="card">
    <div class="card-title">冲榜进度</div>
    <div class="stat-grid">
      <div class="stat"><div class="stat-val" id="songs-played">0</div><div class="stat-lbl">已完成</div></div>
      <div class="stat"><div class="stat-val" id="target">0</div><div class="stat-lbl">目标</div></div>
      <div class="stat"><div class="stat-val" id="songs-failed">0</div><div class="stat-lbl">失败</div></div>
      <div class="stat"><div class="stat-val" id="elapsed">0s</div><div class="stat-lbl">运行时间</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">操作统计</div>
    <div class="stat-grid">
      <div class="stat"><div class="stat-val" id="total-taps">0</div><div class="stat-lbl">点击</div></div>
      <div class="stat"><div class="stat-val" id="total-flicks">0</div><div class="stat-lbl">Flick</div></div>
      <div class="stat"><div class="stat-val" id="total-holds">0</div><div class="stat-lbl">长按</div></div>
      <div class="stat"><div class="stat-val" id="fps">0</div><div class="stat-lbl">FPS</div></div>
      <div class="stat"><div class="stat-val" id="avg-time">0s</div><div class="stat-lbl">平均每首</div></div>
      <div class="stat"><div class="stat-val" id="latency">0ms</div><div class="stat-lbl">延迟补偿</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">启动冲榜</div>
    <div class="form-row">
      <div class="form-group">
        <label>歌单</label>
        <select id="combo-select"></select>
      </div>
      <div class="form-group">
        <label>编队</label>
        <select id="team-select"></select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>打歌次数 (0=无限)</label>
        <input type="number" id="song-count" value="10" min="0">
      </div>
      <div class="form-group">
        <label>&nbsp;</label>
        <button class="btn btn-primary" onclick="quickStart()" style="width:100%">🚀 一键启动</button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">实时日志</div>
    <div class="log-box" id="log-box">
      <div class="log-line"><span class="log-time">--:--:--</span>等待连接...</div>
    </div>
  </div>
</div>

<!-- Screenshot -->
<div id="page-screenshot" class="page">
  <div class="controls">
    <button class="btn btn-primary btn-sm" onclick="refreshScreenshot()">📸 刷新画面</button>
    <span id="screenshot-info" class="screenshot-info" style="display:inline;margin-left:12px"></span>
  </div>
  <div class="card" style="text-align:center">
    <img id="screenshot-img" src="" alt="手机画面">
  </div>
</div>

<!-- Scripts -->
<div id="page-scripts" class="page">
  <div class="card">
    <div class="card-title">可用歌单</div>
    <div id="combos-list"></div>
  </div>
  <div class="card">
    <div class="card-title">可用编队</div>
    <div id="teams-list"></div>
  </div>
  <div class="card">
    <div class="card-title">快速命令</div>
    <p style="color:var(--text-dim);font-size:13px;margin-bottom:12px">在电脑终端执行:</p>
    <div class="log-box" style="font-size:13px">
      <div>python main.py auto --combo grind-single --infinite</div>
      <div style="margin-top:4px">python main.py auto --team event-grind --combo grind-master -n 30</div>
      <div style="margin-top:4px">python main.py calibrate</div>
      <div style="margin-top:4px">python main.py setup</div>
    </div>
  </div>
</div>

<!-- Settings -->
<div id="page-settings" class="page">
  <div class="card">
    <div class="card-title">配置编辑</div>
    <p style="color:var(--text-dim);font-size:13px;margin-bottom:12px">直接编辑 config.yaml。保存后需重启生效。</p>
    <textarea id="config-editor" style="width:100%;min-height:400px;background:#010409;border:1px solid var(--border);border-radius:6px;padding:12px;color:var(--text);font-family:'SF Mono',monospace;font-size:12px;line-height:1.5;resize:vertical"></textarea>
    <div style="margin-top:8px;display:flex;gap:8px">
      <button class="btn btn-primary btn-sm" onclick="saveConfig()">💾 保存</button>
      <button class="btn btn-outline btn-sm" onclick="loadConfig()">🔄 刷新</button>
    </div>
  </div>
</div>

<!-- About -->
<div id="page-about" class="page">
  <div class="card" style="text-align:center">
    <h2 style="color:var(--accent);margin-bottom:8px">🎵 PJSK Auto Player</h2>
    <p style="color:var(--text-dim);font-size:14px">v3.7.0</p>
    <p style="color:var(--text-dim);font-size:13px;margin-top:8px">
      基于 ADB + OpenCV 的 Project Sekai 自动打歌工具<br>
      预测引擎 · Pipeline 流水线 · 冲榜模式 · Web 控制台
    </p>
    <div style="margin-top:16px;display:flex;gap:12px;justify-content:center">
      <a href="https://github.com/WeatherWind/pjsk-auto-player" target="_blank" style="color:var(--accent);font-size:13px">GitHub</a>
      <span style="color:var(--text-dim)">·</span>
      <a href="https://github.com/WeatherWind/pjsk-auto-player/releases" target="_blank" style="color:var(--accent);font-size:13px">Releases</a>
    </div>
    <div id="version-table" style="margin-top:20px;text-align:left"></div>
  </div>
</div>

</div><!-- /main -->

<script>
// ── Page routing ──
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  document.querySelector(`.nav-item[onclick*="${name}"]`).classList.add('active');
}

// ── API ──
async function api(url) {
  const r = await fetch(url);
  return r.json();
}
async function apiAction(action) {
  await fetch('/api/action?action='+action);
}

// ── Stats update ──
async function updateStats() {
  try {
    const d = await api('/api/stats');
    const running = d.running;
    document.getElementById('status-badge').innerHTML = running
      ? '<span class="dot dot-green"></span>运行中'
      : '<span class="dot dot-gray"></span>已停止';
    document.getElementById('status-badge').className = 'badge ' + (running ? 'badge-running' : 'badge-stopped');
    document.getElementById('songs-played').textContent = d.songs_played ?? 0;
    document.getElementById('songs-failed').textContent = d.songs_failed ?? 0;
    document.getElementById('target').textContent = d.target ?? '∞';
    document.getElementById('elapsed').textContent = (d.elapsed_seconds ?? 0) + 's';
    document.getElementById('total-taps').textContent = d.total_taps ?? 0;
    document.getElementById('total-flicks').textContent = d.total_flicks ?? 0;
    document.getElementById('total-holds').textContent = d.total_holds ?? 0;
    document.getElementById('fps').textContent = (d.fps ?? 0).toFixed(1);
    document.getElementById('avg-time').textContent = (d.avg_song_time ?? 0).toFixed(1) + 's';
    document.getElementById('latency').textContent = (d.latency_comp_ms ?? 0) + 'ms';
  } catch(e) {}
}

// ── Log update ──
async function updateLog() {
  try {
    const d = await api('/api/log');
    if (!d.log) return;
    const box = document.getElementById('log-box');
    const lines = d.log.split('\n').filter(l => l.trim());
    box.innerHTML = lines.map(l =>
      '<div class="log-line"><span class="log-time">' + (d.timestamp || '') + '</span>' + escapeHtml(l) + '</div>'
    ).join('');
    box.scrollTop = box.scrollHeight;
  } catch(e) {}
}

// ── Screenshot ──
async function refreshScreenshot() {
  document.getElementById('screenshot-info').textContent = '加载中...';
  try {
    const d = await api('/api/screenshot');
    if (d.image) {
      document.getElementById('screenshot-img').src = 'data:image/jpeg;base64,' + d.image;
      document.getElementById('screenshot-info').textContent = (d.width||'?')+'x'+(d.height||'?')+' · '+(d.size||'?');
    }
  } catch(e) {
    document.getElementById('screenshot-info').textContent = '加载失败';
  }
}

// ── Config ──
async function loadConfig() {
  try {
    const d = await api('/api/config');
    document.getElementById('config-editor').value = d.content || '# (empty)';
  } catch(e) {}
}
async function saveConfig() {
  const content = document.getElementById('config-editor').value;
  await fetch('/api/config', {method:'POST', headers:{'Content-Type':'text/plain'}, body:content});
  alert('✅ 配置已保存');
}

// ── Combos & Teams ──
async function loadCombos() {
  try {
    const d = await api('/api/combos');
    const sel = document.getElementById('combo-select');
    const list = document.getElementById('combos-list');
    sel.innerHTML = '<option value="">-- 选择 --</option>';
    let html = '';
    (d.combos||[]).forEach(c => {
      sel.innerHTML += `<option value="${c.key}">${c.name} (${c.songs}首)</option>`;
      html += `<div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <strong>${c.name}</strong> <span style="color:var(--text-dim);font-size:12px">${c.songs} 首</span>
        ${c.description ? '<div style="color:var(--text-dim);font-size:12px">'+c.description+'</div>' : ''}
      </div>`;
    });
    list.innerHTML = html || '<div style="color:var(--text-dim)">暂无歌单</div>';
  } catch(e) {}
}
async function loadTeams() {
  try {
    const d = await api('/api/teams');
    const sel = document.getElementById('team-select');
    const list = document.getElementById('teams-list');
    sel.innerHTML = '<option value="">-- 不编队 --</option>';
    let html = '';
    (d.teams||[]).forEach(t => {
      sel.innerHTML += `<option value="${t.key}">${t.name} (${t.method})</option>`;
      html += `<div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <strong>${t.name}</strong> <span style="color:var(--text-dim);font-size:12px">${t.method}</span>
        ${t.description ? '<div style="color:var(--text-dim);font-size:12px">'+t.description+'</div>' : ''}
      </div>`;
    });
    list.innerHTML = html || '<div style="color:var(--text-dim)">暂无编队</div>';
  } catch(e) {}
}

async function loadVersionTable() {
  try {
    const d = await api('/api/versions');
    if (!d.versions) return;
    let html = '<div class="card-title">版本历史</div><table style="width:100%;border-collapse:collapse;font-size:13px">';
    d.versions.forEach(v => {
      html += `<tr style="border-bottom:1px solid var(--border)">
        <td style="padding:6px 12px;color:var(--accent);font-weight:600">${v.tag}</td>
        <td style="padding:6px 12px;color:var(--text-dim)">${v.date}</td>
        <td style="padding:6px 12px">${v.message}</td>
      </tr>`;
    });
    html += '</table>';
    document.getElementById('version-table').innerHTML = html;
  } catch(e) {}
}

function quickStart() {
  const combo = document.getElementById('combo-select').value;
  const team = document.getElementById('team-select').value;
  const count = document.getElementById('song-count').value || 0;
  let cmd = `python main.py auto`;
  if (team) cmd += ` --team ${team}`;
  if (combo) cmd += ` --combo ${combo}`;
  if (count > 0) cmd += ` -n ${count}`;
  else cmd += ` --infinite`;
  document.getElementById('log-box').innerHTML =
    `<div class="log-line"><span class="log-time">--:--:--</span>📋 在终端执行: ${cmd}</div>`;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Polling ──
setInterval(updateStats, 2000);
setInterval(updateLog, 3000);

// ── Init ──
loadCombos(); loadTeams(); loadConfig(); loadVersionTable();
updateStats(); updateLog();
</script>
</body>
</html>"""

# ── API ──

class APIHandler:
    """API 请求处理。"""

    @staticmethod
    def stats() -> dict:
        """返回当前冲榜状态。"""
        default = {
            "running": False, "songs_played": 0, "songs_failed": 0,
            "target": 0, "elapsed_seconds": 0, "avg_song_time": 0,
            "fps": 0, "latency_comp_ms": 0,
            "total_taps": 0, "total_flicks": 0, "total_holds": 0,
            "version": "3.7.0",
        }
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE) as f:
                    return {**default, **json.load(f)}
        except Exception:
            pass
        return default

    @staticmethod
    def log() -> dict:
        """返回最近日志。"""
        lines = []
        try:
            root = logging.getLogger()
            for h in root.handlers:
                if hasattr(h, 'stream'):
                    try:
                        content = h.stream.getvalue()
                        lines = content.strip().split("\n")[-30:]
                    except Exception:
                        pass
        except Exception:
            pass
        return {
            "log": "\n".join(lines[-30:]),
            "timestamp": time.strftime("%H:%M:%S"),
        }

    @staticmethod
    def screenshot() -> dict:
        """截取手机画面并返回 base64。"""
        if not _adb:
            return {"image": "", "width": 0, "height": 0, "size": ""}
        try:
            frame = _adb.screencap()
            if frame is None:
                return {"image": "", "width": 0, "height": 0, "size": ""}
            import cv2
            h, w = frame.shape[:2]
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            b64 = base64.b64encode(buf).decode()
            return {"image": b64, "width": w, "height": h,
                    "size": f"{len(buf)/1024:.0f} KB"}
        except Exception as e:
            return {"image": "", "width": 0, "height": 0, "size": str(e)}

    @staticmethod
    def config() -> dict:
        """返回 config.yaml 内容。"""
        path = os.path.join(ROOT_DIR, "config.yaml")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {"content": f.read()}
        except Exception as e:
            return {"content": f"# 加载失败: {e}"}

    @staticmethod
    def save_config(content: str) -> dict:
        """保存 config.yaml。"""
        path = os.path.join(ROOT_DIR, "config.yaml")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def combos() -> dict:
        """列出歌单。"""
        from combo_player import ComboPlayer
        cp = ComboPlayer({})
        return {"combos": cp.list_combos()}

    @staticmethod
    def teams() -> dict:
        """列出编队。"""
        from team_builder import TeamBuilder
        tb = TeamBuilder({})
        return {"teams": tb.list_teams()}

    @staticmethod
    def versions() -> dict:
        """列出版本历史。"""
        versions = []
        try:
            result = subprocess.run(
                ["git", "tag", "--sort=-version:refname"],
                capture_output=True, text=True, timeout=5,
                cwd=ROOT_DIR,
            )
            for tag in result.stdout.strip().split("\n")[:10]:
                if not tag:
                    continue
                date = ""
                msg = ""
                try:
                    r = subprocess.run(
                        ["git", "log", "-1", "--format=%ai|%s", tag],
                        capture_output=True, text=True, timeout=3, cwd=ROOT_DIR,
                    )
                    parts = r.stdout.strip().split("|", 1)
                    if len(parts) == 2:
                        date = parts[0][:10]
                        msg = parts[1][:80]
                except Exception:
                    pass
                versions.append({"tag": tag, "date": date, "message": msg})
        except Exception:
            versions = [{"tag": "v3.7.0", "date": "2026-05-28", "message": "Auto team formation"}]
        return {"versions": versions}


# ── HTTP Server ──

_adb = None


class WebHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。"""

    def do_GET(self):
        path = self.path.split("?")[0]
        query = {}

        if "?" in self.path:
            for part in self.path.split("?")[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        try:
            if path == "/" or path == "/index.html":
                self._html(HTML)
            elif path == "/api/stats":
                self._json(APIHandler.stats())
            elif path == "/api/log":
                self._json(APIHandler.log())
            elif path == "/api/screenshot":
                self._json(APIHandler.screenshot())
            elif path == "/api/config":
                self._json(APIHandler.config())
            elif path == "/api/combos":
                self._json(APIHandler.combos())
            elif path == "/api/teams":
                self._json(APIHandler.teams())
            elif path == "/api/versions":
                self._json(APIHandler.versions())
            elif path == "/api/action":
                action = query.get("action", "")
                self._json({"action": action, "status": "ok"})
            else:
                self.send_error(404)
        except Exception as e:
            self._json({"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            self._json(APIHandler.save_config(body))
        else:
            self._json({"error": "not found"})

    def _html(self, content: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, *args):
        pass


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """启动 Web 控制台。"""
    global _adb

    # 尝试初始化 ADB 用于截图
    try:
        from adb_controller import ADBController
        _adb = ADBController({"adb": {"executable": "adb", "device_serial": ""},
                             "screen": {"width": 1080, "height": 2400}})
        if _adb.is_connected():
            logger.info("ADB 已连接, 截图功能可用")
        else:
            _adb = None
    except Exception:
        _adb = None

    server = HTTPServer((host, port), WebHandler)
    print()
    print(f"  ╔══════════════════════════════════════════╗")
    print(f"  ║  🌐 PJSK Auto Player — Web 控制台        ║")
    print(f"  ║                                          ║")
    print(f"  ║  本地:   http://localhost:{port}")
    print(f"  ║  手机:   http://<电脑IP>:{port}")
    print(f"  ║                                          ║")
    print(f"  ║  按 Ctrl+C 停止                          ║")
    print(f"  ╚══════════════════════════════════════════╝")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb 控制台已停止")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="PJSK Auto Player — Web 控制台")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()
    run_server(host=args.bind, port=args.port)


if __name__ == "__main__":
    main()
