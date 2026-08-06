# -*- coding: utf-8 -*-
"""
despertar_legion.py — Despierta Legion vía Wake-on-LAN y verifica el estado
===========================================================================

Envía el "magic packet" WoL (UDP puerto 9) a la subred de Legion para
despertarla desde suspensión/hibernación, y luego comprueba que SSH
responde. No hace falta login: el servidor OpenSSH corre como servicio,
así que la conexión SSH funciona aunque esté en la pantalla de bloqueo.

USO:
    python F:\\scripts\\despertar_legion.py                 # despierta y verifica
    python F:\\scripts\\despertar_legion.py --esperar 120   # espera más tiempo
    python F:\\scripts\\despertar_legion.py --sin-verificar # solo manda el paquete
    python F:\\scripts\\despertar_legion.py --tarea vision_run
        # además, tras despertar, lanza la tarea programada (p. ej. el batch
        # de clasificación vision_run en esta máquina)

Requisitos en Legion (ya configurados):
  - WoL activado:  powercfg /deviceenablewake "Realtek Gaming 2.5GbE Family Controller"
  - Watchdog:      keep_awake.ps1 (evita la suspensión mientras trabaja)
  - sshd:          servicio OpenSSH en arranque automático
"""
import socket
import struct
import subprocess
import sys
import time

HOST = 'legion'
IP_FIJA = '192.168.1.136'       # IP Ethernet de Legion (DHCP reservado)
MAC_LEGION = 'A8-2B-DD-C1-82-8F'   # Realtek 2.5GbE (Ethernet)
PUERTO_WOL = 9
CLAVE = r'C:\Users\David\Documents\id_ed25519'


def ip_legion():
    try:
        return socket.gethostbyname(HOST)
    except socket.gaierror:
        return IP_FIJA


def buscar_por_mac():
    """Barre la subred y devuelve la IP cuyo MAC coincide con Legion.
    Útil si el DHCP le cambió la IP al despertar."""
    import ipaddress
    subred = '.'.join(IP_FIJA.split('.')[:3]) + '.0/24'
    for ip in ipaddress.ip_network(subred, strict=False).hosts():
        ip_s = str(ip)
        if not _ping(ip_s):
            continue
    # tras el barrido, consultar la tabla ARP
    try:
        out = subprocess.run(['arp', '-a'], capture_output=True, text=True,
                             timeout=30)
        for linea in out.stdout.splitlines():
            if MAC_LEGION.lower() in linea.lower():
                return linea.split()[0]
    except Exception:
        pass
    return None


def _ping(ip):
    r = subprocess.run(['ping', '-n', '1', '-w', '300', ip],
                       capture_output=True, text=True, timeout=10)
    return r.returncode == 0


def magic_packet(mac):
    mac_hex = mac.replace(':', '').replace('-', '')
    if len(mac_hex) != 12:
        raise ValueError(f'MAC inválida: {mac}')
    return b'\xff' * 6 + bytes.fromhex(mac_hex) * 16


def enviar_wol(destinos):
    paquete = magic_packet(MAC_LEGION)
    ok = 0
    for d in destinos:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(paquete, (d, PUERTO_WOL))
            s.close()
            print(f'  magic packet -> {d}:{PUERTO_WOL}')
            ok += 1
        except OSError as e:
            print(f'  ERROR enviando a {d}: {e}')
    return ok > 0


def ssh_ok():
    try:
        r = subprocess.run(
            ['ssh', '-i', CLAVE, '-o', 'BatchMode=yes',
             '-o', 'ConnectTimeout=10', f'{HOST}',
             'echo OK'],
            capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and 'OK' in r.stdout
    except Exception:
        return False


def main():
    esperar = 90
    solo_paquete = False
    tarea = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--esperar':
            esperar = int(args[i + 1])
        elif a == '--sin-verificar':
            solo_paquete = True
        elif a == '--tarea':
            tarea = args[i + 1]

    ip = ip_legion()
    print(f'Legion: {HOST} -> {ip}')
    if not ip:
        print('No se pudo resolver el host. ¿Está la red local activa?')
        sys.exit(1)

    # Brodcast de la subred + broadcast global
    subred = '.'.join(ip.split('.')[:3]) + '.255'
    if not enviar_wol([subred, '255.255.255.255']):
        sys.exit(1)

    if solo_paquete:
        print('Paquete enviado (sin verificación).')
        return

    print(f'Esperando a que SSH responda (hasta {esperar}s)...')
    t0 = time.time()
    while time.time() - t0 < esperar:
        if ssh_ok():
            print(f'Legion DESPIERTA y SSH responde tras '
                  f'{time.time() - t0:.0f}s ✓')
            # estado de los servidores de inferencia
            r = subprocess.run(
                ['ssh', '-i', CLAVE, '-o', 'BatchMode=yes', HOST,
                 'powershell -Command "Get-Process ollama,llama-server '
                 '-ErrorAction SilentlyContinue | Select-Object '
                 '-ExpandProperty ProcessName"'],
                capture_output=True, text=True, timeout=30)
            procs = [p for p in r.stdout.splitlines() if p.strip()]
            print('Procesos de inferencia en Legion:', procs or 'ninguno')
            if tarea:
                subprocess.run(['schtasks', '/run', '/tn', tarea])
                print(f'Tarea "{tarea}" lanzada.')
            return
        time.sleep(5)
    # reintento: si la IP fija ya no vale, buscar el MAC en la subred
    print('Sin respuesta en la IP fija; buscando el MAC de Legion...')
    ip2 = buscar_por_mac()
    if ip2:
        print(f'Encontrada en {ip2} — reintentando SSH...')
        for _ in range(24):
            if ssh_ok():
                print('Legion DESPIERTA ✓ (IP nueva: ' + ip2 + ')')
                return
            time.sleep(5)
    print('TIMEOUT: Legion no respondió. Opciones: pulsar el botón de '
          'encendido, o comprobar WoL en BIOS (ErP/EuP off) y que la '
          'Ethernet esté conectada al router.')


if __name__ == '__main__':
    main()
