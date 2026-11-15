import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  Download,
  FileText,
  Filter,
  Layers,
  Play,
  RefreshCw,
  Search,
  Server,
  Sliders,
  Workflow,
  X,
  XCircle,
} from "lucide-react";

type DatePreset = "all" | "1y" | "90d" | "30d" | "7d" | "custom";

interface Filters {
  preset: DatePreset;
  startDate: string;
  endDate: string;
  ingestionType: string;
  stage: string;
  status: string;
  platform: string;
  sourceFile: string;
  processingVersion: string;
  runId: string;
}

interface SummaryKPIs {
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  running_runs: number;
  success_rate_pct: number;
  avg_duration_seconds: number;
  total_input_records: number;
  total_candidate_pairs: number;
  total_correspondence_edges: number;
  total_activity_clusters: number;
}

interface StageSuccessRate {
  stage: string;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  running_runs: number;
  success_rate_pct: number;
}

interface DurationTrendPoint {
  run_id: string;
  date: string;
  timestamp: string;
  duration_seconds: number;
  stage: string;
  status: string;
  algorithm_version: string;
  input_count: number;
  edge_count: number;
}

interface RecordsFunnel {
  input_records: number;
  candidate_pairs: number;
  correspondence_edges: number;
  activity_clusters: number;
  candidate_reduction_pct: number;
  edge_acceptance_pct: number;
}

interface HarmonizationRun {
  run_id: string;
  algorithm_version: string;
  config_id: string;
  started_at_utc: string | null;
  finished_at_utc: string | null;
  duration_seconds: number;
  status: string;
  input_count: number;
  candidate_count: number;
  correspondence_edge_count: number;
  activity_cluster_count: number;
  failed_stage: string | null;
  error_summary: string | null;
}

interface IngestionRun {
  ingestion_id: number;
  source_type: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  status: string;
  files_count: number;
}

interface SourceFileRecord {
  file_id: number;
  filename: string;
  platform: string;
  product_version: string;
  retrieval_time: string | null;
  checksum: string;
  ingestion_id: number;
}

interface ProcessingRunRecord {
  processing_id: number;
  input_file_id: number;
  filename: string;
  platform: string;
  processing_version: string;
  start_time: string | null;
  status: string;
}

interface PipelineManagementData {
  generated_at: string;
  filters_applied: Record<string, string | null>;
  summary_kpis: SummaryKPIs;
  stage_success_rates: StageSuccessRate[];
  duration_trend: DurationTrendPoint[];
  records_funnel: RecordsFunnel;
  harmonization_runs: HarmonizationRun[];
  ingestion_runs: IngestionRun[];
  source_files_overview: SourceFileRecord[];
  processing_runs: ProcessingRunRecord[];
  available_options: {
    ingestion_types: string[];
    stages: string[];
    statuses: string[];
    platforms: string[];
    source_files: string[];
    processing_versions: string[];
    run_ids: string[];
  };
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

function statusColor(status: string) {
  const s = status.toUpperCase();
  if (s.includes("SUCCESS") || s.includes("COMPLETED")) return "#80a66f";
  if (s.includes("RUNNING") || s.includes("PENDING")) return "#f58200";
  if (s.includes("FAIL") || s.includes("ERROR")) return "#d92d1f";
  return "#9ca3af";
}

export default function PipelineManagementPage() {
  const [filters, setFilters] = useState<Filters>({
    preset: "all",
    startDate: "",
    endDate: "",
    ingestionType: "all",
    stage: "all",
    status: "all",
    platform: "all",
    sourceFile: "",
    processingVersion: "all",
    runId: "",
  });

  const [activeTab, setActiveTab] = useState<"harmonization" | "ingestion" | "source_files" | "processing">("harmonization");
  const [data, setData] = useState<PipelineManagementData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState<boolean>(false);

  // Detail Modal / Selection state
  const [selectedHarmRun, setSelectedHarmRun] = useState<HarmonizationRun | null>(null);

  // Job Trigger Modal state
  const [isTriggerModalOpen, setIsTriggerModalOpen] = useState<boolean>(false);
  const [triggerStage, setTriggerStage] = useState<string>("harmonization");
  const [triggerStartDate, setTriggerStartDate] = useState<string>("");
  const [triggerEndDate, setTriggerEndDate] = useState<string>("");
  const [triggerConfigId, setTriggerConfigId] = useState<string>("cfg_spatiotemporal_iou_v25");
  const [triggerAlgVersion, setTriggerAlgVersion] = useState<string>("v2.5");
  const [triggerDryRun, setTriggerDryRun] = useState<boolean>(false);
  const [isSubmittingJob, setIsSubmittingJob] = useState<boolean>(false);
  const [jobSubmitMessage, setJobSubmitMessage] = useState<{ text: string; error: boolean } | null>(null);

  // Fetch API
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");

    const params = new URLSearchParams();
    if (filters.startDate) params.set("start_date", filters.startDate);
    if (filters.endDate) params.set("end_date", filters.endDate);
    if (filters.ingestionType !== "all") params.set("ingestion_type", filters.ingestionType);
    if (filters.stage !== "all") params.set("stage", filters.stage);
    if (filters.status !== "all") params.set("status", filters.status);
    if (filters.platform !== "all") params.set("platform", filters.platform);
    if (filters.sourceFile) params.set("source_file", filters.sourceFile);
    if (filters.processingVersion !== "all") params.set("processing_version", filters.processingVersion);
    if (filters.runId) params.set("run_id", filters.runId);

    const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
    fetch(`${base}/api/pipeline-management?${params.toString()}`, {
      credentials: "omit",
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `Server responded with status ${res.status}`);
        }
        return res.json();
      })
      .then((json: PipelineManagementData) => {
        setData(json);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(err.message || "Failed to load Pipeline Management telemetry.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [filters, refreshKey]);

  const handlePresetChange = (preset: DatePreset) => {
    const dates = calculatePresetDates(preset);
    setFilters((prev) => ({
      ...prev,
      preset,
      startDate: dates.startDate,
      endDate: dates.endDate,
    }));
  };

  const handleExportCSV = () => {
    if (!data) return;
    const rows = [
      [
        "run_id",
        "stage",
        "algorithm_version",
        "config_id",
        "started_at_utc",
        "duration_seconds",
        "status",
        "input_count",
        "candidate_count",
        "correspondence_edge_count",
        "activity_cluster_count",
        "failed_stage",
        "error_summary",
      ].join(","),
    ];

    data.harmonization_runs.forEach((r) => {
      rows.push(
        [
          `"${r.run_id}"`,
          `"Harmonization"`,
          `"${r.algorithm_version}"`,
          `"${r.config_id}"`,
          `"${r.started_at_utc || ""}"`,
          r.duration_seconds,
          `"${r.status}"`,
          r.input_count,
          r.candidate_count,
          r.correspondence_edge_count,
          r.activity_cluster_count,
          `"${r.failed_stage || ""}"`,
          `"${(r.error_summary || "").replace(/"/g, '""')}"`,
        ].join(",")
      );
    });

    const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `twinflame_pipeline_runs_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleTriggerJobSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmittingJob(true);
    setJobSubmitMessage(null);

    const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
    try {
      const res = await fetch(`${base}/api/pipeline/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage: triggerStage,
          start_date: triggerStartDate || null,
          end_date: triggerEndDate || null,
          config_id: triggerConfigId,
          algorithm_version: triggerAlgVersion,
          dry_run: triggerDryRun,
        }),
      });

      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.detail || `Job launch rejected (${res.status})`);
      }

      setJobSubmitMessage({
        text: `Job '${body.run_id}' initiated successfully in background!`,
        error: false,
      });

      setTimeout(() => {
        setIsTriggerModalOpen(false);
        setJobSubmitMessage(null);
        setRefreshKey((k) => k + 1);
      }, 1400);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to execute pipeline job.";
      setJobSubmitMessage({ text: msg, error: true });
    } finally {
      setIsSubmittingJob(false);
    }
  };

  // Funnel data transformed for horizontal bar chart
  const funnelChartData = useMemo(() => {
    if (!data?.records_funnel) return [];
    return [
      { step: "1. Input Detections", count: data.records_funnel.input_records, fill: "#80a66f" },
      { step: "2. Coincident Candidates", count: data.records_funnel.candidate_pairs, fill: "#f58200" },
      { step: "3. Correspondence Edges", count: data.records_funnel.correspondence_edges, fill: "#d92d1f" },
      { step: "4. Activity Clusters", count: data.records_funnel.activity_clusters, fill: "#9ca3af" },
    ];
  }, [data?.records_funnel]);

  return (
    <div className="historical-page-container pipeline-page-container" role="main">
      {/* 1. Header & Actions Bar */}
      <header className="historical-header">
        <div className="historical-title-group">
          <div className="historical-badge">
            <Server size={14} />
            <span>PAGE 10 &middot; SYSTEM OPERATIONS &amp; EXECUTION ENGINE</span>
          </div>
          <h1 className="historical-title">Pipeline Management</h1>
          <p className="historical-subtitle">
            Real-time execution telemetry, multi-stage lineage tracking, and secure harmonization job execution
          </p>
        </div>

        <div className="historical-header-actions">
          <button
            type="button"
            className="historical-primary-action-btn pipeline-trigger-btn"
            onClick={() => setIsTriggerModalOpen(true)}
            title="Execute new harmonization pipeline run"
          >
            <Play size={14} className="fill-icon" />
            <span>Execute Pipeline Run</span>
          </button>
          <button
            type="button"
            className="historical-refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            title="Refresh operational telemetry"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>{loading ? "Syncing..." : "Refresh"}</span>
          </button>
          <button
            type="button"
            className="historical-download-btn"
            onClick={handleExportCSV}
            disabled={!data || data.harmonization_runs.length === 0}
            title="Export pipeline execution audit log"
          >
            <Download size={14} />
            <span>Export CSV</span>
          </button>
        </div>
      </header>

      {/* 2. Operational Architecture Banner */}
      <section className="harmonization-methodology-banner pipeline-banner" aria-label="Pipeline Architecture">
        <div className="methodology-icon">
          <Workflow size={22} />
        </div>
        <div className="methodology-content">
          <h4>Multi-Tier Processing &amp; Harmonization Architecture</h4>
          <p>
            The TwinFlame pipeline ingests raw NASA FIRMS streams into <code>SOURCE_FILES</code> and <code>INGESTION_RUNS</code>, standardizes observations into <code>UNIFIED_DETECTIONS</code> via <code>PROCESSING_RUNS</code>, and pairs coincident satellite overpasses into <code>harm_correspondence_edges</code> and <code>harm_activity_clusters</code> documented in <code>harm_run_metadata</code>.
          </p>
          <div className="methodology-tags">
            <span className="methodology-tag">
              <strong>Execution Engine:</strong> FastAPI + DuckDB Read-Only Concurrency
            </span>
            <span className="methodology-tag">
              <strong>Concurrency Control:</strong> Server-Side Mutex Lock
            </span>
            <span className="methodology-tag">
              <strong>Active Algorithm:</strong> {filters.processingVersion !== "all" ? filters.processingVersion : "v2.5 (Polygon IoU)"}
            </span>
            <span className="methodology-tag">
              <strong>Telemetry Mode:</strong> Real-time Background Worker
            </span>
          </div>
        </div>
      </section>

      {/* 3. Filter Bar */}
      <section className="historical-filter-bar harmonization-filter-bar" aria-label="Pipeline management filters">
        <div className="filter-row-primary">
          {/* Preset Buttons */}
          <div className="filter-group preset-group">
            <span className="filter-label">
              <Clock size={13} /> TIME WINDOW
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

          {/* Pipeline Stage Selector */}
          <div className="filter-group">
            <span className="filter-label">
              <Workflow size={13} /> STAGE
            </span>
            <div className="select-wrapper">
              <select
                value={filters.stage}
                onChange={(e) => setFilters((prev) => ({ ...prev, stage: e.target.value }))}
              >
                <option value="all">All Pipeline Stages</option>
                <option value="Ingestion">Ingestion (FIRMS API)</option>
                <option value="Standardization">Standardization &amp; Cleaning</option>
                <option value="Harmonization">Harmonization (IoU Matching)</option>
              </select>
            </div>
          </div>

          {/* Execution Status Selector */}
          <div className="filter-group">
            <span className="filter-label">
              <CheckCircle2 size={13} /> STATUS
            </span>
            <div className="select-wrapper">
              <select
                value={filters.status}
                onChange={(e) => setFilters((prev) => ({ ...prev, status: e.target.value }))}
              >
                <option value="all">All Statuses</option>
                <option value="Completed">Completed / Success</option>
                <option value="Running">Running / In Progress</option>
                <option value="Failed">Failed / Error</option>
                <option value="Pending">Pending</option>
              </select>
            </div>
          </div>

          {/* Toggle Advanced Filters */}
          <button
            type="button"
            className={`advanced-toggle-btn ${showAdvancedFilters ? "active" : ""}`}
            onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
          >
            <Sliders size={13} />
            <span>Advanced Filters</span>
          </button>
        </div>

        {/* Row 2: Advanced Controls */}
        {showAdvancedFilters && (
          <div className="filter-row-advanced">
            {/* Ingestion Type */}
            <div className="filter-group">
              <span className="filter-label">INGESTION TYPE</span>
              <div className="select-wrapper">
                <select
                  value={filters.ingestionType}
                  onChange={(e) => setFilters((prev) => ({ ...prev, ingestionType: e.target.value }))}
                >
                  <option value="all">All Ingestion Sources</option>
                  <option value="FIRMS API">FIRMS API Live Stream</option>
                  <option value="Historical Archive">Historical Archive</option>
                  <option value="Sample">Sample / Synthetic</option>
                </select>
              </div>
            </div>

            {/* Satellite / Platform */}
            <div className="filter-group">
              <span className="filter-label">SATELLITE / PLATFORM</span>
              <div className="select-wrapper">
                <select
                  value={filters.platform}
                  onChange={(e) => setFilters((prev) => ({ ...prev, platform: e.target.value }))}
                >
                  <option value="all">All Platforms</option>
                  <option value="Terra">Terra (MODIS)</option>
                  <option value="Aqua">Aqua (MODIS)</option>
                  <option value="NOAA-20">NOAA-20 (VIIRS)</option>
                  <option value="NOAA-21">NOAA-21 (VIIRS)</option>
                </select>
              </div>
            </div>

            {/* Source File */}
            <div className="filter-group">
              <span className="filter-label">SOURCE FILE</span>
              <div className="select-wrapper">
                <select
                  value={filters.sourceFile}
                  onChange={(e) => setFilters((prev) => ({ ...prev, sourceFile: e.target.value }))}
                >
                  <option value="">All Source Files</option>
                  {data?.available_options.source_files.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Processing Version */}
            <div className="filter-group">
              <span className="filter-label">ALGORITHM VERSION</span>
              <div className="select-wrapper">
                <select
                  value={filters.processingVersion}
                  onChange={(e) => setFilters((prev) => ({ ...prev, processingVersion: e.target.value }))}
                >
                  <option value="all">All Versions</option>
                  <option value="v2.5">v2.5 (Polygon IoU)</option>
                  <option value="v2.4">v2.4 (Adaptive Thresholds)</option>
                  <option value="v2.1">v2.1 (Euclidean Distance)</option>
                  <option value="v1.0">v1.0 (Raw Baseline)</option>
                </select>
              </div>
            </div>

            {/* Run ID Filter */}
            <div className="filter-group search-input-group">
              <span className="filter-label">RUN ID SEARCH</span>
              <div className="text-input-wrap">
                <Search size={13} className="search-icon" />
                <input
                  type="text"
                  placeholder="e.g. run_2024_06..."
                  value={filters.runId}
                  onChange={(e) => setFilters((prev) => ({ ...prev, runId: e.target.value }))}
                />
              </div>
            </div>

            <button
              type="button"
              className="reset-filters-btn"
              onClick={() =>
                setFilters({
                  preset: "all",
                  startDate: "",
                  endDate: "",
                  ingestionType: "all",
                  stage: "all",
                  status: "all",
                  platform: "all",
                  sourceFile: "",
                  processingVersion: "all",
                  runId: "",
                })
              }
            >
              Reset All
            </button>
          </div>
        )}
      </section>

      {/* Error Banner */}
      {error && (
        <div className="historical-error-banner" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* 4. Top KPI Hero Cards */}
      <section className="historical-kpi-grid harmonization-kpi-grid" aria-label="Pipeline Execution KPIs">
        {/* Total Runs */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">TOTAL PIPELINE RUNS</span>
            <Server size={16} className="kpi-icon" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value">{loading ? "—" : data?.summary_kpis.total_runs ?? 0}</span>
          </div>
          <div className="kpi-footer">
            <span
              className="kpi-badge"
              style={{
                backgroundColor: "rgba(128, 166, 111, 0.15)",
                color: "#80a66f",
                borderColor: "#80a66f",
              }}
            >
              {loading ? "—" : `${data?.summary_kpis.success_rate_pct ?? 100}% Success Rate`}
            </span>
          </div>
        </div>

        {/* Completed Runs */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">COMPLETED RUNS</span>
            <CheckCircle2 size={16} className="kpi-icon text-success" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value text-success">{loading ? "—" : data?.summary_kpis.completed_runs ?? 0}</span>
          </div>
          <div className="kpi-footer">
            <span className="kpi-subtext">Across Ingestion, Standard &amp; Harmonization</span>
          </div>
        </div>

        {/* Failed Runs */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">FAILED RUNS</span>
            <XCircle size={16} className="kpi-icon text-danger" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value text-danger">{loading ? "—" : data?.summary_kpis.failed_runs ?? 0}</span>
          </div>
          <div className="kpi-footer">
            <span className="kpi-subtext">Error traces isolated &amp; documented</span>
          </div>
        </div>

        {/* Average Processing Duration */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">AVG PROCESSING DURATION</span>
            <Clock size={16} className="kpi-icon" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value">{loading ? "—" : `${data?.summary_kpis.avg_duration_seconds ?? 0}s`}</span>
          </div>
          <div className="kpi-footer">
            <span className="kpi-subtext">Mean harmonization execution runtime</span>
          </div>
        </div>

        {/* Total Input Records */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">INPUT RECORDS AUDITED</span>
            <Database size={16} className="kpi-icon" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value">{loading ? "—" : data?.summary_kpis.total_input_records.toLocaleString() ?? 0}</span>
          </div>
          <div className="kpi-footer">
            <span className="kpi-subtext">Detections processed from unified streams</span>
          </div>
        </div>

        {/* Activity Clusters Generated */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">CLUSTERS GENERATED</span>
            <Layers size={16} className="kpi-icon" />
          </div>
          <div className="kpi-value-row">
            <span className="kpi-value">{loading ? "—" : data?.summary_kpis.total_activity_clusters ?? 0}</span>
          </div>
          <div className="kpi-footer">
            <span className="kpi-subtext">
              {data ? `${data.summary_kpis.total_correspondence_edges} paired edges` : "—"}
            </span>
          </div>
        </div>
      </section>

      {/* 5. Stage Health Progress Cards */}
      <section className="pipeline-stage-cards-grid" aria-label="Pipeline Stage Success Rates">
        {data?.stage_success_rates.map((sr) => {
          const isGood = sr.success_rate_pct >= 90;
          return (
            <div key={sr.stage} className="pipeline-stage-card">
              <div className="stage-card-header">
                <div className="stage-name-wrap">
                  <Workflow size={15} />
                  <h3>{sr.stage} Stage</h3>
                </div>
                <span
                  className="stage-rate-badge"
                  style={{
                    color: isGood ? "#80a66f" : "#f58200",
                    borderColor: isGood ? "#80a66f" : "#f58200",
                  }}
                >
                  {sr.success_rate_pct}% Success
                </span>
              </div>
              <div className="stage-progress-bar-bg">
                <div
                  className="stage-progress-bar-fill"
                  style={{
                    width: `${Math.min(100, Math.max(5, sr.success_rate_pct))}%`,
                    backgroundColor: isGood ? "#80a66f" : "#f58200",
                  }}
                />
              </div>
              <div className="stage-metrics-row">
                <div className="stage-metric-col">
                  <span className="stage-m-label">TOTAL RUNS</span>
                  <span className="stage-m-val">{sr.total_runs}</span>
                </div>
                <div className="stage-metric-col">
                  <span className="stage-m-label">SUCCESSFUL</span>
                  <span className="stage-m-val text-success">{sr.successful_runs}</span>
                </div>
                <div className="stage-metric-col">
                  <span className="stage-m-label">FAILED</span>
                  <span className="stage-m-val text-danger">{sr.failed_runs}</span>
                </div>
                <div className="stage-metric-col">
                  <span className="stage-m-label">RUNNING</span>
                  <span className="stage-m-val text-warning">{sr.running_runs}</span>
                </div>
              </div>
            </div>
          );
        })}
      </section>

      {/* 6. Visualizations Section: Duration Trend & Funnel */}
      <div className="historical-charts-grid pipeline-charts-grid">
        {/* Execution Duration Trend */}
        <section className="historical-chart-panel" aria-label="Execution duration trend">
          <div className="panel-header">
            <div className="panel-title-wrap">
              <Clock size={16} />
              <h2>Execution Duration Trend</h2>
            </div>
            <span className="panel-subtitle">Runtime duration (seconds) across pipeline runs</span>
          </div>
          <div className="chart-wrapper" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data?.duration_trend || []} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
                <defs>
                  <linearGradient id="durationGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#80a66f" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#80a66f" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#252b22" />
                <XAxis dataKey="run_id" stroke="#70796b" tick={{ fontSize: 11 }} />
                <YAxis stroke="#70796b" tick={{ fontSize: 11 }} unit="s" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1b2019",
                    borderColor: "#30362c",
                    color: "#e6e8e3",
                    fontSize: 12,
                    borderRadius: 4,
                  }}
                  formatter={(val: number | string | Array<number | string> | undefined) => [`${val ?? 0}s`, "Duration"]}
                />
                <Area type="monotone" dataKey="duration_seconds" stroke="#80a66f" strokeWidth={2} fillOpacity={1} fill="url(#durationGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        {/* Processing Funnel */}
        <section className="historical-chart-panel" aria-label="Pipeline Transformation Funnel">
          <div className="panel-header">
            <div className="panel-title-wrap">
              <Filter size={16} />
              <h2>Data Transformation Funnel</h2>
            </div>
            <span className="panel-subtitle">Input Detections &rarr; Candidates &rarr; Harmonized Edges</span>
          </div>
          <div className="chart-wrapper" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnelChartData} layout="vertical" margin={{ top: 10, right: 25, left: 45, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#252b22" />
                <XAxis type="number" stroke="#70796b" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="step" stroke="#70796b" tick={{ fontSize: 11 }} width={135} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1b2019",
                    borderColor: "#30362c",
                    color: "#e6e8e3",
                    fontSize: 12,
                    borderRadius: 4,
                  }}
                  formatter={(val: number | string | Array<number | string> | undefined) => [Number(val || 0).toLocaleString(), "Records"]}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {funnelChartData.map((entry, index) => (
                    <Cell key={`funnel-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      {/* 7. Multi-Stage Telemetry Tabs */}
      <section className="pipeline-telemetry-section" aria-label="Detailed Pipeline Tables">
        <div className="quality-tabs-bar">
          <button
            type="button"
            className={`quality-tab-btn ${activeTab === "harmonization" ? "active" : ""}`}
            onClick={() => setActiveTab("harmonization")}
          >
            <Cpu size={14} />
            <span>Harmonization Runs ({data?.harmonization_runs.length ?? 0})</span>
          </button>
          <button
            type="button"
            className={`quality-tab-btn ${activeTab === "ingestion" ? "active" : ""}`}
            onClick={() => setActiveTab("ingestion")}
          >
            <Server size={14} />
            <span>Ingestion History ({data?.ingestion_runs.length ?? 0})</span>
          </button>
          <button
            type="button"
            className={`quality-tab-btn ${activeTab === "source_files" ? "active" : ""}`}
            onClick={() => setActiveTab("source_files")}
          >
            <FileText size={14} />
            <span>Source Files Overview ({data?.source_files_overview.length ?? 0})</span>
          </button>
          <button
            type="button"
            className={`quality-tab-btn ${activeTab === "processing" ? "active" : ""}`}
            onClick={() => setActiveTab("processing")}
          >
            <Workflow size={14} />
            <span>Processing Executions ({data?.processing_runs.length ?? 0})</span>
          </button>
        </div>

        {/* Tab 1: Harmonization Runs */}
        {activeTab === "harmonization" && (
          <div className="historical-table-panel">
            <div className="table-responsive">
              <table className="historical-data-table">
                <thead>
                  <tr>
                    <th>RUN ID</th>
                    <th>VERSION</th>
                    <th>CONFIG PROFILE</th>
                    <th>STARTED (UTC)</th>
                    <th>DURATION</th>
                    <th>STATUS</th>
                    <th>INPUTS</th>
                    <th>CANDIDATES</th>
                    <th>EDGES</th>
                    <th>CLUSTERS</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {(!data || data.harmonization_runs.length === 0) && (
                    <tr>
                      <td colSpan={11} className="empty-table-cell">
                        No harmonization runs found matching the active filter criteria.
                      </td>
                    </tr>
                  )}
                  {data?.harmonization_runs.map((r) => (
                    <tr
                      key={r.run_id}
                      className={selectedHarmRun?.run_id === r.run_id ? "row-selected" : ""}
                      onClick={() => setSelectedHarmRun(r)}
                    >
                      <td className="font-mono text-bold">{r.run_id}</td>
                      <td>
                        <span className="badge-outline">{r.algorithm_version}</span>
                      </td>
                      <td className="font-mono text-muted">{r.config_id}</td>
                      <td>{r.started_at_utc ? r.started_at_utc.replace("T", " ").slice(0, 19) : "—"}</td>
                      <td>{r.duration_seconds > 0 ? `${r.duration_seconds}s` : "—"}</td>
                      <td>
                        <span
                          className="status-pill"
                          style={{
                            color: statusColor(r.status),
                            borderColor: statusColor(r.status),
                            backgroundColor: `${statusColor(r.status)}18`,
                          }}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td>{r.input_count.toLocaleString()}</td>
                      <td>{r.candidate_count.toLocaleString()}</td>
                      <td className="text-bold">{r.correspondence_edge_count.toLocaleString()}</td>
                      <td>{r.activity_cluster_count.toLocaleString()}</td>
                      <td>
                        <button
                          type="button"
                          className="table-action-pill-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedHarmRun(r);
                          }}
                        >
                          Inspect Details &rarr;
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 2: Ingestion History */}
        {activeTab === "ingestion" && (
          <div className="historical-table-panel">
            <div className="table-responsive">
              <table className="historical-data-table">
                <thead>
                  <tr>
                    <th>INGESTION ID</th>
                    <th>SOURCE TYPE</th>
                    <th>START TIME (UTC)</th>
                    <th>END TIME (UTC)</th>
                    <th>DURATION</th>
                    <th>STATUS</th>
                    <th>LINKED SOURCE FILES</th>
                  </tr>
                </thead>
                <tbody>
                  {(!data || data.ingestion_runs.length === 0) && (
                    <tr>
                      <td colSpan={7} className="empty-table-cell">
                        No ingestion execution logs found.
                      </td>
                    </tr>
                  )}
                  {data?.ingestion_runs.map((ir) => (
                    <tr key={ir.ingestion_id}>
                      <td className="font-mono">{ir.ingestion_id}</td>
                      <td className="text-bold">{ir.source_type}</td>
                      <td>{ir.start_time ? ir.start_time.replace("T", " ").slice(0, 19) : "—"}</td>
                      <td>{ir.end_time ? ir.end_time.replace("T", " ").slice(0, 19) : "In Progress"}</td>
                      <td>{ir.duration_seconds != null ? `${ir.duration_seconds}s` : "—"}</td>
                      <td>
                        <span
                          className="status-pill"
                          style={{
                            color: statusColor(ir.status),
                            borderColor: statusColor(ir.status),
                            backgroundColor: `${statusColor(ir.status)}18`,
                          }}
                        >
                          {ir.status}
                        </span>
                      </td>
                      <td>{ir.files_count} file(s) ingested</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 3: Source Files Overview */}
        {activeTab === "source_files" && (
          <div className="historical-table-panel">
            <div className="table-responsive">
              <table className="historical-data-table">
                <thead>
                  <tr>
                    <th>FILE ID</th>
                    <th>FILENAME</th>
                    <th>PLATFORM</th>
                    <th>PRODUCT VERSION</th>
                    <th>RETRIEVAL TIME</th>
                    <th>SHA-256 CHECKSUM</th>
                    <th>INGESTION ID</th>
                  </tr>
                </thead>
                <tbody>
                  {(!data || data.source_files_overview.length === 0) && (
                    <tr>
                      <td colSpan={7} className="empty-table-cell">
                        No source file records cataloged.
                      </td>
                    </tr>
                  )}
                  {data?.source_files_overview.map((sf) => (
                    <tr key={sf.file_id}>
                      <td className="font-mono">{sf.file_id}</td>
                      <td className="font-mono text-bold">{sf.filename}</td>
                      <td>
                        <span className="badge-satellite">{sf.platform}</span>
                      </td>
                      <td>{sf.product_version}</td>
                      <td>{sf.retrieval_time ? sf.retrieval_time.replace("T", " ").slice(0, 19) : "—"}</td>
                      <td className="font-mono text-muted text-truncate" style={{ maxWidth: 180 }}>
                        {sf.checksum}
                      </td>
                      <td className="font-mono">{sf.ingestion_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 4: Processing Runs */}
        {activeTab === "processing" && (
          <div className="historical-table-panel">
            <div className="table-responsive">
              <table className="historical-data-table">
                <thead>
                  <tr>
                    <th>PROCESSING ID</th>
                    <th>INPUT FILE ID</th>
                    <th>FILENAME</th>
                    <th>PLATFORM</th>
                    <th>VERSION</th>
                    <th>EXECUTION TIME</th>
                    <th>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {(!data || data.processing_runs.length === 0) && (
                    <tr>
                      <td colSpan={7} className="empty-table-cell">
                        No processing executions recorded.
                      </td>
                    </tr>
                  )}
                  {data?.processing_runs.map((pr) => (
                    <tr key={pr.processing_id}>
                      <td className="font-mono">{pr.processing_id}</td>
                      <td className="font-mono">{pr.input_file_id}</td>
                      <td className="font-mono text-bold">{pr.filename}</td>
                      <td>
                        <span className="badge-satellite">{pr.platform}</span>
                      </td>
                      <td>{pr.processing_version}</td>
                      <td>{pr.start_time ? pr.start_time.replace("T", " ").slice(0, 19) : "—"}</td>
                      <td>
                        <span
                          className="status-pill"
                          style={{
                            color: statusColor(pr.status),
                            borderColor: statusColor(pr.status),
                            backgroundColor: `${statusColor(pr.status)}18`,
                          }}
                        >
                          {pr.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* 8. Selected Harmonization Run Detail Modal */}
      {selectedHarmRun && (
        <div className="modal-backdrop" onClick={() => setSelectedHarmRun(null)}>
          <div className="modal-card pipeline-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <Workflow size={18} />
                <h3>Execution Run Details: {selectedHarmRun.run_id}</h3>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedHarmRun(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              {/* Failure Alert Banner if Failed */}
              {selectedHarmRun.status === "FAILED" && (
                <div className="pipeline-failed-alert">
                  <AlertTriangle size={18} />
                  <div>
                    <strong>Failed Stage: {selectedHarmRun.failed_stage || "Pipeline Execution"}</strong>
                    <p>{selectedHarmRun.error_summary || "An unexpected error aborted execution."}</p>
                  </div>
                </div>
              )}

              {/* Status and Version Strip */}
              <div className="modal-meta-strip">
                <div className="meta-strip-item">
                  <span className="meta-label">STATUS</span>
                  <span
                    className="status-pill"
                    style={{
                      color: statusColor(selectedHarmRun.status),
                      borderColor: statusColor(selectedHarmRun.status),
                      backgroundColor: `${statusColor(selectedHarmRun.status)}18`,
                    }}
                  >
                    {selectedHarmRun.status}
                  </span>
                </div>
                <div className="meta-strip-item">
                  <span className="meta-label">ALGORITHM VERSION</span>
                  <span className="meta-val font-mono">{selectedHarmRun.algorithm_version}</span>
                </div>
                <div className="meta-strip-item">
                  <span className="meta-label">CONFIGURATION PROFILE</span>
                  <span className="meta-val font-mono">{selectedHarmRun.config_id}</span>
                </div>
                <div className="meta-strip-item">
                  <span className="meta-label">DURATION</span>
                  <span className="meta-val">{selectedHarmRun.duration_seconds}s</span>
                </div>
              </div>

              {/* Telemetry Metrics Grid */}
              <div className="modal-metrics-grid">
                <div className="modal-metric-box">
                  <span className="m-box-label">INPUT DETECTIONS</span>
                  <span className="m-box-val">{selectedHarmRun.input_count.toLocaleString()}</span>
                  <span className="m-box-sub">From unified streams</span>
                </div>
                <div className="modal-metric-box">
                  <span className="m-box-label">CANDIDATE PAIRS</span>
                  <span className="m-box-val">{selectedHarmRun.candidate_count.toLocaleString()}</span>
                  <span className="m-box-sub">Within spatiotemporal window</span>
                </div>
                <div className="modal-metric-box">
                  <span className="m-box-label">CORRESPONDENCE EDGES</span>
                  <span className="m-box-val text-success">{selectedHarmRun.correspondence_edge_count.toLocaleString()}</span>
                  <span className="m-box-sub">Verified Strong + Possible matches</span>
                </div>
                <div className="modal-metric-box">
                  <span className="m-box-label">ACTIVITY CLUSTERS</span>
                  <span className="m-box-val">{selectedHarmRun.activity_cluster_count.toLocaleString()}</span>
                  <span className="m-box-sub">Multi-sensor fire complexes</span>
                </div>
              </div>

              {/* Timestamp Audit */}
              <div className="modal-timing-audit">
                <div className="timing-row">
                  <Clock size={14} />
                  <span>Started At: <strong>{selectedHarmRun.started_at_utc ? selectedHarmRun.started_at_utc.replace("T", " ") : "—"}</strong></span>
                </div>
                <div className="timing-row">
                  <CheckCircle2 size={14} />
                  <span>Finished At: <strong>{selectedHarmRun.finished_at_utc ? selectedHarmRun.finished_at_utc.replace("T", " ") : "In Progress"}</strong></span>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="modal-action-btn secondary"
                onClick={() => setSelectedHarmRun(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 9. Secure Pipeline Execution Modal */}
      {isTriggerModalOpen && (
        <div className="modal-backdrop" onClick={() => !isSubmittingJob && setIsTriggerModalOpen(false)}>
          <div className="modal-card pipeline-trigger-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <Play size={18} className="fill-icon" />
                <h3>Execute Harmonization Pipeline Job</h3>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => !isSubmittingJob && setIsTriggerModalOpen(false)}
                disabled={isSubmittingJob}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleTriggerJobSubmit}>
              <div className="modal-body">
                {/* Notification Banner */}
                {jobSubmitMessage && (
                  <div
                    className={jobSubmitMessage.error ? "pipeline-failed-alert" : "pipeline-success-alert"}
                  >
                    {jobSubmitMessage.error ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
                    <span>{jobSubmitMessage.text}</span>
                  </div>
                )}

                <p className="trigger-intro-text">
                  Configure execution parameters below. The job will be dispatched asynchronously via the server-side FastAPI worker queue with DuckDB concurrency locking.
                </p>

                {/* Stage Selection */}
                <div className="form-field-group">
                  <label>PIPELINE STAGE</label>
                  <select
                    value={triggerStage}
                    onChange={(e) => setTriggerStage(e.target.value)}
                    disabled={isSubmittingJob}
                  >
                    <option value="harmonization">Harmonization (MODIS &amp; VIIRS IoU)</option>
                    <option value="standardization">Standardization &amp; Unit Alignment</option>
                    <option value="ingestion">Ingestion (NASA FIRMS CSV Stream)</option>
                    <option value="full_pipeline">Full End-to-End Pipeline</option>
                  </select>
                </div>

                {/* Date Range Selection */}
                <div className="form-row-2col">
                  <div className="form-field-group">
                    <label>FROM DATE (OBSERVATION)</label>
                    <input
                      type="date"
                      value={triggerStartDate}
                      onChange={(e) => setTriggerStartDate(e.target.value)}
                      disabled={isSubmittingJob}
                    />
                  </div>
                  <div className="form-field-group">
                    <label>TO DATE (OBSERVATION)</label>
                    <input
                      type="date"
                      value={triggerEndDate}
                      onChange={(e) => setTriggerEndDate(e.target.value)}
                      disabled={isSubmittingJob}
                    />
                  </div>
                </div>

                {/* Configuration Profile */}
                <div className="form-field-group">
                  <label>CONFIGURATION PROFILE</label>
                  <select
                    value={triggerConfigId}
                    onChange={(e) => setTriggerConfigId(e.target.value)}
                    disabled={isSubmittingJob}
                  >
                    <option value="cfg_spatiotemporal_iou_v25">cfg_spatiotemporal_iou_v25 (Adaptive Polygon IoU &ge; 0.20)</option>
                    <option value="cfg_strict_spatial_threshold">cfg_strict_spatial_threshold (&le; 2.0 km Nadir Proximity)</option>
                    <option value="cfg_rapid_revisit_noaa">cfg_rapid_revisit_noaa (NOAA-20/21 Diurnal Priority)</option>
                  </select>
                </div>

                {/* Algorithm Version */}
                <div className="form-field-group">
                  <label>ALGORITHM VERSION</label>
                  <select
                    value={triggerAlgVersion}
                    onChange={(e) => setTriggerAlgVersion(e.target.value)}
                    disabled={isSubmittingJob}
                  >
                    <option value="v2.5">v2.5 (Harmonized Footprint Projection)</option>
                    <option value="v2.4">v2.4 (Adaptive Thresholds Baseline)</option>
                  </select>
                </div>

                {/* Dry Run Toggle */}
                <div className="form-checkbox-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={triggerDryRun}
                      onChange={(e) => setTriggerDryRun(e.target.checked)}
                      disabled={isSubmittingJob}
                    />
                    <span>Dry Run (Simulate execution telemetry without committing permanent database records)</span>
                  </label>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="modal-action-btn secondary"
                  onClick={() => setIsTriggerModalOpen(false)}
                  disabled={isSubmittingJob}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="modal-action-btn primary"
                  disabled={isSubmittingJob}
                >
                  {isSubmittingJob ? (
                    <>
                      <RefreshCw size={14} className="spin" />
                      <span>Initiating Job...</span>
                    </>
                  ) : (
                    <>
                      <Play size={14} className="fill-icon" />
                      <span>Launch Pipeline Execution</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
