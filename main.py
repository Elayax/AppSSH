#!/usr/bin/env python3
"""
RUT956 CONFIGURATOR v2.0
Herramienta SSH para Teltonika RUT956 + Autodeteccion de dispositivos Ethernet
"""

import FreeSimpleGUI as sg
import paramiko
import json
import os
import re
import socket
import subprocess
import threading
import webbrowser
from datetime import datetime

# ==============================================================================
#  PALETA â€” Dark Navy Elegante
# ==============================================================================
BG1    = '#08111f'   # fondo principal  (navy profundo)
BG2    = '#0d1e36'   # fondo secundario
BG3    = '#142848'   # inputs / filas alternas
ACCENT = '#1a5cbe'   # azul acento
ACCT2  = '#3a8ee8'   # azul claro (highlight)
TEXT   = '#c8daf0'   # texto principal
DIM    = '#4a6a90'   # texto apagado
GREEN  = '#18c890'   # estado online
RED    = '#e84040'   # estado offline / error
AMBER  = '#e8a020'   # advertencia
CLBG   = '#060d1a'   # fondo consola log

sg.theme_add_new('EliteNavy', {
    'BACKGROUND': BG1,
    'TEXT':       TEXT,
    'INPUT':      BG3,
    'TEXT_INPUT': TEXT,
    'SCROLL':     BG2,
    'BUTTON':     (TEXT, ACCENT),
    'PROGRESS':   (ACCT2, BG2),
    'BORDER':     1,
    'SLIDER_DEPTH':   0,
    'PROGRESS_DEPTH': 0,
})
sg.theme('EliteNavy')

NO_WIN = 0x08000000   # CREATE_NO_WINDOW (Windows)


# ==============================================================================
#  UTILIDADES DE RED
# ==============================================================================

def ping_host(ip: str, timeout_ms: int = 800) -> bool:
    """Ping silencioso (oculta la ventana de consola en Windows)."""
    try:
        r = subprocess.run(
            ['ping', '-n', '1', '-w', str(timeout_ms), ip],
            capture_output=True, text=True, creationflags=NO_WIN,
        )
        return r.returncode == 0
    except Exception:
        return False


def resolve_hostname(ip: str) -> str:
    """DNS inverso; devuelve 'â€”' si falla."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return 'â€”'


def get_arp_devices() -> list:
    """Lee la tabla ARP del sistema y devuelve los dispositivos locales."""
    try:
        r = subprocess.run(
            ['arp', '-a'],
            capture_output=True, text=True, creationflags=NO_WIN,
        )
        devices = []
        pat = re.compile(r'\s*([\d.]+)\s+([\w:-]+)\s+(\S+)')
        for m in pat.finditer(r.stdout):
            ip, mac, kind = m.group(1), m.group(2), m.group(3)
            # descartar multicast y broadcast
            if (ip.startswith('224.') or ip.startswith('239.')
                    or ip.endswith('.255') or ip == '255.255.255.255'):
                continue
            devices.append({'ip': ip, 'mac': mac, 'type': kind})
        return devices
    except Exception:
        return []


def scan_network_thread(window) -> None:
    """
    Hilo de escaneo:
      - Obtiene dispositivos de la tabla ARP
      - Hace ping a cada uno para verificar si esta vivo
      - Envia eventos al window con write_event_value
    """
    devices = get_arp_devices()
    if not devices:
        window.write_event_value('SCAN_DONE', 0)
        return

    lock = threading.Lock()
    count = [0]

    def check(dev):
        ip  = dev['ip']
        alive    = ping_host(ip)
        hostname = resolve_hostname(ip) if alive else 'â€”'
        status   = 'ONLINE' if alive else 'OFFLINE'
        row = [
            ip,
            dev['mac'].upper(),
            hostname,
            dev['type'].capitalize(),
            status,
        ]
        with lock:
            count[0] += 1
        window.write_event_value('SCAN_ROW', row)

    threads = [threading.Thread(target=check, args=(d,), daemon=True)
               for d in devices]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6)

    window.write_event_value('SCAN_DONE', count[0])


# ==============================================================================
#  CLASE PRINCIPAL
# ==============================================================================

class RUT956ConfigGUI:

    def __init__(self):
        self.ssh = None
        self.config = self._load_config()
        self.window = None
        self.log_lines: list[str] = []
        self.current_progress = 0
        self.progress_text = ''
        self.connected = False
        self.devices_data: list[list] = []   # filas de la tabla de dispositivos
        self._scanning = False
        # Barra de estado global (footer)
        self._status_msg   = 'Listo'
        self._status_color = DIM
        # Password guardado en memoria para reconexion automatica
        self._session_password: str = ''
        # Lock para reconexion SSH (evita que dos hilos reconecten en paralelo)
        self._reconnect_lock = threading.Lock()

    # -- Config ----------------------------------------------------------------

    def _load_config(self) -> dict:
        if os.path.exists('config.json'):
            try:
                with open('config.json') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'router_ip': '192.168.1.1', 'username': 'admin'}

    def _save_config(self) -> None:
        try:
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self._log(f'Error guardando config: {e}', 'ERROR')

    # -- Log -------------------------------------------------------------------

    def _log(self, msg: str, level: str = 'INFO') -> None:
        ts    = datetime.now().strftime('%H:%M:%S')
        icons = {'INFO': '>', 'OK': '[OK]', 'ERROR': '[X]', 'WAIT': '...', 'CMD': '$'}
        line  = f'[{ts}] {icons.get(level, ".")} {msg}'
        self.log_lines.append(line)
        if len(self.log_lines) > 300:
            self.log_lines.pop(0)

    # -- Roadmap State Detection + Interactive Tree ---------------------------

    # Acciones al hacer clic en cada nodo del arbol
    ROADMAP_ACTIONS = {
        'SSH':  'BTN_CONNECT',
        'LAN':  'BTN_LAN',
        'SIM':  'BTN_SIM',
        'SNMP': 'BTN_SNMP',
        'ZT':   'BTN_ZT',
        'FW':   'BTN_FW',
    }

    def _update_roadmap(self) -> None:
        """Hilo de fondo: actualiza estado del Roadmap y el panel de parametros."""
        if not self.connected or not self.ssh:
            for k in self.ROADMAP_ACTIONS:
                try:
                    self.window[f'RD_BTN_{k}'].update(button_color=(DIM, BG2))
                except Exception:
                    pass
            return

        def _check():
            try:
                data = {}

                # 1. SSH ok
                self.window.write_event_value('__RD__', ('SSH', GREEN))

                # 2. LAN
                lan_ip = self.exec_cmd(
                    "uci get network.lan.ipaddr 2>/dev/null", show_cmd=False) or ''
                c_lan = GREEN if lan_ip and lan_ip.strip() != '192.168.1.1' else AMBER
                data['lan_ip'] = lan_ip.strip()
                self.window.write_event_value('__RD__', ('LAN', c_lan))

                # 3. SIM: IPs, operador, senal
                sim1_ip = self.exec_cmd(
                    "ip addr show mob1s1a1 2>/dev/null"
                    " | grep 'inet ' | awk '{print $2}' | cut -d/ -f1",
                    show_cmd=False) or ''
                sim2_ip = self.exec_cmd(
                    "ip addr show mob1s2a1 2>/dev/null"
                    " | grep 'inet ' | awk '{print $2}' | cut -d/ -f1",
                    show_cmd=False) or ''
                oper  = self.exec_cmd("gsmctl -o 2>/dev/null || echo '-'", show_cmd=False) or '-'  # -o = operator name
                ntype = self.exec_cmd("gsmctl -t 2>/dev/null || echo '-'", show_cmd=False) or '-'  # -t = conntype LTE/etc
                band  = self.exec_cmd("gsmctl -b 2>/dev/null || echo '-'", show_cmd=False) or '-'
                qual  = self.exec_cmd("gsmctl -q 2>/dev/null || echo '-'", show_cmd=False) or '-'
                imei  = self.exec_cmd("gsmctl -i 2>/dev/null || echo '-'", show_cmd=False) or '-'  # -i = IMEI (no -m)
                iccid = self.exec_cmd("gsmctl -J 2>/dev/null || echo '-'", show_cmd=False) or '-'
                rssi_l = next((l for l in qual.splitlines() if 'RSSI' in l), '-')
                sinr_l = next((l for l in qual.splitlines() if 'SINR' in l), '')
                # Color: GREEN si hay IP, AMBER si hay senal/banda aunque sin IP, DIM si nada
                has_ip     = bool(sim1_ip.strip() or sim2_ip.strip())
                has_signal = ('RSSI' in qual and 'N/A' not in qual)
                has_band   = (band.strip() not in ('', '-', 'N/A'))
                if has_ip:
                    c_sim = GREEN
                elif has_signal or has_band:
                    c_sim = AMBER   # registrado en red pero sin IP aun
                else:
                    c_sim = DIM     # sin señal
                data.update({
                    'sim1_ip': sim1_ip.strip(), 'sim2_ip': sim2_ip.strip(),
                    'oper': oper.strip(), 'ntype': ntype.strip(),
                    'band': band.strip(), 'rssi': rssi_l.strip(),
                    'sinr': sinr_l.strip(), 'imei': imei.strip(), 'iccid': iccid.strip(),
                })
                self.window.write_event_value('__RD__', ('SIM', c_sim))

                # 4. SNMP
                snmp_st = self.exec_cmd("pgrep snmpd 2>/dev/null || echo ''", show_cmd=False) or ''
                c_snmp = GREEN if snmp_st.strip() else DIM
                data['snmp'] = ('Activo (PID: ' + snmp_st.strip()[:6] + ')') if snmp_st.strip() else 'Inactivo'
                self.window.write_event_value('__RD__', ('SNMP', c_snmp))

                # 5. ZeroTier: estado, IP y Network IDs activos
                zt_st = self.exec_cmd("zerotier-cli status 2>/dev/null || echo ''", show_cmd=False) or ''
                zt_ip = self.exec_cmd(
                    "ip addr 2>/dev/null | grep -A2 ' zt' | grep 'inet ' "
                    "| awk '{print $2}' | cut -d/ -f1 | head -1",
                    show_cmd=False) or '-'
                # Obtener redes unidas (ID y estado)
                zt_nets_raw = self.exec_cmd(
                    "zerotier-cli listnetworks 2>/dev/null || echo ''",
                    show_cmd=False) or ''
                # Parsear lineas de listnetworks: <nwid> <name> <mac> <status> <type> <dev> <ips>
                zt_nets = []
                for ln in zt_nets_raw.splitlines():
                    parts = ln.split()
                    if len(parts) >= 4 and len(parts[0]) == 16 and parts[0] != '200':
                        zt_nets.append({'nwid': parts[0], 'status': parts[3] if len(parts) > 3 else '?'})
                c_zt = GREEN if 'ONLINE' in zt_st.upper() else DIM
                data.update({
                    'zt_status': zt_st.strip()[:30],
                    'zt_ip': zt_ip.strip(),
                    'zt_nets': zt_nets,
                })
                self.window.write_event_value('__RD__', ('ZT', c_zt))

                # 6. Firewall: contar redirecciones activas y mostrar detalle
                fw_rules = self.exec_cmd(
                    r"uci show firewall 2>/dev/null | grep '\.name=' | awk -F= '{print $2}'",
                    show_cmd=False) or ''
                fw_snmp  = self.exec_cmd(
                    "uci show firewall 2>/dev/null | grep UPS_SNMP || echo ''",
                    show_cmd=False) or ''
                fw_masq  = self.exec_cmd(
                    "uci get firewall.@zone[1].masq 2>/dev/null || echo '0'",
                    show_cmd=False) or '0'
                rule_names = [r.strip().strip("'") for r in fw_rules.splitlines() if r.strip()]
                c_fw = GREEN if fw_snmp.strip() else AMBER
                fw_detail = ''
                if fw_snmp.strip():
                    fw_detail = f'UPS_SNMP OK  masq={fw_masq.strip()}'
                elif rule_names:
                    fw_detail = f'{len(rule_names)} reglas (sin UPS_SNMP)'
                else:
                    fw_detail = 'Sin reglas de redireccion'
                data.update({'fw': fw_detail, 'fw_rules': rule_names})
                self.window.write_event_value('__RD__', ('FW', c_fw))

                # Enviar datos al panel de estado derecho
                self.window.write_event_value('__STATUS_DATA__', data)

            except Exception:
                pass

        threading.Thread(target=_check, daemon=True).start()

    def _build_roadmap_col(self):
        """Arbol interactivo tipo GIT: cada nodo es un boton clickeable que activa su accion."""
        nodes = [
            ('SSH',  'CONEXION SSH',  'Conectar al router via SSH'),
            ('LAN',  'RED  LAN',      'Configurar IP LAN y DHCP'),
            ('SIM',  '4G  /  SIM',   'Configurar SIM 4G del modem'),
            ('SNMP', 'SNMPD',         'Configurar servicio SNMP'),
            ('ZT',   'ZEROTIER VPN',  'Configurar ZeroTier VPN'),
            ('FW',   'FIREWALL',      'Configurar reglas firewall'),
        ]

        rows = [
            [sg.Text('PROGRESO CONFIG',
                     font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                     pad=(8, (10, 18)))],
        ]
        for i, (key, label, tooltip) in enumerate(nodes):
            rows.append([
                sg.Button(
                    ' (o) ',
                    key=f'RD_BTN_{key}',
                    button_color=(DIM, BG2),
                    tooltip=tooltip,
                    border_width=0,
                    pad=(8, 0),
                    font=('Consolas', 13, 'bold'),
                ),
                sg.Text(
                    label,
                    text_color=TEXT,
                    font=('Segoe UI', 9, 'bold'),
                    size=(16, 1),
                    pad=(2, 0),
                ),
            ])
            if i < len(nodes) - 1:
                rows.append([
                    sg.Text('     |', font=('Consolas', 11), text_color=BG3, pad=(8, 0)),
                ])

        rows.append([sg.HorizontalSeparator(color=BG3, pad=(8, (18, 6)))])
        rows.append([
            sg.Button(
                '[>] Refrescar',
                key='BTN_REFRESH_STATUS',
                button_color=(DIM, BG2),
                font=('Segoe UI', 8),
                pad=(8, 4),
                border_width=0,
            )
        ])

        return sg.Column(
            rows,
            background_color=BG2,
            pad=(0, 0),
            expand_y=True,
            vertical_alignment='top',
        )

    def _build_status_panel(self):
        """Panel derecho: parametros del modem en tiempo real."""
        def _row(label, key, val='--'):
            return [
                sg.Text(f'{label}:', size=(13, 1),
                        text_color=DIM, font=('Segoe UI', 8)),
                sg.Text(val, key=key, text_color=ACCT2,
                        font=('Consolas', 9, 'bold'), size=(20, 1)),
            ]
        def _sec(title):
            return [sg.Text(title, font=('Segoe UI', 8, 'bold'),
                            text_color=DIM, pad=(8, (10, 2)))]

        rows = [
            [sg.Text('ESTADO DEL ROUTER',
                     font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                     pad=(8, (10, 6)))],
            [sg.Button('=] Copiar Estado', key='BTN_COPY_STATUS',
                       button_color=(DIM, BG3),
                       font=('Segoe UI', 8), pad=(8, (0, 10)),
                       border_width=0, tooltip='Copia todo el estado al portapapeles para diagnóstico')],

            *[_sec('-- RED LAN --------------------')],
            *[_row('IP LAN',       'ST_LAN_IP')],

            *[_sec('-- SIM / 4G -------------------')],
            *[_row('SIM 1 IP',     'ST_SIM1_IP')],
            *[_row('SIM 2 IP',     'ST_SIM2_IP')],
            *[_row('Operador',     'ST_OPER')],
            *[_row('Tipo Red',     'ST_NTYPE')],
            *[_row('Banda LTE',    'ST_BAND')],
            *[_row('RSSI',         'ST_RSSI')],
            *[_row('SINR',         'ST_SINR')],

            *[_sec('-- VPN / SNMP -----------------')],
            *[_row('ZeroTier IP',  'ST_ZT_IP')],
            *[_row('ZT Estado',    'ST_ZT')],
            # Network ID activo: fila especial con boton de edicion
            [
                sg.Text('ZT Network ID:', size=(13, 1),
                        text_color=DIM, font=('Segoe UI', 8)),
                sg.Text('--', key='ST_ZT_NETID', text_color=ACCT2,
                        font=('Consolas', 9, 'bold'), size=(18, 1)),
            ],
            [
                sg.Push(),
                sg.Button('[+] Cambiar Red ZT', key='BTN_ZT_EDIT',
                          button_color=(DIM, BG3), font=('Segoe UI', 8),
                          border_width=0, pad=((0, 8), (0, 4))),
            ],
            *[_row('SNMP',         'ST_SNMP')],
            *[_row('Firewall',     'ST_FW')],

            *[_sec('-- MODEM ----------------------')],
            *[_row('IMEI',         'ST_IMEI')],
            *[_row('ICCID',        'ST_ICCID')],
        ]

        return sg.Column(
            rows,
            background_color=BG2,
            pad=(0, 0),
            expand_y=True,
            vertical_alignment='top',
            scrollable=True,
            vertical_scroll_only=True,
        )

    # -- SSH -------------------------------------------------------------------

    def connect(self, ip: str, user: str, password: str) -> bool:
        try:
            self._log(f'Conectando a {ip}...', 'WAIT')
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(ip, username=user, password=password, timeout=10)
            self._log(f'SSH conectado a {ip}', 'OK')
            self.config['router_ip'] = ip
            self.config['username']  = user
            self._session_password   = password   # guardar para reconexion
            self._save_config()
            self.connected = True
            return True
        except Exception as e:
            self._log(f'Error de conexion: {e}', 'ERROR')
            self.connected = False
            return False

    def _try_reconnect(self, retries: int = 5, delay: int = 6) -> bool:
        """Intenta reconectar SSH después de un reinicio de red. Thread-safe."""
        import time as _t
        with self._reconnect_lock:
            # Si ya alguien reconecto mientras esperabamos el lock, listo
            if self.connected and self.ssh:
                try:
                    self.ssh.exec_command('echo ping', timeout=3)
                    return True
                except Exception:
                    pass
            ip   = self.config.get('router_ip', '')
            user = self.config.get('username',  '')
            pwd  = self._session_password
            if not all([ip, user, pwd]):
                self._log('Sin credenciales para reconectar', 'ERROR')
                return False
            for attempt in range(1, retries + 1):
                self._log(f'Reconectando SSH ({attempt}/{retries})...', 'WAIT')
                try:
                    new_ssh = paramiko.SSHClient()
                    new_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    new_ssh.connect(ip, username=user, password=pwd, timeout=12)
                    self.ssh = new_ssh
                    self.connected = True
                    self._log('SSH reconectado OK', 'OK')
                    return True
                except Exception as e:
                    self._log(f'Intento {attempt} fallido: {e}', 'ERROR')
                    if attempt < retries:
                        _t.sleep(delay)
            self.connected = False
            self._log('No se pudo reconectar SSH', 'ERROR')
            return False

    def exec_cmd(self, cmd: str, show_cmd: bool = True) -> str:
        try:
            if show_cmd:
                for line in cmd.strip().split('\n'):
                    line = line.strip()
                    if line:
                        self._log(line, 'CMD')
            _, stdout, _ = self.ssh.exec_command(cmd)
            result = stdout.read().decode().strip()
            if result and len(result) < 150:
                self._log(f'-> {result}', 'INFO')
            return result
        except Exception as e:
            err_str = str(e).lower()
            # Si la sesion murio (network restart la mato), intentar reconectar
            if 'session not active' in err_str or 'not connected' in err_str or 'socket' in err_str:
                if self._session_password and self._try_reconnect():
                    # Reintentar el comando una vez con la nueva sesion
                    try:
                        _, stdout, _ = self.ssh.exec_command(cmd)
                        result = stdout.read().decode().strip()
                        if result and len(result) < 150:
                            self._log(f'-> {result}', 'INFO')
                        return result
                    except Exception as e2:
                        self._log(f'Error tras reconexion: {e2}', 'ERROR')
                        return ''
            self._log(f'Error ejecutando comando: {e}', 'ERROR')
            return ''

    def _set_progress(self, pct: int, text: str) -> None:
        self.current_progress = min(pct, 100)
        self.progress_text    = text

    def _set_status(self, msg: str, color: str = DIM) -> None:
        """Actualiza la barra de estado inferior (footer). Visible en ambas pestanas."""
        self._status_msg   = msg
        self._status_color = color
        # Loguear tambien para que quede en el historial del log
        self._log(msg, 'INFO')

    # -- Configuraciones de Router ----------------------------------------------


    # -- Wizard SIM 4G (Dual SIM, checklist en vivo) --------------------------

    def _sim_wizard(self) -> None:
        """
        Wizard de configuracion SIM 4G para RUT956 (Dual SIM).
        Fase 1: formulario de parametros para SIM1 y SIM2.
        Fase 2: ventana de progreso con checklist visual en tiempo real.
        Ambas SIMs se configuran en paralelo (threads coordinados).
        """
        import time as _time
        import threading as _threading

        if not self.connected:
            self._log('No conectado al router', 'ERROR')
            self._set_status('SIM 4G - No hay conexion SSH activa', RED)
            return

        # -- Pasos del proceso (id, etiqueta) ---------------------------------
        STEPS = [
            ('diag',    'Diagnostico inicial modem/SIM'),
            ('clean',   'Limpiar interfaces residuales'),
            ('uci',     'Configurar UCI  (proto=wwan)'),
            ('fw',      'Asociar a zona WAN firewall'),
            ('restart', 'Reiniciar servicio de red'),
            ('ifup',    'Levantar interfaz (ifup)'),
            ('r1',      'Ronda 1 - esperando registro'),
            ('r2',      'Ronda 2 - reintento modem'),
            ('r3',      'Ronda 3 - verificando senal'),
            ('r4',      'Ronda 4 - ultimo intento'),
            ('final',   'Diagnostico final'),
        ]
        # Iconos y colores por estado
        ST = {
            'pending': ('o', DIM),
            'run':     ('~', AMBER),
            'ok':      ('V', GREEN),
            'warn':    ('!', '#e8a838'),
            'err':     ('X', RED),
            'skip':    ('-', DIM),
        }
        # Secuencia de animacion para pasos activos
        SPIN = ['~', '@', '#', '$']

        def _sig_bar(rssi_str: str) -> str:
            """Convierte RSSI en barra visual: UUUUU-- -73 dBm (Buena)."""
            try:
                val = int(rssi_str.strip().replace('RSSI:', '').strip())
                if val >= -65:
                    bars, qual = 6, 'Excelente'
                elif val >= -75:
                    bars, qual = 5, 'Muy buena'
                elif val >= -85:
                    bars, qual = 4, 'Buena'
                elif val >= -95:
                    bars, qual = 2, 'Regular'
                else:
                    bars, qual = 1, 'Debil'
                bar = '#' * bars + '-' * (6 - bars)
                return f'{bar}  {val} dBm  ({qual})'
            except Exception:
                return rssi_str or 'N/A'

        def _get_ip(slot: str) -> str:
            """Obtiene IP del slot - intenta ip addr y luego ifconfig como fallback."""
            # Metodo 1: ip addr show (kernels modernos)
            ip = self.exec_cmd(
                f"ip addr show {slot} 2>/dev/null"
                f" | grep 'inet ' | awk '{{print $2}}' | cut -d/ -f1",
                show_cmd=False) or ''
            if ip.strip():
                return ip.strip()
            # Metodo 2: ifconfig (OpenWrt clasico)
            ip2 = self.exec_cmd(
                f"ifconfig {slot} 2>/dev/null"
                f" | grep 'inet addr' | awk '{{print $2}}' | cut -d: -f2",
                show_cmd=False) or ''
            if ip2.strip():
                return ip2.strip()
            # Metodo 3: ubus / netifd
            ip3 = self.exec_cmd(
                f"ubus call network.interface.{slot} status 2>/dev/null"
                f" | grep '\"address\"' | head -1 | awk -F'\"' '{{print $4}}'",
                show_cmd=False) or ''
            return ip3.strip()

        # -- Fase 1: Formulario -----------------------------------------------
        def _sim_col(n: str):
            slot = 'mob1s1a1' if n == '1' else 'mob1s2a1'
            return sg.Column([
                [sg.Text(f'SIM {n}  .  {slot}',
                         font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                         pad=(0, (6, 6)))],
                [sg.Text('APN:', size=(12, 1), text_color=TEXT),
                 sg.InputText('internet.itelcel.com', key=f'S{n}_APN', size=(24, 1))],
                [sg.Text('Usuario:', size=(12, 1), text_color=DIM),
                 sg.InputText('webgprs', key=f'S{n}_USER', size=(24, 1))],
                [sg.Text('Contrasena:', size=(12, 1), text_color=DIM),
                 sg.InputText('webgprs2002', key=f'S{n}_PASS',
                              size=(24, 1), password_char='*')],
                [sg.Text('Auth:', size=(12, 1), text_color=TEXT),
                 sg.Combo(['none', 'pap', 'chap'], default_value='none',
                          key=f'S{n}_AUTH', size=(10, 1),
                          background_color=BG3, text_color=TEXT)],
                [sg.Text('PDP type:', size=(12, 1), text_color=TEXT),
                 sg.Combo(['IP', 'IPv6', 'IPv4v6'], default_value='IP',
                          key=f'S{n}_PDP', size=(10, 1),
                          background_color=BG3, text_color=TEXT)],
            ], background_color=BG2, pad=(6, 4))

        form_layout = [
            [sg.Text('SIM 4G Configuracion - RUT956 (Dual SIM)',
                     font=('Segoe UI', 12, 'bold'), text_color=ACCT2,
                     pad=(0, (10, 4)))],
            [sg.Text('Ambas SIMs se configuraran en paralelo con los datos de tu operador.',
                     text_color=DIM, font=('Segoe UI', 8), pad=(0, (0, 8)))],
            [sg.HorizontalSeparator(color=BG3)],
            [_sim_col('1'), sg.VSep(color=BG3, pad=(10, 4)), _sim_col('2')],
            [sg.HorizontalSeparator(color=BG3, pad=(0, 6))],
            [sg.Checkbox('  Copiar configuracion de SIM 1 a SIM 2',
                         key='COPY_SIM', default=True,
                         text_color=DIM, background_color=BG1,
                         font=('Segoe UI', 9))],
            [sg.Text(
                '! Si una SIM no esta presente el proceso la marcara como N/A '
                'y continuara con la otra.\n'
                '    Deja usuario/contrasena vacios si tu operador no los requiere.',
                text_color=DIM, font=('Segoe UI', 8), pad=(0, (2, 8)))],
            [sg.Push(),
             sg.Button('> Iniciar configuracion', key='START', size=(22, 1),
                       button_color=(TEXT, '#186840'),
                       font=('Segoe UI', 10, 'bold')),
             sg.Button('X Cancelar', key='CANCEL', size=(13, 1),
                       button_color=(TEXT, '#4a1010'),
                       font=('Segoe UI', 9, 'bold'))],
        ]

        form_win = sg.Window(
            'Configurar SIM 4G - RUT956',
            form_layout, finalize=True,
            background_color=BG1, modal=True, keep_on_top=True,
        )

        cfgs: list = []
        while True:
            ev, va = form_win.read()
            if ev in (sg.WINDOW_CLOSED, 'CANCEL'):
                form_win.close()
                self._log('Configuracion SIM cancelada por usuario', 'INFO')
                self._set_status('SIM 4G - Cancelado', DIM)
                return
            if ev == 'START':
                if va.get('COPY_SIM'):
                    for f in ('APN', 'USER', 'PASS', 'AUTH', 'PDP'):
                        form_win[f'S2_{f}'].update(va[f'S1_{f}'])
                    va = form_win.read(timeout=0)[1]

                cfgs = [
                    {'sim': '1', 'slot': 'mob1s1a1',
                     'apn':  va['S1_APN'].strip(), 'user': va['S1_USER'].strip(),
                     'password': va['S1_PASS'].strip(),
                     'auth': va['S1_AUTH'], 'pdp': va['S1_PDP']},
                    {'sim': '2', 'slot': 'mob1s2a1',
                     'apn':  va['S2_APN'].strip(), 'user': va['S2_USER'].strip(),
                     'password': va['S2_PASS'].strip(),
                     'auth': va['S2_AUTH'], 'pdp': va['S2_PDP']},
                ]
                form_win.close()
                break

        # -- Fase 2: Ventana de progreso con checklist ------------------------
        def _step_row(prefix: str, sid: str, label: str) -> list:
            return [
                sg.Text('o', key=f'{prefix}_{sid}_ICO',
                        text_color=DIM, font=('Consolas', 11, 'bold'),
                        size=(2, 1), pad=((8, 2), 1)),
                sg.Text(label, key=f'{prefix}_{sid}_LBL',
                        text_color=DIM, font=('Segoe UI', 9),
                        size=(30, 1), pad=((0, 4), 1)),
            ]

        def _sim_progress_col(n: str) -> sg.Column:
            slot = 'mob1s1a1' if n == '1' else 'mob1s2a1'
            prefix = f'S{n}'
            rows: list = [
                [sg.Text(f'SIM {n}  .  {slot}',
                         font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                         pad=(8, (8, 6)))],
                [sg.HorizontalSeparator(color=BG3, pad=((8, 8), 2))],
            ]
            for sid, slbl in STEPS:
                rows.append(_step_row(prefix, sid, slbl))
            rows += [
                [sg.HorizontalSeparator(color=BG3, pad=((8, 8), (6, 2)))],
                [sg.Text('... En progreso...',
                         key=f'{prefix}_RESULT',
                         text_color=AMBER,
                         font=('Segoe UI', 9, 'bold'),
                         size=(38, 4), pad=(8, 2))],
            ]
            return sg.Column(rows, background_color=BG2,
                             pad=(4, 4), expand_x=True)

        prog_layout = [
            [sg.Text('SIM 4G Configuracion - RUT956 (Dual SIM en paralelo)',
                     font=('Segoe UI', 12, 'bold'), text_color=ACCT2,
                     pad=(10, (10, 4)))],
            [sg.Text('Configurando SIM1 y SIM2 simultaneamente...',
                     key='PROG_SUB', text_color=DIM,
                     font=('Segoe UI', 8), pad=(10, (0, 8)))],
            [sg.HorizontalSeparator(color=BG3)],
            [_sim_progress_col('1'),
             sg.VSep(color=BG3, pad=(6, 4)),
             _sim_progress_col('2')],
            [sg.HorizontalSeparator(color=BG3, pad=(0, (6, 2)))],
            [sg.Text('Log detallado:', text_color=DIM,
                     font=('Segoe UI', 8), pad=(10, (2, 0)))],
            [sg.Multiline('', key='PROG_LOG', size=(88, 7),
                          disabled=True, font=('Consolas', 8),
                          background_color=CLBG, text_color='#7ab8f0',
                          expand_x=True, pad=(8, 2))],
            [sg.Push(),
             sg.Button('=] Copiar Diagnostico', key='COPY_DIAG', size=(20, 1),
                       button_color=(TEXT, '#2a4a6a'),
                       font=('Segoe UI', 9, 'bold'),
                       disabled=True, pad=(4, 6)),
             sg.Button('V Cerrar', key='CLOSE', size=(14, 1),
                       button_color=(TEXT, '#186840'),
                       font=('Segoe UI', 10, 'bold'),
                       disabled=True, pad=(4, 6))],
        ]

        prog_win = sg.Window(
            'Progreso - Configuracion SIM 4G',
            prog_layout, finalize=True,
            background_color=BG1, modal=True,
            keep_on_top=True, size=(900, 660),
        )

        prog_log_lines: list = []
        done_count = [0]
        spin_tick = [0]   # contador de animacion compartido
        # Resultados finales por SIM (para el diagnostico copiable)
        sim_results: dict = {'S1': {}, 'S2': {}}

        # -- Workers de configuracion -----------------------------------------
        restart_event = _threading.Event()
        uci_lock      = _threading.Lock()   # evita condicion de carrera en UCI

        def sim_worker(cfg: dict, is_primary: bool) -> None:
            sim_n  = cfg['sim']
            slot   = cfg['slot']
            apn    = cfg['apn']
            user   = cfg['user']
            passw  = cfg['password']
            auth   = cfg['auth']
            pdp    = cfg['pdp']
            prefix = f'S{sim_n}'

            def upd(sid: str, state: str, label: str = '',
                    detail: str = '') -> None:
                ico, col = ST[state]
                prog_win.write_event_value('__UPD__', {
                    'prefix': prefix, 'sid': sid,
                    'ico': ico, 'col': col, 'label': label,
                })
                if detail:
                    prog_win.write_event_value(
                        '__LOG__', f'SIM{sim_n} | {detail}')

            def finish(state: str, msg: str) -> None:
                prog_win.write_event_value('__RESULT__', {
                    'prefix': prefix, 'state': state, 'msg': msg,
                })
                done_count[0] += 1
                prog_win.write_event_value('__DONE__', done_count[0])

            def _real_operator(val: str) -> bool:
                if not val or val.upper() in ('N/A', 'UNKNOWN', ''):
                    return False
                # Identificadores de hardware: alfanum sin espacios, > 10 chars
                if (len(val) > 10 and ' ' not in val
                        and val.replace('-', '').isalnum()):
                    return False
                return True

            # -- PASO 0: Diagnostico inicial (por slot) -----------------------
            upd('diag', 'run', 'Verificando modem y SIM...')
            # gsmctl -z = simstate (NO tiene opcion -s para slot, -s es para SMS)
            # gsmctl -T = current sim slot
            # gsmctl -i = IMEI (NO -m, que da el modelo del equipo)
            # gsmctl -J = ICCID
            sim_st = self.exec_cmd(
                'gsmctl -z 2>/dev/null || echo "N/A"',
                show_cmd=False) or 'N/A'
            iccid  = self.exec_cmd(
                'gsmctl -J 2>/dev/null || echo "N/A"',
                show_cmd=False) or 'N/A'
            imei   = self.exec_cmd(
                'gsmctl -i 2>/dev/null || echo "N/A"',  # -i = IMEI (no -m)
                show_cmd=False) or 'N/A'

            upd('diag', 'run', f'Estado SIM: {sim_st.strip()}',
                f'ICCID:{iccid.strip()}  IMEI:{imei.strip()}')

            sim_results[prefix].update({
                'slot': slot, 'apn': apn, 'auth': auth, 'pdp': pdp,
                'iccid': iccid.strip(), 'imei': imei.strip(),
            })

            if 'not inserted' in sim_st.lower():
                upd('diag', 'err', f'SIM {sim_n}: no detectada fisicamente',
                    f'Estado:{sim_st.strip()}')
                for sid, _ in STEPS[1:]:
                    upd(sid, 'skip', 'N/A - SIM no presente')
                sim_results[prefix]['resultado'] = f'X SIM {sim_n}: no insertada'
                finish('err',
                       f'X  SIM {sim_n}: no insertada\n'
                       'Verifica el contacto fisico de la SIM en el router.')
                if is_primary:
                    restart_event.set()
                return

            upd('diag', 'ok',
                f'SIM {sim_n} detectada  .  {sim_st.strip()}',
                f'ICCID:{iccid.strip()}  IMEI:{imei.strip()}')

            # -- PASO CLEAN: Limpiar interfaces residuales --------------------
            upd('clean', 'run', 'Buscando interfaces residuales...')
            self.exec_cmd(
                "uci -q get network.wan_4g >/dev/null 2>&1 && "
                "{ uci delete network.wan_4g; uci commit network; "
                "echo 'wan_4g eliminada'; } || echo 'limpio'",
                show_cmd=False)
            upd('clean', 'ok', 'Interfaces limpias (wan_4g removida si existia)')

            # -- PASO UCI: Configuracion segun firmware RUT9M_R_00.07.19 -----
            upd('uci', 'run',
                f'Escribiendo UCI completo para {slot}...')
            # Metrica: SIM1=10 (primaria), SIM2=20 (secundaria/failover)
            metric = '10' if is_primary else '20'
            # NOTA: delegate='0' y method='nat' SI son validos en proto=wwan
            # del firmware RUT9M_R_00.07.19 - confirmado con config real
            cmd_uci = (
                f"uci set network.{slot}.proto='wwan'\n"
                f"uci set network.{slot}.sim='{sim_n}'\n"
                f"uci set network.{slot}.modem='1'\n"
                f"uci set network.{slot}.apn='{apn}'\n"
                f"uci set network.{slot}.pdptype='{pdp}'\n"
                f"uci set network.{slot}.auth='{auth}'\n"
                f"uci set network.{slot}.auto_apn='1'\n"
                f"uci set network.{slot}.pdp='1'\n"
                f"uci set network.{slot}.dhcpv6='0'\n"
                f"uci set network.{slot}.delegate='0'\n"
                f"uci set network.{slot}.method='nat'\n"
                f"uci set network.{slot}.area_type='wan'\n"
                f"uci set network.{slot}.metric='{metric}'\n"
                f"uci set network.{slot}.mtu='1430'\n"
                f"uci set network.{slot}.enabled='1'\n"
                f"uci set network.{slot}.auto='1'\n"
            )
            if user:  cmd_uci += f"uci set network.{slot}.username='{user}'\n"
            if passw: cmd_uci += f"uci set network.{slot}.password='{passw}'\n"
            cmd_uci += 'uci commit network'
            with uci_lock:
                out = self.exec_cmd(cmd_uci, show_cmd=False) or ''
            if 'error' in out.lower():
                upd('uci', 'warn', 'UCI aplicado con advertencias', out[:80])
            else:
                upd('uci', 'ok',
                    f'UCI OK  .  {slot}  APN={apn}  metric={metric}  enabled=1')

            # -- PASO Firewall ------------------------------------------------
            upd('fw', 'run', 'Verificando zona WAN...')
            cur = self.exec_cmd(
                "uci get firewall.@zone[1].network 2>/dev/null || echo ''",
                show_cmd=False) or ''
            if slot not in cur:
                self.exec_cmd(
                    f"uci add_list firewall.@zone[1].network='{slot}'\n"
                    "uci commit firewall",
                    show_cmd=False)
                upd('fw', 'ok', f'{slot} anadido a zona WAN')
            else:
                upd('fw', 'ok', f'{slot} ya estaba en zona WAN')

            # -- PASO Restart: solo SIM1 reinicia la red ---------------------
            if is_primary:
                upd('restart', 'run', 'Reiniciando red (puede cortar SSH)...')
                # El network restart cierra la sesion SSH; lanzarlo en bg
                # y luego reconectar activamente
                try:
                    self.ssh.exec_command('/etc/init.d/network restart &')
                except Exception:
                    pass
                self.connected = False
                upd('restart', 'run', 'Red reiniciada - reconectando SSH...')
                _time.sleep(8)   # esperar a que el router levante la red
                reconectado = self._try_reconnect(retries=6, delay=5)
                if reconectado:
                    upd('restart', 'ok', 'Red reiniciada + SSH reconectado OK')
                else:
                    upd('restart', 'warn', 'Red reiniciada - SSH sin respuesta aun')
                _time.sleep(2)
                restart_event.set()
            else:
                upd('restart', 'run', 'Esperando reinicio de red (SIM1)...')
                restart_event.wait(timeout=120)
                # Asegurarse de que la sesion SSH este viva para SIM2 tambien
                if not self.connected:
                    self._try_reconnect(retries=3, delay=5)
                upd('restart', 'ok', 'Red reiniciada (coordinado con SIM1)')

            # -- PASO ifup ---------------------------------------------------
            upd('ifup', 'run', f'Reiniciando interfaz {slot}...')
            # ifdown primero para limpiar estado previo, luego ifup
            self.exec_cmd(
                f'ifdown {slot} 2>/dev/null || true; sleep 2; '
                f'ifup {slot} 2>/dev/null || true',
                show_cmd=False)
            # Esperar 10s para que netifd negocie IP con el APN
            upd('ifup', 'run', f'Esperando negociacion IP con APN (10s)...')
            _time.sleep(10)
            ip_check = _get_ip(slot)
            if ip_check:
                upd('ifup', 'ok', f'IP asignada: {ip_check}')
            else:
                upd('ifup', 'ok', f'ifup ejecutado - esperando IP del APN...')

            # -- Rondas de espera con countdown ------------------------------
            ROUND_SECS = 15
            round_ids  = ['r1', 'r2', 'r3', 'r4']
            connected  = False
            last_state: dict = {}

            for rnd_i, rid in enumerate(round_ids):
                rnd_lbl = STEPS[6 + rnd_i][1]

                for t in range(ROUND_SECS, 0, -1):
                    upd(rid, 'run', f'{rnd_lbl}  ({t}s...)')
                    _time.sleep(1)

                # Leer estado del modem
                # gsmctl -z = simstate | -o = operator (NO -a, eso es serial)
                # gsmctl -i = IMEI | -q = signal | -b = band
                s_sim  = self.exec_cmd(
                    'gsmctl -z 2>/dev/null || echo "N/A"',
                    show_cmd=False) or 'N/A'
                s_oper = self.exec_cmd(
                    'gsmctl -o 2>/dev/null || echo "N/A"',  # -o = operator name
                    show_cmd=False) or 'N/A'
                s_net  = self.exec_cmd(
                    'gsmctl -t 2>/dev/null || echo "N/A"',  # -t = conntype (LTE/etc)
                    show_cmd=False) or 'N/A'
                # gsmctl -q RSSI/RSRP/SINR/RSRQ (mejor que -s)
                s_qual = self.exec_cmd(
                    'gsmctl -q 2>/dev/null || echo "N/A"',
                    show_cmd=False) or 'N/A'
                s_band = self.exec_cmd(
                    'gsmctl -b 2>/dev/null || echo "N/A"',
                    show_cmd=False) or 'N/A'
                s_ip   = _get_ip(slot)

                last_state = {
                    'sim': s_sim.strip(), 'oper': s_oper.strip(),
                    'ntype': s_net.strip(), 'qual': s_qual,
                    'band': s_band.strip(), 'ip': s_ip,
                }

                # Deteccion de senal: gsmctl -q devuelve "RSSI: -73\nRSRP: ..."
                has_signal = ('RSSI' in s_qual and 'N/A' not in s_qual)
                ok_oper    = _real_operator(s_oper.strip())
                ok_ip      = bool(s_ip)

                # Extraer RSSI para el log
                rssi_line = next(
                    (l for l in s_qual.splitlines() if 'RSSI' in l), '')
                detail = (
                    f'SIM={s_sim.strip()}  Oper={s_oper.strip()}  '
                    f'Red={s_net.strip()}  Banda={s_band.strip()}  '
                    f'IP={s_ip or "-"}  {rssi_line.strip()}'
                )

                if has_signal or ok_oper or ok_ip:
                    upd(rid, 'ok',
                        f'{rnd_lbl}  V CONECTADO', detail)
                    connected = True
                    for skip_id in round_ids[rnd_i + 1:]:
                        upd(skip_id, 'skip', '(no necesario)')
                    break
                else:
                    upd(rid, 'warn',
                        f'{rnd_lbl}  sin senal...', detail)
                    if rnd_i < len(round_ids) - 1:
                        upd(rid, 'warn',
                            f'{rnd_lbl}  reiniciando modem...')
                        self.exec_cmd(
                            f'gsmctl -Q 2>/dev/null || true; '
                            f'ifup {slot} 2>/dev/null || true',
                            show_cmd=False)

            # -- Diagnostico final -------------------------------------------
            upd('final', 'run', 'Diagnostico final...')
            s = last_state
            has_sig   = ('RSSI' in s.get('qual', '')
                         and 'N/A' not in s.get('qual', ''))
            ok_oper   = _real_operator(s.get('oper', ''))
            ok_ip     = bool(s.get('ip', ''))
            ok_sim    = ('inserted' in s.get('sim', '').lower()
                         or 'ready' in s.get('sim', '').lower())

            # Parsear niveles de senal para resumen
            qual_lines   = s.get('qual', '').replace('\r', '').split('\n')
            sig_summary  = '  '.join(
                l.strip() for l in qual_lines if ':' in l)
            rssi_line    = next(
                (l for l in qual_lines if 'RSSI' in l), '')
            sig_bar      = _sig_bar(
                rssi_line.replace('RSSI:', '').strip())
            band         = s.get('band', '?')

            detail = (
                f"SIM={s.get('sim','?')}  Oper={s.get('oper','?')}  "
                f"Red={s.get('ntype','?')}  Banda={band}  "
                f"IP={s.get('ip','-')}  {sig_summary}"
            )

            if connected:
                resultado = (
                    f'V  SIM {sim_n} CONECTADA\n'
                    f'Operador: {s.get("oper","?")}  '
                    f'Red: {s.get("ntype","?")}  Banda: {band}\n'
                    f'Senal: {sig_bar}\n'
                    f'{sig_summary}\n'
                    f'IP: {s.get("ip") or "esperando..."}'
                )
                sim_results[prefix].update({'resultado': resultado, 'estado': 'ok',
                                            'oper': s.get('oper','?'), 'ip': s.get('ip',''),
                                            'banda': band, 'senal': sig_bar})
                upd('final', 'ok', 'V Conectado a red celular', detail)
                finish('ok', resultado)
            elif ok_sim:
                resultado = (
                    f'!  SIM {sim_n}: insertada, sin conexion\n'
                    f'APN: {apn}  Banda: {band}\n'
                    f'Senal: {sig_bar}\n'
                    'Verifica APN en WebUI y plan de datos'
                )
                sim_results[prefix].update({'resultado': resultado, 'estado': 'warn',
                                            'ip': '', 'banda': band, 'senal': sig_bar})
                upd('final', 'warn', 'SIM presente - sin datos aun', detail)
                finish('warn', resultado)
            else:
                resultado = (
                    f'X  SIM {sim_n}: sin respuesta\n'
                    f'Estado: {s.get("sim","?")}  '
                    'Verifica fisicamente la SIM y antena'
                )
                sim_results[prefix].update({'resultado': resultado, 'estado': 'err',
                                            'ip': '', 'banda': band, 'senal': ''})
                upd('final', 'err', 'Sin respuesta del modem', detail)
                finish('err', resultado)

        # -- Lanzar ambos threads --------------------------------------------
        _threading.Thread(
            target=sim_worker, args=(cfgs[0], True),  daemon=True).start()
        _threading.Thread(
            target=sim_worker, args=(cfgs[1], False), daemon=True).start()

        # -- Event loop de la ventana de progreso ----------------------------
        result_col = {'ok': GREEN, 'warn': AMBER, 'err': RED, 'skip': DIM}

        while True:
            prog_win['PROG_LOG'].update('\n'.join(prog_log_lines))
            try:
                prog_win['PROG_LOG'].Widget.see('end')
            except Exception:
                pass

            ev2, va2 = prog_win.read(timeout=200)

            if ev2 in (sg.WINDOW_CLOSED, 'CLOSE'):
                break

            elif ev2 == '__UPD__':
                d  = va2['__UPD__']
                p  = d['prefix']
                si = d['sid']
                # Si es 'run', aplicar icono de animacion
                ico = d['ico']
                if d.get('col') == AMBER:
                    ico = SPIN[spin_tick[0] % len(SPIN)]
                    spin_tick[0] += 1
                prog_win[f'{p}_{si}_ICO'].update(ico,
                                                 text_color=d['col'])
                if d.get('label'):
                    prog_win[f'{p}_{si}_LBL'].update(
                        d['label'], text_color=d['col'])

            elif ev2 == '__LOG__':
                prog_log_lines.append(va2['__LOG__'])

            elif ev2 == '__RESULT__':
                d   = va2['__RESULT__']
                col = result_col.get(d['state'], DIM)
                prog_win[f"{d['prefix']}_RESULT"].update(
                    d['msg'], text_color=col)

            elif ev2 == '__DONE__':
                if va2['__DONE__'] >= 2:
                    prog_win['PROG_SUB'].update(
                        'V  Configuracion completada para ambas SIMs')
                    prog_win['CLOSE'].update(disabled=False)
                    prog_win['COPY_DIAG'].update(disabled=False)
                    self._set_status(
                        'SIM 4G - Configuracion dual completa. '
                        'Revisa resultados en la ventana.', GREEN)

            elif ev2 == 'COPY_DIAG':
                # Generar texto de diagnostico copiable para IA
                ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                lines = [
                    '=' * 60,
                    f'DIAGNOSTICO SIM 4G  --  {ts_now}',
                    '=' * 60,
                ]
                for pref, label in [('S1', 'SIM 1'), ('S2', 'SIM 2')]:
                    r = sim_results.get(pref, {})
                    lines += [
                        '',
                        f'--- {label} ({r.get("slot","?")}) ---',
                        f'  APN    : {r.get("apn","?")}',
                        f'  Auth   : {r.get("auth","?")}',
                        f'  PDP    : {r.get("pdp","?")}',
                        f'  IMEI   : {r.get("imei","?")}',
                        f'  ICCID  : {r.get("iccid","?")}',
                        f'  Oper   : {r.get("oper","?")}',
                        f'  Banda  : {r.get("banda","?")}',
                        f'  Senal  : {r.get("senal","?")}',
                        f'  IP     : {r.get("ip") or "sin IP"}',
                        f'  Estado : {r.get("estado","?")}',
                        f'  Resultado:',
                    ]
                    for rl in r.get('resultado', '(sin resultado)').splitlines():
                        lines.append(f'    {rl}')
                lines += [
                    '',
                    '--- LOG DETALLADO ---',
                ]
                lines += prog_log_lines
                lines += [
                    '',
                    '--- LOG PRINCIPAL (ultimas 60 lineas) ---',
                ]
                lines += self.log_lines[-60:]
                diag_text = '\n'.join(lines)
                try:
                    sg.clipboard_set(diag_text)
                    prog_win['PROG_SUB'].update(
                        'V  Diagnostico copiado al portapapeles - pega en tu IA')
                except Exception as _ce:
                    # fallback: mostrar en popup scrollable
                    sg.popup_scrolled(
                        diag_text, title='Diagnostico SIM',
                        size=(80, 30), background_color=BG1, text_color=TEXT,
                        font=('Consolas', 8),
                    )

        prog_win.close()

    def _lan_wizard(self) -> None:
        """Wizard interactivo para configuracion LAN y DHCP."""
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return

        layout = [
            [sg.Text('(NET) Configuracion de Red Local (LAN)', 
                     font=('Segoe UI', 12, 'bold'), text_color=ACCT2, pad=(0, (10, 5)))],
            [sg.Text('Define la direccion IP del router y el rango DHCP.', text_color=DIM, font=('Segoe UI', 8))],
            [sg.HorizontalSeparator(color=BG3, pad=(0, 10))],
            
            [sg.Text('IP LAN Router:', size=(15, 1)),
             sg.InputText('192.168.10.1', key='LAN_IP', size=(20, 1))],
            [sg.Text('Mascara Subred:', size=(15, 1)),
             sg.InputText('255.255.255.0', key='LAN_MASK', size=(20, 1))],
            
            [sg.Text('DHCP Inicio:', size=(15, 1), text_color=DIM),
             sg.InputText('100', key='DHCP_START', size=(10, 1))],
            [sg.Text('DHCP Limite:', size=(15, 1), text_color=DIM),
             sg.InputText('100', key='DHCP_LIMIT', size=(10, 1))],
            
            [sg.HorizontalSeparator(color=BG3, pad=(0, 10))],
            [sg.Text('[!] Nota: Al cambiar la IP la red se reiniciara.', text_color=AMBER, font=('Segoe UI', 8))],
            [sg.Push(), 
             sg.Button('[>] Aplicar LAN', key='SAVE_LAN', button_color=(TEXT, '#186840'), font=('Segoe UI', 9, 'bold')),
             sg.Button('[X] Cancelar', key='CANCEL', button_color=(TEXT, '#4a1010'))]
        ]
        
        win = sg.Window('Configuracion LAN', layout, modal=True, background_color=BG1, keep_on_top=True)
        ev, va = win.read()
        if ev == 'SAVE_LAN':
            ip_lan = va['LAN_IP'].strip()
            mask   = va['LAN_MASK'].strip()
            start  = va['DHCP_START'].strip()
            limit  = va['DHCP_LIMIT'].strip()
            win.close()
            
            def worker():
                self._log(f'=== CONFIGURANDO LAN -> {ip_lan} ===')
                self._set_progress(20, 'Escribiendo UCI LAN')
                cmd = (
                    f"uci set network.lan.ipaddr='{ip_lan}'\n"
                    f"uci set network.lan.netmask='{mask}'\n"
                    f"uci set dhcp.lan.start='{start}'\n"
                    f"uci set dhcp.lan.limit='{limit}'\n"
                    "uci commit network\nuci commit dhcp\n"
                    "/etc/init.d/network restart &"
                )
                self.exec_cmd(cmd)
                self._log(f'LAN configurada: {ip_lan}. Reiniciando red...', 'OK')
                self._set_progress(100, 'Completado [OK]')
                self._set_status(f'LAN CAMBIADA A {ip_lan} - Reconectate si perdiste acceso.', AMBER)
                # Actualizar roadmap tras un momento
                import time; time.sleep(5)
                self._update_roadmap()
                
            threading.Thread(target=worker, daemon=True).start()
        else:
            win.close()

    def configure_snmp(self):
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return
        self._log('=== CONFIGURANDO SNMP ===')
        self._set_progress(70, 'SNMP: Instalando paquetes')
        cmd = (
            "opkg update > /dev/null 2>&1 || true\n"
            "opkg install snmp snmp-utils > /dev/null 2>&1 || echo 'Ya instalado'\n"
            "cat > /etc/config/snmp << 'CONFIG'\n"
            "config snmp\n"
            "    option enabled '1'\n"
            "    option community 'public'\n"
            "    option port '161'\n"
            "    option contact 'admin'\n"
            "    option location 'RUT956'\n"
            "CONFIG\n"
            "/etc/init.d/snmpd start\n"
            "/etc/init.d/snmpd enable"
        )
        self.exec_cmd(cmd)
        self._log('SNMP configurado (puerto 161, community: public)', 'OK')
        self._set_progress(75, 'SNMP: Completado [OK]')
        self._update_roadmap()

    def configure_zerotier(self, network_id: str):
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return
        if not network_id or len(network_id) != 16:
            self._log('Network ID invalido (debe tener 16 caracteres)', 'ERROR'); return

        self._log('=== CONFIGURANDO ZEROTIER ===')
        self._set_progress(80, 'ZeroTier: Instalando')
        cmd = (
            "opkg install zerotier > /dev/null 2>&1 || echo 'Ya instalado'\n"
            "/etc/init.d/zerotier start > /dev/null 2>&1 || true\n"
            "/etc/init.d/zerotier enable\n"
            f"zerotier-cli join {network_id}"
        )
        self.exec_cmd(cmd)
        self._log('Esperando autorizacion ZeroTier (12 s)...', 'WAIT')
        self.exec_cmd('sleep 12')

        # -- Ajustar MTU de la interfaz ZeroTier (evita fragmentacion en 4G) --
        # La interfaz ZT se llama zt<nwid_corto>; MTU optimo con 4G/LTE = 1400
        self._log('Ajustando MTU ZeroTier para evitar fragmentacion en 4G...', 'INFO')
        mtu_cmd = (
            # Obtener nombre de la interfaz ZT y bajar su MTU a 1400
            "ZT_IF=$(ip link 2>/dev/null | grep -o 'zt[a-z0-9]*' | head -1); "
            "if [ -n \"$ZT_IF\" ]; then "
            "  ip link set \"$ZT_IF\" mtu 1400 2>/dev/null && echo \"MTU $ZT_IF=1400 OK\"; "
            "fi"
        )
        mtu_out = self.exec_cmd(mtu_cmd, show_cmd=False) or ''
        if 'MTU' in mtu_out and 'OK' in mtu_out:
            self._log(f'MTU ZT: {mtu_out.strip()}', 'OK')
        else:
            self._log('MTU ZT: interfaz aun no levantada (se aplicara al conectar)', 'WAIT')

        self._log(f'ZeroTier configurado (Network: {network_id[:8]}...)', 'OK')
        self._set_progress(83, 'ZeroTier: Diagnosticando peers...')

        # -- Diagnostico de peers (RELAY vs DIRECT) ---------------------------
        self.zerotier_diagnostics(silent=False)
        self._set_progress(85, 'ZeroTier: Completado [OK]')
        self._update_roadmap()

    def zerotier_diagnostics(self, silent: bool = False) -> dict:
        """
        Diagnostica el estado de conexion ZeroTier en el router:
        - Modo de cada peer: DIRECT / via RELAY
        - Latencia
        - Redes unidas y su estado
        Devuelve un dict con los resultados y los loguea.
        """
        if not self.connected:
            self._log('ZT Diagnostico: sin conexion SSH', 'ERROR')
            return {}

        # Estado general
        zt_ver = self.exec_cmd(
            'zerotier-cli status 2>/dev/null || echo "N/A"', show_cmd=False) or 'N/A'
        # Peers: ID, latencia, via (DIRECT o via relay)
        peers_raw = self.exec_cmd(
            'zerotier-cli peers 2>/dev/planet || zerotier-cli peers 2>/dev/null || echo ""',
            show_cmd=False) or ''
        # Redes
        nets_raw = self.exec_cmd(
            'zerotier-cli listnetworks 2>/dev/null || echo ""',
            show_cmd=False) or ''
        # IP ZT
        zt_ip = self.exec_cmd(
            "ip addr 2>/dev/null | grep -A2 ' zt' | grep 'inet ' "
            "| awk '{print $2}' | cut -d/ -f1 | head -1",
            show_cmd=False) or ''
        # MTU actual
        zt_mtu = self.exec_cmd(
            "ip link 2>/dev/null | grep -A1 'zt' | grep 'mtu' "
            "| awk '{print $5}' | head -1",
            show_cmd=False) or '?'

        result = {
            'status': zt_ver.strip(),
            'zt_ip': zt_ip.strip(),
            'mtu': zt_mtu.strip(),
            'peers': [],
            'networks': [],
            'relay_count': 0,
            'direct_count': 0,
        }

        relay_peers  = []
        direct_peers = []
        for ln in peers_raw.splitlines():
            parts = ln.split()
            # Formato: <id> <ver> <role> <lat_ms> <link_type> ...
            if len(parts) >= 5 and parts[0] not in ('200', '<ztaddr>'):
                peer_id  = parts[0]
                lat      = parts[3] if len(parts) > 3 else '?'
                link     = parts[4] if len(parts) > 4 else '?'
                is_relay = ('relay' in link.lower() or link == '-1' or lat == '-1')
                entry = {'id': peer_id, 'lat': lat, 'link': link, 'relay': is_relay}
                result['peers'].append(entry)
                if is_relay:
                    relay_peers.append(entry)
                    result['relay_count'] += 1
                else:
                    direct_peers.append(entry)
                    result['direct_count'] += 1

        for ln in nets_raw.splitlines():
            parts = ln.split()
            if len(parts) >= 4 and len(parts[0]) == 16 and parts[0] != '200':
                result['networks'].append({
                    'nwid': parts[0],
                    'name': parts[1] if len(parts) > 1 else '?',
                    'status': parts[3] if len(parts) > 3 else '?',
                })

        if not silent:
            self._log(f'ZeroTier: {zt_ver.strip()}', 'INFO')
            self._log(f'  ZT IP: {zt_ip or "sin IP aun"}  MTU: {zt_mtu}', 'INFO')
            for net in result['networks']:
                self._log(
                    f'  Red: {net["nwid"]}  estado={net["status"]}', 'INFO')
            if relay_peers:
                self._log(
                    f'  [!] RELAY activo ({len(relay_peers)} peers via relay): '
                    + ', '.join(p["id"][:10] + '..' for p in relay_peers[:3]),
                    'ERROR')
                self._log(
                    '  Causa probable: NAT/firewall bloqueando UDP 9993. '
                    'ZeroTier usa servidores de relay lentos como fallback.', 'ERROR')
                self._log(
                    '  Solucion: abre puerto UDP 9993 en tu firewall local '
                    'y en el router upstream del RUT956.', 'WAIT')
            elif direct_peers:
                self._log(
                    f'  [OK] Conexion DIRECTA ({len(direct_peers)} peers)', 'OK')
            else:
                self._log('  Sin peers visible aun (puede estar autorizando)', 'WAIT')

        return result

    def configure_firewall(self):
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return
        self._log('=== CONFIGURANDO FIREWALL ===')
        self._set_progress(90, 'Firewall: Configurando')
        cmd = (
            "uci set firewall.zone_wan.masq='1'\n"
            "uci add firewall redirect\n"
            "uci set firewall.@redirect[-1].name='UPS_SNMP'\n"
            "uci set firewall.@redirect[-1].src='wan'\n"
            "uci set firewall.@redirect[-1].proto='udp'\n"
            "uci set firewall.@redirect[-1].src_dport='161'\n"
            "uci set firewall.@redirect[-1].dest='lan'\n"
            "uci set firewall.@redirect[-1].dest_ip='192.168.10.198'\n"
            "uci set firewall.@redirect[-1].dest_port='161'\n"
            "uci commit firewall\n"
            "/etc/init.d/firewall restart > /dev/null 2>&1 || true"
        )
        self.exec_cmd(cmd)
        self._log('Firewall configurado (161 -> 192.168.10.198:161)', 'OK')
        self._set_progress(95, 'Firewall: Completado [OK]')
        self._set_status('Firewall configurado - port forward 161 -> 192.168.10.198:161', GREEN)
        self._update_roadmap()

    # -- Cambiar IP del router --------------------------------------------------

    def change_ip(self, new_ip: str, new_mask: str, new_gw: str) -> None:
        """Cambia la IP LAN del router via SSH."""
        if not self.connected:
            self._log('No conectado al router', 'ERROR')
            self._set_status('Cambio de IP cancelado - no hay conexion SSH activa', RED)
            return

        # Validar formato basico IP
        ip_re = re.compile(
            r'^(\d{1,3}\.){3}\d{1,3}$'
        )
        if not ip_re.match(new_ip):
            self._log(f'IP invalida: {new_ip}', 'ERROR')
            self._set_status(f'IP invalida: "{new_ip}" - usa formato X.X.X.X', RED)
            return

        self._set_status(f'Cambio de IP - aplicando nueva direccion {new_ip}...', ACCT2)
        self._log(f'=== CAMBIANDO IP DEL ROUTER -> {new_ip} ===')
        self._set_progress(10, 'Cambio IP: escribiendo UCI')

        cmd = (
            f"uci set network.lan.ipaddr='{new_ip}'\n"
            f"uci set network.lan.netmask='{new_mask}'\n"
        )
        if new_gw.strip():
            cmd += f"uci set network.lan.gateway='{new_gw}'\n"
        cmd += "uci commit network"

        self._set_status(f'Cambio de IP [1/2] - Guardando nueva IP {new_ip} en UCI...', ACCT2)
        self._set_progress(40, f'Cambio IP: guardando {new_ip}')
        self.exec_cmd(cmd)

        self._set_status(
            f'Cambio de IP [2/2] - Reiniciando red... ! La conexion SSH se perdera.  '
            f'Reconectate usando la nueva IP: {new_ip}', AMBER
        )
        self._set_progress(70, 'Cambio IP: reiniciando red')
        self._log(
            f'! Reiniciando red - la sesion SSH se cerrara.  '
            f'Usa la nueva IP {new_ip} para reconectarte.', 'WAIT'
        )

        # Lanzar restart en background en el router (no esperamos respuesta,
        # porque la sesion SSH se cerrara al cambiar la IP)
        try:
            self.ssh.exec_command('/etc/init.d/network restart &')
        except Exception:
            pass

        import time; time.sleep(1)
        self.connected = False
        self.ssh = None

        # Actualizar IP guardada
        self.config['router_ip'] = new_ip
        self._save_config()

        self._set_progress(100, f'IP cambiada a {new_ip} [OK]')
        self._set_status(
            f'[OK] IP cambiada a {new_ip}  |  Reconectate con esa IP en el campo superior', GREEN
        )
        self._log(f'IP cambiada a {new_ip}. Recuerda reconectarte.', 'OK')

        # Actualizar campo IP en la ventana (thread-safe via evento)
        if self.window:
            self.window.write_event_value('UPDATE_IP_FIELD', new_ip)
        self._update_roadmap()

    def validate_all(self):
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return
        self._log('=== VALIDACIONES ===')
        self._set_progress(70, 'Validando: Celular')
        sig = self.exec_cmd("gsmctl -s 2>/dev/null || echo 'N/A'", show_cmd=False)
        if sig and sig != 'N/A':
            self._log(f'Senal celular: {sig}', 'OK')
        else:
            self._log('Senal celular: No detectada', 'ERROR')

        self._set_progress(80, 'Validando: ZeroTier')
        zt = self.exec_cmd("zerotier-cli status 2>/dev/null || echo 'N/A'", show_cmd=False)
        if zt and zt != 'N/A':
            self._log(f'ZeroTier: {zt[:60]}', 'OK')

        self._set_progress(90, 'Validando: SNMP')
        snmp = self.exec_cmd("netstat -ulpn 2>/dev/null | grep 161 || echo 'No activo'", show_cmd=False)
        if snmp and '161' in snmp:
            self._log('SNMP: Escuchando en puerto 161', 'OK')
        else:
            self._log('SNMP: No esta activo', 'ERROR')

        self._set_progress(100, '[OK] Validaciones completadas')
        self._log('TODAS LAS CONFIGURACIONES COMPLETADAS', 'OK')
        self._update_roadmap()

    # -- Layout ----------------------------------------------------------------

    def _build_layout(self) -> list:

        btn_cfg = dict(font=('Segoe UI', 9, 'bold'), pad=(4, 4))

        # =====================================================================
        # COLUMNA IZQUIERDA: Arbol interactivo de progreso
        # =====================================================================
        left_col = sg.Column(
            [[self._build_roadmap_col()]],
            background_color=BG2,
            pad=(0, 0),
            expand_y=True,
            vertical_alignment='top',
        )

        # =====================================================================
        # COLUMNA CENTRAL: Conexion SSH + LOG completo expandible
        # =====================================================================
        center_content = [
            [sg.Text('CONEXION SSH',
                     font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                     pad=(0, (8, 6)))],
            [sg.Text('IP Router:', size=(10, 1), text_color=DIM,
                     font=('Segoe UI', 9)),
             sg.InputText(self.config.get('router_ip', '192.168.1.1'),
                          key='IP', size=(18, 1), font=('Consolas', 9)),
             sg.Text('Usuario:', size=(8, 1), text_color=DIM,
                     font=('Segoe UI', 9)),
             sg.InputText(self.config.get('username', 'admin'),
                          key='USER', size=(14, 1), font=('Consolas', 9)),
             sg.Text('Pass:', size=(5, 1), text_color=DIM,
                     font=('Segoe UI', 9)),
             sg.InputText('', key='PASS', password_char='*',
                          size=(14, 1), font=('Consolas', 9)),
             sg.Button('CONECTAR', key='BTN_CONNECT',
                       button_color=(TEXT, ACCENT),
                       font=('Segoe UI', 9, 'bold'), pad=(6, 4))],

            [sg.Text('( ) Desconectado', key='STATUS',
                     text_color=RED, font=('Segoe UI', 9, 'bold'),
                     pad=(2, (4, 6))),
             sg.Push(),
             sg.Button('Cambiar IP', key='BTN_CHANGE_IP',
                       button_color=(TEXT, '#2a5080'),
                       font=('Segoe UI', 8), pad=(4, 4)),
             sg.Button('[OK] Validar Todo', key='BTN_VAL',
                       button_color=(TEXT, '#186840'),
                       font=('Segoe UI', 8, 'bold'), pad=(4, 4))],

            [sg.HorizontalSeparator(color=BG3, pad=(0, (4, 8)))],

            # LOG COMPLETO: expand_y=True para que llene todo el espacio
            [sg.Text('LOG EN VIVO',
                     font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                     pad=(0, (0, 4)))],
            [sg.Multiline(
                '',
                key='OUTPUT',
                disabled=True,
                autoscroll=True,
                font=('Consolas', 9),
                text_color='#7ab8f0',
                background_color=CLBG,
                expand_x=True,
                expand_y=True,
                no_scrollbar=False,
                pad=(0, 0),
            )],

            [sg.Text('Progreso:', text_color=DIM, size=(9, 1),
                     font=('Segoe UI', 8)),
             sg.ProgressBar(100, size=(1, 14), key='PROGRESS',
                            bar_color=(ACCT2, BG2), expand_x=True),
             sg.Text('', key='PROGRESS_TEXT',
                     text_color=DIM, font=('Segoe UI', 8),
                     size=(28, 1))],

            # Botones de accion (redundantes del arbol, utiles por si acaso)
            [sg.HorizontalSeparator(color=BG3, pad=(0, (6, 4)))],
            [sg.Button('(SIM) SIM 4G',   key='BTN_SIM',  size=(11, 1),
                       button_color=(TEXT, '#16408a'), **btn_cfg),
             sg.Button('(NET) LAN',      key='BTN_LAN',  size=(11, 1),
                       button_color=(TEXT, '#16408a'), **btn_cfg),
             sg.Button('(STATS) SNMP',   key='BTN_SNMP', size=(11, 1),
                       button_color=(TEXT, '#16408a'), **btn_cfg),
             sg.Button('(LINK) ZeroTier',key='BTN_ZT',   size=(11, 1),
                       button_color=(TEXT, '#16408a'), **btn_cfg),
             sg.Button('(FW) Firewall',  key='BTN_FW',   size=(11, 1),
                       button_color=(TEXT, '#16408a'), **btn_cfg)],
        ]

        center_col = sg.Column(
            center_content,
            background_color=BG1,
            pad=(12, 6),
            expand_x=True,
            expand_y=True,
            vertical_alignment='top',
        )

        # =====================================================================
        # COLUMNA DERECHA: Estado del modem en tiempo real
        # =====================================================================
        right_col = sg.Column(
            [[self._build_status_panel()]],
            background_color=BG2,
            pad=(0, 0),
            expand_y=True,
            vertical_alignment='top',
        )

        # Tab 1: 3 columnas sin costuras
        tab_router = [
            [left_col,
             sg.VSep(color=BG3, pad=(0, 0)),
             center_col,
             sg.VSep(color=BG3, pad=(0, 0)),
             right_col]
        ]

        # =====================================================================
        # TAB 2: Dispositivos en red (tabla ocupa todo el espacio)
        # =====================================================================
        tab_devices = [
            [sg.Text('Dispositivos en la Red Local',
                     font=('Segoe UI', 11, 'bold'), text_color=ACCT2,
                     pad=(0, (10, 4))),
             sg.Push(),
             sg.Button('[M] Detectar Modem', key='BTN_DETECT_MODEM',
                       button_color=(TEXT, '#16408a'),
                       font=('Segoe UI', 9, 'bold'), pad=(4, 4),
                       tooltip='Detecta la IP del gateway/modem de tu conexion actual'),
             sg.Button('Escanear Red',    key='BTN_SCAN',
                       button_color=(TEXT, ACCENT), **btn_cfg),
             sg.Button('Abrir en Browser', key='BTN_BROWSER',
                       button_color=(TEXT, '#186840'), **btn_cfg),
             sg.Button('Limpiar', key='BTN_CLR_DEV',
                       button_color=(TEXT, '#4a1010'), **btn_cfg)],

            # Banner de resultado de deteccion de modem
            [sg.Text('Gateway/Modem detectado:',
                     text_color=DIM, font=('Segoe UI', 9),
                     pad=(2, (0, 2))),
             sg.Text('--', key='MODEM_IP',
                     text_color=GREEN, font=('Consolas', 11, 'bold'),
                     size=(20, 1), pad=(4, (0, 2))),
             sg.Text('', key='MODEM_HOST',
                     text_color=ACCT2, font=('Segoe UI', 9),
                     size=(30, 1), pad=(0, (0, 2))),
             sg.Text('', key='MODEM_PING',
                     text_color=DIM, font=('Segoe UI', 8),
                     size=(12, 1))],

            [sg.Text(
                'Lee la tabla ARP y hace ping a cada dispositivo. '
                'Selecciona una fila y haz clic en "Abrir en Browser" para su panel web.',
                text_color=DIM, font=('Segoe UI', 9), pad=(2, (0, 8)))],

            [sg.Table(
                values=[],
                headings=['  IP Address', '  MAC Address', '  Hostname', '  Tipo', '  Estado'],
                col_widths=[16, 22, 34, 11, 10],
                auto_size_columns=False,
                display_row_numbers=False,
                justification='left',
                key='DEV_TABLE',
                selected_row_colors=(TEXT, ACCENT),
                background_color=BG2,
                alternating_row_color=BG3,
                text_color=TEXT,
                header_background_color=ACCENT,
                header_text_color='#ffffff',
                header_font=('Segoe UI', 9, 'bold'),
                font=('Consolas', 9),
                enable_events=True,
                expand_x=True,
                expand_y=True,
                row_height=28,
                num_rows=26,
            )],

            [sg.Text('', key='DEV_STATUS', text_color=DIM,
                     font=('Segoe UI', 9), expand_x=True),
             sg.Text('Seleccionado:', text_color=DIM, font=('Segoe UI', 9)),
             sg.Text('-', key='SEL_IP', text_color=ACCT2,
                     font=('Segoe UI', 9, 'bold'), size=(18, 1))],
        ]

        # =====================================================================
        # LAYOUT RAIZ
        # =====================================================================
        layout = [
            [sg.Text('RUT956', font=('Segoe UI', 18, 'bold'),
                     text_color=ACCT2, pad=((14, 4), (8, 6))),
             sg.Text('CONFIGURATOR  v2.0',
                     font=('Segoe UI', 13, 'bold'), text_color=TEXT,
                     pad=((0, 0), (10, 6))),
             sg.Push(),
             sg.Text('', key='HDR_IP', text_color=DIM,
                     font=('Consolas', 9), pad=((0, 10), 0)),
             sg.Button('X  Salir', key='BTN_EXIT',
                       button_color=(TEXT, '#4a1010'),
                       font=('Segoe UI', 9, 'bold'), pad=(12, 8))],

            [sg.HorizontalSeparator(color=ACCENT, pad=(0, 0))],

            [sg.TabGroup(
                [[sg.Tab('  Configuracion Router  ', tab_router,
                         background_color=BG1),
                  sg.Tab('  Dispositivos en Red  ', tab_devices,
                         background_color=BG1)]],
                tab_background_color=BG2,
                selected_background_color=BG1,
                selected_title_color=ACCT2,
                title_color=DIM,
                background_color=BG1,
                font=('Segoe UI', 9, 'bold'),
                expand_x=True, expand_y=True,
                key='TABS',
            )],

            [sg.HorizontalSeparator(color=BG3, pad=(0, 0))],
            [sg.Text('( )', key='STATUS_DOT', text_color=DIM,
                     font=('Segoe UI', 9), pad=((10, 4), 4)),
             sg.Text('Listo para conectar',
                     key='STATUS_BAR', text_color=DIM,
                     font=('Segoe UI', 9), expand_x=True),
             sg.Text(datetime.now().strftime('%H:%M'),
                     key='STATUS_TIME', text_color=DIM,
                     font=('Segoe UI', 8), pad=((0, 14), 4))],
        ]
        return layout

    # -- Ventana ---------------------------------------------------------------

    def create_window(self) -> sg.Window:
        window = sg.Window(
            'RUT956 Configurator v2.0',
            self._build_layout(),
            finalize=True,
            resizable=True,
            location=(0, 0),
            background_color=BG1,
        )

        # Pantalla completa al abrir
        try:
            window.maximize()
        except Exception:
            try:
                window.TKroot.state('zoomed')   # Windows
            except Exception:
                pass

        # Ajuste del widget de log (colores y bordes)
        try:
            widget = window['OUTPUT'].Widget
            widget.config(
                fg='#7ab8f0', bg=CLBG,
                insertbackground='#7ab8f0',
                relief='flat', bd=0,
                selectbackground=ACCENT,
                selectforeground=TEXT,
            )
        except Exception:
            pass

        return window

    # -- Bucle de eventos ------------------------------------------------------

    def run(self) -> None:
        self.window = self.create_window()
        self._log('RUT956 CONFIGURATOR v2.0 iniciado', 'OK')
        self._log('Configura la conexion SSH en la pestana "Configuracion Router"', 'INFO')
        self._log('Usa la pestana "Dispositivos en Red" para escanear tu red local', 'INFO')
        self._log('Haz clic en un nodo del arbol para activar esa configuracion', 'INFO')

        while True:
            # Refrescar log (texto completo, autoscroll al final)
            self.window['OUTPUT'].update('\n'.join(self.log_lines))
            try:
                self.window['OUTPUT'].Widget.see('end')
            except Exception:
                pass

            # Refrescar progreso
            self.window['PROGRESS'].update(self.current_progress)
            self.window['PROGRESS_TEXT'].update(self.progress_text)

            # Refrescar barra de estado inferior
            self.window['STATUS_BAR'].update(
                self._status_msg, text_color=self._status_color)
            self.window['STATUS_DOT'].update(text_color=self._status_color)
            self.window['STATUS_TIME'].update(
                datetime.now().strftime('%H:%M:%S'))

            event, values = self.window.read(timeout=200)

            # -- Salir ---------------------------------------------------------
            if event in (sg.WINDOW_CLOSED, 'BTN_EXIT'):
                break

            # -- SSH -----------------------------------------------------------
            elif event in ('BTN_CONNECT', 'RD_BTN_SSH'):
                ip  = values['IP'].strip()
                usr = values['USER'].strip()
                pwd = values['PASS'].strip()
                if not all([ip, usr, pwd]):
                    self._log('Completa todos los campos de conexion', 'ERROR')
                    continue
                if self.connect(ip, usr, pwd):
                    self.window['STATUS'].update(f'(o) Conectado a {ip}', text_color=GREEN)
                    try:
                        self.window['HDR_IP'].update(f'Router: {ip}')
                    except Exception:
                        pass
                    self._update_roadmap()
                else:
                    self.window['STATUS'].update('(X) Error de conexion', text_color=RED)

            elif event in ('BTN_SIM', 'RD_BTN_SIM'):
                self._sim_wizard()
                self._update_roadmap()

            elif event in ('BTN_LAN', 'RD_BTN_LAN'):
                self._lan_wizard()
                self._update_roadmap()

            elif event in ('BTN_SNMP', 'RD_BTN_SNMP'):
                threading.Thread(target=self.configure_snmp, daemon=True).start()

            elif event in ('BTN_FW', 'RD_BTN_FW'):
                threading.Thread(target=self.configure_firewall, daemon=True).start()

            elif event == 'BTN_VAL':
                threading.Thread(target=self.validate_all, daemon=True).start()

            elif event in ('BTN_ZT', 'RD_BTN_ZT'):
                nid = sg.popup_get_text(
                    'Ingresa el Network ID de ZeroTier\n(exactamente 16 caracteres):',
                    title='ZeroTier -- Network ID',
                    background_color=BG2, text_color=TEXT,
                )
                if nid:
                    threading.Thread(target=self.configure_zerotier,
                                     args=(nid,), daemon=True).start()

            # -- Roadmap: estado de nodos (hilo de fondo) ----------------------
            elif event == '__RD__':
                key, color = values[event]
                # Colorear el boton del nodo segun el estado
                node_color_map = {
                    GREEN: (GREEN,  '#0d2a1e'),
                    AMBER: (AMBER,  '#2a1f0d'),
                    RED:   (RED,    '#2a0d0d'),
                    DIM:   (DIM,    BG2),
                }
                fg, bg = node_color_map.get(color, (DIM, BG2))
                try:
                    self.window[f'RD_BTN_{key}'].update(button_color=(fg, bg))
                except Exception:
                    pass

            # -- Panel estado: datos en vivo del modem -------------------------
            elif event == '__STATUS_DATA__':
                d = values[event]
                map_fields = {
                    'ST_LAN_IP':  d.get('lan_ip',  '--'),
                    'ST_SIM1_IP': d.get('sim1_ip', '--'),
                    'ST_SIM2_IP': d.get('sim2_ip', '--'),
                    'ST_OPER':    d.get('oper',    '--'),
                    'ST_NTYPE':   d.get('ntype',   '--'),
                    'ST_BAND':    d.get('band',    '--'),
                    'ST_RSSI':    d.get('rssi',    '--'),
                    'ST_SINR':    d.get('sinr',    '--'),
                    'ST_ZT_IP':   d.get('zt_ip',   '--'),
                    'ST_ZT':      d.get('zt_status','--'),
                    'ST_SNMP':    d.get('snmp',    '--'),
                    'ST_FW':      d.get('fw',      '--'),
                    'ST_IMEI':    (d.get('imei',   '--') or '--')[:18],
                    'ST_ICCID':   (d.get('iccid',  '--') or '--')[:18],
                }
                for k, v in map_fields.items():
                    try:
                        self.window[k].update(v or '--')
                    except Exception:
                        pass
                # Actualizar ZeroTier Network IDs
                zt_nets = d.get('zt_nets', [])
                if zt_nets:
                    net_str = '  '.join(
                        f"{n['nwid'][:8]}.. ({n['status']})"
                        for n in zt_nets[:2])
                    try:
                        self.window['ST_ZT_NETID'].update(net_str)
                    except Exception:
                        pass
                else:
                    try:
                        self.window['ST_ZT_NETID'].update('(ninguna)')
                    except Exception:
                        pass

            # -- Refrescar estado (boton o evento) -----------------------------
            elif event in ('BTN_REFRESH_STATUS',):
                self._update_roadmap()

            elif event == 'BTN_ZT_EDIT':
                # Popup con opciones ZeroTier
                choice = sg.popup_menu(
                    ['[+] Unirse a nueva red',
                     '[D] Diagnostico (relay vs direct)',
                     '[R] Refrescar estado'],
                    title='ZeroTier',
                    location=(None, None),
                )
                if choice == '[+] Unirse a nueva red':
                    nid_new = sg.popup_get_text(
                        'Ingresa el Network ID de ZeroTier\n'
                        '(16 caracteres hex) para unirte a esa red:',
                        title='ZeroTier  --  Unirse a Red',
                        background_color=BG2, text_color=TEXT,
                        default_text='',
                    )
                    if nid_new:
                        nid_new = nid_new.strip()
                        if len(nid_new) == 16:
                            threading.Thread(
                                target=self.configure_zerotier,
                                args=(nid_new,), daemon=True,
                            ).start()
                        else:
                            self._log('Network ID invalido (debe tener 16 caracteres)', 'ERROR')
                elif choice == '[D] Diagnostico (relay vs direct)':
                    if self.connected:
                        threading.Thread(
                            target=self.zerotier_diagnostics,
                            kwargs={'silent': False}, daemon=True,
                        ).start()
                    else:
                        self._log('Conectate al router primero para diagnosticar ZT', 'ERROR')
                elif choice == '[R] Refrescar estado':
                    self._update_roadmap()

            elif event == 'BTN_CHANGE_IP':
                # Popup de cambio de IP con tres campos
                layout_ip = [
                    [sg.Text('Nueva IP del Router (LAN)',
                             font=('Segoe UI', 10, 'bold'), text_color=ACCT2)],
                    [sg.Text('IP actual:', size=(14, 1), text_color=DIM),
                     sg.Text(self.config.get('router_ip', '-'),
                             text_color=AMBER, font=('Consolas', 10))],
                    [sg.HorizontalSeparator(color=BG3)],
                    [sg.Text('Nueva IP:', size=(14, 1), text_color=TEXT),
                     sg.InputText('192.168.1.1', key='NEW_IP', size=(20, 1))],
                    [sg.Text('Mascara:', size=(14, 1), text_color=TEXT),
                     sg.InputText('255.255.255.0', key='NEW_MASK', size=(20, 1))],
                    [sg.Text('Gateway (opc.):', size=(14, 1), text_color=DIM),
                     sg.InputText('', key='NEW_GW', size=(20, 1))],
                    [sg.HorizontalSeparator(color=BG3)],
                    [sg.Text(
                        '[!] La sesion SSH se cerrara al aplicar el cambio.\n'
                        '    Reconectate usando la nueva IP.',
                        text_color=AMBER, font=('Segoe UI', 8))],
                    [sg.Push(),
                     sg.Button('[OK] Aplicar', key='APPLY', size=(10, 1),
                               button_color=(TEXT, '#186840')),
                     sg.Button('[X] Cancelar', key='CANCEL', size=(10, 1),
                               button_color=(TEXT, '#4a1010'))],
                ]
                ip_win = sg.Window(
                    'Cambiar IP del Router',
                    layout_ip, finalize=True,
                    background_color=BG1,
                    modal=True, keep_on_top=True,
                )
                while True:
                    ev2, va2 = ip_win.read()
                    if ev2 in (sg.WINDOW_CLOSED, 'CANCEL'):
                        break
                    if ev2 == 'APPLY':
                        new_ip   = va2['NEW_IP'].strip()
                        new_mask = va2['NEW_MASK'].strip()
                        new_gw   = va2['NEW_GW'].strip()
                        ip_win.close()
                        threading.Thread(
                            target=self.change_ip,
                            args=(new_ip, new_mask, new_gw),
                            daemon=True,
                        ).start()
                        break
                else:
                    ip_win.close()

            elif event == 'UPDATE_IP_FIELD':
                # El hilo de cambio de IP pide actualizar el campo
                new_ip = values[event]
                self.window['IP'].update(new_ip)
                self.window['STATUS'].update(
                    f'( ) Desconectado - reconectate con {new_ip}', text_color=AMBER)

            elif event == 'BTN_COPY_STATUS':
                # Copiar estado completo del router + log para diagnostico con IA
                ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # Leer los valores actuales del panel de estado
                def _vget(k):
                    try: return self.window[k].get()
                    except Exception: return '--'
                diag_parts = [
                    '=' * 60,
                    f'ESTADO ACTUAL DEL ROUTER  --  {ts_now}',
                    f'Router IP : {self.config.get("router_ip", "?")}',
                    f'Conectado : {"SI" if self.connected else "NO"}',
                    '=' * 60,
                    '',
                    '--- RED LAN ---',
                    f'  IP LAN      : {_vget("ST_LAN_IP")}',
                    '',
                    '--- SIM / 4G ---',
                    f'  SIM 1 IP    : {_vget("ST_SIM1_IP")}',
                    f'  SIM 2 IP    : {_vget("ST_SIM2_IP")}',
                    f'  Operador    : {_vget("ST_OPER")}',
                    f'  Tipo Red    : {_vget("ST_NTYPE")}',
                    f'  Banda LTE   : {_vget("ST_BAND")}',
                    f'  RSSI        : {_vget("ST_RSSI")}',
                    f'  SINR        : {_vget("ST_SINR")}',
                    '',
                    '--- VPN / SNMP ---',
                    f'  ZeroTier IP : {_vget("ST_ZT_IP")}',
                    f'  ZT Estado   : {_vget("ST_ZT")}',
                    f'  SNMP        : {_vget("ST_SNMP")}',
                    f'  Firewall    : {_vget("ST_FW")}',
                    '',
                    '--- MODEM ---',
                    f'  IMEI        : {_vget("ST_IMEI")}',
                    f'  ICCID       : {_vget("ST_ICCID")}',
                    '',
                    '--- LOG COMPLETO (ultimas 80 lineas) ---',
                ]
                diag_parts += self.log_lines[-80:]
                diag_text = '\n'.join(diag_parts)
                try:
                    sg.clipboard_set(diag_text)
                    self._set_status(
                        'Estado copiado al portapapeles - pega en tu IA para diagnostico', ACCT2)
                except Exception:
                    sg.popup_scrolled(
                        diag_text, title='Estado Actual del Router',
                        size=(80, 35), background_color=BG1, text_color=TEXT,
                        font=('Consolas', 8),
                    )

            # -- Detectar Modem (Gateway por defecto) --------------------------
            elif event == 'BTN_DETECT_MODEM':
                def _find_modem():
                    try:
                        r = subprocess.run(
                            ['ipconfig'],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            creationflags=NO_WIN,
                        )
                        gw = ''
                        for line in r.stdout.splitlines():
                            lo = line.lower()
                            if 'puerta de enlace' in lo or 'default gateway' in lo:
                                parts = line.split(':')
                                if len(parts) >= 2:
                                    candidate = parts[-1].strip()
                                    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', candidate):
                                        gw = candidate
                                        break
                        # Fallback: route print
                        if not gw:
                            r2 = subprocess.run(
                                ['route', 'print', '0.0.0.0'],
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                creationflags=NO_WIN,
                            )
                            for line in r2.stdout.splitlines():
                                pts = line.split()
                                if len(pts) >= 3 and pts[0] == '0.0.0.0':
                                    c2 = pts[2]
                                    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', c2):
                                        gw = c2
                                        break
                        if not gw:
                            self.window.write_event_value('MODEM_FOUND', {
                                'ip': '', 'host': 'Gateway no encontrado', 'alive': False})
                            return
                        alive = ping_host(gw, timeout_ms=1200)
                        host  = resolve_hostname(gw) if alive else '--'
                        self.window.write_event_value('MODEM_FOUND', {
                            'ip': gw, 'host': host, 'alive': alive})
                    except Exception as exc:
                        self.window.write_event_value('MODEM_FOUND', {
                            'ip': '', 'host': str(exc), 'alive': False})

                self.window['MODEM_IP'].update('Buscando...', text_color=AMBER)
                self.window['MODEM_HOST'].update('')
                self.window['MODEM_PING'].update('')
                threading.Thread(target=_find_modem, daemon=True).start()

            elif event == 'MODEM_FOUND':
                d  = values[event]
                gw = d.get('ip', '')
                if gw:
                    alive = d.get('alive', False)
                    host  = d.get('host', '--')
                    self.window['MODEM_IP'].update(
                        gw, text_color=GREEN if alive else AMBER)
                    self.window['MODEM_HOST'].update(
                        f'({host})' if host and host != '--' else '')
                    self.window['MODEM_PING'].update(
                        '[OK] Responde' if alive else '[!] Sin respuesta',
                        text_color=GREEN if alive else AMBER)
                    # Auto-seleccionar en tabla si ya esta escaneada
                    for i, row in enumerate(self.devices_data):
                        if row[0] == gw:
                            self.window['DEV_TABLE'].update(select_rows=[i])
                            self.window['SEL_IP'].update(gw)
                            break
                    # Si no hay SSH activo, sugerir IP en el campo de conexion
                    if not self.connected:
                        self.window['IP'].update(gw)
                    self._log(f'Modem/Gateway detectado: {gw}  ({host})', 'OK')
                else:
                    self.window['MODEM_IP'].update('No detectado', text_color=RED)
                    self.window['MODEM_HOST'].update(d.get('host', ''))

            # -- Dispositivos --------------------------------------------------
            elif event == 'BTN_SCAN':

                if self._scanning:
                    continue
                self._scanning = True
                self.devices_data.clear()
                self.window['DEV_TABLE'].update(values=[])
                self.window['DEV_STATUS'].update('(SCAN) Escaneando red local... por favor espera')
                self.window['SEL_IP'].update('-')
                threading.Thread(
                    target=scan_network_thread,
                    args=(self.window,), daemon=True,
                ).start()

            elif event == 'SCAN_ROW':
                # Un dispositivo llego del hilo
                row = values[event]
                self.devices_data.append(row)
                self.window['DEV_TABLE'].update(values=self.devices_data)
                n = len(self.devices_data)
                self.window['DEV_STATUS'].update(
                    f'ðŸ” Encontrados {n} dispositivo(s)...')

            elif event == 'SCAN_DONE':
                self._scanning = False
                n = len(self.devices_data)
                msg = (f'[OK] Escaneo completado - {n} dispositivo(s) encontrado(s)'
                       if n else '[!] No se encontraron dispositivos (red vacia o sin ARP)')
                self.window['DEV_STATUS'].update(msg)

            elif event == 'DEV_TABLE':
                sel = values['DEV_TABLE']
                if sel:
                    ip = self.devices_data[sel[0]][0]
                    self.window['SEL_IP'].update(ip)

            elif event == 'BTN_BROWSER':
                sel = values['DEV_TABLE']
                if sel:
                    ip = self.devices_data[sel[0]][0]
                    webbrowser.open(f'http://{ip}')
                    self._log(f'Abriendo http://{ip} en el navegador', 'OK')
                else:
                    sg.popup_quick_message(
                        '  Selecciona un dispositivo de la tabla primero.  ',
                        background_color=BG3, text_color=AMBER,
                        auto_close_duration=2,
                    )

            elif event == 'BTN_CLR_DEV':
                self.devices_data.clear()
                self.window['DEV_TABLE'].update(values=[])
                self.window['DEV_STATUS'].update('')
                self.window['SEL_IP'].update('-')

        self.window.close()


# ==============================================================================
if __name__ == '__main__':
    app = RUT956ConfigGUI()
    app.run()
