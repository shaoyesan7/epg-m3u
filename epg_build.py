#!/usr/bin/env python3
#coding=utf-8
"""
epg_build.py — 为 IPTV 直播源构建匹配 tvg-id 的 EPG（XMLTV）
覆盖：过去 7 天（回放）+ 未来 3 天（预告）+ 今天（补全）
用法：
  python3 epg_build.py --m3u your.m3u [--out epg.xml] [--past 7] [--future 3]
  可选 --sources 指定上游 EPG（默认内置 2 个源，取并集覆盖）
"""
import argparse, json, re, sys, time, gzip, urllib.request, xml.etree.ElementTree as ET

DEFAULT_SOURCES = [
    "https://epg.zsdc.eu.org/t.xml.gz",
    "https://raw.githubusercontent.com/atsushi444/iptv-epg/master/EPG.xml",
    "https://epg.pw/xmltv/epg_CN.xml.gz",
    "https://epg.pw/xmltv/epg.xml.gz",
    "https://epg.pw/xmltv/epg_HK.xml.gz",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}

def http_get(url, timeout=40):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def download_epg(url):
    """download & decode (gz-aware), return text"""
    data = http_get(url)
    return download_epg_local(data)

def download_epg_local(raw):
    """decode a raw byte payload (gz or plain) to text"""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="ignore")

def parse_upstream(text):
    """parse XMLTV -> {channel_id_lower: [(start_dt, stop_dt, title, desc), ...]}"""
    # strip gz magic if nested
    from datetime import datetime
    channels = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # try salvage
        text = re.sub(r"<\?xml[^>]*>", "", text)
        root = ET.fromstring(text)
    progs = {}
    for ch in root.findall("channel"):
        cid = (ch.get("id") or "").strip()
        if not cid:
            continue
        name_el = ch.find("display-name")
        name = (name_el.text or cid).strip() if name_el is not None else cid
        progs[cid.lower()] = {"name": name, "items": []}
    for p in root.findall("programme"):
        cid = (p.get("channel") or "").strip().lower()
        if cid not in progs:
            continue
        start_s, stop_s = p.get("start"), p.get("stop")
        if not start_s or not stop_s:
            continue
        try:
            st = datetime.strptime(start_s.split()[0], "%Y%m%d%H%M%S")
            sp = datetime.strptime(stop_s.split()[0], "%Y%m%d%H%M%S")
        except ValueError:
            continue
        if sp <= st:
            continue
        title_el = p.find("title")
        desc_el = p.find("desc")
        cat_els = p.findall("category")
        title = (title_el.text or "").strip() if title_el is not None else ""
        desc = (desc_el.text or "").strip() if desc_el is not None else ""
        cats = [c.text.strip() for c in cat_els if c.text and c.text.strip()]
        progs[cid]["items"].append((st, sp, title, desc, cats))
    return progs

def _norm_key(s):
    s = s.strip().lower().replace(" ", "")
    s = re.sub(r"\[\d+p\]$", "", s)
    return s


def load_m3u(path):
    """parse m3u -> list of {tvg_id, name, group, raw_line, url_line}"""
    entries = []
    lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    pending = None
    for ln in lines:
        if ln.startswith("#EXTINF"):
            pending = ln
        elif ln and not ln.startswith("#") and pending:
            m_id = re.search(r'tvg-id="([^"]*)"', pending)
            m_name = re.search(r'tvg-name="([^"]*)"', pending)
            m_grp = re.search(r'group-title="([^"]*)"', pending)
            tvg_id = m_id.group(1).strip() if m_id else ""
            # channel display name = everything after last comma
            disp = pending.split(",", 1)[1].strip() if "," in pending else ""
            entries.append({
                "tvg_id": tvg_id,
                "display": disp,
                "tvg_name": m_name.group(1).strip() if m_name else disp,
                "group": m_grp.group(1).strip() if m_grp else "",
                "raw": pending,
                "url": ln.strip(),
            })
            pending = None
    return entries


def _match_key(tvg_id, tvg_name, disp):
    """derive a single canonical lowercase match key for an m3u entry.
    Preference: tvg_id if non-empty, else tvg_name, else display name;
    normalized: lowercase, drop spaces, drop trailing resolution tags like [720P]."""
    raw = (tvg_id or tvg_name or disp or "").strip()
    if tvg_id:
        raw = tvg_id
    elif tvg_name:
        raw = tvg_name
    raw = raw.lower().replace(" ", "")
    raw = re.sub(r"\[\d+p\]$", "", raw)
    return raw


def find_channel(e, upstream):
    """try multiple keys in order; return upstream id or None."""
    keys = []
    for raw in (e["tvg_id"], e["tvg_name"], e["display"]):
        k = _match_key(e["tvg_id"], raw, raw)
        if k and k not in keys:
            keys.append(k)
    for k in keys:
        if k in upstream:
            return k
    return None

def _build_lookup(epg_map):
    """normalized key -> list of (upstream_cid, v). Index by upstream id AND display name."""
    lookup = {}
    for cid, v in epg_map.items():
        k1 = _norm_key(cid)
        if k1:
            lookup.setdefault(k1, []).append((cid, v))
        if v["name"]:
            lookup.setdefault(_norm_key(v["name"]), []).append((cid, v))
    return lookup

def _group_entries(entries):
    """group m3u entries by tvg-id; return {tvg_id: {"tvg_id","tvg_name","display","names":[...all stream display names...]}}"""
    import collections
    groups = {}
    by_group = collections.defaultdict(list)
    for e in entries:
        gid = e["tvg_id"] if e["tvg_id"] else (_norm_key(e["tvg_name"]) or _norm_key(e["display"]) or "nomatch")
        if gid not in groups:
            groups[gid] = {"tvg_id": e["tvg_id"] or gid, "tvg_name": e["tvg_name"], "display": e["display"], "names": []}
        if e["display"]:
            groups[gid]["names"].append(e["display"])
    return groups

def _pick_best(cands, lo, hi):
    """from a list of (cid, v, windowed_items), pick the channel with the most programmes; return dict or None"""
    best = None
    for cid, v, items in cands:
        if best is None or len(items) > len(best["programs"]):
            best = {"display_name": v["name"], "programs": items, "upstream_cid": cid}
    return best

def build(epg_map, entries, past_days, future_days):
    """
    Group m3u entries by tvg-id. For each tvg-id, try to hit an upstream channel using
    (in priority order): the tvg-id string, the tvg-name, the display name. Output
    channel id == the m3u tvg-id (so the app can match). Return
    {tvg_id: {"display_name","programs","upstream_cid"}}, plus match stats.
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    lo = now - timedelta(days=past_days)
    hi = now + timedelta(days=future_days)
    lookup = _build_lookup(epg_map)

    groups = _group_entries(entries)
    out = {}
    n_match = 0
    for gid, g in groups.items():
        # candidate key sets in priority order: tvg-name, display, tvg-id, then all stream names in group
        try_keys = []
        for raw in (g["tvg_name"], g["display"], g["tvg_id"]) + tuple(g.get("names", [])):
            if raw:
                k = _norm_key(raw)
                if k and k not in try_keys:
                    try_keys.append(k)
        chosen = None
        for k in try_keys:
            if k in lookup:
                cands = []
                for cid, v in lookup[k]:
                    items = [it for it in v["items"] if it[1] >= lo and it[0] <= hi]
                    cands.append((cid, v, items))
                pick = _pick_best(cands, lo, hi)
                if pick and pick["programs"]:
                    chosen = pick
                    break
        if chosen:
            out[gid] = chosen
            n_match += 1
    return out, n_match, len(groups)


def _norm_key(s):
    s = s.strip().lower().replace(" ", "")
    s = re.sub(r"\[\d+p\]$", "", s)
    return s

def emit_xml(out, entries, now_str):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<tv generator-info-name="YunYingKongMeng EPG builder" generator-info-date="%s">' % now_str]
    for cid, v in out.items():
        parts.append('  <channel id="%s">' % _esc(cid))
        parts.append('    <display-name lang="zh">%s</display-name>' % _esc(v["display_name"]))
        parts.append("  </channel>")
    for cid, v in out.items():
        for st, sp, title, desc, cats in v["programs"]:
            s = st.strftime("%Y%m%d%H%M%S") + " +0800"
            p = sp.strftime("%Y%m%d%H%M%S") + " +0800"
            line = '  <programme start="%s" stop="%s" channel="%s">' % (s, p, _esc(cid))
            if title:
                line += "\n    <title lang=\"zh\">%s</title>" % _esc(title)
            if desc:
                line += "\n    <desc lang=\"zh\">%s</desc>" % _esc(desc)
            for c in cats:
                line += "\n    <category lang=\"zh\">%s</category>" % _esc(c)
            line += "\n  </programme>"
            parts.append(line)
    parts.append("</tv>")
    return "\n".join(parts)

def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m3u", required=True)
    ap.add_argument("--out", default="epg.xml")
    ap.add_argument("--past", type=int, default=7)
    ap.add_argument("--future", type=int, default=3)
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    ap.add_argument("--gzip", action="store_true", help="also write out.gz")
    ap.add_argument("--autofill", action="store_true",
                    help="add placeholder programmes for tvg-ids that had no upstream EPG match "
                         "(so the app shows a channel entry instead of a blank guide)")
    ap.add_argument("--use-cache", default="",
                    help="comma-separated local EPG files to parse instead of downloading (one or more, "
                         "each may be gz or plain xml)")
    args = ap.parse_args()

    entries = load_m3u(args.m3u)
    print("M3U entries: %d" % len(entries), file=sys.stderr)

    epg_map = {}
    if args.use_cache:
        cache_files = [f.strip() for f in args.use_cache.split(",") if f.strip()]
        for cf in cache_files:
            print("Reading cache %s ..." % cf, file=sys.stderr)
            raw = open(cf, "rb").read()
            text = download_epg_local(raw)
            got = parse_upstream(text)
            n_items = sum(len(v["items"]) for v in got.values())
            print("  -> %d channels, %d programs" % (len(got), n_items), file=sys.stderr)
            for cid, v in got.items():
                if cid in epg_map:
                    epg_map[cid]["items"].extend(v["items"])
                else:
                    epg_map[cid] = dict(v)
    else:
        for src in args.sources.split(","):
            src = src.strip()
            if not src:
                continue
            try:
                print("Downloading %s ..." % src, file=sys.stderr)
                text = download_epg(src)
                got = parse_upstream(text)
                n_items = sum(len(v["items"]) for v in got.values())
                print("  -> %d channels, %d programs" % (len(got), n_items), file=sys.stderr)
                # merge (prefer first source's data per channel, but keep union of channels)
                for cid, v in got.items():
                    if cid in epg_map:
                        epg_map[cid]["items"].extend(v["items"])
                    else:
                        epg_map[cid] = dict(v)
            except Exception as ex:
                print("  !! source failed (%s), skipping" % ex, file=sys.stderr)
    print("Upstream total: %d channels" % len(epg_map), file=sys.stderr)

    out, m, nm = build(epg_map, entries, args.past, args.future)
    groups = _group_entries(entries)
    if args.autofill:
        # placeholder only for tvg-ids that have NO real EPG (dedup by tvg-id)
        from datetime import datetime, timedelta
        now = datetime.now()
        lo = now - timedelta(days=args.past)
        hi = now + timedelta(days=args.future)
        autofilled = 0
        for gid, g in sorted(groups.items()):
            if gid in out or gid == "nomatch":
                continue
            # autofill groups that carry a real tvg-id and were NOT matched; skip stream-name-only groups
            if not g["tvg_id"]:
                continue
            disp = g["display"] or g["tvg_name"] or gid
            items = []
            day = lo.date()
            last_day = hi.date()
            while day <= last_day:
                st = datetime(day.year, day.month, day.day, 0, 0, 0)
                sp = st + timedelta(days=1)
                if sp <= hi:
                    items.append((st, sp, "《%s》节目单" % disp, "%s 暂无上游 EPG，占位节目。" % disp, []))
                day = day + timedelta(days=1)
            if items:
                out[gid] = {"display_name": disp, "programs": items, "upstream_cid": None}
                autofilled += 1
        print("Autofill: %d placeholder channels added" % autofilled, file=sys.stderr)
    print("Matched: %d, unmatched m3u entries: %d, upstream channels kept: %d" % (m, nm, len(out)), file=sys.stderr)
    nprogs = sum(len(v["programs"]) for v in out.values())
    print("Programs after window (%d past / %d future days): %d" % (args.past, args.future, nprogs), file=sys.stderr)

    xml_text = emit_xml(out, entries, time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(xml_text)
    print("Wrote %s (%d bytes)" % (args.out, len(xml_text.encode('utf-8'))), file=sys.stderr)
    if args.gzip:
        base = args.out
        gz = base[:-4] + ".gz" if base.endswith(".xml") else base + ".gz"
        with open(gz, "wb") as f:
            f.write(gzip.compress(xml_text.encode("utf-8")))
        print("Wrote %s" % gz, file=sys.stderr)

    # report unmatched
    matched_ids = {cid.lower() for cid in out}
    unmatched_names = sorted({(e["tvg_name"] or e["display"]) for e in entries if not e["tvg_id"] and not ((e["tvg_id"].lower() in matched_ids or (e["tvg_name"] or e["display"]).lower() in matched_ids))})
    print("\nUnmatched channel names (no EPG):", file=sys.stderr)
    for n in unmatched_names:
        print("  - " + n, file=sys.stderr)

if __name__ == "__main__":
    main()
