"""
JARVIS Analytics Tools — file analysis + Plotly chart generation.

All chart functions return a Plotly figure spec as a plain dict
(JSON-serialisable) so the frontend can render it with Plotly.js.
The `ui_command` key tells the frontend to open the analytics panel.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_dataframe(path: str):
    """Load CSV / Excel / JSON into a pandas DataFrame."""
    import pandas as pd
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in (".xls", ".xlsx", ".xlsm"):
        return pd.read_excel(path)
    if ext == ".json":
        return pd.read_json(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    raise ValueError(f"Unsupported file type: {ext}")


def _numeric_cols(df) -> list[str]:
    import pandas as pd
    return df.select_dtypes(include="number").columns.tolist()


def _category_cols(df) -> list[str]:
    import pandas as pd
    return df.select_dtypes(exclude="number").columns.tolist()


# ── file analysis ─────────────────────────────────────────────────────────────

async def analyze_file(path: str, question: str = "") -> dict:
    """
    Load a data file, compute summary statistics, and return a rich profile
    plus a Plotly overview chart spec.
    """
    import pandas as pd

    try:
        df = _load_dataframe(path)
    except Exception as exc:
        return {"error": str(exc)}

    rows, cols = df.shape
    num_cols = _numeric_cols(df)
    cat_cols = _category_cols(df)

    # ── summary stats ─────────────────────────────────────────────────────────
    stats: dict[str, Any] = {}
    if num_cols:
        desc = df[num_cols].describe().round(3)
        stats = desc.to_dict()

    # ── missing values ────────────────────────────────────────────────────────
    missing = df.isnull().sum()
    missing_info = {c: int(v) for c, v in missing.items() if v > 0}

    # ── correlations ──────────────────────────────────────────────────────────
    correlations: dict = {}
    if len(num_cols) >= 2:
        corr = df[num_cols].corr().round(3)
        correlations = corr.to_dict()

    # ── overview chart: heatmap of correlations or bar of first numeric col ──
    overview_chart = None
    if len(num_cols) >= 2:
        overview_chart = _correlation_heatmap(df, num_cols)
    elif num_cols:
        overview_chart = _bar_chart(df, num_cols[0], cat_cols[0] if cat_cols else None)

    summary = {
        "rows": rows,
        "columns": cols,
        "column_names": df.columns.tolist(),
        "numeric_columns": num_cols,
        "categorical_columns": cat_cols,
        "missing_values": missing_info,
        "statistics": stats,
        "correlations": correlations,
        "sample_head": df.head(5).to_dict(orient="records"),
    }

    result: dict[str, Any] = {
        "file": Path(path).name,
        "summary": summary,
    }
    if overview_chart:
        result["chart"] = overview_chart
        result["ui_command"] = "show_chart"

    return result


# ── chart generators ──────────────────────────────────────────────────────────

async def plot_chart(
    path: str,
    chart_type: str = "auto",
    x_col: str = "",
    y_col: str = "",
    color_col: str = "",
    title: str = "",
) -> dict:
    """
    Generate a Plotly chart from an uploaded file.
    chart_type: auto | bar | line | scatter | histogram | pie | box | heatmap
    """
    import pandas as pd

    try:
        df = _load_dataframe(path)
    except Exception as exc:
        return {"error": str(exc)}

    num_cols = _numeric_cols(df)
    cat_cols = _category_cols(df)

    # resolve columns
    x = x_col if x_col in df.columns else (cat_cols[0] if cat_cols else (num_cols[0] if num_cols else ""))
    y = y_col if y_col in df.columns else (num_cols[0] if num_cols else "")
    clr = color_col if color_col in df.columns else ""

    if chart_type == "auto":
        if len(num_cols) >= 2:
            chart_type = "scatter"
        elif num_cols and cat_cols:
            chart_type = "bar"
        else:
            chart_type = "histogram"

    spec: dict[str, Any] = {}

    if chart_type == "bar":
        spec = _bar_chart(df, y, x, color=clr, title=title or f"{y} by {x}")
    elif chart_type == "line":
        spec = _line_chart(df, x, y, color=clr, title=title or f"{y} over {x}")
    elif chart_type == "scatter":
        y2 = num_cols[1] if len(num_cols) > 1 else y
        spec = _scatter_chart(df, x if x in num_cols else (num_cols[0] if num_cols else x),
                              y2, color=clr, title=title or f"{num_cols[0] if num_cols else x} vs {y2}")
    elif chart_type == "histogram":
        col = y if y in num_cols else (num_cols[0] if num_cols else x)
        spec = _histogram(df, col, title=title or f"Distribution of {col}")
    elif chart_type == "pie":
        spec = _pie_chart(df, x, y, title=title or f"{y} share by {x}")
    elif chart_type == "box":
        spec = _box_chart(df, x, y, title=title or f"{y} distribution by {x}")
    elif chart_type == "heatmap":
        spec = _correlation_heatmap(df, num_cols, title=title or "Correlation Matrix")
    else:
        spec = _bar_chart(df, y, x, title=title or f"{y} by {x}")

    if not spec:
        return {"error": "Could not generate chart — check column names"}

    spec["ui_command"] = "show_chart"
    return spec


async def plot_3d(
    path: str,
    x_col: str = "",
    y_col: str = "",
    z_col: str = "",
    color_col: str = "",
    chart_type: str = "scatter3d",
    title: str = "",
) -> dict:
    """
    Generate a 3D Plotly chart (scatter3d or surface) from an uploaded file.
    chart_type: scatter3d | surface | line3d
    """
    import pandas as pd
    import numpy as np

    try:
        df = _load_dataframe(path)
    except Exception as exc:
        return {"error": str(exc)}

    num_cols = _numeric_cols(df)
    if len(num_cols) < 2:
        return {"error": "Need at least 2 numeric columns for a 3D chart"}

    x = x_col if x_col in num_cols else num_cols[0]
    y = y_col if y_col in num_cols else (num_cols[1] if len(num_cols) > 1 else num_cols[0])
    z = z_col if z_col in num_cols else (num_cols[2] if len(num_cols) > 2 else num_cols[0])

    df_clean = df[[x, y, z]].dropna()
    clr_data = None
    if color_col and color_col in df.columns:
        clr_data = df.loc[df_clean.index, color_col].tolist()

    t = title or f"3D {chart_type.replace('3d','').replace('_',' ').title()}: {x} / {y} / {z}"

    if chart_type == "surface":
        # pivot to grid
        try:
            pivot = df_clean.pivot_table(index=y, columns=x, values=z, aggfunc="mean")
            trace = {
                "type": "surface",
                "x": pivot.columns.tolist(),
                "y": pivot.index.tolist(),
                "z": pivot.values.tolist(),
                "colorscale": "Viridis",
                "opacity": 0.85,
            }
        except Exception:
            # fallback to scatter3d
            chart_type = "scatter3d"

    if chart_type in ("scatter3d", "line3d"):
        mode = "markers" if chart_type == "scatter3d" else "lines+markers"
        marker: dict[str, Any] = {
            "size": 5,
            "opacity": 0.8,
            "colorscale": "Plasma",
        }
        if clr_data:
            marker["color"] = clr_data
            marker["showscale"] = True
        else:
            marker["color"] = df_clean[z].tolist()
            marker["showscale"] = True

        trace = {
            "type": "scatter3d",
            "mode": mode,
            "x": df_clean[x].tolist(),
            "y": df_clean[y].tolist(),
            "z": df_clean[z].tolist(),
            "marker": marker,
            "name": t,
        }

    layout = {
        "title": {"text": t, "font": {"color": "#00d4ff", "size": 16}},
        "paper_bgcolor": "#0a0e1a",
        "plot_bgcolor": "#0a0e1a",
        "font": {"color": "#c0c8d8"},
        "scene": {
            "xaxis": {"title": x, "gridcolor": "#1a2a3a", "color": "#00d4ff"},
            "yaxis": {"title": y, "gridcolor": "#1a2a3a", "color": "#00d4ff"},
            "zaxis": {"title": z, "gridcolor": "#1a2a3a", "color": "#00d4ff"},
            "bgcolor": "#0a0e1a",
        },
        "margin": {"l": 0, "r": 0, "t": 40, "b": 0},
    }

    return {
        "ui_command": "show_chart",
        "chart_type": "3d",
        "plotly": {"data": [trace], "layout": layout},
    }


async def plot_neural_network(
    path: str = "",
    layer_sizes: list[int] | None = None,
    title: str = "",
) -> dict:
    """
    Render an interactive 3D neural network graph.
    If a file is provided, infer layer sizes from column count.
    Otherwise, use layer_sizes (e.g. [4, 8, 8, 3]) or default to a demo.
    """
    import numpy as np

    if path:
        try:
            df = _load_dataframe(path)
            num_cols = _numeric_cols(df)
            n_in = len(num_cols)
            n_out = max(1, len(_category_cols(df)))
            hidden = max(4, n_in * 2)
            layer_sizes = [n_in, hidden, hidden // 2, n_out]
        except Exception:
            pass

    if not layer_sizes:
        layer_sizes = [4, 8, 6, 4, 2]

    # ── build 3D node positions ───────────────────────────────────────────────
    node_x, node_y, node_z = [], [], []
    node_labels = []
    edge_x, edge_y, edge_z = [], [], []

    LAYER_NAMES = ["Input", "Hidden", "Output"]

    for l_idx, n_nodes in enumerate(layer_sizes):
        lx = l_idx * 2.0
        layer_name = (
            "Input" if l_idx == 0
            else "Output" if l_idx == len(layer_sizes) - 1
            else f"Hidden {l_idx}"
        )
        for n_idx in range(n_nodes):
            # spread nodes on a circle in the yz plane
            angle = (2 * math.pi * n_idx / max(n_nodes, 1))
            radius = max(0.8, n_nodes * 0.18)
            ny = radius * math.cos(angle)
            nz = radius * math.sin(angle)
            node_x.append(lx)
            node_y.append(ny)
            node_z.append(nz)
            node_labels.append(f"{layer_name}<br>Node {n_idx + 1}")

    # edges between adjacent layers
    offset = 0
    layer_offsets = []
    for size in layer_sizes:
        layer_offsets.append(offset)
        offset += size

    for l_idx in range(len(layer_sizes) - 1):
        start = layer_offsets[l_idx]
        end = layer_offsets[l_idx + 1]
        n_curr = layer_sizes[l_idx]
        n_next = layer_sizes[l_idx + 1]
        for i in range(n_curr):
            for j in range(n_next):
                n1 = start + i
                n2 = end + j
                edge_x += [node_x[n1], node_x[n2], None]
                edge_y += [node_y[n1], node_y[n2], None]
                edge_z += [node_z[n1], node_z[n2], None]

    edge_trace = {
        "type": "scatter3d",
        "mode": "lines",
        "x": edge_x,
        "y": edge_y,
        "z": edge_z,
        "line": {"width": 1, "color": "rgba(0,180,255,0.15)"},
        "hoverinfo": "none",
        "name": "Connections",
    }

    # colour nodes by layer
    layer_colors = [
        "#00ffcc",  # input — cyan
        "#00aaff",  # hidden — blue
        "#ff6600",  # output — orange
    ]
    node_colors = []
    for l_idx, size in enumerate(layer_sizes):
        clr = (
            layer_colors[0] if l_idx == 0
            else layer_colors[2] if l_idx == len(layer_sizes) - 1
            else layer_colors[1]
        )
        node_colors.extend([clr] * size)

    node_trace = {
        "type": "scatter3d",
        "mode": "markers+text",
        "x": node_x,
        "y": node_y,
        "z": node_z,
        "text": node_labels,
        "hovertext": node_labels,
        "hoverinfo": "text",
        "marker": {
            "size": 10,
            "color": node_colors,
            "opacity": 0.9,
            "line": {"width": 1, "color": "#ffffff22"},
        },
        "name": "Neurons",
    }

    t = title or f"Neural Network — {' × '.join(str(s) for s in layer_sizes)}"

    layout = {
        "title": {"text": t, "font": {"color": "#00d4ff", "size": 16}},
        "paper_bgcolor": "#050a14",
        "plot_bgcolor": "#050a14",
        "font": {"color": "#c0c8d8"},
        "scene": {
            "xaxis": {"title": "Layer", "gridcolor": "#112233", "color": "#335577", "showticklabels": False},
            "yaxis": {"title": "", "gridcolor": "#112233", "color": "#335577", "showticklabels": False},
            "zaxis": {"title": "", "gridcolor": "#112233", "color": "#335577", "showticklabels": False},
            "bgcolor": "#050a14",
            "camera": {"eye": {"x": 1.5, "y": 1.5, "z": 0.8}},
        },
        "margin": {"l": 0, "r": 0, "t": 50, "b": 0},
        "showlegend": True,
        "legend": {"font": {"color": "#c0c8d8"}, "bgcolor": "#0a0e1a"},
    }

    return {
        "ui_command": "show_chart",
        "chart_type": "neural_network",
        "layer_sizes": layer_sizes,
        "plotly": {"data": [edge_trace, node_trace], "layout": layout},
    }


async def get_data_summary(path: str) -> dict:
    """Return a concise text summary of an uploaded file for JARVIS to speak."""
    try:
        df = _load_dataframe(path)
    except Exception as exc:
        return {"error": str(exc)}

    import pandas as pd

    rows, cols = df.shape
    num_cols = _numeric_cols(df)
    cat_cols = _category_cols(df)
    missing_total = int(df.isnull().sum().sum())

    insights = []
    for col in num_cols[:4]:
        s = df[col].describe()
        insights.append(
            f"{col}: mean={s['mean']:.2f}, min={s['min']:.2f}, max={s['max']:.2f}"
        )

    return {
        "file": Path(path).name,
        "rows": rows,
        "columns": cols,
        "numeric_columns": num_cols,
        "categorical_columns": cat_cols,
        "missing_values": missing_total,
        "column_insights": insights,
        "column_names": df.columns.tolist(),
    }


# ── internal chart builders ───────────────────────────────────────────────────

def _jarvis_layout(title: str = "") -> dict:
    base: dict[str, Any] = {
        "paper_bgcolor": "#0a0e1a",
        "plot_bgcolor": "#0a0e1a",
        "font": {"color": "#c0c8d8", "family": "Rajdhani, monospace"},
        "xaxis": {"gridcolor": "#1a2a3a", "linecolor": "#1a2a3a", "color": "#00d4ff"},
        "yaxis": {"gridcolor": "#1a2a3a", "linecolor": "#1a2a3a", "color": "#00d4ff"},
        "margin": {"l": 50, "r": 20, "t": 50, "b": 50},
        "colorway": ["#00d4ff", "#ff6600", "#00ff99", "#cc00ff", "#ffcc00"],
    }
    if title:
        base["title"] = {"text": title, "font": {"color": "#00d4ff", "size": 15}}
    return base


def _bar_chart(df, y_col: str, x_col: str | None = None, color: str = "", title: str = "") -> dict:
    import pandas as pd
    if not y_col or y_col not in df.columns:
        return {}
    layout = _jarvis_layout(title)
    if x_col and x_col in df.columns:
        grouped = df.groupby(x_col)[y_col].mean().reset_index()
        trace = {
            "type": "bar",
            "x": grouped[x_col].tolist(),
            "y": grouped[y_col].round(3).tolist(),
            "marker": {"color": "#00d4ff", "opacity": 0.85},
            "name": y_col,
        }
    else:
        top = df[y_col].value_counts().head(20) if df[y_col].dtype == object else df[y_col].head(30)
        trace = {
            "type": "bar",
            "x": top.index.tolist(),
            "y": top.values.tolist(),
            "marker": {"color": "#00d4ff", "opacity": 0.85},
            "name": y_col,
        }
    return {"plotly": {"data": [trace], "layout": layout}}


def _line_chart(df, x_col: str, y_col: str, color: str = "", title: str = "") -> dict:
    if not all(c in df.columns for c in [x_col, y_col]):
        return {}
    df_s = df[[x_col, y_col]].dropna().sort_values(x_col)
    trace = {
        "type": "scatter",
        "mode": "lines+markers",
        "x": df_s[x_col].tolist(),
        "y": df_s[y_col].tolist(),
        "line": {"color": "#00d4ff", "width": 2},
        "marker": {"size": 4, "color": "#00ff99"},
        "name": y_col,
    }
    return {"plotly": {"data": [trace], "layout": _jarvis_layout(title)}}


def _scatter_chart(df, x_col: str, y_col: str, color: str = "", title: str = "") -> dict:
    if not all(c in df.columns for c in [x_col, y_col]):
        return {}
    df_s = df[[x_col, y_col]].dropna()
    marker: dict[str, Any] = {"size": 6, "opacity": 0.7, "color": "#00d4ff"}
    if color and color in df.columns:
        marker["color"] = df.loc[df_s.index, color].tolist()
        marker["colorscale"] = "Plasma"
        marker["showscale"] = True
    trace = {
        "type": "scatter",
        "mode": "markers",
        "x": df_s[x_col].tolist(),
        "y": df_s[y_col].tolist(),
        "marker": marker,
        "name": f"{x_col} vs {y_col}",
    }
    return {"plotly": {"data": [trace], "layout": _jarvis_layout(title)}}


def _histogram(df, col: str, title: str = "") -> dict:
    if col not in df.columns:
        return {}
    trace = {
        "type": "histogram",
        "x": df[col].dropna().tolist(),
        "marker": {"color": "#00d4ff", "opacity": 0.8},
        "nbinsx": 30,
        "name": col,
    }
    return {"plotly": {"data": [trace], "layout": _jarvis_layout(title)}}


def _pie_chart(df, label_col: str, value_col: str, title: str = "") -> dict:
    if not all(c in df.columns for c in [label_col, value_col]):
        return {}
    grp = df.groupby(label_col)[value_col].sum().head(12)
    trace = {
        "type": "pie",
        "labels": grp.index.tolist(),
        "values": grp.values.tolist(),
        "hole": 0.3,
        "marker": {"colors": ["#00d4ff","#ff6600","#00ff99","#cc00ff","#ffcc00",
                               "#ff3366","#33ccff","#ffaa00","#00ffcc","#9966ff",
                               "#ff6699","#66ff99"]},
    }
    layout = _jarvis_layout(title)
    layout["paper_bgcolor"] = "#0a0e1a"
    return {"plotly": {"data": [trace], "layout": layout}}


def _box_chart(df, x_col: str, y_col: str, title: str = "") -> dict:
    if y_col not in df.columns:
        return {}
    trace: dict[str, Any] = {
        "type": "box",
        "y": df[y_col].dropna().tolist(),
        "name": y_col,
        "marker": {"color": "#00d4ff"},
        "boxmean": True,
    }
    if x_col and x_col in df.columns:
        trace["x"] = df[x_col].tolist()
        trace["boxpoints"] = "outliers"
    return {"plotly": {"data": [trace], "layout": _jarvis_layout(title)}}


def _correlation_heatmap(df, num_cols: list[str], title: str = "Correlation Matrix") -> dict:
    if len(num_cols) < 2:
        return {}
    corr = df[num_cols].corr().round(3)
    trace = {
        "type": "heatmap",
        "x": num_cols,
        "y": num_cols,
        "z": corr.values.tolist(),
        "colorscale": "RdBu",
        "zmid": 0,
        "text": corr.round(2).values.tolist(),
        "texttemplate": "%{text}",
        "showscale": True,
    }
    layout = _jarvis_layout(title)
    layout["xaxis"]["tickangle"] = -30
    return {"plotly": {"data": [trace], "layout": layout}}
