import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Calendar,
  CalendarDays,
  ChevronDown,
  Download,
  Flame,
  Globe2,
  Grid,
  Layers,
  Moon,
  RefreshCw,
  RotateCcw,
  Satellite,
  SlidersHorizontal,
  Sun,
  Table,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CircleMarker, MapContainer, Popup, Rectangle, TileLayer, useMap } from "react-leaflet";

type TemporalAggregation = "daily" | "weekly" | "monthly" | "yearly";
type SpatialAggregation = "detections" | "grid" | "clusters";
type DatePreset = "all" | "5y" | "3y" | "1y" | "6m" | "custom";

type Filters = {
  preset: DatePreset;
  startDate: string;
  endDate: string;
  region: string;
  platform: string;
  daynight: string;
  frpMin: string;
  frpMax: string;
  confidence: string;
  temporalAggregation: TemporalAggregation;
  spatialAggregation: SpatialAggregation;
  gridResolution: number;
};

type HistoricalSummaryKpis = {
  total_detections: number;
  total_clusters: number | null;
  mean_frp: number | null;
  median_frp: number | null;
  total_frp: number | null;
  peak_frp: number | null;
  avg_cluster_size: number | null;
  first_date: string | null;
  last_date: string | null;
};

type TrendRow = {
  period: string;
  detections: number;
  modis_detections: number;
  viirs_detections: number;
  other_detections: number;
};

type FrpRow = {
  period: string;
  observation_count: number;
  mean_frp: number | null;
  median_frp: number | null;
  p90_frp: number | null;
  total_frp: number | null;
};

type ClusterCountRow = {
  period: string;
  clusters: number;
};

type ClusterSizeRow = {
  period: string;
  clusters?: number;
  avg_size: number;
  median_size: number;
  max_size: number;
  small_clusters: number;
  medium_clusters: number;
  large_clusters: number;
  mega_clusters: number;
};

type RegionalRow = {
  region: string;
  region_name: string;
  detections: number;
  total_frp: number;
  mean_frp: number | null;
  median_frp: number | null;
};

type SpatialPoint = {
  id: string;
  latitude: number;
  longitude: number;
  platform: string;
  acq_date: string;
  frp_mw: number | null;
  confidence: string | null;
  daynight: string | null;
};

type SpatialGridCell = {
  id: string;
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
  center_lat: number;
  center_lon: number;
  detections: number;
  mean_frp: number | null;
  total_frp: number | null;
  max_frp: number | null;
};

type SpatialCluster = {
  cluster_id: string;
  latitude: number;
  longitude: number;
  member_count: number;
  mean_frp: number | null;
  max_frp: number | null;
  first_date: string | null;
  last_date: string | null;
};

type HistoricalData = {
  generated_at: string;
  summary_kpis: HistoricalSummaryKpis;
  detection_trend: TrendRow[];
  frp_evolution: FrpRow[];
  cluster_counts: ClusterCountRow[];
  cluster_size_evolution: ClusterSizeRow[];
  regional_comparison: RegionalRow[];
  spatial_distribution: {
    mode: SpatialAggregation;
    points: SpatialPoint[];
    grid_cells: SpatialGridCell[];
    clusters: SpatialCluster[];
  };
  date_bounds: {
    min_date: string | null;
    max_date: string | null;
    available_years: number[];
  };
  sources: {
    historical_detection_trend: string;
    frp_evolution: string;
    historical_cluster_counts: string | null;
    cluster_size_evolution: string | null;
    historical_spatial_distribution: string;
  };
  capabilities: {
    frp: boolean;
    confidence: boolean;
    daynight: boolean;
    geographic_regions: boolean;
    activity_clusters: boolean;
    sensor_activity_daily_table: boolean;
  };
};

const REGIONS: [string, string][] = [
  ["global", "Global (All Regions)"],
  ["africa", "Africa"],
  ["asia", "Asia"],
  ["europe", "Europe"],
  ["north-america", "North America"],
  ["oceania", "Oceania"],
  ["south-america", "South America"],
];

const PLATFORMS: [string, string][] = [
  ["all", "All Platforms / Sensors"],
  ["terra", "Terra (MODIS)"],
  ["aqua", "Aqua (MODIS)"],
  ["noaa20", "NOAA-20 (VIIRS 375m)"],
  ["noaa21", "NOAA-21 (VIIRS 375m)"],
  ["modis", "MODIS (Terra + Aqua)"],
  ["viirs", "VIIRS (NOAA-20 + NOAA-21)"],
];

const CONFIDENCE_LEVELS: [string, string][] = [
  ["all", "All Confidence Levels"],
  ["high", "High (≥ 80% / 'h')"],
  ["nominal", "Nominal (30-79% / 'n')"],
  ["low", "Low (< 30% / 'l')"],
];

const REGION_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  global: { center: [18, 5], zoom: 2 },
  africa: { center: [1, 22], zoom: 3 },
  asia: { center: [34, 98], zoom: 3 },
  europe: { center: [52, 18], zoom: 4 },
  "north-america": { center: [45, -100], zoom: 3 },
  oceania: { center: [-25, 135], zoom: 4 },
  "south-america": { center: [-18, -60], zoom: 3 },
};

function formatNum(value: number | null | undefined, maxDigits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: maxDigits }).format(value);
}

function compactNum(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatPeriodLabel(period: string, temporalGrain: TemporalAggregation): string {
  if (!period) return "";
  if (temporalGrain === "yearly") return period;
  if (temporalGrain === "monthly") {
    const [year, month] = period.split("-");
    const d = new Date(Number(year), Number(month) - 1, 1);
    return isNaN(d.getTime()) ? period : d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  }
  if (temporalGrain === "weekly") {
    const d = new Date(`${period}T00:00:00`);
    return isNaN(d.getTime()) ? period : `Wk of ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
  }
  const d = new Date(`${period}T00:00:00`);
  return isNaN(d.getTime()) ? period : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
}

function calculatePresetDates(preset: DatePreset): { startDate: string; endDate: string } {
  const now = new Date();
  const endIso = now.toISOString().slice(0, 10);
  if (preset === "all") {
    return { startDate: "", endDate: "" };
  }
  const start = new Date(now);
  if (preset === "5y") start.setFullYear(now.getFullYear() - 5);
  else if (preset === "3y") start.setFullYear(now.getFullYear() - 3);
  else if (preset === "1y") start.setFullYear(now.getFullYear() - 1);
  else if (preset === "6m") start.setMonth(now.getMonth() - 6);
  return { startDate: start.toISOString().slice(0, 10), endDate: endIso };
}

function MapViewController({ region }: { region: string }) {
  const map = useMap();
  useEffect(() => {
    const target = REGION_CENTERS[region] || REGION_CENTERS.global;
    map.setView(target.center, target.zoom, { animate: true });
  }, [region, map]);
  return null;
}

export default function HistoricalAnalysisPage() {
  const [filters, setFilters] = useState<Filters>({
    preset: "all",
    startDate: "",
    endDate: "",
    region: "global",
    platform: "all",
    daynight: "all",
    frpMin: "",
    frpMax: "",
    confidence: "all",
    temporalAggregation: "monthly",
    spatialAggregation: "detections",
    gridResolution: 2.0,
  });

  const [data, setData] = useState<HistoricalData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [exportOpen, setExportOpen] = useState<boolean>(false);
  const [exporting, setExporting] = useState<boolean>(false);
  const [clusterViewMode, setClusterViewMode] = useState<"counts" | "sizes">("counts");
  const [regionalMetric, setRegionalMetric] = useState<"detections" | "total_frp" | "mean_frp">("detections");

  // Fetch API
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setLoading(true);
      setError("");

      const params = new URLSearchParams({
        region: filters.region,
        platform: filters.platform,
        daynight: filters.daynight,
        confidence: filters.confidence,
        temporal_aggregation: filters.temporalAggregation,
        spatial_aggregation: filters.spatialAggregation,
        grid_resolution: String(filters.gridResolution),
      });

      if (filters.startDate) params.set("start_date", filters.startDate);
      if (filters.endDate) params.set("end_date", filters.endDate);
      if (filters.frpMin.trim()) params.set("frp_min", filters.frpMin.trim());
      if (filters.frpMax.trim()) params.set("frp_max", filters.frpMax.trim());

      const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
      const url = `${base}/api/historical-analysis?${params.toString()}`;

      try {
        const res = await fetch(url, { signal: controller.signal });
        const body = await res.json();
        if (!res.ok) {
          throw new Error(body.detail ?? "Failed to load historical fire analysis.");
        }
        setData(body as HistoricalData);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Failed to load historical fire analysis.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, 150);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [filters, refreshKey]);

  // Handle Preset change
  const handlePresetChange = (preset: DatePreset) => {
    if (preset === "custom") {
      setFilters((prev) => ({ ...prev, preset }));
      return;
    }
    const dates = calculatePresetDates(preset);
    setFilters((prev) => ({
      ...prev,
      preset,
      startDate: dates.startDate,
      endDate: dates.endDate,
    }));
  };

  // Reset all filters
  const handleResetFilters = () => {
    setFilters({
      preset: "all",
      startDate: "",
      endDate: "",
      region: "global",
      platform: "all",
      daynight: "all",
      frpMin: "",
      frpMax: "",
      confidence: "all",
      temporalAggregation: "monthly",
      spatialAggregation: "detections",
      gridResolution: 2.0,
    });
  };

  // Trigger file download
  const handleDownload = async (exportType: "observations" | "aggregated" | "regional", format: "csv" | "geojson" | "json") => {
    setExporting(true);
    setExportOpen(false);
    try {
      const params = new URLSearchParams({
        export_type: exportType,
        format,
        region: filters.region,
        platform: filters.platform,
        daynight: filters.daynight,
        confidence: filters.confidence,
        temporal_aggregation: filters.temporalAggregation,
        grid_resolution: String(filters.gridResolution),
      });
      if (filters.startDate) params.set("start_date", filters.startDate);
      if (filters.endDate) params.set("end_date", filters.endDate);
      if (filters.frpMin.trim()) params.set("frp_min", filters.frpMin.trim());
      if (filters.frpMax.trim()) params.set("frp_max", filters.frpMax.trim());

      const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
      const url = `${base}/api/historical-analysis/export?${params.toString()}`;

      const res = await fetch(url);
      if (!res.ok) {
        throw new Error("Export download failed. Please retry.");
      }
      const blob = await res.blob();
      const contentDisposition = res.headers.get("content-disposition");
      let filename = `twinflame_historical_${exportType}.${format}`;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?([^"]+)"?/);
        if (match?.[1]) filename = match[1];
      }

      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const kpis = data?.summary_kpis;

  const sensorTotals = useMemo(() => {
    let modis = 0;
    let viirs = 0;
    let other = 0;
    for (const r of data?.detection_trend ?? []) {
      modis += r.modis_detections;
      viirs += r.viirs_detections;
      other += r.other_detections;
    }
    const total = modis + viirs + other;
    return {
      modis,
      viirs,
      other,
      modisPct: total > 0 ? Math.round((modis / total) * 100) : 0,
      viirsPct: total > 0 ? Math.round((viirs / total) * 100) : 0,
    };
  }, [data?.detection_trend]);

  return (
    <div className="historical-page-container">
      {/* 1. Header & Title Section */}
      <section className="historical-header">
        <div className="historical-header-main">
          <div className="historical-badge">
            <span className="badge-pulse" />
            <span>06 · HISTORICAL FIRE ANALYSIS</span>
          </div>
          <h1>Historical Fire Analysis &amp; Regime Evolution</h1>
          <p className="historical-subtitle">
            Long-term multi-year fire regime analysis: Track detection trends, Fire Radiative Power (FRP) evolution,
            wildfire cluster dynamics, and spatial-temporal regime transitions across historical sensor records.
          </p>
        </div>

        {/* Action Controls & Export */}
        <div className="historical-header-actions">
          <div className="export-dropdown-wrapper">
            <button
              type="button"
              className="action-btn export-btn"
              onClick={() => setExportOpen((prev) => !prev)}
              disabled={exporting || loading}
            >
              <Download size={15} />
              <span>{exporting ? "Generating..." : "Export Dataset"}</span>
              <ChevronDown size={14} />
            </button>

            {exportOpen && (
              <div className="export-menu">
                <div className="export-menu-header">SELECT EXPORT FORMAT</div>
                <button
                  type="button"
                  className="export-menu-item"
                  onClick={() => handleDownload("observations", "csv")}
                >
                  <Download size={14} />
                  <div>
                    <strong>Observations (.csv)</strong>
                    <span>Filtered raw detection records with timestamps &amp; FRP</span>
                  </div>
                </button>
                <button
                  type="button"
                  className="export-menu-item"
                  onClick={() => handleDownload("observations", "geojson")}
                >
                  <Globe2 size={14} />
                  <div>
                    <strong>Geospatial Features (.geojson)</strong>
                    <span>Standard GIS FeatureCollection ready for QGIS &amp; ArcGIS</span>
                  </div>
                </button>
                <button
                  type="button"
                  className="export-menu-item"
                  onClick={() => handleDownload("aggregated", "csv")}
                >
                  <TrendingUp size={14} />
                  <div>
                    <strong>Aggregated Time Series (.csv)</strong>
                    <span>{filters.temporalAggregation.toUpperCase()} aggregated detections &amp; FRP evolution</span>
                  </div>
                </button>
                <button
                  type="button"
                  className="export-menu-item"
                  onClick={() => handleDownload("regional", "csv")}
                >
                  <Grid size={14} />
                  <div>
                    <strong>Regional Comparisons (.csv)</strong>
                    <span>Cross-continental fire metrics and energy sums</span>
                  </div>
                </button>
                <button
                  type="button"
                  className="export-menu-item"
                  onClick={() => handleDownload("observations", "json")}
                >
                  <Table size={14} />
                  <div>
                    <strong>Complete JSON Package (.json)</strong>
                    <span>Raw JSON payload with schema metadata</span>
                  </div>
                </button>
              </div>
            )}
          </div>

          <button
            type="button"
            className="action-btn refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            title="Refresh database queries"
          >
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            <span>Refresh</span>
          </button>
        </div>
      </section>

      {/* 2. Top-tier Filter Bar */}
      <section className="historical-filter-bar">
        {/* Preset Range Selector */}
        <div className="filter-group preset-group">
          <span className="filter-label">
            <Calendar size={13} />
            HISTORICAL WINDOW
          </span>
          <div className="preset-buttons">
            {(
              [
                ["all", "All Time"],
                ["5y", "Last 5Y"],
                ["3y", "Last 3Y"],
                ["1y", "Last 1Y"],
                ["6m", "6 Months"],
                ["custom", "Custom"],
              ] as [DatePreset, string][]
            ).map(([presetKey, label]) => (
              <button
                key={presetKey}
                type="button"
                className={`preset-pill ${filters.preset === presetKey ? "active" : ""}`}
                onClick={() => handlePresetChange(presetKey)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Date Inputs if Custom or Selected */}
        <div className="filter-group date-inputs-group">
          <span className="filter-label">DATE RANGE (UTC)</span>
          <div className="date-inputs-inline">
            <input
              type="date"
              className="filter-input date-input"
              value={filters.startDate}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  preset: "custom",
                  startDate: e.target.value,
                }))
              }
              title="Start Date (UTC)"
            />
            <span className="date-sep">→</span>
            <input
              type="date"
              className="filter-input date-input"
              value={filters.endDate}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  preset: "custom",
                  endDate: e.target.value,
                }))
              }
              title="End Date (UTC)"
            />
          </div>
        </div>

        {/* Region */}
        <div className="filter-group">
          <span className="filter-label">
            <Globe2 size={13} /> REGION
          </span>
          <div className="select-wrapper">
            <select
              value={filters.region}
              onChange={(e) => setFilters((prev) => ({ ...prev, region: e.target.value }))}
            >
              {REGIONS.map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Satellite / Platform */}
        <div className="filter-group">
          <span className="filter-label">
            <Satellite size={13} /> PLATFORM / SENSOR
          </span>
          <div className="select-wrapper">
            <select
              value={filters.platform}
              onChange={(e) => setFilters((prev) => ({ ...prev, platform: e.target.value }))}
            >
              {PLATFORMS.map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Day / Night */}
        <div className="filter-group">
          <span className="filter-label">
            {filters.daynight === "day" ? <Sun size={13} /> : filters.daynight === "night" ? <Moon size={13} /> : <SlidersHorizontal size={13} />}
            DAY / NIGHT
          </span>
          <div className="select-wrapper">
            <select
              value={filters.daynight}
              onChange={(e) => setFilters((prev) => ({ ...prev, daynight: e.target.value }))}
            >
              <option value="all">Day &amp; Night</option>
              <option value="day">Daytime Only (D)</option>
              <option value="night">Nighttime Only (N)</option>
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* FRP Range (MW) */}
        <div className="filter-group frp-group">
          <span className="filter-label">
            <Zap size={13} /> FRP RANGE (MW)
          </span>
          <div className="range-inputs">
            <input
              type="number"
              placeholder="Min MW"
              min="0"
              value={filters.frpMin}
              onChange={(e) => setFilters((prev) => ({ ...prev, frpMin: e.target.value }))}
              className="filter-input num-input"
            />
            <span className="date-sep">–</span>
            <input
              type="number"
              placeholder="Max MW"
              min="0"
              value={filters.frpMax}
              onChange={(e) => setFilters((prev) => ({ ...prev, frpMax: e.target.value }))}
              className="filter-input num-input"
            />
          </div>
        </div>

        {/* Confidence */}
        <div className="filter-group">
          <span className="filter-label">CONFIDENCE</span>
          <div className="select-wrapper">
            <select
              value={filters.confidence}
              onChange={(e) => setFilters((prev) => ({ ...prev, confidence: e.target.value }))}
            >
              {CONFIDENCE_LEVELS.map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Temporal Aggregation */}
        <div className="filter-group aggregation-group">
          <span className="filter-label">TEMPORAL BINNING</span>
          <div className="pill-group">
            {(["daily", "weekly", "monthly", "yearly"] as TemporalAggregation[]).map((grain) => (
              <button
                key={grain}
                type="button"
                className={`sub-pill ${filters.temporalAggregation === grain ? "active" : ""}`}
                onClick={() => setFilters((prev) => ({ ...prev, temporalAggregation: grain }))}
              >
                {grain}
              </button>
            ))}
          </div>
        </div>

        {/* Spatial Aggregation */}
        <div className="filter-group aggregation-group">
          <span className="filter-label">SPATIAL BINNING</span>
          <div className="pill-group">
            {(
              [
                ["detections", "Detections"],
                ["grid", "Grid Cells (2°)"],
                ["clusters", "Clusters"],
              ] as [SpatialAggregation, string][]
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                className={`sub-pill ${filters.spatialAggregation === mode ? "active" : ""}`}
                onClick={() => setFilters((prev) => ({ ...prev, spatialAggregation: mode }))}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Reset Filter Button */}
        <div className="filter-group reset-group">
          <button
            type="button"
            className="action-btn reset-btn"
            onClick={handleResetFilters}
            title="Reset to default filters"
          >
            <RotateCcw size={13} />
            <span>Reset</span>
          </button>
        </div>
      </section>

      {/* Error Banner */}
      {error && (
        <div className="historical-error-banner">
          <AlertCircle size={18} />
          <div className="error-content">
            <strong>Unable to load historical dataset</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* 3. Hero KPI Stats Grid */}
      <section className="historical-kpi-grid">
        {/* KPI 1: Detections */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon orange">
              <Flame size={16} />
            </span>
            <span className="kpi-title">TOTAL HISTORICAL DETECTIONS</span>
            <span className="kpi-source-tag">UNIFIED_DETECTIONS</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : formatNum(kpis?.total_detections, 0)}
          </div>
          <div className="kpi-subtext">
            <span>MODIS: <strong>{sensorTotals.modisPct}%</strong></span>
            <span className="dot">·</span>
            <span>VIIRS: <strong>{sensorTotals.viirsPct}%</strong></span>
          </div>
        </div>

        {/* KPI 2: Mean & Median FRP */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon red">
              <Zap size={16} />
            </span>
            <span className="kpi-title">FIRE RADIATIVE POWER (MW)</span>
            <span className="kpi-source-tag">{data?.sources.frp_evolution ?? "FRP"}</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : `${formatNum(kpis?.mean_frp)} MW`}
          </div>
          <div className="kpi-subtext">
            <span>Median: <strong>{formatNum(kpis?.median_frp)} MW</strong></span>
            <span className="dot">·</span>
            <span>Peak: <strong>{formatNum(kpis?.peak_frp)} MW</strong></span>
          </div>
        </div>

        {/* KPI 3: Total Radiative Energy */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon copper">
              <Activity size={16} />
            </span>
            <span className="kpi-title">TOTAL RADIATIVE POWER</span>
            <span className="kpi-source-tag">CUMULATIVE ENERGY</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : `${compactNum(kpis?.total_frp)} MW`}
          </div>
          <div className="kpi-subtext">
            Integrated thermal energy release across period
          </div>
        </div>

        {/* KPI 4: Historical Activity Clusters */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon green">
              <Layers size={16} />
            </span>
            <span className="kpi-title">HISTORICAL CLUSTERS</span>
            <span className="kpi-source-tag">{data?.sources.historical_cluster_counts ?? "harm_clusters"}</span>
          </div>
          <div className="kpi-number">
            {loading && !data
              ? "..."
              : kpis?.total_clusters != null
                ? formatNum(kpis.total_clusters, 0)
                : "Unavailable"}
          </div>
          <div className="kpi-subtext">
            {data?.capabilities.activity_clusters
              ? "Harmonized spatial-temporal event clusters"
              : "Cluster schema not present in current DB"}
          </div>
        </div>

        {/* KPI 5: Average Cluster Size */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon orange">
              <TrendingUp size={16} />
            </span>
            <span className="kpi-title">AVG CLUSTER SIZE</span>
            <span className="kpi-source-tag">CLUSTER MEMBERS</span>
          </div>
          <div className="kpi-number">
            {loading && !data
              ? "..."
              : kpis?.avg_cluster_size != null
                ? `${formatNum(kpis.avg_cluster_size)} det`
                : "—"}
          </div>
          <div className="kpi-subtext">
            Mean detection count per wildfire cluster
          </div>
        </div>

        {/* KPI 6: Temporal Span */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon yellow">
              <CalendarDays size={16} />
            </span>
            <span className="kpi-title">TEMPORAL COVERAGE</span>
            <span className="kpi-source-tag">OBSERVATION WINDOW</span>
          </div>
          <div className="kpi-number kpi-dates">
            {loading && !data
              ? "..."
              : kpis?.first_date && kpis?.last_date
                ? `${kpis.first_date.slice(0, 7)} → ${kpis.last_date.slice(0, 7)}`
                : "All Time"}
          </div>
          <div className="kpi-subtext">
            {data?.date_bounds.available_years.length ?? 0} active historical years recorded
          </div>
        </div>
      </section>

      {/* 4. Chart Grid: Row 1 */}
      <section className="historical-chart-grid">
        {/* Viz 1: Historical Detection Trend (UNIFIED_DETECTIONS) */}
        <article className="chart-panel trend-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet orange" />
                <h3>Historical Detection Trend</h3>
                <span className="source-pill">Source: UNIFIED_DETECTIONS</span>
              </div>
              <p className="panel-desc">
                Long-term active fire detection volume binned by {filters.temporalAggregation}. Breakdown by MODIS vs. VIIRS sensor.
              </p>
            </div>
            <span className="unit-label">DETECTIONS</span>
          </div>

          <div className="chart-body">
            {data && data.detection_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart
                  data={data.detection_trend}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="modisGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f58200" stopOpacity={0.45} />
                      <stop offset="95%" stopColor="#f58200" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="viirsGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#d92d1f" stopOpacity={0.45} />
                      <stop offset="95%" stopColor="#d92d1f" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(val) => formatPeriodLabel(val, filters.temporalAggregation)}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={28}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(val) => compactNum(val)}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      borderColor: "#30362c",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "#f3efe7",
                      boxShadow: "0 6px 20px #00000060",
                    }}
                    labelFormatter={(label) => formatPeriodLabel(String(label), filters.temporalAggregation)}
                    formatter={(val, name) => [
                      formatNum(Number(val), 0),
                      name === "modis_detections" ? "MODIS" : name === "viirs_detections" ? "VIIRS" : "Total Detections",
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 8 }}
                    formatter={(val) => (val === "modis_detections" ? "MODIS" : val === "viirs_detections" ? "VIIRS" : "Total")}
                  />
                  <Area
                    type="monotone"
                    dataKey="modis_detections"
                    name="modis_detections"
                    stackId="1"
                    stroke="#f58200"
                    strokeWidth={2}
                    fill="url(#modisGrad)"
                  />
                  <Area
                    type="monotone"
                    dataKey="viirs_detections"
                    name="viirs_detections"
                    stackId="1"
                    stroke="#d92d1f"
                    strokeWidth={2}
                    fill="url(#viirsGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Activity size={20} />
                <span>No historical detections found for the selected query filters.</span>
              </div>
            )}
          </div>
        </article>

        {/* Viz 2: FRP Evolution (harm_sensor_activity_daily) */}
        <article className="chart-panel frp-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet red" />
                <h3>Fire Radiative Power (FRP) Evolution</h3>
                <span className="source-pill">Source: {data?.sources.frp_evolution ?? "harm_sensor_activity_daily"}</span>
              </div>
              <p className="panel-desc">
                Multi-year fire intensity &amp; energy release: Mean, Median, and 90th percentile peak FRP (MW).
              </p>
            </div>
            <span className="unit-label">MEGAWATTS (MW)</span>
          </div>

          <div className="chart-body">
            {data && data.frp_evolution.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart
                  data={data.frp_evolution}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(val) => formatPeriodLabel(val, filters.temporalAggregation)}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={28}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(val) => `${compactNum(val)}`}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      borderColor: "#30362c",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "#f3efe7",
                      boxShadow: "0 6px 20px #00000060",
                    }}
                    labelFormatter={(label) => formatPeriodLabel(String(label), filters.temporalAggregation)}
                    formatter={(val, name) => [
                      `${formatNum(Number(val))} MW`,
                      name === "mean_frp" ? "Mean FRP" : name === "median_frp" ? "Median FRP" : "P90 Peak FRP",
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 8 }}
                    formatter={(val) => (val === "mean_frp" ? "Mean FRP" : val === "median_frp" ? "Median FRP" : "P90 Peak FRP")}
                  />
                  <Line
                    type="monotone"
                    dataKey="p90_frp"
                    name="p90_frp"
                    stroke="#e9b77e"
                    strokeDasharray="4 4"
                    strokeWidth={1.8}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="mean_frp"
                    name="mean_frp"
                    stroke="#f04b22"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, stroke: "#f3efe7", strokeWidth: 2 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="median_frp"
                    name="median_frp"
                    stroke="#80a66f"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Zap size={20} />
                <span>No FRP evolution records match these filters.</span>
              </div>
            )}
          </div>
        </article>
      </section>

      {/* 5. Chart Grid: Row 2 */}
      <section className="historical-chart-grid">
        {/* Viz 3 & 4: Historical Clusters & Size Evolution */}
        <article className="chart-panel cluster-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet green" />
                <h3>Activity Clusters &amp; Size Evolution</h3>
                <span className="source-pill">Source: {data?.sources.historical_cluster_counts ?? "harm_activity_clusters"}</span>
              </div>
              <p className="panel-desc">
                Spatial-temporal clustering behavior: Total cluster count &amp; cluster size tier composition.
              </p>
            </div>
            <div className="mode-toggle">
              <button
                type="button"
                className={`mode-btn ${clusterViewMode === "counts" ? "active" : ""}`}
                onClick={() => setClusterViewMode("counts")}
              >
                Counts
              </button>
              <button
                type="button"
                className={`mode-btn ${clusterViewMode === "sizes" ? "active" : ""}`}
                onClick={() => setClusterViewMode("sizes")}
              >
                Size Breakdown
              </button>
            </div>
          </div>

          <div className="chart-body">
            {!data?.capabilities.activity_clusters ? (
              <div className="empty-chart-state">
                <Layers size={20} />
                <span>harm_activity_clusters table is not present in the database. Run the harmonization pipeline to view cluster evolution.</span>
              </div>
            ) : clusterViewMode === "counts" ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={data.cluster_counts}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(val) => formatPeriodLabel(val, filters.temporalAggregation)}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={28}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(val) => compactNum(val)}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      borderColor: "#30362c",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "#f3efe7",
                    }}
                    labelFormatter={(label) => formatPeriodLabel(String(label), filters.temporalAggregation)}
                    formatter={(val) => [formatNum(Number(val), 0), "Clusters Formed"]}
                  />
                  <Bar dataKey="clusters" fill="#80a66f" radius={[4, 4, 0, 0]} maxBarSize={32} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={data.cluster_size_evolution}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(val) => formatPeriodLabel(val, filters.temporalAggregation)}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={28}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(val) => compactNum(val)}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      borderColor: "#30362c",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "#f3efe7",
                    }}
                    labelFormatter={(label) => formatPeriodLabel(String(label), filters.temporalAggregation)}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 8 }}
                    formatter={(val) =>
                      val === "small_clusters"
                        ? "Small (1-4)"
                        : val === "medium_clusters"
                          ? "Medium (5-19)"
                          : val === "large_clusters"
                            ? "Large (20-99)"
                            : "Mega (100+)"
                    }
                  />
                  <Bar dataKey="small_clusters" name="small_clusters" stackId="size" fill="#80a66f" />
                  <Bar dataKey="medium_clusters" name="medium_clusters" stackId="size" fill="#f58200" />
                  <Bar dataKey="large_clusters" name="large_clusters" stackId="size" fill="#d92d1f" />
                  <Bar dataKey="mega_clusters" name="mega_clusters" stackId="size" fill="#8d321d" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </article>

        {/* Viz 5: Regional Historical Comparisons */}
        <article className="chart-panel regional-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet blue" />
                <h3>Regional Historical Comparisons</h3>
                <span className="source-pill">CONTINENTAL AGGREGATION</span>
              </div>
              <p className="panel-desc">
                Cross-regional distribution of fire activity throughout the historical observation window.
              </p>
            </div>
            <div className="mode-toggle">
              <button
                type="button"
                className={`mode-btn ${regionalMetric === "detections" ? "active" : ""}`}
                onClick={() => setRegionalMetric("detections")}
              >
                Detections
              </button>
              <button
                type="button"
                className={`mode-btn ${regionalMetric === "total_frp" ? "active" : ""}`}
                onClick={() => setRegionalMetric("total_frp")}
              >
                Total FRP
              </button>
              <button
                type="button"
                className={`mode-btn ${regionalMetric === "mean_frp" ? "active" : ""}`}
                onClick={() => setRegionalMetric("mean_frp")}
              >
                Mean FRP
              </button>
            </div>
          </div>

          <div className="chart-body">
            {data && data.regional_comparison.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={data.regional_comparison}
                  layout="vertical"
                  margin={{ top: 8, right: 25, left: 10, bottom: 2 }}
                >
                  <CartesianGrid horizontal={false} stroke="#2c3328" />
                  <XAxis
                    type="number"
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(val) => compactNum(val)}
                    tick={{ fill: "#a0a596", fontSize: 10 }}
                  />
                  <YAxis
                    type="category"
                    dataKey="region_name"
                    axisLine={false}
                    tickLine={false}
                    width={95}
                    tick={{ fill: "#d4d0c4", fontSize: 11, fontWeight: 600 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      borderColor: "#30362c",
                      borderRadius: 8,
                      fontSize: 12,
                      color: "#f3efe7",
                    }}
                    formatter={(val) => [
                      regionalMetric === "mean_frp"
                        ? `${formatNum(Number(val))} MW`
                        : regionalMetric === "total_frp"
                          ? `${compactNum(Number(val))} MW`
                          : formatNum(Number(val), 0),
                      regionalMetric === "mean_frp"
                        ? "Mean FRP"
                        : regionalMetric === "total_frp"
                          ? "Total Radiative Energy"
                          : "Detections",
                    ]}
                  />
                  <Bar
                    dataKey={regionalMetric}
                    fill={regionalMetric === "mean_frp" ? "#f04b22" : regionalMetric === "total_frp" ? "#d92d1f" : "#f58200"}
                    radius={[0, 4, 4, 0]}
                    maxBarSize={22}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Globe2 size={20} />
                <span>No regional activity records found in this range.</span>
              </div>
            )}
          </div>
        </article>
      </section>

      {/* 6. Historical Activity Map (UNIFIED_DETECTIONS) */}
      <section className="historical-map-panel">
        <div className="panel-header map-header">
          <div>
            <div className="panel-title-row">
              <span className="panel-bullet orange" />
              <h3>Historical Spatial Distribution Map</h3>
              <span className="source-pill">Source: UNIFIED_DETECTIONS</span>
              <span className="active-mode-pill">Mode: {filters.spatialAggregation.toUpperCase()}</span>
            </div>
            <p className="panel-desc">
              Cartographic visualization of historical observations. Toggle spatial binning between individual detections,
              2° density grid cells, and activity clusters above.
            </p>
          </div>

          <div className="map-legend-items">
            {filters.spatialAggregation === "detections" ? (
              <>
                <span className="legend-chip"><span className="legend-dot dot-low" /> FRP &lt; 30 MW</span>
                <span className="legend-chip"><span className="legend-dot dot-med" /> 30–80 MW</span>
                <span className="legend-chip"><span className="legend-dot dot-high" /> &gt; 80 MW</span>
              </>
            ) : filters.spatialAggregation === "grid" ? (
              <>
                <span className="legend-chip"><span className="legend-rect rect-low" /> Low Density</span>
                <span className="legend-chip"><span className="legend-rect rect-med" /> Moderate</span>
                <span className="legend-chip"><span className="legend-rect rect-high" /> Extreme Density</span>
              </>
            ) : (
              <>
                <span className="legend-chip"><span className="legend-dot dot-cluster" /> Wildfire Activity Cluster</span>
              </>
            )}
          </div>
        </div>

        <div className="historical-map-frame">
          <MapContainer
            center={REGION_CENTERS[filters.region]?.center || [18, 5]}
            zoom={REGION_CENTERS[filters.region]?.zoom || 2}
            minZoom={2}
            maxZoom={12}
            scrollWheelZoom
            worldCopyJump
            className="leaflet-historical-map"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
            />
            <MapViewController region={filters.region} />

            {/* Mode 1: Individual Detections */}
            {filters.spatialAggregation === "detections" &&
              data?.spatial_distribution.points.map((pt) => {
                const frp = pt.frp_mw ?? 15;
                const fillColor = frp > 80 ? "#d92d1f" : frp > 30 ? "#f58200" : "#e9b77e";
                const radius = Math.min(10, Math.max(4, Math.sqrt(frp) / 1.5));
                return (
                  <CircleMarker
                    key={pt.id}
                    center={[pt.latitude, pt.longitude]}
                    radius={radius}
                    pathOptions={{
                      color: "#1b2019",
                      weight: 1,
                      fillColor,
                      fillOpacity: 0.85,
                    }}
                  >
                    <Popup className="historical-leaflet-popup">
                      <div className="map-popup-card">
                        <div className="popup-title">HOTSPOT DETECTION</div>
                        <div className="popup-row"><span>ID:</span> <strong>{pt.id}</strong></div>
                        <div className="popup-row"><span>Date:</span> <strong>{pt.acq_date}</strong></div>
                        <div className="popup-row"><span>Platform:</span> <strong>{pt.platform}</strong></div>
                        <div className="popup-row"><span>FRP:</span> <strong>{pt.frp_mw ? `${pt.frp_mw} MW` : "—"}</strong></div>
                        <div className="popup-row"><span>Coordinates:</span> <strong>{pt.latitude.toFixed(2)}, {pt.longitude.toFixed(2)}</strong></div>
                        {pt.confidence && <div className="popup-row"><span>Confidence:</span> <strong>{pt.confidence}</strong></div>}
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}

            {/* Mode 2: Grid Cells */}
            {filters.spatialAggregation === "grid" &&
              data?.spatial_distribution.grid_cells.map((cell) => {
                const count = cell.detections;
                const fillColor = count > 50 ? "#d92d1f" : count > 15 ? "#f58200" : "#e9b77e";
                const fillOpacity = Math.min(0.75, Math.max(0.25, 0.2 + count / 100));
                return (
                  <Rectangle
                    key={cell.id}
                    bounds={[
                      [cell.min_lat, cell.min_lon],
                      [cell.max_lat, cell.max_lon],
                    ]}
                    pathOptions={{
                      color: "#f58200",
                      weight: 0.8,
                      fillColor,
                      fillOpacity,
                    }}
                  >
                    <Popup className="historical-leaflet-popup">
                      <div className="map-popup-card">
                        <div className="popup-title">2° SPATIAL DENSITY GRID CELL</div>
                        <div className="popup-row"><span>Detections:</span> <strong>{formatNum(cell.detections, 0)}</strong></div>
                        <div className="popup-row"><span>Mean FRP:</span> <strong>{formatNum(cell.mean_frp)} MW</strong></div>
                        <div className="popup-row"><span>Peak FRP:</span> <strong>{formatNum(cell.max_frp)} MW</strong></div>
                        <div className="popup-row"><span>Bounds Lat:</span> <strong>{cell.min_lat}° to {cell.max_lat}°</strong></div>
                        <div className="popup-row"><span>Bounds Lon:</span> <strong>{cell.min_lon}° to {cell.max_lon}°</strong></div>
                      </div>
                    </Popup>
                  </Rectangle>
                );
              })}

            {/* Mode 3: Activity Clusters */}
            {filters.spatialAggregation === "clusters" &&
              data?.spatial_distribution.clusters.map((c) => {
                const radius = Math.min(18, Math.max(5, 4 + Math.sqrt(c.member_count) * 2));
                return (
                  <CircleMarker
                    key={c.cluster_id}
                    center={[c.latitude, c.longitude]}
                    radius={radius}
                    pathOptions={{
                      color: "#80a66f",
                      weight: 2,
                      fillColor: "#80a66f",
                      fillOpacity: 0.6,
                    }}
                  >
                    <Popup className="historical-leaflet-popup">
                      <div className="map-popup-card">
                        <div className="popup-title">WILDFIRE ACTIVITY CLUSTER</div>
                        <div className="popup-row"><span>Cluster ID:</span> <strong>{c.cluster_id}</strong></div>
                        <div className="popup-row"><span>Members:</span> <strong>{c.member_count} detections</strong></div>
                        <div className="popup-row"><span>Mean FRP:</span> <strong>{formatNum(c.mean_frp)} MW</strong></div>
                        <div className="popup-row"><span>Max FRP:</span> <strong>{formatNum(c.max_frp)} MW</strong></div>
                        <div className="popup-row"><span>Dates:</span> <strong>{c.first_date} → {c.last_date}</strong></div>
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
          </MapContainer>
        </div>
      </section>

      {/* 7. Footer Status & Scientific Methodology Notes */}
      <footer className="historical-footer">
        <div className="footer-left">
          <span className="source-dot live" />
          <span>Connected to DuckDB Historical Archive</span>
          <span className="dot">·</span>
          <span>Tables: <code>UNIFIED_DETECTIONS</code>, <code>harm_sensor_activity_daily</code>, <code>harm_activity_clusters</code></span>
        </div>
        <div className="footer-right">
          <span>NASA FIRMS Standardized Observations &amp; Harmonized Wildfire Clusters</span>
          <span className="dot">·</span>
          <span>TwinFlame Intelligence Suite</span>
        </div>
      </footer>
    </div>
  );
}
