# Frames retention: archive off-box to the NAS

The raw `frames` table (one zlib world-snapshot per tick) is the only unbounded
grower — ~7 GiB/day. Policy (operator's choice): **archive old frames to the
TrueNAS, then reclaim local space** — never downsample, never lose data.

## The chain

`tools/archive_frames.py` (run daily by cron, no Claude needed):

1. Find every **closed** run whose newest frame is older than the hot window
   (default **48h**) and not already archived.
2. Export its frames to a gzip-JSONL archive that reconstructs the rows
   byte-for-byte (base64 of the stored zlib blob) — see `steemer/archive.py`.
3. Ship it to the NAS and **independently re-verify** the shipped copy
   (size + sha256) — `steemer/shippers.py`.
4. Only on a verified match: delete the local frames, checkpoint the WAL.
   Freed pages are reused by the live writer, so the file stops *growing*.

**Safety invariant:** a frame is never deleted until its archive is shipped
*and* re-observed on the remote with a matching checksum. Any failure leaves the
run fully intact locally and is logged; nothing is lost. The pass also refuses
to run if `/mnt/nas` is not a live mount (so it can't silently stage on local
disk when the NAS is down).

## Infrastructure (set up once, persists across reboots)

- **Mount:** TrueNAS SMB share `//truenas/samba_share` → `/mnt/nas` via
  `smbnetfs` (SMB2/3 over FUSE; FreeBSD base `mount_smbfs` is SMB1-only and
  TrueNAS has SMB1 disabled). The share content is at
  `/mnt/nas/truenas.chack.internal/samba_share/`; archives go under
  `steemer-archives/`.
- **Boot persistence:** `kld_list += fusefs`, `smbnetfs_enable=YES`, and the
  rc.d service in `ops/smbnetfs.rc` (installed at
  `/usr/local/etc/rc.d/smbnetfs`). Verify: `service smbnetfs status`.
- **Credentials:** `/root/.smb/smbnetfs.auth` (mode 600, root-only). **Never in
  this repo.** Config: `/root/.smb/smbnetfs.{conf,host}`, `/usr/local/etc/smb4.conf`.
- **Schedule:** cron for `cal`, daily 04:17 → `uv run tools/archive_frames.py`,
  logging to `archive/cron.log` (gitignored).

## Restore

`steemer.archive.read_archive("<file>.jsonl.gz")` yields the original rows
(`seq,tick,world,received_at,run_id,blob`); re-INSERT into `frames` (json=blob)
to replay an archived window. Manifest of what was shipped where lives in the
`archives` table in `guild_log.db`.

## Known limitation (walk-away with a long-open run)

Archival is per **closed** run. A run stays open until the next redeploy, so if
the improvement loop pauses for a long time (e.g. a usage cap) the *current* run
never ages out and its frames are not archived — that one run can grow unbounded.
While actively iterating this is a non-issue (redeploys close runs constantly).
Fix under consideration: rotate the run window on a timer (close+reopen every
~24h) so even a walk-away bot produces closed, archivable runs; or archive
frames by age from the open run too. Tracked in `findings.jsonl`.
