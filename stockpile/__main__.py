from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from . import fetch, publish, series
from .sites import all_ids, load


def main():
    ap = argparse.ArgumentParser(prog="python -m stockpile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update", help="fetch new scenes, then rebuild the series")
    u.add_argument("--site", required=True)
    u.add_argument("--start", help="default: 20 days before the last scene looked at, or the site's start")
    u.add_argument("--end", default=date.today().isoformat())
    r = sub.add_parser("rebuild", help="reclassify every cached scene (no downloads)")
    r.add_argument("--site", required=True)
    sub.add_parser("publish", help="manifest + README charts for all sites")
    v = sub.add_parser("validate", help="NAIP aerial photo over the yard, for checking the classifier")
    v.add_argument("--site", required=True)
    sub.add_parser("sites", help="site ids as JSON (for the Actions matrix)")
    a = ap.parse_args()

    if a.cmd == "sites":
        print(json.dumps(all_ids()))
    elif a.cmd == "update":
        site = load(a.site)
        start = a.start
        if not start:
            cat = fetch.load_catalog(site.id)
            start = ((date.fromisoformat(cat[-1]["date"]) - timedelta(days=20)).isoformat()
                     if cat else site.start)
        fetch.update(site, start, a.end)
        series.build(site)
    elif a.cmd == "rebuild":
        series.build(load(a.site))
    elif a.cmd == "validate":
        from . import validate
        validate.run(load(a.site))
    elif a.cmd == "publish":
        m = publish.manifest()
        publish.charts()
        print(f"manifest: {len(m)} sites")


if __name__ == "__main__":
    main()
