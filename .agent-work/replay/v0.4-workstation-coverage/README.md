# v0.4 workstation coverage replay corpus

This corpus contains sanitized, bounded command-shaped fixtures for the three
v0.4 diagnostic contracts. Hostnames, usernames, hardware identifiers, device
paths, connection profiles, and timestamps are synthetic.

| Fixture | Source contract | Expected result |
| --- | --- | --- |
| `networkmanager-activation-failure.txt` | `journalctl -b -u NetworkManager --no-pager` | one NetworkManager activation-failure observation |
| `networkmanager-healthy.txt` | same source | no activation-failure observation |
| `network-device-watchdog.txt` | `journalctl -b -k --no-pager` | one network-device watchdog observation |
| `network-device-healthy.txt` | same source | no watchdog observation |
| `upower-critical.txt` | `upower -d` | two critical power-source records |
| `upower-healthy.txt` | same source | no critical power-source observation |
| `upower-near-miss.txt` | same source | ordinary discharging is not an alarm |

Fixture SHA-256 manifest:

| File | SHA-256 |
| --- | --- |
| `networkmanager-activation-failure.txt` | `d43ff7348e1c6ff47a7459545ba6b1660fc1636668b9bfa2b064fd423941dc44` |
| `networkmanager-healthy.txt` | `c49dd7d8cf5db07f1d1b0431eb3ef775b4e0d51910d6d533f70f799374f4cd19` |
| `network-device-watchdog.txt` | `e0872fe7b320f01133222035b221de74914979196591ff279f965b366c18c66a` |
| `network-device-healthy.txt` | `3c1878207cf18fdeededf94050402cd0ad86cf8493d53788ebc70f6368eedbd5` |
| `upower-critical.txt` | `d19215e378b2e339c55ade40acefa7d4a59b71d4fba302d5ee21b99d3ab3b819` |
| `upower-healthy.txt` | `2d8c283618b8e78e3d9a4e18ec47c087528ff53ee7d08b906e06ac8c3211d65f` |
| `upower-near-miss.txt` | `d01b11dd936f6bc0cef49cac02f1f38418a6d471051f4c64a802e66d975acc6e` |

The replay corpus is evidence-only. It is not a benchmark and does not grant
authority to infer network reachability, root cause, hardware identity, or
repair actions.
