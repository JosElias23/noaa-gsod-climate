# Weather events and temperature in NOAA GSOD, counted in SQL

[![CI](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml/badge.svg)](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-44%20passing-brightgreen)](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue)](pyproject.toml)
[![data](https://img.shields.io/badge/data-NOAA%20GSOD%20public%20domain-lightgrey)](https://www.ncei.noaa.gov/data/global-summary-of-the-day/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Five years of NOAA's Global Summary of the Day — **20,110,620 station-days from
12,953 weather stations** — loaded into a local warehouse and queried with SQL.

This is a rebuild of a university project of mine from March 2025, and it exists
because of what I found when I went back to check it: **the results table I had
written in that project's README was not what its own code computed.**
Reproducing the analysis from scratch, from a different source, settles which was
right.

---

## The published table was wrong; the notebook was right

The original README reported fog as the most common weather event, at 10.5% of
observations. Its own analysis text, three sections further down, said the most
common event was rain — and the notebook's stored output agreed with the text,
not with the table.

Rebuilt here from NCEI's archive, independently of BigQuery:

| Event | Occurrences | % of station-days | Original README claimed |
|---|---:|---:|---:|
| **Rain / drizzle** | **983,613** | **25.02%** | 85 (7.4%) |
| Snow / ice pellets | 237,933 | 6.05% | 30 (2.6%) |
| Fog | 221,063 | 5.62% | **120 (10.5%)** |
| Thunder | 176,911 | 4.50% | — |
| Hail | 4,516 | 0.11% | — |
| Tornado / funnel cloud | 207 | 0.01% | — |

Rain is roughly **4.5× more frequent than fog**, not less frequent. The table had
the ranking inverted and the magnitudes off by four orders of magnitude.

### Two independent paths agree

The original queried `bigquery-public-data.noaa_gsod.gsod2024` in March 2025.
This repository parses NCEI's yearly archive today. Different source, different
code, different year of retrieval:

| Event | NCEI (this repo) | Original BigQuery run | Difference |
|---|---:|---:|---:|
| rain_drizzle | 983,613 | 968,620 | +1.55% |
| snow_ice_pellets | 237,933 | 234,571 | +1.43% |
| fog | 221,063 | 217,755 | +1.52% |
| thunder | 176,911 | 173,891 | +1.74% |
| hail | 4,516 | 4,473 | +0.96% |
| tornado_funnel_cloud | 207 | 206 | +0.49% |

Largest disagreement **1.74%**, and every difference is positive. That direction
is the tell: NOAA keeps ingesting station reports filed late, so an archive read
in 2026 holds slightly more of 2024 than a query run in March 2025 did. A random
discrepancy would not be one-signed across all six.

**So the notebook's numbers were sound. Only the write-up was wrong** — which is
the more uncomfortable failure, because the code is the part people check.

### And the percentage column could not mean what it looked like

The six shares here sum to **41.31%**, not 100%. GSOD's `FRSHTT` field is six
independent flags, so one station-day can be fog *and* rain *and* thunder at
once. "% of station-days" is the only denominator that makes sense, and the
original's unlabelled `Porcentaje` column silently invited the other reading.

---

## Counting in SQL instead of in pandas

The original pulled a full year with `SELECT *` and counted the flags in pandas.
The same six numbers are one grouped aggregate. Three arms, identical data,
identical results:

| Approach | Time | Rows to client | Client memory | Speed-up |
|---|---:|---:|---:|---:|
| `SELECT *`, count in pandas | 1.586 s | 3,931,419 | 644 MB | 1.0× |
| Only the six flag columns | 0.157 s | 3,931,419 | 22.5 MB | 10.1× |
| **`SUM(...)` in SQL** | **0.041 s** | **1** | **180 B** | **38.7×** |

**38.7× faster, and 3.75 million times less data handed back to Python.**

The middle row is the interesting one. Simply *not* selecting fourteen unused
columns is 10× on its own, before any aggregation moves. Column pruning is most
of the win, and it is the one-word change.

`scripts/compare_pushdown.py` asserts all three arms return byte-identical
counts before reporting any timing. An optimisation that changes the answer is
not an optimisation.

This matters beyond a laptop: BigQuery bills on bytes scanned, so `SELECT *` on
a public dataset is the query that costs real money for no benefit.
[`sql/bigquery.sql`](sql/bigquery.sql) is the same aggregate written for
BigQuery.

---

## Most of a five-year warming signal is real. Some of it is bookkeeping.

| Year | Stations | Mean temp, all stations | Mean temp, balanced panel |
|---|---:|---:|---:|
| 2020 | 12,299 | 13.084 °C | 13.059 °C |
| 2021 | 12,275 | 12.771 °C | 12.811 °C |
| 2022 | 12,319 | 12.994 °C | 12.934 °C |
| 2023 | 12,311 | 13.605 °C | 13.479 °C |
| 2024 | 12,159 | **13.904 °C** | **13.765 °C** |
| **2020 → 2024** | | **+0.820 °C** | **+0.706 °C** |

The right-hand column keeps only the **11,475 stations that reported in every one
of the five years** (88.6% of the 12,953 that appear at all). Same years, same
query, a panel that cannot change composition.

It rises by 0.114 °C less. **About 14% of the apparent warming in the naive
series is the station network changing, not the climate** — the set of stations
reporting in 2024 is simply not the set that reported in 2020.

That is the whole reason the balanced panel is in here. The naive number is not
wrong, it is answering a slightly different question than it appears to.

**What this does not show.** Five years is not a climate trend, and this is not a
global mean temperature. It is an unweighted average over whichever stations
report to GSOD, and they are concentrated: the United States alone contributes
2,739 of the 12,159 stations reporting in 2024. 2023 and 2024 were also strong El
Niño years. The original project concluded that its temperatures "could be
indicative of gradual climate change"; on this evidence that conclusion is not
available, in either direction. Five points on a network mean is a measurement,
not a trend.

---

## Data

NOAA **Global Summary of the Day**, from the NCEI archive:
`https://www.ncei.noaa.gov/data/global-summary-of-the-day/archive/<year>.tar.gz`

US Government public domain. No key, no registration, **no cloud credentials** —
which is the point: clone this and every number above reproduces.

| | |
|---|---:|
| Years | 2020–2024 |
| Station-days | 20,110,620 |
| Stations | 12,953 |
| Downloaded | 434 MB (gzip) |
| Warehouse | 187 MB (Parquet, zstd) |

The same data is also `bigquery-public-data.noaa_gsod` and the AWS Open Data
bucket `s3://noaa-gsod-pds`, both of which serve it without credentials for
reads. [`docs/DECISIONS.md`](docs/DECISIONS.md) section 2 explains why the
published numbers come from NCEI rather than BigQuery.

---

## Running it

```bash
pip install -e ".[dev]"
python -m pytest                        # 44 tests, no network needed
python scripts/build_warehouse.py       # ~434 MB, about 3 minutes
python scripts/run_analysis.py          # writes reports/metrics_analysis.json
python scripts/compare_pushdown.py      # writes reports/metrics_pushdown.json
```

Every figure in this README is read from `reports/metrics_analysis.json`,
`reports/metrics_pushdown.json` or `reports/data_manifest.json`, each produced by
the commands above. The archives are checksummed on download and the SHA-256 of
what was actually parsed is recorded in the manifest.

---

## Limitations

**Five years, one dataset.** Nothing here supports a claim about long-run
climate, and the write-up above says so where it matters.

**Station coverage is not uniform**, so "the most common weather event" means
"among GSOD reporting stations". A land-area or population weighting would be a
different and more defensible global statistic, and is not done.

**Unweighted station means.** Each station-day counts once regardless of what
area it represents, so dense networks dominate.

**No station-level quality control.** GSOD's missing-value sentinels are handled
(9999.9 and friends never become numbers), but stations with drifting
instruments or partial years are not screened.

**Events are flags, not intensities.** A drizzle and a downpour are both
`rain_drizzle = 1`.

**The BigQuery path is not run in CI**, because that would need a billing
account. `sql/bigquery.sql` is checked by eye against the DuckDB queries, not by
a test.

## License

MIT for the code. The data is NOAA GSOD, US Government public domain.
