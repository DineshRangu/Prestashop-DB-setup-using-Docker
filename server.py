import os
import socket
import subprocess
import time
import requests
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder='static')

BASE_PORT = int(os.getenv('BASE_PORT', 8081))
TENANTS_DIR = os.getenv('TENANTS_DIR', 'tenants')
COMPOSE_FILE = os.getenv('COMPOSE_FILE', 'compose.yaml')

os.makedirs(TENANTS_DIR, exist_ok=True)


def get_next_port():
    port = BASE_PORT
    while True:
        with socket.socket() as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
        port += 1


def get_next_tenant_id():
    existing = [
        d for d in os.listdir(TENANTS_DIR)
        if os.path.isdir(os.path.join(TENANTS_DIR, d)) and d.startswith('tenant')
    ]
    if not existing:
        return 1
    ids = [int(d.replace('tenant', '')) for d in existing if d.replace('tenant', '').isdigit()]
    return max(ids) + 1 if ids else 1


def write_env_file(path, tenant_name, port, admin_email, admin_password):
    with open(path, 'w') as f:
        f.write(f"TENANT_NAME={tenant_name}\n")
        f.write(f"TENANT_PORT={port}\n")
        f.write(f"ADMIN_MAIL={admin_email}\n")
        f.write(f"ADMIN_PASSWD={admin_password}\n")


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/create-store', methods=['POST'])
def create_store():
    body = request.get_json(force=True)
    admin_email = body.get("email")
    admin_password = body.get("password")

    tenant_id = get_next_tenant_id()
    tenant_name = f"tenant{tenant_id}"
    port = get_next_port()
    tenant_dir = os.path.join(TENANTS_DIR, tenant_name)
    env_file = os.path.join(tenant_dir, f"{tenant_name}.env")

    os.makedirs(tenant_dir, exist_ok=True)
    write_env_file(env_file, tenant_name, port, admin_email, admin_password)

    try:
        subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run([
            'docker', 'compose',
            '--file', COMPOSE_FILE,
            '--env-file', env_file,
            '--project-name', tenant_name,
            'up', '-d'
        ], check=True)
    except subprocess.CalledProcessError as e:
        return jsonify({
            'error': 'Docker is not running or not installed. Please start Docker Desktop and try again.',
            'details': str(e)
        }), 500

    container_name = f"{tenant_name}_shop"
    command = f"docker exec {container_name} sh -c \"basename $(find /var/www/html -maxdepth 1 -type d -name 'admin*' | head -n 1)\""

    try:
        admin_folder = subprocess.check_output(command, shell=True).decode().strip()
    except subprocess.CalledProcessError as e:
        print(f"Error fetching admin folder: {e}")
        admin_folder = "admin"

    shop_url = f"http://localhost:{port}"
    for _ in range(30):
        try:
            r = requests.get(shop_url, timeout=5)
            if r.status_code == 200 and 'presta' in r.text.lower():
                break
        except requests.RequestException:
            pass
        time.sleep(2)

    admin_url = f"{shop_url}/{admin_folder}"
    return jsonify({
        'url': shop_url,
        'admin_url': admin_url,
        'admin_email': admin_email,
        'admin_password': admin_password
    })


if __name__ == '__main__':
    app.run('0.0.0.0', 5000, debug=True)
