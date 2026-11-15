import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Clock,
  Compass,
  Download,
  Filter,
  Flame,
  Info,
  Layers,
  Link2,
  Percent,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  XCircle,
  Zap,
} from "lucide-react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";

export type HarmPlatformPair =
  | "all"
  | "terra_noaa20"
  | "terra_noaa21"
  | "aqua_noaa20"
  | "aqua_noaa21"
  | "terra_aqua"
  | "noaa20_noaa21";

export type HarmDecisionClass =
  | "all"
  | "strong"
  | "possible"
  | "rejected"
  | "insufficient_geometry";

export type HarmGeometryQuality =
  | "all"
  | "high"
  | "nominal"
  | "degraded"
  | "insufficient";

export type DatePreset = "all" | "1y" | "90d" | "30d" | "7d" | "custom";

type Filters = {
  preset: DatePreset;
  startDate: string;
  endDate: string;
  platformPair: HarmPlatformPair;
  decisionClass: HarmDecisionClass;
  geometryQuality: HarmGeometryQuality;
  minTimeDiff: string;
  maxTimeDiff: string;
  minDistance: string;
  maxDistance: string;
  minIou: string;
  maxIou: string;
  minContainment: string;
  maxContainment: string;
  runId: string;
  algorithmVersion: string;
};

type DetectionDetails = {
  id: string;
  platform: string;
  instrument: string;
  acq_date: string;
  acq_time: string;
  latitude: number;
  longitude: number;
  frp_mw: number | null;
  confidence: string;
  daynight: string;
};

type InspectionCandidate = {
  edge_id: string;
  decision_class: string;
  decision_reason: string;
  geometry_quality: string;
  distance_km: number;
  time_difference_minutes: number;
  iou: number;
  containment: number;
  platform_pair: string;
  detection_a: DetectionDetails;
  detection_b: DetectionDetails;
};

type HarmonizationResponse = {
  generated_at: string;
  summary_kpis: {
    total_candidates: number;
    strong_count: number;
    possible_count: number;
    rejected_count: number;
    insufficient_geometry_count: number;
    acceptance_rate_pct: number;
    strong_rate_pct: number;
    rejection_rate_pct: number;
    mean_distance_km: number;
    median_distance_km: number;
    mean_time_diff_minutes: number;
    median_time_diff_minutes: number;
    mean_iou: number;
    mean_containment: number;
  };
  decision_distribution: Array<{
    decision: string;
    label: string;
    count: number;
    percentage: number;
    color: string;
  }>;
  correspondence_trend: Array<{
    date: string;
    strong: number;
    possible: number;
    rejected: number;
    total: number;
    acceptance_rate: number;
  }>;
  spatial_distance_distribution: Array<{
    bracket: string;
    count: number;
    percentage: number;
  }>;
  temporal_difference_distribution: Array<{
    bracket: string;
    count: number;
    percentage: number;
  }>;
  iou_distribution: Array<{
    bracket: string;
    count: number;
    percentage: number;
  }>;
  platform_pair_quality: Array<{
    pair: string;
    pair_name: string;
    strong: number;
    possible: number;
    rejected: number;
    total: number;
    strong_pct: number;
    acceptance_pct: number;
  }>;
  cluster_composition: {
    total_clusters: number;
    cross_sensor_clusters: number;
    modis_only_clusters: number;
    viirs_only_clusters: number;
    cross_sensor_pct: number;
    avg_cluster_size: number;
    avg_platforms_per_cluster: number;
  };
  inspection_candidates: InspectionCandidate[];
  available_runs: string[];
  available_versions: string[];
  sources: Record<string, string>;
};

// Map controller to synchronize views when selected edge changes
function MapController({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom, { animate: true });
  }, [center, zoom, map]);
  return null;
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

export default function HarmonizationEvaluationPage() {
  const [filters, setFilters] = useState<Filters>({
    preset: "all",
    startDate: "",
    endDate: "",
    platformPair: "all",
    decisionClass: "all",
    geometryQuality: "all",
    minTimeDiff: "",
    maxTimeDiff: "",
    minDistance: "",
    maxDistance: "",
    minIou: "",
    maxIou: "",
    minContainment: "",
    maxContainment: "",
    runId: "",
    algorithmVersion: "",
  });

  const [data, setData] = useState<HarmonizationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState<boolean>(false);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [edgeSearchQuery, setEdgeSearchQuery] = useState<string>("");
  const [edgeTabFilter, setEdgeTabFilter] = useState<"ALL" | "STRONG" | "POSSIBLE" | "REJECTED" | "INSUFFICIENT">("ALL");

  // Fetch API
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    const params = new URLSearchParams();
    if (filters.startDate) params.set("start_date", filters.startDate);
    if (filters.endDate) params.set("end_date", filters.endDate);
    if (filters.platformPair !== "all") params.set("platform_pair", filters.platformPair);
    if (filters.decisionClass !== "all") params.set("decision_class", filters.decisionClass);
    if (filters.geometryQuality !== "all") params.set("geometry_quality", filters.geometryQuality);
    if (filters.minTimeDiff) params.set("min_time_diff_minutes", filters.minTimeDiff);
    if (filters.maxTimeDiff) params.set("max_time_diff_minutes", filters.maxTimeDiff);
    if (filters.minDistance) params.set("min_distance_km", filters.minDistance);
    if (filters.maxDistance) params.set("max_distance_km", filters.maxDistance);
    if (filters.minIou) params.set("min_iou", filters.minIou);
    if (filters.maxIou) params.set("max_iou", filters.maxIou);
    if (filters.minContainment) params.set("min_containment", filters.minContainment);
    if (filters.maxContainment) params.set("max_containment", filters.maxContainment);
    if (filters.runId) params.set("run_id", filters.runId);
    if (filters.algorithmVersion) params.set("algorithm_version", filters.algorithmVersion);

    fetch(`/api/harmonization-evaluation?${params.toString()}`, { credentials: "omit", signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `Server responded with status ${res.status}`);
        }
        return res.json();
      })
      .then((json: HarmonizationResponse) => {
        setData(json);
        // Default select the first candidate if available
        if (json.inspection_candidates && json.inspection_candidates.length > 0) {
          setSelectedEdgeId((prev) => {
            const exists = json.inspection_candidates.some((e) => e.edge_id === prev);
            return exists ? prev : json.inspection_candidates[0].edge_id;
          });
        } else {
          setSelectedEdgeId(null);
        }
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(err.message || "Failed to load harmonization evaluation data.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [filters, refreshKey]);

  // Handle Preset Changes
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

  const handleResetFilters = () => {
    setFilters({
      preset: "all",
      startDate: "",
      endDate: "",
      platformPair: "all",
      decisionClass: "all",
      geometryQuality: "all",
      minTimeDiff: "",
      maxTimeDiff: "",
      minDistance: "",
      maxDistance: "",
      minIou: "",
      maxIou: "",
      minContainment: "",
      maxContainment: "",
      runId: "",
      algorithmVersion: "",
    });
    setEdgeSearchQuery("");
    setEdgeTabFilter("ALL");
  };

  // Filtered inspection candidates
  const filteredCandidates = useMemo(() => {
    if (!data?.inspection_candidates) return [];
    return data.inspection_candidates.filter((cand) => {
      // Tab filter
      if (edgeTabFilter === "STRONG" && cand.decision_class !== "STRONG") return false;
      if (edgeTabFilter === "POSSIBLE" && cand.decision_class !== "POSSIBLE") return false;
      if (edgeTabFilter === "REJECTED" && cand.decision_class !== "REJECTED") return false;
      if (edgeTabFilter === "INSUFFICIENT" && !cand.decision_class.includes("INSUFFICIENT")) return false;

      // Text query
      if (!edgeSearchQuery.trim()) return true;
      const q = edgeSearchQuery.toLowerCase();
      return (
        cand.edge_id.toLowerCase().includes(q) ||
        cand.detection_a.id.toLowerCase().includes(q) ||
        cand.detection_b.id.toLowerCase().includes(q) ||
        cand.platform_pair.toLowerCase().includes(q) ||
        cand.decision_reason.toLowerCase().includes(q)
      );
    });
  }, [data?.inspection_candidates, edgeTabFilter, edgeSearchQuery]);

  // Selected Candidate
  const selectedCandidate = useMemo(() => {
    if (!data?.inspection_candidates || !selectedEdgeId) return null;
    return data.inspection_candidates.find((cand) => cand.edge_id === selectedEdgeId) || data.inspection_candidates[0] || null;
  }, [data?.inspection_candidates, selectedEdgeId]);

  // Map center between Detection A and Detection B
  const mapCenter: [number, number] = useMemo(() => {
    if (!selectedCandidate) return [20, 0];
    const latA = selectedCandidate.detection_a.latitude;
    const lonA = selectedCandidate.detection_a.longitude;
    const latB = selectedCandidate.detection_b.latitude;
    const lonB = selectedCandidate.detection_b.longitude;
    if (latA === 0 && lonA === 0 && latB === 0 && lonB === 0) return [20, 0];
    return [(latA + latB) / 2, (lonA + lonB) / 2];
  }, [selectedCandidate]);

  // Export correspondence dataset to CSV
  const handleExportCSV = () => {
    if (!data?.inspection_candidates || data.inspection_candidates.length === 0) return;
    const headers = [
      "edge_id",
      "decision_class",
      "platform_pair",
      "distance_km",
      "time_diff_minutes",
      "iou",
      "containment",
      "geometry_quality",
      "decision_reason",
      "detection_a_id",
      "detection_a_platform",
      "detection_a_date",
      "detection_a_lat",
      "detection_a_lon",
      "detection_a_frp",
      "detection_b_id",
      "detection_b_platform",
      "detection_b_date",
      "detection_b_lat",
      "detection_b_lon",
      "detection_b_frp",
    ];

    const rows = data.inspection_candidates.map((c) => [
      `"${c.edge_id}"`,
      `"${c.decision_class}"`,
      `"${c.platform_pair}"`,
      c.distance_km,
      c.time_difference_minutes,
      c.iou,
      c.containment,
      `"${c.geometry_quality}"`,
      `"${c.decision_reason.replace(/"/g, '""')}"`,
      `"${c.detection_a.id}"`,
      `"${c.detection_a.platform}"`,
      `"${c.detection_a.acq_date}"`,
      c.detection_a.latitude,
      c.detection_a.longitude,
      c.detection_a.frp_mw ?? "",
      `"${c.detection_b.id}"`,
      `"${c.detection_b.platform}"`,
      `"${c.detection_b.acq_date}"`,
      c.detection_b.latitude,
      c.detection_b.longitude,
      c.detection_b.frp_mw ?? "",
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `twinflame_correspondences_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const kpis = data?.summary_kpis;

  return (
    <div className="historical-page-container harmonization-page-container">
      {/* 1. Top Header */}
      <header className="historical-header">
        <div className="historical-header-main">
          <div className="historical-badge">
            <Link2 size={13} />
            <span>NASA SPACE APPS CHALLENGE 2026 · ALGORITHM EVALUATION & VALIDATION</span>
          </div>
          <h1>Harmonization Evaluation</h1>
          <p className="historical-subtitle">
            Rigorous evaluation of cross-sensor correspondence matching between MODIS (Terra/Aqua) and VIIRS (NOAA-20/21) active fire observations.
          </p>
        </div>
        <div className="historical-header-actions">
          <button
            type="button"
            className="historical-refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            title="Refresh Evaluation Data"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>{loading ? "Evaluating..." : "Refresh"}</span>
          </button>
          <button
            type="button"
            className="historical-download-btn"
            onClick={handleExportCSV}
            disabled={!data || data.inspection_candidates.length === 0}
            title="Export candidate correspondences as CSV"
          >
            <Download size={14} />
            <span>Export CSV</span>
          </button>
        </div>
      </header>

      {/* 2. Scientific Methodology Banner */}
      <section className="harmonization-methodology-banner" aria-label="Harmonization Methodology">
        <div className="methodology-icon">
          <Zap size={22} />
        </div>
        <div className="methodology-content">
          <h4>Explainable Cross-Sensor Correspondence Pipeline</h4>
          <p>
            TwinFlame pairs active fire detections from morning/afternoon MODIS and VIIRS satellite overpasses within adaptive spatio-temporal coincidence windows. Using orbital swath geometry, polygon overlap (IoU), and centroid containment, correspondence candidates are classified into <strong>Strong</strong> (IoU &ge; 0.20 or tight spatial coincidence), <strong>Possible</strong> (cluster boundary proximity), <strong>Rejected</strong> (threshold violations), or <strong>Insufficient Geometry</strong> (high scan-angle distortion &gt; 55&deg;).
          </p>
          <div className="methodology-tags">
            <span className="methodology-tag">
              <strong>Algorithm:</strong> {filters.algorithmVersion || "v2.5 (Harmonized IoU)"}
            </span>
            <span className="methodology-tag">
              <strong>Coincidence Window:</strong> &le; 120 min
            </span>
            <span className="methodology-tag">
              <strong>Spatial Threshold:</strong> &le; 3.0 km
            </span>
            <span className="methodology-tag">
              <strong>IoU Cutoff:</strong> 0.20
            </span>
          </div>
        </div>
      </section>

      {/* 3. Filter Bar */}
      <section className="historical-filter-bar harmonization-filter-bar" aria-label="Harmonization evaluation filters">
        {/* Row 1: Primary Controls */}
        <div className="filter-row-primary">
          {/* Preset Buttons */}
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
                  className={`preset-btn ${filters.preset === pKey ? "active" : ""}`}
                  onClick={() => handlePresetChange(pKey)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Custom Date Pickers */}
          {filters.preset === "custom" && (
            <div className="filter-group date-inputs-group">
              <div className="date-input-wrap">
                <span className="input-sublabel">FROM</span>
                <input
                  type="date"
                  value={filters.startDate}
                  onChange={(e) => setFilters((prev) => ({ ...prev, startDate: e.target.value }))}
                />
              </div>
              <div className="date-input-wrap">
                <span className="input-sublabel">TO</span>
                <input
                  type="date"
                  value={filters.endDate}
                  onChange={(e) => setFilters((prev) => ({ ...prev, endDate: e.target.value }))}
                />
              </div>
            </div>
          )}

          {/* Platform Pair Selector */}
          <div className="filter-group">
            <span className="filter-label">
              <Layers size={13} /> PLATFORM PAIR
            </span>
            <div className="select-wrapper">
              <select
                value={filters.platformPair}
                onChange={(e) => setFilters((prev) => ({ ...prev, platformPair: e.target.value as HarmPlatformPair }))}
              >
                <option value="all">All Platform Pairs</option>
                <option value="terra_noaa20">Terra – NOAA-20</option>
                <option value="terra_noaa21">Terra – NOAA-21</option>
                <option value="aqua_noaa20">Aqua – NOAA-20</option>
                <option value="aqua_noaa21">Aqua – NOAA-21</option>
                <option value="terra_aqua">Terra – Aqua</option>
                <option value="noaa20_noaa21">NOAA-20 – NOAA-21</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Decision Class Selector */}
          <div className="filter-group">
            <span className="filter-label">
              <CheckCircle2 size={13} /> DECISION CLASS
            </span>
            <div className="select-wrapper">
              <select
                value={filters.decisionClass}
                onChange={(e) => setFilters((prev) => ({ ...prev, decisionClass: e.target.value as HarmDecisionClass }))}
              >
                <option value="all">All Decisions</option>
                <option value="strong">Strong Correspondence</option>
                <option value="possible">Possible Correspondence</option>
                <option value="rejected">Rejected</option>
                <option value="insufficient_geometry">Insufficient Geometry</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Geometry Quality Selector */}
          <div className="filter-group">
            <span className="filter-label">
              <Compass size={13} /> GEOMETRY QUALITY
            </span>
            <div className="select-wrapper">
              <select
                value={filters.geometryQuality}
                onChange={(e) => setFilters((prev) => ({ ...prev, geometryQuality: e.target.value as HarmGeometryQuality }))}
              >
                <option value="all">All Qualities</option>
                <option value="high">High (&lt; 30&deg; scan angle)</option>
                <option value="nominal">Nominal (30&deg; - 45&deg;)</option>
                <option value="degraded">Degraded (45&deg; - 55&deg;)</option>
                <option value="insufficient">Insufficient (&gt; 55&deg;)</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Toggle Advanced Filters Button */}
          <div className="filter-group filter-actions-group">
            <button
              type="button"
              className={`advanced-toggle-btn ${showAdvancedFilters ? "active" : ""}`}
              onClick={() => setShowAdvancedFilters((v) => !v)}
              title="Toggle Advanced Numerical Thresholds"
            >
              <Filter size={13} />
              <span>{showAdvancedFilters ? "Hide Thresholds" : "Thresholds & Runs"}</span>
            </button>
            <button
              type="button"
              className="reset-filters-btn"
              onClick={handleResetFilters}
              title="Reset all filters to defaults"
            >
              <RotateCcw size={13} />
              <span>Reset</span>
            </button>
          </div>
        </div>

        {/* Row 2: Advanced Thresholds & Run Selector (Collapsible) */}
        {showAdvancedFilters && (
          <div className="filter-row-advanced">
            {/* Time Difference Range */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <Clock size={12} /> TIME DIFF (MIN)
              </span>
              <div className="threshold-inputs">
                <input
                  type="number"
                  min="0"
                  step="5"
                  placeholder="Min min"
                  value={filters.minTimeDiff}
                  onChange={(e) => setFilters((prev) => ({ ...prev, minTimeDiff: e.target.value }))}
                />
                <span className="threshold-sep">—</span>
                <input
                  type="number"
                  min="0"
                  step="5"
                  placeholder="Max min"
                  value={filters.maxTimeDiff}
                  onChange={(e) => setFilters((prev) => ({ ...prev, maxTimeDiff: e.target.value }))}
                />
              </div>
            </div>

            {/* Centre Distance Range */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <SlidersHorizontal size={12} /> DISTANCE (KM)
              </span>
              <div className="threshold-inputs">
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  placeholder="Min km"
                  value={filters.minDistance}
                  onChange={(e) => setFilters((prev) => ({ ...prev, minDistance: e.target.value }))}
                />
                <span className="threshold-sep">—</span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  placeholder="Max km"
                  value={filters.maxDistance}
                  onChange={(e) => setFilters((prev) => ({ ...prev, maxDistance: e.target.value }))}
                />
              </div>
            </div>

            {/* IoU Range */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <Percent size={12} /> IoU RANGE (0 - 1)
              </span>
              <div className="threshold-inputs">
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="Min IoU"
                  value={filters.minIou}
                  onChange={(e) => setFilters((prev) => ({ ...prev, minIou: e.target.value }))}
                />
                <span className="threshold-sep">—</span>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="Max IoU"
                  value={filters.maxIou}
                  onChange={(e) => setFilters((prev) => ({ ...prev, maxIou: e.target.value }))}
                />
              </div>
            </div>

            {/* Containment Range */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <Layers size={12} /> CONTAINMENT (0 - 1)
              </span>
              <div className="threshold-inputs">
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="Min cont"
                  value={filters.minContainment}
                  onChange={(e) => setFilters((prev) => ({ ...prev, minContainment: e.target.value }))}
                />
                <span className="threshold-sep">—</span>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  placeholder="Max cont"
                  value={filters.maxContainment}
                  onChange={(e) => setFilters((prev) => ({ ...prev, maxContainment: e.target.value }))}
                />
              </div>
            </div>

            {/* Run ID */}
            {data?.available_runs && data.available_runs.length > 0 && (
              <div className="threshold-input-box">
                <span className="threshold-title">
                  <Activity size={12} /> HARMONIZATION RUN
                </span>
                <div className="select-wrapper">
                  <select
                    value={filters.runId}
                    onChange={(e) => setFilters((prev) => ({ ...prev, runId: e.target.value }))}
                  >
                    <option value="">All Runs</option>
                    {data.available_runs.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={14} className="select-arrow" />
                </div>
              </div>
            )}

            {/* Algorithm Version */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <Info size={12} /> ALGORITHM VERSION
              </span>
              <div className="select-wrapper">
                <select
                  value={filters.algorithmVersion}
                  onChange={(e) => setFilters((prev) => ({ ...prev, algorithmVersion: e.target.value }))}
                >
                  <option value="">v2.5 (Current Harmonized IoU)</option>
                  <option value="v2.4">v2.4 (Geometric Boundary Overlap)</option>
                  <option value="v2.1">v2.1 (Centroid-only Euclidean)</option>
                </select>
                <ChevronDown size={14} className="select-arrow" />
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Error state */}
      {error && (
        <section className="historical-error-banner" role="alert">
          <AlertCircle size={20} />
          <div>
            <strong>Harmonization Evaluation Service Notice</strong>
            <p>{error}</p>
          </div>
        </section>
      )}

      {/* 4. Hero KPI Metric Cards */}
      <section className="historical-kpi-grid harmonization-kpi-grid">
        {/* Total Candidates */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">TOTAL CANDIDATE PAIRS</span>
            <span className="kpi-icon-wrap" style={{ color: "#a0a596" }}>
              <Link2 size={16} />
            </span>
          </div>
          <div className="kpi-value">{loading ? "..." : (kpis?.total_candidates ?? 0).toLocaleString()}</div>
          <div className="kpi-subtitle">Orbital coincident fire detections evaluated</div>
        </div>

        {/* Strong Correspondences */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">STRONG CORRESPONDENCES</span>
            <span className="kpi-icon-wrap" style={{ color: "#80a66f" }}>
              <CheckCircle2 size={16} />
            </span>
          </div>
          <div className="kpi-value" style={{ color: "#80a66f" }}>
            {loading ? "..." : (kpis?.strong_count ?? 0).toLocaleString()}
          </div>
          <div className="kpi-subtitle">
            <span className="kpi-badge strong-badge">{kpis?.strong_rate_pct ?? 0}%</span> high-confidence matches
          </div>
        </div>

        {/* Possible Correspondences */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">POSSIBLE CORRESPONDENCES</span>
            <span className="kpi-icon-wrap" style={{ color: "#f58200" }}>
              <Flame size={16} />
            </span>
          </div>
          <div className="kpi-value" style={{ color: "#f58200" }}>
            {loading ? "..." : (kpis?.possible_count ?? 0).toLocaleString()}
          </div>
          <div className="kpi-subtitle">
            <span className="kpi-badge possible-badge">
              {kpis && kpis.total_candidates > 0
                ? Math.round((kpis.possible_count / kpis.total_candidates) * 1000) / 10
                : 0}%
            </span>{" "}
            cluster proximity matches
          </div>
        </div>

        {/* Rejected Correspondences */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">REJECTED CANDIDATES</span>
            <span className="kpi-icon-wrap" style={{ color: "#d92d1f" }}>
              <XCircle size={16} />
            </span>
          </div>
          <div className="kpi-value" style={{ color: "#d92d1f" }}>
            {loading ? "..." : (kpis?.rejected_count ?? 0).toLocaleString()}
          </div>
          <div className="kpi-subtitle">
            <span className="kpi-badge rejected-badge">{kpis?.rejection_rate_pct ?? 0}%</span> exceeded thresholds
          </div>
        </div>

        {/* Insufficient Geometry */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">INSUFFICIENT GEOMETRY</span>
            <span className="kpi-icon-wrap" style={{ color: "#8d321d" }}>
              <Compass size={16} />
            </span>
          </div>
          <div className="kpi-value" style={{ color: "#e9b77e" }}>
            {loading ? "..." : (kpis?.insufficient_geometry_count ?? 0).toLocaleString()}
          </div>
          <div className="kpi-subtitle">Extreme scan distortion (&gt; 55&deg;)</div>
        </div>

        {/* Acceptance Rate & Means */}
        <div className="historical-kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">ACCEPTANCE RATE</span>
            <span className="kpi-icon-wrap" style={{ color: "#80a66f" }}>
              <Percent size={16} />
            </span>
          </div>
          <div className="kpi-value" style={{ color: "#80a66f" }}>
            {loading ? "..." : `${kpis?.acceptance_rate_pct ?? 0}%`}
          </div>
          <div className="kpi-subtitle">
            &mu;<sub>IoU</sub>: {kpis?.mean_iou ?? 0.0} &middot; &mu;<sub>d</sub>: {kpis?.mean_distance_km ?? 0.0} km
          </div>
        </div>
      </section>

      {/* 5. Visualizations Section */}
      <section className="harmonization-visualizations-section">
        {/* Viz Grid Row 1: Decision Distribution & Trend Over Time */}
        <div className="historical-charts-grid">
          {/* Viz 1: Decision Distribution (Donut & Breakdown) */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Correspondence Decision Distribution</h3>
                <p className="chart-card-subtitle">
                  Class breakdown across strong, possible, rejected, and insufficient geometry
                </p>
              </div>
              <span className="chart-source-badge">harm_correspondence_summary</span>
            </div>
            <div className="decision-dist-container">
              <div className="decision-pie-wrap">
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={data?.decision_distribution || []}
                      dataKey="count"
                      nameKey="label"
                      innerRadius={65}
                      outerRadius={95}
                      paddingAngle={3}
                      stroke="#151813"
                      strokeWidth={2}
                    >
                      {(data?.decision_distribution || []).map((entry, idx) => (
                        <Cell key={`cell-${idx}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1b2019",
                        border: "1px solid #30362c",
                        borderRadius: "6px",
                        color: "#e8ebe4",
                      }}
                      formatter={(val: any, name: any) => [`${Number(val).toLocaleString()} edges`, name]}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="donut-center-stat">
                  <div className="donut-center-val">{kpis?.acceptance_rate_pct ?? 0}%</div>
                  <div className="donut-center-lbl">Accepted</div>
                </div>
              </div>
              <div className="decision-legend-list">
                {(data?.decision_distribution || []).map((item) => (
                  <div key={item.decision} className="decision-legend-row">
                    <span className="legend-indicator" style={{ backgroundColor: item.color }} />
                    <div className="legend-info">
                      <span className="legend-name">{item.label}</span>
                      <span className="legend-stats">
                        {item.count.toLocaleString()} pairs ({item.percentage}%)
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Viz 2: Correspondence Trend Over Time */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Correspondence Trend Over Time</h3>
                <p className="chart-card-subtitle">
                  Daily Strong, Possible, and Rejected matches with Harmonization Acceptance Rate (%)
                </p>
              </div>
              <span className="chart-source-badge">harm_correspondence_summary</span>
            </div>
            <div className="chart-render-wrap">
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart
                  data={data?.correspondence_trend || []}
                  margin={{ top: 15, right: 25, left: 0, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#252b22" vertical={false} />
                  <XAxis dataKey="date" stroke="#687063" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="left" stroke="#687063" tick={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    stroke="#80a66f"
                    domain={[0, 100]}
                    unit="%"
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      border: "1px solid #30362c",
                      borderRadius: "6px",
                      color: "#e8ebe4",
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="strong"
                    name="Strong"
                    stackId="1"
                    stroke="#80a66f"
                    fill="#80a66f"
                    fillOpacity={0.7}
                  />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="possible"
                    name="Possible"
                    stackId="1"
                    stroke="#f58200"
                    fill="#f58200"
                    fillOpacity={0.6}
                  />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="rejected"
                    name="Rejected"
                    stackId="1"
                    stroke="#d92d1f"
                    fill="#d92d1f"
                    fillOpacity={0.5}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="acceptance_rate"
                    name="Acceptance Rate (%)"
                    stroke="#48c774"
                    strokeWidth={2.5}
                    dot={{ r: 2 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Viz Grid Row 2: Spatial, Temporal & IoU Distributions (3 columns) */}
        <div className="harmonization-trio-grid">
          {/* Viz 3: Spatial Distance Distribution */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Spatial Distance Distribution</h3>
                <p className="chart-card-subtitle">Centroid distance between paired observations (km)</p>
              </div>
            </div>
            <div className="chart-render-wrap">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={data?.spatial_distance_distribution || []}
                  margin={{ top: 10, right: 10, left: -15, bottom: 25 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#252b22" vertical={false} />
                  <XAxis
                    dataKey="bracket"
                    stroke="#687063"
                    tick={{ fontSize: 10 }}
                    angle={-20}
                    textAnchor="end"
                  />
                  <YAxis stroke="#687063" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      border: "1px solid #30362c",
                      borderRadius: "6px",
                      color: "#e8ebe4",
                    }}
                    formatter={(val: any) => [`${val} pairs`, "Count"]}
                  />
                  <Bar dataKey="count" fill="#80a66f" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dist-summary-note">
              <span>&mu; Distance: <strong>{kpis?.mean_distance_km ?? 0} km</strong></span>
              <span>Median: <strong>{kpis?.median_distance_km ?? 0} km</strong></span>
            </div>
          </div>

          {/* Viz 4: Temporal Difference Distribution */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Temporal Difference Distribution</h3>
                <p className="chart-card-subtitle">Overpass time difference (&Delta;t min) between sensors</p>
              </div>
            </div>
            <div className="chart-render-wrap">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={data?.temporal_difference_distribution || []}
                  margin={{ top: 10, right: 10, left: -15, bottom: 25 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#252b22" vertical={false} />
                  <XAxis
                    dataKey="bracket"
                    stroke="#687063"
                    tick={{ fontSize: 10 }}
                    angle={-20}
                    textAnchor="end"
                  />
                  <YAxis stroke="#687063" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      border: "1px solid #30362c",
                      borderRadius: "6px",
                      color: "#e8ebe4",
                    }}
                    formatter={(val: any) => [`${val} pairs`, "Count"]}
                  />
                  <Bar dataKey="count" fill="#f58200" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dist-summary-note">
              <span>&mu; &Delta;t: <strong>{kpis?.mean_time_diff_minutes ?? 0} min</strong></span>
              <span>Median: <strong>{kpis?.median_time_diff_minutes ?? 0} min</strong></span>
            </div>
          </div>

          {/* Viz 5: IoU Distribution */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Intersection over Union (IoU)</h3>
                <p className="chart-card-subtitle">Active fire bounding box overlap index</p>
              </div>
            </div>
            <div className="chart-render-wrap">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={data?.iou_distribution || []}
                  margin={{ top: 10, right: 10, left: -15, bottom: 25 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#252b22" vertical={false} />
                  <XAxis
                    dataKey="bracket"
                    stroke="#687063"
                    tick={{ fontSize: 10 }}
                    angle={-20}
                    textAnchor="end"
                  />
                  <YAxis stroke="#687063" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      border: "1px solid #30362c",
                      borderRadius: "6px",
                      color: "#e8ebe4",
                    }}
                    formatter={(val: any) => [`${val} pairs`, "Count"]}
                  />
                  <Bar dataKey="count" fill="#e9b77e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dist-summary-note">
              <span>&mu; IoU: <strong>{kpis?.mean_iou ?? 0}</strong></span>
              <span>&mu; Containment: <strong>{kpis?.mean_containment ?? 0}</strong></span>
            </div>
          </div>
        </div>

        {/* Viz Grid Row 3: Platform Pair Quality & Cluster Membership Composition */}
        <div className="historical-charts-grid">
          {/* Viz 6: Correspondence Quality by Platform Pair */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Correspondence Quality by Platform Pair</h3>
                <p className="chart-card-subtitle">
                  Strong, Possible, and Rejected candidate correspondence breakdown across platform pairs
                </p>
              </div>
              <span className="chart-source-badge">harm_correspondence_edges</span>
            </div>
            <div className="chart-render-wrap">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={data?.platform_pair_quality || []}
                  layout="vertical"
                  margin={{ top: 10, right: 25, left: 45, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#252b22" horizontal={false} />
                  <XAxis type="number" stroke="#687063" tick={{ fontSize: 11 }} />
                  <YAxis
                    dataKey="pair_name"
                    type="category"
                    stroke="#687063"
                    tick={{ fontSize: 11 }}
                    width={110}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1b2019",
                      border: "1px solid #30362c",
                      borderRadius: "6px",
                      color: "#e8ebe4",
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                  <Bar dataKey="strong" name="Strong" stackId="pair" fill="#80a66f" />
                  <Bar dataKey="possible" name="Possible" stackId="pair" fill="#f58200" />
                  <Bar dataKey="rejected" name="Rejected" stackId="pair" fill="#d92d1f" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Viz 7: Cluster Membership Composition */}
          <div className="historical-chart-card">
            <div className="chart-card-header">
              <div>
                <h3>Cluster Membership Composition</h3>
                <p className="chart-card-subtitle">
                  Multi-sensor cluster synergy across harm_activity_clusters &amp; harm_cluster_members
                </p>
              </div>
              <span className="chart-source-badge">harm_cluster_members</span>
            </div>
            <div className="cluster-composition-panel">
              <div className="cluster-synergy-metric">
                <div className="synergy-val">
                  {data?.cluster_composition.cross_sensor_pct ?? 0}%
                </div>
                <div className="synergy-lbl">Cross-Sensor Clusters (MODIS + VIIRS)</div>
                <div className="synergy-progress">
                  <div
                    className="synergy-fill"
                    style={{ width: `${Math.min(100, data?.cluster_composition.cross_sensor_pct ?? 0)}%` }}
                  />
                </div>
              </div>

              <div className="cluster-stats-grid">
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">Total Activity Clusters</span>
                  <span className="cluster-stat-val">
                    {(data?.cluster_composition.total_clusters ?? 0).toLocaleString()}
                  </span>
                </div>
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">Cross-Sensor Harmonized</span>
                  <span className="cluster-stat-val" style={{ color: "#80a66f" }}>
                    {(data?.cluster_composition.cross_sensor_clusters ?? 0).toLocaleString()}
                  </span>
                </div>
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">MODIS-Only Clusters</span>
                  <span className="cluster-stat-val">
                    {(data?.cluster_composition.modis_only_clusters ?? 0).toLocaleString()}
                  </span>
                </div>
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">VIIRS-Only Clusters</span>
                  <span className="cluster-stat-val">
                    {(data?.cluster_composition.viirs_only_clusters ?? 0).toLocaleString()}
                  </span>
                </div>
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">Avg Detections / Cluster</span>
                  <span className="cluster-stat-val">
                    {data?.cluster_composition.avg_cluster_size ?? 0}
                  </span>
                </div>
                <div className="cluster-stat-item">
                  <span className="cluster-stat-lbl">Avg Platforms / Cluster</span>
                  <span className="cluster-stat-val">
                    {data?.cluster_composition.avg_platforms_per_cluster ?? 0}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Interactive Correspondence Inspection Tool */}
      <section className="harmonization-inspector-section" aria-label="Correspondence Inspection Tool">
        <div className="inspector-header">
          <div>
            <div className="inspector-badge">
              <Search size={13} />
              <span>EXPLAINABLE AI &amp; CORRESPONDENCE TRACEABILITY</span>
            </div>
            <h2>Correspondence Inspection Tool</h2>
            <p className="inspector-subtitle">
              Select any candidate edge to inspect Detection A, Detection B, physical geometry, IoU, and the automated decision rationale.
            </p>
          </div>
          <div className="inspector-filter-toolbar">
            <div className="inspector-search-box">
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Search edge or detection ID..."
                value={edgeSearchQuery}
                onChange={(e) => setEdgeSearchQuery(e.target.value)}
              />
              {edgeSearchQuery && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => setEdgeSearchQuery("")}
                  title="Clear search"
                >
                  &times;
                </button>
              )}
            </div>
            <div className="inspector-tabs">
              {(
                [
                  ["ALL", "All"],
                  ["STRONG", "Strong"],
                  ["POSSIBLE", "Possible"],
                  ["REJECTED", "Rejected"],
                  ["INSUFFICIENT", "Insufficient"],
                ] as const
              ).map(([tabKey, label]) => (
                <button
                  key={tabKey}
                  type="button"
                  className={`inspector-tab-btn ${edgeTabFilter === tabKey ? "active" : ""}`}
                  onClick={() => setEdgeTabFilter(tabKey)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Inspection Split Pane: Left Candidate List, Right Candidate Inspector */}
        <div className="inspector-layout">
          {/* Left Column: Candidates Table */}
          <div className="candidates-list-card">
            <div className="candidates-list-header">
              <span>CANDIDATE EDGES ({filteredCandidates.length})</span>
              <span className="candidates-sub">Sorted by correspondence strength</span>
            </div>
            <div className="candidates-scroll-pane">
              {filteredCandidates.length === 0 ? (
                <div className="candidates-empty-msg">
                  <Info size={18} />
                  <span>No candidate correspondence edges match the selected filters.</span>
                </div>
              ) : (
                filteredCandidates.map((cand) => {
                  const isSelected = cand.edge_id === selectedCandidate?.edge_id;
                  const isStrong = cand.decision_class === "STRONG";
                  const isPossible = cand.decision_class === "POSSIBLE";
                  const isRejected = cand.decision_class === "REJECTED";

                  return (
                    <div
                      key={cand.edge_id}
                      className={`candidate-item ${isSelected ? "selected" : ""}`}
                      onClick={() => setSelectedEdgeId(cand.edge_id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") setSelectedEdgeId(cand.edge_id);
                      }}
                    >
                      <div className="candidate-item-top">
                        <span className="candidate-id">{cand.edge_id}</span>
                        <span
                          className={`decision-badge ${
                            isStrong
                              ? "badge-strong"
                              : isPossible
                              ? "badge-possible"
                              : isRejected
                              ? "badge-rejected"
                              : "badge-insufficient"
                          }`}
                        >
                          {cand.decision_class}
                        </span>
                      </div>
                      <div className="candidate-item-mid">
                        <span className="cand-pair">{cand.platform_pair}</span>
                        <span className="cand-quality">{cand.geometry_quality} Quality</span>
                      </div>
                      <div className="candidate-item-bottom">
                        <span>d: <strong>{cand.distance_km} km</strong></span>
                        <span>&Delta;t: <strong>{cand.time_difference_minutes}m</strong></span>
                        <span>IoU: <strong>{cand.iou}</strong></span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Column: Selected Candidate Inspector */}
          <div className="candidate-detail-card">
            {selectedCandidate ? (
              <div className="detail-inspector-body">
                {/* Edge Header */}
                <div className="edge-detail-top">
                  <div>
                    <span className="edge-detail-label">INSPECTING CANDIDATE CORRESPONDENCE</span>
                    <h3 className="edge-detail-id">{selectedCandidate.edge_id}</h3>
                  </div>
                  <div className="edge-top-badges">
                    <span
                      className={`decision-badge large-badge ${
                        selectedCandidate.decision_class === "STRONG"
                          ? "badge-strong"
                          : selectedCandidate.decision_class === "POSSIBLE"
                          ? "badge-possible"
                          : selectedCandidate.decision_class === "REJECTED"
                          ? "badge-rejected"
                          : "badge-insufficient"
                      }`}
                    >
                      {selectedCandidate.decision_class}
                    </span>
                    <span className="pair-badge">{selectedCandidate.platform_pair}</span>
                    <span className="quality-badge">{selectedCandidate.geometry_quality} Quality</span>
                  </div>
                </div>

                {/* Explainable Decision Rationale Banner */}
                <div className="decision-reason-banner">
                  <div className="reason-icon">
                    <Info size={16} />
                  </div>
                  <div className="reason-content">
                    <strong>Decision Reason &amp; Classification Rule:</strong>
                    <p>{selectedCandidate.decision_reason}</p>
                  </div>
                </div>

                {/* Physical & Geometric Metrics Grid */}
                <div className="geometric-metrics-grid">
                  <div className="metric-box">
                    <span className="metric-box-lbl">TIME DIFFERENCE (&Delta;t)</span>
                    <span className="metric-box-val">{selectedCandidate.time_difference_minutes} min</span>
                    <span className="metric-box-sub">Orbital coincidence</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-box-lbl">CENTRE DISTANCE (d)</span>
                    <span className="metric-box-val">{selectedCandidate.distance_km} km</span>
                    <span className="metric-box-sub">Euclidean separation</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-box-lbl">INTERSECTION OVER UNION</span>
                    <span className="metric-box-val" style={{ color: "#80a66f" }}>
                      {selectedCandidate.iou}
                    </span>
                    <span className="metric-box-sub">Bounding box overlap</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-box-lbl">CONTAINMENT RATIO</span>
                    <span className="metric-box-val">{selectedCandidate.containment}</span>
                    <span className="metric-box-sub">Centroid in footprint</span>
                  </div>
                </div>

                {/* Side-by-Side Detections (Detection A vs Detection B) */}
                <div className="detections-side-by-side">
                  {/* Detection A */}
                  <div className="detection-spec-card sensor-a-card">
                    <div className="spec-card-head">
                      <div className="sensor-marker-dot marker-a" />
                      <div>
                        <strong>Detection A</strong>
                        <span className="sensor-spec-name">
                          {selectedCandidate.detection_a.platform} &middot; {selectedCandidate.detection_a.instrument}
                        </span>
                      </div>
                    </div>
                    <div className="spec-table">
                      <div className="spec-row">
                        <span>Detection ID</span>
                        <strong>{selectedCandidate.detection_a.id}</strong>
                      </div>
                      <div className="spec-row">
                        <span>Acq Date &amp; Time</span>
                        <strong>
                          {selectedCandidate.detection_a.acq_date || "—"} {selectedCandidate.detection_a.acq_time} UTC
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Coordinates</span>
                        <strong>
                          {selectedCandidate.detection_a.latitude.toFixed(4)}&deg;N,{" "}
                          {selectedCandidate.detection_a.longitude.toFixed(4)}&deg;E
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Fire Radiative Power</span>
                        <strong style={{ color: "#f58200" }}>
                          {selectedCandidate.detection_a.frp_mw !== null ? `${selectedCandidate.detection_a.frp_mw} MW` : "—"}
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Native Confidence</span>
                        <strong>{selectedCandidate.detection_a.confidence}</strong>
                      </div>
                      <div className="spec-row">
                        <span>Day / Night</span>
                        <strong>{selectedCandidate.detection_a.daynight === "D" ? "Day" : "Night"}</strong>
                      </div>
                    </div>
                  </div>

                  {/* Detection B */}
                  <div className="detection-spec-card sensor-b-card">
                    <div className="spec-card-head">
                      <div className="sensor-marker-dot marker-b" />
                      <div>
                        <strong>Detection B</strong>
                        <span className="sensor-spec-name">
                          {selectedCandidate.detection_b.platform} &middot; {selectedCandidate.detection_b.instrument}
                        </span>
                      </div>
                    </div>
                    <div className="spec-table">
                      <div className="spec-row">
                        <span>Detection ID</span>
                        <strong>{selectedCandidate.detection_b.id}</strong>
                      </div>
                      <div className="spec-row">
                        <span>Acq Date &amp; Time</span>
                        <strong>
                          {selectedCandidate.detection_b.acq_date || "—"} {selectedCandidate.detection_b.acq_time} UTC
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Coordinates</span>
                        <strong>
                          {selectedCandidate.detection_b.latitude.toFixed(4)}&deg;N,{" "}
                          {selectedCandidate.detection_b.longitude.toFixed(4)}&deg;E
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Fire Radiative Power</span>
                        <strong style={{ color: "#f58200" }}>
                          {selectedCandidate.detection_b.frp_mw !== null ? `${selectedCandidate.detection_b.frp_mw} MW` : "—"}
                        </strong>
                      </div>
                      <div className="spec-row">
                        <span>Native Confidence</span>
                        <strong>{selectedCandidate.detection_b.confidence}</strong>
                      </div>
                      <div className="spec-row">
                        <span>Day / Night</span>
                        <strong>{selectedCandidate.detection_b.daynight === "D" ? "Day" : "Night"}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Geospatial Mini-Map View */}
                <div className="inspection-map-frame">
                  <div className="map-frame-header">
                    <span className="map-frame-title">
                      <Compass size={13} /> GEOMETRIC OVERPASS RECONSTRUCTION
                    </span>
                    <span className="map-frame-info">
                      Separation: {selectedCandidate.distance_km} km &middot; Center: {mapCenter[0].toFixed(2)}&deg;, {mapCenter[1].toFixed(2)}&deg;
                    </span>
                  </div>
                  <div className="mini-map-container">
                    <MapContainer
                      center={mapCenter}
                      zoom={selectedCandidate.distance_km < 1.0 ? 14 : selectedCandidate.distance_km < 5.0 ? 12 : 9}
                      minZoom={2}
                      maxZoom={16}
                      scrollWheelZoom={false}
                      className="inspector-leaflet-map"
                    >
                      <MapController
                        center={mapCenter}
                        zoom={selectedCandidate.distance_km < 1.0 ? 14 : selectedCandidate.distance_km < 5.0 ? 12 : 9}
                      />
                      <TileLayer
                        attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                      />
                      {/* Detection A Marker */}
                      <CircleMarker
                        center={[selectedCandidate.detection_a.latitude, selectedCandidate.detection_a.longitude]}
                        radius={9}
                        pathOptions={{
                          color: "#1b2019",
                          weight: 2,
                          fillColor: "#f58200",
                          fillOpacity: 0.9,
                        }}
                      >
                        <Popup>
                          <div style={{ color: "#111", fontSize: "12px" }}>
                            <strong>Detection A ({selectedCandidate.detection_a.platform})</strong>
                            <br />
                            ID: {selectedCandidate.detection_a.id}
                            <br />
                            FRP: {selectedCandidate.detection_a.frp_mw ?? "—"} MW
                            <br />
                            Time: {selectedCandidate.detection_a.acq_time} UTC
                          </div>
                        </Popup>
                      </CircleMarker>

                      {/* Detection B Marker */}
                      <CircleMarker
                        center={[selectedCandidate.detection_b.latitude, selectedCandidate.detection_b.longitude]}
                        radius={9}
                        pathOptions={{
                          color: "#1b2019",
                          weight: 2,
                          fillColor: "#80a66f",
                          fillOpacity: 0.9,
                        }}
                      >
                        <Popup>
                          <div style={{ color: "#111", fontSize: "12px" }}>
                            <strong>Detection B ({selectedCandidate.detection_b.platform})</strong>
                            <br />
                            ID: {selectedCandidate.detection_b.id}
                            <br />
                            FRP: {selectedCandidate.detection_b.frp_mw ?? "—"} MW
                            <br />
                            Time: {selectedCandidate.detection_b.acq_time} UTC
                          </div>
                        </Popup>
                      </CircleMarker>

                      {/* Connecting Edge Polyline */}
                      <Polyline
                        positions={[
                          [selectedCandidate.detection_a.latitude, selectedCandidate.detection_a.longitude],
                          [selectedCandidate.detection_b.latitude, selectedCandidate.detection_b.longitude],
                        ]}
                        pathOptions={{
                          color:
                            selectedCandidate.decision_class === "STRONG"
                              ? "#80a66f"
                              : selectedCandidate.decision_class === "POSSIBLE"
                              ? "#f58200"
                              : "#d92d1f",
                          weight: 2.5,
                          dashArray: "4, 6",
                          opacity: 0.85,
                        }}
                      />
                    </MapContainer>
                  </div>
                </div>
              </div>
            ) : (
              <div className="no-selection-placeholder">
                <Link2 size={32} />
                <p>Select a candidate correspondence edge from the list to inspect its geometric parameters.</p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 7. Footer Status & Scientific Methodology Notes */}
      <footer className="historical-footer">
        <div className="historical-footer-notes">
          <p>
            <strong>Harmonization Algorithm Methodology:</strong> Candidate active fire pairs are evaluated across multi-sensor coincident orbits within a maximum 120-minute window and 3.0 km Euclidean radius. High scan-angle distortion (&gt; 55&deg;) degrades point-spread function geometry, triggering the <em>Insufficient Geometry</em> safeguard to prevent false cross-sensor matches.
          </p>
        </div>
        <div className="historical-footer-meta">
          <span>Sources: {data?.sources ? Object.entries(data.sources).map(([k, v]) => `${k}: ${v}`).join(" · ") : "harm_correspondence_edges"}</span>
          <span>Generated: {data?.generated_at ? new Date(data.generated_at).toUTCString() : "Live"}</span>
        </div>
      </footer>
    </div>
  );
}
