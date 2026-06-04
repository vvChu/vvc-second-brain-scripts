/* ============================================================
   VvC Knowledge Graph — Core Rendering Logic
   Uses force-graph (Canvas 2D) for performance with 2000+ nodes
   ============================================================ */

(function () {
  'use strict';

  // ── Colour palette ──────────────────────────────────────────
  const TYPE_COLORS = {
    concept: '#4A90D9',
    source:  '#50C878',
    topic:   '#FF8C42',
  };
  const DIM_COLOR    = 'rgba(60,65,75,0.25)';
  const EDGE_COLOR   = 'rgba(100,110,130,0.15)';
  const EDGE_HL      = 'rgba(180,190,210,0.55)';
  const LABEL_COLOR  = '#e6edf3';

  // ── State ───────────────────────────────────────────────────
  let graphInstance   = null;
  let graphData       = null;   // { nodes, edges, metadata }
  let nodeById        = {};     // id → node reference
  let adjacency       = {};     // id → Set<id> (undirected neighbours)
  let edgesByNode     = {};     // id → [{source, target, type}]
  let highlightNodes  = new Set();
  let highlightLinks  = new Set();
  let hoveredNode     = null;
  let selectedNode    = null;
  let searchMatches   = new Set();
  let isSearchActive  = false;

  // Filter state
  let activeTypes     = new Set(['concept', 'source', 'topic']);
  let activeTags      = new Set();   // empty = show all
  let allTags         = [];

  // ── Data Loading ────────────────────────────────────────────

  /**
   * Fallback test data for development when no graph_data.js exists.
   * This is ONLY used when window.GRAPH_DATA is undefined AND fetch fails.
   */
  function getTestData() {
    return {
      metadata: { total_nodes: 8, total_edges: 10, generated_at: new Date().toISOString() },
      nodes: [
        { id: 'transformer_architecture',    title: 'Transformer Architecture',           type: 'concept', tags: ['knowledge', 'domain/ai', 'type/concept'], aliases: ['Transformer'], summary: 'Kiến trúc Transformer sử dụng cơ chế self-attention thay thế hoàn toàn RNN/LSTM.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/transformer_architecture.md' },
        { id: 'self_attention',              title: 'Self-Attention Mechanism',            type: 'concept', tags: ['knowledge', 'domain/ai', 'type/concept'], aliases: ['Scaled Dot-Product Attention'], summary: 'Cơ chế cho phép mỗi vị trí trong chuỗi "nhìn" toàn bộ chuỗi input.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/self_attention.md' },
        { id: 'positional_encoding',         title: 'Positional Encoding',                type: 'concept', tags: ['knowledge', 'domain/ai', 'type/concept'], aliases: [], summary: 'Thêm thông tin vị trí vào embedding vì Transformer không có tính tuần tự.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/positional_encoding.md' },
        { id: 'multi_head_attention',        title: 'Multi-Head Attention',               type: 'concept', tags: ['knowledge', 'domain/ai', 'type/concept'], aliases: ['MHA'], summary: 'Chạy nhiều head song song để capture nhiều loại quan hệ khác nhau.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/multi_head_attention.md' },
        { id: 'layer_normalization',         title: 'Layer Normalization',                type: 'concept', tags: ['knowledge', 'domain/ml', 'type/concept'], aliases: ['LayerNorm'], summary: 'Kỹ thuật chuẩn hóa giúp ổn định quá trình huấn luyện.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/layer_normalization.md' },
        { id: '2026-01-01_attention_is_all_you_need', title: 'Attention Is All You Need — Vaswani et al.', type: 'source', tags: ['knowledge', 'type/source', 'domain/ai'], aliases: ['Attention paper'], summary: 'Bài báo giới thiệu kiến trúc Transformer, nền tảng của mọi mô hình ngôn ngữ hiện đại.', source: '', file_path: '04 - Permanent/sources/2026-01-01_attention_is_all_you_need.md' },
        { id: 'ai_friendly_codebase',        title: 'AI-Friendly Codebase',               type: 'topic', tags: ['knowledge', 'domain/software', 'type/topic'], aliases: [], summary: 'Phân tích cách tổ chức codebase tối ưu cho AI agent.', source: '', file_path: '04 - Permanent/topics/ai_friendly_codebase.md' },
        { id: 'feed_forward_network',        title: 'Feed-Forward Network',               type: 'concept', tags: ['knowledge', 'domain/ai', 'type/concept'], aliases: ['FFN', 'MLP sublayer'], summary: 'Mạng feed-forward 2 lớp áp dụng point-wise sau mỗi sub-layer attention.', source: '2026-01-01_attention_is_all_you_need', file_path: '04 - Permanent/concepts/feed_forward_network.md' },
      ],
      edges: [
        { source: 'transformer_architecture', target: 'self_attention',      type: 'related' },
        { source: 'transformer_architecture', target: 'positional_encoding', type: 'related' },
        { source: 'transformer_architecture', target: 'multi_head_attention', type: 'wiki_link' },
        { source: 'transformer_architecture', target: '2026-01-01_attention_is_all_you_need', type: 'source_ref' },
        { source: 'self_attention',           target: 'multi_head_attention', type: 'related' },
        { source: 'self_attention',           target: '2026-01-01_attention_is_all_you_need', type: 'source_ref' },
        { source: 'positional_encoding',      target: '2026-01-01_attention_is_all_you_need', type: 'source_ref' },
        { source: 'multi_head_attention',     target: '2026-01-01_attention_is_all_you_need', type: 'source_ref' },
        { source: 'layer_normalization',      target: 'transformer_architecture', type: 'wiki_link' },
        { source: 'feed_forward_network',     target: 'transformer_architecture', type: 'related' },
      ],
    };
  }

  /**
   * Load graph data: first try window.GRAPH_DATA (from graph_data.js),
   * then try fetch('graph_data.json'), then fall back to test data.
   */
  async function loadGraphData() {
    // Option 1: graph_data.js already set window.GRAPH_DATA
    if (window.GRAPH_DATA) {
      console.log('[VvC Graph] Loaded data from window.GRAPH_DATA');
      return window.GRAPH_DATA;
    }

    // Option 2: fetch JSON (works when served via HTTP)
    try {
      const resp = await fetch('graph_data.json');
      if (resp.ok) {
        const data = await resp.json();
        console.log('[VvC Graph] Loaded data from graph_data.json via fetch');
        return data;
      }
    } catch (_) {
      // fetch fails on file:// — expected
    }

    // Option 3: development test data
    console.warn('[VvC Graph] No graph data found — using test dataset');
    return getTestData();
  }

  // ── Index Building ──────────────────────────────────────────

  function buildIndices(data) {
    nodeById   = {};
    adjacency  = {};
    edgesByNode = {};

    for (const n of data.nodes) {
      n._connections = 0;
      nodeById[n.id] = n;
      adjacency[n.id] = new Set();
      edgesByNode[n.id] = [];
    }

    for (const e of data.edges) {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      if (nodeById[sid]) {
        adjacency[sid].add(tid);
        edgesByNode[sid].push(e);
        nodeById[sid]._connections++;
      }
      if (nodeById[tid]) {
        adjacency[tid].add(sid);
        edgesByNode[tid].push(e);
        nodeById[tid]._connections++;
      }
    }

    // Collect all domain/* tags for the tag filter
    const tagSet = new Set();
    for (const n of data.nodes) {
      if (n.tags) {
        for (const t of n.tags) {
          // Include domain/* and other useful tags, skip generic ones
          if (t.startsWith('domain/') || (t !== 'knowledge' && !t.startsWith('type/'))) {
            tagSet.add(t);
          }
        }
      }
    }
    allTags = Array.from(tagSet).sort();
  }

  // ── Filtering ───────────────────────────────────────────────

  function getFilteredData() {
    const filteredNodes = graphData.nodes.filter(n => {
      if (!activeTypes.has(n.type)) return false;
      if (activeTags.size > 0) {
        const hasTags = n.tags && n.tags.some(t => activeTags.has(t));
        if (!hasTags) return false;
      }
      return true;
    });

    const nodeIds = new Set(filteredNodes.map(n => n.id));

    const filteredEdges = graphData.edges.filter(e => {
      const sid = typeof e.source === 'object' ? e.source.id : e.source;
      const tid = typeof e.target === 'object' ? e.target.id : e.target;
      return nodeIds.has(sid) && nodeIds.has(tid);
    });

    return { nodes: filteredNodes, links: filteredEdges };
  }

  function applyFilters() {
    const fd = getFilteredData();
    graphInstance.graphData(fd);
    updateStats(fd.nodes.length, fd.links.length);
    applySearch(); // re-apply search on filtered data
  }

  // ── Search ──────────────────────────────────────────────────

  let searchTimeout = null;

  function applySearch() {
    const query = document.getElementById('search-input').value.trim().toLowerCase();
    const countEl = document.getElementById('search-count');

    if (!query) {
      isSearchActive = false;
      searchMatches.clear();
      countEl.textContent = '';
      graphInstance.nodeColor(nodeColorFn);
      graphInstance.linkColor(linkColorFn);
      return;
    }

    isSearchActive = true;
    searchMatches.clear();

    const currentData = graphInstance.graphData();
    for (const n of currentData.nodes) {
      const titleMatch   = n.title && n.title.toLowerCase().includes(query);
      const aliasMatch   = n.aliases && n.aliases.some(a => a.toLowerCase().includes(query));
      const tagMatch     = n.tags && n.tags.some(t => t.toLowerCase().includes(query));
      const summaryMatch = n.summary && n.summary.toLowerCase().includes(query);
      if (titleMatch || aliasMatch || tagMatch || summaryMatch) {
        searchMatches.add(n.id);
      }
    }

    countEl.textContent = searchMatches.size + ' / ' + currentData.nodes.length + ' matches';

    // Trigger re-render
    graphInstance.nodeColor(nodeColorFn);
    graphInstance.linkColor(linkColorFn);
  }

  function debouncedSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(applySearch, 200);
  }

  // ── Node Sizing ─────────────────────────────────────────────

  function nodeSize(node) {
    const c = node._connections || 0;
    // Scale: min 2, grows logarithmically, cap at 12
    return Math.min(2 + Math.sqrt(c) * 1.5, 12);
  }

  // ── Colour Functions ────────────────────────────────────────

  function nodeColorFn(node) {
    // Search active: dim non-matches
    if (isSearchActive && !searchMatches.has(node.id)) {
      return DIM_COLOR;
    }
    // Hover highlighting: dim unconnected
    if (hoveredNode && !highlightNodes.has(node.id)) {
      return DIM_COLOR;
    }
    return TYPE_COLORS[node.type] || '#888';
  }

  function linkColorFn(link) {
    const sid = typeof link.source === 'object' ? link.source.id : link.source;
    const tid = typeof link.target === 'object' ? link.target.id : link.target;

    if (isSearchActive) {
      if (searchMatches.has(sid) && searchMatches.has(tid)) return EDGE_HL;
      return DIM_COLOR;
    }
    if (hoveredNode) {
      if (highlightLinks.has(link)) return EDGE_HL;
      return DIM_COLOR;
    }
    return EDGE_COLOR;
  }

  // ── Hover Logic ─────────────────────────────────────────────

  function onNodeHover(node) {
    const container = document.getElementById('graph-container');
    container.style.cursor = node ? 'pointer' : 'grab';

    highlightNodes.clear();
    highlightLinks.clear();
    hoveredNode = node;

    if (node) {
      highlightNodes.add(node.id);
      const neighbours = adjacency[node.id];
      if (neighbours) {
        for (const nid of neighbours) highlightNodes.add(nid);
      }
      // Highlight links connected to this node
      const currentData = graphInstance.graphData();
      for (const link of currentData.links) {
        const sid = typeof link.source === 'object' ? link.source.id : link.source;
        const tid = typeof link.target === 'object' ? link.target.id : link.target;
        if (sid === node.id || tid === node.id) {
          highlightLinks.add(link);
        }
      }
    }

    // Trigger re-render
    graphInstance.nodeColor(nodeColorFn);
    graphInstance.linkColor(linkColorFn);
  }

  // ── Click → Sidebar ─────────────────────────────────────────

  function onNodeClick(node) {
    if (!node) return;
    selectedNode = node;

    // Center on node with animation
    graphInstance.centerAt(node.x, node.y, 600);
    graphInstance.zoom(3, 600);

    showSidebar(node);
  }

  function showSidebar(node) {
    const sidebar = document.getElementById('sidebar');
    const titleEl = document.getElementById('sidebar-title');
    const body    = document.getElementById('sidebar-body');

    titleEl.textContent = node.title || node.id;
    body.innerHTML = buildSidebarContent(node);
    sidebar.classList.add('open');

    // Bind connection clicks
    body.querySelectorAll('.connection-item').forEach(el => {
      el.addEventListener('click', () => {
        const targetId = el.dataset.nodeId;
        const targetNode = nodeById[targetId];
        if (targetNode) {
          onNodeClick(targetNode);
        }
      });
    });

    // Source ref click
    body.querySelectorAll('.source-ref').forEach(el => {
      el.addEventListener('click', () => {
        const targetId = el.dataset.nodeId;
        const targetNode = nodeById[targetId];
        if (targetNode) onNodeClick(targetNode);
      });
    });
  }

  function buildSidebarContent(node) {
    let html = '';

    // Type badge
    html += '<span class="type-badge ' + node.type + '">' + node.type + '</span>';

    // Source ref
    if (node.source && nodeById[node.source]) {
      const src = nodeById[node.source];
      html += '<div class="detail-section">';
      html += '<h3>Source</h3>';
      html += '<span class="source-ref" data-node-id="' + escapeAttr(node.source) + '">';
      html += '📗 ' + escapeHtml(src.title || src.id);
      html += '</span></div>';
    }

    // Summary
    if (node.summary) {
      html += '<div class="detail-section">';
      html += '<h3>Summary</h3>';
      html += '<p>' + escapeHtml(node.summary) + '</p>';
      html += '</div>';
    }

    // Aliases
    if (node.aliases && node.aliases.length > 0) {
      html += '<div class="detail-section">';
      html += '<h3>Aliases</h3>';
      html += '<p class="aliases-list">' + node.aliases.map(escapeHtml).join(', ') + '</p>';
      html += '</div>';
    }

    // Tags
    if (node.tags && node.tags.length > 0) {
      html += '<div class="detail-section">';
      html += '<h3>Tags</h3>';
      html += '<div class="tags-container">';
      for (const t of node.tags) {
        html += '<span class="tag-chip">' + escapeHtml(t) + '</span>';
      }
      html += '</div></div>';
    }

    // File path
    if (node.file_path) {
      html += '<div class="detail-section">';
      html += '<h3>File Path</h3>';
      html += '<p style="font-family:monospace;font-size:12px;color:var(--text-muted);word-break:break-all;">' + escapeHtml(node.file_path) + '</p>';
      html += '</div>';
    }

    // Connections grouped by edge type
    const edges = edgesByNode[node.id] || [];
    if (edges.length > 0) {
      const groups = { related: [], source_ref: [], wiki_link: [] };

      for (const e of edges) {
        const sid = typeof e.source === 'object' ? e.source.id : e.source;
        const tid = typeof e.target === 'object' ? e.target.id : e.target;
        const otherId = sid === node.id ? tid : sid;
        const other = nodeById[otherId];
        if (!other) continue;
        const etype = e.type || 'wiki_link';
        if (!groups[etype]) groups[etype] = [];
        // Avoid duplicates
        if (!groups[etype].some(x => x.id === otherId)) {
          groups[etype].push(other);
        }
      }

      html += '<div class="detail-section">';
      html += '<h3>Connections</h3>';

      const labels = { related: '🔗 Related', source_ref: '📗 Source References', wiki_link: '📝 Wiki Links' };
      for (const [etype, items] of Object.entries(groups)) {
        if (items.length === 0) continue;
        html += '<div class="connections-group">';
        html += '<h4>' + labels[etype] + ' <span class="count">' + items.length + '</span></h4>';
        for (const item of items) {
          const dotColor = TYPE_COLORS[item.type] || '#888';
          html += '<button class="connection-item" data-node-id="' + escapeAttr(item.id) + '">';
          html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + dotColor + ';margin-right:6px;"></span>';
          html += escapeHtml(item.title || item.id);
          html += '</button>';
        }
        html += '</div>';
      }

      html += '</div>';
    }

    return html;
  }

  function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    selectedNode = null;
  }

  // ── Tag Filter UI ───────────────────────────────────────────

  function populateTagDropdown() {
    const list = document.getElementById('tag-list');
    list.innerHTML = '';

    const filterQuery = (document.getElementById('tag-search').value || '').toLowerCase();

    for (const tag of allTags) {
      if (filterQuery && !tag.toLowerCase().includes(filterQuery)) continue;

      const div = document.createElement('div');
      div.className = 'tag-option' + (activeTags.has(tag) ? ' selected' : '');

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = activeTags.has(tag);

      const label = document.createElement('span');
      label.textContent = tag;

      div.appendChild(cb);
      div.appendChild(label);

      div.addEventListener('click', (e) => {
        e.stopPropagation();
        if (activeTags.has(tag)) {
          activeTags.delete(tag);
        } else {
          activeTags.add(tag);
        }
        populateTagDropdown();
        updateTagBtnState();
        applyFilters();
      });

      list.appendChild(div);
    }
  }

  function updateTagBtnState() {
    const btn = document.getElementById('tag-filter-btn');
    if (activeTags.size > 0) {
      btn.classList.add('has-selection');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M1 2a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v2.586a1 1 0 0 1-.293.707L10 10v4a1 1 0 0 1-.553.894l-2 1A1 1 0 0 1 6 15V10L1.293 5.293A1 1 0 0 1 1 4.586V2Z"/></svg> Tags (' + activeTags.size + ')';
    } else {
      btn.classList.remove('has-selection');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M1 2a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v2.586a1 1 0 0 1-.293.707L10 10v4a1 1 0 0 1-.553.894l-2 1A1 1 0 0 1 6 15V10L1.293 5.293A1 1 0 0 1 1 4.586V2Z"/></svg> Tags';
    }
  }

  // ── Stats ───────────────────────────────────────────────────

  function updateStats(nodeCount, edgeCount) {
    document.getElementById('stats-badge').textContent =
      nodeCount.toLocaleString() + ' nodes · ' + edgeCount.toLocaleString() + ' edges';
  }

  // ── Canvas Rendering ────────────────────────────────────────

  function nodeCanvasRenderer(node, ctx, globalScale) {
    const size = nodeSize(node);
    const col  = nodeColorFn(node);

    // Draw circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
    ctx.fillStyle = col;
    ctx.fill();

    // Highlight ring for selected node
    if (selectedNode && selectedNode.id === node.id) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();
    }

    // Label: show when zoomed in (scale > 2.5) or when hovered/highlighted
    const showLabel = globalScale > 2.5 ||
                      (hoveredNode && highlightNodes.has(node.id)) ||
                      (isSearchActive && searchMatches.has(node.id));
    if (showLabel) {
      const label = node.title || node.id;
      const fontSize = Math.max(10 / globalScale, 1.5);
      ctx.font = fontSize + 'px -apple-system, BlinkMacSystemFont, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';

      // Text background for readability
      const textWidth = ctx.measureText(label).width;
      const bgPad = 2 / globalScale;
      ctx.fillStyle = 'rgba(13,17,23,0.85)';
      ctx.fillRect(
        node.x - textWidth / 2 - bgPad,
        node.y + size + 2 / globalScale - bgPad,
        textWidth + bgPad * 2,
        fontSize + bgPad * 2
      );

      ctx.fillStyle = LABEL_COLOR;
      ctx.fillText(label, node.x, node.y + size + 2 / globalScale);
    }
  }

  // ── Initialization ──────────────────────────────────────────

  async function init() {
    const loadingOverlay = document.getElementById('loading-overlay');

    try {
      graphData = await loadGraphData();
    } catch (err) {
      console.error('[VvC Graph] Failed to load data:', err);
      loadingOverlay.querySelector('p').textContent = 'Error loading graph data.';
      return;
    }

    buildIndices(graphData);

    // Prepare data in force-graph format (links instead of edges)
    const gd = {
      nodes: graphData.nodes,
      links: graphData.edges,
    };

    const container = document.getElementById('graph-container');

    // Create force-graph instance
    graphInstance = ForceGraph()(container)
      .graphData(gd)
      .nodeId('id')
      .nodeLabel('')   // We draw custom labels via Canvas
      .nodeCanvasObject(nodeCanvasRenderer)
      .nodeCanvasObjectMode(() => 'replace')
      .nodeVal(n => nodeSize(n) * 2)
      .linkSource('source')
      .linkTarget('target')
      .linkColor(linkColorFn)
      .linkWidth(0.5)
      .linkDirectionalParticles(0)
      .backgroundColor('#0d1117')
      .onNodeHover(onNodeHover)
      .onNodeClick(onNodeClick)
      .onBackgroundClick(closeSidebar)
      .enableNodeDrag(true)
      .enableZoomPanInteraction(true)
      .cooldownTicks(100)
      .warmupTicks(50)
      .onEngineStop(() => {
        // Hide loading after simulation settles
        loadingOverlay.classList.add('hidden');
      });

    // Performance: for large graphs, reduce force strength
    const totalNodes = graphData.nodes.length;
    if (totalNodes > 500) {
      graphInstance
        .d3AlphaDecay(0.03)
        .d3VelocityDecay(0.4);
    }
    if (totalNodes > 1500) {
      graphInstance
        .d3AlphaDecay(0.05)
        .d3VelocityDecay(0.5)
        .cooldownTicks(60)
        .warmupTicks(80);
    }

    // Update stats
    updateStats(gd.nodes.length, gd.links.length);

    // Populate tag filter
    populateTagDropdown();

    // Auto-fit after a short delay to let the simulation settle
    setTimeout(() => {
      graphInstance.zoomToFit(400, 60);
      loadingOverlay.classList.add('hidden');
    }, 2000);

    // ── Wire up UI events ──────────────────────────────────

    // Search
    document.getElementById('search-input')
      .addEventListener('input', debouncedSearch);

    // Type filter buttons
    document.querySelectorAll('.filter-btn[data-type]').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        if (activeTypes.has(type)) {
          activeTypes.delete(type);
          btn.classList.remove('active');
        } else {
          activeTypes.add(type);
          btn.classList.add('active');
        }
        applyFilters();
      });
    });

    // Sidebar close
    document.getElementById('sidebar-close')
      .addEventListener('click', closeSidebar);

    // Escape key closes sidebar
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeSidebar();
    });

    // Tag filter dropdown toggle
    const tagBtn = document.getElementById('tag-filter-btn');
    const tagDropdown = document.getElementById('tag-dropdown');

    tagBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      tagDropdown.classList.toggle('open');
      if (tagDropdown.classList.contains('open')) {
        document.getElementById('tag-search').focus();
      }
    });

    // Close dropdown on outside click
    document.addEventListener('click', () => {
      tagDropdown.classList.remove('open');
    });
    tagDropdown.addEventListener('click', (e) => e.stopPropagation());

    // Tag search within dropdown
    document.getElementById('tag-search')
      .addEventListener('input', populateTagDropdown);

    // Clear all tags
    document.getElementById('clear-tags').addEventListener('click', () => {
      activeTags.clear();
      populateTagDropdown();
      updateTagBtnState();
      applyFilters();
    });

    // Handle window resize
    window.addEventListener('resize', () => {
      graphInstance.width(container.clientWidth);
      graphInstance.height(container.clientHeight);
    });
  }

  // ── Helpers ─────────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;');
  }

  function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#39;');
  }

  // ── Start ───────────────────────────────────────────────────
  init();

})();
