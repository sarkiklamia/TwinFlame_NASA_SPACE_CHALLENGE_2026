import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Award,
  BookOpen,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Database,
  Download,
  FileCheck,
  FileCode,
  FileSpreadsheet,
  FileText,
  Filter,
  Flame,
  Globe2,
  Layers,
  RefreshCw,
  RotateCcw,
  Satellite,
  ShieldCheck,
  SlidersHorizontal,
  Zap,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type QualityStatus = "all" | "EXCELLENT" | "NOMINAL" | "DEGRADED" | "ACTION_REQUIRED";
type QualityIssue =
  | "all"
  | "missing_values"
  | "invalid_coordinates"
  | "duplicate_detections"
  | "invalid_frp"
  | "invalid_timestamps"
  | "insufficient_geometry";

type DatePreset = "all" | "1y" | "90d" | "30d" | "7d" | "custom";

type Filters = {
  preset: DatePreset;
  startDate: string;
  endDate: string;
  platform: string;
  sourceFile: string;
  productVersion: string;
  processingVersion: string;
  qualityStatus: QualityStatus;
  qualityIssue: QualityIssue;
  processingRunId: string;
};

type QualityMethodologyData = {
  generated_at: string;
  filters_applied: Record<string, string | null>;
  summary_kpis: {
    total_detections_audited: number;
    valid_records_count: number;
    completeness_pct: number;
    quality_status: string;
    missing_values_count: number;
    invalid_coordinates_count: number;
    duplicate_detections_count: number;
    invalid_frp_count: number;
    invalid_timestamps_count: number;
    insufficient_geometry_count: number;
    source_files_count: number;
    processing_runs_count: number;
  };
  quality_issues_breakdown: Array<{
    issue: string;
    issue_key: string;
    count: number;
    pct: number;
    severity: string;
    description: string;
  }>;
  platform_completeness: Array<{
    platform: string;
    sensor: string;
    total_records: number;
    valid_records: number;
    completeness_pct: number;
    missing_frp_pct: number;
    invalid_coords_pct: number;
    mean_frp: number;
    bands_status: string;
    coverage_status: string;
  }>;
  product_versions_distribution: Array<{
    product_version: string;
    files_count: number;
    status: string;
  }>;
  source_files_audit: Array<{
    file_id: number;
    filename: string;
    platform: string;
    product_version: string;
    retrieval_time: string;
    checksum: string;
    ingestion_id: number;
    status: string;
  }>;
  processing_runs_audit: Array<{
    processing_id: number;
    input_file_id: number;
    processing_version: string;
    start_time: string;
    status: string;
  }>;
  data_quality_reports: Array<{
    report_id: string;
    run_id: string;
    generated_at: string;
    total_records: number;
    valid_records: number;
    invalid_coordinates: number;
    missing_frp: number;
    duplicate_detections: number;
    insufficient_geometry: number;
    completeness_pct: number;
    quality_status: string;
    summary_notes: string;
  }>;
  scientific_methodology: {
    data_sources: Array<{
      sensor: string;
      full_name: string;
      platforms: string[];
      operator: string;
      launch_years: number[];
      orbit: string;
      equator_crossing: string;
      swath_width_km: number;
      nadir_resolution: string;
      swath_edge_resolution: string;
      thermal_bands: string;
      detection_principle: string;
      strengths: string;
      limitations: string;
    }>;
    standardization_pipeline: Array<{
      step: number;
      name: string;
      description: string;
    }>;
    matching_criteria: {
      spatial_threshold_km: number;
      temporal_window_minutes: number;
      iou_threshold_strong: number;
      scan_angle_insufficient_degrees: number;
      equations: Array<{
        name: string;
        formula: string;
        interpretation: string;
      }>;
    };
    decision_classes: Array<{
      class: string;
      color: string;
      criteria: string;
      meaning: string;
    }>;
    clustering_algorithm: {
      algorithm: string;
      spatial_epsilon_km: number;
      temporal_epsilon_hours: number;
      min_pts: number;
      outputs: string;
    };
    limitations_and_assumptions: string[];
    version_history: Array<{
      version: string;
      date: string;
      changes: string;
    }>;
  };
  available_options: {
    platforms: string[];
    source_files: string[];
    product_versions: string[];
    processing_versions: string[];
    quality_statuses: string[];
    quality_issues: string[];
    processing_runs: string[];
  };
};

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

export default function QualityMethodologyPage() {
  const [activeTab, setActiveTab] = useState<"quality" | "methodology">("quality");
  const [filters, setFilters] = useState<Filters>({
    preset: "all",
    startDate: "",
    endDate: "",
    platform: "all",
    sourceFile: "",
    productVersion: "",
    processingVersion: "",
    qualityStatus: "all",
    qualityIssue: "all",
    processingRunId: "",
  });

  const [data, setData] = useState<QualityMethodologyData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState<boolean>(false);

  // Fetch API
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    const params = new URLSearchParams();
    if (filters.startDate) params.set("start_date", filters.startDate);
    if (filters.endDate) params.set("end_date", filters.endDate);
    if (filters.platform !== "all") params.set("platform", filters.platform);
    if (filters.sourceFile) params.set("source_file", filters.sourceFile);
    if (filters.productVersion) params.set("product_version", filters.productVersion);
    if (filters.processingVersion) params.set("processing_version", filters.processingVersion);
    if (filters.qualityStatus !== "all") params.set("quality_status", filters.qualityStatus);
    if (filters.qualityIssue !== "all") params.set("quality_issue", filters.qualityIssue);
    if (filters.processingRunId) params.set("processing_run_id", filters.processingRunId);

    fetch(`/api/quality-methodology?${params.toString()}`, { credentials: "omit", signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `Server responded with status ${res.status}`);
        }
        return res.json();
      })
      .then((json: QualityMethodologyData) => {
        setData(json);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(err.message || "Failed to load Quality & Methodology data.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [filters, refreshKey]);

  // Handle Preset changes
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
      platform: "all",
      sourceFile: "",
      productVersion: "",
      processingVersion: "",
      qualityStatus: "all",
      qualityIssue: "all",
      processingRunId: "",
    });
  };

  // Export audit report to CSV
  const handleExportAuditCSV = () => {
    if (!data) return;
    const headers = [
      "metric_type",
      "name",
      "count",
      "percentage",
      "severity_status",
      "details",
    ];

    const rows: Array<Array<string | number>> = [];

    // Summary
    rows.push(["Summary", "Total Detections Audited", data.summary_kpis.total_detections_audited, 100, data.summary_kpis.quality_status, "Overall completeness"]);
    rows.push(["Summary", "Valid Records", data.summary_kpis.valid_records_count, data.summary_kpis.completeness_pct, "HEALTHY", "Passed all validation checks"]);

    // Issues
    for (const item of data.quality_issues_breakdown) {
      rows.push(["Defect", `"${item.issue}"`, item.count, item.pct, item.severity, `"${item.description.replace(/"/g, '""')}"`]);
    }

    // Platforms
    for (const p of data.platform_completeness) {
      rows.push(["Platform", `"${p.platform}"`, p.total_records, p.completeness_pct, p.bands_status, `"${p.coverage_status}"`]);
    }

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `twinflame_quality_audit_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const kpis = data?.summary_kpis;
  const meth = data?.scientific_methodology;

  return (
    <div className="historical-page-container quality-page-container">
      {/* 1. Page Header */}
      <header className="historical-header">
        <div className="historical-header-main">
          <div className="historical-badge">
            <ShieldCheck size={13} />
            <span>NASA SPACE APPS CHALLENGE 2026 · DATA ASSURANCE &amp; SCIENTIFIC RIGOR</span>
          </div>
          <h1>09 · Quality &amp; Methodology</h1>
          <p className="historical-subtitle">
            Dual-domain interface for automated data quality auditing, missing value detection, and complete mathematical reference for the harmonization methodology.
          </p>
        </div>
        <div className="historical-header-actions">
          {/* Mode Switcher Tabs */}
          <div className="quality-mode-switcher">
            <button
              type="button"
              className={`mode-tab-btn ${activeTab === "quality" ? "active" : ""}`}
              onClick={() => setActiveTab("quality")}
            >
              <Database size={14} />
              <span>A. Data Quality Audit</span>
            </button>
            <button
              type="button"
              className={`mode-tab-btn ${activeTab === "methodology" ? "active" : ""}`}
              onClick={() => setActiveTab("methodology")}
            >
              <BookOpen size={14} />
              <span>B. Scientific Methodology</span>
            </button>
          </div>

          <button
            type="button"
            className="historical-refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            title="Refresh Quality Audit"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>{loading ? "Auditing..." : "Refresh"}</span>
          </button>
          <button
            type="button"
            className="historical-download-btn"
            onClick={handleExportAuditCSV}
            disabled={!data}
            title="Export validation audit report as CSV"
          >
            <Download size={14} />
            <span>Export Audit</span>
          </button>
        </div>
      </header>

      {/* 2. Specialized Quality Filter Bar */}
      <section className="historical-filter-bar quality-filter-bar" aria-label="Quality and methodology filters">
        <div className="filter-row-primary">
          {/* Time Window Presets */}
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

          {/* Platform Filter */}
          <div className="filter-group">
            <span className="filter-label">
              <Satellite size={13} /> SATELLITE / PLATFORM
            </span>
            <div className="select-wrapper">
              <select
                value={filters.platform}
                onChange={(e) => setFilters((prev) => ({ ...prev, platform: e.target.value }))}
              >
                <option value="all">All Platforms</option>
                <option value="terra">Terra (MODIS)</option>
                <option value="aqua">Aqua (MODIS)</option>
                <option value="noaa20">NOAA-20 (VIIRS)</option>
                <option value="noaa21">NOAA-21 (VIIRS)</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Quality Issue Filter */}
          <div className="filter-group">
            <span className="filter-label">
              <AlertTriangle size={13} /> QUALITY ISSUE
            </span>
            <div className="select-wrapper">
              <select
                value={filters.qualityIssue}
                onChange={(e) => setFilters((prev) => ({ ...prev, qualityIssue: e.target.value as QualityIssue }))}
              >
                <option value="all">All Issues (Complete Audit)</option>
                <option value="missing_values">Missing Values</option>
                <option value="invalid_coordinates">Invalid Coordinates</option>
                <option value="duplicate_detections">Duplicate Detections</option>
                <option value="invalid_frp">Invalid / Missing FRP</option>
                <option value="invalid_timestamps">Invalid Timestamps</option>
                <option value="insufficient_geometry">Insufficient Geometry (&gt;55&deg;)</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Quality Status Filter */}
          <div className="filter-group">
            <span className="filter-label">
              <Award size={13} /> QUALITY STATUS
            </span>
            <div className="select-wrapper">
              <select
                value={filters.qualityStatus}
                onChange={(e) => setFilters((prev) => ({ ...prev, qualityStatus: e.target.value as QualityStatus }))}
              >
                <option value="all">All Statuses</option>
                <option value="EXCELLENT">Excellent (&ge; 99% complete)</option>
                <option value="NOMINAL">Nominal (95% - 99%)</option>
                <option value="DEGRADED">Degraded (85% - 95%)</option>
                <option value="ACTION_REQUIRED">Action Required (&lt; 85%)</option>
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>

          {/* Toggle Advanced Row */}
          <div className="filter-group filter-actions-group">
            <button
              type="button"
              className={`advanced-toggle-btn ${showAdvancedFilters ? "active" : ""}`}
              onClick={() => setShowAdvancedFilters((v) => !v)}
              title="Toggle Advanced Pipeline & Version Filters"
            >
              <Filter size={13} />
              <span>{showAdvancedFilters ? "Hide Details" : "Files & Runs"}</span>
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

        {/* Row 2: Advanced Source File, Product Version, Processing Run Filters */}
        {showAdvancedFilters && (
          <div className="filter-row-advanced quality-filter-advanced">
            {/* Source File Filter */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <FileSpreadsheet size={12} /> SOURCE FILE
              </span>
              <div className="select-wrapper">
                <select
                  value={filters.sourceFile}
                  onChange={(e) => setFilters((prev) => ({ ...prev, sourceFile: e.target.value }))}
                >
                  <option value="">All Source Files</option>
                  {(data?.available_options.source_files || []).map((fn) => (
                    <option key={fn} value={fn}>
                      {fn}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="select-arrow" />
              </div>
            </div>

            {/* Product Version */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <FileCode size={12} /> PRODUCT VERSION
              </span>
              <div className="select-wrapper">
                <select
                  value={filters.productVersion}
                  onChange={(e) => setFilters((prev) => ({ ...prev, productVersion: e.target.value }))}
                >
                  <option value="">All Product Versions</option>
                  <option value="MODIS_C61">MODIS Collection 6.1</option>
                  <option value="VIIRS_VNP14IMG">VIIRS NOAA-20 (VNP14IMG C2)</option>
                  <option value="VIIRS_VJ114IMG">VIIRS NOAA-21 (VJ114IMG C2)</option>
                </select>
                <ChevronDown size={14} className="select-arrow" />
              </div>
            </div>

            {/* Processing Version */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <SlidersHorizontal size={12} /> PROCESSING VERSION
              </span>
              <div className="select-wrapper">
                <select
                  value={filters.processingVersion}
                  onChange={(e) => setFilters((prev) => ({ ...prev, processingVersion: e.target.value }))}
                >
                  <option value="">All Versions</option>
                  <option value="v2.5">v2.5 (Current Harmonized IoU)</option>
                  <option value="v2.4">v2.4 (Geometric Boundary Overlap)</option>
                  <option value="v2.1">v2.1 (Centroid-only Euclidean)</option>
                </select>
                <ChevronDown size={14} className="select-arrow" />
              </div>
            </div>

            {/* Processing Run ID */}
            <div className="threshold-input-box">
              <span className="threshold-title">
                <Activity size={12} /> PROCESSING RUN ID
              </span>
              <div className="select-wrapper">
                <select
                  value={filters.processingRunId}
                  onChange={(e) => setFilters((prev) => ({ ...prev, processingRunId: e.target.value }))}
                >
                  <option value="">All Processing Runs</option>
                  {(data?.available_options.processing_runs || []).map((rid) => (
                    <option key={rid} value={rid}>
                      Run #{rid}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="select-arrow" />
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Error Banner */}
      {error && (
        <section className="historical-error-banner" role="alert">
          <AlertCircle size={20} />
          <div>
            <strong>Data Assurance Audit Notice</strong>
            <p>{error}</p>
          </div>
        </section>
      )}

      {/* ==================================================================== */}
      {/* TAB A: DATA QUALITY & INGESTION AUDIT */}
      {/* ==================================================================== */}
      {activeTab === "quality" && (
        <div className="quality-tab-content">
          {/* 1. Hero KPI Metric Cards */}
          <section className="historical-kpi-grid quality-kpi-grid">
            {/* Completeness & Quality Status */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">DATA COMPLETENESS</span>
                <span className="kpi-icon-wrap" style={{ color: "#80a66f" }}>
                  <ShieldCheck size={16} />
                </span>
              </div>
              <div className="kpi-value" style={{ color: "#80a66f" }}>
                {loading ? "..." : `${kpis?.completeness_pct ?? 100}%`}
              </div>
              <div className="kpi-subtitle">
                <span
                  className={`quality-status-badge ${
                    kpis?.quality_status === "EXCELLENT"
                      ? "status-excellent"
                      : kpis?.quality_status === "NOMINAL"
                      ? "status-nominal"
                      : kpis?.quality_status === "DEGRADED"
                      ? "status-degraded"
                      : "status-action"
                  }`}
                >
                  {kpis?.quality_status || "NOMINAL"}
                </span>{" "}
                validation rating
              </div>
            </div>

            {/* Total Records Audited */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">AUDITED DETECTIONS</span>
                <span className="kpi-icon-wrap" style={{ color: "#a0a596" }}>
                  <Database size={16} />
                </span>
              </div>
              <div className="kpi-value">{loading ? "..." : (kpis?.total_detections_audited ?? 0).toLocaleString()}</div>
              <div className="kpi-subtitle">
                <strong>{(kpis?.valid_records_count ?? 0).toLocaleString()}</strong> fully compliant records
              </div>
            </div>

            {/* Invalid Coordinates */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">INVALID COORDINATES</span>
                <span className="kpi-icon-wrap" style={{ color: "#d92d1f" }}>
                  <Globe2 size={16} />
                </span>
              </div>
              <div className="kpi-value" style={{ color: kpis && kpis.invalid_coordinates_count > 0 ? "#d92d1f" : "#80a66f" }}>
                {loading ? "..." : (kpis?.invalid_coordinates_count ?? 0).toLocaleString()}
              </div>
              <div className="kpi-subtitle">Out of bounds / (0, 0) null island</div>
            </div>

            {/* Invalid or Missing FRP */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">INVALID / MISSING FRP</span>
                <span className="kpi-icon-wrap" style={{ color: "#f58200" }}>
                  <Flame size={16} />
                </span>
              </div>
              <div className="kpi-value" style={{ color: kpis && kpis.invalid_frp_count > 0 ? "#f58200" : "#80a66f" }}>
                {loading ? "..." : (kpis?.invalid_frp_count ?? 0).toLocaleString()}
              </div>
              <div className="kpi-subtitle">Null, &le; 0 MW, or &gt; 5,000 MW</div>
            </div>

            {/* Duplicate Records */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">DUPLICATE DETECTIONS</span>
                <span className="kpi-icon-wrap" style={{ color: "#e9b77e" }}>
                  <Layers size={16} />
                </span>
              </div>
              <div className="kpi-value" style={{ color: "#e9b77e" }}>
                {loading ? "..." : (kpis?.duplicate_detections_count ?? 0).toLocaleString()}
              </div>
              <div className="kpi-subtitle">Redundant spatio-temporal observations</div>
            </div>

            {/* Insufficient Geometry Cases */}
            <div className="historical-kpi-card">
              <div className="kpi-top">
                <span className="kpi-label">INSUFFICIENT GEOMETRY</span>
                <span className="kpi-icon-wrap" style={{ color: "#8d321d" }}>
                  <Zap size={16} />
                </span>
              </div>
              <div className="kpi-value" style={{ color: "#e9b77e" }}>
                {loading ? "..." : (kpis?.insufficient_geometry_count ?? 0).toLocaleString()}
              </div>
              <div className="kpi-subtitle">Off-nadir distortion &gt; 55&deg;</div>
            </div>
          </section>

          {/* 2. Visualizations Row: Quality Defects Breakdown & Platform Completeness */}
          <div className="historical-charts-grid">
            {/* Viz 1: Quality Defects Breakdown */}
            <div className="historical-chart-card">
              <div className="chart-card-header">
                <div>
                  <h3>Quality Defects &amp; Anomaly Distribution</h3>
                  <p className="chart-card-subtitle">
                    Classification of identified defects across missing values, coordinates, FRP, timestamps, and geometry
                  </p>
                </div>
                <span className="chart-source-badge">UNIFIED_DETECTIONS</span>
              </div>
              <div className="chart-render-wrap">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    data={data?.quality_issues_breakdown || []}
                    layout="vertical"
                    margin={{ top: 10, right: 30, left: 70, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#252b22" horizontal={false} />
                    <XAxis type="number" stroke="#687063" tick={{ fontSize: 11 }} />
                    <YAxis dataKey="issue" type="category" stroke="#687063" tick={{ fontSize: 11 }} width={120} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1b2019",
                        border: "1px solid #30362c",
                        borderRadius: "6px",
                        color: "#e8ebe4",
                      }}
                      formatter={(val: any) => [`${val} records`, "Defects"]}
                    />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                      {(data?.quality_issues_breakdown || []).map((entry, idx) => {
                        const fill =
                          entry.severity === "High"
                            ? "#d92d1f"
                            : entry.severity === "Medium"
                            ? "#f58200"
                            : "#80a66f";
                        return <Cell key={`cell-${idx}`} fill={fill} />;
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Viz 2: Data Completeness by Platform */}
            <div className="historical-chart-card">
              <div className="chart-card-header">
                <div>
                  <h3>Data Completeness by Satellite Platform</h3>
                  <p className="chart-card-subtitle">
                    Sensor completeness score (%), valid observations, and spectral channel operational status
                  </p>
                </div>
                <span className="chart-source-badge">harm_sensor_activity_daily</span>
              </div>
              <div className="platform-audit-list">
                {(data?.platform_completeness || []).map((plat) => (
                  <div key={plat.platform} className="platform-audit-row">
                    <div className="plat-audit-top">
                      <div className="plat-title-wrap">
                        <Satellite size={14} className="plat-icon" />
                        <strong>{plat.platform}</strong>
                        <span className="plat-sensor-pill">{plat.sensor}</span>
                      </div>
                      <div className="plat-score-wrap">
                        <span className="plat-score-val">{plat.completeness_pct}%</span>
                        <span className="plat-score-lbl">complete</span>
                      </div>
                    </div>
                    <div className="plat-progress-bar">
                      <div className="plat-progress-fill" style={{ width: `${plat.completeness_pct}%` }} />
                    </div>
                    <div className="plat-audit-details">
                      <span>Total: <strong>{plat.total_records.toLocaleString()}</strong></span>
                      <span>Valid: <strong>{plat.valid_records.toLocaleString()}</strong></span>
                      <span>Missing FRP: <strong>{plat.missing_frp_pct}%</strong></span>
                      <span>Invalid Coords: <strong>{plat.invalid_coords_pct}%</strong></span>
                    </div>
                    <div className="plat-channel-note">
                      <strong>Channels:</strong> {plat.bands_status} &middot; {plat.coverage_status}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 3. Ingestion & Processing Runs Audit Tables */}
          <div className="quality-tables-grid">
            {/* Source Files Ingestion Log */}
            <div className="quality-table-card">
              <div className="quality-table-header">
                <div>
                  <h4>
                    <FileSpreadsheet size={15} /> SOURCE_FILES Ingestion Catalog
                  </h4>
                  <p>NASA FIRMS raw files discovered, validated against SHA-256 checksums, and loaded</p>
                </div>
                <span className="count-badge">{(data?.source_files_audit || []).length} Files</span>
              </div>
              <div className="table-scroll-wrap">
                <table className="quality-data-table">
                  <thead>
                    <tr>
                      <th>File ID</th>
                      <th>Filename</th>
                      <th>Platform</th>
                      <th>Product</th>
                      <th>Retrieval UTC</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.source_files_audit || []).map((file) => (
                      <tr key={file.file_id}>
                        <td><code>#{file.file_id}</code></td>
                        <td className="filename-cell" title={file.filename}>
                          {file.filename}
                        </td>
                        <td>{file.platform}</td>
                        <td><span className="version-pill">{file.product_version}</span></td>
                        <td>{file.retrieval_time ? new Date(file.retrieval_time).toLocaleString() : "—"}</td>
                        <td>
                          <span className="status-badge-ok">
                            <CheckCircle2 size={11} /> VALIDATED
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Processing Runs Execution Log */}
            <div className="quality-table-card">
              <div className="quality-table-header">
                <div>
                  <h4>
                    <Activity size={15} /> PROCESSING_RUNS Standardization Log
                  </h4>
                  <p>Pipeline runs transforming raw CSVs into unified schema and activity clusters</p>
                </div>
                <span className="count-badge">{(data?.processing_runs_audit || []).length} Runs</span>
              </div>
              <div className="table-scroll-wrap">
                <table className="quality-data-table">
                  <thead>
                    <tr>
                      <th>Processing ID</th>
                      <th>Input File ID</th>
                      <th>Version</th>
                      <th>Started At UTC</th>
                      <th>Execution Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.processing_runs_audit || []).map((run) => (
                      <tr key={run.processing_id}>
                        <td><code>run_{run.processing_id}</code></td>
                        <td><code>file_{run.input_file_id}</code></td>
                        <td><span className="version-pill">{run.processing_version}</span></td>
                        <td>{run.start_time ? new Date(run.start_time).toLocaleString() : "—"}</td>
                        <td>
                          <span className="status-badge-ok">
                            <CheckCircle2 size={11} /> {run.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* 4. Preserved Data Quality Reports Table (DATA_QUALITY_REPORTS) */}
          {data?.data_quality_reports && data.data_quality_reports.length > 0 && (
            <div className="dqr-preserved-card">
              <div className="quality-table-header">
                <div>
                  <h4>
                    <FileCheck size={15} /> DATA_QUALITY_REPORTS (Validation History)
                  </h4>
                  <p>Preserved audit snapshots tracking data quality and defect trends across processing runs</p>
                </div>
                <span className="count-badge">{data.data_quality_reports.length} Reports</span>
              </div>
              <div className="table-scroll-wrap">
                <table className="quality-data-table">
                  <thead>
                    <tr>
                      <th>Report ID</th>
                      <th>Run ID</th>
                      <th>Generated At</th>
                      <th>Total Records</th>
                      <th>Valid Records</th>
                      <th>Completeness</th>
                      <th>Status</th>
                      <th>Summary Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.data_quality_reports.map((rep) => (
                      <tr key={rep.report_id}>
                        <td><code>{rep.report_id}</code></td>
                        <td><code>{rep.run_id}</code></td>
                        <td>{new Date(rep.generated_at).toLocaleString()}</td>
                        <td>{rep.total_records.toLocaleString()}</td>
                        <td style={{ color: "#80a66f" }}>{rep.valid_records.toLocaleString()}</td>
                        <td><strong>{rep.completeness_pct}%</strong></td>
                        <td>
                          <span className="status-badge-ok">{rep.quality_status}</span>
                        </td>
                        <td className="notes-cell">{rep.summary_notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ==================================================================== */}
      {/* TAB B: SCIENTIFIC METHODOLOGY & MATHEMATICAL REFERENCE */}
      {/* ==================================================================== */}
      {activeTab === "methodology" && (
        <div className="methodology-tab-content">
          {/* Section 1: Satellite Sensor Profiles */}
          <section className="methodology-section">
            <div className="section-title-wrap">
              <Satellite size={18} className="section-icon" />
              <div>
                <h3>1. Satellite Data Sources &amp; Product Specifications</h3>
                <p>Orbital, optical, and radiometric characteristics of MODIS and VIIRS active fire instruments</p>
              </div>
            </div>

            <div className="sensor-duel-cards">
              {(meth?.data_sources || []).map((sensor) => (
                <div key={sensor.sensor} className="sensor-spec-box">
                  <div className="sensor-box-head">
                    <div>
                      <h4>{sensor.sensor} &middot; {sensor.full_name}</h4>
                      <span className="sensor-operator">{sensor.operator} &middot; Platforms: {sensor.platforms.join(", ")}</span>
                    </div>
                    <span className="sensor-launch-tag">Launched {sensor.launch_years.join(" / ")}</span>
                  </div>
                  <div className="sensor-specs-grid">
                    <div className="spec-item">
                      <span className="spec-label">Orbit &amp; Altitude</span>
                      <strong className="spec-val">{sensor.orbit}</strong>
                    </div>
                    <div className="spec-item">
                      <span className="spec-label">Equator Crossing Time</span>
                      <strong className="spec-val">{sensor.equator_crossing}</strong>
                    </div>
                    <div className="spec-item">
                      <span className="spec-label">Swath Width</span>
                      <strong className="spec-val">{sensor.swath_width_km.toLocaleString()} km</strong>
                    </div>
                    <div className="spec-item">
                      <span className="spec-label">Nadir Spatial Resolution</span>
                      <strong className="spec-val" style={{ color: "#80a66f" }}>{sensor.nadir_resolution}</strong>
                    </div>
                    <div className="spec-item">
                      <span className="spec-label">Swath Edge Resolution</span>
                      <strong className="spec-val" style={{ color: "#f58200" }}>{sensor.swath_edge_resolution}</strong>
                    </div>
                    <div className="spec-item">
                      <span className="spec-label">Thermal Bands</span>
                      <strong className="spec-val">{sensor.thermal_bands}</strong>
                    </div>
                  </div>
                  <div className="sensor-principle-box">
                    <strong>Detection Principle:</strong> {sensor.detection_principle}
                  </div>
                  <div className="sensor-strengths-box">
                    <strong>Scientific Strengths:</strong> {sensor.strengths}
                  </div>
                  <div className="sensor-limits-box">
                    <strong>Instrument Limitations:</strong> {sensor.limitations}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Section 2: Standardization Pipeline */}
          <section className="methodology-section">
            <div className="section-title-wrap">
              <Layers size={18} className="section-icon" />
              <div>
                <h3>2. Standardization Pipeline Methodology</h3>
                <p>Four-stage pipeline transforming heterogeneous NRT feeds into harmonized observation records</p>
              </div>
            </div>

            <div className="pipeline-steps-grid">
              {(meth?.standardization_pipeline || []).map((step) => (
                <div key={step.step} className="pipeline-step-card">
                  <div className="step-number">{step.step}</div>
                  <div className="step-content">
                    <h5>{step.name}</h5>
                    <p>{step.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Section 3: Mathematical Formulations & Matching Criteria */}
          <section className="methodology-section">
            <div className="section-title-wrap">
              <FileCode size={18} className="section-icon" />
              <div>
                <h3>3. Mathematical Formulations &amp; Matching Criteria</h3>
                <p>Quantitative spatio-temporal coincidence algorithms and geometric equations</p>
              </div>
            </div>

            <div className="criteria-parameters-card">
              <div className="criteria-param-item">
                <span className="criteria-param-lbl">MAX SPATIAL DISTANCE (d)</span>
                <span className="criteria-param-val">&le; {meth?.matching_criteria.spatial_threshold_km} km</span>
                <span className="criteria-param-sub">Haversine Euclidean distance</span>
              </div>
              <div className="criteria-param-item">
                <span className="criteria-param-lbl">MAX TEMPORAL WINDOW (&Delta;t)</span>
                <span className="criteria-param-val">&le; {meth?.matching_criteria.temporal_window_minutes} min</span>
                <span className="criteria-param-sub">Orbital coincidence offset</span>
              </div>
              <div className="criteria-param-item">
                <span className="criteria-param-lbl">MIN STRONG IoU OVERLAP</span>
                <span className="criteria-param-val" style={{ color: "#80a66f" }}>
                  &ge; {meth?.matching_criteria.iou_threshold_strong}
                </span>
                <span className="criteria-param-sub">Intersection over Union</span>
              </div>
              <div className="criteria-param-item">
                <span className="criteria-param-lbl">SCAN ANGLE SAFEGUARD (&theta;)</span>
                <span className="criteria-param-val" style={{ color: "#f58200" }}>
                  &gt; {meth?.matching_criteria.scan_angle_insufficient_degrees}&deg;
                </span>
                <span className="criteria-param-sub">Triggers Insufficient Geometry</span>
              </div>
            </div>

            <div className="equations-grid">
              {(meth?.matching_criteria.equations || []).map((eq) => (
                <div key={eq.name} className="equation-card">
                  <div className="equation-head">
                    <Zap size={14} />
                    <span>{eq.name}</span>
                  </div>
                  <div className="equation-formula-box">
                    <code>{eq.formula}</code>
                  </div>
                  <div className="equation-interpretation">{eq.interpretation}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Section 4: Correspondence Decision Classes */}
          <section className="methodology-section">
            <div className="section-title-wrap">
              <Award size={18} className="section-icon" />
              <div>
                <h3>4. Correspondence Decision Classes</h3>
                <p>Taxonomy of automated harmonization classifications based on spatial and temporal metrics</p>
              </div>
            </div>

            <div className="decision-taxonomy-grid">
              {(meth?.decision_classes || []).map((cls) => (
                <div key={cls.class} className="decision-tax-card" style={{ borderLeftColor: cls.color }}>
                  <div className="decision-tax-top">
                    <span className="tax-badge" style={{ backgroundColor: `${cls.color}25`, color: cls.color, borderColor: `${cls.color}50` }}>
                      {cls.class}
                    </span>
                    <span className="tax-criteria">{cls.criteria}</span>
                  </div>
                  <p className="tax-meaning">{cls.meaning}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Section 5: Clustering Algorithm & Limitations */}
          <section className="methodology-section">
            <div className="clustering-and-limits-grid">
              {/* Clustering */}
              <div className="clustering-box">
                <div className="section-title-wrap">
                  <Globe2 size={16} className="section-icon" />
                  <div>
                    <h4>5. Spatio-Temporal Activity Clustering</h4>
                    <p>Density-based clustering grouping contiguous hot spots into unified fire complexes</p>
                  </div>
                </div>
                <div className="clustering-specs">
                  <div className="clust-row">
                    <span>Algorithm</span>
                    <strong>{meth?.clustering_algorithm.algorithm}</strong>
                  </div>
                  <div className="clust-row">
                    <span>Spatial Reach (&epsilon;<sub>spatial</sub>)</span>
                    <strong>{meth?.clustering_algorithm.spatial_epsilon_km} km</strong>
                  </div>
                  <div className="clust-row">
                    <span>Temporal Reach (&epsilon;<sub>temporal</sub>)</span>
                    <strong>{meth?.clustering_algorithm.temporal_epsilon_hours} hours</strong>
                  </div>
                  <div className="clust-row">
                    <span>Cluster Outputs</span>
                    <strong>{meth?.clustering_algorithm.outputs}</strong>
                  </div>
                </div>
              </div>

              {/* Limitations */}
              <div className="limitations-box">
                <div className="section-title-wrap">
                  <AlertTriangle size={16} className="section-icon" style={{ color: "#f58200" }} />
                  <div>
                    <h4>6. Scientific Limitations &amp; Assumptions</h4>
                    <p>Known physical observation constraints and cross-sensor caveats</p>
                  </div>
                </div>
                <ul className="limitations-list">
                  {(meth?.limitations_and_assumptions || []).map((lim, idx) => (
                    <li key={idx}>{lim}</li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          {/* Section 6: Algorithm Version History */}
          <section className="methodology-section">
            <div className="section-title-wrap">
              <FileText size={18} className="section-icon" />
              <div>
                <h3>7. Algorithm Version History</h3>
                <p>Evolution of the TwinFlame standardization and harmonization algorithms</p>
              </div>
            </div>

            <div className="version-timeline">
              {(meth?.version_history || []).map((ver) => (
                <div key={ver.version} className="timeline-node">
                  <div className="timeline-dot" />
                  <div className="timeline-content">
                    <div className="timeline-top">
                      <strong>{ver.version}</strong>
                      <span className="timeline-date">{ver.date}</span>
                    </div>
                    <p>{ver.changes}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* 5. Footer Notes */}
      <footer className="historical-footer">
        <div className="historical-footer-notes">
          <p>
            <strong>Quality &amp; Methodology Assurance:</strong> TwinFlame rigorously audits all incoming active fire records against spatial coordinate bounds, non-physical FRP anomalies, and off-nadir optical distortion limits. Validation results are logged in <code>DATA_QUALITY_REPORTS</code> to maintain a verifiable audit trail for scientific publications.
          </p>
        </div>
        <div className="historical-footer-meta">
          <span>Database: DuckDB &middot; Tables: UNIFIED_DETECTIONS, SOURCE_FILES, PROCESSING_RUNS, DATA_QUALITY_REPORTS</span>
          <span>Generated: {data?.generated_at ? new Date(data.generated_at).toUTCString() : "Live"}</span>
        </div>
      </footer>
    </div>
  );
}
