import os
import psutil
import subprocess
import time
from datetime import datetime
import urllib.request
import urllib.parse
import re
import html as html_mod
import xml.etree.ElementTree as ET



WINDOWS_APPS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "task manager": "taskmgr",
    "file explorer": "explorer",
    "explorer": "explorer",
    "cmd": "cmd",
    "powershell": "powershell",
    "spotify": "spotify",
    "vlc": "vlc",
    "vscode": "code",
    "visual studio code": "code",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "teams": "teams",
    "whatsapp": "WhatsApp",
    "discord": "discord",
    "zoom": "zoom",
    "obs": "obs64",
    "steam": "steam",
    "camera": "microsoft.windows.camera:",
    "settings": "ms-settings:",
    "photos": "ms-photos:",
    "weather": "msnweather:",
    "calendar": "outlookcal:",
    "energy saver": "ms-settings:batterysaver",
    "battery saver": "ms-settings:batterysaver",
    "power": "ms-settings:powersleep",
    "power settings": "ms-settings:powersleep",
    "music": "mswindowsmusic:",
    "music player": "mswindowsmusic:",
    "groove": "mswindowsmusic:",
    "groove music": "mswindowsmusic:",
    "windows media player": "wmplayer",
    "media player": "wmplayer",
    "winamp": "winamp",
    "itunes": "itunes",
    "amazon music": "amazon music",
    "movies": "mswindowsvideo:",
    "movies & tv": "mswindowsvideo:",
    "films": "mswindowsvideo:",
    "snipping tool": "ms-screensketch:",
    "snip": "ms-screensketch:",
    "clock": "ms-clock:",
    "alarm": "ms-clock:",
    "maps": "bingmaps:",
    "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    "sticky notes": "ms-stickynotes:",
    "mail": "outlookmail:",
    "news": "bingnews:",
    "paint 3d": "ms-paint:",
    "3d paint": "ms-paint:",
}

last_io_time = 0
last_net_bytes = 0
last_disk_bytes = 0


def get_system_stats() -> dict:
    """Get real system statistics including Network and Disk I/O bandwidth."""
    global last_io_time, last_net_bytes, last_disk_bytes
    
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    current_time = time.time()
    
    try:
        net = psutil.net_io_counters()
        curr_net = net.bytes_sent + net.bytes_recv
    except:
        curr_net = 0
        
    try:
        disk_io = psutil.disk_io_counters()
        curr_disk = disk_io.read_bytes + disk_io.write_bytes
    except:
        curr_disk = 0
        
    net_kbs = 0.0
    disk_mbs = 0.0
    
    if last_io_time > 0:
        dt = current_time - last_io_time
        if dt > 0:
            net_kbs = (curr_net - last_net_bytes) / dt / 1024
            disk_mbs = (curr_disk - last_disk_bytes) / dt / (1024 * 1024)
            
    last_io_time = current_time
    last_net_bytes = curr_net
    last_disk_bytes = curr_disk
    
    return {
        "cpu": f"{cpu:.1f}%",
        "ram": f"{mem.percent:.1f}% ({mem.used // (1024**3):.1f}GB / {mem.total // (1024**3):.1f}GB)",
        "disk": f"{disk.percent:.1f}% used ({disk.free // (1024**3):.1f}GB free)",
        "processes": len(psutil.pids()),
        "uptime": str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).split('.')[0],
        "battery": _get_battery(),
        "net_kbs": f"{net_kbs:.1f} KB/s",
        "net_pct": min(100.0, (net_kbs / 25000.0) * 100),
        "disk_mbs": f"{disk_mbs:.1f} MB/s",
        "disk_pct": min(100.0, (disk_mbs / 100.0) * 100),
    }


def _get_battery() -> str:
    try:
        b = psutil.sensors_battery()
        if b:
            status = "Charging ⚡" if b.power_plugged else "On Battery"
            return f"{b.percent:.0f}% — {status}"
        return "N/A"
    except:
        return "N/A"


def open_application(app: str) -> dict:
    """Open a Windows application."""
    app_lower = app.lower().strip()
    exe = WINDOWS_APPS.get(app_lower, app_lower)
    
    try:
        # Try direct process open
        if os.path.exists(exe):
            subprocess.Popen([exe])
        else:
            # Try using start command
            subprocess.Popen(f'start "" "{exe}"', shell=True)
        return {"success": True, "message": f"Opened {app} successfully."}
    except Exception as e:
        # Fallback: use windows start
        try:
            os.startfile(exe)
            return {"success": True, "message": f"Opened {app}."}
        except Exception as e2:
            # Search for it
            try:
                subprocess.Popen(f'start "" /B "{app}"', shell=True)
                return {"success": True, "message": f"Attempting to open {app}."}
            except:
                return {"success": False, "message": f"Could not find {app}. Please check if it is installed."}


def open_url(url: str) -> dict:
    """Generate an HTML button to open a URL in the default browser."""
    # Very basic validation
    if not url.startswith("http"):
        url = "https://" + url
    try:
        btn_html = f"<div style='margin-top:12px;'><a href='{url}' target='_blank' style='display:inline-block; padding:8px 15px; background:var(--arc); color:#000; text-decoration:none; font-weight:bold; border-radius:4px; font-size:12px; pointer-events:auto;'>[ GRANT PERMISSION TO OPEN: {url} ]</a></div>"
        return {"html_override": btn_html}
    except Exception as e:
        return {"error": str(e)}


def run_command(command: str) -> dict:
    """Run a safe PowerShell command."""
    # Block dangerous commands
    blocked = ["rm ", "del ", "format ", "shutdown", "restart", "reg delete", "rmdir /s", "drop", "diskpart"]
    for b in blocked:
        if b.lower() in command.lower():
            return {"success": False, "output": f"Blocked: '{b}' is a restricted operation, Sir."}
    
    try:
        result = subprocess.run(
            ["powershell", "-Command", command],
            capture_output=True, text=True, timeout=10, shell=False
        )
        output = result.stdout.strip() or result.stderr.strip()
        return {"success": True, "output": output[:1500] if output else "Command executed successfully."}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Command timed out after 10 seconds."}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _fetch_article_description(url: str) -> tuple:
    """Fetch a real summary (og:description/meta description) and source from an article URL.
    Returns (source, summary) strings."""
    source = ""
    summary = ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        )
        html = urllib.request.urlopen(req, timeout=2).read(15000).decode('utf-8', errors='ignore')

        # ── Extract site/publisher name ──
        for pat in [
            r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,80})',
            r'<meta[^>]+content=["\']([^"\']{2,80})["\'][^>]+property=["\']og:site_name["\']',
        ]:
            m = re.search(pat, html, re.I)
            if m:
                source = m.group(1).strip()
                break

        # ── Extract real article description ──
        for pat in [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{30,500})',
            r'<meta[^>]+content=["\']([^"\']{30,500})["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{30,500})',
            r'<meta[^>]+content=["\']([^"\']{30,500})["\'][^>]+name=["\']description["\']',
            r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']{30,500})',
        ]:
            m = re.search(pat, html, re.I)
            if m:
                raw = m.group(1).strip()
                # Decode common HTML entities
                for ent, ch in [('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'"), ('&#x27;', "'"), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' ')]:
                    raw = raw.replace(ent, ch)
                summary = raw
                break
    except:
        pass
    return source, summary


def search_web(query: str) -> dict:
    def make_news_html(items_data):
        cards = []
        for d in items_data:
            t   = html_mod.escape(d.get('title', ''))
            pub = html_mod.escape(d.get('pub_date', ''))
            src = html_mod.escape(d.get('source', ''))
            sm  = html_mod.escape(d.get('summary', ''))
            url = d.get('url', '#')
            src_h = f'<span style="color:var(--gold);font-size:9px;letter-spacing:2px;">{src}</span>' if src else ''
            sm_h  = f'<div style="margin-top:5px;color:var(--textbright);font-size:10px;line-height:1.6;font-family:\'Exo 2\',sans-serif;">{sm}</div>' if sm else ''
            lnk_h = f'<a href="{url}" target="_blank" style="color:var(--arc2);font-size:8px;letter-spacing:1px;text-decoration:none;margin-top:4px;display:inline-block;">[ \u2192 OPEN ARTICLE ]</a>' if url and url != '#' else ''
            cards.append(f'<div style="border:1px solid rgba(0,229,255,0.15);border-left:3px solid var(--arc);background:rgba(0,229,255,0.03);padding:10px 12px;margin:6px 0;">'
                         f'<div style="color:var(--arc);font-size:11px;font-family:\'Share Tech Mono\',monospace;line-height:1.5;margin-bottom:4px;">{t}</div>'
                         f'<div style="display:flex;gap:12px;align-items:center;margin-bottom:2px;">{src_h}<span style="color:var(--textdim);font-size:8px;">{pub}</span></div>'
                         f'{sm_h}{lnk_h}</div>')
        hdr = f'<div style="color:var(--gold);font-family:\'Orbitron\',monospace;font-size:9px;letter-spacing:3px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,193,7,0.2);">\u25c8 LIVE NEWS  //  {html_mod.escape(query.upper())}</div>'
        return hdr + ''.join(cards)

    def make_web_html(results):
        cards = []
        for i, r in enumerate(results, 1):
            sn  = html_mod.escape(r.get('snippet', ''))
            src = html_mod.escape(r.get('source', ''))
            url = r.get('url', '#')
            lnk = f'<a href="{url}" target="_blank" style="color:var(--arc2);font-size:8px;text-decoration:none;">[ \u2192 OPEN ]</a>' if url != '#' else ''
            cards.append(f'<div style="border:1px solid rgba(0,229,255,0.12);border-left:3px solid var(--green);background:rgba(0,230,118,0.02);padding:10px 12px;margin:6px 0;">'
                         f'<div style="display:flex;justify-content:space-between;margin-bottom:5px;">'
                         f'<span style="color:var(--green);font-family:\'Orbitron\',monospace;font-size:8px;letter-spacing:2px;">RESULT {i:02d}</span>{lnk}</div>'
                         f'<div style="color:var(--textbright);font-size:10px;line-height:1.6;font-family:\'Exo 2\',sans-serif;margin-bottom:4px;">{sn}</div>'
                         f'<div style="color:var(--textdim);font-size:8px;font-family:\'Share Tech Mono\',monospace;word-break:break-all;">{src}</div></div>')
        hdr = f'<div style="color:var(--green);font-family:\'Orbitron\',monospace;font-size:9px;letter-spacing:3px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(0,230,118,0.2);">\u25c8 WEB SEARCH  //  {html_mod.escape(query.upper())}</div>'
        return hdr + ''.join(cards)

    try:
        # 1. Google News RSS
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            xml_data = urllib.request.urlopen(req, timeout=6).read()
            root     = ET.fromstring(xml_data)
            items    = root.findall('.//item')[:4]
            if items:
                items_data = []
                for item in items:
                    raw_title = (item.find('title').text or "").strip()
                    # Remove the trailing " - Publisher" from Google News titles
                    title = ' - '.join(raw_title.split(' - ')[:-1]).strip() if ' - ' in raw_title else raw_title
                    pub_date = (item.find('pubDate').text or "").strip()
                    link_el  = item.find('link')
                    art_url  = (link_el.text or "").strip() if link_el is not None else ""

                    rss_source = ""
                    desc_el = item.find('description')
                    if desc_el is not None and desc_el.text:
                        sm = re.search(r'<font[^>]*color=["\']#6f6f6f["\'][^>]*>(.*?)</font>', desc_el.text, re.I | re.S)
                        if sm:
                            rss_source = re.sub(r'<[^>]+>', '', sm.group(1)).strip()

                    fetched_source, summary = ("", "")
                    if art_url:
                        fetched_source, summary = _fetch_article_description(art_url)

                    display_source = fetched_source or rss_source
                    if summary and summary.lower().strip()[:60] == title.lower().strip()[:60]:
                        summary = ""

                    items_data.append({'title': title, 'pub_date': pub_date,
                                       'source': display_source, 'summary': summary, 'url': art_url})

                return {"success": True, "html_override": make_news_html(items_data)}
        except:
            pass

        # 2. DuckDuckGo HTML fallback
        ddg_url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({'q': query}).encode('utf-8')
        req  = urllib.request.Request(ddg_url, data=data, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        html_page = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')

        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html_page, re.IGNORECASE | re.DOTALL)
        raw_urls = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"', html_page, re.IGNORECASE | re.DOTALL)

        if snippets:
            results = []
            for i in range(min(4, len(snippets))):
                clean   = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                url_str = raw_urls[i] if i < len(raw_urls) else ""
                if url_str.startswith("//"):
                    url_str = "https:" + url_str
                decoded = urllib.parse.unquote(url_str.split('uddg=')[-1]) if 'uddg=' in url_str else url_str
                results.append({'snippet': clean, 'source': decoded, 'url': decoded})
            return {"success": True, "html_override": make_web_html(results)}

        return {"success": False, "output": "No results found, Sir."}
    except Exception as e:
        return {"success": False, "output": f"Search failed: {e}"}


def get_time() -> dict:
    """Get current date and time."""
    now = datetime.now()
    return {
        "time": now.strftime("%I:%M:%S %p"),
        "date": now.strftime("%A, %B %d, %Y"),
        "timestamp": now.isoformat()
    }


def list_directory(path: str) -> dict:
    """List files in a directory."""
    # Expand common shortcuts
    if path.lower() in ["desktop", "~\\desktop"]:
        path = os.path.join(os.path.expanduser("~"), "Desktop")
    elif path.lower() in ["downloads", "~\\downloads"]:
        path = os.path.join(os.path.expanduser("~"), "Downloads")
    elif path.lower() in ["documents", "~\\documents"]:
        path = os.path.join(os.path.expanduser("~"), "Documents")
    elif not os.path.isabs(path):
        path = os.path.join(os.path.expanduser("~"), path)
    
    try:
        entries = os.listdir(path)
        files = []
        dirs = []
        for e in entries[:30]:  # Limit to 30 items
            full = os.path.join(path, e)
            if os.path.isdir(full):
                dirs.append(f"📁 {e}")
            else:
                size = os.path.getsize(full)
                files.append(f"📄 {e} ({size//1024}KB)")
        return {
            "success": True,
            "path": path,
            "dirs": dirs,
            "files": files,
            "total": len(entries)
        }
    except Exception as e:
        return {"success": False, "output": str(e)}
