#!/usr/bin/env python3
# coding=utf-8
"""Download the upstream EPG sources into a cache dir, one file each.
Reuses epg_build.http_get. Then run epg_build.py with --use-cache."""
import sys, os, importlib.util

spec = importlib.util.spec_from_file_location("eb", "epg_build.py")
eb = importlib.util.module_from_spec(spec)
src = open("epg_build.py").read().replace('if __name__ == "__main__":\n    main()', '')
exec(compile(src, "epg_build.py", "exec"), eb.__dict__)

CACHE = "/var/minis/workspace/epg_cache"
os.makedirs(CACHE, exist_ok=True)

for i, url in enumerate(eb.DEFAULT_SOURCES):
    fname = "src_%d.gz" % i
    out = os.path.join(CACHE, fname)
    print("Downloading %d: %s" % (i, url), file=sys.stderr)
    try:
        data = eb.http_get(url, timeout=180)
        # keep raw (may be gz or plain)
        with open(out, "wb") as f:
            f.write(data)
        print("  saved %d bytes -> %s" % (len(data), out), file=sys.stderr)
    except Exception as ex:
        print("  FAILED: %s" % ex, file=sys.stderr)
print("Done.", file=sys.stderr)
