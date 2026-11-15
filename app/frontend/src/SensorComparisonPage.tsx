import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRightLeft,
  Calendar,
  ChevronDown,
  Clock,
  Compass,
  Flame,
  Globe2,
  Layers,
  Moon,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  Sun,
  Thermometer,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ComparisonPlatform = "terra" | "aqua" | "noaa20" | "noaa21";
type ComparisonMetric = "detection_count" | "frp" | "brightness" | "temporal_diff" | "spatial_diff";
type ComparisonEligibility = "all" | "matched_only" | "coincident_overpasses";
type DatePreset = "all" | "1y" | "90d" | "30d" | "7d" | "custom";

type Filters = {
  preset: DatePreset;
  startDate: string;
  endDate: string;
  region: string;
  platformA: ComparisonPlatform;
  platformB: ComparisonPlatform;
  daynight: string;
  comparisonMetric: ComparisonMetric;
  temporalWindowMinutes: number;
  spatialThresholdMeters: number;
  eligibility: ComparisonEligibility;
};

type PlatformSpecs = {
  id: string;
  name: string;
  satellite: string;
  instrument: string;
  operator: string;
  launch_year: number;
  spatial_resolution: string;
  equator_crossing_time: string;
  altitude_km: number;
  spectral_bands: string;
  swath_width_km: number;
  saturation_temp: string;
  characteristics: string;
};

type PlatformSummary = {
  total_detections: number;
  mean_frp: number | null;
  median_frp: number | null;
  p90_frp: number | null;
  total_frp: number | null;
  max_frp: number | null;
  mean_brightness: number | null;
  median_brightness: number | null;
  max_brightness: number | null;
  mean_bright_t31: number | null;
  day_count: number;
  night_count: number;
};

type ComparisonData = {
  generated_at: string;
  scientific_caution: string;
  platform_a: {
    id: ComparisonPlatform;
    specs: PlatformSpecs;
    summary: PlatformSummary;
  };
  platform_b: {
    id: ComparisonPlatform;
    specs: PlatformSpecs;
    summary: PlatformSummary;
  };
  comparative_kpis: {
    detection_ratio: number | null;
    frp_ratio: number | null;
    detection_difference: number;
    frp_difference: number | null;
    matched_pairs_count: number;
    mean_time_difference_minutes: number | null;
    median_time_difference_minutes: number | null;
    mean_spatial_distance_meters: number | null;
    median_spatial_distance_meters: number | null;
  };
  detection_counts: {
    platform_a: number;
    platform_b: number;
    total: number;
    share_a_pct: number;
    share_b_pct: number;
  };
  frp_distribution: Array<{
    bracket: string;
    count_a: number;
    count_b: number;
    pct_a: number;
    pct_b: number;
  }>;
  daily_trends: Array<{
    date: string;
    detections_a: number;
    detections_b: number;
    mean_frp_a: number | null;
    mean_frp_b: number | null;
  }>;
  brightness_comparison: {
    available: boolean;
    distribution: Array<{
      bracket: string;
      count_a: number;
      count_b: number;
    }>;
  };
  diurnal_distribution: Array<{
    hour: number;
    label: string;
    detections_a: number;
    detections_b: number;
  }>;
  temporal_differences: {
    matched_count: number;
    mean_delta_minutes: number | null;
    median_delta_minutes: number | null;
    distribution: Array<{
      bracket: string;
      count: number;
    }>;
  };
  spatial_differences: {
    mean_distance_meters: number | null;
    median_distance_meters: number | null;
    distribution: Array<{
      bracket: string;
      count: number;
    }>;
  };
  sources: {
    detection_metrics: string;
    daily_trends: string;
    frp_comparisons: string;
  };
  capabilities: {
    brightness: boolean;
    frp: boolean;
    daynight: boolean;
    coincidence_matching: boolean;
  };
};

const PLATFORM_OPTIONS: Array<{ value: ComparisonPlatform; label: string; sensor: string }> = [
  { value: "terra", label: "Terra / MODIS (10:30 LST)", sensor: "MODIS (1000m)" },
  { value: "aqua", label: "Aqua / MODIS (13:30 LST)", sensor: "MODIS (1000m)" },
  { value: "noaa20", label: "NOAA-20 / VIIRS (13:30 LST)", sensor: "VIIRS (375m)" },
  { value: "noaa21", label: "NOAA-21 / VIIRS (13:30 LST)", sensor: "VIIRS (375m)" },
];

const REGIONS: [string, string][] = [
  ["global", "Global (All Regions)"],
  ["africa", "Africa"],
  ["asia", "Asia"],
  ["europe", "Europe"],
  ["north-america", "North America"],
  ["oceania", "Oceania"],
  ["south-america", "South America"],
];

const METRICS: [ComparisonMetric, string][] = [
  ["detection_count", "Detection Count"],
  ["frp", "Fire Radiative Power (FRP)"],
  ["brightness", "Brightness Temperature"],
  ["temporal_diff", "Temporal Difference (Δt)"],
  ["spatial_diff", "Spatial Proximity (Distance)"],
];

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

function dateLabel(value: string) {
  const d = new Date(`${value}T00:00:00`);
  return isNaN(d.getTime()) ? value : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function calculatePresetDates(preset: DatePreset): { startDate: string; endDate: string } {
  const now = new Date();
  const endIso = now.toISOString().slice(0, 10);
  if (preset === "all") return { startDate: "", endDate: "" };
  const start = new Date(now);
  if (preset === "1y") start.setFullYear(now.getFullYear() - 1);
  else if (preset === "90d") start.setDate(now.getDate() - 90);
  else if (preset === "30d") start.setDate(now.getDate() - 30);
  else if (preset === "7d") start.setDate(now.getDate() - 7);
  return { startDate: start.toISOString().slice(0, 10), endDate: endIso };
}

export default function SensorComparisonPage() {
  const [filters, setFilters] = useState<Filters>({
    preset: "all",
    startDate: "",
    endDate: "",
    region: "global",
    platformA: "terra",
    platformB: "noaa20",
    daynight: "all",
    comparisonMetric: "detection_count",
    temporalWindowMinutes: 60,
    spatialThresholdMeters: 2000,
    eligibility: "all",
  });

  const [data, setData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [frpChartMode, setFrpChartMode] = useState<"count" | "pct">("pct");

  // Fetch API
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      // Validation: prevent querying identical platforms
      if (filters.platformA === filters.platformB) {
        setError("Platform A and Platform B must be different platforms for comparison.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");

      const params = new URLSearchParams({
        platform_a: filters.platformA,
        platform_b: filters.platformB,
        region: filters.region,
        daynight: filters.daynight,
        comparison_metric: filters.comparisonMetric,
        temporal_window_minutes: String(filters.temporalWindowMinutes),
        spatial_threshold_meters: String(filters.spatialThresholdMeters),
        eligibility: filters.eligibility,
      });

      if (filters.startDate) params.set("start_date", filters.startDate);
      if (filters.endDate) params.set("end_date", filters.endDate);

      const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
      const url = `${base}/api/sensor-comparison?${params.toString()}`;

      try {
        const res = await fetch(url, { signal: controller.signal });
        const body = await res.json();
        if (!res.ok) {
          throw new Error(body.detail ?? "Failed to load sensor comparison.");
        }
        setData(body as ComparisonData);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Failed to load sensor comparison.");
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

  // Swap Platform A and Platform B
  const handleSwapPlatforms = () => {
    setFilters((prev) => ({
      ...prev,
      platformA: prev.platformB,
      platformB: prev.platformA,
    }));
  };

  // Safe Platform A change (ensuring Platform B != Platform A)
  const handlePlatformAChange = (newA: ComparisonPlatform) => {
    setFilters((prev) => {
      let nextB = prev.platformB;
      if (newA === nextB) {
        // Automatically switch Platform B to an alternate platform
        nextB = PLATFORM_OPTIONS.find((opt) => opt.value !== newA)?.value ?? "noaa20";
      }
      return { ...prev, platformA: newA, platformB: nextB };
    });
  };

  // Safe Platform B change
  const handlePlatformBChange = (newB: ComparisonPlatform) => {
    setFilters((prev) => {
      let nextA = prev.platformA;
      if (newB === nextA) {
        nextA = PLATFORM_OPTIONS.find((opt) => opt.value !== newB)?.value ?? "terra";
      }
      return { ...prev, platformA: nextA, platformB: newB };
    });
  };

  // Reset Filters
  const handleResetFilters = () => {
    setFilters({
      preset: "all",
      startDate: "",
      endDate: "",
      region: "global",
      platformA: "terra",
      platformB: "noaa20",
      daynight: "all",
      comparisonMetric: "detection_count",
      temporalWindowMinutes: 60,
      spatialThresholdMeters: 2000,
      eligibility: "all",
    });
  };

  const nameA = data?.platform_a.specs.name ?? "Platform A";
  const nameB = data?.platform_b.specs.name ?? "Platform B";
  const kpis = data?.comparative_kpis;
  const counts = data?.detection_counts;

  return (
    <div className="comparison-page-container">
      {/* 1. Header & Title Section */}
      <section className="comparison-header">
        <div className="comparison-header-main">
          <div className="comparison-badge">
            <span className="badge-pulse" />
            <span>SENSOR COMPARISON</span>
          </div>
          <h1>Cross-Platform Sensor &amp; Observation Comparison</h1>
          <p className="comparison-subtitle">
            Evaluate observational disparities, spatial resolution sensitivity thresholds, Fire Radiative Power (FRP) scaling,
            and diurnal overpass timing across NASA EOS (MODIS) and NOAA JPSS (VIIRS) constellations.
          </p>
        </div>

        <div className="comparison-header-actions">
          <button
            type="button"
            className="action-btn refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
          >
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            <span>Refresh</span>
          </button>
        </div>
      </section>

      {/* 2. Scientific Caution Callout (Mandatory Scientific Context) */}
      <section className="scientific-caution-card">
        <div className="caution-icon">
          <AlertTriangle size={20} />
        </div>
        <div className="caution-content">
          <div className="caution-title">SCIENTIFIC OBSERVATION CAUTION</div>
          <p>
            {data?.scientific_caution ??
              "Differences in detection counts do not necessarily mean one sensor is better. Spatial resolution (375m VIIRS vs 1000m MODIS), overpass timing (morning vs afternoon vs nighttime), detection sensitivity, and observation conditions (cloud cover, scan angle, solar reflection) all matter."}
          </p>
        </div>
      </section>

      {/* 3. Hero Platform Selector (Head-to-Head Duel Card) */}
      <section className="platform-duel-grid">
        {/* Card Platform A */}
        <div className="platform-duel-card card-a">
          <div className="duel-card-header">
            <div className="duel-tag a-tag">PRIMARY PLATFORM (A)</div>
            <span className="duel-sensor-pill">{data?.platform_a.specs.instrument ?? "MODIS"}</span>
          </div>
          <div className="duel-select-row">
            <select
              value={filters.platformA}
              onChange={(e) => handlePlatformAChange(e.target.value as ComparisonPlatform)}
              className="duel-select"
            >
              {PLATFORM_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="duel-specs-list">
            <div className="spec-row">
              <span>Satellite:</span>
              <strong>{data?.platform_a.specs.satellite ?? "Terra (EOS-AM1)"}</strong>
            </div>
            <div className="spec-row">
              <span>Resolution:</span>
              <strong>{data?.platform_a.specs.spatial_resolution ?? "1000m"}</strong>
            </div>
            <div className="spec-row">
              <span>Equator Crossing:</span>
              <strong>{data?.platform_a.specs.equator_crossing_time ?? "10:30 AM / 22:30 PM"}</strong>
            </div>
            <div className="spec-row">
              <span>Bands:</span>
              <strong>{data?.platform_a.specs.spectral_bands ?? "B21/22 & B31"}</strong>
            </div>
          </div>
        </div>

        {/* Center Versus & Swap Button */}
        <div className="platform-duel-center">
          <button
            type="button"
            className="swap-btn"
            onClick={handleSwapPlatforms}
            title="Swap Platform A and Platform B"
          >
            <ArrowRightLeft size={16} />
            <span>SWAP</span>
          </button>
          <div className="vs-circle">VS</div>
          <div className="duel-metric-badge">
            {METRICS.find(([v]) => v === filters.comparisonMetric)?.[1] ?? "Detection Count"}
          </div>
        </div>

        {/* Card Platform B */}
        <div className="platform-duel-card card-b">
          <div className="duel-card-header">
            <div className="duel-tag b-tag">COMPARISON PLATFORM (B)</div>
            <span className="duel-sensor-pill">{data?.platform_b.specs.instrument ?? "VIIRS"}</span>
          </div>
          <div className="duel-select-row">
            <select
              value={filters.platformB}
              onChange={(e) => handlePlatformBChange(e.target.value as ComparisonPlatform)}
              className="duel-select"
            >
              {PLATFORM_OPTIONS.map((opt) => (
                <option
                  key={opt.value}
                  value={opt.value}
                  disabled={opt.value === filters.platformA}
                >
                  {opt.label} {opt.value === filters.platformA ? "(Selected in A)" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="duel-specs-list">
            <div className="spec-row">
              <span>Satellite:</span>
              <strong>{data?.platform_b.specs.satellite ?? "NOAA-20 (JPSS-1)"}</strong>
            </div>
            <div className="spec-row">
              <span>Resolution:</span>
              <strong>{data?.platform_b.specs.spatial_resolution ?? "375m"}</strong>
            </div>
            <div className="spec-row">
              <span>Equator Crossing:</span>
              <strong>{data?.platform_b.specs.equator_crossing_time ?? "13:30 PM / 01:30 AM"}</strong>
            </div>
            <div className="spec-row">
              <span>Bands:</span>
              <strong>{data?.platform_b.specs.spectral_bands ?? "I4 & I5"}</strong>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Controls & Secondary Filter Toolbar */}
      <section className="comparison-filter-bar">
        {/* Preset Range */}
        <div className="filter-group preset-group">
          <span className="filter-label">
            <Calendar size={13} /> TIME WINDOW
          </span>
          <div className="preset-buttons">
            {(
              [
                ["all", "All Time"],
                ["1y", "1 Year"],
                ["90d", "90 Days"],
                ["30d", "30 Days"],
                ["7d", "7 Days"],
                ["custom", "Custom"],
              ] as [DatePreset, string][]
            ).map(([pKey, label]) => (
              <button
                key={pKey}
                type="button"
                className={`preset-pill ${filters.preset === pKey ? "active" : ""}`}
                onClick={() => handlePresetChange(pKey)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Custom Date Inputs */}
        <div className="filter-group">
          <span className="filter-label">DATE RANGE</span>
          <div className="date-inputs-inline">
            <input
              type="date"
              className="filter-input date-input"
              value={filters.startDate}
              onChange={(e) => setFilters((p) => ({ ...p, preset: "custom", startDate: e.target.value }))}
            />
            <span className="date-sep">→</span>
            <input
              type="date"
              className="filter-input date-input"
              value={filters.endDate}
              onChange={(e) => setFilters((p) => ({ ...p, preset: "custom", endDate: e.target.value }))}
            />
          </div>
        </div>

        {/* Geographic Region */}
        <div className="filter-group">
          <span className="filter-label">
            <Globe2 size={13} /> GEOGRAPHIC REGION
          </span>
          <div className="select-wrapper">
            <select
              value={filters.region}
              onChange={(e) => setFilters((p) => ({ ...p, region: e.target.value }))}
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

        {/* Day / Night */}
        <div className="filter-group">
          <span className="filter-label">
            {filters.daynight === "day" ? <Sun size={13} /> : filters.daynight === "night" ? <Moon size={13} /> : <SlidersHorizontal size={13} />}
            DAY / NIGHT
          </span>
          <div className="select-wrapper">
            <select
              value={filters.daynight}
              onChange={(e) => setFilters((p) => ({ ...p, daynight: e.target.value }))}
            >
              <option value="all">Day &amp; Night</option>
              <option value="day">Daytime Only (D)</option>
              <option value="night">Nighttime Only (N)</option>
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Comparison Metric */}
        <div className="filter-group">
          <span className="filter-label">PRIMARY COMPARISON METRIC</span>
          <div className="select-wrapper">
            <select
              value={filters.comparisonMetric}
              onChange={(e) => setFilters((p) => ({ ...p, comparisonMetric: e.target.value as ComparisonMetric }))}
            >
              {METRICS.map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Matching Window */}
        <div className="filter-group">
          <span className="filter-label">
            <Clock size={13} /> MATCHING WINDOW
          </span>
          <div className="select-wrapper">
            <select
              value={filters.temporalWindowMinutes}
              onChange={(e) => setFilters((p) => ({ ...p, temporalWindowMinutes: Number(e.target.value) }))}
            >
              <option value="15">± 15 min (Instantaneous)</option>
              <option value="30">± 30 min (Orbital Phase)</option>
              <option value="60">± 60 min (1 Hour Window)</option>
              <option value="120">± 120 min (2 Hours)</option>
              <option value="180">± 180 min (3 Hours)</option>
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Spatial Threshold */}
        <div className="filter-group">
          <span className="filter-label">
            <Compass size={13} /> SPATIAL THRESHOLD
          </span>
          <div className="select-wrapper">
            <select
              value={filters.spatialThresholdMeters}
              onChange={(e) => setFilters((p) => ({ ...p, spatialThresholdMeters: Number(e.target.value) }))}
            >
              <option value="500">500 m (VIIRS Pixel)</option>
              <option value="1000">1000 m (1 km MODIS Pixel)</option>
              <option value="2000">2000 m (2 km Clustered)</option>
              <option value="3000">3000 m (3 km Area)</option>
              <option value="5000">5000 m (5 km Regional)</option>
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Eligibility Mode */}
        <div className="filter-group">
          <span className="filter-label">COMPARISON ELIGIBILITY</span>
          <div className="select-wrapper">
            <select
              value={filters.eligibility}
              onChange={(e) => setFilters((p) => ({ ...p, eligibility: e.target.value as ComparisonEligibility }))}
            >
              <option value="all">All Domain Detections</option>
              <option value="matched_only">Coincident / Matched Pairs Only</option>
              <option value="coincident_overpasses">Coincident Orbit Swaths</option>
            </select>
            <ChevronDown size={14} className="select-chevron" />
          </div>
        </div>

        {/* Reset Button */}
        <div className="filter-group reset-group">
          <button
            type="button"
            className="action-btn reset-btn"
            onClick={handleResetFilters}
            title="Reset filters"
          >
            <RotateCcw size={13} />
            <span>Reset</span>
          </button>
        </div>
      </section>

      {/* Error Message */}
      {error && (
        <div className="comparison-error-banner">
          <AlertCircle size={18} />
          <div className="error-content">
            <strong>Sensor comparison query error</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* 5. Key Comparative Indicators Strip */}
      <section className="comparison-kpi-grid">
        {/* KPI 1: Detection Ratio */}
        <div className="comparison-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon orange">
              <Flame size={16} />
            </span>
            <span className="kpi-title">DETECTION RATIO (A / B)</span>
            <span className="kpi-tag">{nameA} : {nameB}</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : kpis?.detection_ratio != null ? `${kpis.detection_ratio}×` : "—"}
          </div>
          <div className="kpi-subtext">
            <span>{nameA}: <strong>{formatNum(counts?.platform_a, 0)}</strong> ({counts?.share_a_pct}%)</span>
            <span className="dot">·</span>
            <span>{nameB}: <strong>{formatNum(counts?.platform_b, 0)}</strong> ({counts?.share_b_pct}%)</span>
          </div>
        </div>

        {/* KPI 2: Mean FRP Scaling Ratio */}
        <div className="comparison-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon red">
              <Zap size={16} />
            </span>
            <span className="kpi-title">MEAN FRP RATIO (A / B)</span>
            <span className="kpi-tag">INTENSITY SCALING</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : kpis?.frp_ratio != null ? `${kpis.frp_ratio}×` : "—"}
          </div>
          <div className="kpi-subtext">
            <span>A: <strong>{formatNum(data?.platform_a.summary.mean_frp)} MW</strong></span>
            <span className="dot">·</span>
            <span>B: <strong>{formatNum(data?.platform_b.summary.mean_frp)} MW</strong></span>
          </div>
        </div>

        {/* KPI 3: Coincident Matches */}
        <div className="comparison-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon green">
              <Layers size={16} />
            </span>
            <span className="kpi-title">COINCIDENT MATCHES</span>
            <span className="kpi-tag">SPATIO-TEMPORAL</span>
          </div>
          <div className="kpi-number">
            {loading && !data ? "..." : formatNum(kpis?.matched_pairs_count, 0)}
          </div>
          <div className="kpi-subtext">
            Within ±{filters.temporalWindowMinutes} min and {filters.spatialThresholdMeters} m
          </div>
        </div>

        {/* KPI 4: Mean Temporal Offset */}
        <div className="comparison-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon blue">
              <Clock size={16} />
            </span>
            <span className="kpi-title">MEAN TIME OFFSET (Δt)</span>
            <span className="kpi-tag">ORBITAL SEPARATION</span>
          </div>
          <div className="kpi-number">
            {loading && !data
              ? "..."
              : kpis?.mean_time_difference_minutes != null
                ? `${formatNum(kpis.mean_time_difference_minutes)} min`
                : "—"}
          </div>
          <div className="kpi-subtext">
            Median: <strong>{formatNum(kpis?.median_time_difference_minutes)} min</strong>
          </div>
        </div>

        {/* KPI 5: Mean Spatial Proximity */}
        <div className="comparison-kpi-card">
          <div className="kpi-top">
            <span className="kpi-icon copper">
              <Compass size={16} />
            </span>
            <span className="kpi-title">MEAN CENTROID DISTANCE</span>
            <span className="kpi-tag">PIXEL REGISTRATION</span>
          </div>
          <div className="kpi-number">
            {loading && !data
              ? "..."
              : kpis?.mean_spatial_distance_meters != null
                ? `${formatNum(kpis.mean_spatial_distance_meters, 0)} m`
                : "—"}
          </div>
          <div className="kpi-subtext">
            Median: <strong>{formatNum(kpis?.median_spatial_distance_meters, 0)} m</strong>
          </div>
        </div>
      </section>

      {/* 6. Chart Grid: Row 1 */}
      <section className="comparison-chart-grid">
        {/* Viz 1: Detection Counts Comparison */}
        <article className="comparison-panel count-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet orange" />
                <h3>Detection Counts per Platform</h3>
                <span className="source-pill">Source: UNIFIED_DETECTIONS</span>
              </div>
              <p className="panel-desc">
                Direct detection count comparison across the selected geographic domain and observation window.
              </p>
            </div>
            <span className="unit-label">TOTAL DETECTIONS</span>
          </div>

          <div className="chart-body">
            {data ? (
              <div className="count-compare-wrapper">
                <div className="count-bars-container">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart
                      data={[
                        {
                          name: nameA,
                          detections: data.detection_counts.platform_a,
                          color: "#f58200",
                        },
                        {
                          name: nameB,
                          detections: data.detection_counts.platform_b,
                          color: "#d92d1f",
                        },
                      ]}
                      layout="vertical"
                      margin={{ top: 10, right: 30, left: 15, bottom: 5 }}
                    >
                      <CartesianGrid horizontal={false} stroke="#2c3328" />
                      <XAxis
                        type="number"
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v) => compactNum(v)}
                        tick={{ fill: "#a0a596", fontSize: 11 }}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        axisLine={false}
                        tickLine={false}
                        width={110}
                        tick={{ fill: "#f3efe7", fontSize: 12, fontWeight: 600 }}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#1b2019",
                          borderColor: "#30362c",
                          borderRadius: 8,
                          fontSize: 12,
                          color: "#f3efe7",
                        }}
                        formatter={(val) => [formatNum(Number(val), 0), "Detections"]}
                      />
                      <Bar dataKey="detections" radius={[0, 5, 5, 0]} maxBarSize={28}>
                        <Cell fill="#f58200" />
                        <Cell fill="#d92d1f" />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Relative Share Progress Bar */}
                <div className="share-breakdown">
                  <div className="share-progress-track">
                    <div
                      className="share-progress-a"
                      style={{ width: `${data.detection_counts.share_a_pct}%` }}
                    />
                    <div
                      className="share-progress-b"
                      style={{ width: `${data.detection_counts.share_b_pct}%` }}
                    />
                  </div>
                  <div className="share-legend">
                    <span className="share-item a-color">
                      <span className="dot dot-a" />
                      {nameA}: <strong>{data.detection_counts.share_a_pct}%</strong> ({formatNum(data.detection_counts.platform_a, 0)})
                    </span>
                    <span className="share-item b-color">
                      <span className="dot dot-b" />
                      {nameB}: <strong>{data.detection_counts.share_b_pct}%</strong> ({formatNum(data.detection_counts.platform_b, 0)})
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-chart-state">
                <Activity size={20} />
                <span>Loading detection comparison...</span>
              </div>
            )}
          </div>
        </article>

        {/* Viz 2: FRP Distribution by Platform */}
        <article className="comparison-panel frp-dist-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet red" />
                <h3>FRP Distribution by Platform</h3>
                <span className="source-pill">SENSITIVITY TAILS</span>
              </div>
              <p className="panel-desc">
                Fire Radiative Power (MW) frequency comparison showing sensor sensitivity differences in detecting micro vs intense fires.
              </p>
            </div>
            <div className="mode-toggle">
              <button
                type="button"
                className={`mode-btn ${frpChartMode === "pct" ? "active" : ""}`}
                onClick={() => setFrpChartMode("pct")}
              >
                Percentage (%)
              </button>
              <button
                type="button"
                className={`mode-btn ${frpChartMode === "count" ? "active" : ""}`}
                onClick={() => setFrpChartMode("count")}
              >
                Raw Counts
              </button>
            </div>
          </div>

          <div className="chart-body">
            {data && data.frp_distribution.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={data.frp_distribution}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="bracket"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#a0a596", fontSize: 10 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => (frpChartMode === "pct" ? `${v}%` : compactNum(v))}
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
                    formatter={(val, name) => [
                      frpChartMode === "pct" ? `${val}%` : formatNum(Number(val), 0),
                      name === (frpChartMode === "pct" ? "pct_a" : "count_a") ? nameA : nameB,
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 6 }}
                    formatter={(val) => (val.includes("_a") ? nameA : nameB)}
                  />
                  <Bar
                    dataKey={frpChartMode === "pct" ? "pct_a" : "count_a"}
                    name={frpChartMode === "pct" ? "pct_a" : "count_a"}
                    fill="#f58200"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={22}
                  />
                  <Bar
                    dataKey={frpChartMode === "pct" ? "pct_b" : "count_b"}
                    name={frpChartMode === "pct" ? "pct_b" : "count_b"}
                    fill="#d92d1f"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={22}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Zap size={20} />
                <span>No FRP observations available for this comparison.</span>
              </div>
            )}
          </div>
        </article>
      </section>

      {/* 7. Chart Grid: Row 2 */}
      <section className="comparison-chart-grid">
        {/* Viz 3: Daily Detection Trends */}
        <article className="comparison-panel daily-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet orange" />
                <h3>Daily Detection Trends</h3>
                <span className="source-pill">Source: UNIFIED_DETECTIONS</span>
              </div>
              <p className="panel-desc">
                Synchronized daily detection volume tracking temporal continuity and missing orbit passes.
              </p>
            </div>
            <span className="unit-label">OBSERVATIONS / DAY</span>
          </div>

          <div className="chart-body">
            {data && data.daily_trends.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart
                  data={data.daily_trends}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={dateLabel}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={26}
                    tick={{ fill: "#a0a596", fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => compactNum(v)}
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
                    labelFormatter={(l) => dateLabel(String(l))}
                    formatter={(val, name) => [
                      formatNum(Number(val), 0),
                      name === "detections_a" ? nameA : nameB,
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 6 }}
                    formatter={(val) => (val === "detections_a" ? nameA : nameB)}
                  />
                  <Line
                    type="monotone"
                    dataKey="detections_a"
                    name="detections_a"
                    stroke="#f58200"
                    strokeWidth={2.2}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="detections_b"
                    name="detections_b"
                    stroke="#d92d1f"
                    strokeWidth={2.2}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <TrendingUp size={20} />
                <span>No daily observations match these filters.</span>
              </div>
            )}
          </div>
        </article>

        {/* Viz 4: Mean & Median FRP Comparisons */}
        <article className="comparison-panel frp-metrics-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet red" />
                <h3>Mean &amp; Median FRP Metrics Comparison</h3>
                <span className="source-pill">Source: harm_sensor_activity_daily</span>
              </div>
              <p className="panel-desc">
                Comparative statistical indicators: Mean, Median, 90th percentile, and Total Integrated Fire Radiative Power (MW).
              </p>
            </div>
            <span className="unit-label">MEGAWATTS (MW)</span>
          </div>

          <div className="chart-body">
            {data ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={[
                    {
                      metric: "Mean FRP",
                      val_a: data.platform_a.summary.mean_frp,
                      val_b: data.platform_b.summary.mean_frp,
                    },
                    {
                      metric: "Median FRP",
                      val_a: data.platform_a.summary.median_frp,
                      val_b: data.platform_b.summary.median_frp,
                    },
                    {
                      metric: "P90 Peak FRP",
                      val_a: data.platform_a.summary.p90_frp,
                      val_b: data.platform_b.summary.p90_frp,
                    },
                  ]}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="metric"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#f3efe7", fontSize: 11, fontWeight: 600 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => `${compactNum(v)}`}
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
                    formatter={(val, name) => [`${formatNum(Number(val))} MW`, name === "val_a" ? nameA : nameB]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 6 }}
                    formatter={(val) => (val === "val_a" ? nameA : nameB)}
                  />
                  <Bar dataKey="val_a" name="val_a" fill="#f58200" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="val_b" name="val_b" fill="#d92d1f" radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Zap size={20} />
                <span>Loading FRP metrics...</span>
              </div>
            )}
          </div>
        </article>
      </section>

      {/* 8. Chart Grid: Row 3 */}
      <section className="comparison-chart-grid">
        {/* Viz 5: Brightness Band Comparisons */}
        <article className="comparison-panel brightness-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet copper" />
                <h3>Brightness Band Comparisons</h3>
                <span className="source-pill">MWIR Band (4 µm)</span>
              </div>
              <p className="panel-desc">
                Medium-wave infrared brightness temperature (Kelvin) distribution comparing thermal radiator response.
              </p>
            </div>
            <span className="unit-label">KELVIN (K)</span>
          </div>

          <div className="chart-body">
            {!data?.brightness_comparison.available ? (
              <div className="empty-chart-state">
                <Thermometer size={20} />
                <span>Brightness temperature columns are not available in current database schema.</span>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={data.brightness_comparison.distribution}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="bracket"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#a0a596", fontSize: 10 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => compactNum(v)}
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
                    formatter={(val, name) => [
                      formatNum(Number(val), 0),
                      name === "count_a" ? nameA : nameB,
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 6 }}
                    formatter={(val) => (val === "count_a" ? nameA : nameB)}
                  />
                  <Bar dataKey="count_a" name="count_a" fill="#e9b77e" radius={[4, 4, 0, 0]} maxBarSize={22} />
                  <Bar dataKey="count_b" name="count_b" fill="#8d321d" radius={[4, 4, 0, 0]} maxBarSize={22} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </article>

        {/* Viz 6: Detection Time Differences & Diurnal Distribution */}
        <article className="comparison-panel diurnal-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet blue" />
                <h3>Diurnal Overpass &amp; Detection Time Differences</h3>
                <span className="source-pill">ORBITAL OVERPASS (UTC)</span>
              </div>
              <p className="panel-desc">
                Diurnal 24-hour observation distribution highlighting orbital equator crossing schedules and revisit timing.
              </p>
            </div>
            <span className="unit-label">HOURLY DETECTIONS</span>
          </div>

          <div className="chart-body">
            {data && data.diurnal_distribution.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart
                  data={data.diurnal_distribution}
                  margin={{ top: 12, right: 15, left: -10, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="diurnalAGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f58200" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#f58200" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="diurnalBGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#d92d1f" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#d92d1f" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="label"
                    tickLine={false}
                    axisLine={false}
                    interval={2}
                    tick={{ fill: "#a0a596", fontSize: 10 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => compactNum(v)}
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
                    formatter={(val, name) => [
                      formatNum(Number(val), 0),
                      name === "detections_a" ? nameA : nameB,
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ fontSize: 11, paddingBottom: 6 }}
                    formatter={(val) => (val === "detections_a" ? nameA : nameB)}
                  />
                  <Area
                    type="monotone"
                    dataKey="detections_a"
                    name="detections_a"
                    stroke="#f58200"
                    strokeWidth={2}
                    fill="url(#diurnalAGrad)"
                  />
                  <Area
                    type="monotone"
                    dataKey="detections_b"
                    name="detections_b"
                    stroke="#d92d1f"
                    strokeWidth={2}
                    fill="url(#diurnalBGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart-state">
                <Clock size={20} />
                <span>No diurnal timestamps available for comparison.</span>
              </div>
            )}
          </div>
        </article>
      </section>

      {/* 9. Coincident Detection Time Differences (Δt) & Proximity Breakdown */}
      <section className="matched-pairs-section">
        <article className="comparison-panel matched-pairs-panel">
          <div className="panel-header">
            <div>
              <div className="panel-title-row">
                <span className="panel-bullet green" />
                <h3>Coincident Hotspot Time Difference (Δt) Distribution</h3>
                <span className="source-pill">Source: {data?.sources.frp_comparisons ?? "harm_frp_comparisons"}</span>
              </div>
              <p className="panel-desc">
                Temporal offset (|t_A - t_B|) between coincident fire observations detected by both satellites within {filters.spatialThresholdMeters} meters.
              </p>
            </div>
            <span className="unit-label">MATCHED PAIRS: {formatNum(kpis?.matched_pairs_count, 0)}</span>
          </div>

          <div className="matched-grid">
            <div className="matched-chart-wrap">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={data?.temporal_differences.distribution ?? []}
                  margin={{ top: 10, right: 15, left: -15, bottom: 0 }}
                >
                  <CartesianGrid vertical={false} stroke="#2c3328" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="bracket"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#a0a596", fontSize: 10 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => compactNum(v)}
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
                    formatter={(val) => [formatNum(Number(val), 0), "Coincident Hotspots"]}
                  />
                  <Bar dataKey="count" fill="#80a66f" radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="matched-stats-card">
              <div className="matched-stat-row">
                <span>Total Coincident Matches:</span>
                <strong>{formatNum(kpis?.matched_pairs_count, 0)} pairs</strong>
              </div>
              <div className="matched-stat-row">
                <span>Mean Observation Offset (Δt):</span>
                <strong>{formatNum(kpis?.mean_time_difference_minutes)} minutes</strong>
              </div>
              <div className="matched-stat-row">
                <span>Median Observation Offset:</span>
                <strong>{formatNum(kpis?.median_time_difference_minutes)} minutes</strong>
              </div>
              <div className="matched-stat-row">
                <span>Mean Inter-Centroid Distance:</span>
                <strong>{formatNum(kpis?.mean_spatial_distance_meters, 0)} meters</strong>
              </div>
              <div className="matched-stat-note">
                Coincidence matching identifies fire hotspots observed on the same date within ±{filters.temporalWindowMinutes} min and {filters.spatialThresholdMeters} m.
              </div>
            </div>
          </div>
        </article>
      </section>

      {/* 10. Platform Technical Specifications Matrix */}
      <section className="comparison-specs-panel">
        <div className="panel-header">
          <div>
            <div className="panel-title-row">
              <span className="panel-bullet blue" />
              <h3>Satellite &amp; Sensor Specifications Reference Matrix</h3>
              <span className="source-pill">NASA &amp; NOAA FLIGHT SPECIFICATIONS</span>
            </div>
            <p className="panel-desc">
              Authoritative orbital, spatial, and radiometer parameters governing active fire detection limits.
            </p>
          </div>
        </div>

        <div className="specs-table-wrap">
          <table className="specs-matrix-table">
            <thead>
              <tr>
                <th>SPECIFICATION ATTRIBUTE</th>
                <th className="th-a">{nameA}</th>
                <th className="th-b">{nameB}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Primary Radiometer Instrument</td>
                <td><strong>{data?.platform_a.specs.instrument ?? "MODIS"}</strong></td>
                <td><strong>{data?.platform_b.specs.instrument ?? "VIIRS"}</strong></td>
              </tr>
              <tr>
                <td>Sponsoring Space Agency / Operator</td>
                <td>{data?.platform_a.specs.operator ?? "NASA (EOS)"}</td>
                <td>{data?.platform_b.specs.operator ?? "NOAA / NASA"}</td>
              </tr>
              <tr>
                <td>Nadir Spatial Resolution (Pixel Size)</td>
                <td><span className="res-badge res-modis">{data?.platform_a.specs.spatial_resolution ?? "1000 m"}</span></td>
                <td><span className="res-badge res-viirs">{data?.platform_b.specs.spatial_resolution ?? "375 m"}</span></td>
              </tr>
              <tr>
                <td>Equator Crossing Local Solar Time (LST)</td>
                <td>{data?.platform_a.specs.equator_crossing_time ?? "10:30 AM / 22:30 PM"}</td>
                <td>{data?.platform_b.specs.equator_crossing_time ?? "13:30 PM / 01:30 AM"}</td>
              </tr>
              <tr>
                <td>Nominal Orbital Altitude</td>
                <td>{data?.platform_a.specs.altitude_km ?? 705} km</td>
                <td>{data?.platform_b.specs.altitude_km ?? 824} km</td>
              </tr>
              <tr>
                <td>Imaging Swath Width</td>
                <td>{data?.platform_a.specs.swath_width_km ?? 2330} km</td>
                <td>{data?.platform_b.specs.swath_width_km ?? 3040} km</td>
              </tr>
              <tr>
                <td>Primary Fire Detection Channels</td>
                <td>{data?.platform_a.specs.spectral_bands ?? "Band 21/22 (3.96 µm) & Band 31 (11.03 µm)"}</td>
                <td>{data?.platform_b.specs.spectral_bands ?? "I4 (3.74 µm) & I5 (11.45 µm)"}</td>
              </tr>
              <tr>
                <td>Radiometer Saturation Temperature</td>
                <td>{data?.platform_a.specs.saturation_temp ?? "~500 K (B21 high gain)"}</td>
                <td>{data?.platform_b.specs.saturation_temp ?? "~367 K (I4 dual gain)"}</td>
              </tr>
              <tr>
                <td>Operational Characteristics</td>
                <td><small>{data?.platform_a.specs.characteristics}</small></td>
                <td><small>{data?.platform_b.specs.characteristics}</small></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* 11. Footer Status & Database Attribution */}
      <footer className="comparison-footer">
        <div className="footer-left">
          <span className="source-dot live" />
          <span>Connected to TwinFlame DuckDB Engine</span>
          <span className="dot">·</span>
          <span>Sources: <code>{data?.sources.detection_metrics}</code>, <code>{data?.sources.daily_trends}</code>, <code>{data?.sources.frp_comparisons}</code></span>
        </div>
        <div className="footer-right">
          <span>NASA FIRMS Active Fire Mission Support</span>
          <span className="dot">·</span>
          <span>TwinFlame Intelligence Suite</span>
        </div>
      </footer>
    </div>
  );
}
