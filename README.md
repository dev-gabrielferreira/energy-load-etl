# energy-load-etl

Batch pipeline for Brazilian electricity load data, from the ONS open data portal.

27 yearly CSVs covering 2000 to 2026, one row per hour per subsystem. Everything is
downloaded with a local cache, put through six validation rules, written to partitioned
Parquet, and served by a Streamlit dashboard. Rows that fail validation are not dropped
in silence: they go to a quality report with the rule, the reason, and the line they
came from.

Work in progress. The API client and the full documentation land with v1.0.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone <repo-url> && cd energy-load-etl
uv sync

uv run python -m energy_load_etl.pipeline     # download, validate, write Parquet
uv run streamlit run dashboard/app.py         # dashboard on localhost:8501
```

The first run downloads about 39 MB from the ONS S3 bucket. After that the pipeline
compares ETags and only re-downloads years that changed, which happens more often than
you would expect: ONS revises past data.

Useful flags:

```bash
uv run python -m energy_load_etl.pipeline --sem-download   # use whatever is in data/raw
uv run python -m energy_load_etl.pipeline --anos 2018 2019 # specific years
uv run pytest                                              # 56 tests
```

## What it writes

| Path | What |
|---|---|
| `data/raw/` | CSVs exactly as ONS published them, never edited |
| `data/processed/horario/ano=YYYY/id_subsistema=XX/` | hourly data, 933,620 rows across 108 partitions |
| `data/processed/diario/`, `mensal/` | daily and monthly aggregates, each row declaring how many hours it is made of |
| `data/processed/qualidade/` | rows read, approved and rejected, year by year |
| `data/rejected/` | every rejected row with its rule and source line, plus `relatorio.md` |

`data/` is gitignored. Nothing here is committed.

## The interesting part

Brazil observed daylight saving time until 2019, and the ONS files record it in a way
that breaks every count. Days with 25 hours do not exist in the data: when 11 PM
happened twice, the format had nowhere to put the second measurement, so one real
reading was dropped at the source. Days with 23 hours do exist, but only through 2013,
because from 2014 on ONS started writing the missing hour as an empty row.

So there is no "24 rows per day" and no "8,760 per year" that holds for every year.
Validation compares sets of instants against the real clock grid from `zoneinfo`
instead of counting rows, and no daylight saving date appears anywhere in the code.
Full write-up in [docs/decisions.md](docs/decisions.md).

Data source: [ONS Curva de Carga Horaria](https://dados.ons.org.br/dataset/curva-carga-ho),
licensed CC-BY. This project is not an official ONS product.
