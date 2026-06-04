document.addEventListener("DOMContentLoaded", function () {
  animateStatValues();
  initAdminWidgetPersonalization();

  if (typeof ApexCharts === "undefined") return;

  window.Apex = Object.assign({}, window.Apex || {}, {
    chart: {
      toolbar: { show: false },
      foreColor: "#506985",
      fontFamily: '"Trebuchet MS", "Segoe UI", sans-serif',
      animations: {
        enabled: true,
        easing: "easeinout",
        speed: 640,
        animateGradually: { enabled: true, delay: 90 },
        dynamicAnimation: { enabled: true, speed: 320 },
      },
    },
    dataLabels: { enabled: false },
    stroke: { width: 3, curve: "smooth" },
    grid: {
      borderColor: "#e6edf6",
      strokeDashArray: 4,
      xaxis: { lines: { show: false } },
    },
    tooltip: { theme: "light" },
    legend: {
      position: "top",
      fontSize: "12px",
      labels: { colors: "#48627f" },
    },
    noData: {
      text: "No data available yet",
      align: "center",
      verticalAlign: "middle",
      style: { color: "#8da2ba", fontSize: "13px" },
    },
  });

  var palette = {
    blue: "#2a3f54",
    teal: "#1abb9c",
    amber: "#f0ad4e",
    red: "#d9534f",
    violet: "#4f6380",
    slate: "#8ba2bb",
  };

  var dashboardChartData = {};
  var chartDataEl = document.getElementById("dashboard-chart-data");
  if (chartDataEl) {
    try {
      dashboardChartData = JSON.parse(chartDataEl.textContent || "{}");
    } catch (err) {
      dashboardChartData = {};
    }
  }

  function renderChart(selector, options) {
    var el = document.querySelector(selector);
    if (!el) return;
    if (el.dataset.chartRendered === "true") return;
    try {
      new ApexCharts(el, options).render();
      el.dataset.chartRendered = "true";
    } catch (error) {
      // Keep dashboard usable even if one chart fails.
      // eslint-disable-next-line no-console
      console.warn("Chart render failed for", selector, error);
    }
  }

  renderChart("#chart-class-subject", {
    chart: { type: "bar", height: 300 },
    series: [
      { name: "Class Average", data: dashboardChartData.class_performance_values || [] },
      { name: "Subject Average", data: dashboardChartData.subject_performance_values || [] },
    ],
    xaxis: { categories: dashboardChartData.class_performance_labels || [] },
    colors: [palette.blue, palette.teal],
    plotOptions: {
      bar: {
        borderRadius: 8,
        columnWidth: "54%",
      },
    },
    legend: { position: "top" },
  });

  renderChart("#chart-class-readiness", {
    chart: { type: "bar", height: 300 },
    series: [{ name: "Completion %", data: dashboardChartData.class_readiness_values || [] }],
    xaxis: { categories: dashboardChartData.class_readiness_labels || [] },
    colors: [palette.blue],
    plotOptions: { bar: { borderRadius: 8, columnWidth: "58%" } },
    yaxis: { max: 100, labels: { formatter: function (v) { return v + "%"; } } },
  });

  renderChart("#chart-class-assessment-volume", {
    chart: { type: "bar", height: 280, stacked: true },
    series: [
      { name: "Assessments", data: dashboardChartData.class_assessment_totals || [] },
      { name: "With Results", data: dashboardChartData.class_assessment_completed || [] },
    ],
    xaxis: { categories: dashboardChartData.class_readiness_labels || [] },
    colors: [palette.slate, palette.teal],
    plotOptions: { bar: { borderRadius: 8, columnWidth: "58%" } },
    legend: { position: "bottom" },
  });

  renderChart("#chart-teacher-progress", {
    chart: { type: "line", height: 260 },
    series: [{ name: "Assessment Progress", data: [40, 55, 68, 72] }],
    xaxis: { categories: ["Week 1", "Week 2", "Week 3", "Week 4"] },
    colors: [palette.violet],
    markers: {
      size: 4,
      strokeWidth: 2,
      strokeColors: "#ffffff",
      hover: { size: 6 },
    },
  });

  renderChart("#chart-grade-distribution", {
    chart: { type: "donut", height: 285 },
    series: dashboardChartData.grade_distribution_values || [],
    labels: dashboardChartData.grade_distribution_labels || [],
    colors: dashboardChartData.grade_distribution_colors || [
      palette.teal,
      palette.blue,
      palette.amber,
      "#fb7185",
      "#7c83fd",
    ],
    legend: { position: "bottom" },
    plotOptions: {
      pie: {
        donut: {
          size: "68%",
          labels: {
            show: true,
            total: {
              show: true,
              label: "Results",
              formatter: function (w) {
                var total = 0;
                var series = (w && w.globals && w.globals.seriesTotals) || [];
                for (var i = 0; i < series.length; i += 1) total += series[i] || 0;
                return total;
              },
            },
          },
        },
      },
    },
  });

  renderChart("#chart-performance-trends", {
    chart: { type: "line", height: 300 },
    series: [{ name: "Average Score", data: dashboardChartData.performance_trend_values || [] }],
    xaxis: { categories: dashboardChartData.performance_trend_labels || [] },
    colors: [palette.blue],
    markers: {
      size: 4,
      strokeWidth: 2,
      strokeColors: "#ffffff",
    },
  });

  renderChart("#chart-result-status", {
    chart: { type: "radialBar", height: 270 },
    series: [dashboardChartData.result_status_percent || 0],
    labels: ["Verified"],
    colors: [palette.teal],
    plotOptions: {
      radialBar: {
        hollow: { size: "56%" },
        track: { background: "#edf2f8" },
        dataLabels: {
          name: { color: "#6e84a0", fontWeight: 700 },
          value: { fontSize: "26px", fontWeight: 700, color: "#20324a" },
        },
      },
    },
  });

  renderChart("#chart-enrollment-trend", {
    chart: { type: "line", height: 270 },
    series: [
      { name: "Active", data: dashboardChartData.enrollment_trend_active_values || [] },
      { name: "Inactive", data: dashboardChartData.enrollment_trend_inactive_values || [] },
    ],
    xaxis: { categories: dashboardChartData.enrollment_trend_labels || [] },
    colors: [palette.blue, palette.red],
    markers: {
      size: 4,
      strokeWidth: 2,
      strokeColors: "#ffffff",
    },
  });

  renderChart("#chart-attendance-heatmap", {
    chart: { type: "heatmap", height: 300 },
    series: dashboardChartData.attendance_heatmap_series || [],
    xaxis: { labels: { rotate: -42 } },
    plotOptions: {
      heatmap: {
        radius: 4,
        colorScale: {
          ranges: [
            { from: 0, to: 49.99, color: "#e55555", name: "< 50%" },
            { from: 50, to: 74.99, color: "#f0ad4e", name: "50-74%" },
            { from: 75, to: 89.99, color: "#22a7d4", name: "75-89%" },
            { from: 90, to: 100, color: "#18a88a", name: "90-100%" },
          ],
        },
      },
    },
  });

  var attendanceTrendPoints =
    (dashboardChartData.attendance_heatmap_series &&
      dashboardChartData.attendance_heatmap_series[0] &&
      dashboardChartData.attendance_heatmap_series[0].data) ||
    [];
  var attendanceTrendLabels = [];
  var attendanceTrendValues = [];
  for (var index = 0; index < attendanceTrendPoints.length; index += 1) {
    var point = attendanceTrendPoints[index] || {};
    attendanceTrendLabels.push(point.x || "");
    attendanceTrendValues.push(Number(point.y || 0));
  }

  renderChart("#chart-attendance-trend", {
    chart: { type: "line", height: 240 },
    series: [{ name: "Attendance %", data: attendanceTrendValues }],
    xaxis: { categories: attendanceTrendLabels },
    colors: [palette.teal],
    yaxis: {
      min: 0,
      max: 100,
      labels: {
        formatter: function (value) {
          return Math.round(value) + "%";
        },
      },
    },
    markers: {
      size: 4,
      strokeWidth: 2,
      strokeColors: "#ffffff",
    },
  });

  renderChart("#chart-results-class-distribution", {
    chart: { type: "bar", stacked: true, height: 280 },
    series: dashboardChartData.class_results_distribution_series || [],
    xaxis: { categories: dashboardChartData.class_results_distribution_labels || [] },
    colors: [palette.blue, palette.teal, palette.amber, palette.red, "#6b7dff", "#7c3aed"],
    plotOptions: { bar: { borderRadius: 6, columnWidth: "58%" } },
  });

  renderChart("#chart-fees-collection", {
    chart: { type: "bar", height: 285 },
    series: [
      { name: "Expected", data: dashboardChartData.fees_collection_expected || [] },
      { name: "Collected", data: dashboardChartData.fees_collection_collected || [] },
    ],
    xaxis: { categories: dashboardChartData.fees_collection_labels || [] },
    colors: [palette.slate, palette.blue],
    plotOptions: { bar: { borderRadius: 8, columnWidth: "55%" } },
  });

  renderChart("#chart-expenses-breakdown", {
    chart: { type: "donut", height: 280 },
    series: dashboardChartData.expenses_values || [],
    labels: dashboardChartData.expenses_labels || [],
    colors: [palette.blue, palette.teal, palette.amber, palette.red, "#6b7dff"],
    legend: { position: "bottom" },
  });

  renderChart("#chart-fees-trend", {
    chart: { type: "line", height: 260 },
    series: [{ name: "Collected", data: dashboardChartData.fees_trend_values || [] }],
    xaxis: { categories: dashboardChartData.fees_trend_labels || [] },
    colors: [palette.blue],
    markers: { size: 4, strokeWidth: 2, strokeColors: "#ffffff" },
  });

  renderChart("#chart-revenue-vs-expenses", {
    chart: { type: "area", height: 300 },
    series: [
      { name: "Revenue", data: dashboardChartData.fees_trend_values || [] },
      { name: "Expenses", data: dashboardChartData.expenses_trend_values || [] },
    ],
    xaxis: {
      categories: dashboardChartData.revenue_expense_labels || dashboardChartData.fees_trend_labels || [],
    },
    colors: [palette.blue, palette.amber],
    fill: {
      type: "gradient",
      gradient: {
        shadeIntensity: 1,
        opacityFrom: 0.35,
        opacityTo: 0.06,
        stops: [0, 90, 100],
      },
    },
  });

  renderChart("#chart-payment-methods", {
    chart: { type: "donut", height: 300 },
    series: dashboardChartData.payment_method_values || [],
    labels: dashboardChartData.payment_method_labels || [],
    colors: [palette.blue, palette.teal, palette.amber, palette.red, "#6b7dff", "#334155"],
    legend: { position: "bottom" },
  });

  renderChart("#chart-calendar-overview", {
    chart: { type: "bar", height: 200 },
    series: [{ name: "Events", data: [2, 1, 3, 0, 2, 1, 4] }],
    xaxis: { categories: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] },
    colors: [palette.teal],
    plotOptions: { bar: { borderRadius: 6, columnWidth: "50%" } },
  });
});

function animateStatValues() {
  var nodes = document.querySelectorAll(".stat-value");
  if (!nodes.length) return;

  var regex = /(-?[\d,.]+(?:\.\d+)?)/;

  Array.prototype.forEach.call(nodes, function (node) {
    var original = (node.textContent || "").trim();
    var match = original.match(regex);
    if (!match) return;

    var numericToken = match[0];
    var target = parseFloat(numericToken.replace(/,/g, ""));
    if (!isFinite(target)) return;

    var decimals = numericToken.indexOf(".") > -1 ? numericToken.split(".")[1].length : 0;
    var prefix = original.slice(0, match.index);
    var suffix = original.slice(match.index + numericToken.length);
    var start = 0;
    var duration = 680;
    var startTime = null;

    function frame(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = start + (target - start) * eased;
      var formatted;

      if (decimals > 0) {
        formatted = current.toLocaleString(undefined, {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        });
      } else {
        formatted = Math.round(current).toLocaleString();
      }

      node.textContent = prefix + formatted + suffix;
      if (progress < 1) requestAnimationFrame(frame);
      else node.textContent = original;
    }

    requestAnimationFrame(frame);
  });
}

function initAdminWidgetPersonalization() {
  var modal = document.getElementById("adminWidgetModal");
  if (!modal) return;

  var storageKey = "adminDashboardWidgetsV1";
  var toggles = Array.prototype.slice.call(
    document.querySelectorAll(".admin-widget-toggle[data-widget-id]")
  );
  if (!toggles.length) return;

  var widgets = {};
  Array.prototype.slice.call(document.querySelectorAll("[data-admin-widget]")).forEach(function (el) {
    widgets[el.getAttribute("data-admin-widget")] = el;
  });

  function readState() {
    try {
      var raw = localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : {};
    } catch (err) {
      return {};
    }
  }

  function writeState(state) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state));
    } catch (err) {
      // no-op
    }
  }

  function collectStateFromToggles() {
    var state = {};
    toggles.forEach(function (toggle) {
      var id = toggle.getAttribute("data-widget-id");
      if (!id) return;
      state[id] = !!toggle.checked;
    });
    return state;
  }

  function applyState(state) {
    toggles.forEach(function (toggle) {
      var id = toggle.getAttribute("data-widget-id");
      if (!id) return;
      var enabled = Object.prototype.hasOwnProperty.call(state, id) ? !!state[id] : true;
      toggle.checked = enabled;
      if (widgets[id]) {
        widgets[id].style.display = enabled ? "" : "none";
      }
    });
    window.dispatchEvent(new Event("resize"));
  }

  applyState(readState());

  var applyButton = document.getElementById("applyAdminWidgetsBtn");
  if (applyButton) {
    applyButton.addEventListener("click", function () {
      var state = collectStateFromToggles();
      writeState(state);
      applyState(state);
      if (window.jQuery) window.jQuery("#adminWidgetModal").modal("hide");
    });
  }

  var resetButton = document.getElementById("resetAdminWidgetsBtn");
  if (resetButton) {
    resetButton.addEventListener("click", function () {
      toggles.forEach(function (toggle) {
        toggle.checked = true;
      });
      var defaultState = collectStateFromToggles();
      writeState(defaultState);
      applyState(defaultState);
    });
  }
}
