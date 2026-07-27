#!/bin/bash
set -e

rm -rf package/emortal/luci-app-athena-led
git clone --depth=1 https://github.com/NONGFAH/luci-app-athena-led package/luci-app-athena-led
chmod +x package/luci-app-athena-led/root/etc/init.d/athena_led package/luci-app-athena-led/root/usr/sbin/athena-led

# --- Fix: DNSMASQ HIJACK rule redirects to the wrong port when dnsmasq's
# DNS listener is disabled (port=0) in favor of a replacement DNS server
# (e.g. AdGuard Home, Pi-hole). The hijack rule must redirect to the port
# the actual DNS server is listening on, not dnsmasq's own (now-disabled) port.
DNSMASQ_INIT=$(find . -path "*/dnsmasq/files/dnsmasq.init" -o -path "*/dnsmasq*/dnsmasq.init" 2>/dev/null | head -n1)
 
if [ -n "$DNSMASQ_INIT" ] && grep -q 'redirect to :\$dns_port' "$DNSMASQ_INIT"; then
    echo ">>> Patching DNSMASQ HIJACK rule in $DNSMASQ_INIT"
    sed -i \
        -e 's/config_get dns_port "\$cfg" port 53/config_get dns_port "$cfg" port 53\n\tconfig_get dns_redirect_port "$cfg" dns_redirect_port "$dns_port"/' \
        -e 's/redirect to :\$dns_port/redirect to :$dns_redirect_port/' \
        "$DNSMASQ_INIT"
else
    echo ">>> WARNING: dnsmasq.init not found or pattern has changed, manual check required" >&2
fi
