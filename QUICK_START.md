# ⚡ QUICK START - RUT956 CONFIGURATOR

## En 3 pasos

### PASO 1: Instalar

**Windows:**
```bash
install.bat
```

**Mac/Linux:**
```bash
bash install.sh
# O manualmente:
pip install -r requirements.txt
```

### PASO 2: Ejecutar

```bash
python main.py
```

### PASO 3: Configurar

1. Ingresa IP del router: `192.168.1.1`
2. Usuario: `admin`
3. Contraseña: `tu_contraseña`
4. Click **Conectar**
5. Click en botones para configurar:
   - [SIM 4G]
   - [LAN]
   - [SNMP]
   - [ZeroTier] - Te pedirá Network ID
   - [Firewall]
   - [Validar]

---

## Qué hace cada botón

| Botón | Acción | Resultado |
|-------|--------|-----------|
| **SIM 4G** | Configura conexión celular | Telcel, 4G/LTE activo |
| **LAN** | Configura IP local | LAN: 192.168.10.1 |
| **SNMP** | Instala y configura SNMP | Puerto 161, community: public |
| **ZeroTier** | VPN privada | Red virtual, auto-IP |
| **Firewall** | Port forwarding | UDP 161 → 192.168.10.198 |
| **Validar** | Verifica todo | Muestra estado de cada servicio |

---

## Ejemplo de flujo real

```
┌─ python main.py
│
├─ Ingresa: IP=192.168.1.1, user=admin, pass=***
│
├─ Click Conectar
│  └─ [14:23:10] ✓ SSH conectado
│
├─ Click SIM 4G
│  └─ [14:23:15] ✓ SIM 4G CONFIGURADO - Señal: -65 dBm
│
├─ Click LAN
│  └─ [14:23:25] ✓ LAN CONFIGURADA: 192.168.10.1
│
├─ Click SNMP
│  └─ [14:23:35] ✓ SNMP CONFIGURADO (puerto 161, community: public)
│
├─ Click ZeroTier
│  ├─ [Popup] Ingresa Network ID: a581878f7df27537
│  └─ [14:23:45] ✓ ZEROTIER CONFIGURADO (Network ID: a581878f...)
│
├─ Click Firewall
│  └─ [14:23:55] ✓ FIREWALL CONFIGURADO (161 -> 192.168.10.198:161)
│
└─ Click Validar
   ├─ [14:24:00] ✓ Señal celular: -65 dBm
   ├─ [14:24:01] ✓ SNMP: Escuchando en puerto 161
   ├─ [14:24:02] ✓ ZeroTier: Online
   └─ [14:24:03] ✓✓✓ TODAS LAS CONFIGURACIONES COMPLETADAS ✓✓✓

TIEMPO TOTAL: ~2 minutos
```

---

## Pantalla esperada

```
┌──────────────────────────────────────────────────┐
│  🔧 RUT956 CONFIGURATOR v1.0            [X]     │
├──────────────────────────────────────────────────┤
│ IP Router:  [192.168.1.1____________]           │
│ Usuario:    [admin__________________]           │
│ Contraseña: [***************************]       │
│                                  [Conectar]     │
│ Estado: ✓ Conectado a 192.168.1.1               │
│────────────────────────────────────────────────  │
│ [SIM 4G] [LAN] [SNMP] [ZeroTier] [Firewall]     │
│ [Validar]                                       │
│────────────────────────────────────────────────  │
│ 📋 LOG EN TIEMPO REAL:                          │
│ [14:23:10] ✓ SSH conectado                      │
│ [14:23:12] === CONFIGURANDO SIM 4G ===          │
│ [14:23:20] ✓ SIM 4G CONFIGURADO                 │
│ [Más logs...]                                   │
│                                                  │
│ Progreso:                                        │
│ ████████████░░░░░░░░░░░░░░░░░░░ 40%            │
│ SIM 4G: Completado                              │
│                                                  │
│                                    [Salir]      │
└──────────────────────────────────────────────────┘
```

---

## ⚠️ Requisitos previos

- ✓ Router RUT956 encendido
- ✓ Acceso SSH habilitado (por defecto sí)
- ✓ Conocer IP, usuario y contraseña del router
- ✓ Python 3.6 o superior instalado
- ✓ Conexión a la red del router (LAN o WiFi)

---

## 🔐 Lo que NO hace

- ❌ No cambia contraseña del router
- ❌ No actualiza firmware
- ❌ No modifica WAN por defecto
- ❌ No borra datos existentes

---

## ✅ Lo que configura

- ✓ SIM 4G con APN Telcel
- ✓ LAN con IP 192.168.10.1
- ✓ SNMP en puerto 161
- ✓ ZeroTier VPN
- ✓ Port Forwarding UDP 161
- ✓ Validaciones

---

## 💡 Parámetros Modificables

Si necesitas cambiar valores predeterminados, edita `main.py`:

```python
# Línea ~155: SIM 4G
'apn': 'internet.telcel.com'
'username': 'telcel'
'password': 'telcel'

# Línea ~175: LAN
ip_lan = "192.168.10.1"

# Línea ~195: SNMP
port = "161"
community = "public"

# Línea ~230: Firewall
int_ip = "192.168.10.198"
ext_port = "161"
```

---

## 🚀 ¡Listo!

Ya está todo. Solo ejecuta:

```bash
python main.py
```

Y a configurar. ¡Disfruta! 🎉
