const els = {
  feed: document.querySelector("#threatFeed"),
  areaList: document.querySelector("#areaList"),
  trendList: document.querySelector("#trendList"),
  refreshHistory: document.querySelector("#refreshHistory"),
  statusText: document.querySelector("#statusText"),
  refreshButton: document.querySelector("#refreshButton"),
  highPriority: document.querySelector("#highPriority"),
  recentlyAdded: document.querySelector("#recentlyAdded"),
  detailPanel: document.querySelector("#detailPanel"),
  detailContent: document.querySelector("#detailContent"),
  closeDetail: document.querySelector("#closeDetail"),
  tickerList: document.querySelector("#tickerList"),
  tickerForm: document.querySelector("#tickerForm"),
  tickerInput: document.querySelector("#tickerInput"),
  configForm: document.querySelector("#configForm"),
  refreshMinutesInput: document.querySelector("#refreshMinutesInput"),
  lookbackHoursInput: document.querySelector("#lookbackHoursInput"),
  filters: {
    search: document.querySelector("#searchFilter"),
    ticker: document.querySelector("#tickerFilter"),
    score: document.querySelector("#scoreFilter"),
    area: document.querySelector("#areaFilter"),
    source: document.querySelector("#sourceFilter"),
    dateFrom: document.querySelector("#dateFromFilter"),
    dateTo: document.querySelector("#dateToFilter"),
    sort: document.querySelector("#sortFilter"),
  },
};

let dashboard = null;
let analytics = null;
let tickers = [];
let debounceTimer = null;

function formatDate(value) {
  if (!value) return "--";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function queryString() {
  const params = new URLSearchParams();
  const values = {
    search: els.filters.search.value.trim(),
    ticker: els.filters.ticker.value,
    min_score: els.filters.score.value,
    area: els.filters.area.value,
    source: els.filters.source.value,
    date_from: els.filters.dateFrom.value,
    date_to: els.filters.dateTo.value,
    sort: els.filters.sort.value,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params.toString();
}

function scoreMarkup(score, small = false) {
  const cls = small ? "mini-score" : "score-badge";
  return `<span class="${cls} score-${score}">${score}</span>`;
}

function selectOptions(select, values, label) {
  const current = select.value;
  select.innerHTML = `<option value="">${label}</option>${values
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("")}`;
  if (values.includes(current)) select.value = current;
}

function populateFilters() {
  if (!dashboard) return;
  const rows = dashboard.assessments;
  selectOptions(
    els.filters.ticker,
    tickers.filter((ticker) => ticker.enabled).map((ticker) => ticker.symbol),
    "Any",
  );
  selectOptions(
    els.filters.source,
    [...new Set(rows.map((row) => row.article.publisher || "Unknown source"))].sort(),
    "Any",
  );
  selectOptions(
    els.filters.area,
    [
      ...new Set(
        rows.flatMap((row) => row.assessment?.affected_areas || []),
      ),
    ].sort(),
    "Any",
  );
}

function renderMetrics() {
  const summary = analytics?.summary || {};
  document.querySelector("#articleCount").textContent = summary.total_articles ?? dashboard.article_count;
  document.querySelector("#reviewedToday").textContent = summary.articles_reviewed_today ?? 0;
  document.querySelector("#highThreatCount").textContent = summary.high_threat_articles ?? dashboard.high_threat_count;
  document.querySelector("#averageScore").textContent = summary.average_threat_score ?? 0;
  document.querySelector("#topArea").textContent = summary.most_affected_business_area ?? "--";
  document.querySelector("#topTicker").textContent = summary.most_active_ticker ?? "--";
  document.querySelector("#refreshCadence").textContent = `${dashboard.refresh_minutes}m`;
  document.querySelector("#nextRefresh").textContent = formatDate(dashboard.next_refresh_at);
  document.querySelector("#lastUpdated").textContent = formatDate(dashboard.last_successful_refresh_at);
}

function renderAreas() {
  const rows = analytics?.threats_by_area || [];
  els.areaList.innerHTML = rows.length
    ? rows
        .map(
          (row) => `
            <div class="area">
              <strong>${escapeHtml(row.area)}</strong>
              <span>${row.count} linked headline${row.count === 1 ? "" : "s"}</span>
            </div>
          `,
        )
        .join("")
    : '<p class="empty">No affected business areas yet.</p>';
}

function renderTrend() {
  const rows = analytics?.threat_counts_by_day || [];
  els.trendList.innerHTML = rows.length
    ? rows
        .map(
          (row) => `
            <div class="area">
              <strong>${escapeHtml(row.day)}</strong>
              <span>${row.total} total · ${row.high} high priority</span>
            </div>
          `,
        )
        .join("")
    : '<p class="empty">No trend data yet.</p>';
}

function renderRefreshHistory(runs) {
  els.refreshHistory.innerHTML = runs.length
    ? runs
        .slice(0, 6)
        .map(
          (run) => `
            <div class="area">
              <strong>${escapeHtml(run.status)} · ${formatDate(run.started_at)}</strong>
              <span>${run.tickers_checked} tickers · ${run.new_articles_inserted} new · ${run.articles_assessed} assessed</span>
            </div>
          `,
        )
        .join("")
    : '<p class="empty">No refresh runs yet.</p>';
}

function compactList(rows, emptyText) {
  if (!rows.length) return `<p class="empty">${escapeHtml(emptyText)}</p>`;
  return rows
    .map((row) => {
      const score = row.assessment?.overall_score || 1;
      return `
        <button class="compact-item secondary" type="button" data-id="${escapeHtml(row.article.article_id)}">
          ${scoreMarkup(score, true)}
          <span>
            <strong>${escapeHtml(row.article.title)}</strong><br />
            <span class="meta">${escapeHtml(row.article.ticker)} · ${formatDate(row.article.published_at)}</span>
          </span>
        </button>
      `;
    })
    .join("");
}

function card(row) {
  const article = row.article;
  const assessment = row.assessment || {
    overall_score: 1,
    severity_label: "Low",
    affected_areas: ["Market intelligence and growth"],
    risk_categories: [],
    detected_signals: [],
    confidence: "low",
    impact_summary: "Assessment pending.",
    recommended_action: "Refresh the feed to run assessment.",
    agent_findings: [],
  };
  const score = assessment.overall_score;
  const areas = assessment.affected_areas
    .map((area) => `<span class="chip">${escapeHtml(area)}</span>`)
    .join("");
  const categories = (assessment.risk_categories || [])
    .map((category) => `<span class="chip">${escapeHtml(category)}</span>`)
    .join("");
  const agents = assessment.agent_findings
    .slice()
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(
      (agent) => `
        <div class="agent">
          <strong>${escapeHtml(agent.agent)} · ${agent.score}/5 · ${escapeHtml(agent.confidence)}</strong>
          <p>${escapeHtml(agent.rationale)}</p>
        </div>
      `,
    )
    .join("");

  return `
    <article class="threat-card">
      <div class="score score-${score}">
        <span>${score}<small>/5</small></span>
      </div>
      <div>
        <div class="headline-row">
          <button class="headline secondary" type="button" data-id="${escapeHtml(article.article_id)}">${escapeHtml(article.title)}</button>
          <span class="chip">${escapeHtml(assessment.severity_label)} · ${escapeHtml(assessment.confidence)}</span>
        </div>
        <p class="meta">${escapeHtml(article.ticker)} · ${escapeHtml(article.publisher || "Unknown source")} · ${formatDate(article.published_at)}${article.reviewed ? " · Reviewed" : ""}</p>
        <p class="summary">${escapeHtml(assessment.impact_summary)}</p>
        <div class="chips">${areas}${categories}</div>
        <p class="summary"><strong>Action:</strong> ${escapeHtml(assessment.recommended_action)}</p>
        <div class="agents">${agents}</div>
      </div>
    </article>
  `;
}

function renderFeed() {
  const rows = dashboard.assessments;
  statusText.textContent = `${rows.length} headline${rows.length === 1 ? "" : "s"} shown`;
  els.highPriority.innerHTML = compactList(dashboard.high_priority, "No score 4-5 threats in this view.");
  els.recentlyAdded.innerHTML = compactList(dashboard.recently_added, "No recently added articles yet.");
  els.feed.innerHTML = rows.length
    ? rows.map(card).join("")
    : '<p class="empty">No headlines match the current filters.</p>';
}

async function loadDashboard() {
  els.statusText.textContent = "Loading dashboard...";
  const qs = queryString();
  const [dashboardData, analyticsData, runs, tickerData, config] = await Promise.all([
    api(`/api/dashboard${qs ? `?${qs}` : ""}`),
    api("/api/analytics"),
    api("/api/refresh-runs"),
    api("/api/tickers"),
    api("/api/config"),
  ]);
  dashboard = dashboardData;
  analytics = analyticsData;
  tickers = tickerData;
  els.refreshMinutesInput.value = config.refresh_minutes || dashboard.refresh_minutes;
  els.lookbackHoursInput.value = config.lookback_hours || 72;
  populateFilters();
  renderMetrics();
  renderAreas();
  renderTrend();
  renderRefreshHistory(runs);
  renderTickers();
  renderFeed();
}

async function refreshNow() {
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "Refreshing";
  els.statusText.textContent = "Pulling news and reassessing threats...";
  try {
    const result = await api("/api/refresh", { method: "POST" });
    els.statusText.textContent = result.error ? `Refresh completed with an error: ${result.error}` : "Refresh complete.";
    await loadDashboard();
  } catch (error) {
    els.statusText.textContent = "Refresh failed.";
    throw error;
  } finally {
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "Refresh";
  }
}

async function openDetail(articleId) {
  const row = await api(`/api/articles/${articleId}`);
  const article = row.article;
  const assessment = row.assessment || {};
  const sourceLink = article.link
    ? `<a href="${escapeHtml(article.link)}" target="_blank" rel="noreferrer">${escapeHtml(article.link)}</a>`
    : "No URL available";
  els.detailContent.innerHTML = `
    <section class="detail-section">
      <h2>${escapeHtml(article.title)}</h2>
      <p class="meta">${escapeHtml(article.publisher)} · ${escapeHtml(article.ticker)} · ${formatDate(article.published_at)}</p>
      <p>${sourceLink}</p>
      <p>${escapeHtml(article.summary || "No normalized summary available.")}</p>
      <div class="chips">
        ${scoreMarkup(assessment.overall_score || 1)}
        ${(assessment.affected_areas || []).map((area) => `<span class="chip">${escapeHtml(area)}</span>`).join("")}
        ${(assessment.risk_categories || []).map((category) => `<span class="chip">${escapeHtml(category)}</span>`).join("")}
      </div>
      <p><strong>Assessment:</strong> ${escapeHtml(assessment.impact_summary || "Assessment pending.")}</p>
      <p><strong>Action:</strong> ${escapeHtml(assessment.recommended_action || "Refresh to assess.")}</p>
      <p><strong>Signals:</strong> ${escapeHtml((assessment.detected_signals || []).join(", ") || "None detected")}</p>
      <div class="agents">
        ${(assessment.agent_findings || [])
          .map(
            (agent) => `
              <div class="agent">
                <strong>${escapeHtml(agent.agent)} · ${agent.score}/5 · ${escapeHtml(agent.confidence)}</strong>
                <p>${escapeHtml(agent.rationale)}</p>
              </div>
            `,
          )
          .join("")}
      </div>
      <form class="notes-form" id="notesForm">
        <label>
          <input id="reviewedInput" type="checkbox" ${article.reviewed ? "checked" : ""} />
          Reviewed
        </label>
        <label>
          <span>Analyst notes</span>
          <textarea id="notesInput">${escapeHtml(article.analyst_notes || "")}</textarea>
        </label>
        <button type="submit">Save Notes</button>
      </form>
    </section>
  `;
  els.detailPanel.hidden = false;
  document.querySelector("#notesForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await api(`/api/articles/${article.article_id}`, {
      method: "PATCH",
      body: JSON.stringify({
        reviewed: document.querySelector("#reviewedInput").checked,
        analyst_notes: document.querySelector("#notesInput").value,
      }),
    });
    await loadDashboard();
    await openDetail(article.article_id);
  });
}

function renderTickers() {
  els.tickerList.innerHTML = tickers
    .map(
      (ticker) => `
        <div class="ticker-row">
          <strong>${escapeHtml(ticker.symbol)}</strong>
          <label><input type="checkbox" data-toggle="${ticker.id}" ${ticker.enabled ? "checked" : ""} /> Active</label>
          <button class="secondary" type="button" data-delete="${ticker.id}" aria-label="Delete ${escapeHtml(ticker.symbol)}">×</button>
        </div>
      `,
    )
    .join("");
}

function reloadSoon() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    loadDashboard().catch(showError);
  }, 250);
}

function showError(error) {
  console.error(error);
  els.statusText.textContent = "Unable to load dashboard.";
  els.feed.innerHTML = '<p class="empty">The API returned an error. Check the server logs, then try again.</p>';
}

Object.values(els.filters).forEach((input) => input.addEventListener("change", reloadSoon));
els.filters.search.addEventListener("input", reloadSoon);
els.refreshButton.addEventListener("click", () => refreshNow().catch(showError));
els.closeDetail.addEventListener("click", () => {
  els.detailPanel.hidden = true;
});

document.body.addEventListener("click", async (event) => {
  const detailId = event.target.closest("[data-id]")?.dataset.id;
  if (detailId) {
    await openDetail(detailId).catch(showError);
    return;
  }
  const deleteId = event.target.closest("[data-delete]")?.dataset.delete;
  if (deleteId) {
    await api(`/api/tickers/${deleteId}`, { method: "DELETE" });
    await loadDashboard();
  }
});

document.body.addEventListener("change", async (event) => {
  const toggleId = event.target.dataset?.toggle;
  if (toggleId) {
    await api(`/api/tickers/${toggleId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: event.target.checked }),
    });
    await loadDashboard();
  }
});

els.tickerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbol = els.tickerInput.value.trim();
  if (!symbol) return;
  await api("/api/tickers", {
    method: "POST",
    body: JSON.stringify({ symbol, enabled: true }),
  });
  els.tickerInput.value = "";
  await loadDashboard();
});

els.configForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/config", {
    method: "PATCH",
    body: JSON.stringify({
      refresh_minutes: Number(els.refreshMinutesInput.value),
      lookback_hours: Number(els.lookbackHoursInput.value),
    }),
  });
  await loadDashboard();
});

loadDashboard().catch(showError);
