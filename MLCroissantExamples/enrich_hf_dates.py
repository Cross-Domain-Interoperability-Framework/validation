#!/usr/bin/env python3
"""enrich_hf_dates.py — add dateModified/dateCreated to harvested HF Croissant.

Hugging Face's Croissant payload omits dates, but the HF dataset API exposes
`lastModified` and `createdAt`. CDIF discovery requires `schema:dateModified`,
so this harvest-layer step injects those dates into the local `hf-*.json`
instances (deriving the dataset slug from each file's `url`). Run once after
harvesting; ConvertFromCroissant.py then maps `dateModified` normally and needs
no network access of its own.

    python MLCroissantExamples/enrich_hf_dates.py
"""
import glob
import json
import os
import requests

HF_PREFIX = "https://huggingface.co/datasets/"
API = "https://huggingface.co/api/datasets/"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    for fp in sorted(glob.glob(os.path.join(here, "hf-*.json"))):
        d = json.load(open(fp, encoding="utf-8"))
        url = d.get("url", "")
        if not url.startswith(HF_PREFIX):
            print(f"  SKIP {os.path.basename(fp)} (no HF url)")
            continue
        slug = url[len(HF_PREFIX):].strip("/")
        try:
            meta = requests.get(API + slug, timeout=40).json()
        except Exception as e:
            print(f"  ERR  {os.path.basename(fp)}: {e}")
            continue
        added = []
        # ISO datetimes from the API; trim to YYYY-MM-DD for CDIF.
        if not d.get("dateModified") and meta.get("lastModified"):
            d["dateModified"] = meta["lastModified"][:10]
            added.append(f"dateModified={d['dateModified']}")
        if not d.get("dateCreated") and meta.get("createdAt"):
            d["dateCreated"] = meta["createdAt"][:10]
            added.append(f"dateCreated={d['dateCreated']}")
        if added:
            json.dump(d, open(fp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            open(fp, "a", encoding="utf-8").write("\n")
        print(f"  {os.path.basename(fp):34} {' '.join(added) or '(no dates available)'}")


if __name__ == "__main__":
    main()
