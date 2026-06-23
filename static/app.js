const feed = document.querySelector("#threatFeed");
const areaList = document.querySelector("#areaList");
const statusText = document.querySelector("#statusText");
const scoreFilter = document.querySelector("#scoreFilter");
const refreshButton = document.querySelector("#refreshButton");

let dashboard = null;

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

function card(row) {
  const article = row.article;
  const assessment = row.assessment || {
    overall_score: 1,
    severity_label: "Low",
    affected_areas: ["Market intelligence and growth"],
    impact_summary: "Assessment pending.",
    recommended_action: "Refresh the feed to run assessment.",
    agent_findings: [],
  };
  const score = assessment.overall_score;
  const href = article.link || "#";
  const linkAttrs = article.link ? 'target="_blank" rel="noreferrer"' : "";
  const areas = assessment.affected_areas
    .map((area) => `<span class="chip">${escapeHtml(area)}</span>`)
    .join("");
  const agents = assessment.agent_findings
    .slice()
    .sort((a, b) => b.score - a.score)
    .map(
      (agent) => `
        <div class="agent">
          <strong>${escapeHtml(agent.agent)} · ${agent.score}/5</strong>
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
          <a class="headline" href="${escapeHtml(href)}" ${linkAttrs}>${escapeHtml(article.title)}</a>
          <span class="chip">${escapeHtml(assessment.severity_label)}</span>
        </div>
        <p class="meta">${escapeHtml(article.ticker)} · ${escapeHtml(article.publisher || "Unknown publisher")} · ${formatDate(article.published_at)}</p>
        <p class="summary">${escapeHtml(assessment.impact_summary)}</p>
        <div class="chips">${areas}</div>
        <p class="summary"><strong>Action:</strong> ${escapeHtml(assessment.recommended_action)}</p>
        <div class="agents">${agents}</div>
      </div>
    </article>
  `;
}

function renderAreas(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    const score = row.assessment?.overall_score || 1;
    const areas = row.assessment?.affected_areas || [];
    areas.forEach((area) => {
      const current = counts.get(area) || { count: 0, max: 0 };
      current.count += 1;
      current.max = Math.max(current.max, score);
      counts.set(area, current);
    });
  });

  if (!counts.size) {
    areaList.innerHTML = '<p class="empty">No affected business areas yet.</p>';
    return;
  }

  areaList.innerHTML = Array.from(counts.entries())
    .sort((a, b) => b[1].max - a[1].max || b[1].count - a[1].count)
    .map(
      ([area, data]) => `
        <div class="area">
          <strong>${escapeHtml(area)}</strong>
          <span>${data.count} linked headline${data.count === 1 ? "" : "s"} · peak score ${data.max}/5</span>
        </div>
      `,
    )
    .join("");
}

function render() {
  if (!dashboard) return;
  const minScore = Number(scoreFilter.value);
  const rows = dashboard.assessments.filter((row) => (row.assessment?.overall_score || 1) >= minScore);

  document.querySelector("#articleCount").textContent = dashboard.article_count;
  document.querySelector("#highThreatCount").textContent = dashboard.high_threat_count;
  document.querySelector("#refreshCadence").textContent = `${dashboard.refresh_minutes}m`;
  document.querySelector("#lastUpdated").textContent = formatDate(dashboard.generated_at);
  statusText.textContent = `${rows.length} headline${rows.length === 1 ? "" : "s"} at score ${minScore}+`;

  renderAreas(rows);
  feed.innerHTML = rows.length
    ? rows.map(card).join("")
    : '<p class="empty">No headlines match this score filter.</p>';
}

async function loadDashboard() {
  statusText.textContent = "Loading dashboard...";
  const response = await fetch("/api/dashboard");
  if (!response.ok) throw new Error("Dashboard request failed");
  dashboard = await response.json();
  render();
}

async function refreshNow() {
  refreshButton.disabled = true;
  refreshButton.textContent = "Refreshing";
  statusText.textContent = "Pulling news and reassessing threats...";
  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadDashboard();
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "Refresh";
  }
}

scoreFilter.addEventListener("change", render);
refreshButton.addEventListener("click", refreshNow);

loadDashboard().catch((error) => {
  console.error(error);
  statusText.textContent = "Unable to load dashboard.";
  feed.innerHTML = '<p class="empty">Start the API server, then refresh this page.</p>';
});
