const state = {
  data: null,
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

const $ = (selector) => document.querySelector(selector);

function getDataUrl() {
  const requested = new URLSearchParams(window.location.search).get("data");
  if (requested) return requested;

  const isLocal = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  if (!isLocal) return "/api/snapshot";

  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  return `../outputs/okr_${today}.json`;
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
  return `${sign}${formatHours(Math.abs(value), 1)}`;
}

function formatMonth(value) {
  if (!value) return "—";
  const [year, month] = value.split("-");
  return monthFormat.format(new Date(Date.UTC(Number(year), Number(month) - 1, 1)));
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
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

function latestMonth() {
  return [...state.data.monthly].sort((a, b) => a.month.localeCompare(b.month)).at(-1);
}

function renderSummary() {
  const latest = latestMonth();
  if (!latest) return;

  const coverage = Number.isFinite(latest.coverage_pct) ? `${numberFormat.format(latest.coverage_pct)}%` : "—";
  setText("#latest-actual", formatHours(latest.avg_actual_hours));
  setText("#latest-actual-detail", `${formatMonth(latest.month)} · ${latest.bugs_with_clockify} de ${latest.bugs_in_jira} Bugs`);
  setText("#latest-estimate", formatHours(latest.avg_estimate_hours));
  setText("#latest-estimate-detail", `${formatMonth(latest.month)} · média das estimativas válidas`);
  setText("#latest-variation", formatSignedHours(latest.avg_delta_hours));
  setText("#coverage-value", coverage);
  setText("#coverage-detail", `${latest.bugs_with_clockify} tickets com horas mapeadas`);

  const asOf = state.data.definition?.as_of_date;
  setText("#snapshot-label", asOf ? `SNAPSHOT · ${formatDate(`${asOf}T12:00:00Z`)}` : "SNAPSHOT");

  const jiraTotal = state.data.bugs?.length ?? 0;
  const mappedTotal = state.data.tickets_with_clockify?.length ?? 0;
  setText("#data-source", `${mappedTotal} de ${jiraTotal} tickets com Clockify · atualização ${formatDate(`${asOf}T12:00:00Z`)}`);
}

function renderChart() {
  const canvas = $("#monthly-chart");
  if (!canvas || !window.Chart) return;

  const months = [...state.data.monthly].sort((a, b) => a.month.localeCompare(b.month));
  state.chart?.destroy();
  state.chart = new window.Chart(canvas, {
    type: "line",
    data: {
      labels: months.map((item) => formatMonth(item.month)),
      datasets: [
        {
          label: "Gasto",
          data: months.map((item) => item.avg_actual_hours),
          borderColor: "#161616",
          backgroundColor: "#161616",
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          tension: 0.25,
          spanGaps: false,
        },
        {
          label: "Estimado",
          data: months.map((item) => item.avg_estimate_hours),
          borderColor: "#9a9a94",
          backgroundColor: "#9a9a94",
          borderWidth: 1.5,
          borderDash: [5, 5],
          pointRadius: 2.5,
          pointHoverRadius: 4,
          tension: 0.25,
          spanGaps: false,
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
          displayColors: false,
          callbacks: {
            label: (context) => `${context.dataset.label}: ${formatHours(context.raw)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: "#73736e", font: { family: "Geist Sans", size: 11 } },
        },
        y: {
          beginAtZero: true,
          grid: { color: "#deded8" },
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
  const months = [...state.data.monthly].sort((a, b) => b.month.localeCompare(a.month));
  body.innerHTML = months.map((item) => `
    <tr>
      <td>${formatMonth(item.month)}</td>
      <td>${item.bugs_with_clockify} / ${item.bugs_in_jira}</td>
      <td>${Number.isFinite(item.coverage_pct) ? `${numberFormat.format(item.coverage_pct)}%` : "—"}</td>
      <td>${formatHours(item.avg_estimate_hours)}</td>
      <td>${formatHours(item.avg_actual_hours)}</td>
      <td>${formatSignedHours(item.avg_delta_hours)}</td>
      <td>${Number.isFinite(item.actual_to_estimate_ratio) ? `${numberFormat.format(item.actual_to_estimate_ratio)}×` : "—"}</td>
    </tr>
  `).join("");
}

function populateMonthFilter() {
  const select = $("#month-filter");
  const months = [...new Set(state.tickets.map((ticket) => ticket.created_at.slice(0, 7)))].sort().reverse();
  select.insertAdjacentHTML("beforeend", months.map((month) => `<option value="${month}">${formatMonth(month)}</option>`).join(""));
}

function filteredTickets() {
  const query = $("#ticket-search").value.trim().toLowerCase();
  const month = $("#month-filter").value;
  const source = $("#source-filter").value;
  const sort = $("#sort-select").value;

  const filtered = state.tickets.filter((ticket) => {
    const searchable = `${ticket.issue_key} ${ticket.summary}`.toLowerCase();
    const matchesQuery = !query || searchable.includes(query);
    const matchesMonth = month === "all" || ticket.created_at.slice(0, 7) === month;
    const matchesSource = source === "all" || ticket.spent_source === source;
    return matchesQuery && matchesMonth && matchesSource;
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
  setText("#ticket-count", `${tickets.length} de ${state.tickets.length} tickets`);
  emptyState.hidden = tickets.length > 0;
  body.innerHTML = tickets.map((ticket) => `
    <tr>
      <td title="${safeText(ticket.summary, "")}">
        <div class="ticket-line">
          <span class="ticket-key">${safeText(ticket.issue_key)}</span>
          <span class="ticket-summary">${safeText(ticket.summary)}</span>
        </div>
      </td>
      <td>${formatMonth(ticket.created_at.slice(0, 7))}</td>
      <td><span class="status" title="${safeText(ticket.status, "Sem status")}">${safeText(ticket.status, "Sem status")}</span></td>
      <td>${formatHours(ticket.estimate_hours, 2)}</td>
      <td>${formatHours(ticket.spent_hours, 2)}</td>
      <td>${formatSignedHours(ticket.variation_hours)}</td>
      <td><span class="source-pill">${safeText(ticket.spent_source)}</span></td>
    </tr>
  `).join("");
}

function bindFilters() {
  ["#ticket-search", "#month-filter", "#source-filter", "#sort-select"].forEach((selector) => {
    $(selector).addEventListener("input", renderTickets);
    $(selector).addEventListener("change", renderTickets);
  });
}

function showError(error) {
  const loadState = $("#load-state");
  loadState.classList.add("is-error");
  loadState.querySelector(".eyebrow").textContent = "SNAPSHOT NÃO ENCONTRADO";
  loadState.querySelector("p").textContent = `Execute o pipeline antes de abrir a view ou informe um arquivo pela URL (?data=...).`;
  console.error(error);
}

async function init() {
  try {
    const response = await fetch(getDataUrl(), { cache: "no-store" });
    if (!response.ok) throw new Error(`Snapshot indisponível: ${response.status}`);
    state.data = await response.json();
    state.tickets = [...(state.data.tickets_with_clockify ?? [])];
    renderSummary();
    renderChart();
    renderMonthlyTable();
    populateMonthFilter();
    bindFilters();
    renderTickets();
    $("#load-state").remove();
  } catch (error) {
    showError(error);
  }
}

init();
