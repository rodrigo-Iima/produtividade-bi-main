const state = {
  data: null,
  viewKey: "bug",
  view: null,
  tickets: [],
  chart: null,
};

const numberFormat = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const preciseNumberFormat = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const monthFormat = new Intl.DateTimeFormat("pt-BR", {
  month: "short",
  timeZone: "UTC",
});

const dateFormat = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "America/Sao_Paulo",
});

const $ = (selector) => document.querySelector(selector);

function getDataUrl() {
  const requested = new URLSearchParams(window.location.search).get("data");
  if (requested) return requested;

  const isLocal = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const snapshotPath = isLocal
    ? `../outputs/okr_${today}.json`
    : "../outputs/latest.json";
  return new URL(snapshotPath, window.location.href).toString();
}

function formatHours(value, digits = 1) {
  if (!Number.isFinite(value)) return "—";
  const formatted = digits === 2
    ? preciseNumberFormat.format(value)
    : numberFormat.format(value);
  return `${formatted}h`;
}

function formatSignedHours(value) {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) < 0.005) return "0,0h";
  const sign = value > 0 ? "+" : "−";
  return `${sign}${formatHours(Math.abs(value))}`;
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${numberFormat.format(value)}%` : "—";
}

function formatMonth(value) {
  if (!value) return "—";
  const [year, month] = value.split("-");
  return monthFormat
    .format(new Date(Date.UTC(Number(year), Number(month) - 1, 1)))
    .replace(".", "");
}

function formatDate(value) {
  if (!value) return "—";
  return dateFormat.format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeText(value, fallback = "—") {
  const text = value === null || value === undefined || value === "" ? fallback : String(value);
  return escapeHtml(text);
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function periodMetric(period) {
  return state.view.periods.find((item) => item.period === period);
}

function ticketPeriod(ticket) {
  const month = ticket.created_at.slice(0, 7);
  if (month <= `${state.data.definition.year}-05`) return "baseline";
  if (month >= `${state.data.definition.year}-07`) return "current";
  return "excluded";
}

function trendTone(element, favorable) {
  element.classList.remove("is-favorable", "is-unfavorable");
  if (favorable === true) element.classList.add("is-favorable");
  if (favorable === false) element.classList.add("is-unfavorable");
}

function renderPercentTrend(selector, current, baseline, favorableDirection = null) {
  const element = $(selector);
  if (!element || !Number.isFinite(current) || !Number.isFinite(baseline) || baseline === 0) {
    if (element) element.textContent = "Sem comparação";
    return;
  }
  const delta = ((current - baseline) / Math.abs(baseline)) * 100;
  const arrow = delta > 0.05 ? "↑" : delta < -0.05 ? "↓" : "→";
  element.textContent = `${arrow} ${numberFormat.format(Math.abs(delta))}% vs base`;
  const favorable = favorableDirection === "lower"
    ? delta < 0
    : favorableDirection === "higher"
      ? delta > 0
      : null;
  trendTone(element, favorable);
}

function renderHoursTrend(selector, current, baseline, favorableDirection = null) {
  const element = $(selector);
  if (!element || !Number.isFinite(current) || !Number.isFinite(baseline)) {
    if (element) element.textContent = "Sem comparação";
    return;
  }
  const delta = current - baseline;
  const arrow = delta > 0.005 ? "↑" : delta < -0.005 ? "↓" : "→";
  element.textContent = `${arrow} ${formatHours(Math.abs(delta))} vs base`;
  const favorable = favorableDirection === "lower"
    ? delta < 0
    : favorableDirection === "higher"
      ? delta > 0
      : null;
  trendTone(element, favorable);
}

function renderSummary() {
  const viewLabel = state.view.label;
  const singularLabel = state.view.issue_type === "Bug" ? "Bug" : "Adaptativa";
  const completedWord = state.view.issue_type === "Bug" ? "concluídos" : "concluídas";
  const singularCompletedWord = state.view.issue_type === "Bug" ? "concluído" : "concluída";
  const baseline = periodMetric("baseline");
  const current = periodMetric("current");
  if (!baseline || !current) {
    throw new Error("Snapshot sem os períodos baseline/current. Execute o pipeline atualizado.");
  }

  setText("#actual-current", formatHours(current.avg_actual_hours));
  setText(
    "#actual-base",
    `Base: ${formatHours(baseline.avg_actual_hours)} · ${baseline.bugs_with_clockify} ${viewLabel}`,
  );
  renderPercentTrend(
    "#actual-trend",
    current.avg_actual_hours,
    baseline.avg_actual_hours,
    "lower",
  );

  setText("#estimate-current", formatHours(current.avg_estimate_hours));
  setText(
    "#estimate-base",
    `Base: ${formatHours(baseline.avg_estimate_hours)} · ${baseline.bugs_with_estimate} ${viewLabel}`,
  );
  renderPercentTrend(
    "#estimate-trend",
    current.avg_estimate_hours,
    baseline.avg_estimate_hours,
  );

  setText("#variation-current", formatSignedHours(current.avg_delta_hours));
  setText(
    "#variation-base",
    `Base: ${formatSignedHours(baseline.avg_delta_hours)} · gasto menos estimado`,
  );
  renderHoursTrend(
    "#variation-trend",
    current.avg_delta_hours,
    baseline.avg_delta_hours,
    "lower",
  );

  setText("#coverage-current", formatPercent(current.coverage_pct));
  setText(
    "#coverage-base",
    `Base: ${formatPercent(baseline.coverage_pct)} · ${baseline.bugs_with_clockify}/${baseline.bugs_in_jira} ${viewLabel}`,
  );
  const coverageDelta = current.coverage_pct - baseline.coverage_pct;
  const coverageTrend = $("#coverage-trend");
  coverageTrend.textContent = `${coverageDelta > 0 ? "↑" : coverageDelta < 0 ? "↓" : "→"} ${numberFormat.format(Math.abs(coverageDelta))} p.p. vs base`;
  trendTone(coverageTrend, coverageDelta > 0 ? true : coverageDelta < 0 ? false : null);

  const asOf = state.data.definition?.as_of_date;
  setText("#page-title", `Tempo de desenvolvimento em ${viewLabel.toLowerCase()} ${completedWord}`);
  document.title = `OKR · Tempo de desenvolvimento em ${viewLabel}`;
  setText("#tickets-title", `${viewLabel} ${completedWord} com lançamentos Dev`);
  setText("#ticket-ratio-heading", `${viewLabel} Dev / ${viewLabel} Jira`);
  setText("#snapshot-label", asOf ? `SNAPSHOT · ${formatDate(`${asOf}T12:00:00Z`)}` : "SNAPSHOT");
  setText(
    "#measurement-note",
    `Atual: ${current.bugs_with_clockify}/${current.bugs_in_jira} ${viewLabel} ${completedWord} com Dev · Base: ${baseline.bugs_with_clockify}/${baseline.bugs_in_jira} com Dev · Junho fora dos KPIs`,
  );
  setText(
    "#trend-subtitle",
    `Horas Clockify com tag Dev por ${singularLabel} ${singularCompletedWord} · linha de base real: ${formatHours(baseline.avg_actual_hours)} · junho visível e fora dos KPIs`,
  );
  setText(
    "#data-rule",
    `Gasto real = horas Clockify com tag Dev · Cobertura = ${viewLabel} com Dev / ${viewLabel} Jira do período.`,
  );
  setText(
    "#data-source",
    `${viewLabel}: ${current.matched_entries + baseline.matched_entries} lançamentos Dev mapeados · atualização ${formatDate(`${asOf}T12:00:00Z`)}`,
  );
}

function measurementMonths() {
  return [...state.view.monthly].sort((a, b) => a.month.localeCompare(b.month));
}

function renderChart() {
  const canvas = $("#monthly-chart");
  if (!canvas || !window.Chart) return;

  const baseline = periodMetric("baseline");
  const months = measurementMonths();
  state.chart?.destroy();
  state.chart = new window.Chart(canvas, {
    type: "line",
    data: {
      labels: months.map((item) => formatMonth(item.month)),
      datasets: [
        {
          label: "Estimado",
          data: months.map((item) => item.avg_estimate_hours),
          borderColor: "#8d8d87",
          backgroundColor: "#ffffff",
          borderWidth: 1.75,
          pointRadius: 3,
          pointHoverRadius: 5,
          pointBackgroundColor: "#ffffff",
          pointBorderColor: "#8d8d87",
          pointBorderWidth: 1.5,
          tension: 0.25,
          spanGaps: false,
        },
        {
          label: "Gasto real",
          data: months.map((item) => item.avg_actual_hours),
          borderColor: "#2746c7",
          backgroundColor: "#2746c7",
          borderWidth: 2.5,
          pointRadius: 3.5,
          pointHoverRadius: 5.5,
          pointBackgroundColor: "#2746c7",
          pointBorderColor: "#ffffff",
          pointBorderWidth: 1.25,
          tension: 0.25,
          spanGaps: false,
        },
        {
          label: "Base real",
          data: months.map(() => baseline.avg_actual_hours),
          borderColor: "#52524e",
          backgroundColor: "#52524e",
          borderWidth: 1.5,
          borderDash: [5, 5],
          pointRadius: 0,
          pointHoverRadius: 0,
          tension: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161616",
          titleColor: "#fff",
          bodyColor: "#fff",
          padding: 12,
          usePointStyle: true,
          callbacks: {
            label: (context) => `${context.dataset.label}: ${formatHours(context.raw)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: {
            color: "#686862",
            font: { family: "Geist Sans", size: 11 },
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: "#e2e2dc" },
          border: { display: false },
          ticks: {
            color: "#73736e",
            padding: 8,
            font: { family: "Geist Sans", size: 11 },
            callback: (value) => `${value}h`,
          },
        },
      },
    },
  });
}

function renderMonthlyTable() {
  const body = $("#monthly-body");
  const months = measurementMonths().reverse();
  body.innerHTML = months.map((item) => {
    const period = item.month <= `${state.data.definition.year}-05`
      ? "Base"
      : item.month >= `${state.data.definition.year}-07`
        ? "Atual"
        : "Fora KPI";
    const periodClass = period === "Atual"
      ? "atual"
      : period === "Base"
        ? "base"
        : "excluded";
    return `
      <tr>
        <td>${formatMonth(item.month)}</td>
        <td><span class="period-pill period-pill--${periodClass}">${period}</span></td>
        <td>${item.bugs_with_clockify} / ${item.bugs_in_jira}</td>
        <td>${formatPercent(item.coverage_pct)}</td>
        <td>${formatHours(item.avg_estimate_hours)}</td>
        <td>${formatHours(item.avg_actual_hours)}</td>
        <td>${formatSignedHours(item.avg_delta_hours)}</td>
      </tr>
    `;
  }).join("");
}

function populateMonthFilter() {
  const select = $("#month-filter");
  select.innerHTML = '<option value="all">Todos os meses</option>';
  const months = [...new Set(state.tickets.map((ticket) => ticket.created_at.slice(0, 7)))]
    .sort()
    .reverse();
  select.insertAdjacentHTML(
    "beforeend",
    months.map((month) => `<option value="${month}">${formatMonth(month)}</option>`).join(""),
  );
}

function filteredTickets() {
  const query = $("#ticket-search").value.trim().toLowerCase();
  const period = $("#period-filter").value;
  const month = $("#month-filter").value;
  const sort = $("#sort-select").value;

  const filtered = state.tickets.filter((ticket) => {
    const searchable = `${ticket.issue_key} ${ticket.summary}`.toLowerCase();
    const matchesQuery = !query || searchable.includes(query);
    const matchesPeriod = period === "all" || ticketPeriod(ticket) === period;
    const matchesMonth = month === "all" || ticket.created_at.slice(0, 7) === month;
    return matchesQuery && matchesPeriod && matchesMonth;
  });

  const sorted = [...filtered];
  sorted.sort((a, b) => {
    if (sort === "variation_desc") return (b.variation_hours ?? -Infinity) - (a.variation_hours ?? -Infinity);
    if (sort === "variation_asc") return (a.variation_hours ?? Infinity) - (b.variation_hours ?? Infinity);
    if (sort === "spent_desc") return (b.spent_hours ?? -Infinity) - (a.spent_hours ?? -Infinity);
    if (sort === "estimate_desc") return (b.estimate_hours ?? -Infinity) - (a.estimate_hours ?? -Infinity);
    if (sort === "issue_asc") return a.issue_key.localeCompare(b.issue_key);
    return new Date(b.created_at) - new Date(a.created_at);
  });
  return sorted;
}

function renderTickets() {
  const body = $("#tickets-body");
  const emptyState = $("#empty-state");
  const tickets = filteredTickets();
  const measuredWord = state.view.issue_type === "Bug" ? "medidos" : "medidas";
  setText("#ticket-count", `${tickets.length} de ${state.tickets.length} ${state.view.label.toLowerCase()} ${measuredWord}`);
  emptyState.hidden = tickets.length > 0;
  body.innerHTML = tickets.map((ticket) => `
    <tr>
      <td title="${safeText(ticket.summary, "")}">
        <div class="ticket-line">
          <span class="ticket-key">${safeText(ticket.issue_key)}</span>
          <span class="ticket-summary">${safeText(ticket.summary)}</span>
        </div>
      </td>
      <td>${formatDate(ticket.created_at)}</td>
      <td><span class="status" title="${safeText(ticket.status, "Sem status")}">${safeText(ticket.status, "Sem status")}</span></td>
      <td>${formatHours(ticket.estimate_hours, 2)}</td>
      <td>${formatHours(ticket.spent_hours, 2)}</td>
      <td>${formatSignedHours(ticket.variation_hours)}</td>
      <td>${ticket.clockify_entry_count}</td>
    </tr>
  `).join("");
}

function bindFilters() {
  ["#ticket-search", "#period-filter", "#month-filter", "#sort-select"].forEach((selector) => {
    $(selector).addEventListener("input", renderTickets);
    $(selector).addEventListener("change", renderTickets);
  });
  $("#period-filter").addEventListener("change", () => {
    $("#month-filter").value = "all";
    renderTickets();
  });
}

function setView(viewKey) {
  const view = state.data.views?.[viewKey];
  if (!view) throw new Error(`View não encontrada: ${viewKey}`);

  state.viewKey = viewKey;
  state.view = view;
  state.tickets = [...(view.tickets_with_clockify ?? [])]
    .filter((ticket) => ticketPeriod(ticket) !== "excluded");

  document.querySelectorAll("[data-view]").forEach((button) => {
    const isActive = button.dataset.view === viewKey;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  renderSummary();
  renderChart();
  renderMonthlyTable();
  populateMonthFilter();
  renderTickets();
}

function bindViewSelector() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
}

function showError(error) {
  const loadState = $("#load-state");
  loadState.classList.add("is-error");
  loadState.querySelector(".eyebrow").textContent = "SNAPSHOT INCOMPATÍVEL";
  loadState.querySelector("p").textContent = error.message
    || "Execute o pipeline atualizado antes de abrir a view.";
  console.error(error);
}

async function init() {
  try {
    const response = await fetch(getDataUrl(), { cache: "no-store" });
    if (!response.ok) throw new Error(`Snapshot indisponível: ${response.status}`);
    state.data = await response.json();
    if (state.data.definition?.clockify_required_tag !== "Dev") {
      throw new Error("O snapshot ainda não usa o filtro Clockify Dev. Execute o pipeline atualizado.");
    }
    if (!state.data.views?.bug || !state.data.views?.adaptativa) {
      throw new Error("Snapshot sem as views separadas de Bugs e Adaptativas.");
    }
    bindViewSelector();
    bindFilters();
    setView("bug");
    $("#load-state").remove();
  } catch (error) {
    showError(error);
  }
}

init();
