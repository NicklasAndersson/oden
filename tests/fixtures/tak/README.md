# Real CoT samples

Captured off a live TAK Server 5.7 (`tak.hv-sog.se`) from real ATAK-CIV 5.6
clients. Used by `tests/test_tak_real_samples.py` to lock in inbound parsing.

| file | type | what it is |
|---|---|---|
| `8s_report.xml` | `a-h-G` | 8S enemy-observation report (ATAK Reports plugin). Fields flattened into attributes on `<_8S_>` |
| `spi_pointer.xml` | `b-m-p-s-p-i` | Digital pointer / SPI (long-press pointer) |
| `friendly_pli.xml` | `a-f-G-U-C` | Self-position of a team member — the PLI flood we filter out |
| `takproto_v.xml` | `t-x-takp-v` | Server protocol-version announcement (no position) |
