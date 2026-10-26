# Price lists

An aligned table:

| Item      | Price | Stock |
|:----------|:-----:|------:|
| Tube      |  4.50 |    12 |
| Patch kit |  3.00 |    40 |

An unaligned table without outer pipes:

Item | Price
--- | ---
Chain | 12.00
Cassette | 30.00

Inline code with an escaped pipe:

| Command | Meaning |
| --- | --- |
| `a \| b` | pipe the output |
| `echo ok` | print ok |

A one-column table:

| Tools |
|-------|
| Wrench |
| Pump |

A paragraph that runs straight into a table:
| Name | Role |
| ---- | ---- |
| Ada | Mechanic |
| Grace | Treasurer |

A table with an empty cell:

| Name | Notes |
| ---- | ----- |
| Ada |  |
| Grace | Late on Mondays |

A table right before a fence:

| A | B |
|---|---|
| 1 | 2 |
```text
the fence follows the table with no blank line
```
