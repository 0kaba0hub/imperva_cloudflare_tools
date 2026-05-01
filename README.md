# imperva-cloudflare-tools

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)

Python tool that keeps Imperva and Cloudflare proxy IP ranges up to date on your web servers. It fetches the current IP lists from both providers, updates allowlist files and trusted-proxy configs, reloads Apache or pushes updates to F5 BIG-IP, and sends email/Flock notifications when changes are detected.

---

## Prerequisites

- Python 3.6+
- `requests` library (`pip install requests`)
- Apache with `mod_remoteip` enabled **or** F5 BIG-IP with iControl REST API access
- Write access to the IP list files and permission to reload Apache

---

## Installation

```bash
git clone https://github.com/0kaba0hub/imperva_cloudflare_tools.git /usr/local/src/imperva_cloudflare
cd /usr/local/src/imperva_cloudflare
pip install requests
cp config.ini-example config.ini
```

---

## Configuration

Edit `config.ini`. All sections are described below.

### `[Imperva_API]` / `[Cloudflare_API]`

| Key | Description | Default |
|:----|:------------|:--------|
| `url` | Provider API endpoint | (set) |
| `timeout` | HTTP timeout in seconds | `10` |

### `[Email]`

| Key | Description |
|:----|:------------|
| `enable_smtp` | `true` / `false` |
| `smtp_server` | SMTP host |
| `smtp_port` | SMTP port |
| `smtp_username` / `smtp_password` | Credentials |
| `email_from` / `email_to` | Sender / recipient |
| `email_subject` | Subject line |
| `email_template` | Path to HTML template (default: `email_template.html`) |

### `[Flock]`

| Key | Description |
|:----|:------------|
| `enable_flock` | `true` / `false` |
| `flock_webhook_url` | Incoming webhook URL |

### `[Files]`

| Key | Description | Recommended path |
|:----|:------------|:----------------|
| `ip_file` | IPv4 trusted proxy list | `/etc/apache2/remoteip/ip.txt` |
| `ipv6_file` | IPv6 trusted proxy list | `/etc/apache2/remoteip/ip6.txt` |

### `[Apache]`

| Key | Description | Default |
|:----|:------------|:--------|
| `apache_reload_command` | Shell command to reload Apache | `systemctl reload apache2` |

### `[Logging]`

| Key | Description |
|:----|:------------|
| `log_file` | Path to log file |
| `debug` | `true` during setup, `false` in production |

### `[F5]`

| Key | Description |
|:----|:------------|
| `f5_host` | F5 BIG-IP hostname or IP |
| `f5_username` / `f5_password` | iControl REST credentials |
| `f5_ip_list_name` | IP address list object name on F5 |
| `f5_ssl_verify` | `true`, `false`, or path to CA certificate |
| `f5_timeout` | HTTP timeout in seconds |

---

## Usage

```
update_ips.py [PROVIDER] [OPTION] [CONFIG_PATH]

PROVIDER:
  imperva     Use Imperva as the IP provider
  cloudflare  Use Cloudflare as the IP provider

OPTION:
  apache      Update IP files and reload Apache
  f5          Push updated IP ranges to F5 BIG-IP
  help        Show this help message

CONFIG_PATH: optional — path to a custom .ini file (default: config.ini next to the script)
```

**Examples:**

```bash
# Update Cloudflare IPs for Apache
/usr/local/src/imperva_cloudflare/update_ips.py cloudflare apache

# Update Imperva IPs for F5 BIG-IP
/usr/local/src/imperva_cloudflare/update_ips.py imperva f5

# Use a custom config file
/usr/local/src/imperva_cloudflare/update_ips.py cloudflare apache /etc/myapp/custom.ini
```

---

## Setup guide

### 1. Apache — enable mod_remoteip

Create `/etc/apache2/remoteip/` and add to your Apache config:

```apache
<IfModule remoteip_module>
    RemoteIPHeader X-Forwarded-For
    RemoteIPInternalProxy 10.0.0.0/24
    RemoteIPTrustedProxyList /etc/apache2/remoteip/ip.txt
</IfModule>
```

Configure access logging to use the real client IP:

```apache
LogFormat "%v:%p %a %l %u %t \"%r\" %>s %O \"%{Referer}i\" \"%{User-Agent}i\"" vhost_combined
CustomLog /var/log/apache2/access.log vhost_combined
```

### 2. F5 BIG-IP — enable real IP forwarding

Add the `HTTP-ADD-HEADER-XForwardFor` iRule to the HTTP(S) virtual server, then run the initial sync:

```bash
/usr/local/src/imperva_cloudflare/update_ips.py cloudflare f5
```

### 3. Run a test and check logs

```bash
/usr/local/src/imperva_cloudflare/update_ips.py cloudflare apache
tail -f /path/to/script.log
```

Expected output (debug enabled):

```
2024-12-24 13:10:01,645 - INFO  - Selected provider: Cloudflare
2024-12-24 13:10:01,731 - DEBUG - Received a successful response from API.
2024-12-24 13:10:01,732 - DEBUG - Old IPv4 ranges: [...]
2024-12-24 13:10:01,732 - DEBUG - New IPv4 ranges: [...]
```

### 4. Disable debug logging

Set `debug = false` in the `[Logging]` section of `config.ini`.

### 5. Create a cron job

```bash
# /etc/cron.d/imperva-cloudflare
5-55/5 * * * *  root /usr/local/src/imperva_cloudflare/update_ips.py cloudflare apache
```

---

## License

[GPL-3.0](LICENSE)

