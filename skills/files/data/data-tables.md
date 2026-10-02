# Data tables: declared, loaded, counted

The data a study uses lives as tables in the paper's `data.db`. Three
specialists share one contract about them.

## The data architect declares them

`data_dictionary.json` has a top-level `tables` list: every table the data
analyst will load, before any data are pulled.

```json
{
  "tables": [
    {"name": "spy_prices", "source": "yfinance", "series": "SPY", "frequency": "daily", "role": "market index; trading calendar"},
    {"name": "kbe_prices", "source": "yfinance", "series": "KBE", "frequency": "daily", "role": "bank stocks"},
    {"name": "dgs2", "source": "fred", "series": "DGS2", "frequency": "daily", "role": "2-year Treasury yield"}
  ]
}
```

Naming: lower case, letters, digits and `_`. Daily price series of a ticker
are `<ticker>_prices` (`spy_prices`, `xlf_prices`); a FRED series is its id in
lower case (`dgs2`, `dfedtaru`). Tables the researcher supplied (from the data
folder) keep the name they already have in `data.db`; do not redeclare them.

## The data analyst loads them, and only loads them

The data analyst loads, cleans and describes data. **It never estimates**: no
market model, no abnormal returns, no CARs, no regressions, no test
statistics, no result tables or figures. Estimation is the econometrics
specialist's work, and in templates with a pre-registration it may only start
after the plan is frozen; the pipeline stops the run when estimation output
exists before that.

- Load every declared table with the data wrapper and its `--table` flag, so
  the rows land in `data.db` under the declared name:

  ```
  e2er-data yfinance history --ticker SPY --start 2014-01-01 --end 2025-12-31 --interval 1d \
      --save-to spy_prices.csv --table spy_prices
  e2er-data fred series --series-id DGS2 --start 2014-01-01 --end 2025-12-31 \
      --save-to dgs2.csv --table dgs2
  ```

  The result reports `saved_table` and `saved_table_rows`: the real count.
- Cleaning scripts may derive further tables (e.g. daily returns), but they
  must not overwrite the loaded raw tables.
- `data_summary.md` names every declared table with its **actual** row count,
  as `data.db` holds it (e.g. "spy_prices: 3,018 rows, 2014-01-02 to
  2025-12-31"). Never write expected or approximate counts ("~2,520").

- A table must hold values, not only dates. If the connector fails (for
  instance FRED rejects the API key), `e2er-data … --table` exits non-zero
  and leaves `data.db` untouched: report the error, do not build the table
  some other way with empty values.

The contract fails when a declared table is missing from `data.db` or empty,
when a value column of a declared table is less than 90% non-null (the
message says e.g. `dgs2.value: 0 of 2765 non-null`), or when
`data_summary.md` does not give a table's actual row count. A series that is
legitimately sparse declares its share in the data dictionary:
`{"name": "dgs2", …, "min_non_null": 0.5}`, or per column under `columns`
(`[{"name": "value", "min_non_null": 0.5}]`). When a table's entry lists
`columns`, those columns are checked; otherwise every column that is not a
date. Tables the researcher supplied are checked only where their columns
are declared.

## Everyone else reads them by name

Specialists that refer to data (the identification strategist naming a
trading calendar, the econometrics specialist loading prices) use the table
names from `data_dictionary.json` `tables`, and nothing else.
