-- The same event counts, against the BigQuery public dataset.
--
-- This repository publishes numbers from the NCEI archive instead, because that
-- path needs no credentials and so anyone can reproduce it. This file is here so
-- the BigQuery route is not merely described: run it in the BigQuery console or
-- in Colab and it returns the same six numbers, up to the late station reports
-- NOAA has added since (see docs/DECISIONS.md section 4).
--
-- Note what is NOT here: SELECT *. The aggregate runs in the engine and returns
-- one row. BigQuery bills on bytes scanned, so naming the six flag columns
-- instead of * is also the difference between scanning a handful of columns and
-- scanning the whole table.

SELECT
    COUNTIF(fog)                  AS fog,
    COUNTIF(rain_drizzle)         AS rain_drizzle,
    COUNTIF(snow_ice_pellets)     AS snow_ice_pellets,
    COUNTIF(hail)                 AS hail,
    COUNTIF(thunder)              AS thunder,
    COUNTIF(tornado_funnel_cloud) AS tornado_funnel_cloud,
    COUNT(*)                      AS station_days
FROM `bigquery-public-data.noaa_gsod.gsod2024`;


-- Monthly seasonality, same idea: group in the engine, return twelve rows.
SELECT
    EXTRACT(MONTH FROM date)      AS month,
    COUNTIF(fog)                  AS fog,
    COUNTIF(rain_drizzle)         AS rain_drizzle,
    COUNTIF(snow_ice_pellets)     AS snow_ice_pellets,
    COUNTIF(hail)                 AS hail,
    COUNTIF(thunder)              AS thunder,
    COUNTIF(tornado_funnel_cloud) AS tornado_funnel_cloud,
    COUNT(*)                      AS station_days
FROM `bigquery-public-data.noaa_gsod.gsod2024`
GROUP BY month
ORDER BY month;
