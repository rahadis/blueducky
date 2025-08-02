import os
import bluetooth
import logging as log
import re
import subprocess

def is_valid_mac_address(mac_address):
    pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    return pattern.match(mac_address) is not None

def read_duckyscript(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return [line.strip() for line in file.readlines()]
    else:
        log.warning(f"File {filename} not found. Skipping DuckyScript.")
        return None

def load_known_devices(filename='known_devices.txt'):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return [tuple(line.strip().split(',')) for line in file]
    else:
        return []

def save_devices_to_file(devices, filename='known_devices.txt'):
    with open(filename, 'w') as file:
        for addr, name in devices:
            file.write(f"{addr},{name}\n")

def scan_for_devices():
    known_devices = load_known_devices()
    nearby_devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True, lookup_class=True)
    device_list = [(addr, name) for addr, name, _ in nearby_devices]

    new_devices = [device for device in device_list if device not in known_devices]
    if new_devices:
        known_devices += new_devices
        save_devices_to_file(known_devices)

    return device_list

def run(command):
    assert isinstance(command, list)
    log.info("executing '%s'" % " ".join(command))
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result

def restart_bluetooth_daemon():
    run(["sudo", "service", "bluetooth", "restart"])
    import time
    time.sleep(0.5)
