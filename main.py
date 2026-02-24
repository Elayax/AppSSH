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

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PALETA â€” Dark Navy Elegante
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UTILIDADES DE RED
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CLASE PRINCIPAL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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
        # Comunicacion thread-safe para el popup de configuracion SIM

    # â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _log(self, msg: str, level: str = 'INFO') -> None:
        ts    = datetime.now().strftime('%H:%M:%S')
        icons = {'INFO': 'â€º', 'OK': 'âœ“', 'ERROR': 'âœ—', 'WAIT': '...', 'CMD': '$'}
        line  = f'[{ts}] {icons.get(level, "·")} {msg}'
        self.log_lines.append(line)
        if len(self.log_lines) > 300:
            self.log_lines.pop(0)

    # â”€â”€ SSH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def connect(self, ip: str, user: str, password: str) -> bool:
        try:
            self._log(f'Conectando a {ip}...', 'WAIT')
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(ip, username=user, password=password, timeout=10)
            self._log(f'SSH conectado a {ip}', 'OK')
            self.config['router_ip'] = ip
            self.config['username']  = user
            self._save_config()
            self.connected = True
            return True
        except Exception as e:
            self._log(f'Error de conexion: {e}', 'ERROR')
            self.connected = False
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
                self._log(f'â†’ {result}', 'INFO')
            return result
        except Exception as e:
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

    # â”€â”€ Configuraciones de Router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
            'run':     ('\u27f3', AMBER),
            'ok':      ('\u2713', GREEN),
            'warn':    ('\u26a0', '#e8a838'),
            'err':     ('\u2717', RED),
            'skip':    ('-', DIM),
        }
        # Secuencia de animacion para pasos activos
        SPIN = ['\u27f3', '\u21bb', '\u27f2', '\u21ba']

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
                bar = '\u2593' * bars + '\u2591' * (6 - bars)
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
                [sg.Text(f'SIM {n}  \u00b7  {slot}',
                         font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                         pad=(0, (6, 6)))],
                [sg.Text('APN:', size=(12, 1), text_color=TEXT),
                 sg.InputText('internet.itelcel.com', key=f'S{n}_APN', size=(24, 1))],
                [sg.Text('Usuario:', size=(12, 1), text_color=DIM),
                 sg.InputText('webgprs', key=f'S{n}_USER', size=(24, 1))],
                [sg.Text('Contrasena:', size=(12, 1), text_color=DIM),
                 sg.InputText('webgprs2002', key=f'S{n}_PASS',
                              size=(24, 1), password_char='\u25cf')],
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
            [sg.Text('\U0001f4e1  Configuracion SIM 4G  -  RUT956  (Dual SIM)',
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
                '\U0001f4a1  Si una SIM no esta presente el proceso la marcara como N/A '
                'y continuara con la otra.\n'
                '    Deja usuario/contrasena vacios si tu operador no los requiere.',
                text_color=DIM, font=('Segoe UI', 8), pad=(0, (2, 8)))],
            [sg.Push(),
             sg.Button('\u25b6  Iniciar configuracion', key='START', size=(22, 1),
                       button_color=(TEXT, '#186840'),
                       font=('Segoe UI', 10, 'bold')),
             sg.Button('\u2715  Cancelar', key='CANCEL', size=(13, 1),
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
                [sg.Text(f'SIM {n}  \u00b7  {slot}',
                         font=('Segoe UI', 10, 'bold'), text_color=ACCT2,
                         pad=(8, (8, 6)))],
                [sg.HorizontalSeparator(color=BG3, pad=((8, 8), 2))],
            ]
            for sid, slbl in STEPS:
                rows.append(_step_row(prefix, sid, slbl))
            rows += [
                [sg.HorizontalSeparator(color=BG3, pad=((8, 8), (6, 2)))],
                [sg.Text('\u23f3  En progreso...',
                         key=f'{prefix}_RESULT',
                         text_color=AMBER,
                         font=('Segoe UI', 9, 'bold'),
                         size=(38, 4), pad=(8, 2))],
            ]
            return sg.Column(rows, background_color=BG2,
                             pad=(4, 4), expand_x=True)

        prog_layout = [
            [sg.Text('\U0001f4e1  Configuracion SIM 4G  -  RUT956  (Dual SIM en paralelo)',
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
             sg.Button('\u2713  Cerrar', key='CLOSE', size=(14, 1),
                       button_color=(TEXT, '#186840'),
                       font=('Segoe UI', 10, 'bold'),
                       disabled=True, pad=(8, 6))],
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

        # -- Workers de configuracion -----------------------------------------
        restart_event = _threading.Event()

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

            # -- PASO 0: Diagnostico inicial ----------------------------------
            upd('diag', 'run', 'Verificando modem y SIM...')
            sim_st = self.exec_cmd(
                'gsmctl -z 2>/dev/null || echo "N/A"',
                show_cmd=False) or 'N/A'
            iccid  = self.exec_cmd(
                'gsmctl -J 2>/dev/null || echo "N/A"',
                show_cmd=False) or 'N/A'
            imei   = self.exec_cmd(
                'gsmctl -m 2>/dev/null || echo "N/A"',
                show_cmd=False) or 'N/A'

            upd('diag', 'run', f'Estado SIM: {sim_st.strip()}',
                f'ICCID:{iccid.strip()}  IMEI:{imei.strip()}')

            if 'not inserted' in sim_st.lower():
                upd('diag', 'err', f'SIM {sim_n}: no detectada fisicamente',
                    f'Estado:{sim_st.strip()}')
                for sid, _ in STEPS[1:]:
                    upd(sid, 'skip', 'N/A - SIM no presente')
                finish('err',
                       f'\u2717  SIM {sim_n}: no insertada\n'
                       'Verifica el contacto fisico de la SIM en el router.')
                if is_primary:
                    restart_event.set()
                return

            upd('diag', 'ok',
                f'SIM {sim_n} detectada  \u00b7  {sim_st.strip()}',
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
                f"uci set network.{slot}.area_type='wan'\n"
                f"uci set network.{slot}.metric='1'\n"
                f"uci set network.{slot}.mtu='1280'\n"
                f"uci set network.{slot}.delegate='0'\n"
                f"uci set network.{slot}.method='nat'\n"
            )
            if user:  cmd_uci += f"uci set network.{slot}.username='{user}'\n"
            if passw: cmd_uci += f"uci set network.{slot}.password='{passw}'\n"
            cmd_uci += 'uci commit network'
            out = self.exec_cmd(cmd_uci, show_cmd=False) or ''
            if 'error' in out.lower():
                upd('uci', 'warn', 'UCI aplicado con advertencias', out[:80])
            else:
                upd('uci', 'ok',
                    f'UCI OK  \u00b7  {slot}  APN={apn}  auto_apn=1')

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
                upd('restart', 'run', 'Reiniciando servicio de red...')
                self.exec_cmd('/etc/init.d/network restart', show_cmd=False)
                upd('restart', 'ok', 'Red reiniciada  \u00b7  esperando 5 s...')
                _time.sleep(5)
                restart_event.set()
            else:
                upd('restart', 'run', 'Esperando reinicio de red (SIM1)...')
                restart_event.wait(timeout=90)
                upd('restart', 'ok', 'Red reiniciada (por SIM1)')

            # -- PASO ifup ---------------------------------------------------
            upd('ifup', 'run', f'Forzando ifup {slot}...')
            self.exec_cmd(f'ifup {slot} 2>/dev/null || true', show_cmd=False)
            upd('ifup', 'ok', f'ifup {slot} ejecutado')

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
                s_sim  = self.exec_cmd(
                    'gsmctl -z 2>/dev/null || echo "N/A"',
                    show_cmd=False) or 'N/A'
                s_oper = self.exec_cmd(
                    'gsmctl -a 2>/dev/null || echo "N/A"',
                    show_cmd=False) or 'N/A'
                s_net  = self.exec_cmd(
                    'gsmctl -n 2>/dev/null || echo "N/A"',
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
                        f'{rnd_lbl}  \u2713 CONECTADO', detail)
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
                upd('final', 'ok',
                    '\u2713 Conectado a red celular', detail)
                finish('ok',
                       f'\u2713  SIM {sim_n} CONECTADA\n'
                       f'Operador: {s.get("oper","?")}  '
                       f'Red: {s.get("ntype","?")}  Banda: {band}\n'
                       f'Senal: {sig_bar}\n'
                       f'{sig_summary}\n'
                       f'IP: {s.get("ip") or "esperando..."}')
            elif ok_sim:
                upd('final', 'warn',
                    'SIM presente - sin datos aun', detail)
                finish('warn',
                       f'\u26a0  SIM {sim_n}: insertada, sin conexion\n'
                       f'APN: {apn}  Banda: {band}\n'
                       f'Senal: {sig_bar}\n'
                       'Verifica APN en WebUI y plan de datos')
            else:
                upd('final', 'err',
                    'Sin respuesta del modem', detail)
                finish('err',
                       f'\u2717  SIM {sim_n}: sin respuesta\n'
                       f'Estado: {s.get("sim","?")}  '
                       'Verifica fisicamente la SIM y antena')

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
                        '\u2713  Configuracion completada para ambas SIMs')
                    prog_win['CLOSE'].update(disabled=False)
                    self._set_status(
                        '\U0001f4e1 SIM 4G - Configuracion dual completa. '
                        'Revisa resultados en la ventana.', GREEN)

        prog_win.close()

    def configure_lan(self):
        if not self.connected:
            self._log('No conectado al router', 'ERROR'); return
        self._log('=== CONFIGURANDO LAN ===')
        self._set_progress(50, 'LAN: Configurando IP')
        ip_lan = '192.168.10.1'
        cmd = (
            f"uci set network.lan.ipaddr='{ip_lan}'\n"
            "uci set network.lan.netmask='255.255.255.0'\n"
            "uci set dhcp.lan.start='100'\n"
            "uci set dhcp.lan.limit='100'\n"
            "uci commit network\nuci commit dhcp\n"
            "/etc/init.d/network restart"
        )
        self.exec_cmd(cmd)
        self._log(f'LAN configurada: {ip_lan}', 'OK')
        self._set_progress(60, 'LAN: Completado âœ“')

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
        self._set_progress(75, 'SNMP: Completado âœ“')

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
        self._log('Esperando autorizacion ZeroTier (5 s)...', 'WAIT')
        self.exec_cmd('sleep 5')
        self._log(f'ZeroTier configurado (Network: {network_id[:8]}...)', 'OK')
        self._set_progress(85, 'ZeroTier: Completado âœ“')

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
        self._log('Firewall configurado (161 â†’ 192.168.10.198:161)', 'OK')
        self._set_progress(95, 'Firewall: Completado âœ“')
        self._set_status('Firewall configurado â€” port forward 161 â†’ 192.168.10.198:161', GREEN)

    # â”€â”€ Cambiar IP del router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def change_ip(self, new_ip: str, new_mask: str, new_gw: str) -> None:
        """Cambia la IP LAN del router via SSH."""
        if not self.connected:
            self._log('No conectado al router', 'ERROR')
            self._set_status('Cambio de IP cancelado â€” no hay conexion SSH activa', RED)
            return

        # Validar formato basico IP
        ip_re = re.compile(
            r'^(\d{1,3}\.){3}\d{1,3}$'
        )
        if not ip_re.match(new_ip):
            self._log(f'IP invalida: {new_ip}', 'ERROR')
            self._set_status(f'IP invalida: "{new_ip}" â€” usa formato X.X.X.X', RED)
            return

        self._set_status(f'Cambio de IP â€” aplicando nueva direccion {new_ip}...', ACCT2)
        self._log(f'=== CAMBIANDO IP DEL ROUTER â†’ {new_ip} ===')
        self._set_progress(10, 'Cambio IP: escribiendo UCI')

        cmd = (
            f"uci set network.lan.ipaddr='{new_ip}'\n"
            f"uci set network.lan.netmask='{new_mask}'\n"
        )
        if new_gw.strip():
            cmd += f"uci set network.lan.gateway='{new_gw}'\n"
        cmd += "uci commit network"

        self._set_status(f'Cambio de IP [1/2] â€” Guardando nueva IP {new_ip} en UCI...', ACCT2)
        self._set_progress(40, f'Cambio IP: guardando {new_ip}')
        self.exec_cmd(cmd)

        self._set_status(
            f'Cambio de IP [2/2] â€” Reiniciando red... âš  La conexion SSH se perdera.  '
            f'Reconectate usando la nueva IP: {new_ip}', AMBER
        )
        self._set_progress(70, 'Cambio IP: reiniciando red')
        self._log(
            f'âš  Reiniciando red â€” la sesion SSH se cerrara.  '
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

        self._set_progress(100, f'IP cambiada a {new_ip} âœ“')
        self._set_status(
            f'âœ“ IP cambiada a {new_ip}  |  Reconectate con esa IP en el campo superior', GREEN
        )
        self._log(f'IP cambiada a {new_ip}. Recuerda reconectarte.', 'OK')

        # Actualizar campo IP en la ventana (thread-safe via evento)
        if self.window:
            self.window.write_event_value('UPDATE_IP_FIELD', new_ip)

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

        self._set_progress(100, 'âœ“ Validaciones completadas')
        self._log('TODAS LAS CONFIGURACIONES COMPLETADAS', 'OK')

    # â”€â”€ Layout â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_layout(self) -> list:

        # â”€â”€ Tab 1: Configuracion Router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        btn_cfg  = dict(font=('Segoe UI', 9, 'bold'), pad=(4, 4))
        btn_blue = dict(button_color=(TEXT, '#16408a'), **btn_cfg)

        tab_router = [
            [sg.Text('Conexion SSH al Router',
                     font=('Segoe UI', 11, 'bold'), text_color=ACCT2, pad=(0, (10, 6)))],

            [sg.Text('IP Router:',  size=(12, 1), text_color=DIM),
             sg.InputText(self.config.get('router_ip', '192.168.1.1'),
                          key='IP', size=(20, 1)),
             sg.Text('Usuario:', size=(9, 1), text_color=DIM),
             sg.InputText(self.config.get('username', 'admin'),
                          key='USER', size=(16, 1))],

            [sg.Text('Contrasena:', size=(12, 1), text_color=DIM),
             sg.InputText('', key='PASS', password_char='â—', size=(20, 1)),
             sg.Button('âš¡ Conectar', key='BTN_CONNECT', size=(13, 1),
                       button_color=(TEXT, ACCENT), **btn_cfg)],

            [sg.Text('â— Desconectado', key='STATUS', text_color=RED,
                     font=('Segoe UI', 9, 'bold'), pad=(2, 6))],

            [sg.HorizontalSeparator(color=BG3, pad=(0, 4))],

            [sg.Text('Configuracion del Router',
                     font=('Segoe UI', 9, 'bold'), text_color=DIM, pad=(0, 4))],

            # Fila 1: acciones de red
            [sg.Button('ðŸ“¡ SIM 4G',   key='BTN_SIM',  size=(11, 1), **btn_blue),
             sg.Button('ðŸŒ LAN',      key='BTN_LAN',  size=(11, 1), **btn_blue),
             sg.Button('ðŸ“Š SNMP',     key='BTN_SNMP', size=(11, 1), **btn_blue),
             sg.Button('ðŸ”— ZeroTier', key='BTN_ZT',   size=(11, 1), **btn_blue),
             sg.Button('ðŸ”¥ Firewall', key='BTN_FW',   size=(11, 1), **btn_blue),
             sg.Button('âœ… Validar',  key='BTN_VAL',  size=(11, 1),
                       button_color=(TEXT, '#186840'), **btn_cfg)],

            # Fila 2: cambio de IP
            [sg.Button('ðŸ”„ Cambiar IP Router', key='BTN_CHANGE_IP', size=(20, 1),
                       button_color=(TEXT, '#2a5080'), **btn_cfg),
             sg.Text('Cambia la IP LAN del router y reconectate con la nueva direccion.',
                     text_color=DIM, font=('Segoe UI', 8))],

            [sg.HorizontalSeparator(color=BG3, pad=(0, 6))],

            [sg.Text('ðŸ“‹ Log en tiempo real',
                     font=('Segoe UI', 9, 'bold'), text_color=DIM)],

            [sg.Multiline(
                size=(90, 13), key='OUTPUT', disabled=True,
                font=('Consolas', 9), text_color='#7ab8f0',
                background_color=CLBG,
                expand_x=True, expand_y=True,
            )],

            [sg.Text('Progreso:', text_color=DIM, size=(9, 1)),
             sg.ProgressBar(100, size=(55, 14), key='PROGRESS',
                            bar_color=(ACCT2, BG2), expand_x=True),
             sg.Text('', key='PROGRESS_TEXT', size=(26, 1),
                     text_color=DIM, font=('Segoe UI', 8))],
        ]

        # â”€â”€ Tab 2: Dispositivos en Red â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        tab_devices = [
            [sg.Text('Dispositivos Ethernet en la Red Local',
                     font=('Segoe UI', 11, 'bold'), text_color=ACCT2, pad=(0, (10, 4))),
             sg.Push(),
             sg.Button('ðŸ” Escanear Red',    key='BTN_SCAN',    size=(16, 1),
                       button_color=(TEXT, ACCENT), **btn_cfg),
             sg.Button('ðŸŒ Abrir en Browser', key='BTN_BROWSER', size=(18, 1),
                       button_color=(TEXT, '#186840'), **btn_cfg),
             sg.Button('ðŸ—‘ Limpiar',          key='BTN_CLR_DEV', size=(10, 1),
                       button_color=(TEXT, '#4a1010'), **btn_cfg)],

            [sg.Text(
                'Lee la tabla ARP y hace ping a cada dispositivo para verificar su estado. '
                'Selecciona una fila y haz clic en "Abrir en Browser" para ir a su panel web.',
                text_color=DIM, font=('Segoe UI', 9), pad=(2, (0, 8)))],

            [sg.Table(
                values=[],
                headings=['  IP Address', '  MAC Address', '  Hostname', '  Tipo', '  Estado'],
                col_widths=[16, 22, 30, 11, 10],
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
                row_height=26,
                num_rows=18,
            )],

            [sg.Text('', key='DEV_STATUS', text_color=DIM,
                     font=('Segoe UI', 9), expand_x=True),
             sg.Text('Seleccionado:', text_color=DIM, font=('Segoe UI', 9)),
             sg.Text('â€”', key='SEL_IP', text_color=ACCT2,
                     font=('Segoe UI', 9, 'bold'), size=(18, 1))],
        ]

        # â”€â”€ Layout raiz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        layout = [
            # Header bar
            [sg.Text('âš™', font=('Segoe UI', 20), text_color=ACCT2, pad=((10, 4), 8)),
             sg.Text('RUT956  CONFIGURATOR',
                     font=('Segoe UI', 15, 'bold'), text_color=TEXT),
             sg.Text('v2.0', font=('Segoe UI', 9), text_color=DIM, pad=((4, 0), 0)),
             sg.Push(),
             sg.Button('âœ•  Salir', key='BTN_EXIT', size=(10, 1),
                       button_color=(TEXT, '#4a1010'),
                       font=('Segoe UI', 9, 'bold'), pad=(12, 8))],

            [sg.HorizontalSeparator(color=ACCENT, pad=(0, 0))],

            [sg.TabGroup(
                [[sg.Tab('  ðŸ”§ Configuracion Router  ', tab_router,
                         background_color=BG1),
                  sg.Tab('  ðŸ“¡ Dispositivos en Red   ', tab_devices,
                         background_color=BG1)]],
                tab_background_color=BG2,
                selected_background_color=BG1,
                selected_title_color=ACCT2,
                title_color=DIM,
                background_color=BG1,
                expand_x=True, expand_y=True,
                key='TABS',
            )],

            # â”€â”€ Barra de estado global (footer) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            [sg.HorizontalSeparator(color=BG3, pad=(0, 0))],
            [sg.Text('â—', key='STATUS_DOT', text_color=DIM,
                     font=('Segoe UI', 9), pad=((10, 4), 4)),
             sg.Text('Listo', key='STATUS_BAR', text_color=DIM,
                     font=('Segoe UI', 9), expand_x=True,
                     relief='flat'),
             sg.Text(
                 datetime.now().strftime('%H:%M'),
                 key='STATUS_TIME', text_color=DIM,
                 font=('Segoe UI', 8), pad=((0, 10), 4)
             )],
        ]
        return layout

    # â”€â”€ Ventana â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def create_window(self) -> sg.Window:
        try:
            import tkinter as tk
            r = tk.Tk(); r.withdraw()
            sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
            r.destroy()
            ww = min(1100, sw - 60)
            wh = min(800,  sh - 80)
        except Exception:
            ww, wh = 1050, 760

        window = sg.Window(
            'RUT956 Configurator v2.0',
            self._build_layout(),
            finalize=True,
            size=(ww, wh),
            resizable=True,
            location=(None, None),
            background_color=BG1,
        )

        # Ajuste extra del widget de log
        try:
            window['OUTPUT'].Widget.config(
                fg='#7ab8f0', bg=CLBG,
                insertbackground='#7ab8f0',
                relief='flat', bd=0,
            )
        except Exception:
            pass

        return window

    # â”€â”€ Bucle de eventos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def run(self) -> None:
        self.window = self.create_window()
        self._log('RUT956 CONFIGURATOR v2.0 iniciado', 'OK')
        self._log('Configura la conexion SSH en la pestana "Configuracion Router"', 'INFO')
        self._log('Usa la pestana "Dispositivos en Red" para escanear tu red local', 'INFO')

        while True:
            # Refrescar log
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

            # â”€â”€ Salir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if event in (sg.WINDOW_CLOSED, 'BTN_EXIT'):
                break

            # â”€â”€ SSH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif event == 'BTN_CONNECT':
                ip  = values['IP'].strip()
                usr = values['USER'].strip()
                pwd = values['PASS'].strip()
                if not all([ip, usr, pwd]):
                    self._log('Completa todos los campos de conexion', 'ERROR')
                    continue
                if self.connect(ip, usr, pwd):
                    self.window['STATUS'].update(f'â— Conectado a {ip}', text_color=GREEN)
                else:
                    self.window['STATUS'].update('â— Error de conexion', text_color=RED)

            elif event == 'BTN_SIM':
                # El wizard gestiona sus propios threads internamente;
                # se llama directamente en el hilo de UI para poder
                # abrir ventanas modales con event loops propios.
                self._sim_wizard()

            elif event == 'BTN_LAN':

                threading.Thread(target=self.configure_lan,     daemon=True).start()
            elif event == 'BTN_SNMP':
                threading.Thread(target=self.configure_snmp,    daemon=True).start()
            elif event == 'BTN_FW':
                threading.Thread(target=self.configure_firewall, daemon=True).start()
            elif event == 'BTN_VAL':
                threading.Thread(target=self.validate_all,      daemon=True).start()
            elif event == 'BTN_ZT':
                nid = sg.popup_get_text(
                    'Ingresa el Network ID de ZeroTier\n(exactamente 16 caracteres):',
                    title='ZeroTier â€” Network ID',
                    background_color=BG2, text_color=TEXT,
                )
                if nid:
                    threading.Thread(target=self.configure_zerotier,
                                     args=(nid,), daemon=True).start()

            elif event == 'BTN_CHANGE_IP':
                # Popup de cambio de IP con tres campos
                layout_ip = [
                    [sg.Text('Nueva IP del Router (LAN)',
                             font=('Segoe UI', 10, 'bold'), text_color=ACCT2)],
                    [sg.Text('IP actual:', size=(14, 1), text_color=DIM),
                     sg.Text(self.config.get('router_ip', 'â€”'),
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
                        'âš  La sesion SSH se cerrara al aplicar el cambio.\n'
                        '   Reconectate usando la nueva IP.',
                        text_color=AMBER, font=('Segoe UI', 8))],
                    [sg.Push(),
                     sg.Button('âœ“ Aplicar', key='APPLY', size=(10, 1),
                               button_color=(TEXT, '#186840')),
                     sg.Button('âœ• Cancelar', key='CANCEL', size=(10, 1),
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
                    f'â— Desconectado â€” reconectate con {new_ip}', text_color=AMBER)

            # â”€â”€ Dispositivos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif event == 'BTN_SCAN':
                if self._scanning:
                    continue
                self._scanning = True
                self.devices_data.clear()
                self.window['DEV_TABLE'].update(values=[])
                self.window['DEV_STATUS'].update('ðŸ” Escaneando red local... por favor espera')
                self.window['SEL_IP'].update('â€”')
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
                msg = (f'âœ“ Escaneo completado â€” {n} dispositivo(s) encontrado(s)'
                       if n else 'âš  No se encontraron dispositivos (red vacia o sin ARP)')
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
                self.window['SEL_IP'].update('â€”')

        self.window.close()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
if __name__ == '__main__':
    app = RUT956ConfigGUI()
    app.run()
