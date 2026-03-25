// ── Chat Network Analysis — D3.js + Chart.js ───────────────────────

const COMMUNITY_COLORS = [
  "#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
  "#f778ba", "#79c0ff", "#56d364", "#e3b341", "#ff7b72",
];

let fullNetworkData = null;
let currentSimulation = null;
let currentView = "full";
let svg, g, zoom;
let width, height;
let topicsChart = null;
let sentimentChart = null;
let clusterRadar = null;
let userTypesData = null;

// ── 토스트 알림 ─────────────────────────────────────────────────────

function showToast(msg, type = "info") {
  const c = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── 분석 상태 폴링 ─────────────────────────────────────────────────

let _statusPollTimer = null;

async function pollAnalysisStatus() {
  try {
    const status = await fetch("/api/analysis-status").then(r => r.json());
    updateStatusBadges(status);
    if (status.text && status.user_types) {
      clearInterval(_statusPollTimer);
      _statusPollTimer = null;
      // 현재 활성 탭 자동 초기화
      const activeTab = document.querySelector(".tab-btn.active")?.dataset.tab;
      if (activeTab === "text") initTextTab();
      if (activeTab === "types") initTypesTab();
    }
    return status;
  } catch { return null; }
}

function updateStatusBadges(status) {
  const c = document.getElementById("analysis-badges");
  if (!c) return;
  c.innerHTML = [
    { label: "텍스트", ready: status.text },
    { label: "분류", ready: status.user_types },
  ].map(s => `
    <span class="status-badge ${s.ready ? 'ready' : 'loading'}">
      <span class="badge-dot"></span>${s.label}
    </span>
  `).join("");
}

function startStatusPolling() {
  pollAnalysisStatus();
  _statusPollTimer = setInterval(pollAnalysisStatus, 5000);
}

// ── 탭 전환 ───────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
      const target = document.getElementById(`tab-${tab}`);
      target.classList.add("active");
      document.getElementById("view-controls").style.display = tab === "network" ? "flex" : "none";
      if (tab === "text") initTextTab();
      if (tab === "types") initTypesTab();
    });
  });
}

// ── 초기화 ─────────────────────────────────────────────────────────

async function init() {
  showLoading(true);
  setupTabs();

  const container = document.getElementById("graph-container");
  width = container.clientWidth;
  height = container.clientHeight;

  svg = d3.select("#network-svg").attr("width", width).attr("height", height);
  zoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", (e) => g.attr("transform", e.transform));
  svg.call(zoom);
  g = svg.append("g");

  try {
    const resp = await fetch("/api/network");
    if (!resp.ok) throw new Error("Network API failed");
    fullNetworkData = await resp.json();
    updateHeaderStats(fullNetworkData.stats);
    renderFullNetwork(fullNetworkData);
    renderLegend(fullNetworkData);
  } catch (err) {
    showToast("네트워크 데이터 로드 실패", "error");
    console.error(err);
  }

  showLoading(false);
  setupSearch();
  setupControls();
  startStatusPolling();
}

function showLoading(show) {
  let el = document.querySelector(".loading-overlay");
  if (show && !el) {
    el = document.createElement("div");
    el.className = "loading-overlay";
    el.innerHTML = '<div class="spinner"></div>로딩 중...';
    document.body.appendChild(el);
  } else if (!show && el) { el.remove(); }
}

function updateHeaderStats(s) {
  document.getElementById("header-stats").textContent =
    `${s.total_nodes}명 · ${s.total_edges}연결 · ${s.total_communities}커뮤니티 · mod ${s.modularity}`;
}

// ── 범례 ────────────────────────────────────────────────────────────

function renderLegend(data) {
  const el = document.getElementById("legend");
  if (!el || !data.communities) return;
  const items = data.communities.map((c, i) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${COMMUNITY_COLORS[i % COMMUNITY_COLORS.length]}"></div>커뮤니티 ${c.id} (${c.members.length}명)</div>`
  ).join("");
  el.innerHTML = `
    <div class="legend-title">커뮤니티</div>
    ${items}
    <div class="legend-size-info">노드 크기 = 메시지 수</div>
  `;
}

// ── 전체 네트워크 렌더링 ─────────────────────────────────────────────

function renderFullNetwork(data) {
  currentView = "full";
  document.getElementById("btn-full-view").classList.add("active");
  g.selectAll("*").remove();
  if (currentSimulation) currentSimulation.stop();

  const nodes = data.nodes.map(d => ({ ...d }));
  const edges = data.edges.map(d => ({ ...d }));

  const weights = edges.map(e => e.weight).sort((a, b) => a - b);
  const threshold = weights[Math.floor(weights.length * 0.7)] || 0;
  const visibleEdges = edges.filter(e => e.weight >= threshold);

  const maxMsg = d3.max(nodes, d => d.msg_count) || 1;
  const nodeScale = d3.scaleSqrt().domain([0, maxMsg]).range([4, 28]);
  const maxW = d3.max(visibleEdges, d => d.weight) || 1;
  const minW = d3.min(visibleEdges, d => d.weight) || 0;
  const edgeScale = d3.scaleLinear().domain([minW, maxW]).range([0.3, 4]);
  const edgeColorScale = d3.scaleLinear().domain([minW, maxW]).range(["#21262d", "#58a6ff"]);

  const link = g.append("g").selectAll("line").data(visibleEdges).join("line")
    .attr("stroke", d => edgeColorScale(d.weight))
    .attr("stroke-opacity", 0.5)
    .attr("stroke-width", d => edgeScale(d.weight));

  const node = g.append("g").selectAll("circle").data(nodes).join("circle")
    .attr("r", d => nodeScale(d.msg_count))
    .attr("fill", d => COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
    .attr("fill-opacity", 0.85)
    .attr("stroke", d => COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
    .attr("stroke-width", 2)
    .attr("stroke-opacity", 0.3)
    .attr("cursor", "pointer")
    .call(d3.drag().on("start", dragStarted).on("drag", dragged).on("end", dragEnded))
    .on("mouseover", (event, d) => { highlightConnections(d, nodes, visibleEdges, node, link); showTooltip(event, d); })
    .on("mouseout", () => { unhighlightAll(node, link, visibleEdges, edgeColorScale); hideTooltip(); })
    .on("click", (_, d) => selectUser(d.id));

  const topNodes = [...nodes].sort((a, b) => b.msg_count - a.msg_count).slice(0, 15);
  const topIds = new Set(topNodes.map(d => d.id));

  const label = g.append("g").selectAll("text").data(nodes.filter(d => topIds.has(d.id))).join("text")
    .text(d => d.label)
    .attr("font-size", 10).attr("fill", "#e6edf3").attr("text-anchor", "middle")
    .attr("dy", d => -nodeScale(d.msg_count) - 5)
    .attr("pointer-events", "none")
    .style("text-shadow", "0 0 4px #0d1117, 0 0 8px #0d1117");

  currentSimulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(visibleEdges).id(d => d.id).distance(80).strength(d => Math.min(d.weight / 100, 0.5)))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(d => nodeScale(d.msg_count) + 2))
    .on("tick", () => {
      link.attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("cx", d => d.x).attr("cy", d => d.y);
      label.attr("x", d => d.x).attr("y", d => d.y);
    });
}

// ── 노드 호버 하이라이트 ────────────────────────────────────────────

function highlightConnections(d, nodes, edges, nodeSelection, linkSelection) {
  const connectedIds = new Set();
  connectedIds.add(d.id);
  edges.forEach(e => {
    const src = typeof e.source === "object" ? e.source.id : e.source;
    const tgt = typeof e.target === "object" ? e.target.id : e.target;
    if (src === d.id) connectedIds.add(tgt);
    if (tgt === d.id) connectedIds.add(src);
  });
  nodeSelection.attr("fill-opacity", n => connectedIds.has(n.id) ? 1 : 0.15)
    .attr("stroke-opacity", n => connectedIds.has(n.id) ? 0.8 : 0.05);
  linkSelection.attr("stroke-opacity", e => {
    const src = typeof e.source === "object" ? e.source.id : e.source;
    const tgt = typeof e.target === "object" ? e.target.id : e.target;
    return (src === d.id || tgt === d.id) ? 0.9 : 0.05;
  });
}

function unhighlightAll(nodeSelection, linkSelection, edges, edgeColorScale) {
  nodeSelection.attr("fill-opacity", 0.85).attr("stroke-opacity", 0.3);
  linkSelection.attr("stroke-opacity", 0.5);
}

// ── Ego 네트워크 렌더링 ──────────────────────────────────────────────

async function renderEgoNetwork(userId) {
  currentView = "ego";
  document.getElementById("btn-full-view").classList.remove("active");
  showLoading(true);

  try {
    const resp = await fetch(`/api/user/${encodeURIComponent(userId)}`);
    if (!resp.ok) throw new Error("User not found");
    const data = await resp.json();

    g.selectAll("*").remove();
    if (currentSimulation) currentSimulation.stop();

    const nodes = data.nodes.map(d => ({ ...d }));
    const edges = data.edges.map(d => ({ ...d }));

    const maxMsg = d3.max(nodes, d => d.msg_count) || 1;
    const nodeScale = d3.scaleSqrt().domain([0, maxMsg]).range([8, 40]);
    const maxWeight = d3.max(edges, d => d.weight) || 1;
    const edgeScale = d3.scaleLinear().domain([0, maxWeight]).range([1, 6]);
    const edgeColorScale = d3.scaleLinear().domain([0, maxWeight]).range(["#21262d", "#58a6ff"]);

    const link = g.append("g").selectAll("line").data(edges).join("line")
      .attr("stroke", d => edgeColorScale(d.weight))
      .attr("stroke-opacity", 0.6)
      .attr("stroke-width", d => edgeScale(d.weight));

    const node = g.append("g").selectAll("circle").data(nodes).join("circle")
      .attr("r", d => d.is_center ? nodeScale(d.msg_count) * 1.3 : nodeScale(d.msg_count))
      .attr("fill", d => d.is_center ? "#f0883e" : COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
      .attr("fill-opacity", d => d.is_center ? 1 : 0.8)
      .attr("stroke", d => d.is_center ? "#f0883e" : COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
      .attr("stroke-width", d => d.is_center ? 3 : 2)
      .attr("stroke-opacity", d => d.is_center ? 0.5 : 0.3)
      .attr("cursor", "pointer")
      .call(d3.drag().on("start", dragStarted).on("drag", dragged).on("end", dragEnded))
      .on("mouseover", (event, d) => showTooltip(event, d))
      .on("mouseout", hideTooltip)
      .on("click", (_, d) => { if (!d.is_center) selectUser(d.id); });

    const label = g.append("g").selectAll("text").data(nodes).join("text")
      .text(d => d.label)
      .attr("font-size", d => d.is_center ? 13 : 11)
      .attr("font-weight", d => d.is_center ? "700" : "400")
      .attr("fill", "#e6edf3").attr("text-anchor", "middle")
      .attr("dy", d => -(d.is_center ? nodeScale(d.msg_count) * 1.3 : nodeScale(d.msg_count)) - 6)
      .attr("pointer-events", "none")
      .style("text-shadow", "0 0 4px #0d1117, 0 0 8px #0d1117");

    currentSimulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id(d => d.id).distance(120).strength(d => Math.min(d.weight / 50, 0.8)))
      .force("charge", d3.forceManyBody().strength(-250))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(d => nodeScale(d.msg_count) + 6))
      .on("tick", () => {
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("cx", d => d.x).attr("cy", d => d.y);
        label.attr("x", d => d.x).attr("y", d => d.y);
      });

    showSidePanel(data);
  } catch (err) {
    showToast("유저 데이터 로드 실패", "error");
    console.error(err);
  }
  showLoading(false);
}

// ── 사이드 패널 ──────────────────────────────────────────────────────

function showSidePanel(data) {
  const panel = document.getElementById("side-panel");
  const content = document.getElementById("panel-content");
  panel.classList.remove("hidden");

  const user = data.user;
  const c = user.centrality;
  const ranks = user.centrality_ranks;
  const total = fullNetworkData ? fullNetworkData.stats.total_nodes : "?";
  const color = COMMUNITY_COLORS[user.community % COMMUNITY_COLORS.length];

  // 유저 유형 정보
  const typeInfo = userTypesData?.users?.[user.id];
  const typeTag = typeInfo ? `<span class="type-tag">${typeInfo.type}</span>` : "";

  // 워드클라우드 미니
  const wcImg = `<div class="panel-wc"><img src="/api/text/wordcloud/${encodeURIComponent(user.id)}" alt="WordCloud" onerror="this.parentElement.style.display='none'"></div>`;

  content.innerHTML = `
    <div class="user-header">
      <div class="user-avatar" style="background:${color}">${user.label.charAt(0)}</div>
      <div class="user-info">
        <div class="name">${user.label}</div>
        <div class="detail">메시지 ${user.msg_count.toLocaleString()}개 · Community ${user.community}</div>
        ${typeTag}
      </div>
    </div>

    ${wcImg}

    <div class="panel-section">
      <h2>중심성 지표</h2>
      <div class="metric-grid">
        ${["degree","betweenness","pagerank","eigenvector"].map(m => `
          <div class="metric-card">
            <div class="label">${m}</div>
            <div class="value">${c[m].toFixed(3)}</div>
            <div class="rank">#${ranks[m] || "?"} / ${total}</div>
          </div>
        `).join("")}
      </div>
    </div>

    <div class="panel-section">
      <h2>Top 대화 상대</h2>
      <ul class="partner-list">
        ${data.top_partners.map((p, i) => {
          const maxW = data.top_partners[0]?.weight || 1;
          const pct = (p.weight / maxW * 100).toFixed(0);
          return `<li class="partner-item" data-id="${p.id}"><span>${i+1}. ${p.label}</span><span style="color:var(--text-dim)">${p.weight.toLocaleString()}</span></li><div class="partner-bar" style="width:${pct}%"></div>`;
        }).join("")}
      </ul>
    </div>

    <div class="panel-section">
      <h2>커뮤니티 ${user.community} 멤버</h2>
      <div class="member-tags">
        ${data.community_members.map(m => `<span class="member-tag ${m.id === user.id ? 'current' : ''}" data-id="${m.id}">${m.label}</span>`).join("")}
      </div>
    </div>
  `;

  content.querySelectorAll("[data-id]").forEach(el => {
    el.addEventListener("click", () => selectUser(el.dataset.id));
  });
}

function hideSidePanel() { document.getElementById("side-panel").classList.add("hidden"); }
function selectUser(userId) { renderEgoNetwork(userId); }

// ── 검색 ────────────────────────────────────────────────────────────

function setupSearch() {
  const input = document.getElementById("search");
  const dropdown = document.getElementById("search-results");
  let timer;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { dropdown.classList.remove("visible"); return; }
      try {
        const users = await fetch(`/api/users?q=${encodeURIComponent(q)}`).then(r => r.json());
        if (!users.length) { dropdown.classList.remove("visible"); return; }
        dropdown.innerHTML = users.slice(0, 10).map(u =>
          `<div class="search-item" data-id="${u.id}"><span>${u.label}</span><span class="count">${u.msg_count.toLocaleString()}</span></div>`
        ).join("");
        dropdown.classList.add("visible");
        dropdown.querySelectorAll(".search-item").forEach(el => {
          el.addEventListener("click", () => {
            selectUser(el.dataset.id);
            input.value = el.querySelector("span").textContent;
            dropdown.classList.remove("visible");
          });
        });
      } catch { /* ignore */ }
    }, 200);
  });

  document.addEventListener("click", (e) => { if (!e.target.closest(".search-container")) dropdown.classList.remove("visible"); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") dropdown.querySelector(".search-item")?.click(); });
}

// ── 컨트롤 ──────────────────────────────────────────────────────────

function setupControls() {
  document.getElementById("btn-full-view").addEventListener("click", () => {
    if (fullNetworkData) { hideSidePanel(); renderFullNetwork(fullNetworkData); resetZoom(); }
  });
  document.getElementById("btn-reset-zoom").addEventListener("click", resetZoom);
  document.getElementById("close-panel").addEventListener("click", hideSidePanel);
}

function resetZoom() { svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity); }

// ── 툴팁 ────────────────────────────────────────────────────────────

function showTooltip(event, d) {
  const tooltip = document.getElementById("tooltip");
  const c = d.centrality || {};
  const typeInfo = userTypesData?.users?.[d.id];
  const typeBadge = typeInfo ? `<div class="user-type-badge">${typeInfo.type}</div>` : "";
  tooltip.innerHTML = `
    <div class="name">${d.label}</div>
    <div class="detail">
      메시지: ${d.msg_count.toLocaleString()}<br>
      Community: ${d.community} · PageRank: ${(c.pagerank || 0).toFixed(4)}
    </div>
    ${typeBadge}
  `;
  // 화면 경계 감지
  let x = event.pageX + 12, y = event.pageY - 10;
  const rect = tooltip.getBoundingClientRect();
  if (x + 280 > window.innerWidth) x = event.pageX - 290;
  if (y + 120 > window.innerHeight) y = event.pageY - 120;
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
  tooltip.classList.add("visible");
}

function hideTooltip() { document.getElementById("tooltip").classList.remove("visible"); }

// ── 드래그 ──────────────────────────────────────────────────────────

function dragStarted(event, d) { if (!event.active) currentSimulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragEnded(event, d) { if (!event.active) currentSimulation.alphaTarget(0); d.fx = null; d.fy = null; }

window.addEventListener("resize", () => {
  const c = document.getElementById("graph-container");
  if (c) { width = c.clientWidth; height = c.clientHeight; svg.attr("width", width).attr("height", height); }
});

// ══════════════════════════════════════════════════════════════════════
// ── 텍스트 분석 탭 ──────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════

let textTabReady = false;

async function initTextTab() {
  if (textTabReady) return;

  const status = await pollAnalysisStatus();
  if (!status?.text) return; // 폴링이 자동 재시도 처리

  textTabReady = true;

  // 유저 셀렉트
  if (fullNetworkData) {
    const select = document.getElementById("text-user-select");
    if (select.options.length <= 1) {
      const sorted = [...fullNetworkData.nodes].sort((a, b) => b.msg_count - a.msg_count);
      sorted.forEach(n => {
        const opt = document.createElement("option");
        opt.value = n.id;
        opt.textContent = `${n.label} (${n.msg_count.toLocaleString()})`;
        select.appendChild(opt);
      });
      select.addEventListener("change", () => { if (select.value) loadUserTextAnalysis(select.value); });
    }
    // 첫 번째 유저 자동 선택
    if (select.options.length > 1 && !select.value) {
      select.value = select.options[1].value;
      loadUserTextAnalysis(select.value);
    }
  }

  // 커뮤니티 TF-IDF 전체 로드
  loadAllCommunityTfidf();
  loadTopicsChart();
  loadSentimentChart();
}

async function loadUserTextAnalysis(userId) {
  // 워드클라우드
  const wcCard = document.querySelector("#wordcloud-card .card-body");
  wcCard.innerHTML = '<div class="card-placeholder"><div class="spinner"></div></div>';
  const img = document.createElement("img");
  img.src = `/api/text/wordcloud/${encodeURIComponent(userId)}`;
  img.alt = "WordCloud";
  img.onload = () => { wcCard.innerHTML = ""; wcCard.appendChild(img); };
  img.onerror = () => { wcCard.innerHTML = '<div class="card-placeholder"><p>워드클라우드 없음</p></div>'; };

  // TF-IDF
  const tfidfCard = document.querySelector("#tfidf-card .card-body");
  tfidfCard.innerHTML = '<div class="card-placeholder"><div class="spinner"></div></div>';
  try {
    const data = await fetch(`/api/text/tfidf?scope=user&id=${encodeURIComponent(userId)}`).then(r => r.json());
    if (data.words?.length > 0) {
      const max = data.words[0][1];
      tfidfCard.innerHTML = data.words.slice(0, 15).map(([word, score]) => `
        <div class="word-item">
          <span class="word">${word}</span>
          <div class="word-bar-wrap"><div class="word-bar" style="width:${(score / max * 100).toFixed(0)}%"></div></div>
          <span class="score">${score.toFixed(3)}</span>
        </div>
      `).join("");
    } else {
      tfidfCard.innerHTML = '<div class="card-placeholder"><p>데이터 없음</p></div>';
    }
  } catch { tfidfCard.innerHTML = '<div class="card-placeholder"><p>로드 실패</p></div>'; }
}

async function loadAllCommunityTfidf() {
  const grid = document.getElementById("community-tfidf-grid");
  if (!grid || !fullNetworkData) return;

  try {
    const data = await fetch("/api/text/tfidf?scope=community").then(r => r.json());
    const commData = data.data || {};
    grid.innerHTML = Object.entries(commData).map(([id, words]) => {
      const color = COMMUNITY_COLORS[parseInt(id) % COMMUNITY_COLORS.length];
      const max = words[0]?.[1] || 1;
      return `
        <div class="community-card">
          <h4><span class="comm-dot" style="background:${color}"></span>커뮤니티 ${id}</h4>
          ${words.slice(0, 10).map(([w, s]) => `
            <div class="word-item">
              <span class="word">${w}</span>
              <div class="word-bar-wrap"><div class="word-bar" style="width:${(s/max*100).toFixed(0)}%;background:${color}88"></div></div>
              <span class="score">${s.toFixed(3)}</span>
            </div>
          `).join("")}
        </div>
      `;
    }).join("");
  } catch { grid.innerHTML = '<div class="card-placeholder"><p>로드 실패</p></div>'; }
}

async function loadTopicsChart() {
  try {
    const data = await fetch("/api/text/topics").then(r => r.json());
    if (!data.topics?.length || !data.monthly?.length) return;

    const ctx = document.getElementById("topics-chart");
    if (topicsChart) topicsChart.destroy();

    const months = data.monthly.map(m => m.month);
    const datasets = data.topics.slice(0, 8).map((topic, i) => ({
      label: `T${topic.id}: ${topic.keywords.slice(0, 3).map(k => k[0]).join(", ")}`,
      data: data.monthly.map(m => m.distribution[topic.id] || 0),
      borderColor: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length],
      backgroundColor: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length] + "44",
      fill: true, tension: 0.4, borderWidth: 1.5, pointRadius: 2,
    }));

    topicsChart = new Chart(ctx, {
      type: "line",
      data: { labels: months, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { color: "#e6edf3", font: { size: 10 }, boxWidth: 12, padding: 8 } } },
        scales: {
          x: { ticks: { color: "#8b949e", font: { size: 10 } }, grid: { color: "#21262d" } },
          y: { ticks: { color: "#8b949e", font: { size: 10 } }, grid: { color: "#21262d" }, stacked: true },
        },
      },
    });

    // 토픽 키워드 테이블
    const table = document.getElementById("topics-keywords");
    if (table) {
      table.innerHTML = data.topics.map((t, i) => `
        <div class="topic-item">
          <div class="topic-id" style="color:${COMMUNITY_COLORS[i % COMMUNITY_COLORS.length]}">토픽 ${t.id}</div>
          <div class="topic-words">${t.keywords.slice(0, 6).map(k => k[0]).join(" · ")}</div>
        </div>
      `).join("");
    }
  } catch (err) { console.error("Topics chart error:", err); }
}

async function loadSentimentChart() {
  try {
    const allData = await fetch("/api/text/sentiment").then(r => r.json());
    const monthlyData = allData.monthly || [];
    if (!monthlyData.length) return;

    // 요약
    const summaryEl = document.getElementById("sentiment-summary");
    const avgPos = (monthlyData.reduce((s, m) => s + m.positive, 0) / monthlyData.length * 100).toFixed(0);
    const avgNeg = (monthlyData.reduce((s, m) => s + m.negative, 0) / monthlyData.length * 100).toFixed(0);
    summaryEl.innerHTML = `평균 긍정 <span class="score-positive">${avgPos}%</span> · 부정 <span class="score-negative">${avgNeg}%</span>`;

    const ctx = document.getElementById("sentiment-chart");
    if (sentimentChart) sentimentChart.destroy();

    const months = monthlyData.map(m => m.month);
    sentimentChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: months,
        datasets: [
          { label: "긍정", data: monthlyData.map(m => m.positive), backgroundColor: "#3fb95099", borderColor: "#3fb950", borderWidth: 1 },
          { label: "부정", data: monthlyData.map(m => m.negative), backgroundColor: "#f8514999", borderColor: "#f85149", borderWidth: 1 },
          { label: "중립", data: monthlyData.map(m => m.neutral), backgroundColor: "#8b949e66", borderColor: "#8b949e", borderWidth: 1 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: "#e6edf3", font: { size: 11 } } } },
        scales: {
          x: { stacked: true, ticks: { color: "#8b949e" }, grid: { color: "#21262d" } },
          y: { stacked: true, ticks: { color: "#8b949e" }, grid: { color: "#21262d" }, max: 1 },
        },
      },
    });

    // Gemini 보정 결과
    const gemini = allData.gemini_calibration;
    if (gemini) {
      const moodsEl = document.getElementById("gemini-moods");
      moodsEl.innerHTML = Object.entries(gemini).map(([id, g]) => `
        <div class="mood-card">
          <div class="mood-label">커뮤니티 ${id} 분위기</div>
          ${g.mood_summary || "분석 없음"}
        </div>
      `).join("");
    }
  } catch (err) { console.error("Sentiment chart error:", err); }
}

// ══════════════════════════════════════════════════════════════════════
// ── 유저 유형 탭 ────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════

let typesTabReady = false;
let currentTypeFilter = null;

async function initTypesTab() {
  if (typesTabReady) return;

  const status = await pollAnalysisStatus();
  if (!status?.user_types) return;

  typesTabReady = true;

  try {
    const data = await fetch("/api/user-types").then(r => r.json());
    userTypesData = data;
    renderTypeSummary(data.clusters);
    renderTypeFilter(data.clusters);
    renderClusterRadar(data.clusters, data.feature_names);
    renderUserCards(data.users);
  } catch (err) {
    showToast("유저 분류 데이터 로드 실패", "error");
    console.error(err);
  }
}

function renderTypeSummary(clusters) {
  const c = document.getElementById("types-summary");
  const descriptions = {
    "허브형 (Hub)": "높은 연결성, 많은 메시지",
    "야행성 다작러 (Night Owl)": "심야 시간대 활동 집중",
    "조용한 관찰자 (Observer)": "낮은 활동량, 주로 읽기",
    "소통러 (Connector)": "멘션 활발, 다양한 대화 상대",
    "에세이스트 (Essayist)": "긴 메시지, 다양한 어휘",
    "활발한 참여자 (Active)": "높은 일평균 메시지",
    "꾸준한 참여자": "안정적 활동 패턴",
  };

  c.innerHTML = clusters.map(cl => `
    <div class="type-badge" data-cluster="${cl.id}">
      <span class="type-count">${cl.size}</span>
      <div>
        <div class="type-label">${cl.label}</div>
        <div class="type-desc">${descriptions[cl.label] || ""}</div>
      </div>
    </div>
  `).join("");

  c.querySelectorAll(".type-badge").forEach(el => {
    el.addEventListener("click", () => {
      const id = parseInt(el.dataset.cluster);
      setTypeFilter(id === currentTypeFilter ? null : id);
    });
  });
}

function renderTypeFilter(clusters) {
  const f = document.getElementById("types-filter");
  f.innerHTML = `<button class="filter-btn active" data-filter="all">전체</button>` +
    clusters.map(c => `<button class="filter-btn" data-filter="${c.id}">${c.label} (${c.size})</button>`).join("");
  f.querySelectorAll(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const v = btn.dataset.filter;
      setTypeFilter(v === "all" ? null : parseInt(v));
    });
  });
}

function setTypeFilter(clusterId) {
  currentTypeFilter = clusterId;
  // 필터 버튼 활성화
  document.querySelectorAll(".types-filter .filter-btn").forEach(btn => {
    const v = btn.dataset.filter;
    btn.classList.toggle("active", clusterId === null ? v === "all" : parseInt(v) === clusterId);
  });
  // 뱃지 활성화
  document.querySelectorAll(".type-badge").forEach(el => {
    el.classList.toggle("active", clusterId !== null && parseInt(el.dataset.cluster) === clusterId);
  });
  // 카드 필터링
  document.querySelectorAll(".user-type-card").forEach(card => {
    const cid = parseInt(card.dataset.cluster);
    card.style.display = (clusterId === null || cid === clusterId) ? "flex" : "none";
  });
}

function renderClusterRadar(clusters, featureNames) {
  const ctx = document.getElementById("cluster-radar");
  if (!ctx) return;
  if (clusterRadar) clusterRadar.destroy();

  const radarFeatures = ["msg_count", "night_ratio", "weekend_ratio", "avg_length", "vocab_richness", "degree"];
  const labels = ["활동량", "심야", "주말", "메시지길이", "어휘다양성", "연결성"];

  // 각 클러스터의 중심점을 0-1 정규화
  const allVals = {};
  radarFeatures.forEach(f => {
    const vals = clusters.map(c => c.center[f] || 0);
    allVals[f] = { min: Math.min(...vals), max: Math.max(...vals) };
  });

  const datasets = clusters.map((cl, i) => ({
    label: cl.label,
    data: radarFeatures.map(f => {
      const r = allVals[f];
      return r.max === r.min ? 0.5 : (cl.center[f] - r.min) / (r.max - r.min);
    }),
    borderColor: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length],
    backgroundColor: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length] + "33",
    borderWidth: 2, pointRadius: 3,
  }));

  clusterRadar = new Chart(ctx, {
    type: "radar",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { color: "#e6edf3", font: { size: 10 }, boxWidth: 10 } } },
      scales: {
        r: {
          grid: { color: "#21262d" }, angleLines: { color: "#30363d" },
          ticks: { display: false }, pointLabels: { color: "#8b949e", font: { size: 10 } },
          min: 0, max: 1,
        },
      },
    },
  });
}

function renderUserCards(users) {
  const grid = document.getElementById("types-grid");
  const sorted = Object.entries(users).sort((a, b) => (b[1].features.msg_count || 0) - (a[1].features.msg_count || 0));

  grid.innerHTML = sorted.map(([hash, u]) => {
    const f = u.features;
    const commColor = COMMUNITY_COLORS[(fullNetworkData?.nodes?.find(n => n.id === hash)?.community || 0) % COMMUNITY_COLORS.length];
    return `
      <div class="user-type-card" data-id="${hash}" data-cluster="${u.cluster_id}" style="border-left-color:${commColor}">
        <div class="card-left">
          <div class="card-header">
            <span class="user-name">${u.label}</span>
            <span class="user-type">${u.type}</span>
          </div>
          <div class="card-stats">
            <div><span class="stat-value">${Math.round(f.msg_count || 0).toLocaleString()}</span><br>메시지</div>
            <div><span class="stat-value">${f.active_days || 0}</span><br>활동일</div>
            <div><span class="stat-value">${(f.msgs_per_day || 0).toFixed(1)}</span><br>일평균</div>
            <div><span class="stat-value">${((f.night_ratio || 0) * 100).toFixed(0)}%</span><br>심야</div>
            <div><span class="stat-value">${((f.weekend_ratio || 0) * 100).toFixed(0)}%</span><br>주말</div>
            <div><span class="stat-value">${(f.avg_length || 0).toFixed(0)}</span><br>평균길이</div>
          </div>
        </div>
        <div class="card-right">
          <canvas class="mini-radar" data-hash="${hash}"></canvas>
        </div>
      </div>
    `;
  }).join("");

  // 미니 레이더 차트 렌더링
  grid.querySelectorAll(".mini-radar").forEach(canvas => {
    const hash = canvas.dataset.hash;
    const u = users[hash];
    if (!u) return;
    renderMiniRadar(canvas, u.features);
  });

  // 카드 클릭
  grid.querySelectorAll(".user-type-card").forEach(card => {
    card.addEventListener("click", () => {
      document.querySelector('.tab-btn[data-tab="network"]').click();
      selectUser(card.dataset.id);
    });
  });
}

function renderMiniRadar(canvas, features) {
  const labels = ["활동", "심야", "주말", "길이", "어휘", "연결"];
  const keys = ["msgs_per_day", "night_ratio", "weekend_ratio", "avg_length", "vocab_richness", "degree"];

  // 간단한 정규화 (대략적 범위)
  const maxVals = { msgs_per_day: 50, night_ratio: 0.5, weekend_ratio: 0.5, avg_length: 50, vocab_richness: 0.3, degree: 1 };
  const data = keys.map(k => Math.min((features[k] || 0) / (maxVals[k] || 1), 1));

  new Chart(canvas, {
    type: "radar",
    data: {
      labels,
      datasets: [{ data, borderColor: "#58a6ff", backgroundColor: "#58a6ff33", borderWidth: 1.5, pointRadius: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        r: {
          grid: { color: "#21262d" }, angleLines: { color: "#30363d" },
          ticks: { display: false }, pointLabels: { color: "#8b949e", font: { size: 8 } },
          min: 0, max: 1,
        },
      },
    },
  });
}

// ── 시작 ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", init);
