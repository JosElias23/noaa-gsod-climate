# Decision log

What was built, in what order, why each choice was made, and what the numbers
turned out to be. Every figure here comes from a file in `reports/`, produced by
running the code.

---

## 1. Why rebuild something that already exists

In March 2025 I built a climate analysis with a classmate as a university
project. Going back to it a year later to see whether it was worth putting on a
CV, I compared its README against its own notebook output and they disagreed.

The README's results table:

| Event | Occurrence | Percentage |
|---|---:|---:|
| Fog | 120 | 10.5% |
| Rain Drizzle | 85 | 7.4% |
| Snow Ice Pellets | 30 | 2.6% |

The notebook's stored output, from the same project:

| Event | Occurrence | Percentage |
|---|---:|---:|
| Rain Drizzle | 968,620 | 25.10% |
| Snow Ice Pellets | 234,571 | 6.08% |
| Fog | 217,755 | 5.64% |
| Thunder | 173,891 | 4.51% |
| Hail | 4,473 | 0.12% |
| Tornado Funnel Cloud | 206 | 0.01% |

Not a rounding difference. The magnitudes are off by four orders of magnitude,
two events are missing, and **the ranking is inverted** — the table says fog is
most common, the notebook says rain. The README's own prose, three sections
later, states that the most common phenomenon is rain-drizzle, contradicting the
table above it.

That is a table of numbers that were never computed. It is the failure mode I
care most about avoiding, sitting in my own public work.

**The table is mine.** `git blame` on that section of the original README
returns my name on the heading and on all three rows. The project was done with
a classmate who wrote other parts of that file; this particular mistake is not
his, and it matters enough to state rather than leave to inference.

The original repository is shared, so it is not mine alone to rewrite. This is a
separate rebuild that settles the question independently and leaves that
repository as it stands.

---

## 2. Decisions about the data

### 2.1 NCEI's archive rather than BigQuery

The original used the BigQuery public dataset. BigQuery always requires
authentication, so a reader without a Google Cloud account cannot reproduce
anything, and neither could I while writing this.

NOAA publishes the identical data three ways:

| Path | Credentials | Reproducible by a stranger |
|---|---|---|
| `bigquery-public-data.noaa_gsod` | Google Cloud account | no |
| `s3://noaa-gsod-pds` | none for reads | yes |
| NCEI yearly `.tar.gz` | none | yes |

NCEI wins on shape as much as on access: one 100 MB request per year against
roughly 12,000 objects on S3. The BigQuery version is kept as
[`sql/bigquery.sql`](../sql/bigquery.sql) so that route is executable rather than
merely described.

**This is a deliberate trade.** The cloud-warehouse path is the more
professionally interesting one, and it is the one this repository does not run.
It buys the guarantee that every number here can be checked by anyone.

### 2.2 The rows must go through a real CSV parser

The first attempt split each line on commas and produced these counts:

| Event | split(",") | Correct |
|---|---:|---:|
| rain_drizzle | 2,383 | 983,613 |
| fog | 746 | 221,063 |
| hail | 0 | 4,516 |
| tornado | 0 | 207 |

Roughly 400× too small, and **nothing raised**. GSOD's `NAME` column contains
commas inside quotes — `"JAN MAYEN NOR NAVY, NO"` — so every column after `NAME`
shifts by one. `FRSHTT` is the last column, so it read whatever landed there, and
the answer came out plausible-looking and wrong.

The give-away was that the row count was right (3,931,419) while the event counts
were not. Parsing that is broken per-field but not per-row looks exactly like
that.

`csv.DictReader` fixes it and `tests/test_data.py::TestCommaInsideQuotes` pins
it, including a test that a name *with* a comma parses the same as one without.

### 2.3 Missing values are sentinels, per column

GSOD encodes "not observed" as repeated nines, and the sentinel differs by
column: `9999.9` for temperature, `99.99` for precipitation, `999.9` for wind and
visibility. Averaging without handling these gives a mean temperature in the
thousands.

The subtlety worth a test: **the sentinel for one column is a legitimate value
for another.** `99.99` is missing precipitation but an ordinary temperature in
Fahrenheit. A global "drop all repeated nines" rule would silently delete real
hot days.

### 2.4 Celsius is derived once, at load

GSOD reports Fahrenheit. The conversion happens in `read_archive`, so no query
can forget it. Two tests pin it at the two points everyone knows by heart, 32 °F
and 212 °F.

### 2.5 Parquet is written atomically

Building the years in the background while querying the warehouse produced
`No magic bytes found at end of file` — which reads like corruption and is
actually a race: the view globs `gsod_*.parquet`, and a file still being written
matches the glob. `write_parquet` now writes to `.part` and renames, so a file
appears complete or not at all.

Found by hitting it, not by designing for it.

---

## 3. Decisions about the analysis

### 3.1 The denominator is station-days, and it is stated

`FRSHTT` is six independent flags. One station-day can be fog and rain and
thunder simultaneously, so the six shares sum to **41.31%** in 2024, not 100%.

There is no meaningful "percentage of events" here, and the original README's
bare `Porcentaje` column invited exactly that reading. Every share in this
repository is labelled `pct_of_station_days`, and a test asserts that the shares
*need not* sum to 100 — encoding the property rather than trusting a comment.

### 3.2 The temperature series is reported twice

An average over "all stations that reported" confounds climate with the
composition of the reporting network. So the same query runs against a balanced
panel: only the 11,475 stations that reported in **every** one of the five years.

| Year | All stations | Balanced panel |
|---|---:|---:|
| 2020 | 13.084 °C | 13.059 °C |
| 2024 | 13.904 °C | 13.765 °C |
| **Change** | **+0.820 °C** | **+0.706 °C** |

The balanced panel rises 0.114 °C less, so **13.9% of the apparent warming is
the station network changing, 95% CI [8.2%, 18.9%].** The naive figure is not
wrong; it answers a different question than it appears to.

Reporting only the larger number would have been the more impressive choice and
the less defensible one.

### 3.2.1 That interval was missing, and adding it changed the wording

The first version of this repository published "about 14%" as a bare difference
of two differences, with no uncertainty of any kind. That is the same class of
mistake the whole project is about, one level up: the arithmetic was right and
the confidence was invented.

`src/gsod/uncertainty.py` now bootstraps it. Two decisions in there are the
substance:

**The resampling unit is the station, not the station-day.** `annual_temperature`
already returned `sd_temp_c`, about 12.5 °C. Divided by the square root of four
million rows that gives a standard error of 0.009 °C, which would make every
comparison here overwhelmingly significant. It is wrong twice over: that 12.5 °C
is the spread between a station in Greenland and one in the Sahara, not
measurement error; and station-days are clustered by station and autocorrelated
in time, so they are nowhere near four million independent draws.
`tests/test_uncertainty.py::test_the_resampling_unit_is_the_station` makes that
testable — two warehouses with identical station-days but different numbers of
stations must not get the same interval.

**The share is resampled, not derived.** The first version of this computed the
interval for the *effect* and then divided its two endpoints by the point
estimate of the naive change, which treats that denominator as a known constant.
It is not — it is an estimate from the same stations, and it moves in every
draw. The share is now computed inside the bootstrap loop, and the interval it
gives is [8.2%, 18.9%] rather than the [7.7%, 19.9%] the derivation produced.
Slightly narrower, because numerator and denominator move together.

**Both panels come from the same draw.** They share most of their data, so their
errors are strongly positively correlated and the variance of their difference is
much smaller than the sum of their variances. Bootstrapping them separately and
subtracting would have overstated the uncertainty.

The result: 0.1136 °C, 95% CI [0.0628, 0.1636], which excludes zero. **The
finding survives; the wording did not.** "About 14%" implied a precision the
data does not carry, and the honest range is a twelfth to a fifth.

### 3.3 What is deliberately not concluded

The original ended with temperatures that "could be indicative of gradual climate
change". Five annual points on an unweighted mean over a geographically skewed
station network does not support that, in either direction — and 2023 and 2024
were strong El Niño years, which is a simpler explanation for the last two points
than a trend.

The United States alone supplies 2,739 of the 12,159 stations reporting in 2024.
"The most common weather event" here means "among GSOD reporting stations", and
the README says so.

---

## 4. Cross-checking against the original

The point of a rebuild is to be able to disagree with the thing being rebuilt.

| Event | NCEI, read 2026 | BigQuery, run March 2025 | Difference |
|---|---:|---:|---:|
| rain_drizzle | 983,613 | 968,620 | +1.55% |
| snow_ice_pellets | 237,933 | 234,571 | +1.43% |
| fog | 221,063 | 217,755 | +1.52% |
| thunder | 176,911 | 173,891 | +1.74% |
| hail | 4,516 | 4,473 | +0.96% |
| tornado_funnel_cloud | 207 | 206 | +0.49% |

Largest disagreement 1.74%, and **every difference is positive**. NOAA continues
ingesting late station reports, so an archive read later holds more of 2024 than
a query run in March 2025 did.

**Correction.** An earlier version of this section argued that "six independent
random errors would not all point the same way", which implies odds of about one
in sixty-four. They are not six independent errors. All six counts are sums of
flags over the same row set, so a larger row set raises all of them almost
deterministically. The one-sided pattern is a single observation consistent with
late ingestion, not six confirmations of it.

The comparison is not a note in a document — `NOTEBOOK_2024` is a constant in
`scripts/run_analysis.py` and the check runs on every execution, so a future
change that breaks agreement shows up in `reports/metrics_analysis.json`.

**Conclusion: the original notebook's 2024 event counts were correct. Only its
write-up was wrong.** What was checked is those six counts for one year. The same
notebook also produced a temperature analysis and pulled the NASA POWER API for
40°N 100°W to compare against NOAA; neither is reproduced here, so neither is
vouched for.
That is the more uncomfortable result of the two, because the code is the part a
reader would check.

---

## 5. Counting in SQL rather than in pandas

The original ran `SELECT *` over a year and counted in pandas. Three arms on
identical data:

| Arm | Time | Rows to client | Client memory | Speed-up |
|---|---:|---:|---:|---:|
| `SELECT *`, count in pandas | 1.586 s | 3,931,419 | 644 MB | 1.0× |
| Six flag columns only | 0.157 s | 3,931,419 | 22.5 MB | 10.1× |
| `SUM(...)` in SQL | 0.041 s | 1 | 180 B | 38.7× |

**Column pruning alone is 10× of the 38.7×**, and it is a one-word change. Moving
the aggregation is the remaining 4×. The ordering is worth knowing before
optimising: the cheap fix is most of the win.

`compare_pushdown.py` asserts all three arms return byte-identical counts before
reporting any timing, and exits non-zero if they do not.

Timings are the best of three runs on one machine. The ratios are the finding;
the absolute seconds are not portable.

---

## 6. What was not done

- **No BigQuery run.** `sql/bigquery.sql` is checked by eye against the DuckDB
  queries, not by a test, because CI has no billing account. If it drifts,
  nothing catches it.
- **Unweighted station means.** No land-area or population weighting, so dense
  networks dominate every average here.
- **No station-level quality control.** Sentinels are handled; drifting
  instruments and partial years are not screened.
- **Events are flags, not intensities.** Drizzle and downpour are both
  `rain_drizzle = 1`.
- **Five years.** Enough to demonstrate the balanced-panel effect, nowhere near
  enough for a climate claim.
- **No NASA POWER arm.** The original also pulled the NASA POWER API for a single
  point (40°N, 100°W) and compared it against NOAA. That comparison is a
  reasonable idea and is not rebuilt here; the event-count discrepancy was the
  reason for this repository and it lives entirely in the NOAA data.

---

## 7. Reproducing

```bash
pip install -e ".[dev]"
python -m pytest                        # 74 tests, no network required
python scripts/build_warehouse.py       # 434 MB from NCEI, about 3 minutes
python scripts/run_analysis.py
python scripts/compare_pushdown.py
python scripts/run_uncertainty.py
```

The test suite builds its own miniature GSOD archives in a temporary directory,
so it needs neither the network nor the 434 MB download. A test that requires the
full dataset is a test nobody runs.

Every number in this document lives in `reports/metrics_analysis.json`,
`reports/metrics_pushdown.json` and `reports/data_manifest.json`.
