#!/usr/bin/env python3
"""Analytics dashboard — professional dark-themed UI.

Served at /analytics route. Includes:
- Weekly/Monthly KPI reports (6 pillars)
- Activity log + summary stats (moved from main dashboard)
- FB live insights + engagement (moved from main dashboard)
"""

ANALYTICS_HTML = """<!DOCTYPE html>
<html lang="ka">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FB Analytics — Crea Communication</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
  }

  /* ── Sidebar ── */
  .sidebar {
    position: fixed; left: 0; top: 0; bottom: 0;
    width: 260px;
    background: #151620;
    border-right: 1px solid #2d3148;
    display: flex; flex-direction: column;
    z-index: 100;
  }
  .sidebar-brand {
    padding: 28px 24px 20px;
    border-bottom: 1px solid #2d3148;
  }
  .sidebar-brand h1 {
    font-size: 18px; font-weight: 700; color: #fff;
    display: flex; align-items: center; gap: 10px;
  }
  .sidebar-brand h1 .logo-icon {
    width: 36px; height: 36px; border-radius: 10px;
    background: linear-gradient(135deg, #1877f2, #0c277d);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; color: #fff;
  }
  .sidebar-brand p { font-size: 12px; color: #64748b; margin-top: 4px; }

  .sidebar-nav { padding: 16px 12px; flex: 1; overflow-y: auto; }
  .nav-section { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; padding: 12px 12px 8px; }
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 12px; border-radius: 8px; cursor: pointer;
    color: #94a3b8; font-size: 14px; transition: all 0.15s;
    text-decoration: none;
  }
  .nav-item:hover { background: #1e2030; color: #e2e8f0; }
  .nav-item.active { background: #1877f2; color: #fff; }
  .nav-icon { font-size: 16px; width: 20px; text-align: center; }
  .sidebar-footer {
    padding: 16px 24px; border-top: 1px solid #2d3148;
    font-size: 12px; color: #475569;
  }

  /* ── Main content ── */
  .main { margin-left: 260px; padding: 32px; }

  .page-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 32px;
  }
  .page-header h2 { font-size: 28px; font-weight: 700; }
  .page-header p { color: #94a3b8; font-size: 14px; margin-top: 4px; }

  .header-actions { display: flex; gap: 10px; }
  .btn {
    padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer;
    font-size: 13px; font-weight: 600; transition: all 0.15s;
    display: flex; align-items: center; gap: 6px;
  }
  .btn-primary { background: #1877f2; color: #fff; }
  .btn-primary:hover { background: #1565c0; }
  .btn-secondary { background: #1e2030; color: #e2e8f0; border: 1px solid #2d3148; }
  .btn-secondary:hover { background: #2d3148; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Period tabs ── */
  .period-tabs {
    display: flex; gap: 4px; background: #151620; border-radius: 10px;
    padding: 4px; margin-bottom: 28px; width: fit-content;
  }
  .period-tab {
    padding: 8px 20px; border-radius: 8px; cursor: pointer;
    font-size: 13px; font-weight: 500; color: #94a3b8; transition: all 0.15s;
  }
  .period-tab.active { background: #1877f2; color: #fff; }
  .period-tab:hover:not(.active) { color: #e2e8f0; }

  /* ── KPI Cards ── */
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 28px;
  }
  .kpi-card {
    background: #151620; border: 1px solid #2d3148; border-radius: 12px;
    padding: 20px; transition: border-color 0.15s;
  }
  .kpi-card:hover { border-color: #3d4168; }
  .kpi-label { font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
  .kpi-value { font-size: 28px; font-weight: 700; margin: 8px 0 4px; color: #fff; }
  .kpi-trend { font-size: 12px; font-weight: 600; }
  .kpi-trend.up { color: #4ade80; }
  .kpi-trend.down { color: #f87171; }
  .kpi-trend.neutral { color: #64748b; }
  .kpi-sub { font-size: 11px; color: #475569; margin-top: 2px; }

  /* ── Sections ── */
  .section {
    background: #151620; border: 1px solid #2d3148; border-radius: 12px;
    padding: 24px; margin-bottom: 20px;
  }
  .section-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 20px;
  }
  .section-title {
    font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px;
  }
  .section-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; border-radius: 6px; font-size: 12px; font-weight: 700;
  }
  .num-blue { background: #1877f2; color: #fff; }
  .num-green { background: #059669; color: #fff; }
  .num-orange { background: #d97706; color: #fff; }
  .num-purple { background: #7c3aed; color: #fff; }
  .num-red { background: #dc2626; color: #fff; }
  .num-teal { background: #0891b2; color: #fff; }
  .section-badge {
    padding: 4px 10px; border-radius: 20px; font-size: 11px;
    font-weight: 600; background: #1e2030; color: #94a3b8;
  }

  /* ── Stat grid ── */
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; }
  .stat-item {
    background: #1a1d2e; border-radius: 8px; padding: 14px;
    text-align: center;
  }
  .stat-val { font-size: 22px; font-weight: 700; color: #fff; }
  .stat-label { font-size: 11px; color: #64748b; margin-top: 4px; }

  /* ── Reactions row ── */
  .reactions-row { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
  .rx-badge {
    display: flex; align-items: center; gap: 6px;
    background: #1a1d2e; padding: 8px 14px; border-radius: 8px;
    font-size: 14px;
  }
  .rx-badge .rx-count { font-weight: 700; color: #fff; }

  /* ── Table ── */
  .data-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  .data-table th {
    text-align: left; padding: 10px 14px; font-size: 11px;
    color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;
    border-bottom: 1px solid #2d3148;
  }
  .data-table td {
    padding: 12px 14px; font-size: 13px; border-bottom: 1px solid #1e2030;
    color: #e2e8f0;
  }
  .data-table tr:hover td { background: #1a1d2e; }
  .data-table .num { text-align: right; font-weight: 600; }
  .data-table .highlight { color: #1877f2; font-weight: 700; }

  /* ── Tags ── */
  .tag {
    display: inline-block; padding: 3px 10px; border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }
  .tag-blue { background: rgba(24, 119, 242, 0.15); color: #60a5fa; }
  .tag-green { background: rgba(74, 222, 128, 0.15); color: #4ade80; }
  .tag-red { background: rgba(248, 113, 113, 0.15); color: #f87171; }
  .tag-yellow { background: rgba(250, 204, 21, 0.15); color: #fbbf24; }
  .tag-purple { background: rgba(167, 139, 250, 0.15); color: #a78bfa; }
  .tag-gray { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }

  /* ── Progress bars ── */
  .progress-bar { height: 6px; background: #1e2030; border-radius: 3px; margin-top: 6px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
  .fill-blue { background: #1877f2; }
  .fill-green { background: #4ade80; }
  .fill-red { background: #f87171; }
  .fill-yellow { background: #fbbf24; }

  /* ── Sentiment gauge ── */
  .sentiment-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 10px 0; }
  .sent-pos { background: #4ade80; }
  .sent-neu { background: #64748b; }
  .sent-neg { background: #f87171; }

  /* ── Time grid ── */
  .time-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 4px; margin-top: 12px; }
  .time-cell {
    aspect-ratio: 1; border-radius: 4px; display: flex; align-items: center;
    justify-content: center; font-size: 10px; color: #94a3b8;
    background: #1a1d2e; position: relative;
  }
  .time-cell.hot { background: #1877f2; color: #fff; font-weight: 700; }
  .time-cell.warm { background: rgba(24, 119, 242, 0.3); }

  /* ── Alerts ── */
  .alert { padding: 12px 16px; border-radius: 8px; font-size: 13px; margin-top: 12px; }
  .alert-warn { background: rgba(250, 204, 21, 0.1); border: 1px solid rgba(250, 204, 21, 0.2); color: #fbbf24; }
  .alert-danger { background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.2); color: #f87171; }
  .alert-info { background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.2); color: #60a5fa; }

  /* ── Recommendations ── */
  .rec-list { list-style: none; }
  .rec-item {
    padding: 12px 16px; background: #1a1d2e; border-radius: 8px; margin-bottom: 8px;
    font-size: 13px; display: flex; align-items: flex-start; gap: 10px;
    border-left: 3px solid #1877f2;
  }
  .rec-num {
    width: 22px; height: 22px; border-radius: 6px; background: #1877f2;
    color: #fff; font-size: 11px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  }

  /* ── Two columns ── */
  .cols-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .cols-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }

  /* ── Loading ── */
  .loading { text-align: center; padding: 60px; color: #64748b; }
  .spinner { display: inline-block; width: 32px; height: 32px; border: 3px solid #2d3148;
    border-top-color: #1877f2; border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Unavailable ── */
  .unavail-list { margin-top: 8px; }
  .unavail-item { font-size: 12px; color: #64748b; padding: 4px 0; }
  .unavail-item::before { content: "\\00B7"; margin-right: 8px; color: #475569; }

  /* ── Activity Log styles ── */
  .a-src { display: flex; gap: 8px; flex-wrap: wrap; }
  .a-src-tag {
    padding: 6px 14px; background: #1a1d2e; border: 1px solid #2d3148;
    border-radius: 20px; font-size: 12px; color: #e2e8f0;
  }
  .a-src-tag .cnt { font-weight: 700; color: #1877f2; margin-left: 4px; }
  .a-filters { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
  .a-filters select {
    background: #1a1d2e; border: 1px solid #2d3148; border-radius: 7px;
    padding: 8px 12px; color: #e2e8f0; font-size: 13px; outline: none;
  }
  .st-badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .st-ok { background: rgba(74,222,128,0.15); color: #4ade80; }
  .st-no { background: rgba(248,113,113,0.15); color: #f87171; }
  .st-wait { background: rgba(251,191,36,0.15); color: #fbbf24; }

  /* ── FB Insights styles ── */
  .fb-stats-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 14px; margin-bottom: 20px;
  }
  .fb-stat-card {
    background: #1a1d2e; border-radius: 8px; padding: 16px; text-align: center;
  }
  .fb-stat-card .fv { font-size: 24px; font-weight: 700; color: #1877f2; }
  .fb-stat-card .fl { font-size: 11px; color: #64748b; margin-top: 4px; }
  .fb-growth { display: inline-block; font-size: 12px; font-weight: 600; margin-left: 6px; }
  .fb-growth.pos { color: #4ade80; }
  .fb-growth.neg { color: #f87171; }
  .fb-reactions-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 14px 0; }
  .fb-rx {
    background: #1a1d2e; border: 1px solid #2d3148; border-radius: 20px;
    padding: 8px 16px; font-size: 13px; color: #e2e8f0;
  }
  .fb-rx .rx-n { font-weight: 700; color: #1877f2; margin-left: 4px; }
  .fb-src-perf { margin: 14px 0; }
  .fb-src-row {
    display: flex; justify-content: space-between; padding: 8px 12px;
    border-bottom: 1px solid #1e2030; font-size: 13px;
  }
  .fb-src-row:hover { background: #1a1d2e; }
  .fb-src-name { color: #e2e8f0; }
  .fb-src-val { color: #1877f2; font-weight: 600; }
  .fb-top-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 12px; border-bottom: 1px solid #1e2030; font-size: 13px;
  }
  .fb-top-item:hover { background: #1a1d2e; }
  .fb-top-title {
    color: #e2e8f0; flex: 1; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; margin-right: 12px;
  }
  .fb-top-eng { display: flex; gap: 10px; color: #94a3b8; font-size: 12px; white-space: nowrap; }
  .fb-top-eng span { color: #1877f2; font-weight: 600; }
  .fb-msg { font-size: 12px; color: #4ade80; margin-top: 8px; display: none; }

  /* ── Responsive ── */
  @media (max-width: 900px) {
    .sidebar { display: none; }
    .main { margin-left: 0; padding: 16px; }
    .cols-2 { grid-template-columns: 1fr; }
    .cols-3 { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>

<!-- Sidebar -->
<nav class="sidebar">
  <div class="sidebar-brand">
    <h1><span class="logo-icon">📊</span> FB Analytics</h1>
    <p>Crea Communication</p>
  </div>
  <div class="sidebar-nav">
    <div class="nav-section">რეპორტები</div>
    <a class="nav-item active" data-nav="reports-weekly" onclick="showView('reports','weekly')"><span class="nav-icon">📅</span> კვირის რეპორტი</a>
    <a class="nav-item" data-nav="reports-monthly" onclick="showView('reports','monthly')"><span class="nav-icon">📆</span> თვის რეპორტი</a>

    <div class="nav-section">მონიტორინგი</div>
    <a class="nav-item" data-nav="activity" onclick="showView('activity')"><span class="nav-icon">📋</span> აქტივობის ლოგი</a>
    <a class="nav-item" data-nav="fb" onclick="showView('fb')"><span class="nav-icon">📘</span> FB Insights</a>

    <div class="nav-section">ნავიგაცია</div>
    <a class="nav-item" href="/"><span class="nav-icon">🏠</span> მთავარი დეშბორდი</a>
  </div>
  <div class="sidebar-footer">● FB Analytics v2.0</div>
</nav>

<!-- Main -->
<div class="main">

  <!-- ═══════════════ REPORTS VIEW ═══════════════ -->
  <div id="viewReports">
    <div class="page-header">
      <div>
        <h2 id="pageTitle">Facebook ანალიტიკა</h2>
        <p id="pageSub">პერიოდი: იტვირთება...</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" onclick="refreshData()">🔄 განახლება</button>
        <button class="btn btn-primary" onclick="generateReport()" id="btnGenerate">📊 ახალი რეპორტი</button>
      </div>
    </div>

    <div class="period-tabs">
      <div class="period-tab active" onclick="switchPeriod(this, 'weekly')">კვირის</div>
      <div class="period-tab" onclick="switchPeriod(this, 'monthly')">თვის</div>
    </div>

    <div id="loadingState" class="loading">
      <div class="spinner"></div>
      <p style="margin-top:12px">ანალიტიკა იტვირთება...</p>
    </div>

    <div id="reportContent" style="display:none">
      <div class="kpi-grid" id="kpiGrid"></div>

      <!-- 1. Distribution -->
      <div class="section">
        <div class="section-header">
          <span class="section-title"><span class="section-num num-blue">1</span> დისტრიბუცია</span>
          <span class="section-badge" id="distBadge">—</span>
        </div>
        <div class="stat-grid" id="distStats"></div>
        <div id="contentTypeBreakdown" style="margin-top:16px"></div>
      </div>

      <!-- 2. Attention -->
      <div class="section">
        <div class="section-header">
          <span class="section-title"><span class="section-num num-green">2</span> ყურადღება</span>
        </div>
        <div class="stat-grid" id="attStats"></div>
      </div>

      <!-- 3. Engagement -->
      <div class="section">
        <div class="section-header">
          <span class="section-title"><span class="section-num num-orange">3</span> ჩართულობა და ვირალურობა</span>
        </div>
        <div class="stat-grid" id="engStats"></div>
        <div class="reactions-row" id="reactionsRow"></div>
      </div>

      <!-- 4. Audience + 5. Trust -->
      <div class="cols-2">
        <div class="section">
          <div class="section-header">
            <span class="section-title"><span class="section-num num-purple">4</span> აუდიტორია</span>
          </div>
          <div class="stat-grid" id="audStats"></div>
          <div id="growthTrend" style="margin-top:16px"></div>
        </div>
        <div class="section">
          <div class="section-header">
            <span class="section-title"><span class="section-num num-red">5</span> ნდობა და უსაფრთხოება</span>
          </div>
          <div id="trustContent"></div>
        </div>
      </div>

      <!-- 6. Editorial -->
      <div class="section">
        <div class="section-header">
          <span class="section-title"><span class="section-num num-teal">6</span> სარედაქციო ინტელიჯენსი</span>
        </div>
        <div class="cols-2">
          <div>
            <h4 style="font-size:13px; color:#94a3b8; margin-bottom:10px">თემების ეფექტურობა</h4>
            <table class="data-table" id="topicsTable">
              <thead><tr><th>თემა</th><th class="num">პოსტები</th><th class="num">საშ. ჩართ.</th><th class="num">Share %</th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div>
            <h4 style="font-size:13px; color:#94a3b8; margin-bottom:10px">საუკეთესო დრო</h4>
            <div id="bestTimeContent"></div>
            <div class="time-grid" id="timeGrid"></div>
          </div>
        </div>
      </div>

      <!-- Top & Bottom posts -->
      <div class="cols-2">
        <div class="section">
          <div class="section-header">
            <span class="section-title">🏆 ტოპ პოსტები</span>
          </div>
          <div id="topPostsList"></div>
        </div>
        <div class="section">
          <div class="section-header">
            <span class="section-title">📉 სუსტი პოსტები</span>
          </div>
          <div id="bottomPostsList"></div>
        </div>
      </div>

      <!-- Recommendations -->
      <div class="section">
        <div class="section-header">
          <span class="section-title">📋 რეკომენდაციები</span>
        </div>
        <ul class="rec-list" id="recList"></ul>
      </div>

      <!-- Unavailable metrics -->
      <div id="unavailSection" class="section" style="display:none">
        <div class="section-header">
          <span class="section-title">⚠️ მიუწვდომელი მეტრიკები</span>
        </div>
        <div class="unavail-list" id="unavailList"></div>
      </div>
    </div>
  </div>

  <!-- ═══════════════ ACTIVITY LOG VIEW ═══════════════ -->
  <div id="viewActivity" style="display:none">
    <div class="page-header">
      <div>
        <h2>აქტივობის ლოგი</h2>
        <p>აქტივობის სტატისტიკა და ლოგები</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" onclick="loadActivityView()">🔄 განახლება</button>
      </div>
    </div>

    <div class="kpi-grid" id="actKpiGrid"></div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">📂 წყაროების მიხედვით</span>
      </div>
      <div class="a-src" id="a-src"></div>
    </div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">📋 ბოლო აქტივობები</span>
      </div>
      <div class="a-filters">
        <select id="a-fsrc" onchange="loadALogs()">
          <option value="">ყველა წყარო</option>
          <option value="interpressnews">interpressnews</option>
          <option value="rss_cnn">RSS CNN</option>
          <option value="rss_bbc">RSS BBC</option>
          <option value="rss_other">RSS Other</option>
          <option value="manual">manual</option>
          <option value="auto_card">auto_card</option>
        </select>
        <select id="a-fst" onchange="loadALogs()">
          <option value="">ყველა სტატუსი</option>
          <option value="approved">დამტკიცებული</option>
          <option value="rejected">უარყოფილი</option>
          <option value="pending">მოლოდინში</option>
        </select>
      </div>
      <div style="overflow-x:auto;">
        <table class="data-table">
          <thead><tr><th>დრო</th><th>წყარო</th><th>სათაური</th><th>სტატუსი</th><th>FB</th></tr></thead>
          <tbody id="a-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ═══════════════ FB INSIGHTS VIEW ═══════════════ -->
  <div id="viewFB" style="display:none">
    <div class="page-header">
      <div>
        <h2>Facebook Insights</h2>
        <p>გვერდის სტატისტიკა და ჩართულობა (ცოცხალი მონაცემები)</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" onclick="refreshFBEngagement()" id="btnFBRefresh">🔄 Engagement განახლება</button>
        <button class="btn btn-primary" onclick="loadFBView()">📊 განახლება</button>
      </div>
    </div>

    <div class="kpi-grid" id="fbKpiGrid"></div>
    <div class="fb-msg" id="fb-refresh-msg"></div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">📊 ჩართულობის მეტრიკები</span>
      </div>
      <div class="fb-stats-grid" id="fbInsightCards"></div>
      <p style="color:#94a3b8;font-size:12px;margin-bottom:8px;">რეაქციები (კვირა):</p>
      <div class="fb-reactions-row" id="fb-reactions-row"></div>
    </div>

    <div class="cols-2">
      <div class="section">
        <div class="section-header">
          <span class="section-title">🎯 საუკეთესო პოსტის დრო</span>
        </div>
        <div id="fb-best-hour" style="font-size:28px;font-weight:700;color:#1877f2;margin-bottom:8px">—</div>
        <p style="color:#64748b;font-size:12px">Engagement-ის მიხედვით</p>
      </div>
      <div class="section">
        <div class="section-header">
          <span class="section-title">📈 წყაროების ეფექტურობა</span>
        </div>
        <div class="fb-src-perf" id="fb-src-perf"></div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">🏆 ტოპ პოსტები (engagement)</span>
      </div>
      <div id="fb-top-list"></div>
    </div>
  </div>

</div>

<script>
var currentPeriod = 'weekly';
var reportData = null;
var currentView = 'reports';

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtNum(n) {
  n = parseInt(n || 0);
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toLocaleString('ka-GE');
}

/* ═══════════════ VIEW SWITCHING ═══════════════ */
function showView(view, subType) {
  currentView = view;
  document.getElementById('viewReports').style.display = view === 'reports' ? 'block' : 'none';
  document.getElementById('viewActivity').style.display = view === 'activity' ? 'block' : 'none';
  document.getElementById('viewFB').style.display = view === 'fb' ? 'block' : 'none';

  document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
  var navKey = view;
  if (view === 'reports' && subType) navKey = 'reports-' + subType;
  var activeNav = document.querySelector('.nav-item[data-nav="' + navKey + '"]');
  if (activeNav) activeNav.classList.add('active');

  if (view === 'reports') {
    if (subType) loadReport(subType);
  } else if (view === 'activity') {
    loadActivityView();
  } else if (view === 'fb') {
    loadFBView();
  }
}

/* ═══════════════ REPORTS ═══════════════ */
function switchPeriod(el, period) {
  document.querySelectorAll('.period-tab').forEach(function(t) { t.classList.remove('active'); });
  el.classList.add('active');
  currentPeriod = period;
  document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
  var activeNav = document.querySelector('.nav-item[data-nav="reports-' + period + '"]');
  if (activeNav) activeNav.classList.add('active');
  loadReport(period);
}

function loadReport(period) {
  currentPeriod = period || currentPeriod;
  document.getElementById('loadingState').style.display = 'block';
  document.getElementById('reportContent').style.display = 'none';

  fetch('/api/analytics/' + currentPeriod)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data.ok || !data.report) {
        document.getElementById('loadingState').innerHTML =
          '<p style="color:#f87171">რეპორტი ჯერ არ გენერირებულა.</p>' +
          '<button class="btn btn-primary" style="margin-top:16px" onclick="generateReport()">📊 გენერირება</button>';
        return;
      }
      reportData = data.report;
      renderReport(reportData);
    })
    .catch(function(err) {
      document.getElementById('loadingState').innerHTML =
        '<p style="color:#f87171">შეცდომა: ' + err.message + '</p>';
    });
}

function generateReport() {
  var btn = document.getElementById('btnGenerate');
  btn.disabled = true;
  btn.textContent = '⏳ გენერირდება...';
  fetch('/api/analytics/test-' + currentPeriod)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      btn.disabled = false;
      btn.textContent = '📊 ახალი რეპორტი';
      if (data.ok) loadReport(currentPeriod);
    })
    .catch(function() {
      btn.disabled = false;
      btn.textContent = '📊 ახალი რეპორტი';
    });
}

function refreshData() { loadReport(currentPeriod); }

function renderReport(r) {
  var period = r.period || {};
  document.getElementById('pageTitle').textContent =
    currentPeriod === 'weekly' ? 'კვირის ანალიტიკა' : 'თვის სტრატეგიული ანალიტიკა';
  document.getElementById('pageSub').textContent =
    'პერიოდი: ' + (period.since || '—') + ' — ' + (period.until || '—') +
    ' | განახლდა: ' + (r.computed_at || '').slice(0, 16).replace('T', ' ');

  var dist = r.distribution || {};
  var att = r.attention || {};
  var eng = r.engagement || {};
  var aud = r.audience || {};
  var trust = r.trust || {};
  var editorial = r.editorial || {};

  // KPI cards
  var kpis = [
    { label: 'მიღწევა', value: fmtNum(dist.total_reach), sub: 'Reach', color: '#1877f2' },
    { label: 'შთაბეჭდილებები', value: fmtNum(dist.total_impressions), sub: 'Impressions', color: '#60a5fa' },
    { label: 'ჩართულობა', value: (eng.engagement_rate || 0).toFixed(1) + '%', sub: 'Engagement Rate', color: '#f59e0b' },
    { label: 'პოსტები', value: dist.total_posts || 0, sub: 'Total Posts', color: '#8b5cf6' },
    { label: 'მიმდევრები', value: (aud.net_growth >= 0 ? '+' : '') + (aud.net_growth || 0), sub: 'Net Growth', color: aud.net_growth >= 0 ? '#4ade80' : '#f87171' },
    { label: 'ნეგატიური', value: (trust.negative_rate || 0).toFixed(1) + '%', sub: 'Negative Rate', color: trust.negative_rate > 1.5 ? '#f87171' : '#4ade80' },
  ];
  document.getElementById('kpiGrid').innerHTML = kpis.map(function(k) {
    return '<div class="kpi-card"><div class="kpi-label">' + k.label + '</div>' +
      '<div class="kpi-value" style="color:' + k.color + '">' + k.value + '</div>' +
      '<div class="kpi-sub">' + k.sub + '</div></div>';
  }).join('');

  // Distribution
  document.getElementById('distBadge').textContent = (dist.total_posts || 0) + ' პოსტი';
  document.getElementById('distStats').innerHTML =
    statItem('მიღწევა', fmtNum(dist.total_reach)) +
    statItem('შთაბეჭდილებები', fmtNum(dist.total_impressions)) +
    statItem('სიხშირე', (dist.frequency || 0).toFixed(2)) +
    statItem('პოსტები', dist.total_posts || 0);

  var byType = dist.by_content_type || {};
  var typeKeys = Object.keys(byType);
  if (typeKeys.length) {
    var colors = { photo: 'tag-blue', video: 'tag-purple', link: 'tag-green', status: 'tag-gray', reel: 'tag-yellow' };
    document.getElementById('contentTypeBreakdown').innerHTML =
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      typeKeys.map(function(t) { return '<span class="tag ' + (colors[t] || 'tag-gray') + '">' + t + ': ' + byType[t].count + '</span>'; }).join('') +
      '</div>';
  } else {
    document.getElementById('contentTypeBreakdown').innerHTML = '';
  }

  // Attention
  document.getElementById('attStats').innerHTML =
    statItem('კლიკები', fmtNum(att.total_clicks)) +
    statItem('CTR', (att.ctr || 0).toFixed(1) + '%') +
    statItem('ვიდეო პოსტები', att.video_posts_count || 0) +
    statItem('ვიდეო ნახვები', fmtNum(att.video_views));

  // Engagement
  document.getElementById('engStats').innerHTML =
    statItem('👍 ლაიქები', fmtNum(eng.total_likes)) +
    statItem('💬 კომენტარები', fmtNum(eng.total_comments)) +
    statItem('🔄 გაზიარებები', fmtNum(eng.total_shares)) +
    statItem('📈 Eng. Rate', (eng.engagement_rate || 0).toFixed(1) + '%') +
    statItem('📤 Share Rate', (eng.share_rate || 0).toFixed(1) + '%') +
    statItem('საშუალო', (eng.avg_engagement_per_post || 0).toFixed(1));

  var rx = eng.reactions || {};
  var rxItems = [
    { emoji: '❤️', key: 'love' }, { emoji: '😂', key: 'haha' },
    { emoji: '😮', key: 'wow' }, { emoji: '😢', key: 'sad' }, { emoji: '😠', key: 'angry' }
  ];
  document.getElementById('reactionsRow').innerHTML = rxItems.map(function(ri) {
    return '<div class="rx-badge">' + ri.emoji + ' <span class="rx-count">' + (rx[ri.key] || 0) + '</span></div>';
  }).join('');

  // Audience
  document.getElementById('audStats').innerHTML =
    statItem('ახალი', '+' + (aud.new_followers || 0)) +
    statItem('წასული', '-' + (aud.unfollows || 0)) +
    statItem('წმინდა', (aud.net_growth >= 0 ? '+' : '') + (aud.net_growth || 0));

  var daily = aud.daily_trend || [];
  if (daily.length) {
    var maxNet = Math.max.apply(null, daily.map(function(d) { return Math.abs(d.net); }).concat([1]));
    document.getElementById('growthTrend').innerHTML =
      '<div style="display:flex;gap:4px;align-items:flex-end;height:60px">' +
      daily.map(function(d) {
        var h = Math.max(4, Math.abs(d.net) / maxNet * 50);
        var color = d.net >= 0 ? '#4ade80' : '#f87171';
        return '<div style="flex:1;display:flex;flex-direction:column;align-items:center">' +
          '<div style="width:100%;height:' + h + 'px;background:' + color + ';border-radius:3px;min-width:4px"></div>' +
          '<span style="font-size:9px;color:#475569;margin-top:2px">' + (d.date || '').slice(5) + '</span></div>';
      }).join('') + '</div>';
  } else {
    document.getElementById('growthTrend').innerHTML = '<p style="color:#475569;font-size:12px">მონაცემები არ არის</p>';
  }

  // Trust
  var sent = trust.sentiment || {};
  var trustHTML = '<div class="stat-grid">' +
    statItem('ნეგატიური', fmtNum(trust.negative_feedback)) +
    statItem('ნეგ. %', (trust.negative_rate || 0).toFixed(1) + '%') +
    '</div>';

  if (sent.available) {
    trustHTML += '<div style="margin-top:16px"><div style="font-size:12px;color:#94a3b8;margin-bottom:6px">სენტიმენტი (' + sent.total + ' კომენტარი)</div>';
    trustHTML += '<div class="sentiment-bar">' +
      '<div class="sent-pos" style="width:' + (sent.positive_pct || 0) + '%"></div>' +
      '<div class="sent-neu" style="width:' + (sent.neutral_pct || 0) + '%"></div>' +
      '<div class="sent-neg" style="width:' + (sent.negative_pct || 0) + '%"></div></div>';
    trustHTML += '<div style="display:flex;justify-content:space-between;font-size:11px">' +
      '<span style="color:#4ade80">✅ ' + sent.positive_pct + '%</span>' +
      '<span style="color:#64748b">➖ ' + sent.neutral_pct + '%</span>' +
      '<span style="color:#f87171">⚠️ ' + sent.negative_pct + '%</span></div></div>';
  } else {
    trustHTML += '<div class="alert alert-info" style="margin-top:12px">სენტიმენტი მიუწვდომელი (კომენტარები არ მოიძებნა)</div>';
  }

  if (trust.alert) {
    trustHTML += '<div class="alert alert-danger">⚠️ ' + trust.alert + '</div>';
  }

  var negTypes = trust.negative_by_type || {};
  var negKeys = Object.keys(negTypes);
  if (negKeys.length) {
    trustHTML += '<div style="margin-top:12px">';
    negKeys.forEach(function(k) {
      trustHTML += '<div style="font-size:12px;color:#94a3b8;margin-bottom:4px">' + k + ': ' + negTypes[k] + '</div>';
    });
    trustHTML += '</div>';
  }
  document.getElementById('trustContent').innerHTML = trustHTML;

  // Editorial — Topics
  var topics = editorial.topics || {};
  var topicKeys = Object.keys(topics);
  var topicColors = ['tag-blue', 'tag-green', 'tag-purple', 'tag-yellow', 'tag-red', 'tag-gray'];
  var tbody = document.querySelector('#topicsTable tbody');
  tbody.innerHTML = topicKeys.length ? topicKeys.map(function(t, i) {
    var d = topics[t];
    return '<tr><td><span class="tag ' + topicColors[i % topicColors.length] + '">' + t + '</span></td>' +
      '<td class="num">' + d.count + '</td>' +
      '<td class="num highlight">' + (d.avg_engagement || 0).toFixed(1) + '</td>' +
      '<td class="num">' + (d.share_rate || 0).toFixed(1) + '%</td></tr>';
  }).join('') : '<tr><td colspan="4" style="color:#475569;text-align:center">თემები ვერ მოიძებნა</td></tr>';

  // Editorial — Best time
  var times = editorial.best_posting_times || {};
  var timeHTML = '';
  if (times.best_hour !== null && times.best_hour !== undefined) {
    timeHTML += '<div style="margin-bottom:12px">' +
      '<span style="font-size:20px;font-weight:700;color:#1877f2">' + String(times.best_hour).padStart(2, '0') + ':00</span>' +
      '<span style="color:#94a3b8;font-size:13px;margin-left:8px">საუკეთესო საათი</span></div>';
  }
  if (times.best_day) {
    timeHTML += '<div style="margin-bottom:12px">' +
      '<span style="font-size:16px;font-weight:600;color:#4ade80">' + times.best_day + '</span>' +
      '<span style="color:#94a3b8;font-size:13px;margin-left:8px">საუკეთესო დღე</span></div>';
  }
  document.getElementById('bestTimeContent').innerHTML = timeHTML || '<p style="color:#475569;font-size:12px">მონაცემები არ არის</p>';

  // Time heatmap
  var byHour = times.by_hour || {};
  var hourKeys = Object.keys(byHour).map(Number).sort(function(a, b) { return a - b; });
  if (hourKeys.length) {
    var maxEng = Math.max.apply(null, hourKeys.map(function(h) { return byHour[h].avg_engagement || 0; }).concat([1]));
    document.getElementById('timeGrid').innerHTML = Array.from({length: 24}, function(_, h) {
      var d = byHour[h];
      var cls = '';
      if (d) {
        var ratio = (d.avg_engagement || 0) / maxEng;
        cls = ratio > 0.7 ? 'hot' : ratio > 0.3 ? 'warm' : '';
      }
      return '<div class="time-cell ' + cls + '">' + h + '</div>';
    }).join('');
  } else {
    document.getElementById('timeGrid').innerHTML = '';
  }

  // Top & Bottom posts
  document.getElementById('topPostsList').innerHTML = renderPostsList(r.top_posts || [], '🏆');
  document.getElementById('bottomPostsList').innerHTML = renderPostsList(r.bottom_posts || [], '📉');

  // Recommendations
  var recs = r.recommendations || [];
  document.getElementById('recList').innerHTML = recs.length ?
    recs.map(function(rec, i) { return '<li class="rec-item"><span class="rec-num">' + (i + 1) + '</span><span>' + rec + '</span></li>'; }).join('') :
    '<li style="color:#475569;font-size:13px">რეკომენდაციები არ არის</li>';

  // Unavailable
  var unavail = r.unavailable_metrics || [];
  if (unavail.length) {
    document.getElementById('unavailSection').style.display = 'block';
    document.getElementById('unavailList').innerHTML = unavail.map(function(m) { return '<div class="unavail-item">' + m + '</div>'; }).join('');
  } else {
    document.getElementById('unavailSection').style.display = 'none';
  }

  document.getElementById('loadingState').style.display = 'none';
  document.getElementById('reportContent').style.display = 'block';
}

function statItem(label, value) {
  return '<div class="stat-item"><div class="stat-val">' + value + '</div><div class="stat-label">' + label + '</div></div>';
}

function renderPostsList(posts, icon) {
  if (!posts.length) return '<p style="color:#475569;font-size:13px">პოსტები არ მოიძებნა</p>';
  return posts.map(function(p, i) {
    var msg = (p.message || '').slice(0, 70) + ((p.message || '').length > 70 ? '...' : '');
    var topicTag = p.topic ? '<span class="tag tag-blue" style="margin-left:6px">' + p.topic + '</span>' : '';
    return '<div style="padding:12px;background:#1a1d2e;border-radius:8px;margin-bottom:8px">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span style="font-size:13px;font-weight:600;color:#e2e8f0">' + icon + ' ' + (i + 1) + '. ' + (msg || '(უსათაურო)') + '</span>' +
      topicTag + '</div>' +
      '<div style="display:flex;gap:14px;margin-top:8px;font-size:12px;color:#94a3b8">' +
      '<span>👍 ' + (p.likes || 0) + '</span>' +
      '<span>💬 ' + (p.comments || 0) + '</span>' +
      '<span>🔄 ' + (p.shares || 0) + '</span>' +
      '<span>📊 reach: ' + fmtNum(p.reach) + '</span>' +
      '<span style="color:#1877f2;font-weight:600">eng: ' + (p.engagement_rate || 0).toFixed(1) + '%</span>' +
      '</div></div>';
  }).join('');
}

/* ═══════════════ ACTIVITY LOG ═══════════════ */
function loadActivityView() {
  fetch('/api/analytics/summary')
    .then(function(r) { return r.json(); })
    .then(function(s) {
      var kpis = [
        { label: 'დღეს', value: s.today || 0, color: '#1877f2' },
        { label: 'კვირა', value: s.week || 0, color: '#60a5fa' },
        { label: 'თვე', value: s.month || 0, color: '#8b5cf6' },
        { label: 'სულ', value: s.total || 0, color: '#e2e8f0' },
        { label: 'დამტკიცებული', value: s.approved || 0, color: '#4ade80' },
        { label: 'უარყოფილი', value: s.rejected || 0, color: '#f87171' },
        { label: 'გამოქვეყნებული', value: s.published || 0, color: '#1877f2' },
      ];
      document.getElementById('actKpiGrid').innerHTML = kpis.map(function(k) {
        return '<div class="kpi-card"><div class="kpi-label">' + k.label + '</div>' +
          '<div class="kpi-value" style="color:' + k.color + '">' + k.value + '</div></div>';
      }).join('');

      var srcDiv = document.getElementById('a-src');
      srcDiv.innerHTML = '';
      var bySrc = s.by_source || {};
      Object.keys(bySrc).forEach(function(k) {
        srcDiv.innerHTML += '<div class="a-src-tag">' + esc(k) + '<span class="cnt">' + bySrc[k] + '</span></div>';
      });

      loadALogs();
    })
    .catch(function(e) { console.log('Activity load error:', e); });
}

function loadALogs() {
  var src = document.getElementById('a-fsrc').value;
  var st = document.getElementById('a-fst').value;
  var url = '/api/analytics/logs?limit=30';
  if (src) url += '&source=' + encodeURIComponent(src);
  if (st) url += '&status=' + encodeURIComponent(st);
  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var tb = document.getElementById('a-tbody');
      tb.innerHTML = '';
      (d.logs || []).forEach(function(l) {
        var ts = (l.timestamp || '').replace('T', ' ').slice(0, 16);
        var sc = l.status === 'approved' ? 'st-ok' : l.status === 'rejected' ? 'st-no' : 'st-wait';
        var sl = l.status === 'approved' ? 'დამტკ.' : l.status === 'rejected' ? 'უარყ.' : 'მოლოდ.';
        var fb = l.facebook_post_id ? '✅' : '—';
        tb.innerHTML += '<tr><td>' + esc(ts) + '</td><td>' + esc(l.source || '') + '</td><td>' + esc((l.title || '').slice(0, 40)) + '</td><td><span class="st-badge ' + sc + '">' + sl + '</span></td><td>' + fb + '</td></tr>';
      });
    })
    .catch(function(e) { console.log('Activity logs error:', e); });
}

/* ═══════════════ FB INSIGHTS ═══════════════ */
function loadFBView() {
  fetch('/api/fb/page-stats')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var net = (d.fan_adds || 0) - (d.fan_removes || 0);
      var growthBadge = net !== 0 ? '<span class="fb-growth ' + (net >= 0 ? 'pos' : 'neg') + '">' + (net > 0 ? '+' : '') + net + '</span>' : '';
      var kpis = [
        { label: 'მიმდევრები', value: (d.followers || 0).toLocaleString(), extra: growthBadge, color: '#1877f2' },
        { label: 'ფანები', value: (d.fans || 0).toLocaleString(), color: '#60a5fa' },
        { label: 'შთაბეჭდილებები', value: (d.page_impressions || 0).toLocaleString(), color: '#f59e0b' },
        { label: 'ჩართულობა', value: (d.page_post_engagements || 0).toLocaleString(), color: '#8b5cf6' },
      ];
      document.getElementById('fbKpiGrid').innerHTML = kpis.map(function(k) {
        return '<div class="kpi-card"><div class="kpi-label">' + k.label + '</div>' +
          '<div class="kpi-value" style="color:' + k.color + '">' + k.value + (k.extra || '') + '</div></div>';
      }).join('');
    })
    .catch(function(e) { console.log('FB stats error:', e); });

  fetch('/api/fb/computed-analytics')
    .then(function(r) { return r.json(); })
    .then(function(c) {
      if (c.error) return;
      document.getElementById('fbInsightCards').innerHTML =
        '<div class="fb-stat-card"><div class="fv">' + (c.engagement_rate || 0).toFixed(1) + '%</div><div class="fl">Engagement Rate</div></div>' +
        '<div class="fb-stat-card"><div class="fv">' + (c.avg_engagement || 0).toFixed(1) + '</div><div class="fl">საშ. ჩართულობა</div></div>' +
        '<div class="fb-stat-card"><div class="fv">' + (c.week_reach || 0).toLocaleString() + '</div><div class="fl">კვირის Reach</div></div>' +
        '<div class="fb-stat-card"><div class="fv">' + (c.total_posts || 0) + '</div><div class="fl">პოსტები (კვირა)</div></div>';

      var rx = c.reactions || {};
      document.getElementById('fb-reactions-row').innerHTML =
        '<div class="fb-rx">❤️ <span class="rx-n">' + (rx.love || 0) + '</span></div>' +
        '<div class="fb-rx">😂 <span class="rx-n">' + (rx.haha || 0) + '</span></div>' +
        '<div class="fb-rx">😮 <span class="rx-n">' + (rx.wow || 0) + '</span></div>' +
        '<div class="fb-rx">😢 <span class="rx-n">' + (rx.sad || 0) + '</span></div>' +
        '<div class="fb-rx">😠 <span class="rx-n">' + (rx.angry || 0) + '</span></div>';

      if (c.best_hour && c.best_hour !== '—') {
        document.getElementById('fb-best-hour').textContent = c.best_hour + ':00';
      }

      var sp = c.source_performance || {};
      var spDiv = document.getElementById('fb-src-perf');
      spDiv.innerHTML = '';
      Object.keys(sp).forEach(function(src) {
        var info = sp[src];
        spDiv.innerHTML += '<div class="fb-src-row"><span class="fb-src-name">' + esc(src) + ' (' + (info.count || 0) + ' პოსტი)</span><span class="fb-src-val">საშ. ' + (info.avg_engagement || 0).toFixed(1) + '</span></div>';
      });
      if (!Object.keys(sp).length) spDiv.innerHTML = '<div style="color:#64748b;font-size:12px;padding:8px;">მონაცემები არ არის</div>';
    })
    .catch(function(e) { console.log('FB analytics error:', e); });

  fetch('/api/fb/top-engaged?limit=5')
    .then(function(r) { return r.json(); })
    .then(function(d2) {
      var list = document.getElementById('fb-top-list');
      list.innerHTML = '';
      (d2.posts || []).forEach(function(p) {
        var likes = parseInt(p.likes || 0), cmts = parseInt(p.comments || 0), shares = parseInt(p.shares || 0);
        var rxBadge = '';
        if (p.reactions) {
          var rr = p.reactions;
          if (rr.love) rxBadge += ' ❤️' + rr.love;
          if (rr.haha) rxBadge += ' 😂' + rr.haha;
          if (rr.wow) rxBadge += ' 😮' + rr.wow;
        }
        list.innerHTML += '<div class="fb-top-item"><div class="fb-top-title">' + esc((p.title || '').slice(0, 50)) + '</div><div class="fb-top-eng">👍 <span>' + likes + '</span> 💬 <span>' + cmts + '</span> 🔄 <span>' + shares + '</span>' + rxBadge + '</div></div>';
      });
      if (!(d2.posts || []).length) list.innerHTML = '<div style="color:#64748b;font-size:12px;padding:12px;">ჯერ არ არის გამოქვეყნებული პოსტები</div>';
    })
    .catch(function(e) { console.log('FB top error:', e); });
}

function refreshFBEngagement() {
  var btn = document.getElementById('btnFBRefresh');
  var msg = document.getElementById('fb-refresh-msg');
  btn.disabled = true;
  btn.textContent = '⏳ მიმდინარეობს...';
  msg.style.display = 'none';
  fetch('/api/fb/refresh-engagement')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      msg.textContent = '✅ განახლდა ' + d.updated + '/' + d.total + ' პოსტი';
      msg.style.display = 'block';
      btn.disabled = false;
      btn.textContent = '🔄 Engagement განახლება';
      loadFBView();
    })
    .catch(function(e) {
      btn.disabled = false;
      btn.textContent = '🔄 Engagement განახლება';
      console.log('FB refresh error:', e);
    });
}

// Load initial view
loadReport('weekly');
</script>
</body>
</html>"""
