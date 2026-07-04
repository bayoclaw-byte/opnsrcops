#!/usr/bin/env python3
"""Publish synthetic Meshtastic ServiceEnvelopes to the sentinel MQTT listener,
simulating a solar field node uplinked by a gateway radio."""
import os
import time
import random
import paho.mqtt.client as mqtt
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2

NODE = 0xDEADBEEF
GW = "!aabbccdd"
TOPIC = "msh/US/2/e/LongFast/" + GW


def envelope(portnum, payload, pid):
    pkt = mesh_pb2.MeshPacket()
    setattr(pkt, "from", NODE)
    pkt.to = 0xFFFFFFFF
    pkt.id = pid
    pkt.hop_limit = 3
    pkt.decoded.portnum = portnum
    pkt.decoded.payload = payload
    env = mqtt_pb2.ServiceEnvelope()
    env.packet.CopyFrom(pkt)
    env.channel_id = "LongFast"
    env.gateway_id = GW
    return env.SerializeToString()


c = mqtt.Client(client_id="test-injector")
c.username_pw_set("meshtastic", os.environ["MQTT_PASS"])
c.connect("127.0.0.1", 1883)
c.loop_start()

u = mesh_pb2.User()
u.id = "!deadbeef"
u.long_name = "SOLAR-1"
u.short_name = "S1"
c.publish(TOPIC, envelope(portnums_pb2.PortNum.NODEINFO_APP,
                          u.SerializeToString(), random.getrandbits(32))).wait_for_publish()
time.sleep(0.5)

p = mesh_pb2.Position()
p.latitude_i = int(32.3437583 * 1e7)
p.longitude_i = int(-88.7464806 * 1e7)
p.altitude = 110
c.publish(TOPIC, envelope(portnums_pb2.PortNum.POSITION_APP,
                          p.SerializeToString(), random.getrandbits(32))).wait_for_publish()
time.sleep(0.5)

c.publish(TOPIC, envelope(portnums_pb2.PortNum.TEXT_MESSAGE_APP,
                          b"radio check from the solar mesh",
                          random.getrandbits(32))).wait_for_publish()
time.sleep(0.5)
print("published nodeinfo + position + text for SOLAR-1 (!deadbeef)")
