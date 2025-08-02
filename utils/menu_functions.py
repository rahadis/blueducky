import os, bluetooth, re, subprocess, time, curses
import logging as log

##########################
# UI by Agus Hasib #
##########################

def get_target_address():
    blue = "\033[94m"
    reset = "\033[0m"
    print(f"\n Masukkan alamat target{blue}? {reset}Jika kosong, tekan Enter untuk mencari perangkat Bluetooth{blue}!{reset}")
    target_address = input(f"\n {blue}> ")

    if target_address == "":
        devices = scan_for_devices()
        if devices:
            # Perangkat baru yang ditemukan dari proses scan
            if len(devices) == 1 and isinstance(devices[0], tuple) and len(devices[0]) == 2:
                # Sistem hanya mendeteksi satu perangkat yang sudah dikenal sebelumnya
                # Tanya dulu, apakah ingin memindai perangkat atau memilih perangkay yang sudah dikenal
                confirm = input(f"\n Apakah Anda ingin mendaftarkan perangkat ini?{blue}:\n{reset}{devices[0][1]} {devices[0][0]}{blue}? {blue}({reset}y{blue}/{reset}n{blue}) {blue}").strip().lower()
                if confirm == 'y' or confirm == 'yes':
                    return devices[0][0]
                elif confirm != 'y' or 'yes':
                    return
            else:
                # Tampilkan daftar perangkat hasil pemindaian untuk dipilih oleh pengguna.
                for idx, (addr, name) in enumerate(devices):
                    print(f"{reset}[{blue}{idx + 1}{reset}] {blue}Nama Perangkat{reset}: {blue}{name}, {blue}Address{reset}: {blue}{addr}")
                selection = int(input(f"\n{reset}Silakan pilih perangkat dengan nomor yang tersedia{blue}: {blue}")) - 1
                if 0 <= selection < len(devices):
                    target_address = devices[selection][0]
                else:
                    print("\nPilihan tidak valid. Keluar dari program.")
                    return
        else:
            return
    elif not is_valid_mac_address(target_address):
        print("\nAlamat MAC yang dimasukkan tidak valid. Mohon masukkan alamat MAC yang sesua.")
        return

    return target_address

def restart_bluetooth_daemon():
    run(["sudo", "service", "bluetooth", "restart"])
    time.sleep(0.5)

def run(command):
    assert(isinstance(command, list))
    log.info("executing '%s'" % " ".join(command))
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result

# def print_fancy_ascii_art():

#     ascii_art = """
# 	⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⠤⠄⠒⠒⠒⠒⠒⠒⠂⠠⢄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⠴⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠓⢄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⠞⠁⠀⠀⠀⠀⣀⡤⠴⠒⠒⠒⠒⠦⠤⣀⠀⠀⠀⠙⢆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⠀⢰⠋⠀⠀⠀⣠⠖⠋⢀⣄⣀⡀⠀⠀⠀⠀⠀⠀⠉⠲⣄⠀⠈⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⢠⠇⠀⠀⢀⡼⠁⠀⣴⣿⡛⠻⣿⣧⡀⠀⠀⠀⠀⠀⠀⠈⠳⡄⡿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⣼⣀⣀⣀⡜⠀⠀⠀⣿⣿⣿⣿⣿⣿⡧⠀⠀⠀⠀⠀⠀⠀⠀⠙⣿⣷⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⣀⡤⠟⠁⠀⠈⠙⡶⣄⡀⠈⠻⢿⣿⡿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠇⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
# 	⣤⣤⠖⠖⠛⠉⠈⣀⣀⠀⠴⠊⠀⠀⣹⣷⣶⡏⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀ ⠀⣀⡀⠀⠀
# 	⠘⠿⣿⣷⣶⣶⣶⣶⣤⣶⣶⣶⣿⣿⣿⡿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡜⠀⠀⠀⠀⠀⠀⢀⣀⣠⣤⠤⠖⠒⠋⠉⠁⠙⣆⠀
# 	⠀⠀⠀⠀⠉⠉⠉⠉⠙⠿⣍⣩⠟⠋⠙⢦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣾⣖⣶⣶⢾⠯⠽⠛⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⡄
# 	⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⠚⠁⠀⠀⠀⠀⠈⠓⠤⠀⠀⠀⠀⠀⠀⠐⠒⠚⠉⠉⠁⠀⠀⠀⠀⠀⠀⢀⣀⣀⠀⣀⢀⠀⠀⠀⠀⠀⠀⠀⣇
# 	⠀⠀⠀⠀⠀⠀⠀⡴⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⠤⠤⠖⠒⠚⠉⠉⠁⠀⠀⠀⢸⢸⣦⠀⠀⠀⠀⠀⠀⢸
# 	⠀⠀⠀⠀⠀⢠⠎⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡠⠤⠴⠒⠒⠉⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡏⣸⡏⠇⠀⠀⠀⠀⠀⢸
# 	⠀⠀⠀⠀⢠⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢻⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠞⢠⡿⠀⠀⠀⠀⠀⠀⠀⢸
# 	⠀⠀⠀⠀⣾⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠊⣠⡟⠀⠀⠀⠀⠀⠀⠀⠀⡏
# 	⠀⠀⠀⠀⡏⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠢⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠖⠉⢀⣴⠏⠠⠀⠀⠀⠀⠀⠀⠀⣸⠁
# 	⠀⠀⠀⠀⢹⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠒⠒⠢⠤⠄⠀⠀⠀⠀⠀⠈⠁⠀⣠⣶⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⢠⠃⠀
# 	⠀⠀⠀⠀⠀⢣⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⣴⠿⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⠃⠀⠀
# 	⠀⠀⠀⠀⠀⠈⢧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⡶⠿⠛⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡴⠃⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⠳⣄⢀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠤⠖⣪⡵⠋⠀⠀⠀⠀⠀
# 	⠀⠀⠀⠀⠀⠀⠀⠀⠈⠑⠫⠭⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣭⣭⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⡴⠶⠛⠉⠀⠀⠀⠀⠀⠀⠀
# """

#     print("\033[94m" + ascii_art + "\033[0m")  # Blue 

# def clear_screen():
#     os.system('clear')

# Fungsi untuk menyimpan perangkat yang ditemukan
def save_devices_to_file(devices, filename='known_devices.txt'):
    with open(filename, 'w') as file:
        for addr, name in devices:
            file.write(f"{addr},{name}\n")

# Fungsi untuk memindai (men-scan) perangkat yang tersedia.
def scan_for_devices():
    known_devices = load_known_devices()
    nearby_devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True, lookup_class=True)
    device_list = [(addr, name) for addr, name, _ in nearby_devices]

    new_devices = [device for device in device_list if device not in known_devices]
    if new_devices:
        known_devices += new_devices
        save_devices_to_file(known_devices)

    return device_list

# def getterm():
#     size = os.get_terminal_size()
#     return size.columns


# def print_menu():
#     blue = '\033[94m'
#     reset = "\033[0m"
#     title = "BlueDucky - Bluetooth Device Attacker by Agus Hasib"
#     vertext = "2025"
#     motd1 = f"Remember, For educational purposes only"
#     motd2 = f"For the purpose of Tugas Akhir"
#     terminal_width = getterm()
#     separator = "*" * terminal_width

#     print(blue + separator)  # Warna biru untuk pemisah.
#     print(reset + title.center(len(separator)))  # Judul dengan warna biru
#     print(blue + vertext.center(len(separator)))  # Versi yang terpusat dengan warna biru
#     print(blue + separator + reset)  # Warna biru digunakan untuk pembatas
#     print(motd1.center(len(separator)))# Metode yang sama digunakan untuk meratakan (centering) 
#     print(motd2.center(len(separator)))# uMetode yang sama digunakan untuk meratakan (centering) 
#     print(blue + separator + reset)  # Warna biru digunakan untuk pembatas

# def main_menu():
#     clear_screen()
#     print_fancy_ascii_art()
#     print_menu()


def is_valid_mac_address(mac_address):
    # Regular expression digunakan untuk mencocokkan alamat MAC address dalam format XX:XX:XX:XX:XX:XX
    mac_address_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    return mac_address_pattern.match(mac_address) is not None

# Fungsi untuk membaca DuckyScript dari file
def read_duckyscript(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return [line.strip() for line in file.readlines()]
    else:
        log.warning(f"File {filename} not found. Skipping DuckyScript.")
        return None

# Fungsi untuk memuat perangkat yang sudah dikenal
def load_known_devices(filename='known_devices.txt'):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return [tuple(line.strip().split(',')) for line in file]
    else:
        return []


# title = "BlueDucky - Bluetooth Device Attacker by Agus Hasib"
# vertext = "2025"
# terminal_width = getterm()
# separator = "=" * terminal_width
# blue = "\033[0m"
# reset = "\033[0m"

# print(blue + separator)  # Warna biru untuk pemisah.
# print(reset + title.center(len(separator)))  # Untuk memberikan warna putih pada judul 
# print(blue + vertext.center(len(separator)))  # menampilkan nomor versi
# print(blue + separator + reset)  # Warna biru untuk pemisah.
# print(f"{reset}For educational purposes only{blue}.." + reset)
# print(f"{blue}For the purpose of {reset}Tugas Akhir {blue}.." + reset)
# print(blue + separator + reset)  # Warna biru untuk pemisah.
