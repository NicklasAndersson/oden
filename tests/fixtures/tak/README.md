# Real CoT samples

Captured off a live TAK Server 5.7 (`tak.hv-sog.se`) from real ATAK-CIV 5.6
clients. Used by `tests/test_tak_real_samples.py` to lock in inbound parsing.

| file | type | what it is |
|---|---|---|
| `8s_report.xml` | `a-h-G` | 8S enemy-observation report from the **8S** plugin (`com.atakmap.android.eights.plugin`). English field names flattened into attributes on `<_8S_>` |
| `8s_hvreports.xml` | `a-x-X` | The *same report type* from the **HV Rapporter** plugin (`com.atakmap.android.hvreports.plugin`). Swedish field names as element text, wrapped in `<HVSS_DOCUMENTS>`, ISO-8601 UTC timestamp. Both plugins are enabled side by side across the fleet |
| `mission_package_8s.zip` | – | Mission package: an 8S sent *with* an attachment never reaches the CoT stream. Contains the manifest, the CoT and a 0-byte JPEG (an ATAK bug) |
| `mission_package_8s_with_image.zip` | – | Same package with a working image, for the normal path |
| `spi_pointer.xml` | `b-m-p-s-p-i` | Digital pointer / SPI (long-press pointer) |
| `friendly_pli.xml` | `a-f-G-U-C` | Self-position of a team member — the PLI flood we filter out |
| `takproto_v.xml` | `t-x-takp-v` | Server protocol-version announcement (no position) |

## Data packages

| file | what it is |
|---|---|
| `enrollment_package.pref` | The `.pref` from a trust-only ATAK data package: server CA + `enrollForCertificateWithTrust0`, no client cert. Same key layout as a real one, with the host and passwords replaced. `tests/test_tak_pref_package.py` wraps it in a zip together with a generated CA. |
