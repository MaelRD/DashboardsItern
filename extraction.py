"""
extraction.py — Capa de Extracción (ETL)

Responsabilidad única: contacto con Odoo 18 vía protocolo XML-RPC estándar.
Ninguna otra capa conoce la URL, credenciales ni el protocolo de comunicación.

Arquitectura desacoplada — justificación:
- Cambiar de fuente (Odoo Cloud → Odoo On-Premise → PostgreSQL directo)
  solo requiere modificar esta capa. analytics.py y dashboard.py
  no se tocan por cambios de infraestructura.
- Las credenciales se aíslan aquí: analytics.py no sabe cómo se
  obtienen los datos, solo los recibe como DataFrames normalizados.
- DEMO_MODE permite desarrollar y testear el dashboard sin instancia
  de Odoo disponible, usando datos simulados con estructura idéntica
  a lo que retorna el XML-RPC real.
"""

import os
import xmlrpc.client
import pandas as pd
import numpy as np
import random
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# DEMO_MODE=true → datos simulados, no se necesita instancia de Odoo
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
TODAY     = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)


# ══════════════════════════════════════════════════════════════════════════════
# CONECTOR ODOO — XML-RPC real
# ══════════════════════════════════════════════════════════════════════════════

class OdooConnector:
    """
    Gestiona autenticación y extracción de datos desde Odoo 18 vía XML-RPC.

    Patrón de conexión lazy: el socket TCP no se abre hasta la primera llamada.
    En producción con múltiples workers gunicorn, crear una instancia por proceso
    (no compartir entre procesos — xmlrpc.client no es thread-safe por defecto).
    """

    def __init__(self):
        self.url  = os.environ["ODOO_URL"].rstrip("/")
        self.db   = os.environ["ODOO_DB"]
        self.pwd  = os.environ["ODOO_PWD"]
        raw_uid   = os.environ["ODOO_UID"]
        self._models: xmlrpc.client.ServerProxy | None = None

        # ODOO_UID puede ser numérico o email/login.
        # Si es email, se autentica contra /xmlrpc/2/common para obtener el UID numérico.
        if raw_uid.lstrip("-").isdigit():
            self.uid = int(raw_uid)
        else:
            self.uid = self._authenticate(login=raw_uid)

    def _authenticate(self, login: str) -> int:
        """
        Autenticación XML-RPC de dos pasos requerida por Odoo cuando se
        proporciona email/login en lugar de UID numérico.
        Endpoint /xmlrpc/2/common::authenticate retorna el UID numérico.

        Para Odoo SaaS (odoo.com): asegúrate de usar el nombre técnico de la DB
        visible en Ajustes → Activar modo desarrollador → URL de base de datos,
        y una API key generada en Ajustes → Usuarios → tu usuario → Seguridad.
        """
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        uid    = common.authenticate(self.db, login, self.pwd, {})
        if not uid:
            raise ConnectionError(
                f"Credenciales inválidas para '{login}' en DB '{self.db}'.\n"
                "Verifica: 1) DB name correcto  2) API key vigente  "
                "3) Usuario con acceso XML-RPC habilitado en Odoo."
            )
        logger.info(f"[Odoo] Autenticado como '{login}' → UID numérico: {uid}")
        return int(uid)

    @property
    def models(self) -> xmlrpc.client.ServerProxy:
        """Conexión lazy al endpoint de modelos — un solo proxy por instancia."""
        if self._models is None:
            self._models = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/object",
                allow_none=True,
            )
        return self._models

    def _search_read(
        self,
        model: str,
        domain: list,
        fields: list,
        limit: int = 5000,
    ) -> list[dict]:
        """
        Wrapper centralizado para execute_kw('search_read').
        Punto único de manejo de errores XML-RPC — evita try/except dispersos.
        """
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.pwd,
                model, "search_read", [domain],
                {"fields": fields, "limit": limit},
            )
        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo RPC Fault en {model}: {e.faultString}")
            return []
        except Exception as e:
            logger.error(f"Error de conexión en {model}: {e}")
            return []

    def get_account_moves(self, dias_atras: int = 365) -> pd.DataFrame:
        """
        Extrae facturas posted de los últimos N días.

        Filtro server-side vía domain de Odoo: el servidor filtra antes de
        transmitir — crítico para instancias con millones de asientos contables.
        Se excluyen 'draft' porque su amount_residual = amount_total distorsiona
        el cálculo de CxC real y el DSO hacia arriba.
        """
        corte = (TODAY - timedelta(days=dias_atras)).strftime("%Y-%m-%d")

        domain = [
            ["move_type", "in", ["out_invoice", "in_invoice"]],
            ["state",     "=",  "posted"],
            ["invoice_date", ">=", corte],
        ]
        fields = [
            "name", "move_type", "state",
            "invoice_date", "invoice_date_due",
            "amount_total", "amount_residual",
            "partner_id",
        ]

        raw = self._search_read("account.move", domain, fields)
        if not raw:
            logger.warning("account.move: sin registros.")
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        df = df.rename(columns={"invoice_date_due": "date_maturity"})
        df["invoice_date"]  = pd.to_datetime(df["invoice_date"],  errors="coerce")
        df["date_maturity"] = pd.to_datetime(df["date_maturity"], errors="coerce")

        # many2one en XML-RPC retorna [id, "Nombre"] — extraer nombre
        df["partner_name"] = df["partner_id"].apply(
            lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) > 1 else "Sin partner"
        )

        logger.info(f"[Odoo] account.move: {len(df)} facturas extraídas.")
        return df

    def get_account_payments(self, dias_atras: int = 365) -> pd.DataFrame:
        """
        Extrae pagos confirmados (state=posted) de los últimos N días.
        Filtro 'posted' excluye pagos en borrador que aún no impactan el saldo real.
        """
        corte = (TODAY - timedelta(days=dias_atras)).strftime("%Y-%m-%d")

        domain = [
            ["state",        "=",  "posted"],
            ["date",         ">=", corte],
            ["payment_type", "in", ["inbound", "outbound"]],
        ]
        fields = ["date", "amount", "payment_type", "journal_id", "partner_id"]

        raw = self._search_read("account.payment", domain, fields)
        if not raw:
            logger.warning("account.payment: sin registros.")
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["journal_tipo"] = df["journal_id"].apply(
            lambda x: x[1] if isinstance(x, (list, tuple)) else "desconocido"
        )

        logger.info(f"[Odoo] account.payment: {len(df)} pagos extraídos.")
        return df

    def get_journal_balances(self) -> pd.DataFrame:
        """
        Extrae saldos de diarios bank/cash.

        En Odoo 18, current_balance es un campo computado en account.journal
        que agrega el saldo de las líneas contables de ese diario.
        Se accede vía read() y no search_read() porque los campos computados
        no se serializan por defecto en search_read.
        Si current_balance falla (instancias viejas o permisos), retorna 0.
        """
        domain = [["type", "in", ["bank", "cash"]]]
        fields_base = ["id", "name", "type"]

        raw = self._search_read("account.journal", domain, fields_base, limit=50)
        if not raw:
            return pd.DataFrame()

        journal_ids = [r["id"] for r in raw]

        try:
            balances = self.models.execute_kw(
                self.db, self.uid, self.pwd,
                "account.journal", "read",
                [journal_ids],
                {"fields": ["id", "name", "type", "current_balance"]},
            )
            df = pd.DataFrame(balances)
            df["current_balance"] = pd.to_numeric(df["current_balance"], errors="coerce").fillna(0)
        except Exception:
            logger.warning("[Odoo] current_balance no disponible — saldo fijo en 0.")
            df = pd.DataFrame(raw)
            df["current_balance"] = 0.0

        logger.info(f"[Odoo] account.journal: {len(df)} diarios extraídos.")
        return df

    def load_all(self) -> dict[str, pd.DataFrame]:
        """Punto de entrada único del ETL — retorna dict normalizado."""
        return {
            "moves":    self.get_account_moves(),
            "payments": self.get_account_payments(),
            "journals": self.get_journal_balances(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# GENERADOR DE DATOS DEMO — estructura idéntica al XML-RPC real
# ══════════════════════════════════════════════════════════════════════════════

class DemoDataGenerator:
    """
    Genera datos simulados con la misma estructura que retorna OdooConnector.
    Semilla fija (42) garantiza reproducibilidad entre recargas del dashboard.
    En DEMO_MODE=false, este generador nunca se instancia.
    """

    PARTNERS = [
        "Acme Corp SA",         "Tecnologías XYZ",    "Distribuidora Norte",
        "Servicios Delta",      "Global Import SA",   "Industrias Beta SC",
        "Comercial Sur",        "Grupo Innovación",   "Logística Express",
        "Manufacturas Omega",
    ]

    def __init__(self):
        random.seed(42)
        np.random.seed(42)

    def get_account_moves(self, dias_atras: int = 365) -> pd.DataFrame:
        """Simula account.move con distribución realista de pagos y vencimientos."""
        registros  = []
        invoice_id = 1

        for i in range(min(dias_atras, 180)):
            fecha = TODAY - timedelta(days=i)

            # Facturas de cliente (out_invoice)
            for _ in range(random.randint(1, 4)):
                monto   = round(random.uniform(5_000, 120_000), 2)
                dias_v  = random.choice([30, 45, 60])
                cobrado = random.random() > 0.22

                registros.append({
                    "id":              invoice_id,
                    "name":            f"INV/{fecha.year}/{invoice_id:05d}",
                    "move_type":       "out_invoice",
                    "state":           "posted",
                    "invoice_date":    fecha,
                    "date_maturity":   fecha + timedelta(days=dias_v),
                    "amount_total":    monto,
                    "amount_residual": 0.0 if cobrado else monto,
                    "partner_name":    random.choice(self.PARTNERS),
                })
                invoice_id += 1

            # Facturas de proveedor (in_invoice)
            for _ in range(random.randint(0, 2)):
                monto = round(random.uniform(2_000, 45_000), 2)
                registros.append({
                    "id":              invoice_id,
                    "name":            f"BILL/{fecha.year}/{invoice_id:05d}",
                    "move_type":       "in_invoice",
                    "state":           "posted",
                    "invoice_date":    fecha,
                    "date_maturity":   fecha + timedelta(days=30),
                    "amount_total":    monto,
                    "amount_residual": round(monto * random.uniform(0, 0.4), 2),
                    "partner_name":    random.choice(self.PARTNERS),
                })
                invoice_id += 1

        df = pd.DataFrame(registros)
        if not df.empty:
            df["invoice_date"]  = pd.to_datetime(df["invoice_date"])
            df["date_maturity"] = pd.to_datetime(df["date_maturity"])
        return df

    def get_account_payments(self, dias_atras: int = 365) -> pd.DataFrame:
        """Simula account.payment con proporción realista inbound/outbound."""
        registros = []
        for i in range(min(dias_atras, 180)):
            fecha = TODAY - timedelta(days=i)
            for _ in range(random.randint(2, 6)):
                tipo = random.choices(["inbound", "outbound"], weights=[0.55, 0.45])[0]
                registros.append({
                    "date":         fecha,
                    "amount":       round(random.uniform(3_000, 85_000), 2),
                    "payment_type": tipo,
                    "journal_tipo": random.choice(["bank", "cash"]),
                })
        df = pd.DataFrame(registros)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def get_journal_balances(self) -> pd.DataFrame:
        """Simula account.journal con saldos típicos de empresa mediana."""
        return pd.DataFrame([
            {"id": 1, "name": "Banco Principal BBVA",   "type": "bank",  "current_balance": 1_250_000.0},
            {"id": 2, "name": "Banco Secundario HSBC",  "type": "bank",  "current_balance":   480_000.0},
            {"id": 3, "name": "Caja General",            "type": "cash",  "current_balance":    28_500.0},
            {"id": 4, "name": "Caja Sucursal Norte",     "type": "cash",  "current_balance":    12_000.0},
        ])

    def load_all(self) -> dict[str, pd.DataFrame]:
        return {
            "moves":    self.get_account_moves(),
            "payments": self.get_account_payments(),
            "journals": self.get_journal_balances(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY — punto de decisión único: Odoo real vs Demo
# ══════════════════════════════════════════════════════════════════════════════

def get_data_source() -> OdooConnector | DemoDataGenerator:
    """
    Retorna la fuente de datos correcta según DEMO_MODE.
    dashboard.py llama solo esta función — nunca instancia conectores directamente.
    Cambiar de Demo a producción = cambiar DEMO_MODE=false en .env.

    Si DEMO_MODE=false pero la conexión falla, retorna DemoDataGenerator con
    advertencia — el dashboard sigue funcionando mientras se corrigen credenciales.
    """
    if DEMO_MODE:
        logger.info("DEMO_MODE activo — usando datos simulados.")
        return DemoDataGenerator()

    logger.info("Conectando a Odoo vía XML-RPC...")
    try:
        conector = OdooConnector()
        return conector
    except Exception as e:
        logger.error(
            f"[Odoo] Conexión fallida — activando DEMO_MODE automáticamente.\n"
            f"Causa: {e}\n"
            f"Verifica tu .env: ODOO_URL, ODOO_DB, ODOO_UID (email o número), ODOO_PWD (API key)."
        )
        return DemoDataGenerator()
