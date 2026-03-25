// ── Chat Network Analysis — D3.js Visualization ──────────────────────

const COMMUNITY_COLORS = [
  "#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
  "#f778ba", "#79c0ff", "#56d364", "#e3b341", "#ff7b72",
];

let fullNetworkData = null;
let currentSimulation = null;
let currentView = "full"; // "full" | "ego"
let svg, g, zoom;
let width, height;

// ── 초기화 ─────────────────────────────────────────────────────────

async function init() {
  showLoading(true);

  // SVG 설정
  const container = document.getElementById("graph-container");
  width = container.clientWidth;
  height = container.clientHeight;

  svg = d3.select("#network-svg")
    .attr("width", width)
    .attr("height", height);

  // 줌 설정
  zoom = d3.zoom()
    .scaleExtent([0.1, 8])
    .on("zoom", (event) => g.attr("transform", event.transform));

  svg.call(zoom);
  g = svg.append("g");

  // 데이터 로드
  try {
    const resp = await fetch("/api/network");
    fullNetworkData = await resp.json();
    updateHeaderStats(fullNetworkData.stats);
    renderFullNetwork(fullNetworkData);
  } catch (err) {
    console.error("Failed to load network:", err);
  }

  showLoading(false);
  setupSearch();
  setupControls();
}

function showLoading(show) {
  let el = document.querySelector(".loading-overlay");
  if (show && !el) {
    el = document.createElement("div");
    el.className = "loading-overlay";
    el.innerHTML = '<div class="spinner"></div>네트워크 분석 로딩 중...';
    document.body.appendChild(el);
  } else if (!show && el) {
    el.remove();
  }
}

function updateHeaderStats(stats) {
  document.getElementById("header-stats").textContent =
    `${stats.total_nodes}명 · ${stats.total_edges}개 연결 · ${stats.total_communities}개 커뮤니티 · modularity ${stats.modularity}`;
}

// ── 전체 네트워크 렌더링 ─────────────────────────────────────────────

function renderFullNetwork(data) {
  currentView = "full";
  document.getElementById("btn-full-view").classList.add("active");

  g.selectAll("*").remove();
  if (currentSimulation) currentSimulation.stop();

  const nodes = data.nodes.map(d => ({ ...d }));
  const edges = data.edges.map(d => ({ ...d }));

  // 엣지 가중치 기준 상위만 표시
  const weights = edges.map(e => e.weight).sort((a, b) => a - b);
  const threshold = weights[Math.floor(weights.length * 0.7)] || 0;
  const visibleEdges = edges.filter(e => e.weight >= threshold);

  // 스케일
  const maxMsg = d3.max(nodes, d => d.msg_count) || 1;
  const nodeScale = d3.scaleSqrt().domain([0, maxMsg]).range([4, 28]);
  const edgeScale = d3.scaleLinear()
    .domain([d3.min(visibleEdges, d => d.weight) || 0, d3.max(visibleEdges, d => d.weight) || 1])
    .range([0.3, 4]);

  // 엣지 그리기
  const link = g.append("g")
    .selectAll("line")
    .data(visibleEdges)
    .join("line")
    .attr("stroke", "#30363d")
    .attr("stroke-opacity", 0.4)
    .attr("stroke-width", d => edgeScale(d.weight));

  // 노드 그리기
  const node = g.append("g")
    .selectAll("circle")
    .data(nodes)
    .join("circle")
    .attr("r", d => nodeScale(d.msg_count))
    .attr("fill", d => COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
    .attr("fill-opacity", 0.85)
    .attr("stroke", "#0d1117")
    .attr("stroke-width", 1)
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", dragStarted)
      .on("drag", dragged)
      .on("end", dragEnded))
    .on("mouseover", (event, d) => showTooltip(event, d))
    .on("mouseout", hideTooltip)
    .on("click", (event, d) => selectUser(d.id));

  // 상위 15명 라벨
  const topNodes = [...nodes].sort((a, b) => b.msg_count - a.msg_count).slice(0, 15);
  const topIds = new Set(topNodes.map(d => d.id));

  const label = g.append("g")
    .selectAll("text")
    .data(nodes.filter(d => topIds.has(d.id)))
    .join("text")
    .text(d => d.label)
    .attr("font-size", 10)
    .attr("fill", "#e6edf3")
    .attr("text-anchor", "middle")
    .attr("dy", d => -nodeScale(d.msg_count) - 4)
    .attr("pointer-events", "none");

  // 시뮬레이션
  currentSimulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(visibleEdges).id(d => d.id).distance(80).strength(d => Math.min(d.weight / 100, 0.5)))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(d => nodeScale(d.msg_count) + 2))
    .on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);
      node.attr("cx", d => d.x).attr("cy", d => d.y);
      label.attr("x", d => d.x).attr("y", d => d.y);
    });
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

    // 스케일
    const maxMsg = d3.max(nodes, d => d.msg_count) || 1;
    const nodeScale = d3.scaleSqrt().domain([0, maxMsg]).range([8, 40]);
    const maxWeight = d3.max(edges, d => d.weight) || 1;
    const edgeScale = d3.scaleLinear().domain([0, maxWeight]).range([1, 6]);

    // 엣지
    const link = g.append("g")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("stroke", "#30363d")
      .attr("stroke-opacity", 0.6)
      .attr("stroke-width", d => edgeScale(d.weight));

    // 노드
    const node = g.append("g")
      .selectAll("circle")
      .data(nodes)
      .join("circle")
      .attr("r", d => d.is_center ? nodeScale(d.msg_count) * 1.3 : nodeScale(d.msg_count))
      .attr("fill", d => d.is_center ? "#f0883e" : COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length])
      .attr("fill-opacity", d => d.is_center ? 1 : 0.8)
      .attr("stroke", d => d.is_center ? "#f0883e" : "#0d1117")
      .attr("stroke-width", d => d.is_center ? 3 : 1)
      .attr("cursor", "pointer")
      .call(d3.drag()
        .on("start", dragStarted)
        .on("drag", dragged)
        .on("end", dragEnded))
      .on("mouseover", (event, d) => showTooltip(event, d))
      .on("mouseout", hideTooltip)
      .on("click", (event, d) => {
        if (!d.is_center) selectUser(d.id);
      });

    // 모든 노드에 라벨
    const label = g.append("g")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text(d => d.label)
      .attr("font-size", d => d.is_center ? 13 : 11)
      .attr("font-weight", d => d.is_center ? "700" : "400")
      .attr("fill", "#e6edf3")
      .attr("text-anchor", "middle")
      .attr("dy", d => -(d.is_center ? nodeScale(d.msg_count) * 1.3 : nodeScale(d.msg_count)) - 6)
      .attr("pointer-events", "none");

    // 시뮬레이션
    currentSimulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id(d => d.id).distance(120).strength(d => Math.min(d.weight / 50, 0.8)))
      .force("charge", d3.forceManyBody().strength(-250))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(d => nodeScale(d.msg_count) + 6))
      .on("tick", () => {
        link
          .attr("x1", d => d.source.x)
          .attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x)
          .attr("y2", d => d.target.y);
        node.attr("cx", d => d.x).attr("cy", d => d.y);
        label.attr("x", d => d.x).attr("y", d => d.y);
      });

    // 사이드 패널 표시
    showSidePanel(data);

  } catch (err) {
    console.error("Failed to load ego network:", err);
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
  const totalUsers = fullNetworkData ? fullNetworkData.stats.total_nodes : "?";

  const communityColor = COMMUNITY_COLORS[user.community % COMMUNITY_COLORS.length];

  content.innerHTML = `
    <div class="user-header">
      <div class="user-avatar" style="background:${communityColor}">${user.label.charAt(0)}</div>
      <div class="user-info">
        <div class="name">${user.label}</div>
        <div class="detail">메시지 ${user.msg_count.toLocaleString()}개 · Community ${user.community}</div>
      </div>
    </div>

    <div class="panel-section">
      <h2>중심성 지표</h2>
      <div class="metric-grid">
        <div class="metric-card">
          <div class="label">Degree</div>
          <div class="value">${c.degree.toFixed(3)}</div>
          <div class="rank">#${ranks.degree || "?"} / ${totalUsers}</div>
        </div>
        <div class="metric-card">
          <div class="label">Betweenness</div>
          <div class="value">${c.betweenness.toFixed(3)}</div>
          <div class="rank">#${ranks.betweenness || "?"} / ${totalUsers}</div>
        </div>
        <div class="metric-card">
          <div class="label">PageRank</div>
          <div class="value">${c.pagerank.toFixed(3)}</div>
          <div class="rank">#${ranks.pagerank || "?"} / ${totalUsers}</div>
        </div>
        <div class="metric-card">
          <div class="label">Eigenvector</div>
          <div class="value">${c.eigenvector.toFixed(3)}</div>
          <div class="rank">#${ranks.eigenvector || "?"} / ${totalUsers}</div>
        </div>
      </div>
    </div>

    <div class="panel-section">
      <h2>Top 대화 상대</h2>
      <ul class="partner-list">
        ${data.top_partners.map((p, i) => {
          const maxW = data.top_partners[0]?.weight || 1;
          const pct = (p.weight / maxW * 100).toFixed(0);
          return `
            <li class="partner-item" data-id="${p.id}">
              <span>${i + 1}. ${p.label}</span>
              <span style="color:var(--text-dim)">${p.weight.toLocaleString()}</span>
            </li>
            <div class="partner-bar" style="width:${pct}%"></div>
          `;
        }).join("")}
      </ul>
    </div>

    <div class="panel-section">
      <h2>커뮤니티 ${user.community} 멤버</h2>
      <div class="member-tags">
        ${data.community_members.map(m =>
          `<span class="member-tag ${m.id === user.id ? 'current' : ''}" data-id="${m.id}">${m.label}</span>`
        ).join("")}
      </div>
    </div>
  `;

  // 파트너 클릭 이벤트
  content.querySelectorAll(".partner-item[data-id]").forEach(el => {
    el.addEventListener("click", () => selectUser(el.dataset.id));
  });
  content.querySelectorAll(".member-tag[data-id]").forEach(el => {
    el.addEventListener("click", () => selectUser(el.dataset.id));
  });
}

function hideSidePanel() {
  document.getElementById("side-panel").classList.add("hidden");
}

// ── 유저 선택 ────────────────────────────────────────────────────────

function selectUser(userId) {
  renderEgoNetwork(userId);
}

// ── 검색 ────────────────────────────────────────────────────────────

function setupSearch() {
  const input = document.getElementById("search");
  const dropdown = document.getElementById("search-results");
  let debounceTimer;

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) {
        dropdown.classList.remove("visible");
        return;
      }
      try {
        const resp = await fetch(`/api/users?q=${encodeURIComponent(q)}`);
        const users = await resp.json();
        if (users.length === 0) {
          dropdown.classList.remove("visible");
          return;
        }
        dropdown.innerHTML = users.slice(0, 10).map(u =>
          `<div class="search-item" data-id="${u.id}">
            <span>${u.label}</span>
            <span class="count">${u.msg_count.toLocaleString()}</span>
          </div>`
        ).join("");
        dropdown.classList.add("visible");

        dropdown.querySelectorAll(".search-item").forEach(el => {
          el.addEventListener("click", () => {
            selectUser(el.dataset.id);
            input.value = el.querySelector("span").textContent;
            dropdown.classList.remove("visible");
          });
        });
      } catch (err) {
        console.error("Search error:", err);
      }
    }, 200);
  });

  // 외부 클릭 시 드롭다운 닫기
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-container")) {
      dropdown.classList.remove("visible");
    }
  });

  // Enter 키
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = dropdown.querySelector(".search-item");
      if (first) first.click();
    }
  });
}

// ── 컨트롤 ──────────────────────────────────────────────────────────

function setupControls() {
  document.getElementById("btn-full-view").addEventListener("click", () => {
    if (fullNetworkData) {
      hideSidePanel();
      renderFullNetwork(fullNetworkData);
      resetZoom();
    }
  });

  document.getElementById("btn-reset-zoom").addEventListener("click", resetZoom);
  document.getElementById("close-panel").addEventListener("click", hideSidePanel);
}

function resetZoom() {
  svg.transition().duration(500).call(
    zoom.transform, d3.zoomIdentity.translate(0, 0).scale(1)
  );
}

// ── 툴팁 ────────────────────────────────────────────────────────────

function showTooltip(event, d) {
  const tooltip = document.getElementById("tooltip");
  const c = d.centrality || {};
  tooltip.innerHTML = `
    <div class="name">${d.label}</div>
    <div class="detail">
      메시지: ${d.msg_count.toLocaleString()}<br>
      Community: ${d.community}<br>
      PageRank: ${(c.pagerank || 0).toFixed(4)}
    </div>
  `;
  tooltip.style.left = (event.pageX + 12) + "px";
  tooltip.style.top = (event.pageY - 10) + "px";
  tooltip.classList.add("visible");
}

function hideTooltip() {
  document.getElementById("tooltip").classList.remove("visible");
}

// ── 드래그 ──────────────────────────────────────────────────────────

function dragStarted(event, d) {
  if (!event.active) currentSimulation.alphaTarget(0.3).restart();
  d.fx = d.x;
  d.fy = d.y;
}

function dragged(event, d) {
  d.fx = event.x;
  d.fy = event.y;
}

function dragEnded(event, d) {
  if (!event.active) currentSimulation.alphaTarget(0);
  d.fx = null;
  d.fy = null;
}

// ── 윈도우 리사이즈 ─────────────────────────────────────────────────

window.addEventListener("resize", () => {
  const container = document.getElementById("graph-container");
  width = container.clientWidth;
  height = container.clientHeight;
  svg.attr("width", width).attr("height", height);
});

// ── 시작 ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", init);
