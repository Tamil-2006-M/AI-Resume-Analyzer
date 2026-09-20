/* ==================================================================
   charts.js - AI Resume Analyzer
   ==================================================================
   Draws the dashboard charts with Chart.js.

   How the data gets here
   ----------------------
   app.py builds a plain dictionary and the template writes it into the
   page as JSON:

       <script type="application/json" id="chartData">{...}</script>

   We read that element's text and JSON.parse it. Nothing is ever pasted
   straight into a JavaScript statement, so a strange character inside a
   skill name can never break - or hijack - our code.

   Design rules followed here (and worth explaining in a viva)
   -----------------------------------------------------------
   * ONE colour per chart. Every chart shows a single series, so every
     bar is the same colour. Colouring bars darker-where-bigger would
     encode the value twice (length AND shade) and waste the only free
     visual channel.
   * No legend on a single-series chart - the card title already says
     what is plotted, so a legend box with one swatch just repeats it.
   * Thin marks, solid hairline gridlines, no chart junk. The data is
     the only thing allowed to be loud.
   * Every chart has a matching TABLE underneath, inside a <details>.
     A tooltip must never be the only way to read a value - that locks
     out screen-reader and keyboard users.
   ================================================================== */

document.addEventListener("DOMContentLoaded", function () {

    // Chart.js is loaded from a CDN. If the user is offline it will be
    // missing, and calling it would throw and break the rest of the page.
    if (typeof Chart === "undefined") {
        return;
    }

    // ---------------- Shared look ----------------
    // These mirror the CSS variables in style.css. Keeping them in one
    // object means every chart on the site stays visually consistent.
    const INK = "#1e2235";        // primary text
    const INK_MUTED = "#6b7280";  // axis labels
    const GRID = "#e5e7eb";       // hairline gridlines
    const SURFACE = "#ffffff";    // card background
    const SERIES = "#4f46e5";     // the one brand hue used by every mark
    const SERIES_WASH = "rgba(79, 70, 229, 0.10)";  // 10% area fill

    // Applied to every chart so we never repeat ourselves.
    Chart.defaults.font.family =
        '"Segoe UI", system-ui, -apple-system, Arial, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = INK_MUTED;

    // A tooltip style used by all charts.
    const TOOLTIP = {
        backgroundColor: INK,
        titleColor: "#ffffff",
        bodyColor: "#e5e7eb",
        padding: 10,
        cornerRadius: 8,
        displayColors: false,     // one series, so a colour swatch says nothing
        titleFont: { weight: "600" },
    };

    /**
     * Read and parse the JSON block the server wrote into the page.
     * Returns null if it is missing or malformed, so each chart can
     * simply skip rendering instead of throwing.
     */
    function readData(elementId) {
        const element = document.getElementById(elementId);
        if (!element) {
            return null;
        }
        try {
            return JSON.parse(element.textContent);
        } catch (error) {
            // Never let a data problem break the whole page.
            console.warn("Could not parse chart data:", error);
            return null;
        }
    }

    // =================================================================
    // CHART 1 - Skills by category  (horizontal bar)
    // =================================================================
    // Why a bar chart and not a pie?
    // The categories have close values, and a pie makes close values
    // almost impossible to compare - you cannot judge the difference
    // between a 55-degree slice and a 62-degree one. Bar length you can
    // compare instantly. A pie is only reasonable for a rough
    // part-to-whole glance with very few slices.
    //
    // Horizontal rather than vertical because the labels are long
    // ("Programming Languages"). Vertical columns would force the text
    // to rotate 45 degrees, which is hard to read.
    function drawSkillsChart(data) {
        const canvas = document.getElementById("skillsChart");
        if (!canvas || !data || !data.labels.length) {
            return;
        }

        new Chart(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: SERIES,
                    hoverBackgroundColor: "#4338ca",

                    // 4px rounded end on the data side, square at the
                    // baseline, so the bar clearly grows from the axis.
                    borderRadius: { topLeft: 0, bottomLeft: 0,
                                    topRight: 4, bottomRight: 4 },
                    borderSkipped: false,

                    // Cap the thickness. Letting a bar fill its whole
                    // slot removes the air between bars and reads heavy.
                    maxBarThickness: 22,
                }],
            },
            options: {
                indexAxis: "y",              // horizontal bars
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    // Single series -> no legend. The card title says it.
                    legend: { display: false },
                    tooltip: Object.assign({}, TOOLTIP, {
                        callbacks: {
                            title: function (items) {
                                return items[0].label;
                            },
                            label: function (item) {
                                const count = item.raw;
                                return count + (count === 1 ? " skill" : " skills");
                            },
                            // Show WHICH skills, not just how many.
                            afterLabel: function (item) {
                                const detail = data.detail[item.dataIndex] || "";
                                // Wrap long lists so the tooltip stays narrow.
                                return detail.match(/.{1,46}(,\s|$)/g) || detail;
                            },
                        },
                    }),
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        // Whole numbers only - "2.5 skills" is nonsense.
                        ticks: { precision: 0, color: INK_MUTED },
                        grid: { color: GRID, drawTicks: false },
                        border: { display: false },
                    },
                    y: {
                        ticks: { color: INK_MUTED },
                        // No vertical gridlines behind horizontal bars -
                        // the bars themselves carry the eye.
                        grid: { display: false },
                        border: { display: false },
                    },
                },
            },
        });
    }

    // =================================================================
    // CHART 2 - ATS score over time  (line)
    // =================================================================
    // Only drawn when the database holds two or more past uploads for
    // this candidate. One dot is not a trend, and a chart showing one
    // point is worse than no chart at all.
    function drawHistoryChart(history) {
        const canvas = document.getElementById("historyChart");
        if (!canvas || !history || history.length < 2) {
            return;
        }

        new Chart(canvas, {
            type: "line",
            data: {
                labels: history.map(function (point) { return point.date; }),
                datasets: [{
                    data: history.map(function (point) { return point.score; }),
                    borderColor: SERIES,
                    borderWidth: 2,              // thin line, never thick
                    tension: 0.3,                // gentle curve
                    fill: true,
                    backgroundColor: SERIES_WASH, // 10% wash, not a block

                    pointBackgroundColor: SERIES,
                    // A 2px ring in the surface colour keeps the dot
                    // readable where it sits on top of the line.
                    pointBorderColor: SURFACE,
                    pointBorderWidth: 2,
                    pointRadius: 4,              // >= 8px across
                    // A bigger invisible hit area, so the dot is easy to
                    // hover. Aiming at an 8px target is frustrating.
                    pointHitRadius: 18,
                    pointHoverRadius: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, TOOLTIP, {
                        callbacks: {
                            label: function (item) {
                                return item.raw + " / 100";
                            },
                            afterLabel: function (item) {
                                return history[item.dataIndex].file;
                            },
                        },
                    }),
                },
                scales: {
                    y: {
                        min: 0,
                        max: 100,
                        ticks: { stepSize: 25, color: INK_MUTED },
                        grid: { color: GRID, drawTicks: false },
                        border: { display: false },
                    },
                    x: {
                        ticks: { color: INK_MUTED, maxRotation: 0,
                                 autoSkipPadding: 12 },
                        grid: { display: false },
                        border: { color: GRID },
                    },
                },
            },
        });
    }

    // =================================================================
    // CHART 3 - ATS score distribution  (history page, horizontal bar)
    // =================================================================
    // How many resumes landed in each grade band. The bands are ordered
    // (Poor -> Excellent), so the axis order carries that meaning and
    // one colour is enough.
    function drawDistributionChart(distribution) {
        const canvas = document.getElementById("distributionChart");
        if (!canvas || !distribution || !distribution.length) {
            return;
        }

        new Chart(canvas, {
            type: "bar",
            data: {
                labels: distribution.map(function (row) { return row.band; }),
                datasets: [{
                    data: distribution.map(function (row) { return row.total; }),
                    backgroundColor: SERIES,
                    hoverBackgroundColor: "#4338ca",
                    borderRadius: { topLeft: 0, bottomLeft: 0,
                                    topRight: 4, bottomRight: 4 },
                    borderSkipped: false,
                    maxBarThickness: 22,
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, TOOLTIP, {
                        callbacks: {
                            label: function (item) {
                                const n = item.raw;
                                return n + (n === 1 ? " resume" : " resumes");
                            },
                        },
                    }),
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: { precision: 0, color: INK_MUTED },
                        grid: { color: GRID, drawTicks: false },
                        border: { display: false },
                    },
                    y: {
                        ticks: { color: INK_MUTED },
                        grid: { display: false },
                        border: { display: false },
                    },
                },
            },
        });
    }

    // ---------------- Run them ----------------
    const resultData = readData("chartData");
    if (resultData) {
        drawSkillsChart(resultData.skillsByCategory);
        drawHistoryChart(resultData.scoreHistory);
    }

    const distributionData = readData("distributionData");
    if (distributionData) {
        drawDistributionChart(distributionData);
    }
});
