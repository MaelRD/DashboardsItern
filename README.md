# Odoo Financial Intelligence: Scalable Liquidity Dashboard

> **Visibilidad financiera en tiempo real para tomadores de decisiones — impulsado por Odoo 18, Python y Dash.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Dash](https://img.shields.io/badge/Dash-2.17+-00A8E0?style=flat-square&logo=plotly&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-5.22+-3F4F75?style=flat-square&logo=plotly&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-2.2+-150458?style=flat-square&logo=pandas&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-FLATLY-7952B3?style=flat-square&logo=bootstrap&logoColor=white)

---

## Misión del Proyecto

La mayoría de los sistemas ERP almacenan datos financieros valiosos, pero los ocultan detrás de reportes lentos y módulos fragmentados. **Este proyecto resuelve eso.**

El Odoo Financial Intelligence Dashboard transforma datos transaccionales crudos de Odoo 18 en **insights financieros accionables y en tiempo real** para directores financieros, contralores y dueños de negocio. En lugar de esperar reportes mensuales, los tomadores de decisiones obtienen:

- Posición de caja en tiempo real a través de todas las cuentas bancarias y de efectivo
- Antigüedad de facturas vencidas segmentada en tramos de riesgo
- Proyecciones de runway de caja con simulación de escenarios
- Tendencias de velocidad de cobranza y riesgo de concentración por cliente

El resultado: **decisiones más rápidas, menor exposición y visibilidad financiera total — en una sola pantalla.**

---

## Arquitectura — Vista del Ingeniero

La aplicación sigue una **arquitectura estrictamente desacoplada en tres capas** que separa responsabilidades, aísla credenciales y permite reemplazar fuentes de datos sin tocar la lógica de negocio ni la interfaz.

```
+-------------------------------------------------------------------+
|                         ODOO 18 (ERP)                            |
|              account.move · account.payment · account.journal     |
+-----------------------------+-------------------------------------+
                              |  XML-RPC API (HTTPS)
                              v
+-------------------------------------------------------------------+
|                    CAPA 1 — EXTRACCION                            |
|                       extraction.py                               |
|  · OdooConnector: autenticacion XML-RPC en dos pasos, proxy       |
|    lazy, filtros de dominio aplicados del lado del servidor       |
|  · DemoDataGenerator: interfaz identica, seed=42, sin Odoo        |
|  · get_data_source(): factory unico — Odoo o Demo, con            |
|    fallback automatico graceful ante fallo de autenticacion       |
+-----------------------------+-------------------------------------+
                              |  dict[str, pd.DataFrame]
                              v
+-------------------------------------------------------------------+
|                  CAPA 2 — MOTOR ANALITICO                         |
|                        analytics.py                               |
|  · Staging layer: transformaciones vectorizadas con Pandas        |
|    (np.select), computadas una sola vez — callbacks solo leen     |
|  · Calculadores de KPI: DSO, Burn Rate, Cash Runway, Ratio        |
|    de Liquidez, Tasa de Cobranza                                  |
|  · Constructores de reporte: Aging, Comparativo Mensual,          |
|    Waterfall, Concentracion de Clientes, Velocidad DSO            |
|  · Motor What-if: proyeccion de flujo con banda de confianza      |
|    +-15% y cobrabilidad parametrizable                            |
+-----------------------------+-------------------------------------+
                              |  KPIs + DataFrames listos para graficar
                              v
+-------------------------------------------------------------------+
|                   CAPA 3 — INTERFAZ DE USUARIO                    |
|                        dashboard.py                               |
|  · Dash + Plotly: 7 graficas interactivas, 5 tarjetas KPI        |
|  · Tema Bootstrap FLATLY via dash-bootstrap-components           |
|  · Callback 1: ETL completo + graficas estaticas (carga inicial) |
|  · Callback 2: Solo What-if (cambio de slider — sin re-ETL)      |
|  · DataTable: facturas criticas con estilo condicional por riesgo |
+-------------------------------------------------------------------+
```

**Por que importa arquitectonicamente:**

| Preocupacion | Como se resuelve |
|---|---|
| **Seguridad** | Credenciales solo en `.env` — nunca en codigo, nunca en Capa 2 o 3 |
| **Escalabilidad** | Reemplazar Odoo por PostgreSQL directo solo requiere modificar la Capa 1 |
| **Rendimiento** | Filtros de dominio server-side en Odoo; staging computado una vez; callbacks de solo lectura |
| **Resiliencia** | Fallo de autenticacion activa Demo automaticamente; el dashboard nunca se cae |
| **Testabilidad** | `DemoDataGenerator` provee interfaz identica — pruebas unitarias sin instancia de Odoo |

---

## Caracteristicas Tecnicas Clave

### Pipeline de Datos Automatizado

Extraccion eficiente usando `execute_kw('search_read')` de Odoo con **filtros de dominio aplicados del lado del servidor** — solo los registros relevantes se transmiten, no el dataset completo.

```python
domain = [
    ["move_type", "in", ["out_invoice", "in_invoice"]],
    ["state",     "=",  "posted"],
    ["invoice_date", ">=", corte],   # el servidor filtra antes de transmitir
]
```

Modelos extraidos: `account.move`, `account.payment`, `account.journal`

La autenticacion en dos pasos maneja tanto UID numerico como credenciales email/login, compatible con despliegues Odoo SaaS y On-Premise.

---

### Motor Financiero

KPIs criticos computados desde la capa de staging:

| KPI | Formula | Umbrales |
|---|---|---|
| **DSO** (Days Sales Outstanding) | `(CxC pendiente / Facturacion anualizada) x 365` | Bien <45d · Alerta 45-60d · Critico >60d |
| **Burn Rate** | `Promedio mensual de pagos salientes (rolling 3 meses)` | — |
| **Cash Runway** | `Saldo liquido / Burn Rate` | Bien >6 meses · Alerta 3-6 meses · Critico <3 meses |
| **Ratio de Liquidez** | `Saldo liquido / Burn mensual` | Bien >1.5 · Alerta 1.0-1.5 · Critico <1.0 |
| **Tasa de Cobranza** | `Cobrado / Total facturado (ultimos 90 dias)` | — |

Tramos del reporte de antigüedad: **Por vencer · 1-30d · 31-60d · 61-90d · +90d**

Cada KPI retorna un codigo de color Bootstrap (`success` / `warning` / `danger`) para renderizado condicional directo en la interfaz — sin logica filtrada a la capa de UI.

---

### Simulaciones Predictivas — Motor What-If

El **slider de cobrabilidad** (0-100%) impulsa un modelo de proyeccion de caja en tiempo real sin volver a ejecutar el pipeline ETL:

```
Caja Proyectada = Saldo Actual
               + (CxC pendiente x % cobrabilidad)
               - (Gastos proyectados x dias)
```

La proyeccion incluye una **banda de confianza +-15%** (escenario optimista / pesimista) renderizada como grafica de area sombreada. Los tomadores de decisiones pueden ver inmediatamente:

- Cuantos meses de runway a diferentes tasas de cobranza
- El impacto en dolares de una caida del 10% en cobranza
- La tasa de cobranza minima para mantener posicion de caja positiva

---

## Stack Tecnologico

| Capa | Tecnologia | Proposito |
|---|---|---|
| **Fuente de datos** | Odoo 18 XML-RPC API | Datos financieros del ERP |
| **ETL** | `xmlrpc.client` (stdlib) | Conector Odoo sin dependencias externas |
| **Procesamiento** | **Pandas 2.2+** · NumPy | Staging, transformaciones, KPIs |
| **Framework web** | **Dash 2.17+** | UI reactiva con callbacks en Python |
| **Visualizacion** | **Plotly 5.22+** | 7 tipos de graficas interactivas |
| **Componentes UI** | **dash-bootstrap-components** (FLATLY) | Layout y estilos profesionales |
| **Configuracion** | **python-dotenv** | Gestion segura de credenciales |
| **Tipografia** | Inter · JetBrains Mono (Google Fonts) | Visualizacion legible de datos financieros |
| **Produccion** | Gunicorn | Servidor WSGI para despliegue |

---

## Instalacion y Configuracion

### Prerequisitos

- Python 3.10+
- Acceso a una instancia de Odoo 18 (o usar `DEMO_MODE=true` para desarrollo local)

### 1. Clonar y crear entorno virtual

```bash
git clone https://github.com/tu-usuario/odoo-financial-dashboard.git
cd odoo-financial-dashboard

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurar credenciales

```bash
cp .env.example .env
```

Editar `.env` con las credenciales de Odoo:

```dotenv
# Conexion a Odoo
ODOO_URL=https://tu-empresa.odoo.com
ODOO_DB=nombre-de-tu-base
ODOO_UID=tu@email.com             # email o UID numerico — ambos soportados
ODOO_PWD=tu_api_key_aqui          # Ajustes > Usuarios > Seguridad > Generar API Key

# true para desarrollo sin instancia de Odoo
DEMO_MODE=true
```

**Donde encontrar las credenciales en Odoo 18:**
- **ODOO_DB**: Ajustes > Activar modo desarrollador > visible en la URL
- **ODOO_UID**: Ajustes > Usuarios > tu usuario > ID en la barra de URL
- **ODOO_PWD**: Ajustes > Usuarios > tu usuario > pestana Seguridad > Generar clave API

### 3. Ejecutar el dashboard

```bash
python dashboard.py
```

Abrir `http://localhost:8050` en el navegador.

### 4. Despliegue en produccion (Gunicorn)

```bash
gunicorn dashboard:server -w 4 -b 0.0.0.0:8050 --timeout 120
```

---

## Seguridad

**Las credenciales nunca se almacenan en el codigo.** Todos los valores sensibles (`ODOO_URL`, `ODOO_DB`, `ODOO_UID`, `ODOO_PWD`) se cargan exclusivamente desde variables de entorno via `python-dotenv`.

```
.env          <- solo desarrollo local — NUNCA commitear este archivo
.env.example  <- plantilla segura commiteada al repositorio (sin valores reales)
.gitignore    <- .env esta listado aqui
```

En produccion (cloud / contenedores), inyectar las variables directamente en el entorno — sin archivo `.env` en el servidor:

```bash
# Docker
docker run -e ODOO_URL=... -e ODOO_PWD=... tu-imagen

# Railway / Render / Fly.io
# Configurar via panel de variables de entorno — sin archivo necesario
```

`OdooConnector` es la **unica capa** que lee credenciales. `analytics.py` y `dashboard.py` reciben DataFrames limpios — no tienen conocimiento de la fuente de datos, URL ni mecanismo de autenticacion.

---

## Por Que Importa

Este proyecto demuestra el stack completo de habilidades requeridas para **ingenieria de datos y desarrollo de software financiero a nivel empresarial**:

**Integracion de sistemas** — Conexion a un ERP real (Odoo 18) via su API XML-RPC, manejo de casos borde de autenticacion (email vs. UID numerico, SaaS vs. On-Premise) e implementacion de estrategias de fallback graceful ante fallos de conectividad.

**Arquitectura de software** — Un diseno deliberadamente desacoplado en tres capas donde cambiar la fuente de datos requiere tocar exactamente un archivo, y donde la capa de UI es completamente agnostica respecto al origen de los datos.

**Conocimiento del dominio financiero** — Implementacion correcta de KPIs a nivel de CFO (DSO, Burn Rate, Cash Runway, tramos de Aging) con umbrales estandar de la industria y modelos predictivos direccionalmente precisos.

**Desarrollo Python full-stack** — Desde llamadas XML-RPC crudas y transformaciones vectorizadas con Pandas hasta callbacks reactivos de Dash y una UI profesional con Bootstrap — toda la aplicacion es Python, sin JavaScript escrito a mano.

**Preparacion para produccion** — Logging estructurado, configuracion basada en entorno, despliegue WSGI y modo demo que hace el sistema demostrable sin dependencias externas.

> *La diferencia entre un script funcional y una aplicacion de datos lista para produccion es la arquitectura. Este proyecto cierra esa brecha.*

---

## Estructura del Proyecto

```
odoo-financial-dashboard/
├── extraction.py        # Capa 1: conector XML-RPC de Odoo + generador de datos demo
├── analytics.py         # Capa 2: motor de KPIs + constructores de reportes (staging)
├── dashboard.py         # Capa 3: app Dash, layout, callbacks, graficas
├── assets/
│   └── style.css        # CSS personalizado — overrides Bootstrap, tipografia, animaciones
├── requirements.txt     # Dependencias Python
├── .env.example         # Plantilla de credenciales (seguro para commitear)
├── .env                 # Credenciales reales — NUNCA commitear
└── README.md
```

---

<div align="center">

**Construido con precision. Desplegado con confianza.**

*Odoo Financial Intelligence Dashboard — Proyecto de Portafolio*

</div>
