"""
Sentinel Stockpile v3: the economy you can see from space.

    python -m stockpile update  --site vancouver_wind            # new scenes -> stacks -> series -> web data
    python -m stockpile update  --site vancouver_wind --start 2023-04-01
    python -m stockpile rebuild --site vancouver_wind            # reclassify every cached scene (no downloads)
    python -m stockpile publish                                  # manifest + README charts for all sites
    python -m stockpile sites                                    # list site ids (for the Actions matrix)

Layout
    sites/<id>.json            the site registry: one file per site
    sites/commodities.json     classification rules per commodity
    stacks/<id>/<date>.npz     cached band stacks (kept on the `stacks` branch, not main)
    data/<id>/scenes.json      every scene looked at, kept or rejected, and why
    docs/data/...              what the dashboard reads
"""
__version__ = "3.0.0"
