-- The same event counts, against the BigQuery public dataset.
--
-- This repository publishes numbers from the NCEI archive instead, because that
-- path needs no credentials and so anyone can reproduce it. This file exists so
-- the BigQuery route is executable rather than merely described, and
-- `scripts/run_bigquery.py` executes this file rather than a copy of it.
--
-- CORRECTION, September 2026. Until that script existed, this file had never
-- been run. It was written as COUNTIF(fog), which reads naturally and is wrong:
-- in `bigquery-public-data.noaa_gsod` the six indicator columns are STRING, not
-- BOOL, holding '0' and '1'. BigQuery refuses the query outright --
--
--     No matching signature for aggregate function COUNTIF
--     Argument types: STRING
--     Signature: COUNTIF(BOOL)
--
-- -- so the comment that used to sit here, promising this "returns the same six
-- numbers", described a query that returned nothing at all. Section 6 of
-- docs/DECISIONS.md listed this file as checked by eye rather than by a test,
-- and this is what that was worth. The types below are now the dataset's.
--
-- Note also what is NOT here: SELECT *. The aggregate runs in the engine and
-- returns one row. BigQuery bills on bytes scanned, so naming the six flag
-- columns instead of * is the difference between scanning a few hundred
-- megabytes and scanning the whole table, every time the query runs.

SELECT
    COUNTIF(fog = '1')                  AS fog,
    COUNTIF(rain_drizzle = '1')         AS rain_drizzle,
    COUNTIF(snow_ice_pellets = '1')     AS snow_ice_pellets,
    COUNTIF(hail = '1')                 AS hail,
    COUNTIF(thunder = '1')              AS thunder,
    COUNTIF(tornado_funnel_cloud = '1') AS tornado_funnel_cloud,
    COUNT(*)                            AS station_days
FROM `bigquery-public-data.noaa_gsod.gsod2024`;


-- Monthly seasonality, same idea: group in the engine, return twelve rows.
SELECT
    EXTRACT(MONTH FROM date)            AS month,
    COUNTIF(fog = '1')                  AS fog,
    COUNTIF(rain_drizzle = '1')         AS rain_drizzle,
    COUNTIF(snow_ice_pellets = '1')     AS snow_ice_pellets,
    COUNTIF(hail = '1')                 AS hail,
    COUNTIF(thunder = '1')              AS thunder,
    COUNTIF(tornado_funnel_cloud = '1') AS tornado_funnel_cloud,
    COUNT(*)                            AS station_days
FROM `bigquery-public-data.noaa_gsod.gsod2024`
GROUP BY month
ORDER BY month;
