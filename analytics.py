"""
analytics.py — Capa de Analítica y KPIs Financieros

Responsabilidad única: transformar DataFrames crudos en métricas de negocio.
Sin UI, sin acceso a datos, sin dependencias de Odoo o Dash.

Arquitectura desacoplada — justificación:
- Las fórmulas financieras son agnósticas a la fuente. analytics.py funciona
  igual con datos de Odoo, CSV o cualquier origen con el mismo esquema.
- La lógica de negocio es testeable de forma aislada sin levantar Dash
  ni una instancia de Odoo.
- Pre-calcular todos los derivados en _build_staging() garantiza que los
  callbacks de Dash solo lean — nunca transformen datos en tiempo real.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

TODAY = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

# ── Umbrales de alerta — centralizados para fácil calibración ─────────────────
UMBRAL_DSO_WARN    = 45
UMBRAL_DSO_CRIT    = 60
UMBRAL_RUNWAY_WARN = 6
UMBRAL_RUNWAY_CRIT = 3
UMBRAL_LIQ_WARN    = 1.5
UMBRAL_LIQ_CRIT    = 1.0


class FinancialAnalytics:
    """
    Motor de análisis financiero sobre datos extraídos de Odoo.
    Flujo: extraction.py → dict[str, DataFrame] → FinancialAnalytics → KPIs + Tablas.
    La Staging Table se construye una sola vez al inicializar la instancia.
    """

    def __init__(self, raw: dict[str, pd.DataFrame]):
        self.moves    = raw.get("moves",    pd.DataFrame())
        self.payments = raw.get("payments", pd.DataFrame())
        self.journals = raw.get("journals", pd.DataFrame())
        self.staging  = self._build_staging()

    # ══════════════════════════════════════════════════════════════════════════
    # STAGING TABLE
    # ══════════════════════════════════════════════════════════════════════════

    def _build_staging(self) -> pd.DataFrame:
        """
        Flat Table desnormalizada — fuente única de verdad para todos los cálculos.

        Decisiones de diseño:
        - Dimensiones de fecha pre-calculadas: evitan parseo en cada GROUP BY.
        - Flags booleanos vectorizados: sin apply(), operan sobre arrays NumPy.
        - collected_amt: SUM directo sin IF en agrupadores mensuales.
        - nivel_riesgo con np.select: más rápido que pd.cut en DataFrames grandes
          porque opera en arrays en lugar de Series categóricas.
        """
        if self.moves.empty:
            return pd.DataFrame()

        df = self.moves.copy()
        df["invoice_date"]  = pd.to_datetime(df["invoice_date"],  errors="coerce")
        df["date_maturity"] = pd.to_datetime(df["date_maturity"], errors="coerce")

        hoy = pd.Timestamp(TODAY)

        # Dimensiones temporales
        df["year"]     = df["invoice_date"].dt.year
        df["month"]    = df["invoice_date"].dt.to_period("M").astype(str)
        df["quarter"]  = df["invoice_date"].dt.to_period("Q").astype(str)
        df["week_num"] = df["invoice_date"].dt.isocalendar().week.astype(int)

        # Flags de estado financiero (completamente vectorizados)
        df["is_collected"]  = df["amount_residual"] == 0
        df["is_overdue"]    = (df["date_maturity"] < hoy) & (df["amount_residual"] > 0)
        df["days_overdue"]  = (hoy - df["date_maturity"]).dt.days.clip(lower=0)
        df["collected_amt"] = df["is_collected"].astype(int) * df["amount_total"]
        df["pending_amt"]   = df["amount_total"] - df["collected_amt"]

        # Clasificación de riesgo crediticio (4 niveles)
        df["nivel_riesgo"] = np.select(
            condlist=[
                df["days_overdue"] == 0,
                df["days_overdue"] <= 30,
                df["days_overdue"] <= 60,
                df["days_overdue"] >  60,
            ],
            choicelist=["Al corriente", "Riesgo bajo", "Riesgo medio", "Riesgo crítico"],
            default="Sin vencimiento",
        )

        # Tramo de aging pre-calculado para agrupaciones directas
        bins   = [-1, 0, 30, 60, 90, float("inf")]
        labels = ["Por vencer", "1–30 días", "31–60 días", "61–90 días", "+90 días"]
        df["tramo_aging"] = pd.cut(df["days_overdue"], bins=bins, labels=labels)

        return df

    # ══════════════════════════════════════════════════════════════════════════
    # KPIs FINANCIEROS
    # ══════════════════════════════════════════════════════════════════════════

    def calc_dso(self) -> float:
        """
        DSO = media(date_maturity − invoice_date) para out_invoices cobradas.
        Usa date_maturity como proxy de fecha de pago cuando payment_date
        no está disponible en el campo directo del asiento.
        """
        if self.staging.empty:
            return 0.0

        cobradas = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            self.staging["is_collected"]
        ].copy()

        if cobradas.empty:
            return 0.0

        cobradas["dias_cobro"] = (
            cobradas["date_maturity"] - cobradas["invoice_date"]
        ).dt.days.clip(lower=0)

        return round(float(cobradas["dias_cobro"].mean()), 1)

    def calc_burn_rate(self, meses: int = 3) -> float:
        """
        Burn Rate = promedio mensual de OPEX en los últimos N meses.
        Fuente: in_invoice posted — facturas de proveedor confirmadas.
        """
        if self.staging.empty:
            return 0.0

        corte = pd.Timestamp(TODAY - timedelta(days=30 * meses))
        opex  = self.staging[
            (self.staging["move_type"] == "in_invoice") &
            (self.staging["invoice_date"] >= corte)
        ].copy()

        if opex.empty:
            return 0.0

        opex["mes"] = opex["invoice_date"].dt.to_period("M")
        return round(float(opex.groupby("mes")["amount_total"].sum().mean()), 2)

    def get_liquid_balance(self) -> float:
        """Saldo líquido = suma de current_balance en diarios bank + cash."""
        if self.journals.empty or "current_balance" not in self.journals.columns:
            return 0.0
        return float(self.journals[
            self.journals["type"].isin(["bank", "cash"])
        ]["current_balance"].sum())

    def calc_cash_runway(self, burn_rate: float | None = None) -> float:
        """
        Cash Runway = Saldo Líquido / Burn Rate mensual.
        Acepta burn_rate externo para el simulador what-if sin recalcular.
        """
        br = burn_rate if burn_rate is not None else self.calc_burn_rate()
        if br <= 0:
            return float("inf")
        return round(self.get_liquid_balance() / br, 1)

    def calc_liquidity_ratio(self) -> float:
        """Ratio de Liquidez = Activo Líquido / Pasivo Corriente vencido."""
        if self.staging.empty:
            return 0.0
        liquido = self.get_liquid_balance()
        pasivos = float(self.staging[
            (self.staging["move_type"] == "in_invoice") &
            self.staging["is_overdue"]
        ]["amount_residual"].sum())
        if pasivos == 0:
            return 99.0
        return round(liquido / pasivos, 2)

    def calc_collection_rate(self) -> float:
        """Tasa global de cobro = cobrado / facturado en out_invoices del período."""
        if self.staging.empty:
            return 0.0
        out = self.staging[self.staging["move_type"] == "out_invoice"]
        total    = float(out["amount_total"].sum())
        cobrado  = float(out["collected_amt"].sum())
        if total == 0:
            return 0.0
        return round(cobrado / total * 100, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # REPORTES PARA VISUALIZACIÓN
    # ══════════════════════════════════════════════════════════════════════════

    def build_aging_report(self) -> pd.DataFrame:
        """
        Aging Report estándar contable de CxC segmentado por tramo de antigüedad.
        Tramos: Por vencer / 1-30 / 31-60 / 61-90 / +90 días.
        """
        if self.staging.empty:
            return pd.DataFrame()

        cxc = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            (self.staging["amount_residual"] > 0)
        ]

        if cxc.empty:
            return pd.DataFrame()

        reporte = cxc.groupby("tramo_aging", observed=True).agg(
            monto=("amount_residual", "sum"),
            facturas=("id",           "count"),
        ).reset_index().rename(columns={"tramo_aging": "tramo"})

        total = reporte["monto"].sum()
        reporte["porcentaje"] = (reporte["monto"] / total * 100).round(1) if total > 0 else 0.0

        return reporte

    def build_cashflow_projection(
        self,
        cobrabilidad: float = 1.0,
        dias: int = 90,
    ) -> pd.DataFrame:
        """
        Proyecta saldo diario de caja para los próximos N días con bandas de escenario.

        cobrabilidad (0.0–1.0): % de CxC que efectivamente se cobrará (slider what-if).
        Además del escenario elegido, calcula banda optimista (+15%) y pesimista (-15%)
        para dar contexto visual de incertidumbre en el gráfico de área.

        Diseño conservador: egresos al 100%, ingresos × cobrabilidad.
        Complejidad O(n+d): índice por fecha antes del bucle diario.
        """
        if self.staging.empty:
            return pd.DataFrame()

        hoy = pd.Timestamp(TODAY)
        fin = pd.Timestamp(TODAY + timedelta(days=dias))

        cxc = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            (self.staging["amount_residual"] > 0) &
            (self.staging["date_maturity"] >= hoy) &
            (self.staging["date_maturity"] <= fin)
        ]
        cxp = self.staging[
            (self.staging["move_type"] == "in_invoice") &
            (self.staging["amount_residual"] > 0) &
            (self.staging["date_maturity"] >= hoy) &
            (self.staging["date_maturity"] <= fin)
        ]

        base_ingresos = cxc.groupby("date_maturity")["amount_residual"].sum()
        idx_ingresos  = base_ingresos * cobrabilidad
        idx_optimista = base_ingresos * min(cobrabilidad * 1.15, 1.0)
        idx_pesimista = base_ingresos * max(cobrabilidad * 0.85, 0.0)
        idx_egresos   = cxp.groupby("date_maturity")["amount_residual"].sum()

        filas         = []
        saldo         = self.get_liquid_balance()
        saldo_opt     = saldo
        saldo_pes     = saldo

        for d in pd.date_range(start=TODAY, periods=dias, freq="D"):
            ts      = pd.Timestamp(d)
            ingreso = float(idx_ingresos.get(ts, 0))
            egreso  = float(idx_egresos.get(ts, 0))
            saldo       = saldo     + ingreso                              - egreso
            saldo_opt   = saldo_opt + float(idx_optimista.get(ts, 0))     - egreso
            saldo_pes   = saldo_pes + float(idx_pesimista.get(ts, 0))     - egreso
            filas.append({
                "fecha":       d,
                "ingreso":     ingreso,
                "egreso":      egreso,
                "saldo":       saldo,
                "saldo_opt":   saldo_opt,
                "saldo_pes":   saldo_pes,
            })

        return pd.DataFrame(filas)

    def build_monthly_comparison(self) -> pd.DataFrame:
        """Últimos 12 meses: facturado vs. cobrado con tasa de cobro."""
        if self.staging.empty:
            return pd.DataFrame()

        out = self.staging[self.staging["move_type"] == "out_invoice"].copy()
        mensual = out.groupby("month").agg(
            facturado=("amount_total",   "sum"),
            cobrado=("collected_amt",    "sum"),
            n_facturas=("id",            "count"),
        ).reset_index()
        mensual["tasa_cobro"] = (mensual["cobrado"] / mensual["facturado"] * 100).round(1).fillna(0)
        mensual["month_dt"]   = pd.to_datetime(mensual["month"])
        return mensual.sort_values("month_dt").tail(12)

    def build_client_concentration(self, top_n: int = 8) -> pd.DataFrame:
        """
        Concentración de CxC pendiente por cliente — para gráfico de pastel.
        Agrupa todo lo que no es top-N en 'Otros' para mantener el chart legible.
        Solo out_invoice con amount_residual > 0 — cartera pendiente real.
        """
        if self.staging.empty or "partner_name" not in self.staging.columns:
            return pd.DataFrame()

        cxc = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            (self.staging["amount_residual"] > 0)
        ]

        if cxc.empty:
            return pd.DataFrame()

        por_cliente = (
            cxc.groupby("partner_name")["amount_residual"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
            .rename(columns={"partner_name": "cliente", "amount_residual": "monto"})
        )

        top    = por_cliente.head(top_n)
        otros  = por_cliente.iloc[top_n:]["monto"].sum()

        if otros > 0:
            top = pd.concat([
                top,
                pd.DataFrame([{"cliente": "Otros", "monto": otros}]),
            ], ignore_index=True)

        total = top["monto"].sum()
        top["porcentaje"] = (top["monto"] / total * 100).round(1)

        return top

    def build_monthly_net_cashflow(self, meses: int = 12) -> pd.DataFrame:
        """
        Flujo neto mensual (ingresos cobrados − egresos) — para gráfico waterfall.
        Usa facturas posted para calcular el neto real de cada mes.
        La columna 'tipo' indica si el mes es positivo, negativo o es el total
        acumulado — formato requerido por go.Waterfall de Plotly.
        """
        if self.staging.empty:
            return pd.DataFrame()

        # Ingresos mensuales cobrados (out_invoice cobradas en ese mes)
        ingresos = (
            self.staging[self.staging["move_type"] == "out_invoice"]
            .groupby("month")["collected_amt"].sum()
        )

        # Egresos mensuales (in_invoice total del mes)
        egresos = (
            self.staging[self.staging["move_type"] == "in_invoice"]
            .groupby("month")["amount_total"].sum()
        )

        meses_df = (
            pd.DataFrame({"ingresos": ingresos, "egresos": egresos})
            .fillna(0)
            .reset_index()
        )
        meses_df["neto"]     = meses_df["ingresos"] - meses_df["egresos"]
        meses_df["month_dt"] = pd.to_datetime(meses_df["month"])
        meses_df             = meses_df.sort_values("month_dt").tail(meses)

        # Tipo para go.Waterfall: 'relative' para barras, 'total' para acumulado
        meses_df["tipo"] = "relative"

        # Agregar barra de total acumulado al final
        total_row = pd.DataFrame([{
            "month":    "Total",
            "ingresos": meses_df["ingresos"].sum(),
            "egresos":  meses_df["egresos"].sum(),
            "neto":     meses_df["neto"].sum(),
            "month_dt": meses_df["month_dt"].max() + pd.DateOffset(months=1),
            "tipo":     "total",
        }])
        return pd.concat([meses_df, total_row], ignore_index=True)

    def build_collections_velocity(self) -> pd.DataFrame:
        """
        Velocidad de cobro mensual: DSO promedio por mes.
        Útil para detectar si la cartera se cobra más rápido o más lento
        con el tiempo — tendencia positiva = DSO bajando.
        Solo incluye meses con al menos 3 facturas cobradas para estadística robusta.
        """
        if self.staging.empty:
            return pd.DataFrame()

        cobradas = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            self.staging["is_collected"]
        ].copy()

        if cobradas.empty:
            return pd.DataFrame()

        cobradas["dias_cobro"] = (
            cobradas["date_maturity"] - cobradas["invoice_date"]
        ).dt.days.clip(lower=0)

        velocidad = cobradas.groupby("month").agg(
            dso_mes=("dias_cobro",  "mean"),
            n_fact=("id",           "count"),
        ).reset_index()

        # Filtrar meses con muestra estadísticamente representativa
        velocidad = velocidad[velocidad["n_fact"] >= 3].copy()
        velocidad["dso_mes"]  = velocidad["dso_mes"].round(1)
        velocidad["month_dt"] = pd.to_datetime(velocidad["month"])

        # Media móvil de 3 meses para suavizar ruido estacional
        velocidad = velocidad.sort_values("month_dt").tail(12)
        velocidad["dso_ma3"]  = velocidad["dso_mes"].rolling(3, min_periods=1).mean().round(1)

        return velocidad

    def build_journal_breakdown(self) -> pd.DataFrame:
        """Saldo por diario para gráfico de anillo (donut) de liquidez."""
        if self.journals.empty or "current_balance" not in self.journals.columns:
            return pd.DataFrame()
        return self.journals[self.journals["type"].isin(["bank", "cash"])][
            ["name", "type", "current_balance"]
        ].copy()

    def get_critical_invoices(self, top_n: int = 15) -> pd.DataFrame:
        """Top N facturas vencidas por monto pendiente — para tabla de alertas."""
        if self.staging.empty:
            return pd.DataFrame()

        criticas = self.staging[
            (self.staging["move_type"] == "out_invoice") &
            self.staging["is_overdue"]
        ].copy()

        if criticas.empty:
            return pd.DataFrame()

        criticas["invoice_date"]  = criticas["invoice_date"].dt.strftime("%d/%m/%Y")
        criticas["date_maturity"] = criticas["date_maturity"].dt.strftime("%d/%m/%Y")

        cols = [c for c in [
            "name", "partner_name", "invoice_date", "date_maturity",
            "amount_total", "amount_residual", "days_overdue", "nivel_riesgo",
        ] if c in criticas.columns]

        return (
            criticas[cols]
            .sort_values("amount_residual", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )

    def get_all_kpis(self) -> dict:
        """
        Diccionario completo de KPIs con colores Bootstrap pre-calculados.
        dashboard.py consume este dict sin recalcular — cero lógica en callbacks.
        """
        dso    = self.calc_dso()
        runway = self.calc_cash_runway()
        burn   = self.calc_burn_rate()
        saldo  = self.get_liquid_balance()
        liq    = self.calc_liquidity_ratio()
        tasa   = self.calc_collection_rate()

        total_cxc = cxc_vencida = n_criticas = 0.0

        if not self.staging.empty:
            out         = self.staging[self.staging["move_type"] == "out_invoice"]
            total_cxc   = float(out["amount_residual"].sum())
            cxc_vencida = float(self.staging[self.staging["is_overdue"]]["amount_residual"].sum())
            n_criticas  = int(self.staging[
                self.staging["is_overdue"] & (self.staging["days_overdue"] > 60)
            ].shape[0])

        return {
            "dso":              dso,
            "burn_rate":        burn,
            "cash_runway":      runway,
            "saldo_liquido":    saldo,
            "liquidity_ratio":  liq,
            "collection_rate":  tasa,
            "total_cxc":        total_cxc,
            "cxc_vencida":      cxc_vencida,
            "n_criticas":       int(n_criticas),
            # Colores semáforo Bootstrap
            "color_dso":    "danger"  if dso    > UMBRAL_DSO_CRIT    else "warning" if dso    > UMBRAL_DSO_WARN    else "success",
            "color_runway": "danger"  if runway < UMBRAL_RUNWAY_CRIT else "warning" if runway < UMBRAL_RUNWAY_WARN else "success",
            "color_liq":    "danger"  if liq    < UMBRAL_LIQ_CRIT    else "warning" if liq    < UMBRAL_LIQ_WARN    else "success",
            "color_tasa":   "success" if tasa   > 80                 else "warning" if tasa   > 60                 else "danger",
        }
