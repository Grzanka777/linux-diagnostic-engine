# v0.5 multi-workstation portability corpus

These fixtures encode source-state contracts, not machine identities or raw
reports. They are derived from the accepted v0.4 second-workstation evidence
and a contrasting home-like capability profile. No hostname, username, home
path, UUID, serial, address, or private report is included.

`home-like-capability-profile.json` represents authoritative optional sources,
including UPower and user systemd, with one unrelated optional source absent.
`office-like-capability-profile.json` represents the accepted limitations:
NVMe unavailable, direct kernel-log access restricted, the user systemd bus
limited, and Btrfs inspection privilege-limited. UPower remains available.

The shared semantic contract is intentionally small:

- an unavailable source does not create a Finding;
- a limited source is neither health nor failure evidence;
- capability visibility does not change the existing RAW -> OBS -> Evidence ->
  Finding pipeline.

The corpus is safe to keep under source control and must not be replaced with
the original workstation reports.
