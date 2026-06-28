# RUT241 First Step

## Objective

Configure the Teltonika RUT241 over Ethernet so ISAAC1 can later control a Tonmind SIP-T21 over the internet and continue receiving software updates remotely.

## Hardware role

- RUT241: LTE internet gateway and remote management point.
- Tonmind SIP-T21: LAN-connected paging adapter with HTTP/HTTPS support and 2 relay outputs.
- ISAAC1 user interface: future internet-facing control surface for relay on/off commands.

Vendor references:

- RUT241: https://wiki.teltonika-networks.com/view/RUT241
- SIP-T21: https://www.tonmind.com/tonmind-ip-paging-adapter-sip-t21_p45.html

## First setup target

The first field milestone is not relay control. It is remote programmability:

1. Connect a laptop to the RUT241 Ethernet LAN.
2. Reach the router at `192.168.1.1`.
3. Complete the RutOS first-login password change.
4. Confirm the SIM is inserted, PIN state is OK, LTE operator is visible, signal is usable, and internet routing works.
5. Enable a secure remote access path for future ISAAC1 deployment and upgrades.

## Recommended remote access model

Use Teltonika RMS or a VPN tunnel for remote access. Do not expose raw SSH or the WebUI directly to the public internet unless there is a deliberate firewall policy, strong credentials, and source-IP restriction.

RMS is the simplest first option because many mobile SIM services use CGNAT and do not provide an inbound public IP address.

## Local Ethernet checklist

1. Insert the SIM and antennas, then power the RUT241.
2. Connect the laptop to the RUT241 LAN Ethernet port.
3. Open `http://192.168.1.1`.
4. Log in as the default admin user, using the password printed on the device label or the documented default if applicable.
5. Change the admin password during first login.
6. Confirm mobile data is enabled under the RutOS mobile settings.
7. Confirm the RUT241 can browse the internet or ping a known public IP.
8. Enable SSH only for the management path ISAAC1 will use.
9. Register or enable RMS/VPN remote access for future software changes.
10. Reserve a LAN IP for the Tonmind SIP-T21 before moving the Ethernet cable from the laptop to the SIP-T21.

## Diagnostic command

After SSH key or credential access is configured, run:

```powershell
python -m isaac1 rut241-check --host 192.168.1.1 --user root
```

The command runs these RutOS checks:

- `ubus call system board`
- `gsmctl -z`
- `gsmctl -u`
- `gsmctl -o`
- `gsmctl -q`
- `ip route show default`
- `ping -c 3 1.1.1.1`

Expected result:

- SIM state reports inserted.
- PIN state reports OK.
- Operator is not `N/A`.
- Signal output is present and should be reviewed before installation.
- A default route exists.
- Ping to `1.1.1.1` succeeds.

## Tonmind LAN handoff

Once remote access to the RUT241 is proven, the RUT241 Ethernet LAN can be used for the SIP-T21. The SIP-T21 should receive a known static or reserved IP address so ISAAC1 can send relay-control HTTP requests through the RUT241 management path.

Relay HTTP command details still need to be confirmed from Tonmind's SIP-T21 API/manual before implementation.
