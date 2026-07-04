# Meshtastic LoRa Gateway Runbook (BayoGate pattern)

*Proven 2026-06-11 on Heltec V3 "BayoGate" (!433aeed8), firmware 2.7.25, after
a long fight with 2.7.x firmware bugs. This REPLACES the gateway section in
HAVEN_COP_HANDOFF.md — that procedure is insufficient on 2.7 firmware.*

## End state

USB/any Meshtastic node → WiFi (house LAN) → mosquitto on bayoserv :1883
(user `bayogate`) → meshtak-bridge → TAK Server. Verified: text from node
appears in ATAK/WinTAK All Chat Rooms (`chat Mesh-eed8: ... -> TAK`).

## THE THREE LESSONS (read before touching anything)

1. **Every config write reboots the node, and writes that arrive during a
   reboot are SILENTLY EATEN** (CLI still prints "Writing... to device").
   Therefore: **one `--set` per command, wait 40 s between commands, verify
   with `--get` after anything important.** Never chain multiple `--set`
   flags for the mqtt section; never fire commands back-to-back.
2. **Firmware 2.7.15 cannot be MQTT-provisioned at all** (config silently not
   persisted — meshtastic/firmware#9107; partial fix #9934 shipped 2.7.21 but
   2.7.25 still required the per-field/wait discipline). If a node is on
   2.7.15–2.7.20: flash 2.7.25+ first (procedure below).
3. **Long MQTT passwords <REDACTED>
   authenticated from firmware (suspected struct truncation). Gateways use the
   dedicated account `bayogate` with a 16-char password
   (in `~/tak-client/HAVEN_COP_NOTES.txt` on bayoserv). The 32-char
   `meshtastic` account is for server-side processes (bridge, injector) only.

## Procedure (any new gateway node, from COMP2 or any box w/ python)

Prereqs: `pip install meshtastic esptool`; node on USB (find COM port via
Device Manager / `Get-PnpDevice`; CP210x or CH340 serial).

### 0. Identify + firmware gate
```
meshtastic --port COMx --info   # note hwModel, firmwareVersion, channel 0
```
If firmware < 2.7.21: download matching arch zip from
github.com/meshtastic/firmware releases (e.g. firmware-esp32s3-*.zip for
Heltec V3), extract `firmware-<board>-<ver>.bin`, then:
```
esptool --port COMx --baud 921600 write-flash 0x10000 <board-ver>.bin
```
(0x10000 = app-only update, keeps settings. If config storage is suspect,
nuke instead: `erase-flash` + write `.factory.bin` at 0x0, reconfigure all.)

### 1. Channel (skip if already on fleet channel)
Fleet channel = `HAVEN2`, custom PSK <REDACTED>
existing fleet node: `--info` → "Primary channel URL", then on the new node
`--seturl <url>`. Enable gateway flags (one command, these tolerate pairing):
```
meshtastic --port COMx --ch-index 0 --ch-set uplink_enabled true --ch-set downlink_enabled true
```

### 2. MQTT — ONE FIELD AT A TIME, 40 s BETWEEN EACH
```
meshtastic --port COMx --set mqtt.enabled true              # wait 40s
meshtastic --port COMx --set mqtt.address 192.168.1.28      # wait 40s
meshtastic --port COMx --set mqtt.username bayogate         # wait 40s
meshtastic --port COMx --set mqtt.password <REDACTED>
meshtastic --port COMx --set mqtt.encryption_enabled false  # wait 40s
meshtastic --port COMx --set lora.config_ok_to_mqtt true    # wait 40s
```
Verify: `meshtastic --port COMx --get mqtt.address --get mqtt.username`
(password <REDACTED>

### 3. Owner + WiFi (WiFi LAST — wrong SSID wedges ESP32 serial API)
```
meshtastic --port COMx --set-owner <Name> --set-owner-short <ABC>   # wait 40s
meshtastic --port COMx --set network.wifi_enabled true --set network.wifi_ssid TestReplacement13Nov24 --set network.wifi_psk <REDACTED>
```
(network section tolerates multi-set; SSID typo recovery: esptool hard reset
or decoy hotspot — see HAVEN_COP_HANDOFF.md gotchas.)

### 4. Verify end-to-end
On bayoserv:
```
sudo tail -f /var/log/mosquitto/mosquitto.log
   # want: New client connected ... as !<nodeid> ... u'bayogate'
   # "not authorised" = password <REDACTED>
journalctl -u meshtak-bridge -f
```
Force traffic from the node: `meshtastic --port COMx --sendtext 'radio check'`
→ bridge logs `chat ...: radio check -> TAK` → message visible in ATAK/WinTAK
All Chat Rooms. That line = gateway DONE.

## Notes
- Node's own callsign shows as `Mesh-xxxx` until its NODEINFO broadcast
  arrives (interval 3 h); cosmetic, fixes itself.
- mosquitto restart bounces the bridge; it auto-reconnects (watch for
  "MQTT connected rc=0").
- The YAML route (`--export-config` / `--configure`) is fine for NON-mqtt
  sections but the mqtt section must still be done per-field afterwards.
- These quirks are exactly what Tether Phase D automates: pinned firmware
  flash + per-field-with-verify config writer.
