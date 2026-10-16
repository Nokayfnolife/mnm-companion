#!/usr/bin/env python3
"""
MnM Companion - a local helper for Monsters & Memories.

It keeps a copy of the community wiki at storiesofmnm.com (quests, zones and
camps, items, class guides), re-checks it on a schedule, and serves a page at
http://127.0.0.1:8637/ that recommends gear, quests, camps and bags for each of
your characters based on the level slider.

Runs on macOS (the Python that ships with it) and Windows (a bundled Python),
Python 3.9+, standard library only.

  python3 mnm_companion.py serve     # run the page + background checks
  python3 mnm_companion.py scan      # check the wiki once and exit
  python3 mnm_companion.py scan --full
  python3 mnm_companion.py stop      # stop a running copy
"""
from __future__ import annotations

import base64
import datetime as _dt
import html as _html
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
WEB_DIR = APP_DIR / "web"
SNAPSHOT = DATA_DIR / "snapshot.json"
USERFILE = DATA_DIR / "user.json"
LOGFILE = DATA_DIR / "companion.log"
CURATED = APP_DIR / "curated.json"
CONFIG = APP_DIR / "config.json"

CA_FILE = APP_DIR / "cacert.pem"     # bundled certificates (Windows build); optional
IS_WIN = os.name == "nt"

BASE = "https://storiesofmnm.com"
UA = ("Mozilla/5.0 (%s) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36 "
      "MnM-Companion/1.1" % ("Windows NT 10.0; Win64; x64" if IS_WIN else "Macintosh; Intel Mac OS X 14_5"))

DEFAULT_CONFIG = {
    "port": 8637,
    "host": "0.0.0.0",            # 0.0.0.0 = reachable from your phone on home Wi-Fi; 127.0.0.1 = this computer only
    "scan_every_hours": 2,        # quick check (quest list) this often
    "full_refresh_hours": 20,     # zones, item list and class guides this often
    "item_detail_days": 7,        # re-read an item page after this many days
    "max_item_pages_per_scan": 120,
    "request_delay_seconds": 1.2, # be polite to the wiki
    "desktop_notifications": True,
    "ntfy_topic": "",             # optional: free ntfy app topic for phone alerts
}

_scan_lock = threading.Lock()
_scan_status = {"running": False, "phase": "", "started": None, "error": None}
_SERVER = None


# ---------------------------------------------------------------- utilities
def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = "[%s] %s" % (now_iso(), msg)
    try:
        print(line, flush=True)           # no console under pythonw / launchd - that's fine
    except Exception:
        pass
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if LOGFILE.stat().st_size > 2_000_000:          # keep the log small
            tail = LOGFILE.read_text(encoding="utf-8").splitlines()[-4000:]
            LOGFILE.write_text("\n".join(tail) + "\n", encoding="utf-8")
    except Exception:
        pass


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        log("could not read %s: %s" % (path.name, e))
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    for attempt in range(20):             # Windows refuses to replace a file that's open for reading
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.15)
    os.replace(tmp, path)


def try_lock(f) -> bool:
    """Non-blocking exclusive lock on an open file (macOS/Linux: flock, Windows: msvcrt)."""
    try:
        import fcntl
    except ImportError:
        fcntl = None
    try:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def lan_ip():
    """This computer's address on the home network (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    user_cfg = load_json(CONFIG, {})
    if "mac_notifications" in user_cfg and "desktop_notifications" not in user_cfg:
        user_cfg["desktop_notifications"] = user_cfg["mac_notifications"]   # older config files
    cfg.update(user_cfg)
    return cfg


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


def slug_from(url: str, kind: str):
    m = re.search(r"/%s/([^/?#]+)" % kind, url or "")
    return m.group(1) if m else None


def parse_level_text(t: str) -> dict:
    """'Lvl 4-6 solo · 3-6 group' -> {'solo':[4,6],'group':[3,6],'text':...}"""
    t = clean(t).replace("–", "-").replace("—", "-")
    out = {"text": t, "solo": None, "group": None}
    parts = re.split(r"·|\|", t)

    def rng(p):
        m = re.search(r"(\d+)\s*-\s*(\d+)", p)
        if m:
            return [int(m.group(1)), int(m.group(2))]
        m = re.search(r"(\d+)\s*\+", p)
        if m:
            return [int(m.group(1)), int(m.group(1)) + 6]
        m = re.search(r"(\d+)", p)
        if m:
            v = int(m.group(1))
            return [max(1, v - 2), v + 2]
        return None

    for p in parts:
        r = rng(p)
        if r is None:
            continue
        if "group" in p.lower():
            out["group"] = r
        else:
            out["solo"] = r if out["solo"] is None else out["solo"]
    if out["solo"] is None and out["group"] is not None:
        out["solo"] = None
    return out


# ------------------------------------------------------------ tiny HTML DOM
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.parent = parent

    def cls(self):
        return (self.attrs.get("class") or "").split()

    def text(self) -> str:
        out = []
        stack = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                out.append(n)
            elif n.tag not in ("script", "style"):
                stack.extend(reversed(n.children))
        return clean(" ".join(out))

    def iter(self):
        stack = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, Node):
                yield n
                stack.extend(reversed([c for c in n.children if isinstance(c, Node)]))

    def find_all(self, tag=None, cls=None):
        for n in self.iter():
            if tag and n.tag != tag:
                continue
            if cls and cls not in n.cls():
                continue
            yield n

    def find(self, tag=None, cls=None):
        for n in self.find_all(tag, cls):
            return n
        return None

    def links(self, kind=None):
        res = []
        for a in self.find_all("a"):
            href = a.attrs.get("href") or ""
            if kind and ("/%s/" % kind) not in href:
                continue
            res.append({"href": urllib.parse.urljoin(BASE, href), "text": a.text()})
        return res


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


def dom(html_text: str) -> Node:
    b = _Builder()
    b.feed(html_text)
    b.close()
    return b.root


# ---------------------------------------------------------------- fetching
def _ssl_context():
    ctx = ssl.create_default_context()      # system certificates (Keychain / Windows store)
    if CA_FILE.exists():
        try:
            ctx.load_verify_locations(cafile=str(CA_FILE))
        except Exception as e:
            log("could not load %s: %s" % (CA_FILE.name, e))
    try:
        import certifi  # type: ignore  # optional, only if already installed
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


_SSL = None


def fetch(path_or_url: str, timeout=30) -> str:
    global _SSL
    if _SSL is None:
        _SSL = _ssl_context()
    url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410):
                raise
            time.sleep(3 * (attempt + 1))
        except urllib.error.URLError as e:
            last = e
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                raise RuntimeError(
                    "Python can't verify the website's certificate. On Windows, run Install.cmd again; on a "
                    "Mac with the python.org installer, run 'Install Certificates.command' from the Python "
                    "folder in Applications.")
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # timeouts, resets
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("could not load %s (%s)" % (url, last))


# ----------------------------------------------------------------- parsers
def parse_nav(root: Node) -> dict:
    zones, classes = {}, {}
    for l in root.links("zone"):
        s = slug_from(l["href"], "zone")
        if s and l["text"] and s not in zones and "atlas" not in s:
            zones[s] = l["text"].replace("’", "'")
    for l in root.links("class"):
        s = slug_from(l["href"], "class")
        if s and l["text"]:
            classes[s] = l["text"]
    return {"zones": zones, "classes": classes}


def parse_quests(root: Node) -> list:
    out, seen = [], set()
    for a in root.find_all("a", "mnm-card"):
        href = a.attrs.get("href") or ""
        slug = slug_from(href, "wiki/quest")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        name = (a.find("h2", "mnm-card-name") or a).text()
        role = a.find(None, "mnm-card-role")
        lvl_txt = role.text() if role else ""
        m = re.search(r"(\d+)", lvl_txt)
        exc = a.find(None, "mnm-card-excerpt")
        out.append({
            "slug": slug,
            "name": name,
            "url": urllib.parse.urljoin(BASE, href),
            "level": int(m.group(1)) if m else 1,
            "zone": clean(a.attrs.get("data-zone", "")).replace("’", "'"),
            "classes": clean(a.attrs.get("data-class", "")) or "ALL",
            "starter": (a.attrs.get("data-starter") == "true"),
            "reward": clean(a.attrs.get("data-reward", "")),
            "excerpt": exc.text() if exc else "",
        })
    return out


def parse_items_index(root: Node) -> dict:
    out = {}
    for a in root.find_all("a", "mnm-card"):
        href = a.attrs.get("href") or ""
        slug = slug_from(href, "wiki/item")
        if not slug or slug in out:
            continue
        name = (a.find("h2", "mnm-card-name") or a).text()
        exc = a.find(None, "mnm-card-excerpt")
        out[slug] = {
            "slug": slug,
            "name": name,
            "url": urllib.parse.urljoin(BASE, href),
            "type": clean(a.attrs.get("data-item-type", "")),
            "slot": clean(a.attrs.get("data-slot", "")),
            "classes": clean(a.attrs.get("data-classes", "")),
            "statKeys": clean(a.attrs.get("data-stats", "")),
            "races": clean(a.attrs.get("data-races", "")),
            "levelMin": clean(a.attrs.get("data-level-min", "")),
            "excerpt": exc.text() if exc else "",
        }
    return out


def parse_item_page(root: Node) -> dict:
    card = root.find(None, "mnm-item-card")
    if card is None:
        return {}
    d = {"tags": [t.text() for t in card.find_all("span", "mnm-tag")], "stats": {}}
    sub = card.find(None, "mnm-item-card-sub")
    d["sub"] = sub.text() if sub else ""
    for st in card.find_all(None, "mnm-item-card-stat"):
        lab = st.find("span")
        val = st.find("b")
        if lab is not None and val is not None:
            d["stats"][lab.text()] = val.text()
    wpn = card.find(None, "mnm-item-card-weapon")
    if wpn is not None:
        d["weapon"] = {}
        for blk in wpn.children:
            if isinstance(blk, Node):
                lab, val = blk.find("span"), blk.find("b")
                if lab is not None and val is not None:
                    d["weapon"][lab.text()] = val.text()
    for key, cls in (("saves", "mnm-item-card-saves"), ("effect", "mnm-item-card-effect")):
        n = card.find(None, cls)
        if n is not None:
            d[key] = n.text()
    drop = card.find(None, "mnm-item-card-drop")
    if drop is not None:
        d["drop"] = drop.text()
        d["dropNpcs"] = [l["text"] for l in drop.links("wiki/npc")]
        m = re.search(r"(\d+)[- ]slot", d["drop"], re.I)
        if m:
            d["bagSlots"] = int(m.group(1))
    foot = card.find(None, "mnm-item-card-footer")
    if foot is not None:
        for sp in foot.find_all("span"):
            t = sp.text()
            if ":" in t:
                k, v = t.split(":", 1)
                d[k.strip().lower()] = v.strip()
    return d


def parse_zone_page(root: Node, zone_slug: str, zone_name: str) -> dict:
    page_txt = root.text()
    m = re.search(r"\b(City|Dungeon|Zone|Outdoor|Coastal|Ocean)\s+Level\s+(\d+)\s*[-–]\s*(\d+)", page_txt)
    zone = {"slug": zone_slug, "name": zone_name, "url": "%s/zone/%s/" % (BASE, zone_slug),
            "kind": m.group(1) if m else "", "levels": [int(m.group(2)), int(m.group(3))] if m else None,
            "camps": []}
    for card in root.find_all("div", "exp-card"):
        lv = card.find(None, "exp-level")
        area = card.find(None, "exp-area")
        mobs = card.find(None, "exp-mobs")
        note = card.find(None, "exp-note")
        loot = card.find(None, "exp-loot")
        loot_txt = loot.text() if loot else ""
        loot_txt = re.sub(r"^Notable Loot:\s*", "", loot_txt)
        items = [] if re.match(r"(none|not yet|unknown|tbd|\?)", loot_txt.strip().lower()) else [x.strip() for x in loot_txt.split(",") if x.strip()]
        zone["camps"].append({
            "zone": zone_name, "zoneSlug": zone_slug,
            "level": parse_level_text(lv.text() if lv else ""),
            "area": area.text() if area else "",
            "mobs": mobs.text().replace(" · ", ", ") if mobs else "",
            "named": [l["text"] for l in (mobs.links("wiki/npc") if mobs else [])],
            "note": note.text() if note else "",
            "loot": items,
            "lootSlugs": [slug_from(l["href"], "wiki/item") for l in (loot.links("wiki/item") if loot else [])],
        })
    return zone


def parse_guide(root: Node) -> dict:
    gear, path = [], []
    heading = ""
    for n in root.iter():
        if n.tag in ("h2", "h3"):
            heading = n.text()
        if n.tag != "table":
            continue
        heads = [th.text().lower() for th in n.find_all("th")]
        rows = [tr for tr in n.find_all("tr") if tr.find("td") is not None]
        if "item" in heads and "slot" in heads:
            tier = "later" if re.search(r"later|upgrade", heading, re.I) else "early"
            for tr in rows:
                tds = [td for td in tr.children if isinstance(td, Node) and td.tag == "td"]
                if len(tds) < 4:
                    continue
                link = tds[0].links("wiki/item")
                gear.append({
                    "name": tds[0].text(), "slug": slug_from(link[0]["href"], "wiki/item") if link else None,
                    "slot": tds[1].text(), "stats": tds[2].text(), "where": tds[3].text(), "tier": tier,
                })
        elif heads[:2] == ["levels", "where"] or ("levels" in heads and "where" in heads):
            for tr in rows:
                tds = [td for td in tr.children if isinstance(td, Node) and td.tag == "td"]
                if len(tds) < 2:
                    continue
                lv = parse_level_text(tds[0].text())
                path.append({
                    "level": lv, "where": tds[1].text(),
                    "zones": [l["text"] for l in tds[1].links("zone")],
                    "why": tds[2].text() if len(tds) > 2 else "",
                })
    return {"gear": gear, "path": path}


STAT_KEYS = ("STR", "STA", "DEX", "AGI", "INT", "WIS", "CHA")


def parse_race_page(root: Node) -> dict:
    """Base stats, starting stats for each class the race can play, and the race details table."""
    race = {"base": None, "classes": {}, "bonus": None, "details": {}}
    m = re.search(r"\+\s*(\d+)\s*stat-point bonus pool", root.text())
    if m:
        race["bonus"] = int(m.group(1))
    for t in root.find_all("table"):
        heads = [th.text().strip() for th in t.find_all("th")]
        rows = [[td.text().strip() for td in tr.children if isinstance(td, Node) and td.tag == "td"]
                for tr in t.find_all("tr")]
        rows = [r for r in rows if r]
        if heads[:2] == ["Attribute", "Detail"]:
            race["details"] = {r[0]: r[1] for r in rows if len(r) >= 2}
        elif heads == list(STAT_KEYS) and rows:
            try:
                race["base"] = dict(zip(STAT_KEYS, (int(v) for v in rows[0])))
            except ValueError:
                pass
        elif heads and heads[0] == "Class" and tuple(heads[1:]) == STAT_KEYS:
            for r in rows:
                try:
                    race["classes"][r[0]] = dict(zip(STAT_KEYS, (int(v) for v in r[1:8])))
                except ValueError:
                    continue
    return race


def scan_races(snap: dict, delay: float) -> None:
    root = dom(fetch("/races/"))
    slugs = []
    for l in root.links("race"):
        s = slug_from(l["href"], "race")
        if s and s not in slugs:
            slugs.append(s)
    races = dict(snap.get("races", {}))
    for s in slugs:
        time.sleep(delay)
        _status("reading race: %s" % s)
        try:
            page = dom(fetch("/race/%s/" % s))
            r = parse_race_page(page)
            h1 = page.find("h1", "race-title")
            r["name"] = h1.text() if h1 is not None else s.replace("-", " ").title()
            r["url"] = "%s/race/%s/" % (BASE, s)
            races[s] = r
        except Exception as e:
            log("race %s skipped: %s" % (s, e))
    if races:
        snap["races"] = races


# -------------------------------------------------------------------- scan
def _status(phase: str):
    _scan_status["phase"] = phase
    log("scan: " + phase)


def guide_slugs_for(characters: list) -> set:
    want = set()
    for c in characters:
        cl = (c.get("cls") or "").strip().lower().replace(" ", "-")
        if cl:
            want.add("%s-class-guide" % cl)
    return want


def run_scan(full: bool = False) -> dict:
    if not _scan_lock.acquire(blocking=False):
        return {"ok": False, "error": "a check is already running"}
    lockf = None
    try:                                  # one scan at a time, even across processes
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        lockf = open(DATA_DIR / ".scan.lock", "w")
    except OSError:
        lockf = None
    if lockf is not None and not try_lock(lockf):
        lockf.close()
        _scan_lock.release()
        return {"ok": False, "error": "another check is already running"}
    _scan_status.update({"running": True, "started": now_iso(), "error": None})
    try:
        return _scan(full)
    except Exception as e:
        _scan_status["error"] = str(e)
        log("scan failed: %s\n%s" % (e, traceback.format_exc()))
        snap = load_json(SNAPSHOT, {})
        snap.setdefault("meta", {})["lastError"] = {"at": now_iso(), "message": str(e)}
        save_json(SNAPSHOT, snap)
        return {"ok": False, "error": str(e)}
    finally:
        _scan_status["running"] = False
        _scan_status["phase"] = ""
        if lockf is not None:
            lockf.close()
        _scan_lock.release()


def _scan(full: bool) -> dict:
    cfg = config()
    delay = float(cfg["request_delay_seconds"])
    snap = load_json(SNAPSHOT, {})
    meta = snap.setdefault("meta", {})
    first_run = not snap.get("quests")
    user = load_json(USERFILE, {})
    characters = user.get("characters") or default_user()["characters"]

    last_full = meta.get("lastFull")
    if last_full:
        age_h = (time.time() - _dt.datetime.fromisoformat(last_full).timestamp()) / 3600
        full = full or age_h >= float(cfg["full_refresh_hours"])
    else:
        full = True

    news = []

    # 1) quest list (every check)
    _status("reading the quest list")
    qroot = dom(fetch("/wiki/quests/"))
    nav = parse_nav(qroot)
    quests = parse_quests(qroot)
    if len(quests) < 20:
        raise RuntimeError("the quest list looked empty (%d quests) - the site layout may have changed" % len(quests))
    old_q = {q["slug"]: q for q in snap.get("quests", [])}
    for q in quests:
        o = old_q.get(q["slug"])
        q["firstSeen"] = (o or {}).get("firstSeen") or now_iso()
        if not first_run and o is None:
            news.append({"kind": "quest", "slug": q["slug"], "name": q["name"], "zone": q["zone"],
                         "level": q["level"], "classes": q["classes"], "url": q["url"],
                         "text": "New quest: %s (%s, level %s+)" % (q["name"], q["zone"], q["level"])})
        elif o and (o.get("reward") != q.get("reward")) and q.get("reward") and not first_run:
            news.append({"kind": "quest-update", "slug": q["slug"], "name": q["name"], "zone": q["zone"],
                         "level": q["level"], "classes": q["classes"], "url": q["url"],
                         "text": "%s now lists its reward: %s" % (q["name"], q["reward"])})
    snap["quests"] = quests
    snap["zonesNav"] = nav["zones"] or snap.get("zonesNav", {})
    snap["classesNav"] = nav["classes"] or snap.get("classesNav", {})

    # 2) zones, item list, class guides (daily)
    if full:
        zones = dict(snap.get("zones", {}))
        for zs, zn in sorted(snap["zonesNav"].items()):
            time.sleep(delay)
            _status("reading zone: %s" % zn)
            try:
                z = parse_zone_page(dom(fetch("/zone/%s/" % zs)), zs, zn)
            except Exception as e:
                log("zone %s skipped: %s" % (zs, e))
                continue
            old = zones.get(zs)
            if old and not first_run:
                old_loot = {x for c in old.get("camps", []) for x in c.get("loot", [])}
                for c in z["camps"]:
                    for it in c["loot"]:
                        if it not in old_loot:
                            news.append({"kind": "loot", "name": it, "zone": zn, "url": z["url"],
                                         "level": (c["level"].get("solo") or c["level"].get("group") or [None])[0],
                                         "text": "New loot listed in %s (%s): %s" % (zn, c["area"], it)})
            zones[zs] = z
        snap["zones"] = zones

        time.sleep(delay)
        _status("reading the item list")
        items = parse_items_index(dom(fetch("/wiki/items/")))
        if len(items) > 50:
            old_items = snap.get("items", {})
            for s, it in items.items():
                o = old_items.get(s, {})
                it["detail"] = o.get("detail")
                it["detailAt"] = o.get("detailAt")
                it["firstSeen"] = o.get("firstSeen") or now_iso()
            snap["items"] = items
        meta["lastFull"] = now_iso()

    # races: starting stats by race and class (daily, or once if missing)
    if full or not snap.get("races"):
        try:
            scan_races(snap, delay)
        except Exception as e:
            log("races skipped: %s" % e)

    # class guides: daily, or right away when a new class shows up on a tab
    guides = dict(snap.get("guides", {}))
    for gs in sorted(guide_slugs_for(characters)):
        if gs in guides and not full:
            continue
        time.sleep(delay)
        _status("reading guide: %s" % gs)
        try:
            guides[gs] = parse_guide(dom(fetch("/wiki/guide/%s/" % gs)))
            guides[gs]["at"] = now_iso()
        except Exception as e:
            log("guide %s skipped: %s" % (gs, e))
    snap["guides"] = guides

    # 3) item details for things we actually recommend
    items = snap.get("items", {})
    curated = load_json(CURATED, {})
    # order = priority: things the page leans on first
    wanted = list(curated.get("trackItems", []))
    for g in guides.values():
        wanted += [x.get("slug") for x in g.get("gear", [])]
    by_name = {v["name"].lower(): k for k, v in items.items()}
    for q in quests:
        for part in re.split(r",\s*", q.get("reward") or ""):
            s = by_name.get(part.strip().lower())
            if s:
                wanted.append(s)
    for z in snap.get("zones", {}).values():
        for c in z.get("camps", []):
            wanted += c.get("lootSlugs", [])
            wanted += [by_name.get(x.lower()) for x in c.get("loot", [])]
    wanted += [s for s, it in items.items() if it.get("slot") in ("bag", "light")]
    # gear-shaped items from the index too (so alts get recommendations), oldest first
    wanted += [s for s, it in items.items() if it.get("type") in ("armor", "weapon", "jewelry") and not it.get("detail")]
    seen, queue = set(), []
    max_age = float(cfg["item_detail_days"]) * 86400
    for s in wanted:
        if not s or s in seen:
            continue
        seen.add(s)
        it = items.get(s)
        if it is None:
            items[s] = it = {"slug": s, "name": s.replace("-", " ").title(), "url": "%s/wiki/item/%s/" % (BASE, s)}
        at = it.get("detailAt")
        stale = (not at) or (time.time() - _dt.datetime.fromisoformat(at).timestamp() > max_age)
        if stale:
            queue.append(s)
    cap = int(cfg["max_item_pages_per_scan"]) * (3 if first_run else 1)
    cap = int(os.environ.get("MNM_ITEM_CAP") or cap)
    for s in queue[:cap]:
        time.sleep(delay)
        _status("reading item: %s" % items[s].get("name", s))
        try:
            items[s]["detail"] = parse_item_page(dom(fetch("/wiki/item/%s/" % s)))
            items[s]["detailAt"] = now_iso()
        except Exception as e:
            log("item %s skipped: %s" % (s, e))
            items[s]["detailAt"] = now_iso()   # don't hammer a broken page
    snap["items"] = items
    meta["itemDetailsPending"] = max(0, len(queue) - cap)

    # 4) news + notifications
    feed = news + snap.get("news", [])
    for n in news:
        n["at"] = now_iso()
    snap["news"] = feed[:300]
    meta["lastScan"] = now_iso()
    meta["lastError"] = None
    meta["counts"] = {"quests": len(quests), "items": len(items),
                      "zones": len(snap.get("zones", {})), "guides": len(guides)}
    meta["source"] = BASE
    save_json(SNAPSHOT, snap)
    log("scan done: %d quests, %d items, %d zones, %d new" % (len(quests), len(items), len(snap.get("zones", {})), len(news)))

    if news and not first_run:
        notify_relevant(news, characters, cfg)
    return {"ok": True, "new": len(news), "full": full,
            "relevant": relevant_hits(news, characters) if not first_run else []}


# ------------------------------------------------------------ notifications
CLASS_ABBR = {
    "archer": "ARC", "bard": "BRD", "beastmaster": "BST", "cleric": "CLR", "druid": "DRU",
    "elementalist": "ELE", "enchanter": "ENC", "fighter": "FTR", "inquisitor": "INQ", "monk": "MNK",
    "necromancer": "NEC", "paladin": "PAL", "ranger": "RNG", "rogue": "ROG", "shadow knight": "SHD",
    "shaman": "SHM", "spellblade": "SPB", "wizard": "WIZ",
}


def class_matches(classes: str, cls: str) -> bool:
    c = (classes or "ALL").upper()
    if "ALL" in c.split() or not c.strip():
        return True
    name = (cls or "").lower()
    ab = CLASS_ABBR.get(name, "")
    return (name.upper() in c) or (ab and ab in re.split(r"[\s,/]+", c)) or (name.replace(" ", "_").upper() in c)


def relevant_hits(news: list, characters: list) -> list:
    """News items that fit at least one character (class can use it, within ~6 levels)."""
    hits = []
    for n in news:
        for c in characters:
            lvl = int(c.get("level") or 1)
            nl = n.get("level") or 1
            if nl > lvl + 6:
                continue
            if n["kind"].startswith("quest") and not class_matches(n.get("classes"), c.get("cls")):
                continue
            hits.append("%s - %s" % (c.get("name") or c.get("cls"), n["text"]))
            break
    return hits


def notify_relevant(news: list, characters: list, cfg: dict) -> None:
    hits = relevant_hits(news, characters)
    if not hits:
        return
    title = "MnM Companion"
    body = hits[0] if len(hits) == 1 else "%d new things for your characters. %s" % (len(hits), hits[0])
    if cfg.get("desktop_notifications", True):
        desktop_notify(title, body, "http://127.0.0.1:%s/" % cfg["port"])
    topic = (cfg.get("ntfy_topic") or "").strip()
    if topic:
        try:
            req = urllib.request.Request("https://ntfy.sh/%s" % urllib.parse.quote(topic),
                                         data="\n".join(hits[:8]).encode("utf-8"),
                                         headers={"Title": title, "Tags": "crossed_swords"})
            urllib.request.urlopen(req, timeout=15, context=_ssl_context()).read()
        except Exception as e:
            log("ntfy failed: %s" % e)


_WIN_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [System.Security.SecurityElement]::Escape($env:MNM_TITLE)
$b = [System.Security.SecurityElement]::Escape($env:MNM_BODY)
$u = [System.Security.SecurityElement]::Escape($env:MNM_URL)
$xml = '<toast activationType="protocol" launch="' + $u + '"><visual><binding template="ToastGeneric"><text>' + $t + '</text><text>' + $b + '</text></binding></visual></toast>'
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""


def desktop_notify(title: str, body: str, url: str) -> None:
    """Mac: Notification Center. Windows: a toast; clicking it opens the page."""
    body = body[:220]
    try:
        if sys.platform == "darwin":
            script = 'display notification %s with title %s sound name "Glass"' % (json.dumps(body), json.dumps(title))
            subprocess.run(["/usr/bin/osascript", "-e", script], timeout=10, check=False)
        elif IS_WIN:
            enc = base64.b64encode(_WIN_TOAST_PS.encode("utf-16-le")).decode("ascii")
            env = dict(os.environ, MNM_TITLE=title, MNM_BODY=body, MNM_URL=url)
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-WindowStyle", "Hidden", "-EncodedCommand", enc],
                           env=env, timeout=30, check=False, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except Exception as e:
        log("desktop notification failed: %s" % e)


# -------------------------------------------------------------- user state
def default_user() -> dict:
    return {
        "characters": [{
            "id": "main", "name": "My Shadow Knight", "race": "Human", "cls": "Shadow Knight",
            "city": "night-harbor", "level": 3, "solo": True, "created": now_iso(),
        }],
        "active": "main",
        "progress": {},
    }


def load_user() -> dict:
    u = load_json(USERFILE, None)
    if not u or not u.get("characters"):
        u = default_user()
        save_json(USERFILE, u)
    return u


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    server_version = "MnMCompanion/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/api/state":
            cfg = config()
            snap = load_json(SNAPSHOT, {})
            meta = snap.get("meta", {})
            nxt = None
            if meta.get("lastScan"):
                nxt = (_dt.datetime.fromisoformat(meta["lastScan"]) +
                       _dt.timedelta(hours=float(cfg["scan_every_hours"]))).isoformat(timespec="seconds")
            lan = None
            if cfg.get("host") in ("0.0.0.0", "", "::"):
                ip = lan_ip()
                lan = "http://%s:%s/" % (ip, cfg["port"]) if ip else None
            return self._send(200, {
                "snapshot": snap, "curated": load_json(CURATED, {}), "user": load_user(),
                "scan": dict(_scan_status), "nextScan": nxt, "server": True, "lan": lan,
                "platform": "windows" if IS_WIN else sys.platform,
            })
        if p == "/api/scan-status":
            return self._send(200, dict(_scan_status))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            if p == "/api/user":
                body = self._body()
                if not isinstance(body.get("characters"), list) or not body["characters"]:
                    return self._send(400, {"error": "need at least one character"})
                u = load_user()
                u["characters"] = body["characters"]
                u["active"] = body.get("active") or u["characters"][0].get("id")
                u["progress"] = body.get("progress") if isinstance(body.get("progress"), dict) else u.get("progress", {})
                save_json(USERFILE, u)
                # a brand-new class on a tab -> fetch its guide soon
                snap = load_json(SNAPSHOT, {})
                missing = guide_slugs_for(u["characters"]) - set(snap.get("guides", {}))
                if missing and not _scan_status["running"]:
                    threading.Thread(target=run_scan, kwargs={"full": False}, daemon=True).start()
                return self._send(200, {"ok": True})
            if p == "/api/shutdown":          # used by the installer / uninstaller to stop this copy
                if self.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                    return self._send(403, {"error": "only from this computer"})
                self._send(200, {"ok": True})
                if _SERVER is not None:
                    threading.Thread(target=_SERVER.shutdown, daemon=True).start()
                return None
            if p == "/api/scan":
                full = bool(self._body().get("full"))
                if _scan_status["running"]:
                    return self._send(200, {"ok": True, "already": True})
                threading.Thread(target=run_scan, kwargs={"full": full}, daemon=True).start()
                return self._send(200, {"ok": True, "started": True})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})


def scheduler_loop():
    time.sleep(5)
    while True:
        try:
            cfg = config()
            snap = load_json(SNAPSHOT, {})
            last = (snap.get("meta") or {}).get("lastScan")
            due = True
            if last:
                age_h = (time.time() - _dt.datetime.fromisoformat(last).timestamp()) / 3600
                due = age_h >= float(cfg["scan_every_hours"])
            if due and not _scan_status["running"]:
                run_scan(full=False)
        except Exception as e:
            log("scheduler: %s" % e)
        time.sleep(60)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second copy bind the same port; keep it to one copy.
    allow_reuse_address = not IS_WIN


def serve():
    global _SERVER
    cfg = config()
    load_user()
    try:
        srv = _Server((cfg["host"], int(cfg["port"])), Handler)
    except OSError as e:
        log("could not open port %s (%s) - MnM Companion is probably already running. "
            "Open http://127.0.0.1:%s/" % (cfg["port"], e, cfg["port"]))
        return 0
    _SERVER = srv
    threading.Thread(target=scheduler_loop, daemon=True).start()
    log("MnM Companion running at http://127.0.0.1:%s/" % cfg["port"])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        log("MnM Companion stopped")
    return 0


def _local_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never send 127.0.0.1 through a proxy


def is_running(port) -> bool:
    try:
        with _local_opener().open("http://127.0.0.1:%s/api/scan-status" % port, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def open_page() -> int:
    """Start the background copy if it isn't running, then open the page (desktop / Start menu icon)."""
    import webbrowser
    port = config()["port"]
    url = "http://127.0.0.1:%s/" % port
    if not is_running(port):
        exe = sys.executable
        if IS_WIN and exe.lower().endswith("python.exe"):
            alt = exe[:-10] + "pythonw.exe"
            exe = alt if os.path.exists(alt) else exe
        kw = {"cwd": str(APP_DIR), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if IS_WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # detached, new group, no window
        else:
            kw["start_new_session"] = True
        subprocess.Popen([exe, str(APP_DIR / "mnm_companion.py"), "serve"], **kw)
        for _ in range(40):
            if is_running(port):
                break
            time.sleep(0.5)
    webbrowser.open(url)
    return 0


def stop_running() -> bool:
    port = config()["port"]
    try:
        req = urllib.request.Request("http://127.0.0.1:%s/api/shutdown" % port, data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with _local_opener().open(req, timeout=5) as r:
            r.read()
        return True
    except Exception:
        return False


def export_offline(out_path: Path) -> Path:
    """One-file copy of the page with today's data baked in (opens without the server)."""
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    embed = {"snapshot": load_json(SNAPSHOT, {}), "curated": load_json(CURATED, {}),
             "user": load_json(USERFILE, None) or default_user(), "scan": {"running": False}, "nextScan": None}
    blob = json.dumps(embed, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = page.replace("<script>\n\"use strict\";", "<script>window.MNM_EMBED=%s;</script>\n<script>\n\"use strict\";" % blob, 1)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "serve":
        return serve()
    elif cmd == "open":
        return open_page()
    elif cmd == "stop":
        print("stopped" if stop_running() else "not running")
    elif cmd == "export":
        out = Path(argv[2]) if len(argv) > 2 else APP_DIR / "MnM-Companion-offline.html"
        print(export_offline(out))
    elif cmd == "scan":
        res = run_scan(full="--full" in argv)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
