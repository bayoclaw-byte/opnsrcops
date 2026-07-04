#!/usr/bin/env bash
# End-to-end check: watch the TAK stream with the admin cert while injecting
# synthetic mesh traffic via MQTT. Run with sudo (needs admin key passphrase env).
set -e
CERTS=/var/lib/docker/volumes/tak_takserver_data/_data/certs/files
WORK=/tmp/meshtak-verify
mkdir -p $WORK

# admin key is passphrase-protected; make a temp decrypted copy
openssl rsa -in $CERTS/admin.key -passin pass:"$ADMIN_CERT_PASS" -out $WORK/admin.key 2>/dev/null
cp $CERTS/admin.pem $CERTS/root-ca.pem $CERTS/ca.pem $WORK/
cat $WORK/root-ca.pem $WORK/ca.pem > $WORK/chain.pem

# listen to the TAK broadcast stream for 20s
(timeout 20 openssl s_client -connect 127.0.0.1:8089 \
  -cert $WORK/admin.pem -key $WORK/admin.key -CAfile $WORK/chain.pem \
  -quiet 2>/dev/null > $WORK/stream.xml || true) &
LISTENER=$!
sleep 3

# inject
MQTT_PASS="$MQTT_PASS" /opt/meshtak-bridge/venv/bin/python /tmp/test_inject.py

wait $LISTENER
echo "=== TAK stream captured ==="
if grep -q "MESH-deadbeef" $WORK/stream.xml; then
  echo "PASS: SOLAR-1 PLI/chat seen in TAK broadcast stream"
  grep -o '<event[^>]*uid="[^"]*"[^>]*type="[^"]*"' $WORK/stream.xml | sort -u
else
  echo "FAIL: no MESH- events in stream; dump follows"
  head -c 2000 $WORK/stream.xml
fi
echo "=== bridge log ==="
journalctl -u meshtak-bridge -n 8 --no-pager
rm -f $WORK/admin.key
