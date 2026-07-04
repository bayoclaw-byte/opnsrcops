# HAVEN COP — Agent Handoff (bayo-serv)

**Read this first if you are an agent (or human) working on the Haven/Meshtastic/TAK
common-operating-picture system on this machine.**

Last updated: 2026-06-09 (meshtak-bridge deployment session, run from COMP2).
History: TAK Server + mosquitto sentinel listener stood up 2026-05-24 (see
`~/pigeon-tasks/logs/20260524T135229_codex_atak-mqtt-setup.log`); bridge,
Mumble, and gateway-radio work added 2026-06-09.

## Mission context

Small team operating beyond connectivity. Goal: one COP in ATAK/iTAK with
location sharing (PLI), messaging, and later VoIP. Two radio layers:

- **Haven / OpenMANET HaLow mesh** (802.11ah, Pi 5 gates w/ MM8108 radios) —
  full-bandwidth IP backbone. Gate "green" = 192.168.1.153 (OpenWrt/dropbear).
  EUDs (phones in pouch kits) connect to a gate's AP and reach TAK Server here.
- **Meshtastic LoRa** (T-Beams etc., incl. SOLAR-POWERED FIELD NODES already
  deployed) — low-bandwidth fallback layer: PLI + chat only (~237-byte packets).
  Reaches this server via a WiFi gateway radio → MQTT.

Architecture decision record: Reticulum/RNode reflash was researched and
REJECTED for now (no Reticulum→TAK bridge exists anywhere; stock Meshtastic
keeps the whole TAK ecosystem). Full research report on COMP2:
`C:\Users\awrig.COMP2\meshtastic-haven-tak-integration-report.md`.

## System map (all on this host, 192.168.1.28, Ubuntu 24.04)

```
LoRa mesh ──> gateway radio (WiFi) ──> mosquitto :1883 ──> meshtak-bridge ──> TAK Server :8089 (TLS)
                                          (sentinel)         (systemd)   <──── downlink: GeoChat→mesh text
ATAK/iTAK EUDs (HaLow or LAN) ────────────────────────────────────────────> TAK Server :8089
WinTAK/admin ──> https://192.168.1.28:8443/Marti
Future voice: Mumble :64738 (installed, enabled)
```

| Component | Location | Service |
|---|---|---|
| TAK Server 5.7 (pvarki docker, 6 containers + postgis) | `/opt/takserver/docker-compose.yml`, env `takserver.env` | docker, `unless-stopped` |
| TAK data/certs volume | `/var/lib/docker/volumes/tak_takserver_data/_data/` (certs under `certs/files/`) | — |
| mosquitto + "sentinel" Meshtastic listener | `/etc/mosquitto/conf.d/sentinel.conf` (1883, password <REDACTED>
| **meshtak-bridge** | `/opt/meshtak-bridge/` (`bridge.py`, venv, `bridge.env`, `certs/`) | `meshtak-bridge.service` |
| Mumble VoIP | `/etc/mumble/mumble-server.ini` | `mumble-server.service` |
| Credentials & connection notes | `~/tak-client/WINTAK_CONNECTION.txt` and `~/tak-client/HAVEN_COP_NOTES.txt` | — |

**All passwords** (TAK certs, Marti admin, MQTT user `meshtastic`, Mumble
SuperUser) are in those two files in `~/tak-client/`. Do not duplicate them
elsewhere.

UNRELATED tenants on this box — do not disturb: Sentinel drone-tracker
(port 5900, `~/dev/drone-tracker-opencv`), iNTERCEPT SDR (`~/dev/intercept`),
lighttpd :80, gnome-remote-desktop :3389, tailscale (100.98.183.88).

## meshtak-bridge (custom, built 2026-06-09)

`/opt/meshtak-bridge/bridge.py`, runs as user `meshtak`. Copies of all sources
+ deploy scripts also on COMP2 at `C:\Users\awrig.COMP2\haven-tak\`.

- **Uplink**: subscribes `msh/#`, decodes Meshtastic `ServiceEnvelope` protobufs:
  - `POSITION_APP` → CoT PLI `a-f-G-U-C`, uid `MESH-<nodenum hex>`, callsign from cached NODEINFO
  - `TEXT_MESSAGE_APP` → GeoChat to All Chat Rooms
  - `ATAK_PLUGIN` (portnum 72, TAKPacket from the official ATAK plugin / TAK_TRACKER role) → PLI + chat (unishox2 decompression)
  - `TELEMETRY_APP` → battery cached, attached to PLI `<status>`
- **Downlink**: TAK GeoChat (`b-t-f`) → mesh broadcast text `"callsign: msg"`,
  published to the per-channel topic learned from uplink traffic, gateway id `!bb6d6e8c`.
- Loop prevention: drops MQTT envelopes with our gateway_id; drops TAK events with `MESH-*` uids.
- TAK auth: client cert CN=meshbridge (expires 2028-06), files in `/opt/meshtak-bridge/certs/`.
  Regenerate via `makeCert.sh` (see "Make certs" below).
- Config: `/opt/meshtak-bridge/bridge.env`. Logs: `journalctl -u meshtak-bridge -f`.
- Encrypted-payload note: gateway radios must use `mqtt.encryption_enabled=false`
  (payload decrypted at gateway; broker is LAN+password; matches the OpenTAKServer pattern).
  Encrypted envelopes are skipped with a debug log.

### Verified working (2026-06-09)
Synthetic test: `test_inject.py` publishes nodeinfo+position+text for fake node
`!deadbeef` → bridge → TAK Server broadcast both PLI and GeoChat to a second TLS
client. Re-run anytime:

```bash
# copies live in /tmp may be gone; originals on COMP2 haven-tak/; inline gist:
sudo env ADMIN_CERT_PASS=<see WINTAK_CONNECTION.txt> MQTT_PASS=<see notes> bash /tmp/verify-e2e.sh
```

## Gateway radio status — ACTION LIKELY NEEDED

The LoRa→MQTT link needs ONE always-on Meshtastic node on home WiFi with MQTT
uplink. **As of 2026-06-09 night this is NOT yet live**:

- A Heltec V4 ("BayoGate", `!a6963878`) was configured from COMP2 over USB
  (COM6) but was given the WiFi SSID `2.4ghz`, which NO LONGER EXISTS.
  **The live house SSID is `TestReplacement13Nov24`** (2.4GHz on ch 6; password
  in COMP2's saved WiFi profiles, same as old 2.4ghz profile). With an
  unjoinable SSID the ESP32's scan loop starves its serial PhoneAPI — device
  appears wedged. Workarounds that worked: `esptool --port COMx --after
  hard_reset chip_id` to force reboot; or broadcast a decoy hotspot with the
  configured SSID so it joins and the API recovers (script:
  COMP2 `haven-tak\hotspot.ps1`).
- Owner said he will bring a DIFFERENT board for the gateway role.

### To configure ANY new gateway radio (from any box with python + USB):

```bash
pip install meshtastic
meshtastic --port <PORT> --set-owner "BayoGate" --set-owner-short "BGW" \
  --ch-index 0 --ch-set uplink_enabled true --ch-set downlink_enabled true
meshtastic --port <PORT> \
  --set mqtt.enabled true --set mqtt.address 192.168.1.28 \
  --set mqtt.username meshtastic --set mqtt.password <REDACTED>
  --set mqtt.encryption_enabled false --set mqtt.json_enabled false \
  --set network.wifi_enabled true \
  --set network.wifi_ssid 'TestReplacement13Nov24' --set network.wifi_psk <REDACTED>
```

Success check (on this box):
```bash
sudo tail -f /var/log/mosquitto/mosquitto.log   # node connects as u'meshtastic' from a 192.168.1.x IP
journalctl -u meshtak-bridge -f                  # 'nodeinfo'/'PLI' lines as mesh traffic arrives
```
Then any node the gateway hears on LoRa (incl. the solar field nodes) paints in
TAK automatically.

## Make certs for new EUDs / services

```bash
cd /var/lib/docker/volumes/tak_takserver_data/_data/certs   # as root
export COUNTRY=US STATE=NA CITY=NA ORGANIZATION=LocalTAK ORGANIZATIONAL_UNIT=Operations
export CAPASS='<CA_PASS from /opt/takserver/takserver.env>' PASS='<new cert password>'
yes | ./makeCert.sh client <username>
# results in files/<username>.{pem,key,p12}; .p12 + truststore-root.p12 go to the EUD
```
ATAK enrollment package pattern: see `~/tak-client/wintak.zip` as the model.

## Phone/EUD onboarding (the pouch-kit pattern)

- **Android**: ATAK + cert package (above) pointed at 192.168.1.28:8089 SSL
  (or the Tailscale IP remotely) + the official **Meshtastic ATAK plugin** with
  a BT-paired Meshtastic node for off-grid fallback. Both can run simultaneously;
  the map degrades gracefully from full TAK to LoRa PLI/chat.
- **iOS**: iTAK → same server when on LAN/HaLow; off-grid fallback = Meshtastic
  iOS app's local TAK server feature (app must stay foregrounded).
- Do NOT enable the ATAK plugin's "Relay to/from Server" on more than one EUD —
  and with this server-side bridge running you shouldn't enable it at all
  (the bridge already does that job; double-relaying = duplicate traffic).

## Backlog (priority order)

1. **Gateway radio live** (see above) — blocks the whole LoRa side.
2. **Fleet channel migration** (SECURITY): everything is on default LongFast +
   default PSK = <REDACTED>
   (solar nodes incl.) to a private channel, Short Fast preset. Requires field
   trip or remote-admin keys. Update the gateway + this doc after.
3. Solar-node RF reach: confirm field nodes are in LoRa range of the gateway's
   location; if not, add a second gateway radio at Haven gate green
   (meshtasticd or USB radio exposed via TCP 4403 — bridge/OTS pattern supports it;
   bridge dedupes by packet id so multiple gateways are safe).
4. TAK_TRACKER role for solar nodes during the channel-migration trip
   (cleaner PLI w/ callsigns, no phone needed).
5. Mumble phase 2: create team channel, test client over HaLow from a pouch kit,
   document codec/bandwidth behavior multi-hop.
6. ufw is INACTIVE — everything LAN-exposed. If enabling: allow 22, 80, 1883,
   3389, 5001, 5900, 8089, 8443, 64738 (+ tailscale) first, test, then enable.
7. Bridge nice-to-haves: paho v2 callback API, downlink as TAKPacket (portnum
   72) for plugin EUDs in the field, dedupe/rate metrics, handle
   ATAK_PLUGIN_V2 (portnum 78, zstd).

## Gotchas learned the hard way

- PowerShell 5.1 (COMP2) mangles inner double quotes in `ssh "..."` commands —
  scp script files over instead of inline heredocs (BOM issues too).
- `docker compose exec` into the pvarki tak containers does NOT land where
  expected; run cert scripts directly on the host volume path as root instead.
- Heltec V4 / ESP32-S3: WiFi-enable turns off BLE; an unjoinable SSID starves
  USB serial API (see gateway section for recovery).
- mosquitto sentinel listener requires auth: user `meshtastic` (password <REDACTED>
  notes file). `connection_messages true` is on — watch the log to debug clients.
- TAK Server takes minutes to start; check
  `sudo docker compose -p tak --env-file /opt/takserver/takserver.env -f /opt/takserver/docker-compose.yml ps`.
