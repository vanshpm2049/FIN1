# === Bintix Waste Analytics — CSV-only (All Variables Included) ===
# Variables: Tonnage, Trees_Saved, CO2_Kgs_Averted, Households_Participation_Percent, Segregation_Compliance_Percent
# CSV Upload Only Mode

import re
import io
import base64
import mimetypes
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
import folium
from folium.plugins import MarkerCluster, HeatMap
import plotly.express as px
import plotly.graph_objects as go
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt
from matplotlib import colormaps
from branca.element import MacroElement, IFrame
from jinja2 import Template
import pydeck as pdk
from datetime import datetime

# ---------------- App & Brand ----------------
st.set_page_config(page_title="Bintix Waste Analytics", layout="wide")

BRAND_PRIMARY = 'purple'
TEXT_DARK = "#36204D"

# Speed settings
ST_MAP_HEIGHT = 900
ST_RETURNED_OBJECTS = []  # don't send all map layers back to Streamlit

# --- Environmental conversions ---
CO2_PER_KG_DRY = 2.18  # 1 kg dry waste -> 2.18 kg CO2 averted
KG_PER_TREE = 117.0     # 117 kg dry waste -> 1 tree saved

# ---------------- Assets (icons) ----------------
BASE_DIR = Path(__file__).parent.resolve()
_ASSET_DIR_CANDIDATES = [BASE_DIR / "assets", BASE_DIR / "assests"]
ASSETS_DIR = next((p for p in _ASSET_DIR_CANDIDATES if p.exists()), _ASSET_DIR_CANDIDATES[0])

@st.cache_resource(show_spinner=False)
def load_icon_data_uri(filename: str) -> str:
    """Return a data: URI for an image in ASSETS_DIR so it renders inside Folium popups."""
    p = ASSETS_DIR / filename
    if not p.exists():
        raise FileNotFoundError(f"Icon not found: {p}")
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"

try:
    TREE_ICON = load_icon_data_uri("tree.png")
    HOUSE_ICON = load_icon_data_uri("house.png")
    RECYCLE_ICON = load_icon_data_uri("waste-management.png")
except FileNotFoundError as e:
    st.warning(f"{e}\nUsing default markers instead.")
    TREE_ICON = HOUSE_ICON = RECYCLE_ICON = ""

# ---------------- Helper Functions ----------------
def create_trend_chart_base64(community_data, metric_name, color='purple'):
    """Create a small trend chart and return as base64 encoded PNG."""
    if community_data.empty:
        return None
    
    fig, ax = plt.subplots(figsize=(5, 3), dpi=80)
    ax.plot(community_data['Date'], community_data['Value'], marker='o', color=color, linewidth=2, markersize=4)
    ax.set_title(f'{metric_name} Trend', fontsize=10, fontweight='bold')
    ax.set_xlabel('Date', fontsize=8)
    ax.set_ylabel('Value', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Convert to base64
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    
    return img_base64

# ---------------- Data loading (CSV only - Upload Required) ----------------
# ALL variables from CSV
VARIABLES_REQUIRED = [
    "Tonnage",
    "Trees_Saved",
    "CO2_Kgs_Averted",
    "Households_Participation_Percent",
    "Segregation_Compliance_Percent"
]
ID_COLS_REQUIRED = ["City", "Community", "Pincode"]
ID_COLS_OPTIONAL = ["Latitude", "Longitude", "community_id"]



# --- Helpers for charts/popups (from PM.py) ---
def _to_data_uri(fig, w=340):
    buf = io.BytesIO()
    plt.tight_layout(pad=0.3)
    fig.savefig(buf, format="png", bbox_inches="tight", transparent=True, dpi=180)
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"<img src='data:image/png;base64,{b64}' style='width:{w}px;height:auto;border:0;'/>"


def _distinct_colors(n):
    cmaps = [plt.cm.tab20, plt.cm.Set3, plt.cm.Pastel1]
    colors = []
    i = 0
    while len(colors) < n:
        cmap = cmaps[i % len(cmaps)]
        M = cmap.N
        take = min(n - len(colors), M)
        for j in range(take):
            colors.append(cmap(j / max(M - 1, 1)))
        i += 1
    return colors[:n]


def popup_charts_for_comm(dfl_filtered: pd.DataFrame, community_id: str):
    BRAND = BRAND_PRIMARY
    dm = dfl_filtered.copy()
    dm["Community"] = dm["Community"].astype(str)
    dm = dm[dm["Community"] == str(community_id)]
    if dm.empty:
        return "", ""

    dm["MonthKey"] = dm["Date"].dt.to_period("M")

    # ------------------ TONNAGE (Plotly static PNG for popup) ------------------
    import plotly.express as px
    import plotly.io as pio

    bar_img = ""
    d_ton = dm[dm["Metric"] == "Tonnage"][["MonthKey", "Value"]].copy()
    if not d_ton.empty:
        d_ton["MonthLabel"] = [period.to_timestamp().strftime("%b") for period in d_ton["MonthKey"]]
        fig, ax = plt.subplots(figsize=(4.0, 1.4), dpi=120)
        ax.plot(d_ton["MonthLabel"], d_ton["Value"], marker="o", lw=1.6, color=BRAND)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{int(v):,}"))
        ax.tick_params(axis="x", labelsize=8, colors=BRAND)
        ax.tick_params(axis="y", labelsize=8, colors=BRAND)
        ax.grid(alpha=0.12, axis="y")
        plt.xticks(rotation=45)
        bar_img = _to_data_uri(fig, w=380)


            

    # ------------------ CO2 DONUT (Plotly interactive preferred) ------------------
    # ------------------ CO2 DONUT (matplotlib with values) ------------------
    donut_img = ""
    dry_candidates = ["Tonnage_Dry", "Dry_Tonnage", "DryWaste", "Tonnage"]
    dry_month = None
    for m in dry_candidates:
        cur = dm[dm["Metric"] == m][["MonthKey", "Value"]].copy()
        if not cur.empty:
            cur["Value"] = pd.to_numeric(cur["Value"], errors="coerce").fillna(0.0)
            dry_month = cur
            break




    if dry_month is not None:
        d = dry_month.groupby("MonthKey", as_index=False)["Value"].sum().sort_values("MonthKey")
        co2_vals = (d["Value"] * CO2_PER_KG_DRY).clip(lower=0.0).to_numpy()
        labels = [p.to_timestamp().strftime("%b") for p in d["MonthKey"]]
        colors = _distinct_colors(len(labels))

        # --- Donut chart with slice labels ---
        fig, ax = plt.subplots(figsize=(2.3, 2.3), dpi=120)
        wedges, texts, autotexts = ax.pie(
            co2_vals,
            labels=labels,  # ✅ show month beside slice
            autopct=lambda pct: (f'{pct:.1f}%') if pct > 0 else '',
            wedgeprops=dict(width=0.60, edgecolor='white', linewidth=1.2),
            startangle=90,
            colors=colors,
            pctdistance=0.7,
            labeldistance=1.05  # slight spacing between label and slice
        )
        ax.set(aspect="equal")

        # Format labels & percentages
        for t in texts:
            t.set_fontsize(8)
            t.set_color("#36204D")
            t.set_weight("bold")

        from matplotlib.colors import to_rgb
        for wedge, autotext in zip(wedges, autotexts):
            r, g, b = wedge.get_facecolor()[:3]
            lum = 0.2126*r + 0.7152*g + 0.0722*b
            autotext.set_color('#ffffff' if lum < 0.6 else '#222222')
            autotext.set_fontsize(8)
            autotext.set_weight('bold')

        # Center text inside donut
        ax.text(0, 0, "CO₂\nAverted", ha="center", va="center",
                fontsize=10, color='purple', fontweight="bold")

        plt.tight_layout(pad=0.3)
        donut_img = _to_data_uri(fig, w=200)
        plt.close(fig)

        # --- Legend below the donut ---
        

        
        donut_img = f"<div style='text-align:center;'>{donut_img}</div>"
    # return HTML fragments (bar_img and donut_img)
    return bar_img, donut_img

def normalize_column_names(df):
    """
    Normalize column names to match expected format:
    - 'Tonnage Apr 2025' -> 'Tonnage_2025-04'
    - 'Trees Saved May 2025' -> 'Trees_Saved_2025-05'
    - 'Households Participation % Jun 2025' -> 'Households_Participation_Percent_2025-06'
    """
    month_map = {
        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
    }
    
    new_cols = {}
    for col in df.columns:
        # Check if column matches pattern: "Metric Month Year"
        # e.g., "Tonnage Apr 2025" or "Trees Saved Apr 2025" or "Households Participation % Apr 2025"
        pattern = r'^(.+?)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$'
        match = re.match(pattern, col, re.IGNORECASE)
        
        if match:
            metric_raw = match.group(1).strip()
            month_abbr = match.group(2).capitalize()
            year = match.group(3)
            
            # Normalize metric name
            metric_normalized = metric_raw.replace(' ', '_').replace('%', 'Percent')
            
            # Build new column name: Metric_YYYY-MM
            month_num = month_map.get(month_abbr, '01')
            new_col = f"{metric_normalized}_{year}-{month_num}"
            new_cols[col] = new_col
    
    if new_cols:
        df = df.rename(columns=new_cols)
    
    return df

# Regex to detect metric_YYYY-MM columns
METRIC_COL_REGEX = re.compile(
    r"^(Tonnage|Trees_Saved|CO2_Kgs_Averted|Households_Participation_Percent|Segregation_Compliance_Percent)_(\d{4}-\d{2})$"
)

def _detect_metric_month_cols(columns):
    cols, months = [], set()
    for c in columns:
        m = METRIC_COL_REGEX.match(c)
        if m:
            cols.append(c)
            months.add(m.group(2))
    return cols, sorted(months)

@st.cache_data(show_spinner=False)
def load_uploaded(file) -> tuple[pd.DataFrame, pd.DataFrame, list[str], str]:
    df = pd.read_csv(file)
    df.rename(columns={c: c.strip() for c in df.columns}, inplace=True)
    
    # Normalize column names from "Metric Month Year" to "Metric_YYYY-MM"
    df = normalize_column_names(df)
    
    # Check required ID columns
    missing = [c for c in ID_COLS_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    # Detect metric-month columns
    metric_month_cols, months = _detect_metric_month_cols(df.columns)
    if not metric_month_cols:
        raise ValueError(
            f"No metric-month columns found. Expected format: {{Metric}}_YYYY-MM\n"
            f"Supported metrics: {', '.join(VARIABLES_REQUIRED)}"
        )
    
    # Convert metric columns to numeric
    for c in metric_month_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    
    # Identify all ID columns present
    id_cols_present = [c for c in (ID_COLS_REQUIRED + ID_COLS_OPTIONAL) if c in df.columns]
    
    # Melt to long format
    long_df = df.melt(
        id_vars=id_cols_present,
        value_vars=metric_month_cols,
        var_name="Metric_Month",
        value_name="Value"
    )
    
    # Split Metric_Month into Metric and Date
    parts = long_df["Metric_Month"].str.rsplit("_", n=1, expand=True)
    long_df["Metric"] = parts[0]
    long_df["Date"] = pd.to_datetime(parts[1] + "-01", format="%Y-%m-%d")
    long_df = long_df.drop(columns=["Metric_Month"]).sort_values(
        id_cols_present + ["Metric", "Date"]
    )
    
    # Convert string columns
    for c in ["City", "Community", "Pincode"]:
        if c in df.columns:
            df[c] = df[c].astype(str)
        if c in long_df.columns:
            long_df[c] = long_df[c].astype(str)
    
    # Convert numeric columns
    for c in ["Latitude", "Longitude"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    
    return df, long_df, months, f"uploaded: {file.name}"

# ---------------- Sidebar (Upload Only) ----------------
with st.sidebar:
    st.markdown("### 📤 Upload Your Data")
    uploaded = st.file_uploader(
        "Upload CSV File",
        type=["csv"],
        help=(
            "Required columns: City, Community, Pincode, Latitude, Longitude\n"
            "Metric columns format: 'Metric Month Year' (e.g., 'Tonnage Apr 2025')\n\n"
            "Supported Metrics:\n"
            "• Tonnage\n"
            "• Trees Saved\n"
            "• CO2 Kgs Averted\n"
            "• Households Participation %\n"
            "• Segregation Compliance %"
        )
    )
    
    if uploaded is None:
        st.warning("⚠️ Please upload a CSV file to proceed.")
    
    st.markdown("---")
    st.markdown("### 🗺️ Map Type")
    map_type = st.radio(
        "Select Map Type",
        options=["2D Map (Folium)", "3D Map (PyDeck)"],
        index=0,
        help="Choose between 2D interactive map or 3D extruded visualization"
    )
    
    st.markdown("---")
    
    # Only show these options for 2D map
    if map_type == "2D Map (Folium)":
        show_popup_charts = st.toggle(
            "Show trend charts in popups",
            value=True,
            help="Display time series trend charts in map popups (slower to load)",
            key="toggle_popup_charts"
        )
        
        st.caption("Map heatmap options:")
        heatmap_metric = st.selectbox(
            "Heatmap by",
            options=["None", "Tonnage", "Trees Saved", "CO2 Kgs Averted", 
                    "Households Participation %", "Segregation Compliance %"],
            index=0,
            help="Show colored markers by selected metric",
            key="heatmap_metric"
        )
    else:
        # For 3D map
        show_popup_charts = False  # Not applicable for 3D
        heatmap_metric = "None"
        
        extrude_metric = st.selectbox(
            "Extrude by",
            options=["Tonnage", "Trees Saved", "CO2 Kgs Averted", 
                    "Households Participation %", "Segregation Compliance %"],
            index=0,
            help="Height of 3D columns represents this metric",
            key="extrude_metric"
        )

# Check if file is uploaded
if uploaded is None:
    st.error("📁 Please upload a CSV file to get started. Use the upload widget on the left sidebar.")
    st.stop()

# Try to load the uploaded file
try:
    df_wide, df_long, months, data_src = load_uploaded(uploaded)
    st.session_state["df_wide"] = df_wide
    st.session_state["df_long"] = df_long
    st.session_state["months"] = months
    st.session_state["data_src"] = data_src
except Exception as e:
    st.error(f"❌ Error loading dataset: {e}")
    st.stop()

# Minor UI theming
st.markdown(
    """
    <style>
    .main { background-color: #f9f9f9; }
    h1, h2, h3 { color: #36204D; }
    /* Hide the multiselect labels when all items are selected */
    div[data-baseweb="select"] span[data-baseweb="tag"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Load Data from session
df_wide = st.session_state["df_wide"]
df_long = st.session_state["df_long"]
months = st.session_state["months"]
data_src = st.session_state["data_src"]

# Normalize key id columns to STRING (safety)
for col in ["Pincode", "Community", "City"]:
    if col in df_wide.columns:
        df_wide[col] = df_wide[col].astype(str)
    if col in df_long.columns:
        df_long[col] = df_long[col].astype(str)

# Title
st.markdown(
    f"""
    <h1 style='text-align:center; color:{BRAND_PRIMARY};'>
    ♻️ Bintix Waste Analytics Dashboard
    </h1>
    <p style='text-align:center; color:gray;'>CSV Upload Mode — All Metrics Included</p>
    """,
    unsafe_allow_html=True
)

# ---------------- Filter Controls ----------------
st.markdown("### 🔍 Filters")
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    cities_all = sorted(df_wide["City"].dropna().unique())
    
    # Initialize filter state if not exists
    if "city_filter_initialized" not in st.session_state:
        st.session_state.city_filter_initialized = True
        st.session_state.city_selection = cities_all  # All selected by default
    
    city_filter = st.multiselect(
        "Select City/Cities", 
        cities_all, 
        default=st.session_state.city_selection if st.session_state.city_selection else cities_all, 
        key="city_filter",
        placeholder="All cities selected" if len(st.session_state.get("city_selection", cities_all)) == len(cities_all) else "Choose cities..."
    )
    
    # Update session state
    st.session_state.city_selection = city_filter if city_filter else cities_all
    
    # Display summary below the multiselect
    if len(city_filter) == len(cities_all):
        st.info("📍 **All Cities** selected")
    elif len(city_filter) == 0:
        st.warning("⚠️ No cities selected")
    else:
        st.success(f"📍 **{len(city_filter)}** of **{len(cities_all)}** cities selected")

with col_f2:
    if city_filter:
        communities_filtered = df_wide[df_wide["City"].isin(city_filter)]["Community"].dropna().unique()
    else:
        communities_filtered = []
    
    # Initialize filter state if not exists
    if "community_filter_initialized" not in st.session_state:
        st.session_state.community_filter_initialized = True
        st.session_state.community_selection = list(communities_filtered)
    
    community_filter = st.multiselect(
        "Select Community", 
        sorted(communities_filtered), 
        default=st.session_state.community_selection if st.session_state.community_selection else list(communities_filtered), 
        key="community_filter",
        placeholder="All communities selected" if len(st.session_state.get("community_selection", communities_filtered)) == len(communities_filtered) else "Choose communities..."
    )
    
    # Update session state
    st.session_state.community_selection = community_filter if community_filter else list(communities_filtered)
    
    # Display summary below the multiselect
    if len(community_filter) == len(communities_filtered):
        st.info("🏘️ **All Communities** selected")
    elif len(community_filter) == 0:
        st.warning("⚠️ No communities selected")
    else:
        st.success(f"🏘️ **{len(community_filter)}** of **{len(communities_filtered)}** communities selected")

with col_f3:
    month_filter = st.selectbox("Select Month", options=months, index=len(months)-1, key="month_filter")

# Apply filters (use all if none selected)
actual_city_filter = city_filter if city_filter else cities_all
actual_community_filter = community_filter if community_filter else list(communities_filtered)

df_filtered = df_wide[
    (df_wide["City"].isin(actual_city_filter)) &
    (df_wide["Community"].isin(actual_community_filter))
].copy()

# ---------------- Summary KPIs ----------------
st.markdown("---")
st.markdown("### 📊 Key Performance Indicators")

# Get the selected month's metrics
metric_cols_for_month = [c for c in df_filtered.columns if c.endswith(month_filter)]
tonnage_col = next((c for c in metric_cols_for_month if c.startswith("Tonnage_")), None)
trees_col = next((c for c in metric_cols_for_month if c.startswith("Trees_Saved_")), None)
co2_col = next((c for c in metric_cols_for_month if c.startswith("CO2_Kgs_Averted_")), None)
participation_col = next((c for c in metric_cols_for_month if c.startswith("Households_Participation_Percent_")), None)
compliance_col = next((c for c in metric_cols_for_month if c.startswith("Segregation_Compliance_Percent_")), None)

kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5 = st.columns(5)

with kpi_c1:
    if tonnage_col:
        total_tonnage = df_filtered[tonnage_col].sum()
        st.metric("Total Tonnage", f"{total_tonnage:,.0f} kg")
    else:
        st.metric("Total Tonnage", "N/A")

with kpi_c2:
    if trees_col:
        total_trees = df_filtered[trees_col].sum()
        st.metric("Trees Saved", f"{total_trees:,.0f}")
    else:
        st.metric("Trees Saved", "N/A")

with kpi_c3:
    if co2_col:
        total_co2 = df_filtered[co2_col].sum()
        st.metric("CO₂ Averted", f"{total_co2:,.0f} kg")
    else:
        st.metric("CO₂ Averted", "N/A")

with kpi_c4:
    if participation_col:
        avg_participation = df_filtered[participation_col].mean()
        st.metric("Avg Participation", f"{avg_participation:.1f}%")
    else:
        st.metric("Avg Participation", "N/A")

with kpi_c5:
    if compliance_col:
        avg_compliance = df_filtered[compliance_col].mean()
        st.metric("Avg Compliance", f"{avg_compliance:.1f}%")
    else:
        st.metric("Avg Compliance", "N/A")

st.markdown("---")

# ---------------- Map Visualization ----------------
st.markdown(f"### 🗺️ Interactive Map ({map_type})")

# Prepare map data
map_df = df_filtered.dropna(subset=["Latitude", "Longitude"]).copy()

if map_df.empty:
    st.warning("⚠️ No location data available for selected filters.")
else:
    if map_type == "2D Map (Folium)":
        # ---------------- 2D FOLIUM MAP ----------------
        center_lat = map_df["Latitude"].mean()
        center_lon = map_df["Longitude"].mean()
        
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=11,
            tiles="OpenStreetMap",
            control_scale=True
        )
        
        # Add heatmap layer if selected
        if heatmap_metric != "None":
            # Map metric name to column name
            metric_mapping = {
                "Tonnage": tonnage_col,
                "Trees Saved": trees_col,
                "CO2 Kgs Averted": co2_col,
                "Households Participation %": participation_col,
                "Segregation Compliance %": compliance_col
            }
            
            heatmap_col = metric_mapping.get(heatmap_metric)
            if heatmap_col and heatmap_col in map_df.columns:
                heat_data = []
                for idx, row in map_df.iterrows():
                    if pd.notna(row[heatmap_col]) and row[heatmap_col] > 0:
                        # Normalize the weight
                        weight = row[heatmap_col] / map_df[heatmap_col].max()
                        heat_data.append([row["Latitude"], row["Longitude"], weight])
                
                if heat_data:
                    HeatMap(
                        heat_data,
                        min_opacity=0.2,
                        max_opacity=0.8,
                        radius=15,
                        blur=20,
                        gradient={0.2: 'blue', 0.4: 'lime', 0.6: 'yellow', 0.8: 'orange', 1.0: 'red'}
                    ).add_to(m)
        
        # Add markers
        marker_cluster = MarkerCluster().add_to(m)
        
        for idx, row in map_df.iterrows():
            # Build popup content
            popup_html = f"""
            <div style='width: 350px; font-family: Arial;'>
                <h4 style='color: {BRAND_PRIMARY}; margin-bottom: 10px;'>{row['Community']}</h4>
                <p><strong>City:</strong> {row['City']}</p>
                <p><strong>Pincode:</strong> {row['Pincode']}</p>
                <hr>
            """
            
            # Add metrics for selected month
            if tonnage_col:
                popup_html += f"<p>📦 <strong>Tonnage:</strong> {row[tonnage_col]:,.0f} kg</p>"
            if trees_col:
                popup_html += f"<p>🌳 <strong>Trees Saved:</strong> {row[trees_col]:,.0f}</p>"
            if co2_col:
                popup_html += f"<p>🌍 <strong>CO₂ Averted:</strong> {row[co2_col]:,.0f} kg</p>"
            if participation_col:
                popup_html += f"<p>🏠 <strong>Participation:</strong> {row[participation_col]:.1f}%</p>"
            if compliance_col:
                popup_html += f"<p>✅ <strong>Compliance:</strong> {row[compliance_col]:.1f}%</p>"
            
            # Add trend charts ONLY if toggle is ON
            if show_popup_charts:
                # Get time series data for this community
                community_data_tonnage = df_long[
                    (df_long["Community"] == row["Community"]) &
                    (df_long["City"] == row["City"]) &
                    (df_long["Metric"] == "Tonnage")
                ].sort_values("Date")
                
                community_data_participation = df_long[
                    (df_long["Community"] == row["Community"]) &
                    (df_long["City"] == row["City"]) &
                    (df_long["Metric"] == "Households_Participation_Percent")
                ].sort_values("Date")
                
                if not community_data_tonnage.empty:
                    popup_html += "<hr><h5 style='margin-top: 10px;'>📈 Trends Over Time</h5>"
                    
                    # Create tonnage trend chart
                    tonnage_chart = create_trend_chart_base64(community_data_tonnage, "Tonnage (kg)", color='#8B4513')
                    if tonnage_chart:
                        popup_html += f'<img src="data:image/png;base64,{tonnage_chart}" style="width:100%; margin-top:10px;">'
                    
                    # Create participation trend chart
                    if not community_data_participation.empty:
                        participation_chart = create_trend_chart_base64(community_data_participation, "Participation %", color='green')
                        if participation_chart:
                            popup_html += f'<img src="data:image/png;base64,{participation_chart}" style="width:100%; margin-top:10px;">'
            
            popup_html += "</div>"
            
            folium.Marker(
                location=[row["Latitude"], row["Longitude"]],
                popup=folium.Popup(popup_html, max_width=400),
                tooltip=row["Community"],
                icon=folium.Icon(color="purple", icon="recycle", prefix="fa")
            ).add_to(marker_cluster)
        
        # Display map
        st_folium(m, width=None, height=ST_MAP_HEIGHT, returned_objects=ST_RETURNED_OBJECTS)
    
    else:
    # ---------------- 3D PYDECK MAP (CLEAN VERSION) ----------------
    
    # ---------------- 3D PYDECK MAP (WHITE BACKGROUND) ----------------
        st.markdown("#### 🧭 3D Extruded View")

        # Map metric name → column name
        metric_mapping = {
            "Tonnage": tonnage_col,
            "Trees Saved": trees_col,
            "CO2 Kgs Averted": co2_col,
            "Households Participation %": participation_col,
            "Segregation Compliance %": compliance_col
        }
        extrude_col = metric_mapping.get(extrude_metric)

        if extrude_col is None or extrude_col not in map_df.columns:
            st.warning("⚠️ Selected metric not available for 3D extrusion.")
        else:
            # Normalize height for extrusion
            df_3d = map_df.copy()
            max_val = df_3d[extrude_col].max()
            df_3d["height"] = (
                df_3d[extrude_col] / max_val * 800
                if max_val > 0 else 50
            )

            layer = pdk.Layer(
                "ColumnLayer",
                data=df_3d,
                get_position=["Longitude", "Latitude"],
                get_elevation="height",
                elevation_scale=1,
                radius=120,
                get_fill_color="[180, 140, 255, 180]",  # soft purple
                pickable=True,
                auto_highlight=True,
                extruded=True
            )

            view_state = pdk.ViewState(
                latitude=df_3d["Latitude"].mean(),
                longitude=df_3d["Longitude"].mean(),
                zoom=11,
                pitch=55,
                bearing=20
            )

            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip={
                    "html": """
                    <b>Community:</b> {Community}<br/>
                    <b>City:</b> {City}<br/>
                    <b>Value:</b> {""" + extrude_col + """}
                    """,
                    "style": {
                        "backgroundColor": "white",
                        "color": "black"
                    }
                },
                map_style="light"  # ✅ white background
            )

            st.pydeck_chart(deck, use_container_width=True)

            st.markdown("---")

    # ---------------- Charts Section ----------------
    st.markdown("### 📈 Analytics & Trends")

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("#### Tonnage Trend Over Time")
        tonnage_trend = df_long[
            (df_long["City"].isin(actual_city_filter)) &
            (df_long["Community"].isin(actual_community_filter)) &
            (df_long["Metric"] == "Tonnage")
        ].groupby("Date")["Value"].sum().reset_index()
        
        if not tonnage_trend.empty:
            fig_tonnage = px.line(
                tonnage_trend,
                x="Date",
                y="Value",
                title="Total Tonnage Over Time",
                labels={"Value": "Tonnage (kg)", "Date": "Month"},
                markers=True
            )
            fig_tonnage.update_traces(line_color=BRAND_PRIMARY)
            st.plotly_chart(fig_tonnage, use_container_width=True)
        else:
            st.info("No tonnage data available")

    with chart_col2:
        st.markdown("#### Participation Rate Trend")
        participation_trend = df_long[
            (df_long["City"].isin(actual_city_filter)) &
            (df_long["Community"].isin(actual_community_filter)) &
            (df_long["Metric"] == "Households_Participation_Percent")
        ].groupby("Date")["Value"].mean().reset_index()
        
        if not participation_trend.empty:
            fig_participation = px.line(
                participation_trend,
                x="Date",
                y="Value",
                title="Average Participation Rate Over Time",
                labels={"Value": "Participation (%)", "Date": "Month"},
                markers=True
            )
            fig_participation.update_traces(line_color="green")
            st.plotly_chart(fig_participation, use_container_width=True)
        else:
            st.info("No participation data available")

    st.markdown("---")

    # ---------------- COMMUNITY/CITY ANALYSIS REPORT SECTION ----------------
    st.markdown("### 📊 Generate Analysis Report")
    st.markdown("Generate a comprehensive analysis report for a specific community or city with detailed trends and insights.")

    report_col1, report_col2 = st.columns([2, 1])

    with report_col1:
        report_type = st.radio(
            "Report Type",
            options=["Community Report", "City Report"],
            horizontal=True,
            key="report_type"
        )
        
        if report_type == "Community Report":
            # Select city first, then community
            report_city = st.selectbox(
                "Select City",
                options=sorted(df_wide["City"].unique()),
                key="report_city"
            )
            
            communities_in_city = df_wide[df_wide["City"] == report_city]["Community"].unique()
            report_community = st.selectbox(
                "Select Community",
                options=sorted(communities_in_city),
                key="report_community"
            )
            
            report_entity_name = f"{report_community}, {report_city}"
            report_filter = (df_long["Community"] == report_community) & (df_long["City"] == report_city)
            
        else:  # City Report
            report_city = st.selectbox(
                "Select City",
                options=sorted(df_wide["City"].unique()),
                key="report_city_only"
            )
            
            report_entity_name = report_city
            report_filter = df_long["City"] == report_city

    with report_col2:
        st.markdown("#### Report Options")
        include_all_metrics = st.checkbox("Include all metrics", value=True, key="include_all")
        
        if st.button("📄 Generate Report", type="primary", use_container_width=True):
            st.session_state.generate_report = True

    # Generate and display report
    if st.session_state.get("generate_report", False):
        st.markdown("---")
        st.markdown(f"## 📑 Analysis Report: {report_entity_name}")
        st.caption(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Filter data for the selected entity
        report_data = df_long[report_filter].copy()
        
        if report_data.empty:
            st.warning(f"⚠️ No data available for {report_entity_name}")
        else:
            # Summary statistics
            st.markdown("### 📌 Summary Statistics")
            
            summary_metrics = {}
            for metric in ["Tonnage", "Trees_Saved", "CO2_Kgs_Averted", "Households_Participation_Percent", "Segregation_Compliance_Percent"]:
                metric_data = report_data[report_data["Metric"] == metric]["Value"]
                if not metric_data.empty:
                    summary_metrics[metric] = {
                        "Total": metric_data.sum() if metric in ["Tonnage", "Trees_Saved", "CO2_Kgs_Averted"] else None,
                        "Average": metric_data.mean(),
                        "Max": metric_data.max(),
                        "Min": metric_data.min(),
                        "Latest": metric_data.iloc[-1]
                    }
            
            # Display summary in columns
            sum_cols = st.columns(5)
            metric_labels = {
                "Tonnage": "Total Tonnage",
                "Trees_Saved": "Trees Saved",
                "CO2_Kgs_Averted": "CO₂ Averted",
                "Households_Participation_Percent": "Avg Participation",
                "Segregation_Compliance_Percent": "Avg Compliance"
            }
            
            for idx, (metric, label) in enumerate(metric_labels.items()):
                if metric in summary_metrics:
                    with sum_cols[idx]:
                        if summary_metrics[metric]["Total"] is not None:
                            st.metric(label, f"{summary_metrics[metric]['Total']:,.0f}")
                        else:
                            st.metric(label, f"{summary_metrics[metric]['Average']:.1f}%")
            
            st.markdown("---")
            
            # Detailed trend charts
            st.markdown("### 📈 Detailed Trend Analysis")
            
            metrics_to_plot = [
                ("Tonnage", "Tonnage (kg)", BRAND_PRIMARY),
                ("Trees_Saved", "Trees Saved", "green"),
                ("CO2_Kgs_Averted", "CO₂ Averted (kg)", "orange"),
                ("Households_Participation_Percent", "Participation (%)", "blue"),
                ("Segregation_Compliance_Percent", "Compliance (%)", "red")
            ]
            
            for metric, label, color in metrics_to_plot:
                metric_trend = report_data[report_data["Metric"] == metric].sort_values("Date")
                
                if not metric_trend.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=metric_trend["Date"],
                        y=metric_trend["Value"],
                        mode='lines+markers',
                        name=label,
                        line=dict(color=color, width=3),
                        marker=dict(size=8)
                    ))
                    
                    fig.update_layout(
                        title=f"{label} Trend",
                        xaxis_title="Date",
                        yaxis_title=label,
                        hovermode='x unified',
                        height=400
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("---")
            
            # Data table
            st.markdown("### 📋 Raw Data")
            
            # Pivot the data for better display
            pivot_data = report_data.pivot_table(
                index="Date",
                columns="Metric",
                values="Value",
                aggfunc="sum"
            ).reset_index()
            
            pivot_data.columns.name = None
            pivot_data["Date"] = pivot_data["Date"].dt.strftime("%Y-%m")
            
            st.dataframe(pivot_data, use_container_width=True, height=400)
            
            # Download button for report data
            csv_report = pivot_data.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Report Data as CSV",
                data=csv_report,
                file_name=f"analysis_report_{report_entity_name.replace(', ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

    st.markdown("---")

# ---------------- Data Table ----------------
st.markdown("### 📋 Detailed Data Table")

# Show selected month's data
display_cols = ["City", "Community", "Pincode"]
if tonnage_col:
    display_cols.append(tonnage_col)
if trees_col:
    display_cols.append(trees_col)
if co2_col:
    display_cols.append(co2_col)
if participation_col:
    display_cols.append(participation_col)
if compliance_col:
    display_cols.append(compliance_col)

display_df = df_filtered[display_cols].copy()

# Rename columns for better display
rename_map = {}
if tonnage_col:
    rename_map[tonnage_col] = "Tonnage (kg)"
if trees_col:
    rename_map[trees_col] = "Trees Saved"
if co2_col:
    rename_map[co2_col] = "CO₂ Averted (kg)"
if participation_col:
    rename_map[participation_col] = "Participation (%)"
if compliance_col:
    rename_map[compliance_col] = "Compliance (%)"

display_df = display_df.rename(columns=rename_map)

st.dataframe(display_df, use_container_width=True, height=400)

# Download button
csv_data = display_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Download Filtered Data as CSV",
    data=csv_data,
    file_name=f"bintix_data_{month_filter}.csv",
    mime="text/csv"
)

st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: gray;'>Built with ❤️ by Bintix Analytics Team</p>",
    unsafe_allow_html=True
)
