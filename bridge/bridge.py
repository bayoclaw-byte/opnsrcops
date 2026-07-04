#!/usr/bin/env python3
"""meshtak-bridge: Meshtastic MQTT <-> TAK Server CoT bridge.

Uplink:  Meshtastic ServiceEnvelope protobufs published by gateway radios to the
         local mosquitto 'sentinel' listener are decoded (position, nodeinfo,
         text, telemetry, ATAK plugin TAKPackets) and injected into TAK Server
         as CoT over TLS (client cert auth, port 8089).
Downlink: GeoChat (b-t-f) events from TAK Server are forwarded to the mesh as
         plain Meshtastic text messages (broadcast), rate-limited.

Designed for: bayo-serv, TAK Server 5.7 (docker), mosquitto 1883 w/ password.
"""
import asyncio
import logging
import os
import random
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape, quoteattr

import paho.mqtt.client as mqtt
from meshtastic.protobuf import (atak_pb2, mesh_pb2, mqtt_pb2, portnums_pb2,
                                 telemetry_pb2)

try:
    import unishox2
except ImportError:
    unishox2 = None

log = logging.getLogger("meshtak")

# ---------------- config ----------------
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "meshtastic")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_SUB = os.environ.get("MQTT_SUB", "msh/#")

TAK_HOST = os.environ.get("TAK_HOST", "127.0.0.1")
TAK_PORT = int(os.environ.get("TAK_PORT", "8089"))
TLS_CERT = os.environ.get("TLS_CERT", "/opt/meshtak-bridge/certs/meshbridge.pem")
TLS_KEY = os.environ.get("TLS_KEY", "/opt/meshtak-bridge/certs/meshbridge.key")
TLS_CA = os.environ.get("TLS_CA", "/opt/meshtak-bridge/certs/root-ca.pem")

BRIDGE_ID = os.environ.get("BRIDGE_ID", "!bb6d6e8c")  # gateway id used on MQTT
BRIDGE_NODENUM = int(BRIDGE_ID.lstrip("!"), 16)
UID_PREFIX = "MESH"
PLI_STALE_S = int(os.environ.get("PLI_STALE_S", "900"))
DOWNLINK_CHAT = os.environ.get("DOWNLINK_CHAT", "true").lower() == "true"
DOWNLINK_MIN_INTERVAL = float(os.environ.get("DOWNLINK_MIN_INTERVAL", "2.0"))
COT_TYPE_DEFAULT = os.environ.get("COT_TYPE", "a-f-G-U-C")

# ---------------- state ----------------
nodes = {}  # nodenum -> dict(id,long,short,battery,hw)
seen = OrderedDict()  # (from,id) dedupe
chan_topics = {}  # channel_id -> uplink topic prefix for downlink publishing
injected_uids = set()  # uids we sent to TAK (loop prevention)


def now_dt():
    return datetime.now(timezone.utc)


def cot_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def node_uid(nodenum):
    return f"{UID_PREFIX}-{nodenum:08x}"


def node_callsign(nodenum):
    n = nodes.get(nodenum, {})
    return n.get("long") or n.get("short") or f"Mesh-{nodenum & 0xFFFF:04x}"


def dedupe(frm, pid):
    if pid == 0:
        return False
    k = (frm, pid)
    if k in seen:
        return True
    seen[k] = True
    while len(seen) > 1000:
        seen.popitem(last=False)
    return False


# ---------------- CoT builders ----------------
def pli_event(nodenum, lat, lon, hae=0.0, battery=None, course=None, speed=None):
    uid = node_uid(nodenum)
    cs = node_callsign(nodenum)
    injected_uids.add(uid)
    t = now_dt()
    detail = [
        f"<contact callsign={quoteattr(cs)}/>",
        '<__group name="Cyan" role="Team Member"/>',
        f'<takv device="Meshtastic" platform="meshtak-bridge" os="linux" version="1.0"/>',
        "<precisionlocation altsrc=\"GPS\" geopointsrc=\"GPS\"/>",
    ]
    if battery is not None:
        detail.append(f'<status battery="{int(battery)}"/>')
    if course is not None or speed is not None:
        detail.append(
            f'<track course="{course if course is not None else 0:.1f}" '
            f'speed="{speed if speed is not None else 0:.1f}"/>')
    detail.append(f"<remarks>via Meshtastic node {nodes.get(nodenum, {}).get('id', nodenum)}</remarks>")
    return (
        f'<event version="2.0" uid="{uid}" type="{COT_TYPE_DEFAULT}" how="m-g" '
        f'time="{cot_time(t)}" start="{cot_time(t)}" stale="{cot_time(t + timedelta(seconds=PLI_STALE_S))}">'
        f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="{hae:.1f}" ce="20.0" le="9999999.0"/>'
        f"<detail>{''.join(detail)}</detail></event>"
    )


def chat_event(nodenum, text):
    uid = node_uid(nodenum)
    cs = node_callsign(nodenum)
    injected_uids.add(uid)
    t = now_dt()
    mid = f"{uid}.{int(t.timestamp() * 1000)}"
    msg = escape(text)
    chat_uid = f"GeoChat.{uid}.All Chat Rooms.{mid}"
    injected_uids.add(chat_uid)
    return (
        f'<event version="2.0" uid="{chat_uid}" type="b-t-f" how="h-g-i-g-o" '
        f'time="{cot_time(t)}" start="{cot_time(t)}" stale="{cot_time(t + timedelta(days=1))}">'
        f'<point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0"/>'
        f'<detail><__chat parent="RootContactGroup" groupOwner="false" messageId={quoteattr(mid)} '
        f'chatroom="All Chat Rooms" id="All Chat Rooms" senderCallsign={quoteattr(cs)}>'
        f'<chatgrp uid0={quoteattr(uid)} uid1="All Chat Rooms" id="All Chat Rooms"/></__chat>'
        f'<link uid={quoteattr(uid)} type="a-f-G-U-C" relation="p-p"/>'
        f"<remarks source={quoteattr('BAO.F.meshtak.' + uid)} to=\"All Chat Rooms\" "
        f'time="{cot_time(t)}">{msg}</remarks></detail></event>'
    )


# ---------------- uplink decode ----------------
def maybe_unishox(data: bytes, compressed: bool) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        return data
    if compressed and unishox2 is not None:
        try:
            return unishox2.decompress(data, max(len(data) * 6, 64))
        except Exception:
            pass
    try:
        return data.decode("utf-8", "replace")
    except Exception:
        return ""


def handle_envelope(topic: str, payload: bytes, out: list):
    env = mqtt_pb2.ServiceEnvelope()
    env.ParseFromString(payload)
    pkt = env.packet
    frm = getattr(pkt, "from")
    if env.gateway_id == BRIDGE_ID:
        return  # our own downlink echoed back
    if dedupe(frm, pkt.id):
        return
    # learn downlink topic prefix: msh/<region>/2/e/<channel>/<gw>
    if "/2/e/" in topic and env.channel_id:
        chan_topics[env.channel_id] = topic.rsplit("/", 1)[0]
    if not pkt.HasField("decoded"):
        log.debug("encrypted packet from %08x on %s (enable mqtt encryption_enabled=false on gateway)", frm, topic)
        return
    port = pkt.decoded.portnum
    data = pkt.decoded.payload
    P = portnums_pb2.PortNum

    if port == P.NODEINFO_APP:
        u = mesh_pb2.User()
        u.ParseFromString(data)
        nodes.setdefault(frm, {}).update(
            id=u.id, long=u.long_name, short=u.short_name)
        log.info("nodeinfo %08x -> %s (%s)", frm, u.long_name, u.id)

    elif port == P.POSITION_APP:
        p = mesh_pb2.Position()
        p.ParseFromString(data)
        if p.latitude_i == 0 and p.longitude_i == 0:
            return
        lat, lon = p.latitude_i * 1e-7, p.longitude_i * 1e-7
        bat = nodes.get(frm, {}).get("battery")
        out.append(pli_event(frm, lat, lon, float(p.altitude), bat))
        log.info("PLI %s %.5f,%.5f -> TAK", node_callsign(frm), lat, lon)

    elif port == P.TELEMETRY_APP:
        t = telemetry_pb2.Telemetry()
        t.ParseFromString(data)
        if t.HasField("device_metrics"):
            nodes.setdefault(frm, {})["battery"] = t.device_metrics.battery_level

    elif port == P.TEXT_MESSAGE_APP:
        text = data.decode("utf-8", "replace")
        out.append(chat_event(frm, text))
        log.info("chat %s: %s -> TAK", node_callsign(frm), text[:60])

    elif port in (P.ATAK_PLUGIN, 72):
        tp = atak_pb2.TAKPacket()
        tp.ParseFromString(data)
        cs = maybe_unishox(tp.contact.callsign, tp.is_compressed)
        if cs:
            nodes.setdefault(frm, {})["long"] = cs
        if tp.HasField("pli") and (tp.pli.latitude_i or tp.pli.longitude_i):
            bat = tp.status.battery if tp.HasField("status") else None
            out.append(pli_event(frm, tp.pli.latitude_i * 1e-7,
                                 tp.pli.longitude_i * 1e-7,
                                 float(tp.pli.altitude), bat,
                                 float(tp.pli.course), float(tp.pli.speed)))
            log.info("TAKPacket PLI %s -> TAK", node_callsign(frm))
        elif tp.HasField("chat"):
            msg = maybe_unishox(tp.chat.message, tp.is_compressed)
            if msg:
                out.append(chat_event(frm, msg))
                log.info("TAKPacket chat %s: %s -> TAK", node_callsign(frm), msg[:60])


# ---------------- downlink (TAK -> mesh) ----------------
def build_downlink(text: str) -> list:
    """Return [(topic, payload)] ServiceEnvelope text broadcasts per known channel."""
    res = []
    for chan, prefix in chan_topics.items():
        pkt = mesh_pb2.MeshPacket()
        setattr(pkt, "from", BRIDGE_NODENUM)
        pkt.to = 0xFFFFFFFF
        pkt.id = random.getrandbits(32)
        pkt.hop_limit = 3
        pkt.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
        pkt.decoded.payload = text.encode("utf-8")[:200]
        env = mqtt_pb2.ServiceEnvelope()
        env.packet.CopyFrom(pkt)
        env.channel_id = chan
        env.gateway_id = BRIDGE_ID
        res.append((f"{prefix}/{BRIDGE_ID}", env.SerializeToString()))
    return res


def parse_tak_event(xml_text: str):
    """Return downlink text for GeoChat events from TAK side, else None."""
    try:
        ev = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    if ev.get("type") != "b-t-f":
        return None
    uid = ev.get("uid", "")
    if uid in injected_uids or f".{UID_PREFIX}-" in uid:
        return None
    chat = ev.find(".//__chat")
    remarks = ev.find(".//remarks")
    if remarks is None or not (remarks.text or "").strip():
        return None
    sender = (chat.get("senderCallsign") if chat is not None else None) or "TAK"
    return f"{sender}: {remarks.text.strip()}"


# ---------------- workers ----------------
class Bridge:
    def __init__(self):
        self.loop = None
        self.cot_q = asyncio.Queue(maxsize=500)   # CoT XML -> TAK
        self.mesh_q = asyncio.Queue(maxsize=50)   # text -> mesh
        self.mq = None

    # MQTT (paho thread) -------------------------------------------------
    def mqtt_start(self):
        c = mqtt.Client(client_id="meshtak-bridge", clean_session=True)
        c.username_pw_set(MQTT_USER, MQTT_PASS)
        c.on_connect = lambda c, u, f, rc: (
            log.info("MQTT connected rc=%s, subscribing %s", rc, MQTT_SUB),
            c.subscribe(MQTT_SUB))
        c.on_message = self.on_mqtt
        c.reconnect_delay_set(1, 30)
        c.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        c.loop_start()
        self.mq = c

    def on_mqtt(self, client, userdata, msg):
        if "/2/e/" not in msg.topic and "/2/c/" not in msg.topic:
            return
        out = []
        try:
            handle_envelope(msg.topic, msg.payload, out)
        except Exception as e:
            log.debug("decode failed on %s: %s", msg.topic, e)
            return
        for cot in out:
            self.loop.call_soon_threadsafe(self._q_put, cot)

    def _q_put(self, cot):
        try:
            self.cot_q.put_nowait(cot)
        except asyncio.QueueFull:
            log.warning("CoT queue full, dropping")

    # TAK TLS stream ------------------------------------------------------
    async def tak_loop(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        ctx.load_verify_locations(TLS_CA)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        while True:
            try:
                reader, writer = await asyncio.open_connection(
                    TAK_HOST, TAK_PORT, ssl=ctx)
                log.info("connected to TAK %s:%s", TAK_HOST, TAK_PORT)
                await asyncio.gather(self._tak_tx(writer), self._tak_rx(reader))
            except Exception as e:
                log.warning("TAK connection error: %s; retrying in 5s", e)
                await asyncio.sleep(5)

    async def _tak_tx(self, writer):
        while True:
            try:
                cot = await asyncio.wait_for(self.cot_q.get(), timeout=45)
            except asyncio.TimeoutError:
                cot = (f'<event version="2.0" uid="meshtak-bridge-ping" type="t-x-c-t" '
                       f'how="m-g" time="{cot_time(now_dt())}" start="{cot_time(now_dt())}" '
                       f'stale="{cot_time(now_dt() + timedelta(seconds=120))}">'
                       f'<point lat="0" lon="0" hae="0" ce="9999999" le="9999999"/></event>')
            writer.write(cot.encode())
            await writer.drain()

    async def _tak_rx(self, reader):
        buf = b""
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                raise ConnectionError("TAK stream closed")
            buf += chunk
            while b"</event>" in buf:
                raw, buf = buf.split(b"</event>", 1)
                if not DOWNLINK_CHAT:
                    continue
                text = parse_tak_event(raw.decode("utf-8", "replace") + "</event>")
                if text:
                    try:
                        self.mesh_q.put_nowait(text)
                    except asyncio.QueueFull:
                        log.warning("mesh downlink queue full, dropping")

    # mesh downlink publisher ---------------------------------------------
    async def mesh_tx(self):
        while True:
            text = await self.mesh_q.get()
            if not chan_topics:
                log.info("no mesh channel learned yet, dropping downlink: %s", text[:40])
                continue
            for topic, payload in build_downlink(text):
                self.mq.publish(topic, payload)
                log.info("downlink -> %s : %s", topic, text[:60])
            await asyncio.sleep(DOWNLINK_MIN_INTERVAL)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.mqtt_start()
        await asyncio.gather(self.tak_loop(), self.mesh_tx())


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    if unishox2 is None:
        log.warning("unishox2 not installed; compressed TAKPacket strings limited")
    log.info("meshtak-bridge starting: mqtt=%s:%s tak=%s:%s bridge_id=%s",
             MQTT_HOST, MQTT_PORT, TAK_HOST, TAK_PORT, BRIDGE_ID)
    asyncio.run(Bridge().run())


if __name__ == "__main__":
    main()
