#!/usr/bin/env python3

import sys
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import subprocess
import configparser
import logging
import urllib3
from requests.auth import HTTPBasicAuth

# ── globals — populated by load_config() before any function is called ────────
imperva_url = imperva_timeout = None
cloudflare_url = cloudflare_timeout = None
ENABLE_SMTP = SMTP_SERVER = SMTP_PORT = SMTP_USERNAME = SMTP_PASSWORD = None
SMTP_TIMEOUT = EMAIL_FROM = EMAIL_TO = EMAIL_SUBJECT = EMAIL_TEMPLATE_FILE = None
ENABLE_FLOCK = FLOCK_WEBHOOK_URL = FLOCK_TIMEOUT = None
IP_FILE = IPV6_FILE = APACHE_RELOAD_COMMAND = None
F5_HOST = F5_USERNAME = F5_PASSWORD = F5_IP_LIST_NAME = F5_SSL_VERIFY = F5_TIMEOUT = None


def load_config(config_path):
    global imperva_url, imperva_timeout, cloudflare_url, cloudflare_timeout
    global ENABLE_SMTP, SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
    global SMTP_TIMEOUT, EMAIL_FROM, EMAIL_TO, EMAIL_SUBJECT, EMAIL_TEMPLATE_FILE
    global ENABLE_FLOCK, FLOCK_WEBHOOK_URL, FLOCK_TIMEOUT
    global IP_FILE, IPV6_FILE, APACHE_RELOAD_COMMAND
    global F5_HOST, F5_USERNAME, F5_PASSWORD, F5_IP_LIST_NAME, F5_SSL_VERIFY, F5_TIMEOUT

    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.isfile(config_path):
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(config_path)

    imperva_url     = config['Imperva_API']['url']
    imperva_timeout = config['Imperva_API'].getint('timeout')

    cloudflare_url     = config['Cloudflare_API']['url']
    cloudflare_timeout = config['Cloudflare_API'].getint('timeout')

    ENABLE_SMTP         = config['Email'].getboolean('enable_smtp')
    SMTP_SERVER         = config['Email']['smtp_server']
    SMTP_PORT           = config['Email'].getint('smtp_port')
    SMTP_USERNAME       = config['Email']['smtp_username']
    SMTP_PASSWORD       = config['Email']['smtp_password']
    SMTP_TIMEOUT        = config['Email'].getint('smtp_timeout')
    EMAIL_FROM          = config['Email']['email_from']
    EMAIL_TO            = config['Email']['email_to']
    EMAIL_SUBJECT       = config['Email']['email_subject']
    EMAIL_TEMPLATE_FILE = os.path.join(script_dir, config['Email']['email_template'])

    ENABLE_FLOCK      = config['Flock'].getboolean('enable_flock')
    FLOCK_WEBHOOK_URL = config['Flock']['flock_webhook_url']
    FLOCK_TIMEOUT     = config['Flock'].getint('flock_timeout')

    IP_FILE               = config['Files']['ip_file']
    IPV6_FILE             = config['Files']['ipv6_file']
    APACHE_RELOAD_COMMAND = config['Apache']['apache_reload_command'].split()

    F5_HOST         = config['F5']['f5_host']
    F5_USERNAME     = config['F5']['f5_username']
    F5_PASSWORD     = config['F5']['f5_password']
    F5_IP_LIST_NAME = config['F5']['f5_ip_list_name']
    F5_TIMEOUT      = config['F5'].getint('f5_timeout')

    # ssl_verify: false / true / path to CA bundle
    ssl_raw = config['F5']['f5_ssl_verify']
    if ssl_raw.lower() == 'false':
        F5_SSL_VERIFY = False
    elif ssl_raw.lower() == 'true':
        F5_SSL_VERIFY = True
    elif os.path.isfile(ssl_raw):
        F5_SSL_VERIFY = ssl_raw  # requests accepts a CA bundle path as verify=
    else:
        print(f"Invalid f5_ssl_verify value: '{ssl_raw}'. Use true, false, or a path to a CA cert.", file=sys.stderr)
        sys.exit(1)

    if F5_SSL_VERIFY is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    log_file = config['Logging']['log_file']
    debug    = config['Logging'].getboolean('debug')
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


def print_help(file=sys.stdout):
    print("""
    Usage: update_ips.py [PROVIDER] [OPTION] [CONFIG_PATH]

    PROVIDER:
      imperva    - Use Imperva as the IP provider.
      cloudflare - Use Cloudflare as the IP provider.

    Options:
      apache    - Update IP ranges in Apache and reload the service.
      f5        - Update IP ranges on F5 BIG-IP device.
      help      - Display this help message.

    CONFIG_PATH: Optional path to a custom config.ini file.
    """, file=file)


def notify(message):
    logging.error(message)
    if ENABLE_SMTP:
        send_email(message)
    if ENABLE_FLOCK:
        send_flock_alert(message)


def send_email(error_message):
    try:
        with open(EMAIL_TEMPLATE_FILE, 'r') as file:
            template = file.read()
    except OSError as e:
        logging.error(f"Failed to read email template {EMAIL_TEMPLATE_FILE}: {e}")
        return

    body = template.replace('{{ error_message }}', error_message)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = EMAIL_SUBJECT
    msg['From']    = EMAIL_FROM
    msg['To']      = EMAIL_TO
    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        logging.info("Email sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")


def send_flock_alert(error_message):
    payload = {
        "flockml": f"<flockml><b>{EMAIL_SUBJECT}</b></br>{error_message}</flockml>"
    }
    try:
        response = requests.post(FLOCK_WEBHOOK_URL, json=payload, timeout=FLOCK_TIMEOUT)
        response.raise_for_status()
        logging.info("Flock alert sent successfully.")
    except Exception as e:
        logging.error(f"Error sending Flock alert: {e}")


def load_data_from_file(filename):
    try:
        with open(filename, 'r') as file:
            return file.read().splitlines()
    except FileNotFoundError:
        logging.warning(f"File {filename} not found. Treating as empty.")
        return []


def save_data_to_file(filename, data):
    try:
        with open(filename, 'w') as file:
            file.write("\n".join(data) + "\n")
        logging.info(f"Data saved to {filename}.")
    except OSError as e:
        notify(f"Failed to write {filename}: {e}")
        sys.exit(1)


def reload_apache2():
    try:
        subprocess.run(APACHE_RELOAD_COMMAND, check=True)
        logging.info("Apache2 reloaded successfully.")
    except subprocess.CalledProcessError as e:
        notify(f"Failed to reload Apache2: {e}")


def fetch_f5_ip_list():
    logging.info("Fetching current IP list from F5 BIG-IP.")
    url     = f"https://{F5_HOST}/mgmt/tm/ltm/data-group/internal/{F5_IP_LIST_NAME}"
    headers = {'Content-Type': 'application/json'}
    auth    = HTTPBasicAuth(F5_USERNAME, F5_PASSWORD)

    try:
        response = requests.get(url, headers=headers, auth=auth, verify=F5_SSL_VERIFY, timeout=F5_TIMEOUT)
        response.raise_for_status()
        current_ips = [record['name'] for record in response.json().get('records', [])]
        logging.debug(f"Current F5 IP list: {current_ips}")
        return current_ips
    except Exception as e:
        notify(f"Error fetching F5 IP list: {e}")
        sys.exit(1)


def update_f5_ip_list(ip_ranges):
    current_ip_ranges = fetch_f5_ip_list()

    if set(ip_ranges) == set(current_ip_ranges):
        logging.info("No changes detected in the F5 IP list. No update needed.")
        return

    logging.info("Updating F5 BIG-IP IP list.")
    url     = f"https://{F5_HOST}/mgmt/tm/ltm/data-group/internal/{F5_IP_LIST_NAME}"
    headers = {'Content-Type': 'application/json'}
    auth    = HTTPBasicAuth(F5_USERNAME, F5_PASSWORD)
    data    = {"records": [{"name": ip} for ip in ip_ranges]}

    try:
        response = requests.put(url, json=data, headers=headers, auth=auth, verify=F5_SSL_VERIFY, timeout=F5_TIMEOUT)
        response.raise_for_status()
        logging.info("F5 IP list updated successfully.")
    except Exception as e:
        notify(f"Error updating F5 IP list: {e}")
        sys.exit(1)


def _fetch(url, timeout, headers=None):
    try:
        response = requests.get(url=url, timeout=timeout, headers=headers or {})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        notify(f"Request to {url} timed out after {timeout} seconds.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        notify(f"Error during API request: {e}")
        sys.exit(1)


def imperva_process_ip_ranges(url, timeout, update_f5):
    logging.debug("Start imperva_process_ip_ranges()")
    data = _fetch(url, timeout)

    if data.get('res_message') != 'OK':
        notify(f"API returned a non-OK message: {data.get('res_message')}")
        return

    logging.debug("API response indicates success.")

    if not update_f5:
        old_ip_ranges   = load_data_from_file(IP_FILE)
        old_ipv6_ranges = load_data_from_file(IPV6_FILE)
        new_ip_ranges   = data.get('ipRanges', [])
        new_ipv6_ranges = data.get('ipv6Ranges', [])

        logging.debug(f"Old IP ranges: {old_ip_ranges}")
        logging.debug(f"New IP ranges: {new_ip_ranges}")
        logging.debug(f"Old IPv6 ranges: {old_ipv6_ranges}")
        logging.debug(f"New IPv6 ranges: {new_ipv6_ranges}")

        if set(new_ip_ranges) != set(old_ip_ranges) or set(new_ipv6_ranges) != set(old_ipv6_ranges):
            logging.info("Changes detected. Updating files and reloading Apache2.")
            save_data_to_file(IP_FILE, sorted(new_ip_ranges))
            save_data_to_file(IPV6_FILE, sorted(new_ipv6_ranges))
            reload_apache2()
        else:
            logging.info("No changes detected. No action needed.")
    else:
        update_f5_ip_list(data.get('ipRanges', []))


def cloudflare_process_ip_ranges(url, timeout, update_f5):
    logging.debug("Start cloudflare_process_ip_ranges()")
    data = _fetch(url, timeout, headers={'Content-Type': 'application/json'})

    if not data.get('success', False):
        notify(f"API returned a non-success response: {data}")
        return

    logging.debug("API response indicates success.")

    ipv4_ranges = data['result'].get('ipv4_cidrs', [])
    ipv6_ranges = data['result'].get('ipv6_cidrs', [])

    if not update_f5:
        old_ipv4_ranges = load_data_from_file(IP_FILE)
        old_ipv6_ranges = load_data_from_file(IPV6_FILE)

        logging.debug(f"Old IPv4 ranges: {old_ipv4_ranges}")
        logging.debug(f"New IPv4 ranges: {ipv4_ranges}")
        logging.debug(f"Old IPv6 ranges: {old_ipv6_ranges}")
        logging.debug(f"New IPv6 ranges: {ipv6_ranges}")

        changed = False
        if set(ipv4_ranges) != set(old_ipv4_ranges):
            logging.info("Changes detected in IPv4 ranges. Updating file.")
            save_data_to_file(IP_FILE, sorted(ipv4_ranges))
            changed = True
        if set(ipv6_ranges) != set(old_ipv6_ranges):
            logging.info("Changes detected in IPv6 ranges. Updating file.")
            save_data_to_file(IPV6_FILE, sorted(ipv6_ranges))
            changed = True
        if changed:
            reload_apache2()
        else:
            logging.info("No changes detected. No action needed.")
    else:
        combined_ranges = ipv4_ranges + ipv6_ranges
        logging.info("Updating F5 with combined IPv4 and IPv6 ranges.")
        update_f5_ip_list(combined_ranges)


def main():
    script_dir          = os.path.dirname(os.path.abspath(__file__))
    default_config_path = os.path.join(script_dir, 'config.ini')

    if len(sys.argv) < 3 or sys.argv[1].lower() in ('help', '--help', '-h'):
        print_help()
        sys.exit(0)

    provider = sys.argv[1].lower()
    option   = sys.argv[2].lower()

    if option == 'help':
        print_help()
        sys.exit(0)

    config_path = default_config_path
    if len(sys.argv) > 3 and sys.argv[3].endswith('.ini'):
        config_path = sys.argv[3]

    if provider not in ('imperva', 'cloudflare'):
        print(f"Error: unknown provider '{provider}'.", file=sys.stderr)
        print_help(sys.stderr)
        sys.exit(1)

    if option not in ('apache', 'f5'):
        print(f"Error: unknown option '{option}'.", file=sys.stderr)
        print_help(sys.stderr)
        sys.exit(1)

    load_config(config_path)

    update_f5 = option == 'f5'

    if provider == 'imperva':
        logging.info("Selected provider: Imperva")
        imperva_process_ip_ranges(imperva_url, imperva_timeout, update_f5)
    else:
        logging.info("Selected provider: Cloudflare")
        cloudflare_process_ip_ranges(cloudflare_url, cloudflare_timeout, update_f5)


if __name__ == "__main__":
    main()
