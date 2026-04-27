"""
data_engine.py — Capa ETL, Lógica de Negocio y Staging

Arquitectura: ETL desacoplado → Staging → Visualización
--------------------------------------------------------------
¿Por qué NO consultar el ORM de Odoo directamente desde los callbacks?

1. El ORM de Odoo agrega latencia por llamada — las consultas N+1 degradan
   la capacidad de respuesta de la UI bajo usuarios concurrentes.
   Un solo callback de Dash puede disparar 5+ lecturas ORM.

2. La lógica de negocio dentro de callbacks es no testeable y fuertemente
   acoplada. Separar responsabilidades permite probar las fórmulas KPI
   de forma independiente con pruebas unitarias.

3. La capa de Staging actúa como frontera de caché: cambiar la fuente de
   datos (Odoo RPC → PostgreSQL directo → CSV) solo requiere modificar
   load_raw_data(), sin tocar ninguna otra capa.

4. Las Flat Tables pre-unificadas eliminan el costo de JOIN en tiempo de
   ejecución durante las interacciones del usuario, crítico cuando el
   dataset abarca millones de registros en account.move.line.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

# ─── Semilla fija para reproducibilidad de los datos simulados ───────────────
random.seed(42)
np.random.seed(42)

TODAY = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)


# ══════════════════════════════════════════════════════════════════════════════
# 1. SIMULACIÓN DE DATOS — refleja fielmente los campos de los modelos Odoo 18
#    En producción: reemplazar el cuerpo de cada función con una llamada
#    xmlrpc/jsonrpc:
#    models.execute_kw(db, uid, pwd, 'account.move', 'search_read', [...])
# ══════════════════════════════════════════════════════════════════════════════

def _generate_account_move() -> pd.DataFrame:
    """
    Simula registros de account.move (facturas de cliente + facturas de proveedor).
    payment_date es un campo sintético — en Odoo se deriva desde la conciliación
    de account.move.line o desde los registros vinculados en account.payment.
    """
    records = []
    invoice_id = 1

    for i in range(180):
        date = TODAY - timedelta(days=i)

        # out_invoice — facturas de cliente (Cuentas por Cobrar)
        for _ in range(random.randint(1, 4)):
            amount   = round(random.uniform(5_000, 80_000), 2)
            state    = "posted" if i > 3 else random.choice(["posted", "draft"])
            days_due = random.choice([30, 45, 60])
            paid     = random.random() > 0.20

            records.append({
                "id":              invoice_id,
                "name":            f"INV/{date.year}/{invoice_id:05d}",
                "move_type":       "out_invoice",
                "state":           state,
                "invoice_date":    date,
                "date_maturity":   date + timedelta(days=days_due),
                "amount_total":    amount,
                "amount_residual": 0.0 if (paid and state == "posted") else amount,
                "payment_date":    date + timedelta(days=random.randint(5, days_due + 20))
                                   if paid else None,
            })
            invoice_id += 1

        # in_invoice — facturas de proveedor (Cuentas por Pagar / OPEX)
        for _ in range(random.randint(0, 2)):
            amount = round(random.uniform(1_000, 25_000), 2)
            records.append({
                "id":              invoice_id,
                "name":            f"BILL/{date.year}/{invoice_id:05d}",
                "move_type":       "in_invoice",
                "state":           "posted",
                "invoice_date":    date,
                "date_maturity":   date + timedelta(days=30),
                "amount_total":    amount,
                "amount_residual": round(amount * random.uniform(0, 0.3), 2),
                "payment_date":    date + timedelta(days=random.randint(15, 35)),
            })
            invoice_id += 1

    return pd.DataFrame(records)


def _generate_account_payment() -> pd.DataFrame:
    """
    Simula registros de account.payment.
    inbound = cobros de clientes, outbound = pagos a proveedores o nómina.
    journal_type refleja account.journal.type (bank | cash).
    """
    records = []
    for i in range(180):
        date = TODAY - timedelta(days=i)
        for _ in range(random.randint(1, 5)):
            ptype = random.choices(["inbound", "outbound"], weights=[0.55, 0.45])[0]
            records.append({
                "date":         date,
                "amount":       round(random.uniform(2_000, 60_000), 2),
                "payment_type": ptype,
                "journal_type": random.choice(["bank", "cash"]),
            })
    return pd.DataFrame(records)


def _generate_account_journal() -> pd.DataFrame:
    """
    Simula saldos de account.journal.
    En Odoo 18 el saldo calculado proviene de account.journal._get_journal_dashboard_data()
    o de la suma de account.move.line.balance filtrada por account_ids del diario.
    """
    return pd.DataFrame([
        {"id": 1, "name": "Banco Principal",  "type": "bank",  "balance": 850_000.0},
        {"id": 2, "name": "Banco Secundario", "type": "bank",  "balance": 320_000.0},
        {"id": 3, "name": "Caja Chica",       "type": "cash",  "balance":  15_000.0},
        {"id": 4, "name": "Caja Sucursal",    "type": "cash",  "balance":   8_500.0},
    ])


def load_raw_data() -> dict[str, pd.DataFrame]:
    """
    Punto de entrada del ETL. Reemplazar el contenido interno por llamadas
    reales a Odoo vía XMLRPC/JSONRPC sin romper el contrato con los callers.
    La firma pública permanece estable independientemente de la fuente.
    """
    return {
        "account_move":    _generate_account_move(),
        "account_payment": _generate_account_payment(),
        "account_journal": _generate_account_journal(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. LÓGICA DE NEGOCIO — Fórmulas de KPIs Financieros
# ══════════════════════════════════════════════════════════════════════════════

def calc_dso(moves: pd.DataFrame) -> float:
    """
    DSO (Days Sales Outstanding) = media(payment_date − invoice_date) para facturas cobradas.
    Solo son entradas válidas las out_invoice en estado 'posted' con payment_date confirmada.
    Las facturas en 'draft' sesgan el DSO hacia arriba — se excluyen explícitamente.
    """
    collected = moves[
        (moves["move_type"] == "out_invoice") &
        (moves["state"] == "posted") &
        (moves["payment_date"].notna())
    ].copy()

    collected["days_to_pay"] = (
        pd.to_datetime(collected["payment_date"]) -
        pd.to_datetime(collected["invoice_date"])
    ).dt.days

    return round(collected["days_to_pay"].mean(), 1)


def calc_burn_rate(moves: pd.DataFrame, months: int = 3) -> float:
    """
    Burn Rate mensual = promedio de OPEX mensual durante los últimos N meses.
    Usa in_invoice como proxy de gastos operativos.
    En producción, agregar asientos de nómina (account.move con diario de nómina)
    como segunda fuente para mayor precisión.
    """
    cutoff = TODAY - timedelta(days=30 * months)
    opex = moves[
        (moves["move_type"] == "in_invoice") &
        (moves["state"] == "posted") &
        (moves["invoice_date"] >= cutoff)
    ].copy()

    opex["month"] = pd.to_datetime(opex["invoice_date"]).dt.to_period("M")
    totales_mensuales = opex.groupby("month")["amount_total"].sum()

    return round(totales_mensuales.mean(), 2)


def calc_cash_runway(journals: pd.DataFrame, burn_rate: float) -> float:
    """
    Cash Runway (meses) = Saldo Líquido / Burn Rate mensual.
    Saldo líquido = suma de todos los saldos en diarios de tipo bank + cash.
    Retorna inf cuando el burn_rate es cero (empresa sin egresos registrados aún).
    """
    total_liquido = journals[journals["type"].isin(["bank", "cash"])]["balance"].sum()
    if burn_rate <= 0:
        return float("inf")
    return round(total_liquido / burn_rate, 1)


def calc_liquidity_ratio(moves: pd.DataFrame, journals: pd.DataFrame) -> float:
    """
    Ratio de Liquidez Inmediata = Activos Líquidos / Pasivos Corrientes.
    Pasivos corrientes = residuos de in_invoice vencidos (past date_maturity).
    Un ratio < 1.0 es alerta crítica: los pasivos superan los activos líquidos.
    """
    liquido = journals["balance"].sum()
    pasivos_vencidos = moves[
        (moves["move_type"] == "in_invoice") &
        (moves["state"] == "posted") &
        (moves["date_maturity"] < TODAY) &
        (moves["amount_residual"] > 0)
    ]["amount_residual"].sum()

    if pasivos_vencidos == 0:
        return 99.99
    return round(liquido / pasivos_vencidos, 2)


# ══════════════════════════════════════════════════════════════════════════════
# 3. CAPA DE STAGING — Tabla Plana (Flat Table)
#    Tabla única desnormalizada consultada por todos los componentes del dashboard.
#    Todas las columnas derivadas se pre-calculan aquí — nunca dentro de callbacks.
# ══════════════════════════════════════════════════════════════════════════════

def build_staging_table(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Produce una Flat Table desnormalizada optimizada para lecturas del dashboard.

    Decisiones de diseño:
    - Columnas de dimensión de fecha (year, month, week) habilitan GROUP BY
      por período sin parsing de strings en tiempo de ejecución en los callbacks.
    - Flags booleanos (is_collected, is_overdue) evitan lógica condicional repetida.
    - collected_amt pre-calcula el monto cobrado para facilitar agregaciones.
    """
    moves = raw["account_move"].copy()
    moves["invoice_date"]  = pd.to_datetime(moves["invoice_date"])
    moves["date_maturity"] = pd.to_datetime(moves["date_maturity"])
    moves["payment_date"]  = pd.to_datetime(moves["payment_date"])

    # Dimensiones de fecha para agrupaciones eficientes
    moves["year"]  = moves["invoice_date"].dt.year
    moves["month"] = moves["invoice_date"].dt.to_period("M").astype(str)
    moves["week"]  = moves["invoice_date"].dt.to_period("W").astype(str)

    # Flags de negocio derivados
    moves["is_collected"]  = moves["amount_residual"] == 0
    moves["is_overdue"]    = (moves["date_maturity"] < TODAY) & (moves["amount_residual"] > 0)
    moves["days_overdue"]  = (TODAY - moves["date_maturity"]).dt.days.clip(lower=0)
    moves["collected_amt"] = moves["is_collected"].map({True: 1, False: 0}) * moves["amount_total"]

    return moves


def build_cashflow_projection(
    payments: pd.DataFrame,
    staging: pd.DataFrame,
    current_balance: float,
    impayment_rate: float = 0.0,
    days: int = 90,
) -> pd.DataFrame:
    """
    Proyecta el saldo de caja diario para los próximos N días.

    impayment_rate (0.0–1.0): simula el % de cobros esperados que no llegarán.
    Se aplica solo a los ingresos — modela escenarios de riesgo crediticio desde el slider.

    Ingresos  = residuos de out_invoice pendientes con date_maturity en [HOY, HOY+N].
    Egresos   = residuos de in_invoice pendientes con date_maturity en [HOY, HOY+N].
    """
    fin_horizonte = TODAY + timedelta(days=days)

    cxc_pendiente = staging[
        (staging["move_type"] == "out_invoice") &
        (staging["state"] == "posted") &
        (staging["amount_residual"] > 0)
    ]
    cxp_pendiente = staging[
        (staging["move_type"] == "in_invoice") &
        (staging["state"] == "posted") &
        (staging["amount_residual"] > 0)
    ]

    # Diccionarios indexados por fecha para lookups O(1) en el bucle diario
    ingresos_diarios: dict  = {}
    egresos_diarios: dict   = {}

    for _, fila in cxc_pendiente.iterrows():
        d = fila["date_maturity"]
        if pd.Timestamp(TODAY) <= d <= pd.Timestamp(fin_horizonte):
            clave = d.date()
            ingresos_diarios[clave] = ingresos_diarios.get(clave, 0) + \
                fila["amount_residual"] * (1 - impayment_rate)

    for _, fila in cxp_pendiente.iterrows():
        d = fila["date_maturity"]
        if pd.Timestamp(TODAY) <= d <= pd.Timestamp(fin_horizonte):
            clave = d.date()
            egresos_diarios[clave] = egresos_diarios.get(clave, 0) + fila["amount_residual"]

    filas = []
    saldo = current_balance
    for d in pd.date_range(start=TODAY, periods=days, freq="D"):
        clave   = d.date()
        ingreso = ingresos_diarios.get(clave, 0)
        egreso  = egresos_diarios.get(clave, 0)
        saldo   = saldo + ingreso - egreso
        filas.append({"date": d, "inflow": ingreso, "outflow": egreso, "balance": saldo})

    return pd.DataFrame(filas)


def build_monthly_comparison(staging: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega los últimos 12 meses de out_invoice: facturado vs. cobrado.
    collection_rate alimenta el eje secundario del gráfico de comparación mensual.
    """
    salida = staging[staging["move_type"] == "out_invoice"].copy()
    mensual = salida.groupby("month").agg(
        invoiced=("amount_total",   "sum"),
        collected=("collected_amt", "sum"),
        count=("id",                "count"),
    ).reset_index()
    mensual["collection_rate"] = (mensual["collected"] / mensual["invoiced"] * 100).round(1)
    mensual["month_dt"] = pd.to_datetime(mensual["month"])
    return mensual.sort_values("month_dt").tail(12)


# ══════════════════════════════════════════════════════════════════════════════
# 4. API PÚBLICA — único punto de llamada desde app.py
# ══════════════════════════════════════════════════════════════════════════════

def get_dashboard_data(impayment_rate: float = 0.0) -> dict:
    """
    Orquesta el pipeline ETL completo para un ciclo de actualización del dashboard.

    app.py llama ÚNICAMENTE a esta función — nunca a los helpers individuales.
    Esta frontera garantiza que cambiar los internos del ETL nunca afecte la capa UI.

    Args:
        impayment_rate: valor 0.0–1.0 desde el slider de riesgo
                        (% de CxC que se espera que no sean cobradas)
    """
    raw      = load_raw_data()
    staging  = build_staging_table(raw)
    diarios  = raw["account_journal"]

    burn_rate   = calc_burn_rate(raw["account_move"])
    total_caja  = diarios["balance"].sum()

    facturas_cliente = staging[staging["move_type"] == "out_invoice"]
    vencidas         = staging[staging["is_overdue"]]

    return {
        "staging":  staging,
        "payments": raw["account_payment"],
        "journals": diarios,
        "kpis": {
            "dso":             calc_dso(raw["account_move"]),
            "burn_rate":       burn_rate,
            "cash_runway":     calc_cash_runway(diarios, burn_rate),
            "liquidity_ratio": calc_liquidity_ratio(raw["account_move"], diarios),
            "total_cash":      round(total_caja, 2),
            "total_ar":        round(facturas_cliente["amount_residual"].sum(), 2),
            "overdue_ar":      round(vencidas["amount_residual"].sum(), 2),
        },
        "cashflow_projection": build_cashflow_projection(
            raw["account_payment"], staging, total_caja, impayment_rate
        ),
        "monthly_comparison": build_monthly_comparison(staging),
    }
