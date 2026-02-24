# 🔧 RUT956 CONFIGURATOR v1.0

**Herramienta simple para configurar routers Teltonika RUT956 remotamente**

## 🚀 Inicio Rápido (5 minutos)

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Ejecutar la herramienta

```bash
python main.py
```

### 3. Usar la interfaz

- **Ingresa IP del router**: `192.168.1.1` (o tu IP)
- **Usuario**: `admin`
- **Contraseña**: tu contraseña
- Click **Conectar**
- Click en cada botón para configurar:
  - **SIM 4G**: Configura conexión celular
  - **LAN**: Configura red local
  - **SNMP**: Instala y configura SNMP
  - **ZeroTier**: Instala VPN ZeroTier
  - **Firewall**: Configura Port Forwarding
  - **Validar**: Verifica todas las configuraciones

## ✨ Características

✅ **Console en tiempo real** - Ves cada comando ejecutándose
✅ **Barra de progreso** - Sabes dónde vas en cada momento
✅ **Log con timestamps** - Hora exacta de cada acción
✅ **Iconos codificados** - ✓ OK, ✗ Error, ⏳ Esperando, - CMD
✅ **Auto-guardado** - Guarda IP y usuario para próximas veces
✅ **Simple y directo** - 6 botones, sin complicaciones

## 🔧 Qué configura

### SIM 4G
- Proveedor: Telcel (internet.telcel.com)
- Configurable para otros proveedores
- Muestra señal celular en dBm

### LAN
- IP: 192.168.10.1
- DHCP: 100-200
- Netmask: 255.255.255.0

### SNMP
- Puerto: 161
- Community: public
- Versión: v2c

### ZeroTier
- Te pide Network ID (16 caracteres)
- Crea VPN privada
- Auto-asigna IP

### Firewall
- NAT habilitado
- Port Forward UDP 161
- IP interna: 192.168.10.198

## 📋 Requisitos

- Python 3.6+
- Acceso SSH al router RUT956
- Paramiko (SSH) - instala con requirements.txt
- PySimpleGUI (GUI) - instala con requirements.txt

## 📝 Ejemplo de uso

```
$ python main.py

[14:23:10] ✓ RUT956 CONFIGURATOR iniciado
[14:23:10] ℹ️ Ingresa IP, usuario y contraseña del router

[Ingresa datos y click Conectar]

[14:23:15] ⏳ Conectando a router...
[14:23:17] ✓ SSH conectado a 192.168.1.1

[Click en SIM 4G]

[14:23:18] === CONFIGURANDO SIM 4G ===
[14:23:18] - uci set network.wan_4g='interface'
[14:23:18] - uci set network.wan_4g.proto='3g'
[14:23:18] - uci set network.wan_4g.apn='internet.telcel.com'
[14:23:20] ✓ Comandos ejecutados
[14:23:20] ⏳ Esperando conexión celular (10 seg)...
[14:23:30] ✓ SIM 4G CONFIGURADO - Señal: -65 dBm

Progreso: ⬜⬜⬜⬜⬜ 40%    SIM 4G: Completado
```

## 🔐 Seguridad

- La contraseña NO se guarda (solo IP y usuario)
- Conexión SSH encriptada
- Comandos se ejecutan en el router directamente
- Logs guardados en memoria (últimas 100 líneas)

## 📁 Estructura del Proyecto

```
rut956-configurator/
├── main.py              # Aplicación principal
├── requirements.txt     # Dependencias Python
├── config.json          # Configuración guardada (auto-generado)
└── README.md           # Este archivo
```

## 🐛 Troubleshooting

**"Error de conexión"**
- Verifica que el router esté encendido
- Verifica IP, usuario y contraseña
- Prueba conectividad: `ping 192.168.1.1`

**"Command not found"**
- Algunos comandos pueden no estar disponibles en el firmware
- Intenta actualizar firmware del router

**"SNMP no se instala"**
- Verifica espacio disponible: `df -h`
- Intenta ejecutar nuevamente

## 📞 Soporte

Para problemas o preguntas, revisa:
- Los logs en la consola (útiles para debugging)
- El código en main.py (está bien comentado)
- La documentación de Teltonika RUT956

## 📄 Licencia

Herramienta de código abierto. Úsala libremente.

## 🎯 Versión

**v1.0** - Versión funcional inicial (Febrero 2026)

---

**¡Hecho! Tu herramienta está lista para usar.** 🚀
