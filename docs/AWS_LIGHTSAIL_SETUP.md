# AWS Lightsail Setup

This is the cloud replacement for leaving the Windows PC running.

The first deployment should keep the ISAAC1 control UI private on ZeroTier. Do not expose port `8765` to the public internet until the UI has proper login and HTTPS.

## Target

- Provider: AWS Lightsail
- Region: Asia Pacific Sydney, `ap-southeast-2`
- Instance: Linux/Unix, Ubuntu LTS, 1 GB RAM
- Name: `isaac1-control-01`
- ZeroTier network: `08752e18b1384126`
- RUT241 ZeroTier URL: `http://10.23.48.89`
- UI port: `8765`

AWS currently lists the 1 GB Linux bundle at US$7/month with IPv4, or US$5/month for IPv6-only. Use the IPv4 bundle for this project because it is easier to administer and recover.

## 1. Create The Lightsail Instance

1. Open <https://lightsail.aws.amazon.com/>.
2. Create an instance.
3. Select Linux/Unix.
4. Select OS Only, Ubuntu LTS.
5. Select Region `ap-southeast-2` Sydney.
6. Select the 1 GB RAM bundle.
7. Name the instance `isaac1-control-01`.
8. Open the launch script/user-data field and paste the contents of `deploy/lightsail/cloud-init.sh`.
9. Create the instance.

## 2. Attach A Static IP

1. In Lightsail, open Networking.
2. Create a static IP in the same region.
3. Attach it to `isaac1-control-01`.

The static IP is for administration. The ISAAC1 UI should still be accessed over ZeroTier at this stage.

## 3. Firewall

Keep the Lightsail public firewall minimal:

- Allow SSH, TCP `22`, from your administration IP if possible.
- Do not open TCP `8765` publicly.
- Do not open HTTP `80` or HTTPS `443` until public HTTPS/login is implemented.

## 4. Authorize ZeroTier

After the instance boots:

1. Open the instance's browser SSH console in Lightsail.
2. Check ZeroTier:

```bash
sudo zerotier-cli info
sudo zerotier-cli listnetworks
```

3. In ZeroTier Central, authorize the new `isaac1-lightsail` member.
4. Wait until `listnetworks` shows an assigned ZeroTier IP.

## 5. Deploy The ISAAC1 App

From PowerShell on the ISAAC1 workstation:

```powershell
cd $env:USERPROFILE\OneDrive\Projects\ISAAC1
$env:ISAAC1_CONTROL_TOKEN = "<router-token>"
.\deploy\lightsail\deploy-local.ps1 -Host <lightsail-static-ip> -SshKey <path-to-lightsail-private-key>
```

If you use the default Lightsail SSH key, download it from the Lightsail account SSH keys page and pass its path as `-SshKey`.

The deploy script copies only project files from this repo, writes the real token to `/etc/isaac1/isaac1.env` on the server, installs the package into `/opt/isaac1/venv`, and starts `isaac1-control.service`.

## 6. Test From The Server

In the Lightsail SSH console:

```bash
sudo systemctl status isaac1-control --no-pager
curl http://127.0.0.1:8765/api/state
curl http://10.23.48.89/cgi-bin/custom/isaac1-relay
```

The relay endpoint may return an authorization error without parameters. That still proves the RUT241 is reachable over ZeroTier.

## 7. Open From iPhone

1. Keep ZeroTier enabled on the iPhone.
2. Open Safari to:

```text
http://<lightsail-zerotier-ip>:8765
```

3. Use Share, Add to Home Screen.

The iPhone should use the Lightsail ZeroTier IP, not the old Windows PC ZeroTier IP.

## References

- AWS Lightsail pricing: <https://aws.amazon.com/lightsail/pricing/>
- Lightsail instance bundles: <https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html>
- Lightsail SSH keys: <https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-set-up-ssh.html>
- Lightsail static IPs: <https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-create-static-ip.html>
- ZeroTier quickstart: <https://docs.zerotier.com/quickstart/>
