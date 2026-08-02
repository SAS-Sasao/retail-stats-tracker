/* 小売月次統計トラッカー 画面ロジック（実装設計 §6.4 SC-01〜SC-06）。
 *
 * 描画の禁則（R1 / R6 / R8）はここで機械的に守る。silent に混ぜない。
 *   R1: 1 チャートの source_authority は必ず単一。違反時は描画せずエラー表示
 *   R6: meti-commerce-dynamics（小売業全体）を他業態と同一チャートに並べない
 *   R8: parent_segment_id によるロールアップ集計を行わない（合計を作らない）
 */
(function () {
  "use strict";
  var D = window.__SERIES__;
  var $ = function (id) { return document.getElementById(id); };
  var segById = {}, metById = {}, authById = {};
  D.segments.forEach(function (s) { segById[s.segment_id] = s; });
  D.metrics.forEach(function (m) { metById[m.metric_id] = m; });
  D.authorities.forEach(function (a) { authById[a.source_authority] = a; });

  function authLabel(code) { return (authById[code] || {}).label || code; }
  function segName(id) { return (segById[id] || {}).name || id; }
  function metName(id) { return (metById[id] || {}).name || id; }
  function fmt(v, id) {
    if (v === null || v === undefined) return "—";
    var p = (metById[id] || {}).precision;
    return (v > 0 ? "+" : "") + v.toFixed(p === undefined ? 1 : p);
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* ---- R1: 発表主体の単一性を assert する ---------------------------------- */
  function assertSingleAuthority(series) {
    var codes = {};
    series.forEach(function (s) { codes[s.source_authority] = 1; });
    var n = Object.keys(codes).length;
    if (n > 1) throw new Error("R1 違反: 発表主体が " + n + " 種混在しています");
    return Object.keys(codes)[0];
  }

  /* ---- R6: 粒度が違う segment を混ぜない ---------------------------------- */
  function splitGranularity(series) {
    var normal = [], macro = [];
    series.forEach(function (s) {
      ((segById[s.segment_id] || {}).different_granularity ? macro : normal).push(s);
    });
    return { normal: normal, macro: macro };
  }

  var PALETTE = ["#2b6cb0", "#c53030", "#2f855a", "#b7791f", "#6b46c1",
                 "#0987a0", "#d53f8c", "#4a5568", "#975a16", "#276749"];
  var charts = {};

  function renderLineChart(canvasId, series, labelOf, subtitleEl, emptyEl) {
    if (charts[canvasId]) { charts[canvasId].destroy(); delete charts[canvasId]; }
    var canvas = $(canvasId);
    if (!series.length) {
      canvas.parentNode.hidden = true; emptyEl.hidden = false; subtitleEl.textContent = "";
      return;
    }
    var authority;
    try { authority = assertSingleAuthority(series); }
    catch (e) {
      // silent に混ぜず、描画を止めて理由を出す
      canvas.parentNode.hidden = true; emptyEl.hidden = false;
      emptyEl.textContent = e.message; return;
    }
    canvas.parentNode.hidden = false; emptyEl.hidden = true;
    emptyEl.textContent = "この組み合わせのデータはありません。";

    // 期間軸は periods が持つ全期間。points に無い期間は欠測のまま（FR-20）
    var axis = D.periods.month || [];
    var datasets = series.map(function (s, i) {
      var byKey = {};
      s.points.forEach(function (p) { byKey[p.period_key] = p.value; });
      return {
        label: labelOf(s), borderColor: PALETTE[i % PALETTE.length],
        backgroundColor: PALETTE[i % PALETTE.length], tension: 0.2, spanGaps: false,
        data: axis.map(function (k) { return byKey.hasOwnProperty(k) ? byKey[k] : null; })
      };
    });
    // R4: チャートのサブタイトルにも発表主体を出す（画像化しても出所が残る）
    subtitleEl.textContent = "発表主体: " + authLabel(authority);
    charts[canvasId] = new Chart(canvas, {
      type: "line",
      data: { labels: axis, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { position: "bottom" },
                   title: { display: true, text: "発表主体: " + authLabel(authority) } },
        scales: { y: { title: { display: true, text: "%" } } }
      }
    });
  }

  /* ---- SC-01 概観 --------------------------------------------------------- */
  function renderOverview() {
    var months = D.periods.month || [];
    var latest = months[months.length - 1];
    var lines = [];
    D.series.forEach(function (s) {
      s.points.forEach(function (p) {
        if (p.streak_broken_months) {
          lines.push(segName(s.segment_id) + " が " + p.streak_broken_months +
                     " カ月ぶりに前年割れ（" + p.period_key + " " + fmt(p.value, s.metric_id) + "）");
        }
      });
    });
    $("highlights").innerHTML = lines.length
      ? "<h3>ハイライト</h3><ul>" + lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>"
      : "";

    // entity_type == association の業態について既存店売上前年比の最新値
    var html = "";
    D.segments.forEach(function (seg) {
      if (seg.entity_type !== "association") return;
      var hit = D.series.filter(function (s) {
        return s.segment_id === seg.segment_id &&
               s.metric_id === "existing-store-sales-yoy" &&
               s.source_authority === seg.default_source_authority;
      })[0];
      var value = "データなし", cls = "", sub = "";
      if (hit && hit.points.length) {
        var pts = hit.points.slice().sort(function (a, b) {
          return a.period_key < b.period_key ? -1 : 1; });
        var last = pts[pts.length - 1], prev = pts[pts.length - 2];
        value = fmt(last.value, hit.metric_id);
        cls = last.value >= 0 ? "pos" : "neg";
        sub = last.period_key + (prev ? "（前月 " + fmt(prev.value, hit.metric_id) + " → 当月 " + value + "）" : "");
      }
      html += '<div class="card"><div class="name">' + esc(seg.name) + '</div>' +
              '<div class="value ' + cls + '">' + esc(value) + '</div>' +
              '<div class="sub">' + esc(sub || "既存店売上高前年比") + '</div></div>';
    });
    $("cards").innerHTML = html;
    $("meta").textContent =
      "最新ダイジェスト " + D.meta.generated_from_digest_max_date +
      " ／ 走査 " + D.meta.digest_files_scanned + " ファイル" +
      " ／ observation " + D.meta.observation_count + " 件" +
      " ／ 未解決 " + D.meta.unresolved_count + " 件";
  }

  /* ---- SC-02 業態別トレンド ---------------------------------------------- */
  function optionsFor(sel, items, valueOf, labelOf) {
    sel.innerHTML = items.map(function (it) {
      return '<option value="' + esc(valueOf(it)) + '">' + esc(labelOf(it)) + "</option>";
    }).join("");
  }
  function setupSc02() {
    // R7: 粒度が違う業態はラベルで明示する（silent に隠さない）
    optionsFor($("sc02-segment"), D.segments, function (s) { return s.segment_id; },
      function (s) { return s.name + (s.different_granularity ? "（他業態と粒度が異なるため単独表示）" : ""); });
    optionsFor($("sc02-metric"), D.metrics, function (m) { return m.metric_id; },
      function (m) { return m.name; });
    ["sc02-segment", "sc02-metric", "sc02-authority"].forEach(function (id) {
      $(id).addEventListener("change", function () { drawSc02(id === "sc02-authority"); });
    });
    drawSc02(false);
  }
  function drawSc02(keepAuthority) {
    var seg = $("sc02-segment").value, met = $("sc02-metric").value;
    var all = D.series.filter(function (s) {
      return s.segment_id === seg && s.metric_id === met; });
    var codes = [];
    all.forEach(function (s) { if (codes.indexOf(s.source_authority) < 0) codes.push(s.source_authority); });
    var sel = $("sc02-authority");
    var current = keepAuthority ? sel.value : null;
    // R2: 既定値は選択中業態の default_source_authority（= 協会統計）
    var preferred = (segById[seg] || {}).default_source_authority;
    optionsFor(sel, codes, function (c) { return c; }, authLabel);
    sel.value = (current && codes.indexOf(current) >= 0) ? current
      : (codes.indexOf(preferred) >= 0 ? preferred : codes[0] || "");

    // R3: 複数主体がある場合は母集団の違いを常時表示する
    var notice = $("sc02-notice");
    if (codes.length > 1) {
      notice.hidden = false;
      notice.textContent = "この業態には " + codes.map(authLabel).join(" / ") +
        " の " + codes.length + " 系統があります。母集団が異なるため数値は一致しません。";
    } else { notice.hidden = true; }

    var shown = all.filter(function (s) { return s.source_authority === sel.value; });
    renderLineChart("sc02-chart", shown, function (s) {
      return metName(s.metric_id) + "（" + s.scope + "）"; }, $("sc02-subtitle"), $("sc02-empty"));
  }

  /* ---- SC-03 指標横断比較 ------------------------------------------------- */
  function setupSc03() {
    optionsFor($("sc03-metric"), D.metrics, function (m) { return m.metric_id; },
      function (m) { return m.name; });
    ["sc03-metric", "sc03-authority", "sc03-include-macro"].forEach(function (id) {
      $(id).addEventListener("change", function () { drawSc03(id === "sc03-authority"); });
    });
    drawSc03(false);
  }
  function drawSc03(keepAuthority) {
    var met = $("sc03-metric").value;
    var all = D.series.filter(function (s) { return s.metric_id === met; });
    var codes = [];
    all.forEach(function (s) { if (codes.indexOf(s.source_authority) < 0) codes.push(s.source_authority); });
    var sel = $("sc03-authority");
    var current = keepAuthority ? sel.value : null;
    optionsFor(sel, codes, function (c) { return c; }, authLabel);
    sel.value = (current && codes.indexOf(current) >= 0) ? current : codes[0] || "";

    // R5: 発表主体を先に単一選択させてから業態を横並びにする
    var picked = all.filter(function (s) { return s.source_authority === sel.value; });
    var split = splitGranularity(picked);
    // R6: 小売業全体は既定で除外。含める場合も**単独系列**にする
    var shown = $("sc03-include-macro").checked ? split.macro : split.normal;
    renderLineChart("sc03-chart", shown, function (s) { return segName(s.segment_id); },
      $("sc03-subtitle"), $("sc03-empty"));
  }

  /* ---- SC-04 データテーブル / CSV ---------------------------------------- */
  var COLS = ["業態", "指標", "スコープ", "発表主体", "期間", "値", "連続記録", "抽出", "要確認", "出典"];
  function rows() {
    var out = [];
    D.series.forEach(function (s) {
      s.points.forEach(function (p) {
        out.push([segName(s.segment_id), metName(s.metric_id), s.scope,
                  authLabel(s.source_authority), p.period_key,
                  p.value === null ? (p.sign_only || "—") : fmt(p.value, s.metric_id),
                  p.streak_broken_months || "", p.method,
                  p.needs_source_check ? "要" : "", p.article_id]);
      });
    });
    return out.sort(function (a, b) { return (a[0] + a[1] + a[4]) < (b[0] + b[1] + b[4]) ? -1 : 1; });
  }
  function renderTable() {
    var data = rows();
    $("table").innerHTML =
      "<thead><tr>" + COLS.map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead><tbody>" +
      data.map(function (r) {
        return "<tr>" + r.map(function (c, i) {
          return '<td' + (i === 5 ? ' class="num"' : "") + ">" + esc(c) + "</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody>";
    $("csv").addEventListener("click", function () {
      var csv = [COLS].concat(rows()).map(function (r) {
        return r.map(function (c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(",");
      }).join("\r\n");
      var url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
      var a = document.createElement("a");
      a.href = url; a.download = "retail-stats.csv"; a.click(); URL.revokeObjectURL(url);
    });
  }

  /* ---- SC-05 出典一覧 ----------------------------------------------------- */
  function renderSources() {
    $("sources").innerHTML =
      "<thead><tr><th>掲載日</th><th>掲載回数</th><th>ソース</th><th>タイトル</th></tr></thead><tbody>" +
      D.articles.map(function (a) {
        return "<tr><td>" + esc(a.first_published_date) + "</td><td class='num'>" + a.appeared_count +
          "</td><td>" + esc(a.source) + '</td><td><a href="' + esc(a.url) +
          '" rel="noreferrer noopener">' + esc(a.title) + "</a></td></tr>";
      }).join("") + "</tbody>";
  }

  /* ---- SC-06 データ品質（P1 / P2 / P3）------------------------------------ */
  var IN_SCOPE_REASONS = ["no_segment_match", "no_metric_match", "no_metric_match_in_multi_value",
                          "no_numeric", "ambiguous_period", "low_confidence", "llm_schema_error"];
  function renderQuality() {
    var q = D.quality, n5 = q.nfr05, n4 = q.nfr04;
    $("p1").innerHTML =
      "<h3>P1 抽出品質</h3>" +
      "<p>対象内行 <b>" + n5.denominator + "</b> 件中 <b>" + n5.numerator + "</b> 件を抽出" +
      ' （<span class="kpi ' + (n5.met ? "good" : "bad") + '">' + (n5.rate * 100).toFixed(1) + "%</span>" +
      " / 目標 " + (n5.target * 100).toFixed(0) + "% / <b>" + (n5.met ? "達成" : "未達") + "</b>）</p>" +
      "<p class='sub'>分母の定義: <b>発表主体が協会統計・マクロ統計である行</b>。個社開示・非統計記事は" +
      "対象範囲外として分母から除外しています。</p>" +
      "<p>NFR-04 主要 4 業態の月次既存店: " + n4.covered.length + " / 4 " +
      '（<span class="' + (n4.met ? "good" : "bad") + '">' + (n4.rate * 100).toFixed(0) + "%</span>" +
      " / 目標 " + (n4.target * 100).toFixed(0) + "%）" +
      (n4.missing.length ? " 欠落: " + esc(n4.missing.join(", ")) : "") + "</p>" +
      "<p>抽出方法: " + Object.keys(q.by_method).map(function (k) {
        return k + " " + q.by_method[k]; }).join(" / ") +
      " ／ 回収余地（no_metric_match）: <b>" + (q.by_reason_code.no_metric_match || 0) + "</b> 件</p>";

    var p2 = "<h3>P2 未解決（要改善）</h3>";
    IN_SCOPE_REASONS.forEach(function (code) {
      var rows = D.unresolved.filter(function (u) { return u.reason_code === code; });
      if (!rows.length) return;
      p2 += "<details><summary>" + code + "（" + rows.length + " 件）" +
        (code === "no_segment_match" ? " — <b>カタログに業態行を追加すべき候補</b>" : "") +
        "</summary>" + rows.slice(0, 20).map(function (u) {
          return "<pre>" + esc(u.raw_line) + "</pre>"; }).join("") + "</details>";
    });
    $("p2").innerHTML = p2;

    var oos = D.unresolved.filter(function (u) { return u.reason_code === "out_of_scope"; });
    var byKind = { company_disclosure: [], non_statistical: [] };
    oos.forEach(function (u) { (byKind[u.out_of_scope_kind] || []).push(u); });
    $("p3").innerHTML =
      "<h3>P3 対象外（意図的除外）</h3>" +
      "<p class='notice'>これらは抽出の失敗ではなく、本システムの対象範囲外として意図的に除外した記事です。" +
      "NFR-05 の分母には含みません。</p>" +
      "<p>個社開示 <b>" + byKind.company_disclosure.length + "</b> 件 ／ " +
      "非統計記事 <b>" + byKind.non_statistical.length + "</b> 件</p>" +
      Object.keys(byKind).map(function (k) {
        return "<details><summary>" + (k === "company_disclosure" ? "個社開示" : "非統計記事") +
          "（" + byKind[k].length + " 件・代表 10 件）</summary>" +
          byKind[k].slice(0, 10).map(function (u) {
            return "<pre>" + esc(u.raw_line) + "</pre>"; }).join("") + "</details>";
      }).join("");
  }

  /* ---- タブ --------------------------------------------------------------- */
  var VIEWS = [["sc01", "概観"], ["sc02", "業態別トレンド"], ["sc03", "指標横断比較"],
               ["sc04", "データテーブル"], ["sc05", "出典一覧"], ["sc06", "データ品質"]];
  function setupTabs() {
    $("tabs").innerHTML = VIEWS.map(function (v, i) {
      return '<button data-view="' + v[0] + '" aria-selected="' + (i === 0) + '">' + v[1] + "</button>";
    }).join("");
    Array.prototype.forEach.call($("tabs").children, function (btn) {
      btn.addEventListener("click", function () {
        VIEWS.forEach(function (v) { $(v[0]).hidden = v[0] !== btn.dataset.view; });
        Array.prototype.forEach.call($("tabs").children, function (b) {
          b.setAttribute("aria-selected", String(b === btn)); });
        Object.keys(charts).forEach(function (k) { charts[k].resize(); });
      });
    });
  }

  renderOverview(); setupTabs(); setupSc02(); setupSc03();
  renderTable(); renderSources(); renderQuality();
})();
