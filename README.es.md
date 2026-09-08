# Eventos meteorológicos y temperatura en NOAA GSOD, contados en SQL

[![CI](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml/badge.svg)](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-59%20passing-brightgreen)](https://github.com/JosElias23/noaa-gsod-climate/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue)](pyproject.toml)
[![data](https://img.shields.io/badge/data-NOAA%20GSOD%20dominio%20p%C3%BAblico-lightgrey)](https://www.ncei.noaa.gov/data/global-summary-of-the-day/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) · **Español**

Cinco años del Global Summary of the Day de NOAA — **20.110.620 registros
estación-día de 12.953 estaciones meteorológicas** — cargados en un warehouse
local y consultados con SQL.

Es la reconstrucción de un proyecto universitario mío de marzo de 2025, y existe
por lo que encontré al volver a revisarlo: **la tabla de resultados que yo mismo
había escrito en el README de ese proyecto no era lo que su propio código había
calculado.** Rehacer el análisis desde cero, desde otra fuente, resuelve cuál de
los dos tenía razón.

---

## La tabla publicada estaba mal; el notebook estaba bien

El README original reportaba la niebla como el evento más común, con 10,5 % de
las observaciones. Su propio texto de análisis, tres secciones más abajo, decía
que el evento más común era la lluvia — y la salida guardada del notebook
coincidía con el texto, no con la tabla.

Reconstruido aquí desde el archivo de NCEI, sin pasar por BigQuery:

| Evento | Ocurrencias | % de estación-días | El README original decía |
|---|---:|---:|---:|
| **Lluvia / llovizna** | **983.613** | **25,02 %** | 85 (7,4 %) |
| Nieve / granizo blando | 237.933 | 6,05 % | 30 (2,6 %) |
| Niebla | 221.063 | 5,62 % | **120 (10,5 %)** |
| Tormenta eléctrica | 176.911 | 4,50 % | — |
| Granizo | 4.516 | 0,11 % | — |
| Tornado / tromba | 207 | 0,01 % | — |

La lluvia es unas **4,5 veces más frecuente que la niebla**, no menos. La tabla
tenía el orden invertido y las magnitudes erradas por cuatro órdenes de
magnitud.

### Dos caminos independientes coinciden

El original consultó `bigquery-public-data.noaa_gsod.gsod2024` en marzo de 2025.
Este repositorio parsea hoy el archivo anual de NCEI. Distinta fuente, distinto
código, distinto momento de descarga:

| Evento | NCEI (este repo) | Corrida original en BigQuery | Diferencia |
|---|---:|---:|---:|
| rain_drizzle | 983.613 | 968.620 | +1,55 % |
| snow_ice_pellets | 237.933 | 234.571 | +1,43 % |
| fog | 221.063 | 217.755 | +1,52 % |
| thunder | 176.911 | 173.891 | +1,74 % |
| hail | 4.516 | 4.473 | +0,96 % |
| tornado_funnel_cloud | 207 | 206 | +0,49 % |

La discrepancia mayor es de **1,74 %**, y **todas las diferencias son
positivas**. Esa dirección es la pista: NOAA sigue incorporando reportes de
estaciones enviados tarde, así que un archivo leído en 2026 contiene algo más de
2024 que una consulta hecha en marzo de 2025. Seis errores aleatorios no
apuntarían todos al mismo lado.

**Es decir: los números del notebook eran correctos. Lo que estaba mal era el
texto publicado** — que es la falla más incómoda de las dos, porque el código es
la parte que la gente sí revisa.

### Y la columna de porcentaje no podía significar lo que parecía

Los seis porcentajes suman **41,31 %**, no 100 %. El campo `FRSHTT` de GSOD son
seis indicadores independientes, así que un mismo estación-día puede ser niebla
*y* lluvia *y* tormenta a la vez. "% de estación-días" es el único denominador
que tiene sentido, y la columna `Porcentaje` sin etiquetar del original invitaba
en silencio a la otra lectura.

---

## Contar en SQL en vez de en pandas

El original traía el año completo con `SELECT *` y contaba los indicadores en
pandas. Esos mismos seis números son una sola agregación agrupada. Tres brazos,
datos idénticos, resultados idénticos:

| Enfoque | Tiempo | Filas al cliente | Memoria en cliente | Aceleración |
|---|---:|---:|---:|---:|
| `SELECT *` y contar en pandas | 1,586 s | 3.931.419 | 644 MB | 1,0× |
| Solo las seis columnas de indicadores | 0,157 s | 3.931.419 | 22,5 MB | 10,1× |
| **`SUM(...)` en SQL** | **0,041 s** | **1** | **180 B** | **38,7×** |

**38,7× más rápido, y 3,75 millones de veces menos datos devueltos a Python.**

La fila del medio es la interesante. Simplemente *no* pedir catorce columnas que
no se usan ya da 10× por sí solo, antes de mover ninguna agregación. La poda de
columnas es la mayor parte de la ganancia, y es el cambio de una palabra.

`scripts/compare_pushdown.py` verifica que los tres brazos devuelvan conteos
idénticos byte a byte antes de reportar ningún tiempo. Una optimización que
cambia la respuesta no es una optimización.

Esto importa más allá de un notebook: BigQuery cobra por bytes escaneados, así
que `SELECT *` sobre un dataset público es la consulta que cuesta dinero real a
cambio de nada. [`sql/bigquery.sql`](sql/bigquery.sql) es la misma agregación
escrita para BigQuery.

---

## Gran parte del calentamiento a cinco años es real. Otra parte es contabilidad.

| Año | Estaciones | Temp. media, todas | Temp. media, panel balanceado |
|---|---:|---:|---:|
| 2020 | 12.299 | 13,084 °C | 13,059 °C |
| 2021 | 12.275 | 12,771 °C | 12,811 °C |
| 2022 | 12.319 | 12,994 °C | 12,934 °C |
| 2023 | 12.311 | 13,605 °C | 13,479 °C |
| 2024 | 12.159 | **13,904 °C** | **13,765 °C** |
| **2020 → 2024** | | **+0,820 °C** | **+0,706 °C** |

La columna derecha conserva solo las **11.475 estaciones que reportaron en cada
uno de los cinco años** (88,6 % de las 12.953 que aparecen alguna vez). Mismos
años, misma consulta, un panel que no puede cambiar de composición.

Sube 0,114 °C menos. **Cerca del 14 % del calentamiento aparente en la serie
ingenua es la red de estaciones cambiando, no el clima** — el conjunto que
reportó en 2024 sencillamente no es el que reportó en 2020.

Esa es toda la razón por la que el panel balanceado está aquí. El número ingenuo
no está mal: responde una pregunta ligeramente distinta de la que aparenta.

**Lo que esto no demuestra.** Cinco años no son una tendencia climática, y esto
no es una temperatura media global. Es un promedio sin ponderar sobre las
estaciones que reportan a GSOD, y están concentradas: solo Estados Unidos aporta
2.739 de las 12.159 estaciones que reportan en 2024. Además 2023 y 2024 fueron
años de El Niño fuerte. El proyecto original concluía que sus temperaturas
"podrían ser indicativas de un cambio climático gradual"; con esta evidencia esa
conclusión no está disponible, ni a favor ni en contra. Cinco puntos sobre la
media de una red son una medición, no una tendencia.

---

## Datos

**Global Summary of the Day** de NOAA, desde el archivo de NCEI:
`https://www.ncei.noaa.gov/data/global-summary-of-the-day/archive/<año>.tar.gz`

Dominio público del Gobierno de EE. UU. Sin llave, sin registro, **sin
credenciales de nube** — que es justamente el punto: clona esto y cada número de
arriba se reproduce.

| | |
|---|---:|
| Años | 2020–2024 |
| Registros estación-día | 20.110.620 |
| Estaciones | 12.953 |
| Descargado | 434 MB (gzip) |
| Warehouse | 187 MB (Parquet, zstd) |

Los mismos datos están también en `bigquery-public-data.noaa_gsod` y en el bucket
de AWS Open Data `s3://noaa-gsod-pds`, ambos accesibles para lectura sin
credenciales. La sección 2 de [`docs/DECISIONS.md`](docs/DECISIONS.md) explica
por qué los números publicados vienen de NCEI y no de BigQuery.

---

## Cómo ejecutarlo

```bash
pip install -e ".[dev]"
python -m pytest                        # 59 tests, sin necesidad de red
python scripts/build_warehouse.py       # ~434 MB, unos 3 minutos
python scripts/run_analysis.py          # escribe reports/metrics_analysis.json
python scripts/compare_pushdown.py      # escribe reports/metrics_pushdown.json
```

Cada cifra de este README se lee de `reports/metrics_analysis.json`,
`reports/metrics_pushdown.json` o `reports/data_manifest.json`, producidos por
los comandos de arriba. Los archivos se verifican por checksum al descargarlos y
el SHA-256 de lo que efectivamente se parseó queda registrado en el manifiesto.

Hay además un test que comprueba que **cada número citado en este README y en el
inglés exista en esos JSON**. Este repositorio existe porque una tabla publicada
no coincidía con ningún cálculo; protegerse de repetir eso corresponde a la
suite de tests, no a la buena voluntad.

---

## Limitaciones

**Cinco años, un solo dataset.** Nada aquí sostiene una afirmación sobre clima de
largo plazo, y el texto de arriba lo dice donde corresponde.

**La cobertura de estaciones no es uniforme**, así que "el evento más común"
significa "entre las estaciones que reportan a GSOD". Una ponderación por área o
por población sería un estadístico global distinto y más defendible, y no está
hecha.

**Medias por estación sin ponderar.** Cada estación-día cuenta una vez sin
importar qué superficie representa, así que las redes densas dominan.

**Sin control de calidad por estación.** Los centinelas de dato faltante de GSOD
sí se manejan (9999.9 y compañía nunca se convierten en números), pero no se
filtran estaciones con instrumentos desviados o años parciales.

**Los eventos son indicadores, no intensidades.** Una llovizna y un aguacero son
ambos `rain_drizzle = 1`.

**El camino de BigQuery no se ejecuta en CI**, porque requeriría una cuenta con
facturación. `sql/bigquery.sql` está revisado a mano contra las consultas de
DuckDB, no por un test.

## Licencia

MIT para el código. Los datos son NOAA GSOD, dominio público del Gobierno de
EE. UU.
