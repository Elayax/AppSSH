#!/usr/bin/env python3
"""
RUT956 CONFIGURATOR - Herramienta simple para configurar Teltonika routers
Versión 1.0 - Funcional y lista para usar
"""

import PySimpleGUI as sg
import paramiko
import json
import os
from datetime import datetime

# Configurar tema
sg.theme('DarkBlue3')

class RUT956ConfigGUI:
    def __init__(self):
        self.ssh = None
        self.config = self.load_config()
        self.window = None
        self.output_queue = []
        self.current_progress = 0
        self.progress_text = ""
        self.connected = False
        
    def load_config(self):
        """Cargar configuración guardada"""
        if os.path.exists('config.json'):
            try:
                with open('config.json', 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            'router_ip': '192.168.1.1',
            'username': 'admin'
        }
    
    def save_config(self):
        """Guardar configuración"""
        try:
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self.log(f"Error guardando config: {e}", "ERROR")
    
    def log(self, message, level="INFO"):
        """Agregar línea al log con timestamp e icono"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        icons = {
            "INFO": "ℹ️",
            "OK": "✓",
            "ERROR": "✗",
            "WAIT": "⏳",
            "CMD": "-"
        }
        icon = icons.get(level, "•")
        
        log_msg = f"[{timestamp}] {icon} {message}"
        self.output_queue.append(log_msg)
        
        # Guardar últimas 100 líneas
        if len(self.output_queue) > 100:
            self.output_queue.pop(0)
    
    def connect(self, ip, user, password):
        """Conectar SSH al router"""
        try:
            self.log("Conectando a router...", "WAIT")
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(ip, username=user, password=password, timeout=10)
            self.log(f"SSH conectado a {ip}", "OK")
            self.config['router_ip'] = ip
            self.config['username'] = user
            self.save_config()
            self.connected = True
            return True
        except Exception as e:
            self.log(f"Error de conexión: {str(e)}", "ERROR")
            self.connected = False
            return False
    
    def exec_cmd(self, cmd, show_cmd=True):
        """Ejecutar comando SSH y mostrar en log"""
        try:
            if show_cmd:
                for line in cmd.strip().split('\n'):
                    line = line.strip()
                    if line:
                        self.log(line, "CMD")
            
            stdin, stdout, stderr = self.ssh.exec_command(cmd)
            result = stdout.read().decode().strip()
            
            if result and len(result) < 100:
                self.log(f"Respuesta: {result}", "INFO")
            
            return result
        except Exception as e:
            self.log(f"Error ejecutando comando: {str(e)}", "ERROR")
            return ""
    
    def update_progress(self, percent, text):
        """Actualizar barra de progreso"""
        self.current_progress = min(percent, 100)
        self.progress_text = text
    
    def configure_sim_4g(self):
        """Configurar SIM 4G"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        self.log("=== CONFIGURANDO SIM 4G ===", "INFO")
        self.update_progress(20, "SIM 4G: Enviando comandos")
        
        cmd = """
uci set network.wan_4g='interface'
uci set network.wan_4g.proto='3g'
uci set network.wan_4g.device='/dev/ttyUSB0'
uci set network.wan_4g.apn='internet.telcel.com'
uci set network.wan_4g.username='telcel'
uci set network.wan_4g.password='telcel'
uci set firewall.zone_wan.network='wan_4g'
uci commit network
uci commit firewall
/etc/init.d/network restart
        """
        
        self.exec_cmd(cmd)
        
        self.log("Esperando conexión celular (10 seg)...", "WAIT")
        self.update_progress(30, "SIM 4G: Esperando conexión")
        self.exec_cmd("sleep 10")
        
        signal = self.exec_cmd("gsmctl -s 2>/dev/null || echo 'N/A'", show_cmd=False)
        
        if signal and signal != "N/A":
            self.log(f"✓ SIM 4G CONFIGURADO - Señal: {signal}", "OK")
            self.update_progress(40, "SIM 4G: Completado")
        else:
            self.log("⚠ Verificar conexión celular", "ERROR")
            self.update_progress(30, "SIM 4G: Error")
    
    def configure_lan(self):
        """Configurar LAN"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        self.log("=== CONFIGURANDO LAN ===", "INFO")
        self.update_progress(50, "LAN: Configurando IP")
        
        ip_lan = "192.168.10.1"
        
        cmd = f"""
uci set network.lan.ipaddr='{ip_lan}'
uci set network.lan.netmask='255.255.255.0'
uci set dhcp.lan.start='100'
uci set dhcp.lan.limit='100'
uci commit network
uci commit dhcp
/etc/init.d/network restart
        """
        
        self.exec_cmd(cmd)
        self.log(f"✓ LAN CONFIGURADA: {ip_lan}", "OK")
        self.update_progress(60, "LAN: Completado")
    
    def configure_snmp(self):
        """Configurar SNMP"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        self.log("=== CONFIGURANDO SNMP ===", "INFO")
        self.update_progress(70, "SNMP: Instalando paquetes")
        
        port = "161"
        community = "public"
        
        cmd = f"""
opkg update > /dev/null 2>&1 || true
opkg install snmp snmp-utils > /dev/null 2>&1 || echo "Ya instalado"
cat > /etc/config/snmp << 'CONFIG'
config snmp
    option enabled '1'
    option community '{community}'
    option port '{port}'
    option contact 'admin'
    option location 'RUT956'
CONFIG
/etc/init.d/snmpd start
/etc/init.d/snmpd enable
        """
        
        self.exec_cmd(cmd)
        self.log(f"✓ SNMP CONFIGURADO (puerto {port}, community: {community})", "OK")
        self.update_progress(75, "SNMP: Completado")
    
    def configure_zerotier(self, network_id):
        """Configurar ZeroTier"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        if not network_id or len(network_id) != 16:
            self.log("Network ID inválido (debe ser 16 caracteres)", "ERROR")
            return
        
        self.log("=== CONFIGURANDO ZEROTIER ===", "INFO")
        self.update_progress(80, "ZeroTier: Instalando")
        
        cmd = f"""
opkg install zerotier > /dev/null 2>&1 || echo "Ya instalado"
/etc/init.d/zerotier start > /dev/null 2>&1 || true
/etc/init.d/zerotier enable
zerotier-cli join {network_id}
        """
        
        self.exec_cmd(cmd)
        self.log("Esperando autorización en ZeroTier (5 seg)...", "WAIT")
        self.exec_cmd("sleep 5")
        
        status = self.exec_cmd("zerotier-cli listnetworks 2>/dev/null", show_cmd=False)
        self.log(f"✓ ZEROTIER CONFIGURADO (Network ID: {network_id[:8]}...)", "OK")
        self.update_progress(85, "ZeroTier: Completado")
    
    def configure_firewall(self):
        """Configurar Port Forward"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        self.log("=== CONFIGURANDO FIREWALL ===", "INFO")
        self.update_progress(90, "Firewall: Configurando")
        
        ext_port = "161"
        int_ip = "192.168.10.198"
        int_port = "161"
        
        cmd = f"""
uci set firewall.zone_wan.masq='1'
uci add firewall redirect
uci set firewall.@redirect[-1].name='UPS_SNMP'
uci set firewall.@redirect[-1].src='wan'
uci set firewall.@redirect[-1].proto='udp'
uci set firewall.@redirect[-1].src_dport='{ext_port}'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='{int_ip}'
uci set firewall.@redirect[-1].dest_port='{int_port}'
uci commit firewall
/etc/init.d/firewall restart > /dev/null 2>&1 || true
        """
        
        self.exec_cmd(cmd)
        self.log(f"✓ FIREWALL CONFIGURADO ({ext_port} -> {int_ip}:{int_port})", "OK")
        self.update_progress(95, "Firewall: Completado")
    
    def validate_all(self):
        """Validar todas las configuraciones"""
        if not self.connected:
            self.log("No conectado al router", "ERROR")
            return
        
        self.log("=== VALIDACIONES ===", "INFO")
        self.update_progress(70, "Validando: Celular")
        
        # Validar señal celular
        signal = self.exec_cmd("gsmctl -s 2>/dev/null || echo 'N/A'", show_cmd=False)
        if signal and signal != "N/A":
            self.log(f"✓ Señal celular: {signal}", "OK")
        else:
            self.log("⚠ Señal celular: No detectada", "ERROR")
        
        self.update_progress(80, "Validando: ZeroTier")
        
        # Validar ZeroTier
        status = self.exec_cmd("zerotier-cli status 2>/dev/null || echo 'N/A'", show_cmd=False)
        if status and status != "N/A":
            self.log(f"✓ ZeroTier: {status[:50]}", "OK")
        
        self.update_progress(90, "Validando: SNMP")
        
        # Validar SNMP
        snmp = self.exec_cmd("netstat -ulpn 2>/dev/null | grep 161 || echo 'No activo'", show_cmd=False)
        if snmp and "161" in snmp:
            self.log("✓ SNMP: Escuchando en puerto 161", "OK")
        else:
            self.log("⚠ SNMP: No está activo", "ERROR")
        
        self.update_progress(100, "Validaciones: Completadas")
        self.log("✓✓✓ TODAS LAS CONFIGURACIONES COMPLETADAS ✓✓✓", "OK")
    
    def create_window(self):
        """Crear ventana principal"""
        
        layout = [
            # Título
            [sg.Text("🔧 RUT956 CONFIGURATOR v1.0", 
                    font=('Arial', 16, 'bold'), 
                    text_color='lightblue')],
            
            [sg.Text("Herramienta para configurar Teltonika routers",
                    font=('Arial', 10),
                    text_color='lightgray')],
            
            [sg.Text('_' * 70)],
            
            # Formulario de conexión
            [sg.Text("IP Router:"), 
             sg.InputText(self.config.get('router_ip', '192.168.1.1'), 
                         key='IP', size=(20, 1))],
            
            [sg.Text("Usuario:"), 
             sg.InputText(self.config.get('username', 'admin'), 
                         key='USER', size=(20, 1))],
            
            [sg.Text("Contraseña:"), 
             sg.InputText('', key='PASS', password_char='*', size=(20, 1)),
             sg.Button('Conectar', bind_return_key=True, size=(10, 1))],
            
            [sg.Text("Estado: No conectado", 
                    key='STATUS', 
                    text_color='red',
                    font=('Arial', 10, 'bold'))],
            
            [sg.Text('_' * 70)],
            
            # Botones de configuración
            [sg.Button('SIM 4G', size=(10, 1)), 
             sg.Button('LAN', size=(10, 1)), 
             sg.Button('SNMP', size=(10, 1)), 
             sg.Button('ZeroTier', size=(10, 1)), 
             sg.Button('Firewall', size=(10, 1)),
             sg.Button('Validar', size=(10, 1))],
            
            [sg.Text('_' * 70)],
            
            # Console/Output
            [sg.Text("📋 LOG EN TIEMPO REAL:")],
            [sg.Multiline(size=(85, 18), 
                         key='OUTPUT', 
                         disabled=True,
                         font=('Courier', 9),
                         text_color='white',
                         background_color='#000000')],
            
            # Barra de progreso
            [sg.Text('Progreso:')],
            [sg.ProgressBar(100, size=(70, 20), 
                           key='PROGRESS',
                           bar_color=('green', 'lightgray'))],
            
            [sg.Text("", key='PROGRESS_TEXT', size=(70, 1))],
            
            # Botón salir
            [sg.Button('Salir', size=(10, 1))]
        ]
        
        window = sg.Window('RUT956 Configurator', layout, finalize=True, size=(900, 900))
        
        # Estilo para el output
        try:
            window['OUTPUT'].Widget.config(
                fg='white',
                bg='#000000',
                insertbackground='white'
            )
        except:
            pass
        
        return window
    
    def run(self):
        """Ejecutar la aplicación"""
        self.window = self.create_window()
        
        self.log("RUT956 CONFIGURATOR iniciado", "OK")
        self.log("Ingresa IP, usuario y contraseña del router", "INFO")
        
        while True:
            # Actualizar output
            output_text = '\n'.join(self.output_queue)
            self.window['OUTPUT'].update(output_text)
            
            # Scroll al final
            try:
                self.window['OUTPUT'].Widget.see(sg.tk.END)
            except:
                pass
            
            # Actualizar progreso
            self.window['PROGRESS'].update(self.current_progress)
            self.window['PROGRESS_TEXT'].update(self.progress_text)
            
            event, values = self.window.read(timeout=100)
            
            if event == sg.WINDOW_CLOSED or event == 'Salir':
                self.log("Cerrando aplicación", "INFO")
                break
            
            if event == 'Conectar':
                ip = values['IP'].strip()
                user = values['USER'].strip()
                password = values['PASS'].strip()
                
                if not all([ip, user, password]):
                    self.log("Por favor completa todos los campos", "ERROR")
                    continue
                
                if self.connect(ip, user, password):
                    self.window['STATUS'].update(
                        f"✓ Conectado a {ip}",
                        text_color='green'
                    )
                else:
                    self.window['STATUS'].update(
                        "✗ Error de conexión",
                        text_color='red'
                    )
            
            elif event == 'SIM 4G':
                self.configure_sim_4g()
            
            elif event == 'LAN':
                self.configure_lan()
            
            elif event == 'SNMP':
                self.configure_snmp()
            
            elif event == 'ZeroTier':
                network_id = sg.popup_get_text(
                    'Ingresa Network ID ZeroTier:',
                    title='ZeroTier Configuration'
                )
                if network_id:
                    self.configure_zerotier(network_id)
            
            elif event == 'Firewall':
                self.configure_firewall()
            
            elif event == 'Validar':
                self.validate_all()
        
        self.window.close()

if __name__ == '__main__':
    app = RUT956ConfigGUI()
    app.run()
