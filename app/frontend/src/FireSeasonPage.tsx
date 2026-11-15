import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  BarChart3,
  CalendarDays,
  Flame,
  RefreshCw,
  SlidersHorizontal,
  TrendingUp,
} from "lucide-react";
import {
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

type Metric =
  | "detections"
  | "mean_frp"
  | "median_frp"
  | "total_frp"
  | "activity_clusters";
type SeasonMode = "all" | "month" | "window";

type MetricRow = {
  detections: number;
  frp_observations: number;
  mean_frp: number | null;
  median_frp: number | null;
  total_frp: number | null;
  activity_clusters: number | null;
};
type MonthlyRow = MetricRow & { year: number; month: number };
type RegionalMonthlyRow = MonthlyRow & { region: string };
type FireSeasonData = {
  generated_at: string;
  available_years: number[];
  available_platforms: string[];
  monthly: MonthlyRow[];
  climatology: Array<MetricRow & { month: number }>;
  annual: Array<MetricRow & { year: number }>;
  regional_activity: RegionalMonthlyRow[];
  regional_climatology: Array<
    MetricRow & { region: string; month: number; climatology_years: number }
  >;
  sensor_monthly: Array<{
    sensor: string;
    year: number;
    month: number;
    detections: number;
  }>;
  sensor_climatology: Array<{
    sensor: string;
    month: number;
    detections: number;
  }>;
  capabilities: {
    frp: boolean;
    daynight: boolean;
    geographic_regions: boolean;
    activity_clusters: boolean;
    climatology_years: number;
  };
  sources: {
    detection_metrics: string;
    cluster_metrics: string | null;
    regional_method: string;
  };
};
type Filters = {
  platform: string;
  region: string;
  daynight: string;
};

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const MONTH_OPTIONS = MONTHS.map((month, index) => [String(index + 1), month]);
const REGIONS = [
  ["global", "Global"],
  ["africa", "Africa"],
  ["asia", "Asia"],
  ["europe", "Europe"],
  ["north-america", "North America"],
  ["oceania", "Oceania"],
  ["south-america", "South America"],
];
const REGION_NAMES: Record<string, string> = {
  africa: "Africa",
  asia: "Asia",
  europe: "Europe",
  "north-america": "North America",
  oceania: "Oceania",
  "south-america": "South America",
  other: "Other / unclassified",
};
const REGIONAL_ORDER = [
  "africa",
  "asia",
  "europe",
  "north-america",
  "oceania",
  "south-america",
  "other",
];
const METRICS: Array<[Metric, string, string]> = [
  ["detections", "Detection count", "detections"],
  ["mean_frp", "Mean FRP", "MW"],
  ["median_frp", "Median FRP", "MW"],
  ["total_frp", "Total FRP", "MW"],
  ["activity_clusters", "Activity clusters", "clusters"],
];

function apiUrl(filters: Filters) {
  const params = new URLSearchParams({
    platform: filters.platform,
    region: filters.region,
    daynight: filters.daynight,
  });
  const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  return `${base}/api/fire-season?${params}`;
}

function formatNumber(value: number | null | undefined, maximumFractionDigits = 1) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(value);
}

function metricValue(
  row:
    | Pick<
        MetricRow,
        "detections" | "mean_frp" | "median_frp" | "total_frp" | "activity_clusters"
      >
    | undefined,
  metric: Metric,
): number | null {
  if (!row) return null;
  if (metric === "mean_frp") return row.mean_frp;
  if (metric === "median_frp") return row.median_frp;
  if (metric === "total_frp") return row.total_frp;
  if (metric === "activity_clusters") return row.activity_clusters;
  return row.detections;
}

function metricLabel(metric: Metric) {
  return METRICS.find(([value]) => value === metric)?.[1] ?? "Detection count";
}

function dateLabel(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function inWindow(month: number, startMonth: number, endMonth: number) {
  return startMonth <= endMonth
    ? month >= startMonth && month <= endMonth
    : month >= startMonth || month <= endMonth;
}

function FireSeasonPage() {
  const [filters, setFilters] = useState<Filters>({
    platform: "all",
    region: "global",
    daynight: "all",
  });
  const [data, setData] = useState<FireSeasonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [year, setYear] = useState("all");
  const [metric, setMetric] = useState<Metric>("detections");
  const [seasonMode, setSeasonMode] = useState<SeasonMode>("all");
  const [selectedMonth, setSelectedMonth] = useState(1);
  const [seasonStart, setSeasonStart] = useState(1);
  const [seasonEnd, setSeasonEnd] = useState(12);

  const updateFilter = useCallback((key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(apiUrl(filters), { signal: controller.signal });
        let body: { detail?: string } & Partial<FireSeasonData>;
        try {
          body = await response.json();
        } catch {
          throw new Error(
            `Fire Season API returned HTTP ${response.status} with an invalid JSON response.`,
          );
        }
        if (!response.ok) {
          throw new Error(body.detail ?? "Fire season data could not be loaded.");
        }
        setData(body as FireSeasonData);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Fire season data could not be loaded.",
        );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [filters, refreshKey]);

  const years = data?.available_years ?? [];
  const effectiveMetric: Metric =
    metric === "mean_frp" || metric === "median_frp" || metric === "total_frp"
      ? data?.capabilities.frp
        ? metric
        : "detections"
      : metric === "activity_clusters" && !data?.capabilities.activity_clusters
        ? "detections"
        : metric;
  const yearCount = Math.max(1, data?.capabilities.climatology_years ?? 1);

  const monthlyData = useMemo(() => {
    const monthRows = new Map<number, MonthlyRow>();
    if (year === "all") {
      for (const row of data?.climatology ?? []) {
        const clusterTotal = (data?.monthly ?? [])
          .filter((monthly) => monthly.month === row.month)
          .reduce((sum, monthly) => sum + (monthly.activity_clusters ?? 0), 0);
        monthRows.set(row.month, {
          ...row,
          year: 0,
          detections: row.detections / yearCount,
          total_frp: row.total_frp == null ? null : row.total_frp / yearCount,
          activity_clusters:
            data?.capabilities.activity_clusters
              ? clusterTotal / yearCount
              : null,
        });
      }
    } else {
      for (const row of data?.monthly ?? []) {
        if (row.year === Number(year)) monthRows.set(row.month, row);
      }
    }
    return MONTHS.map((_month, index) => {
      const month = index + 1;
      const row = monthRows.get(month);
      return {
        month,
        label: MONTHS[index],
        detections: row?.detections ?? 0,
        mean_frp: row?.mean_frp ?? null,
        median_frp: row?.median_frp ?? null,
        total_frp: row?.total_frp ?? null,
        activity_clusters: row?.activity_clusters ?? null,
      };
    });
  }, [data, year, yearCount]);

  const regionalData = useMemo(() => {
    const byRegionMonth = new Map<string, RegionalMonthlyRow | (MetricRow & { region: string; month: number })>();
    if (year === "all") {
      for (const row of data?.regional_climatology ?? []) {
        byRegionMonth.set(`${row.region}-${row.month}`, {
          ...row,
          detections: row.detections / Math.max(1, row.climatology_years),
          total_frp:
            row.total_frp == null
              ? null
              : row.total_frp / Math.max(1, row.climatology_years),
        });
      }
    } else {
      for (const row of data?.regional_activity ?? []) {
        if (row.year === Number(year)) {
          byRegionMonth.set(`${row.region}-${row.month}`, row);
        }
      }
    }

    return MONTHS.map((_month, index) => {
      const month = index + 1;
      const values: Record<string, string | number | null> = {
        month,
        label: MONTHS[index],
      };
      for (const region of REGIONAL_ORDER) {
        values[region] = metricValue(
          byRegionMonth.get(`${region}-${month}`),
          effectiveMetric,
        );
      }
      return values;
    });
  }, [data, effectiveMetric, year]);

  const sensorData = useMemo(() => {
    const sensorNames = [
      ...new Set([
        ...(data?.sensor_monthly ?? []).map((row) => row.sensor),
        ...(data?.sensor_climatology ?? []).map((row) => row.sensor),
      ]),
    ].sort();
    const rowsBySensorMonth = new Map<string, number>();
    if (year === "all") {
      for (const row of data?.sensor_climatology ?? []) {
        rowsBySensorMonth.set(
          `${row.sensor}-${row.month}`,
          row.detections / yearCount,
        );
      }
    } else {
      for (const row of data?.sensor_monthly ?? []) {
        if (row.year === Number(year)) {
          rowsBySensorMonth.set(`${row.sensor}-${row.month}`, row.detections);
        }
      }
    }
    return {
      sensorNames,
      rows: MONTHS.map((_month, index) => {
        const month = index + 1;
        const values: Record<string, string | number | null> = {
          month,
          label: MONTHS[index],
        };
        for (const sensor of sensorNames) {
          values[sensor] = rowsBySensorMonth.get(`${sensor}-${month}`) ?? 0;
        }
        return values;
      }),
    };
  }, [data, year, yearCount]);

  const heatmap = useMemo(() => {
    const max = Math.max(1, ...(data?.monthly ?? []).map((row) => row.detections));
    const rows = [...years].reverse().map((availableYear) => {
      const months = new Map(
        (data?.monthly ?? [])
          .filter((row) => row.year === availableYear)
          .map((row) => [row.month, row.detections]),
      );
      return {
        year: availableYear,
        cells: MONTHS.map((_month, index) => {
          const month = index + 1;
          const value = months.get(month) ?? 0;
          return {
            month,
            value,
            intensity: value === 0 ? 0 : 0.18 + 0.78 * Math.sqrt(value / max),
          };
        }),
      };
    });
    return { max, rows };
  }, [data?.monthly, years]);

  const seasonMonths = (month: number) => {
    if (seasonMode === "all") return true;
    if (seasonMode === "month") return month === selectedMonth;
    return inWindow(month, seasonStart, seasonEnd);
  };
  const selectedMonths = monthlyData.filter((row) => seasonMonths(row.month));
  const selectedSeasonDetections = selectedMonths.reduce(
    (sum, row) => sum + row.detections,
    0,
  );
  const peakMonths = [...monthlyData]
    .filter((row) => (metricValue(row, effectiveMetric) ?? 0) > 0)
    .sort(
      (left, right) =>
        (metricValue(right, effectiveMetric) ?? 0) -
        (metricValue(left, effectiveMetric) ?? 0),
    )
    .slice(0, 3);
  const topMonth = peakMonths[0];
  const monthLabel =
    seasonMode === "all"
      ? "All months"
      : seasonMode === "month"
        ? MONTHS[selectedMonth - 1]
        : `${MONTHS[seasonStart - 1]}–${MONTHS[seasonEnd - 1]}`;
  const hasAnnualData = (data?.annual.length ?? 0) > 0;
  const dataRange = years.length
    ? `${years[0]}–${years[years.length - 1]}`
    : "—";

  const chooseHeatmapCell = (targetYear: number, month: number) => {
    setYear(String(targetYear));
    setSeasonMode("month");
    setSelectedMonth(month);
  };

  return (
    <>
      <section className="page-heading season-heading">
        <div>
          <div className="eyebrow"><span /> LONG-TERM FIRE ACTIVITY</div>
          <h1>Fire season monitor</h1>
          <p className="page-subtitle">
            Explore when and where satellite-observed fire activity rises across years.
          </p>
        </div>
        <button
          className={`refresh-button ${loading ? "is-loading" : ""}`}
          type="button"
          onClick={() => setRefreshKey((key) => key + 1)}
          disabled={loading}
        >
          <RefreshCw size={15} />
          <span>Refresh data</span>
        </button>
      </section>

      <section className="season-filter-panel" aria-label="Fire season filters">
        <div className="season-filter-heading">
          <SlidersHorizontal size={15} />
          <span>Season analysis filters</span>
        </div>
        <label className="season-filter">
          <span>YEAR</span>
          <select value={year} onChange={(event) => setYear(event.target.value)} disabled={!years.length}>
            <option value="all">All years · seasonal average</option>
            {[...years].reverse().map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
        </label>
        <label className="season-filter">
          <span>SEASON / MONTH</span>
          <select
            value={seasonMode}
            onChange={(event) => setSeasonMode(event.target.value as SeasonMode)}
          >
            <option value="all">All months</option>
            <option value="month">Investigate one month</option>
            <option value="window">Define a season window</option>
          </select>
        </label>
        {seasonMode === "month" && (
          <label className="season-filter">
            <span>MONTH OF INTEREST</span>
            <select
              value={selectedMonth}
              onChange={(event) => setSelectedMonth(Number(event.target.value))}
            >
              {MONTH_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
        )}
        {seasonMode === "window" && (
          <>
            <label className="season-filter">
              <span>SEASON START</span>
              <select
                value={seasonStart}
                onChange={(event) => setSeasonStart(Number(event.target.value))}
              >
                {MONTH_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
              </select>
            </label>
            <label className="season-filter">
              <span>SEASON END</span>
              <select
                value={seasonEnd}
                onChange={(event) => setSeasonEnd(Number(event.target.value))}
              >
                {MONTH_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
              </select>
            </label>
          </>
        )}
        <label className="season-filter">
          <span>GEOGRAPHIC REGION</span>
          <select
            value={filters.region}
            onChange={(event) => updateFilter("region", event.target.value)}
            disabled={data != null && !data.capabilities.geographic_regions}
          >
            {REGIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
        </label>
        <label className="season-filter">
          <span>SATELLITE / PLATFORM</span>
          <select value={filters.platform} onChange={(event) => updateFilter("platform", event.target.value)}>
            <option value="all">All platforms</option>
            <option value="terra">Terra</option>
            <option value="aqua">Aqua</option>
            <option value="noaa20">NOAA-20</option>
            <option value="noaa21">NOAA-21</option>
            <option value="modis">MODIS</option>
            <option value="viirs">VIIRS</option>
          </select>
        </label>
        <label className="season-filter">
          <span>DAY / NIGHT</span>
          <select
            value={filters.daynight}
            onChange={(event) => updateFilter("daynight", event.target.value)}
            disabled={data != null && !data.capabilities.daynight}
          >
            <option value="all">All observations</option>
            <option value="day">Day</option>
            <option value="night">Night</option>
          </select>
        </label>
        <label className="season-filter season-metric-filter">
          <span>METRIC</span>
          <select
            value={effectiveMetric}
            onChange={(event) => setMetric(event.target.value as Metric)}
          >
            {METRICS.map(([value, label]) => (
              <option
                value={value}
                key={value}
                disabled={
                  (value !== "detections" && value !== "activity_clusters" && data != null && !data.capabilities.frp) ||
                  (value === "activity_clusters" && data != null && !data.capabilities.activity_clusters)
                }
              >
                {label}
              </option>
            ))}
          </select>
        </label>
      </section>

      {seasonMode === "window" && (
        <p className="season-window-note">
          Season window: <strong>{monthLabel}</strong>
          {seasonStart > seasonEnd && " · spans the end of one calendar year"}
          {" "}— selected months are highlighted; the full annual cycle remains visible.
        </p>
      )}

      {error && (
        <div className="season-error" role="alert">
          <AlertCircle size={17} />
          <div>
            <strong>Season data unavailable</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      {data && (
        <>
          <section className="season-summary" aria-label="Season overview">
            <article className="season-summary-card">
              <span className="season-summary-icon"><CalendarDays size={16} /></span>
              <span>DATA COVERAGE</span>
              <strong>{dataRange}</strong>
              <small>{years.length} available observation years</small>
            </article>
            <article className="season-summary-card">
              <span className="season-summary-icon"><Flame size={16} /></span>
              <span>PEAK {metricLabel(effectiveMetric).toUpperCase()}</span>
              <strong>{topMonth ? MONTHS[topMonth.month - 1] : "—"}</strong>
              <small>{formatNumber(metricValue(topMonth, effectiveMetric))} · {year === "all" ? "seasonal average" : year}</small>
            </article>
            <article className="season-summary-card">
              <span className="season-summary-icon"><Activity size={16} /></span>
              <span>{monthLabel.toUpperCase()} ACTIVITY</span>
              <strong>{formatNumber(selectedSeasonDetections)}</strong>
              <small>{year === "all" ? "average detections per year" : `detections in ${year}`}</small>
            </article>
            <article className="season-summary-card">
              <span className="season-summary-icon"><TrendingUp size={16} /></span>
              <span>REGION</span>
              <strong>{REGIONS.find(([value]) => value === filters.region)?.[1] ?? "Global"}</strong>
              <small>{filters.platform === "all" ? "All satellites / platforms" : filters.platform.toUpperCase()}</small>
            </article>
          </section>

          {!hasAnnualData && !loading && (
            <div className="season-empty" role="status">
              <BarChart3 size={22} />
              <strong>No detections match these filters.</strong>
              <span>Choose another region, platform, or day/night selection.</span>
            </div>
          )}

          {hasAnnualData && (
            <>
              <div className="season-chart-grid">
                <section className="season-chart-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Monthly {metricLabel(effectiveMetric).toLowerCase()}</h2>
                      <p>
                        {year === "all"
                          ? `Average by calendar month across ${yearCount} available years`
                          : `Calendar-month activity in ${year}`}
                      </p>
                    </div>
                    <span className="season-panel-tag">{filters.region.toUpperCase()}</span>
                  </div>
                  <div className="season-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={monthlyData} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                        <CartesianGrid stroke="#30362c" strokeDasharray="3 4" vertical={false} />
                        <XAxis dataKey="label" tick={{ fill: "#a0a596", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis
                          allowDecimals={effectiveMetric !== "detections" && effectiveMetric !== "activity_clusters"}
                          tick={{ fill: "#a0a596", fontSize: 9 }}
                          axisLine={false}
                          tickLine={false}
                          width={42}
                        />
                        <Tooltip
                          cursor={{ fill: "#f5820012" }}
                          contentStyle={{ background: "#20241d", border: "1px solid #3a4035", borderRadius: 8 }}
                          labelStyle={{ color: "#f3efe7" }}
                          itemStyle={{ color: "#f5a044" }}
                          formatter={(value) => [formatNumber(Number(value)), metricLabel(effectiveMetric)]}
                        />
                        <Bar dataKey={effectiveMetric} name={metricLabel(effectiveMetric)} radius={[4, 4, 0, 0]} maxBarSize={31}>
                          {monthlyData.map((row) => (
                            <Cell
                              key={row.month}
                              fill={seasonMonths(row.month) ? "#f58200" : "#80542f"}
                              fillOpacity={seasonMonths(row.month) ? 0.95 : 0.58}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </section>

                <section className="season-chart-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Monthly FRP trend</h2>
                      <p>Mean and median fire radiative power · MW</p>
                    </div>
                    <span className="season-panel-tag">MW</span>
                  </div>
                  {data.capabilities.frp ? (
                    <>
                      <div className="season-chart">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={monthlyData} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                            <CartesianGrid stroke="#30362c" strokeDasharray="3 4" vertical={false} />
                            <XAxis dataKey="label" tick={{ fill: "#a0a596", fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis tick={{ fill: "#a0a596", fontSize: 9 }} axisLine={false} tickLine={false} width={42} />
                            <Tooltip
                              contentStyle={{ background: "#20241d", border: "1px solid #3a4035", borderRadius: 8 }}
                              labelStyle={{ color: "#f3efe7" }}
                              formatter={(value) => [`${formatNumber(Number(value))} MW`, ""]}
                            />
                            <Legend wrapperStyle={{ color: "#c5c6b8", fontSize: 9 }} />
                            <Line type="monotone" dataKey="mean_frp" name="Mean FRP" stroke="#f58200" strokeWidth={2} dot={{ r: 3, fill: "#f58200" }} connectNulls />
                            <Line type="monotone" dataKey="median_frp" name="Median FRP" stroke="#80a66f" strokeWidth={2} dot={{ r: 3, fill: "#80a66f" }} connectNulls />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="season-frp-note">
                        FRP summarizes satellite-observed radiant energy; it is not a direct measure of threat to people.
                      </div>
                    </>
                  ) : (
                    <div className="season-chart-unavailable">
                      FRP fields are not available in this database schema.
                    </div>
                  )}
                </section>

                <section className="season-chart-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Year-over-year comparison</h2>
                      <p>{metricLabel(effectiveMetric)} by year · {filters.region}</p>
                    </div>
                    <span className="season-panel-tag">ANNUAL</span>
                  </div>
                  <div className="season-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.annual} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                        <CartesianGrid stroke="#30362c" strokeDasharray="3 4" vertical={false} />
                        <XAxis dataKey="year" tick={{ fill: "#a0a596", fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis
                          allowDecimals={effectiveMetric !== "detections" && effectiveMetric !== "activity_clusters"}
                          tick={{ fill: "#a0a596", fontSize: 9 }}
                          axisLine={false}
                          tickLine={false}
                          width={42}
                        />
                        <Tooltip
                          contentStyle={{ background: "#20241d", border: "1px solid #3a4035", borderRadius: 8 }}
                          labelStyle={{ color: "#f3efe7" }}
                          formatter={(value) => [formatNumber(Number(value)), metricLabel(effectiveMetric)]}
                        />
                        <Bar dataKey={effectiveMetric} name={metricLabel(effectiveMetric)} fill="#e9b77e" radius={[4, 4, 0, 0]} maxBarSize={36} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </section>

                <section className="season-heatmap-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Month × year activity</h2>
                      <p>Detection-count heatmap · select a cell to inspect that month</p>
                    </div>
                    <span className="season-panel-tag">{filters.region.toUpperCase()}</span>
                  </div>
                  <div className="season-heatmap-scroll">
                    <div className="season-heatmap" role="grid" aria-label="Monthly detections by year">
                      <span className="season-heatmap-corner" />
                      {MONTHS.map((month) => <span className="season-heatmap-month" key={month}>{month}</span>)}
                      {heatmap.rows.map((row) => (
                        <div className="season-heatmap-row" role="row" key={row.year}>
                          <span className="season-heatmap-year" role="rowheader">{row.year}</span>
                          {row.cells.map((cell) => (
                            <button
                              className={`season-heatmap-cell ${year === String(row.year) && seasonMode === "month" && selectedMonth === cell.month ? "is-selected" : ""}`}
                              type="button"
                              key={cell.month}
                              style={{
                                backgroundColor: cell.value
                                  ? `rgba(245, 130, 0, ${cell.intensity})`
                                  : "#20251e",
                              }}
                              title={`${MONTHS[cell.month - 1]} ${row.year}: ${formatNumber(cell.value)} detections`}
                              aria-label={`${MONTHS[cell.month - 1]} ${row.year}: ${formatNumber(cell.value)} detections`}
                              onClick={() => chooseHeatmapCell(row.year, cell.month)}
                            >
                              {cell.value ? formatNumber(cell.value, 0) : ""}
                            </button>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="season-heatmap-legend">
                    <span>Fewer detections</span><i className="heat-low" /><i className="heat-mid" /><i className="heat-high" /><span>More</span>
                  </div>
                </section>

                <section className="season-chart-panel season-regional-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Regional seasonal activity</h2>
                      <p>
                        {year === "all"
                          ? `Monthly seasonal averages · ${filters.platform === "all" ? "all platforms" : filters.platform.toUpperCase()}`
                          : `Monthly activity in ${year} · ${metricLabel(effectiveMetric).toLowerCase()}`}
                      </p>
                    </div>
                    <span className="season-panel-tag">REGIONAL</span>
                  </div>
                  {data.capabilities.geographic_regions ? (
                    <>
                      <div className="season-chart">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={regionalData} margin={{ top: 10, right: 15, left: -18, bottom: 0 }}>
                            <CartesianGrid stroke="#30362c" strokeDasharray="3 4" vertical={false} />
                            <XAxis dataKey="label" tick={{ fill: "#a0a596", fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis
                              allowDecimals={effectiveMetric !== "detections" && effectiveMetric !== "activity_clusters"}
                              tick={{ fill: "#a0a596", fontSize: 9 }}
                              axisLine={false}
                              tickLine={false}
                              width={42}
                            />
                            <Tooltip
                              contentStyle={{ background: "#20241d", border: "1px solid #3a4035", borderRadius: 8 }}
                              labelStyle={{ color: "#f3efe7" }}
                              formatter={(value, name) => [formatNumber(Number(value)), REGION_NAMES[String(name)] ?? String(name)]}
                            />
                            <Legend
                              wrapperStyle={{ color: "#c5c6b8", fontSize: 8 }}
                              formatter={(value) => REGION_NAMES[String(value)] ?? String(value)}
                            />
                            {REGIONAL_ORDER.map((region, index) => (
                              <Line
                                key={region}
                                type="monotone"
                                dataKey={region}
                                name={region}
                                stroke={["#f58200", "#80a66f", "#e9b77e", "#d92d1f", "#7fa7c9", "#bd8fc7", "#a0a596"][index]}
                                strokeWidth={region === filters.region ? 2.8 : 1.8}
                                dot={false}
                                connectNulls
                              />
                            ))}
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="season-frp-note">
                        Region comparison uses approximate dashboard bounding boxes and ignores the selected region filter.
                      </div>
                    </>
                  ) : (
                    <div className="season-chart-unavailable">
                      Latitude and longitude are required for regional comparisons.
                    </div>
                  )}
                </section>

                <section className="season-chart-panel season-sensor-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Sensor-specific seasonal differences</h2>
                      <p>
                        Monthly MODIS / VIIRS detection counts ·{" "}
                        {year === "all" ? "seasonal average" : year}
                      </p>
                    </div>
                    <span className="season-panel-tag">SENSOR</span>
                  </div>
                  {sensorData.sensorNames.length ? (
                    <div className="season-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={sensorData.rows} margin={{ top: 10, right: 15, left: -18, bottom: 0 }}>
                          <CartesianGrid stroke="#30362c" strokeDasharray="3 4" vertical={false} />
                          <XAxis dataKey="label" tick={{ fill: "#a0a596", fontSize: 10 }} axisLine={false} tickLine={false} />
                          <YAxis allowDecimals={year === "all"} tick={{ fill: "#a0a596", fontSize: 9 }} axisLine={false} tickLine={false} width={42} />
                          <Tooltip
                            contentStyle={{ background: "#20241d", border: "1px solid #3a4035", borderRadius: 8 }}
                            labelStyle={{ color: "#f3efe7" }}
                            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
                          />
                          <Legend wrapperStyle={{ color: "#c5c6b8", fontSize: 9 }} />
                          {sensorData.sensorNames.map((sensor, index) => (
                            <Line
                              key={sensor}
                              type="monotone"
                              dataKey={sensor}
                              name={sensor}
                              stroke={sensor === "MODIS" ? "#f58200" : sensor === "VIIRS" ? "#80a66f" : ["#e9b77e", "#7fa7c9", "#bd8fc7"][index % 3]}
                              strokeWidth={2}
                              dot={{ r: 3 }}
                              connectNulls
                            />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <div className="season-chart-unavailable">
                      Sensor labels could not be derived from this database.
                    </div>
                  )}
                  <div className="season-frp-note">
                    Sensor attribution uses available instrument/source labels; unclassified records are shown as Other.
                  </div>
                </section>

                <section className="season-peaks-panel">
                  <div className="season-panel-header">
                    <div>
                      <h2>Peak activity periods</h2>
                      <p>Highest months for {metricLabel(effectiveMetric).toLowerCase()}</p>
                    </div>
                    <span className="season-panel-tag">{year === "all" ? "AVERAGE" : year}</span>
                  </div>
                  <div className="season-peak-list">
                    {peakMonths.map((row, index) => {
                      const value = metricValue(row, effectiveMetric);
                      const maximum = Math.max(1, ...peakMonths.map((item) => metricValue(item, effectiveMetric) ?? 0));
                      return (
                        <div className="season-peak-row" key={row.month}>
                          <span className={`season-peak-rank ${index === 0 ? "is-first" : ""}`}>{String(index + 1).padStart(2, "0")}</span>
                          <span className="season-peak-month">{MONTHS[row.month - 1]}</span>
                          <span className="season-peak-track"><i style={{ width: `${Math.max(3, ((value ?? 0) / maximum) * 100)}%` }} /></span>
                          <strong>{formatNumber(value)}</strong>
                          {seasonMonths(row.month) && <span className="season-peak-in-window">IN SEASON</span>}
                        </div>
                      );
                    })}
                    {!peakMonths.length && (
                      <div className="season-chart-unavailable">No peak periods are available for this selection.</div>
                    )}
                  </div>
                  <div className="season-peak-footnote">
                    <Flame size={13} />
                    <span>
                      Season months follow your selection ({monthLabel}); peaks are inferred from the filtered observations, not a fixed calendar.
                    </span>
                  </div>
                </section>
              </div>

              <footer className="season-footer">
                <span>Detection and FRP metrics from {data.sources.detection_metrics}.</span>
                <span>
                  {data.sources.cluster_metrics
                    ? `Cluster counts from ${data.sources.cluster_metrics}.`
                    : "Activity-cluster counts are unavailable for this database."}
                </span>
                {data.generated_at && <span>Updated {dateLabel(data.generated_at)}</span>}
              </footer>
              <p className="season-method-note">
                {data.sources.regional_method} These regional comparisons are exploratory, not administrative boundaries or fire-danger assessments.
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}

export default FireSeasonPage;
