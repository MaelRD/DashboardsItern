import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta

from data_engine import get_dashboard_data

# ══════════════════════════════════════════════════════════════════════════════
# SISTEMA DE DISEÑO — paleta de colores y fuente tipográfica
# ══════════════════════════════════════════════════════════════════════════════

C = {
    "bg":         "#0b0e1a",
    "surface":    "#111827",
    "surface2":   "#1c2333",
    "border":     "#1f2d45",
    "accent":     "#3b82f6",
    "accent2":    "#8b5cf6",
    "green":      "#10b981",
    "red":        "#ef4444",
    "amber":      "#f59e0b",
    "text":       "#f1f5f9",
    "muted":      "#64748b",
    "grid":       "#151d2e",
}

FUENTE = "Inter, 'Segoe UI', system-ui, sans-serif"

# Layout base compartido por todos los gráficos Plotly
LAYOUT_BASE = dict(
    paper_bgcolor = "rgba(0,0,0,0)",
    plot_bgcolor  = "rgba(0,0,0,0)",
    font          = dict(family=FUENTE, color=C["text"], size=12),
    xaxis         = dict(gridcolor=C["grid"], linecolor=C["border"],
                         tickfont=dict(color=C["muted"], size=11),
                         showgrid=True, zeroline=False),
    yaxis         = dict(gridcolor=C["grid"], linecolor=C["border"],
                         tickfont=dict(color=C["muted"], size=11),
                         showgrid=True, zeroline=False),
    legend        = dict(bgcolor="rgba(0,0,0,0)", bordercolor=C["border"],
                         borderwidth=1, font=dict(size=11, color=C["muted"])),
    margin        = dict(l=8, r=8, t=32, b=8),
    hoverlabel    = dict(bgcolor=C["surface2"], bordercolor=C["border"],
                         font_color=C["text"], font_size=12),
    hovermode     = "x unified",
)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTORES DE COMPONENTES UI
# ══════════════════════════════════════════════════════════════════════════════

def kpi_card(titulo, valor, subtitulo="", color=None, badge=None, badge_color=None):
    """Tarjeta KPI reutilizable con indicador de color semáforo y badge de estado."""
    color = color or C["accent"]
    badge_color = badge_color or C["muted"]
    return html.Div([
        html.Div([
            html.Span(titulo, style={
                "color": C["muted"], "fontSize": "10px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.1em",
            }),
            html.Span(badge, style={
                "background": badge_color + "22",
                "color": badge_color,
                "fontSize": "9px", "fontWeight": "700",
                "padding": "2px 7px", "borderRadius": "20px",
                "letterSpacing": "0.05em",
                "border": f"1px solid {badge_color}44",
            }) if badge else None,
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "marginBottom": "10px"}),

        html.Div(valor, style={
            "fontSize": "24px", "fontWeight": "800",
            "color": color, "letterSpacing": "-0.03em",
            "lineHeight": "1",
        }),
        html.Div(subtitulo, style={
            "color": C["muted"], "fontSize": "11px", "marginTop": "6px",
        }) if subtitulo else None,

        # Barra decorativa de gradiente en la parte inferior
        html.Div(style={
            "position": "absolute", "bottom": "0", "left": "0", "right": "0",
            "height": "2px",
            "background": f"linear-gradient(90deg, {color}88, transparent)",
            "borderRadius": "0 0 10px 10px",
        }),
    ], style={
        "background":   C["surface"],
        "border":       f"1px solid {C['border']}",
        "borderRadius": "12px",
        "padding":      "18px 20px 20px",
        "flex":         "1",
        "minWidth":     "148px",
        "position":     "relative",
        "overflow":     "hidden",
    })


def tarjeta_grafico(titulo, subtitulo, graph_id, altura="340px"):
    """Contenedor estilizado para cada gráfico del dashboard."""
    return html.Div([
        html.Div([
            html.Div(titulo, style={
                "color": C["text"], "fontSize": "13px",
                "fontWeight": "600", "letterSpacing": "-0.01em",
            }),
            html.Div(subtitulo, style={
                "color": C["muted"], "fontSize": "11px", "marginTop": "3px",
            }),
        ], style={"marginBottom": "16px"}),
        dcc.Graph(
            id=graph_id,
            config={"displayModeBar": False, "responsive": True},
            style={"height": altura},
        ),
    ], style={
        "background":   C["surface"],
        "border":       f"1px solid {C['border']}",
        "borderRadius": "12px",
        "padding":      "22px 22px 16px",
    })


# ══════════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN DE LA APLICACIÓN
# ══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    title="Inteligencia Financiera · Odoo 18",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "theme-color", "content": C["bg"]},
    ],
    suppress_callback_exceptions=True,
)
server = app.server  # Punto de entrada WSGI para gunicorn / despliegue en producción


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUCTURA DE LA INTERFAZ (LAYOUT)
# ══════════════════════════════════════════════════════════════════════════════

app.layout = html.Div([

    # ── Barra de navegación superior (sticky) ─────────────────────────────────
    html.Div([
        html.Div([

            # Marca / Logotipo
            html.Div([
                html.Div([
                    html.Span("◈", style={"color": C["accent"], "fontSize": "18px", "lineHeight": "1"}),
                    html.Div([
                        html.Span("Inteligencia Financiera ", style={
                            "color": C["text"], "fontWeight": "800",
                            "fontSize": "15px", "letterSpacing": "-0.03em",
                        }),
                        html.Span("ODOO 18", style={
                            "color": C["accent"], "fontSize": "9px", "fontWeight": "700",
                            "letterSpacing": "0.15em", "background": C["accent"] + "18",
                            "padding": "2px 8px", "borderRadius": "20px",
                            "border": f"1px solid {C['accent']}33",
                            "verticalAlign": "middle", "marginLeft": "8px",
                        }),
                    ]),
                ], style={"display": "flex", "alignItems": "center", "gap": "10px"}),
                html.Div(id="ultima-actualizacion", style={"color": C["muted"], "fontSize": "10px"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "24px"}),

            # Controles de filtrado
            html.Div([
                # Selector de rango de fechas
                html.Div([
                    html.Div("PERIODO", style={
                        "color": C["muted"], "fontSize": "9px", "fontWeight": "700",
                        "letterSpacing": "0.12em", "marginBottom": "8px",
                    }),
                    dcc.DatePickerRange(
                        id="rango-fechas",
                        start_date=(datetime.today() - timedelta(days=90)).date(),
                        end_date=datetime.today().date(),
                        display_format="DD MMM YYYY",
                        first_day_of_week=1,
                    ),
                ]),

                # Slider de escenario de riesgo
                html.Div([
                    html.Div([
                        html.Span("ESCENARIO DE RIESGO — IMPAGOS:", style={
                            "color": C["muted"], "fontSize": "9px",
                            "fontWeight": "700", "letterSpacing": "0.12em",
                        }),
                        html.Span(id="etiqueta-riesgo", style={
                            "color": C["red"], "fontWeight": "800",
                            "fontSize": "12px", "marginLeft": "8px",
                        }),
                    ], style={"marginBottom": "10px"}),
                    dcc.Slider(
                        id="slider-riesgo",
                        min=0, max=50, step=5, value=0,
                        marks={i: {
                            "label": f"{i}%",
                            "style": {"color": C["muted"], "fontSize": "10px"},
                        } for i in range(0, 51, 10)},
                        tooltip={"placement": "top", "always_visible": False},
                    ),
                ], style={"width": "340px"}),

            ], style={"display": "flex", "gap": "32px", "alignItems": "flex-end"}),

        ], style={
            "display":        "flex",
            "justifyContent": "space-between",
            "alignItems":     "flex-end",
            "maxWidth":       "1440px",
            "margin":         "0 auto",
            "padding":        "0 28px",
            "flexWrap":       "wrap",
            "gap":            "20px",
        }),
    ], style={
        "background":   C["surface"],
        "borderBottom": f"1px solid {C['border']}",
        "padding":      "18px 0",
        "position":     "sticky",
        "top":          "0",
        "zIndex":       "200",
    }),

    # ── Cuerpo principal ──────────────────────────────────────────────────────
    html.Div([

        # Fila de KPIs
        html.Div(id="fila-kpis", style={
            "display":      "flex",
            "gap":          "12px",
            "flexWrap":     "wrap",
            "marginBottom": "20px",
        }),

        # Cuadrícula de gráficos — 2 columnas
        html.Div([

            # Fila 1: Proyección de flujo de caja (ancho completo)
            html.Div(
                tarjeta_grafico(
                    "Proyección de Flujo de Caja — 90 días",
                    "Ingresos · Egresos · Saldo acumulado  ·  Ajustado por escenario de impagos",
                    "grafico-cashflow", "360px",
                ),
                style={"gridColumn": "1 / -1"},
            ),

            # Fila 2: Comparación mensual + Antigüedad de cartera
            tarjeta_grafico(
                "Facturado vs. Cobrado",
                "Últimos 12 meses  ·  Facturas de cliente  ·  Tasa de cobro %",
                "grafico-comparacion",
            ),
            tarjeta_grafico(
                "Cartera Vencida por Antigüedad",
                "Cuentas por cobrar  ·  Estado vencido  ·  Clasificadas por tramo",
                "grafico-antiguedad",
            ),

        ], style={
            "display":             "grid",
            "gridTemplateColumns": "repeat(2, 1fr)",
            "gap":                 "16px",
        }),

    ], style={
        "maxWidth": "1440px",
        "margin":   "0 auto",
        "padding":  "24px 28px 40px",
    }),

    # Pie de página
    html.Div(
        f"Dashboard de Inteligencia Financiera  ·  Odoo 18  ·  {datetime.today().year}  ·  ETL → Staging → Visualización",
        style={
            "textAlign":     "center",
            "color":         C["muted"],
            "fontSize":      "10px",
            "padding":       "20px",
            "borderTop":     f"1px solid {C['border']}",
            "letterSpacing": "0.05em",
        }
    ),

], style={"minHeight": "100vh", "background": C["bg"]})


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — Lógica de actualización reactiva
#
# Todas las salidas son accionadas por slider-riesgo + rango-fechas.
# Los datos se obtienen una sola vez por ciclo de callback mediante
# get_dashboard_data() — nunca una llamada por gráfico.
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("etiqueta-riesgo",    "children"),
    Output("ultima-actualizacion", "children"),
    Output("fila-kpis",          "children"),
    Output("grafico-cashflow",   "figure"),
    Output("grafico-comparacion","figure"),
    Output("grafico-antiguedad", "figure"),
    Input("slider-riesgo",       "value"),
    Input("rango-fechas",        "start_date"),
    Input("rango-fechas",        "end_date"),
)
def actualizar_dashboard(pct_riesgo, fecha_inicio, fecha_fin):
    pct_riesgo    = pct_riesgo or 0
    tasa_impago   = pct_riesgo / 100

    # ── Una sola llamada ETL — todos los gráficos comparten este payload ──────
    datos   = get_dashboard_data(tasa_impago)
    kpis    = datos["kpis"]
    staging = datos["staging"].copy()

    # Aplicar filtro de fechas del selector en el header
    if fecha_inicio and fecha_fin:
        staging = staging[
            (staging["invoice_date"] >= pd.Timestamp(fecha_inicio)) &
            (staging["invoice_date"] <= pd.Timestamp(fecha_fin))
        ]

    # ── Textos de estado ──────────────────────────────────────────────────────
    etiqueta_riesgo     = f"{pct_riesgo}%"
    ultima_actualizacion = f"Actualizado {datetime.now().strftime('%H:%M:%S')}"

    # ── Colores semáforo por umbrales de negocio ──────────────────────────────
    c_runway = C["green"] if kpis["cash_runway"] > 6 else C["amber"] if kpis["cash_runway"] > 3 else C["red"]
    c_dso    = C["green"] if kpis["dso"] < 30 else C["amber"] if kpis["dso"] < 45 else C["red"]
    c_liq    = C["green"] if kpis["liquidity_ratio"] > 1.5 else C["amber"] if kpis["liquidity_ratio"] > 1 else C["red"]

    tarjetas_kpi = [
        kpi_card("Saldo Líquido",  f"${kpis['total_cash']:,.0f}",
                 "Banco + Caja  ·  Diarios Odoo",          C["accent"],  "ACTIVO",   C["accent"]),
        kpi_card("DSO",            f"{kpis['dso']} d",
                 "Días promedio de cobro",                  c_dso,        "KPI",      c_dso),
        kpi_card("Burn Rate",      f"${kpis['burn_rate']:,.0f}",
                 "Egreso operativo mensual  ·  3 meses",    C["text"]),
        kpi_card("Cash Runway",    f"{kpis['cash_runway']} m",
                 "Meses de supervivencia financiera",        c_runway,
                 "CRÍTICO" if kpis["cash_runway"] < 3 else "OK",
                 C["red"] if kpis["cash_runway"] < 3 else C["green"]),
        kpi_card("C×C Total",      f"${kpis['total_ar']:,.0f}",
                 "Cuentas por cobrar pendientes",            C["amber"],   "AR"),
        kpi_card("C×C Vencida",    f"${kpis['overdue_ar']:,.0f}",
                 "Facturas con fecha de vencimiento pasada", C["red"],     "VENCIDA",  C["red"]),
        kpi_card("Ratio Liquidez", f"{kpis['liquidity_ratio']:.2f}×",
                 "Activo líquido / Pasivo corriente",        c_liq,        "RATIO",    c_liq),
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 1 — Proyección de Flujo de Caja (Áreas Apiladas)
    # ══════════════════════════════════════════════════════════════════════════
    fc   = datos["cashflow_projection"]
    fig1 = go.Figure()

    # Área de ingresos esperados
    fig1.add_trace(go.Scatter(
        x=fc["date"], y=fc["inflow"],
        name="Ingresos esperados",
        fill="tozeroy", mode="lines",
        line=dict(color=C["green"], width=1.5),
        fillcolor="rgba(16,185,129,0.12)",
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Ingreso: <b>$%{y:,.0f}</b><extra></extra>",
    ))

    # Área de egresos esperados (espejada al negativo)
    fig1.add_trace(go.Scatter(
        x=fc["date"], y=[-v for v in fc["outflow"]],
        name="Egresos esperados",
        fill="tozeroy", mode="lines",
        line=dict(color=C["red"], width=1.5),
        fillcolor="rgba(239,68,68,0.12)",
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Egreso: <b>$%{y:,.0f}</b><extra></extra>",
    ))

    # Saldo proyectado acumulado (eje derecho)
    fig1.add_trace(go.Scatter(
        x=fc["date"], y=fc["balance"],
        name="Saldo proyectado",
        mode="lines",
        line=dict(color=C["accent"], width=2, dash="dot"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Saldo: <b>$%{y:,.0f}</b><extra></extra>",
    ))

    # Línea de equilibrio en cero
    fig1.add_hline(y=0, line_color=C["border"], line_width=1)

    # Anotación de escenario de riesgo activo
    if pct_riesgo > 0:
        fig1.add_annotation(
            text=f"⚠ Escenario activo: {pct_riesgo}% impagos",
            xref="paper", yref="paper", x=0.01, y=0.95,
            showarrow=False,
            font=dict(color=C["amber"], size=11, family=FUENTE),
            bgcolor=C["surface2"],
            bordercolor=C["amber"],
            borderwidth=1,
            borderpad=6,
        )

    fig1.update_layout(
        **LAYOUT_BASE,
        yaxis2=dict(
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=C["accent"], size=10),
            tickprefix="$",
            zeroline=False,
            showgrid=False,
        ),
        yaxis=dict(**LAYOUT_BASE["yaxis"], tickprefix="$"),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 2 — Facturado vs. Cobrado (Barras Agrupadas + Línea)
    # ══════════════════════════════════════════════════════════════════════════
    mensual = datos["monthly_comparison"]
    fig2    = go.Figure()

    fig2.add_trace(go.Bar(
        x=mensual["month_dt"],
        y=mensual["invoiced"],
        name="Facturado",
        marker=dict(color=C["accent"], opacity=0.8, cornerradius=3),
        hovertemplate="<b>%{x|%b %Y}</b><br>Facturado: <b>$%{y:,.0f}</b><extra></extra>",
    ))
    fig2.add_trace(go.Bar(
        x=mensual["month_dt"],
        y=mensual["collected"],
        name="Cobrado",
        marker=dict(color=C["green"], opacity=0.8, cornerradius=3),
        hovertemplate="<b>%{x|%b %Y}</b><br>Cobrado: <b>$%{y:,.0f}</b><extra></extra>",
    ))
    # Tasa de cobro en eje secundario
    fig2.add_trace(go.Scatter(
        x=mensual["month_dt"],
        y=mensual["collection_rate"],
        name="% Cobro",
        mode="lines+markers",
        yaxis="y2",
        line=dict(color=C["amber"], width=2),
        marker=dict(size=5, color=C["amber"], line=dict(color=C["bg"], width=1.5)),
        hovertemplate="<b>%{x|%b %Y}</b><br>Tasa: <b>%{y:.1f}%</b><extra></extra>",
    ))
    fig2.update_layout(
        **LAYOUT_BASE,
        barmode="group",
        bargap=0.22,
        yaxis=dict(**LAYOUT_BASE["yaxis"], tickprefix="$"),
        yaxis2=dict(
            overlaying="y", side="right",
            range=[0, 125], ticksuffix="%",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=C["amber"], size=10),
            zeroline=False,
            showgrid=False,
        ),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # GRÁFICO 3 — Antigüedad de Cartera (Barras Horizontales)
    # ══════════════════════════════════════════════════════════════════════════
    vencidas = staging[
        (staging["move_type"] == "out_invoice") & staging["is_overdue"]
    ].copy()

    # Clasificación por tramos de antigüedad
    bins   = [0, 30, 60, 90, float("inf")]
    labels = ["1 – 30 días", "31 – 60 días", "61 – 90 días", "+90 días"]
    vencidas["tramo"] = pd.cut(vencidas["days_overdue"], bins=bins, labels=labels)

    antiguedad = (
        vencidas.groupby("tramo", observed=True)["amount_residual"]
        .sum().reset_index()
    )
    colores_antiguedad = [C["green"], C["amber"], C["accent2"], C["red"]]

    fig3 = go.Figure(go.Bar(
        y=antiguedad["tramo"],
        x=antiguedad["amount_residual"],
        orientation="h",
        marker=dict(
            color=colores_antiguedad[:len(antiguedad)],
            opacity=0.85,
            cornerradius=4,
        ),
        text=[f"  ${v:,.0f}" for v in antiguedad["amount_residual"]],
        textposition="outside",
        textfont=dict(color=C["text"], size=11),
        hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
    ))
    fig3.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(**LAYOUT_BASE["xaxis"], tickprefix="$"),
        yaxis=dict(**LAYOUT_BASE["yaxis"], showgrid=False),
        showlegend=False,
    )

    return etiqueta_riesgo, ultima_actualizacion, tarjetas_kpi, fig1, fig2, fig3


# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, port=8050, host="0.0.0.0")
