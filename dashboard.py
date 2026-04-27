"""
dashboard.py — Capa de Visualización e Interfaz de Usuario

Responsabilidad exclusiva: presentación e interacción del usuario.
Sin lógica de negocio. Sin acceso directo a datos.
Todos los datos provienen de analytics.FinancialAnalytics — nunca inline.

Arquitectura de callbacks:
- Callback principal: KPIs + gráficos estáticos + tabla.
  Disparadores: intervalo automático, botón refresh, cambio de fechas.
- Callback what-if: SOLO proyección de cashflow + runway proyectado.
  Disparador: slider de cobrabilidad.
  Separado para no recalcular todos los KPIs por cada movimiento del slider.

Gráficos incluidos:
  1. Áreas apiladas + banda de confianza — Proyección de flujo de caja 90 días
  2. Donut — Aging Report de CxC por tramo de antigüedad
  3. Donut — Distribución de liquidez por diario (banco/caja)
  4. Pastel — Concentración de CxC por cliente top-8
  5. Barras agrupadas + línea — Facturado vs Cobrado últimos 12 meses
  6. Waterfall — Flujo neto mensual (ingresos cobrados − egresos)
  7. Línea + área — Velocidad de cobro (DSO mensual + media móvil 3m)
"""

import dash
from dash import dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv

from extraction import get_data_source, DEMO_MODE
from analytics import FinancialAnalytics

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# PALETA — Bootstrap FLATLY + extensiones para Plotly
# ══════════════════════════════════════════════════════════════════════════════

C = {
    "primary":   "#2C3E50",
    "success":   "#18BC9C",
    "warning":   "#F39C12",
    "danger":    "#E74C3C",
    "info":      "#3498DB",
    "purple":    "#8E44AD",
    "orange":    "#E67E22",
    "muted":     "#95A5A6",
    "light":     "#ECF0F1",
    "grid":      "#EDF0F3",
    "white":     "#FFFFFF",
    "bg":        "#F4F6F9",
    "text":      "#2C3E50",
    "text2":     "#7F8C8D",
    "border":    "#E8ECF0",
}

# Secuencia de colores para gráficos multi-serie
PALETA_GRAFICOS = [
    C["info"], C["success"], C["warning"], C["danger"],
    C["purple"], C["orange"], "#1ABC9C", "#2980B9",
]

# Layout base Plotly — hereda background del card Bootstrap (transparente)
def base_layout(**kwargs) -> dict:
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'Inter','Segoe UI',sans-serif", color=C["text"], size=12),
        xaxis=dict(
            gridcolor=C["grid"], linecolor=C["border"],
            tickfont=dict(color=C["muted"], size=11),
            showgrid=True, zeroline=False,
        ),
        yaxis=dict(
            gridcolor=C["grid"], linecolor=C["border"],
            tickfont=dict(color=C["muted"], size=11),
            showgrid=True, zeroline=False,
        ),
        legend=dict(
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor=C["border"], borderwidth=1,
            font=dict(size=11, color=C["text2"]),
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
        ),
        margin=dict(l=12, r=12, t=40, b=12),
        hoverlabel=dict(
            bgcolor=C["white"], bordercolor=C["border"],
            font_color=C["text"], font_size=12,
            font_family="'Inter','Segoe UI',sans-serif",
        ),
        hovermode="x unified",
    )
    layout.update(kwargs)
    return layout


# ══════════════════════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.FONT_AWESOME],
    title="BI Financiero · Odoo 18",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "theme-color", "content": C["primary"]},
    ],
    suppress_callback_exceptions=True,
)
server = app.server


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE COMPONENTES
# ══════════════════════════════════════════════════════════════════════════════

def kpi_card(titulo, valor, icono, color_bs, subtitulo="", badge=None, badge_color=None):
    """
    Tarjeta KPI con borde izquierdo de color semáforo, icono FA y badge opcional.
    color_bs debe ser un color Bootstrap (primary/success/warning/danger/info).
    """
    color_hex = C.get(color_bs, C["primary"])
    return dbc.Card(
        dbc.CardBody([
            html.Div([
                # Icono con fondo circular de color
                html.Div(
                    html.I(className=f"fa-solid {icono}", style={"fontSize": "18px", "color": C["white"]}),
                    style={
                        "background":    color_hex,
                        "borderRadius":  "50%",
                        "width":         "40px",
                        "height":        "40px",
                        "display":       "flex",
                        "alignItems":    "center",
                        "justifyContent":"center",
                        "flexShrink":    "0",
                        "boxShadow":     f"0 4px 12px {color_hex}44",
                    },
                ),
                # Textos
                html.Div([
                    html.Div([
                        html.Span(
                            titulo,
                            style={
                                "fontSize":      "10px",
                                "fontWeight":    "700",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.09em",
                                "color":         C["muted"],
                            },
                        ),
                        dbc.Badge(
                            badge, color=badge_color or color_bs,
                            pill=True,
                            style={"fontSize": "9px", "marginLeft": "6px", "verticalAlign": "middle"},
                        ) if badge else None,
                    ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
                    html.Div(
                        valor,
                        style={
                            "fontSize":      "22px",
                            "fontWeight":    "800",
                            "color":         color_hex,
                            "letterSpacing": "-0.03em",
                            "lineHeight":    "1",
                            "fontVariantNumeric": "tabular-nums",
                        },
                    ),
                    html.Div(
                        subtitulo,
                        style={"fontSize": "11px", "color": C["muted"], "marginTop": "3px"},
                    ) if subtitulo else None,
                ], style={"marginLeft": "12px", "flex": "1"}),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={"padding": "16px 18px"}),
        className="kpi-card h-100",
        style={
            "borderLeft": f"4px solid {color_hex} !important",
            "borderRadius": "10px",
        },
    )


def chart_card(header_content, graph_id, height="320px", extra_content=None):
    """Card contenedor para gráficos con header consistente."""
    return dbc.Card([
        dbc.CardHeader(header_content),
        dbc.CardBody([
            dcc.Graph(
                id=graph_id,
                config={"displayModeBar": False, "responsive": True},
                style={"height": height},
            ),
            extra_content or html.Div(),
        ], style={"padding": "12px 16px"}),
    ], className="chart-card shadow-sm h-100")


def chart_header(icono, titulo, badge=None, badge_color="primary"):
    return html.Div([
        html.I(className=f"fa-solid {icono} me-2", style={"color": C.get(badge_color, C["primary"])}),
        html.Span(titulo),
        dbc.Badge(badge, color=badge_color, className="ms-2",
                  style={"fontSize": "9px", "verticalAlign": "middle"}) if badge else None,
    ], style={"fontWeight": "600", "fontSize": "13px", "color": C["text"], "display": "flex", "alignItems": "center"})


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

app.layout = dbc.Container([

    # ── Navbar ────────────────────────────────────────────────────────────────
    dbc.Navbar(
        dbc.Container([
            # Logo
            html.Div([
                html.Div(
                    html.I(className="fa-solid fa-chart-pie", style={"color": "#18BC9C", "fontSize": "20px"}),
                    style={"marginRight": "10px"},
                ),
                html.Div([
                    html.Span(
                        "BI Financiero",
                        style={"fontWeight": "800", "fontSize": "16px",
                               "color": C["white"], "letterSpacing": "-0.02em"},
                    ),
                    dbc.Badge(
                        "Odoo 18",
                        color="light", text_color="primary",
                        style={"fontSize": "9px", "marginLeft": "8px", "verticalAlign": "middle"},
                    ),
                ]),
            ], style={"display": "flex", "alignItems": "center"}),

            # Controles derecha
            dbc.Nav([
                # Estado conexión
                html.Div([
                    html.Span(
                        className="fa-solid fa-circle",
                        style={
                            "color":     C["warning"] if DEMO_MODE else C["success"],
                            "fontSize":  "7px",
                            "marginRight":"6px",
                        },
                    ),
                    html.Span(
                        "DEMO" if DEMO_MODE else "En línea · Odoo 18",
                        style={"color": "rgba(255,255,255,0.6)", "fontSize": "11px", "fontWeight": "500"},
                    ),
                ], style={"display": "flex", "alignItems": "center", "marginRight": "20px"}),

                # Timestamp
                html.Span(
                    id="ts-actualizacion",
                    style={"color": "rgba(255,255,255,0.4)", "fontSize": "10px", "marginRight": "16px"},
                ),

                # Botón refresh
                dbc.Button([
                    html.I(className="fa-solid fa-rotate me-1"),
                    "Actualizar",
                ], id="btn-refresh", color="outline-light", size="sm",
                   style={"fontSize": "11px", "borderRadius": "6px"}),
            ], className="ms-auto", navbar=True,
               style={"display": "flex", "alignItems": "center"}),

        ], fluid=True),
        dark=True,
        sticky="top",
        className="shadow-sm",
        style={"background": "linear-gradient(135deg, #1A252F 0%, #2C3E50 100%)",
               "borderBottom": f"3px solid {C['success']}"},
    ),

    # ── Banner de alertas (dinámico) ──────────────────────────────────────────
    html.Div(id="banner-alertas"),

    # ── Cuerpo ────────────────────────────────────────────────────────────────
    dbc.Container([

        # Header + filtro de fechas
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H5(
                        "Dashboard de Liquidez y Flujo de Caja",
                        style={"fontWeight": "800", "color": C["primary"],
                               "letterSpacing": "-0.02em", "marginBottom": "2px"},
                    ),
                    html.Span(
                        f"{'Datos Simulados · DEMO MODE' if DEMO_MODE else 'Datos en Tiempo Real · Odoo 18'}  "
                        f"·  {datetime.today().strftime('%d de %B de %Y')}",
                        style={"fontSize": "12px", "color": C["muted"]},
                    ),
                ], style={"marginTop": "18px"}),
            ], md=7),
            dbc.Col([
                html.Div([
                    html.Div(
                        "Periodo de análisis",
                        style={"fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
                               "letterSpacing": "0.08em", "color": C["muted"], "marginBottom": "6px"},
                    ),
                    dcc.DatePickerRange(
                        id="rango-fechas",
                        start_date=(datetime.today() - pd.DateOffset(months=6)).date(),
                        end_date=datetime.today().date(),
                        display_format="DD/MM/YYYY",
                        first_day_of_week=1,
                    ),
                ], style={"marginTop": "18px"}),
            ], md=5, style={"textAlign": "right"}),
        ], className="mb-3"),

        # ── Fila de KPIs ──────────────────────────────────────────────────────
        html.Div(
            "Indicadores clave de desempeño",
            className="section-title",
        ),
        html.Div(id="fila-kpis", className="mb-3"),

        # ── Simulador What-If ─────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.I(className="fa-solid fa-sliders me-2"),
                    html.Span("Simulador de Escenarios"),
                    dbc.Badge("What-If", color="light", text_color="dark", className="ms-2",
                              style={"fontSize": "9px"}),
                ], style={"fontWeight": "600", "color": C["white"]}),
                style={"background": f"linear-gradient(135deg, {C['warning']} 0%, {C['orange']} 100%)",
                       "border": "none", "borderRadius": "9px 9px 0 0"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.P([
                            html.Strong("¿Qué porcentaje de cuentas por cobrar pendientes esperas recuperar?"),
                            html.Br(),
                            html.Span(
                                "El gráfico de proyección y el Cash Runway se recalculan en tiempo real.",
                                style={"fontSize": "12px", "color": C["muted"]},
                            ),
                        ], style={"marginBottom": "16px"}),
                        dcc.Slider(
                            id="slider-cobrabilidad",
                            min=0, max=100, step=5, value=85,
                            marks={i: {"label": f"{i}%", "style": {"color": C["muted"], "fontSize": "11px"}}
                                   for i in range(0, 101, 10)},
                            tooltip={"placement": "top", "always_visible": True},
                        ),
                    ], md=8),
                    dbc.Col([
                        html.Div([
                            html.Div(
                                "Cash Runway proyectado",
                                style={"fontSize": "11px", "color": C["muted"],
                                       "textAlign": "center", "marginBottom": "6px"},
                            ),
                            html.Div(
                                id="runway-whatif",
                                style={"fontSize": "32px", "fontWeight": "800",
                                       "color": C["info"], "textAlign": "center",
                                       "letterSpacing": "-0.03em", "lineHeight": "1"},
                            ),
                            html.Div(
                                "meses con este escenario",
                                style={"fontSize": "11px", "color": C["muted"],
                                       "textAlign": "center", "marginTop": "6px"},
                            ),
                        ], className="runway-box", style={"padding": "16px"}),
                    ], md=4),
                ], style={"alignItems": "center"}),
            ]),
        ], className="mb-3 shadow-sm",
           style={"borderRadius": "10px", "border": f"1px solid {C['border']}",
                  "background": "#FEFDF8"}),

        # ── Gráfico 1: Proyección de Flujo de Caja (full width) ───────────────
        html.Div("Proyección de flujo de caja", className="section-title"),
        chart_card(
            chart_header("fa-chart-area", "Proyección de Flujo de Caja — 90 días",
                         badge="Dinámico", badge_color="info"),
            "grafico-cashflow",
            height="360px",
        ),
        html.Div(style={"marginBottom": "16px"}),

        # ── Fila: Donut Aging | Donut Liquidez | Pastel Clientes ──────────────
        html.Div("Distribución y concentración", className="section-title mt-3"),
        dbc.Row([
            dbc.Col(
                chart_card(
                    chart_header("fa-hourglass-half", "Aging Report CxC", badge="Por tramo", badge_color="warning"),
                    "grafico-donut-aging",
                    height="300px",
                ),
                md=4, className="mb-3",
            ),
            dbc.Col(
                chart_card(
                    chart_header("fa-building-columns", "Liquidez por Diario", badge="Banco/Caja", badge_color="success"),
                    "grafico-donut-liquidez",
                    height="300px",
                ),
                md=4, className="mb-3",
            ),
            dbc.Col(
                chart_card(
                    chart_header("fa-users", "Concentración CxC por Cliente", badge="Top 8", badge_color="info"),
                    "grafico-pastel-clientes",
                    height="300px",
                ),
                md=4, className="mb-3",
            ),
        ], className="g-3"),

        # ── Fila: Barras Facturado/Cobrado | Waterfall Neto ───────────────────
        html.Div("Análisis mensual", className="section-title"),
        dbc.Row([
            dbc.Col(
                chart_card(
                    chart_header("fa-chart-bar", "Facturado vs. Cobrado — Últimos 12 meses"),
                    "grafico-barras",
                    height="320px",
                ),
                md=7, className="mb-3",
            ),
            dbc.Col(
                chart_card(
                    chart_header("fa-water", "Flujo Neto Mensual", badge="Waterfall", badge_color="purple"),
                    "grafico-waterfall",
                    height="320px",
                ),
                md=5, className="mb-3",
            ),
        ], className="g-3"),

        # ── Gráfico 7: Velocidad de Cobro (DSO mensual) ───────────────────────
        html.Div("Eficiencia operativa", className="section-title"),
        chart_card(
            chart_header("fa-gauge-high", "Velocidad de Cobro — DSO Mensual y Media Móvil 3 meses",
                         badge="Tendencia", badge_color="primary"),
            "grafico-velocidad",
            height="240px",
        ),
        html.Div(style={"marginBottom": "16px"}),

        # ── Tabla: Facturas Críticas ───────────────────────────────────────────
        html.Div("Alertas de cartera", className="section-title mt-3"),
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.I(className="fa-solid fa-triangle-exclamation me-2",
                           style={"color": C["danger"]}),
                    html.Span("Facturas Críticas — Vencidas con Mayor Riesgo de Impago",
                              style={"fontWeight": "600", "fontSize": "13px"}),
                    html.Span(id="badge-criticas", className="ms-2"),
                ], style={"display": "flex", "alignItems": "center"}),
            ),
            dbc.CardBody([html.Div(id="tabla-criticas")],
                         style={"padding": "12px 16px"}),
        ], className="chart-card shadow-sm mb-4"),

    ], fluid=True, style={"maxWidth": "1440px", "margin": "0 auto", "padding": "0 20px"}),

    # Footer
    html.Footer(
        html.P(
            f"BI Financiero Dashboard  ·  Odoo 18  ·  {datetime.today().year}  "
            "·  ETL → Analítica → Visualización  ·  Arquitectura desacoplada",
            style={"fontSize": "11px", "color": C["muted"], "textAlign": "center",
                   "padding": "16px", "margin": "0",
                   "borderTop": f"1px solid {C['border']}"},
        ),
    ),

    dcc.Interval(id="intervalo", interval=300_000, n_intervals=0),

], fluid=True, className="px-0", style={"background": C["bg"]})


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK PRINCIPAL — KPIs + todos los gráficos estáticos + tabla
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("banner-alertas",         "children"),
    Output("ts-actualizacion",       "children"),
    Output("fila-kpis",              "children"),
    Output("grafico-donut-aging",    "figure"),
    Output("grafico-donut-liquidez", "figure"),
    Output("grafico-pastel-clientes","figure"),
    Output("grafico-barras",         "figure"),
    Output("grafico-waterfall",      "figure"),
    Output("grafico-velocidad",      "figure"),
    Output("tabla-criticas",         "children"),
    Output("badge-criticas",         "children"),
    Input("intervalo",               "n_intervals"),
    Input("btn-refresh",             "n_clicks"),
    Input("rango-fechas",            "start_date"),
    Input("rango-fechas",            "end_date"),
    prevent_initial_call=False,
)
def actualizar_dashboard(n_int, n_clicks, f_inicio, f_fin):

    # ── Una sola llamada ETL por ciclo ────────────────────────────────────────
    fa   = FinancialAnalytics(get_data_source().load_all())
    kpis = fa.get_all_kpis()

    staging = fa.staging.copy()
    if f_inicio and f_fin and not staging.empty:
        staging = staging[
            (staging["invoice_date"] >= pd.Timestamp(f_inicio)) &
            (staging["invoice_date"] <= pd.Timestamp(f_fin))
        ]

    ts = f"Actualizado {datetime.now().strftime('%H:%M:%S')}"

    # ── Alertas ───────────────────────────────────────────────────────────────
    alertas = []
    if kpis["cash_runway"] < 3:
        alertas.append(dbc.Alert([
            html.I(className="fa-solid fa-circle-exclamation me-2"),
            html.Strong("ALERTA CRÍTICA — "),
            f"Cash Runway de {kpis['cash_runway']} meses. Liquidez insuficiente para 90 días de operación.",
        ], color="danger", className="mb-0 border-0 rounded-0 py-2"))
    elif kpis["cash_runway"] < 6:
        alertas.append(dbc.Alert([
            html.I(className="fa-solid fa-triangle-exclamation me-2"),
            html.Strong("ADVERTENCIA — "),
            f"Cash Runway de {kpis['cash_runway']} meses. Revisar plan de cobranza.",
        ], color="warning", className="mb-0 border-0 rounded-0 py-2"))

    if kpis["n_criticas"] > 0:
        alertas.append(dbc.Alert([
            html.I(className="fa-solid fa-file-invoice-dollar me-2"),
            f"{kpis['n_criticas']} facturas con más de 60 días vencidas detectadas.",
        ], color="warning" if kpis["n_criticas"] < 10 else "danger",
           className="mb-0 border-0 rounded-0 py-2"))

    banner = html.Div(alertas) if alertas else None

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    runway_str = f"{kpis['cash_runway']} m" if kpis["cash_runway"] != float("inf") else "∞"
    liq_str    = f"{kpis['liquidity_ratio']:.2f}×" if kpis["liquidity_ratio"] < 90 else ">90×"

    fila_kpis = dbc.Row([
        dbc.Col(kpi_card(
            "Saldo Líquido", f"${kpis['saldo_liquido']:,.0f}", "fa-building-columns",
            "primary", "Banco + Caja · Odoo journals",
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "DSO", f"{kpis['dso']} días", "fa-clock-rotate-left",
            kpis["color_dso"], "Days Sales Outstanding promedio",
            badge="KPI", badge_color=kpis["color_dso"],
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "Burn Rate", f"${kpis['burn_rate']:,.0f}/m", "fa-fire-flame-curved",
            "warning", "Egreso operativo mensual (3 m)",
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "Cash Runway", runway_str, "fa-rocket",
            kpis["color_runway"], "Meses de supervivencia",
            badge="CRÍTICO" if kpis["cash_runway"] < 3 else "OK",
            badge_color=kpis["color_runway"],
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "CxC Total", f"${kpis['total_cxc']:,.0f}", "fa-file-invoice-dollar",
            "info", "Cuentas por cobrar pendientes",
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "CxC Vencida", f"${kpis['cxc_vencida']:,.0f}", "fa-calendar-xmark",
            "danger", "Facturas con fecha vencida",
            badge="OVERDUE", badge_color="danger",
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
        dbc.Col(kpi_card(
            "Tasa Cobro", f"{kpis['collection_rate']}%", "fa-percent",
            kpis["color_tasa"], "Porcentaje cobrado / facturado",
            badge=f"{kpis['collection_rate']}%", badge_color=kpis["color_tasa"],
        ), xs=12, sm=6, md=4, lg=True, className="mb-3"),
    ], className="g-3")

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 2 — DONUT: Aging Report
    # ══════════════════════════════════════════════════════════════════════════
    aging   = fa.build_aging_report()
    colores_aging = [C["success"], C["warning"], C["info"], C["orange"], C["danger"]]

    if aging.empty:
        fig_aging_donut = go.Figure()
    else:
        total_cxc_str = f"${aging['monto'].sum():,.0f}"
        fig_aging_donut = go.Figure(go.Pie(
            labels=aging["tramo"],
            values=aging["monto"],
            hole=0.62,
            marker=dict(colors=colores_aging[:len(aging)],
                        line=dict(color=C["white"], width=2)),
            textposition="outside",
            textinfo="label+percent",
            textfont=dict(size=11, color=C["text"]),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Monto: $%{value:,.0f}<br>"
                "Participación: %{percent}<extra></extra>"
            ),
            pull=[0.04 if i == len(aging) - 1 else 0 for i in range(len(aging))],
        ))
        fig_aging_donut.add_annotation(
            text=f"<b>CxC</b><br>{total_cxc_str}",
            x=0.5, y=0.5, font=dict(size=12, color=C["text"], family="'Inter',sans-serif"),
            showarrow=False,
        )
        fig_aging_donut.update_layout(
            **base_layout(
                showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=-0.25,
                    xanchor="center", x=0.5,
                    font=dict(size=10, color=C["text2"]),
                    bgcolor="rgba(0,0,0,0)",
                ),
                margin=dict(l=20, r=20, t=30, b=20),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 3 — DONUT: Distribución de Liquidez por Diario
    # ══════════════════════════════════════════════════════════════════════════
    diarios = fa.build_journal_breakdown()
    colores_diarios = [C["info"], C["primary"], C["success"], C["purple"]]

    if diarios.empty:
        fig_liq_donut = go.Figure()
    else:
        saldo_total_str = f"${diarios['current_balance'].sum():,.0f}"
        fig_liq_donut = go.Figure(go.Pie(
            labels=diarios["name"],
            values=diarios["current_balance"],
            hole=0.60,
            marker=dict(colors=colores_diarios[:len(diarios)],
                        line=dict(color=C["white"], width=2)),
            textposition="outside",
            textinfo="label+percent",
            textfont=dict(size=11, color=C["text"]),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Saldo: $%{value:,.0f}<br>"
                "%{percent}<extra></extra>"
            ),
        ))
        fig_liq_donut.add_annotation(
            text=f"<b>Líquido</b><br>{saldo_total_str}",
            x=0.5, y=0.5, font=dict(size=12, color=C["text"], family="'Inter',sans-serif"),
            showarrow=False,
        )
        fig_liq_donut.update_layout(
            **base_layout(
                showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=-0.25,
                    xanchor="center", x=0.5,
                    font=dict(size=10, color=C["text2"]),
                    bgcolor="rgba(0,0,0,0)",
                ),
                margin=dict(l=20, r=20, t=30, b=20),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 4 — PASTEL: Concentración CxC por Cliente
    # ══════════════════════════════════════════════════════════════════════════
    clientes = fa.build_client_concentration(top_n=8)

    if clientes.empty:
        fig_pie_clientes = go.Figure()
    else:
        fig_pie_clientes = go.Figure(go.Pie(
            labels=clientes["cliente"],
            values=clientes["monto"],
            hole=0,
            marker=dict(colors=PALETA_GRAFICOS[:len(clientes)],
                        line=dict(color=C["white"], width=1.5)),
            textposition="inside",
            textinfo="percent",
            insidetextfont=dict(size=11, color=C["white"], family="'Inter',sans-serif"),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "$%{value:,.0f}  (%{percent})<extra></extra>"
            ),
        ))
        fig_pie_clientes.update_layout(
            **base_layout(
                showlegend=True,
                legend=dict(
                    orientation="v", yanchor="middle", y=0.5,
                    xanchor="left", x=1.02,
                    font=dict(size=10, color=C["text2"]),
                    bgcolor="rgba(0,0,0,0)",
                ),
                margin=dict(l=10, r=120, t=30, b=10),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 5 — BARRAS AGRUPADAS: Facturado vs. Cobrado
    # ══════════════════════════════════════════════════════════════════════════
    mensual = fa.build_monthly_comparison()

    if mensual.empty:
        fig_barras = go.Figure()
    else:
        fig_barras = go.Figure()

        fig_barras.add_trace(go.Bar(
            x=mensual["month_dt"],
            y=mensual["facturado"],
            name="Facturado",
            marker=dict(
                color=C["info"],
                opacity=0.85,
                cornerradius=4,
                line=dict(width=0),
            ),
            hovertemplate="<b>%{x|%b %Y}</b><br>Facturado: $%{y:,.0f}<extra></extra>",
        ))
        fig_barras.add_trace(go.Bar(
            x=mensual["month_dt"],
            y=mensual["cobrado"],
            name="Cobrado",
            marker=dict(
                color=C["success"],
                opacity=0.85,
                cornerradius=4,
                line=dict(width=0),
            ),
            hovertemplate="<b>%{x|%b %Y}</b><br>Cobrado: $%{y:,.0f}<extra></extra>",
        ))
        # Tasa de cobro — línea en eje secundario
        fig_barras.add_trace(go.Scatter(
            x=mensual["month_dt"],
            y=mensual["tasa_cobro"],
            name="% Cobro",
            mode="lines+markers",
            yaxis="y2",
            line=dict(color=C["warning"], width=2.5, shape="spline", smoothing=0.6),
            marker=dict(size=7, color=C["warning"],
                        line=dict(color=C["white"], width=2), symbol="circle"),
            hovertemplate="<b>%{x|%b %Y}</b><br>Tasa: %{y:.1f}%<extra></extra>",
        ))
        # Línea de meta de cobro al 80%
        fig_barras.add_hline(
            y=80, yref="y2",
            line_dash="dot", line_color=C["muted"], line_width=1.5,
            annotation_text="Meta 80%",
            annotation_font=dict(size=10, color=C["muted"]),
            annotation_position="right",
        )
        fig_barras.update_layout(
            **base_layout(
                barmode="group",
                bargap=0.22,
                bargroupgap=0.06,
                yaxis=dict(tickprefix="$", gridcolor=C["grid"],
                           linecolor=C["border"], zeroline=False,
                           tickfont=dict(color=C["muted"], size=11)),
                yaxis2=dict(
                    overlaying="y", side="right",
                    range=[0, 130], ticksuffix="%",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=C["warning"], size=10),
                    zeroline=False, showgrid=False,
                ),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 6 — WATERFALL: Flujo Neto Mensual
    # ══════════════════════════════════════════════════════════════════════════
    neto_mensual = fa.build_monthly_net_cashflow(meses=10)

    if neto_mensual.empty:
        fig_waterfall = go.Figure()
    else:
        etiquetas = [
            d.strftime("%b %y") if t == "relative" else "Total"
            for d, t in zip(neto_mensual["month_dt"], neto_mensual["tipo"])
        ]
        fig_waterfall = go.Figure(go.Waterfall(
            name="Flujo Neto",
            orientation="v",
            measure=neto_mensual["tipo"].tolist(),
            x=etiquetas,
            y=neto_mensual["neto"].tolist(),
            textposition="outside",
            text=[f"${v:,.0f}" for v in neto_mensual["neto"]],
            textfont=dict(size=9, color=C["text"]),
            connector=dict(line=dict(color=C["grid"], width=1.5, dash="dot")),
            increasing=dict(marker=dict(
                color=C["success"],
                line=dict(color=C["success"], width=0),
            )),
            decreasing=dict(marker=dict(
                color=C["danger"],
                line=dict(color=C["danger"], width=0),
            )),
            totals=dict(marker=dict(
                color=C["primary"],
                line=dict(color=C["primary"], width=0),
            )),
            hovertemplate="<b>%{x}</b><br>Neto: $%{y:,.0f}<extra></extra>",
        ))
        fig_waterfall.update_layout(
            **base_layout(
                showlegend=False,
                yaxis=dict(tickprefix="$", gridcolor=C["grid"],
                           zeroline=True, zerolinecolor=C["border"],
                           zerolinewidth=1.5, linecolor=C["border"],
                           tickfont=dict(color=C["muted"], size=10)),
                xaxis=dict(gridcolor="rgba(0,0,0,0)", linecolor=C["border"],
                           tickfont=dict(color=C["muted"], size=10)),
                bargap=0.35,
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 7 — LÍNEA + ÁREA: Velocidad de Cobro (DSO Mensual)
    # ══════════════════════════════════════════════════════════════════════════
    velocidad = fa.build_collections_velocity()

    if velocidad.empty:
        fig_velocidad = go.Figure()
    else:
        fig_velocidad = go.Figure()

        # Área de fondo para DSO mensual
        fig_velocidad.add_trace(go.Scatter(
            x=velocidad["month_dt"],
            y=velocidad["dso_mes"],
            name="DSO mensual",
            mode="lines+markers",
            line=dict(color=C["info"], width=1.5),
            fill="tozeroy",
            fillcolor="rgba(52,152,219,0.08)",
            marker=dict(size=6, color=C["info"],
                        line=dict(color=C["white"], width=1.5)),
            hovertemplate="<b>%{x|%b %Y}</b><br>DSO: %{y:.1f} días<extra></extra>",
        ))
        # Media móvil 3 meses — línea de tendencia
        fig_velocidad.add_trace(go.Scatter(
            x=velocidad["month_dt"],
            y=velocidad["dso_ma3"],
            name="Media móvil 3m",
            mode="lines",
            line=dict(color=C["warning"], width=2.5, dash="solid", shape="spline", smoothing=0.8),
            hovertemplate="<b>%{x|%b %Y}</b><br>MA3: %{y:.1f} días<extra></extra>",
        ))
        # Línea de umbral de alerta
        fig_velocidad.add_hline(
            y=45,
            line_dash="dot", line_color=C["danger"], line_width=1.5,
            annotation_text="Umbral alerta 45d",
            annotation_font=dict(size=10, color=C["danger"]),
            annotation_position="right",
        )
        fig_velocidad.update_layout(
            **base_layout(
                yaxis=dict(
                    ticksuffix=" d", gridcolor=C["grid"],
                    zeroline=False, linecolor=C["border"],
                    tickfont=dict(color=C["muted"], size=11),
                    title=dict(text="Días", font=dict(size=11, color=C["muted"])),
                ),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # TABLA: Facturas Críticas
    # ══════════════════════════════════════════════════════════════════════════
    criticas  = fa.get_critical_invoices(top_n=15)
    n_criticas = len(criticas)

    if criticas.empty:
        tabla = dbc.Alert([
            html.I(className="fa-solid fa-circle-check me-2"),
            "Sin facturas críticas vencidas en el período seleccionado.",
        ], color="success", className="mb-0")
    else:
        renombres = {
            "name": "Folio", "partner_name": "Cliente",
            "invoice_date": "Emisión", "date_maturity": "Vencimiento",
            "amount_total": "Total", "amount_residual": "Pendiente",
            "days_overdue": "Días vencida", "nivel_riesgo": "Riesgo",
        }
        df_tabla = criticas.rename(columns={k: v for k, v in renombres.items() if k in criticas.columns})

        for col in ["Total", "Pendiente"]:
            if col in df_tabla.columns:
                df_tabla[col] = df_tabla[col].apply(lambda x: f"${x:,.0f}")

        tabla = dash_table.DataTable(
            data=df_tabla.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df_tabla.columns],
            page_size=10,
            sort_action="native",
            filter_action="native",
            style_as_list_view=True,
            style_table={"overflowX": "auto"},
            style_header={
                "backgroundColor": C["light"],
                "fontWeight":       "700",
                "color":            C["text"],
                "fontSize":         "10px",
                "textTransform":    "uppercase",
                "letterSpacing":    "0.07em",
                "border":           f"1px solid {C['border']}",
                "borderBottom":     f"2px solid {C['border']}",
                "padding":          "10px 12px",
            },
            style_cell={
                "fontFamily":    "'Inter','Segoe UI',sans-serif",
                "fontSize":      "13px",
                "color":         C["text"],
                "padding":       "9px 12px",
                "border":        f"1px solid {C['border']}",
                "whiteSpace":    "normal",
                "textAlign":     "left",
            },
            style_cell_conditional=[
                {"if": {"column_id": "Pendiente"}, "fontWeight": "700", "textAlign": "right"},
                {"if": {"column_id": "Total"},     "textAlign": "right"},
                {"if": {"column_id": "Días vencida"}, "textAlign": "center", "fontWeight": "600"},
            ],
            style_data_conditional=[
                {
                    "if": {"filter_query": '{Riesgo} = "Riesgo crítico"'},
                    "backgroundColor": "#FEF0EF",
                    "color":           C["danger"],
                    "fontWeight":      "600",
                    "borderLeft":      f"3px solid {C['danger']}",
                },
                {
                    "if": {"filter_query": '{Riesgo} = "Riesgo medio"'},
                    "backgroundColor": "#FEF9EC",
                    "color":           "#7D6608",
                    "borderLeft":      f"3px solid {C['warning']}",
                },
                {
                    "if": {"filter_query": '{Riesgo} = "Riesgo bajo"'},
                    "backgroundColor": "#EBF5FB",
                    "borderLeft":      f"3px solid {C['info']}",
                },
                {"if": {"row_index": "odd"}, "backgroundColor": "#FBFCFD"},
            ],
            style_filter={
                "backgroundColor": "#F8F9FA",
                "fontSize":        "12px",
                "fontFamily":      "'Inter',sans-serif",
            },
        )

    badge_criticas = dbc.Badge(
        f"{n_criticas} facturas",
        color="danger" if n_criticas > 5 else "warning",
        pill=True, style={"fontSize": "10px"},
    ) if n_criticas > 0 else dbc.Badge("Sin alertas", color="success", pill=True)

    return (banner, ts, fila_kpis,
            fig_aging_donut, fig_liq_donut, fig_pie_clientes,
            fig_barras, fig_waterfall, fig_velocidad,
            tabla, badge_criticas)


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK WHAT-IF — solo proyección cashflow + runway proyectado
# Separado para no recalcular todos los KPIs por cada movimiento del slider.
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("grafico-cashflow", "figure"),
    Output("runway-whatif",    "children"),
    Input("slider-cobrabilidad", "value"),
    prevent_initial_call=False,
)
def actualizar_whatif(pct: int):
    cobrabilidad = (pct or 0) / 100
    fa           = FinancialAnalytics(get_data_source().load_all())
    proy         = fa.build_cashflow_projection(cobrabilidad=cobrabilidad, dias=90)
    burn_rate    = fa.calc_burn_rate()

    # Runway proyectado con saldo al final del horizonte
    if not proy.empty and burn_rate > 0:
        saldo_final  = max(float(proy["saldo"].iloc[-1]), 0)
        runway_proy  = round(saldo_final / burn_rate, 1)
        runway_color = C["danger"] if runway_proy < 3 else C["warning"] if runway_proy < 6 else C["success"]
        runway_str   = f"{runway_proy} m"
    else:
        runway_color = C["muted"]
        runway_str   = "N/D"

    if proy.empty:
        return go.Figure(), runway_str

    fig = go.Figure()

    # ── Banda de confianza (escenario optimista) ──────────────────────────────
    fig.add_trace(go.Scatter(
        x=list(proy["fecha"]) + list(proy["fecha"])[::-1],
        y=list(proy["saldo_opt"]) + list(proy["saldo_pes"])[::-1],
        fill="toself",
        fillcolor="rgba(52,152,219,0.07)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=True,
        name="Banda de confianza ±15%",
        hoverinfo="skip",
    ))

    # ── Área de ingresos ──────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=proy["fecha"], y=proy["ingreso"],
        name="Ingresos esperados",
        fill="tozeroy", mode="lines",
        line=dict(color=C["success"], width=1.5),
        fillcolor="rgba(24,188,156,0.13)",
        hovertemplate="<b>%{x|%d %b}</b><br>Ingreso: $%{y:,.0f}<extra></extra>",
    ))

    # ── Área de egresos (espejada) ────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=proy["fecha"], y=[-v for v in proy["egreso"]],
        name="Egresos comprometidos",
        fill="tozeroy", mode="lines",
        line=dict(color=C["danger"], width=1.5),
        fillcolor="rgba(231,76,60,0.10)",
        hovertemplate="<b>%{x|%d %b}</b><br>Egreso: $%{y:,.0f}<extra></extra>",
    ))

    # ── Saldo proyectado — línea principal ────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=proy["fecha"], y=proy["saldo"],
        name="Saldo proyectado",
        mode="lines",
        line=dict(color=C["primary"], width=3, shape="spline", smoothing=0.3),
        yaxis="y2",
        hovertemplate="<b>%{x|%d %b}</b><br>Saldo: $%{y:,.0f}<extra></extra>",
    ))

    # Línea de equilibrio
    fig.add_hline(y=0, line_color=C["border"], line_width=1)

    # Anotación de escenario activo
    if pct < 100:
        fig.add_annotation(
            text=f"⚠  Escenario activo: {pct}% cobrabilidad",
            xref="paper", yref="paper", x=0.01, y=0.97,
            showarrow=False,
            font=dict(size=11, color=C["warning"], family="'Inter',sans-serif"),
            bgcolor=C["white"],
            bordercolor=C["warning"],
            borderwidth=1,
            borderpad=6,
        )

    fig.update_layout(
        **base_layout(
            yaxis=dict(tickprefix="$", gridcolor=C["grid"],
                       zeroline=False, linecolor=C["border"],
                       tickfont=dict(color=C["muted"], size=11)),
            yaxis2=dict(
                overlaying="y", side="right",
                gridcolor="rgba(0,0,0,0)",
                tickfont=dict(color=C["primary"], size=10),
                tickprefix="$",
                zeroline=False, showgrid=False,
            ),
        ),
    )

    runway_display = html.Span(runway_str, style={"color": runway_color})
    return fig, runway_display


# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, port=8050, host="0.0.0.0")
