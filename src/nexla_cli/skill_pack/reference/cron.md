# `start_cron` — Quartz cron quick reference

Shared by source and custom_rest scheduling. This is **Quartz cron**, not Unix cron.

7 fields: `second minute hour day-of-month month day-of-week year`. Year is optional; `*` means every year.

- Quartz requires **exactly one** of day-of-month / day-of-week to be `?` (you can't pin both).
- Weekdays accept `SUN`–`SAT` or `1`–`7` (SUN=1, SAT=7).
- `/` = steps (`0/15` = every 15), `-` = ranges (`MON-FRI`), `,` = lists (`MON,THU`).

| Cadence | Cron |
|---|---|
| Daily 00:00 UTC (default) | `0 0 0 * * ? *` |
| Every Mon 09:00 | `0 0 9 ? * MON *` |
| Weekdays 09:00 | `0 0 9 ? * MON-FRI *` |
| Mon & Thu 09:00 | `0 0 9 ? * MON,THU *` |
| Hourly on the hour | `0 0 * * * ? *` |
| Every 15 minutes | `0 0/15 * * * ? *` |
| 1st of month 09:00 | `0 0 9 1 * ? *` |

Common bug: pasting a 5-field Unix expression (no `?`) — Nexla rejects it. `schedule: "once"` on the create body ignores `start_cron` entirely.
