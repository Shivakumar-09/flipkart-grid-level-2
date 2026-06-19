document.addEventListener("DOMContentLoaded", () => {

    // ── Toast Notification System (replaces all alert() calls) ──────────
    function showToast(message, type = "info", duration = 4000) {
        const container = document.getElementById("toast-container");
        if (!container) return;
        const toast = document.createElement("div");
        const colors = {
            success: { bg: "rgba(16,185,129,0.95)",  border: "#10b981" },
            error:   { bg: "rgba(239,68,68,0.95)",   border: "#ef4444" },
            warning: { bg: "rgba(245,158,11,0.95)",  border: "#f59e0b" },
            info:    { bg: "rgba(0,240,255,0.92)",   border: "#00f0ff" }
        };
        const c = colors[type] || colors.info;
        const icons = { success: "✅", error: "❌", warning: "⚠️", info: "ℹ️" };
        toast.style.cssText = [
            `background:${c.bg}`,
            `border:1px solid ${c.border}`,
            "border-radius:10px",
            "padding:12px 20px",
            "color:#fff",
            "font-family:Outfit,sans-serif",
            "font-size:0.88rem",
            "font-weight:600",
            "max-width:420px",
            "text-align:center",
            "box-shadow:0 8px 32px rgba(0,0,0,0.4)",
            "pointer-events:auto",
            "cursor:pointer",
            "transition:opacity 0.4s ease, transform 0.4s ease",
            "opacity:0",
            "transform:translateY(20px)",
            "backdrop-filter:blur(10px)",
            "-webkit-backdrop-filter:blur(10px)"
        ].join(";");
        toast.innerHTML = `${icons[type] || ""} ${message}`;
        container.appendChild(toast);
        requestAnimationFrame(() => {
            toast.style.opacity = "1";
            toast.style.transform = "translateY(0)";
        });
        const dismiss = () => {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(20px)";
            setTimeout(() => toast.remove(), 400);
        };
        toast.addEventListener("click", dismiss);
        setTimeout(dismiss, duration);
    }

    // ── Prevent browser form re-submission on page refresh ───────────────
    if (window.history.replaceState) {
        window.history.replaceState(null, null, window.location.href);
    }
    const uploadFormReset = document.getElementById("upload-form");
    if (uploadFormReset) uploadFormReset.reset();

    // 1. Navigation Panel Switches
    const navLinks = document.querySelectorAll(".nav-links a");
    const sections = document.querySelectorAll(".dashboard-section");

    navLinks.forEach(link => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            navLinks.forEach(l => l.classList.remove("active"));
            sections.forEach(s => s.classList.remove("active"));

            link.classList.add("active");
            const targetHref = link.getAttribute("href");
            const targetSection = document.querySelector(targetHref);
            if (targetSection) {
                targetSection.classList.add("active");
            }

            // Map resize fix on tab switch
            if (targetHref === "#command-center" && trafficMapInstance) {
                setTimeout(() => {
                    trafficMapInstance.invalidateSize();
                }, 200);
            }

            // Render Analytics Tab charts if switching to City Analytics
            if (targetHref === "#city-analytics") {
                if (!chartTelemetry) {
                    loadChartTelemetry();
                } else {
                    const activeTabBtn = document.querySelector(".chart-tab-btn.active");
                    const currentChart = activeTabBtn ? activeTabBtn.getAttribute("data-chart") : "hourly";
                    renderAnalyticsTabChart(currentChart);
                }
            }
        });
    });

    // 2. Fetch and Load Dashboard Telemetry & Chart Data
    let trendChartInstance = null;
    let breakdownChartInstance = null;
    let peakChartInstance = null;
    let weekendChartInstance = null;

    // Command Center and Detailed Charts state
    let trafficMapInstance = null;
    let analyticsChartInstance = null;
    let chartTelemetry = null;
    let liveAlertsCount = 0;

    // Safety Hub & Challan Modal Global State
    let loadedLogs = [];
    let youtubeLinks = {};
    let currentQuestionIndex = 0;
    let quizScore = 0;
    let selectedOptionIndex = null;

    function animateValue(element, start, end, duration) {
        if (!element) return;
        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / duration, 1);
            element.textContent = Math.floor(progress * (end - start) + start);
            if (progress < 1) {
                window.requestAnimationFrame(step);
            }
        };
        window.requestAnimationFrame(step);
    }

    // --- Traffic Command Center Implementation (v4.0) ---
    function initCommandCenter() {
        fetch("/api/command_center")
            .then(res => res.json())
            .then(data => {
                // Populate KPIs
                const vTodayEl = document.getElementById("cc-violations-today");
                const riskZonesEl = document.getElementById("cc-risk-zones");
                const pendingEl = document.getElementById("cc-pending-challans");
                const policeAlertsEl = document.getElementById("cc-police-alerts");
                
                animateValue(vTodayEl, 0, parseInt(data.kpis.total_violations_today) || 0, 1000);
                animateValue(riskZonesEl, 0, parseInt(data.kpis.high_risk_zones) || 0, 1000);
                animateValue(pendingEl, 0, parseInt(data.kpis.pending_challans) || 0, 1000);
                
                liveAlertsCount = data.alerts ? data.alerts.length : 0;
                if (policeAlertsEl) policeAlertsEl.textContent = liveAlertsCount;
                
                // Initialize Leaflet Map
                initMap(data.markers);
                
                // Populate Top Hotspots Decision Matrix
                populateHotspotsMatrix(data.markers);
                
                // Populate Smart Insights
                populateSmartInsights(data.insights);
                
                // Populate Real-Time Alert Feed
                populateLiveAlertFeed(data.alerts);
                
                // Start Alert Simulation loop
                startAlertSimulation();
                
                // Start CCTV streams simulation (Phase 5)
                startCCTVFeedsSim();
            })
            .catch(err => console.error("Error loading command center telemetry:", err));
    }

    function initMap(markers) {
        if (trafficMapInstance) return;
        
        // Centered on Bengaluru [12.9716, 77.5946]
        trafficMapInstance = L.map('traffic-map', {
            zoomControl: true,
            scrollWheelZoom: true,
            attributionControl: false
        }).setView([12.9716, 77.5946], 11.5);
        
        // CartoDB Dark Matter tiles
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(trafficMapInstance);
        
        // Add markers
        markers.forEach(m => {
            const pulseClass = `pulse-${m.color}`;
            const customIcon = L.divIcon({
                className: 'custom-leaflet-marker',
                html: `<span class="map-marker-pulse ${pulseClass}"></span>`,
                iconSize: [14, 14],
                iconAnchor: [7, 7],
                popupAnchor: [0, -7]
            });
            
            const popupContent = `
                <div class="map-popup-container">
                    <div class="map-popup-header">
                        <h4>${m.location}</h4>
                    </div>
                    <div class="map-popup-body">
                        <div class="map-popup-row">
                            <span class="label">Violations Today:</span>
                            <span class="val">${m.violation_count}</span>
                        </div>
                        <div class="map-popup-row">
                            <span class="label">Traffic Density:</span>
                            <span class="val">${m.traffic_density}</span>
                        </div>
                        <div class="map-popup-row">
                            <span class="label">Hotspot Score:</span>
                            <span class="val">${m.risk_score}</span>
                        </div>
                    </div>
                    <div class="map-popup-action">${m.action}</div>
                </div>
            `;
            
            L.marker(m.coordinates, { icon: customIcon })
                .addTo(trafficMapInstance)
                .bindPopup(popupContent);
        });
        
        // Trigger map invalidate size slightly after loading to prevent grey tiles
        setTimeout(() => {
            trafficMapInstance.invalidateSize();
        }, 300);
    }

    function populateHotspotsMatrix(markers) {
        const listEl = document.getElementById("cc-hotspots-list");
        if (!listEl) return;
        
        listEl.innerHTML = "";
        const sorted = [...markers].sort((a, b) => b.risk_score - a.risk_score);
        
        sorted.slice(0, 5).forEach(m => {
            let badgeColorClass = "score-low";
            if (m.color === "red") badgeColorClass = "score-critical";
            else if (m.color === "orange") badgeColorClass = "score-high";
            else if (m.color === "yellow") badgeColorClass = "score-medium";
            
            const row = document.createElement("div");
            row.className = "hotspot-row";
            row.innerHTML = `
                <div class="hotspot-info">
                    <span class="hotspot-loc">${m.location}</span>
                    <span class="hotspot-sub">${m.violation_count} Violations | Avg Density: ${m.traffic_density}</span>
                </div>
                <span class="hotspot-score-badge ${badgeColorClass}">${m.risk_score}</span>
            `;
            listEl.appendChild(row);
        });
    }

    function populateSmartInsights(insights) {
        if (!insights) return;
        setText("ins-danger", insights.most_dangerous_area);
        setText("ins-congested", insights.most_congested_area);
        setText("ins-violation", insights.most_common_violation);
        setText("ins-hour", insights.peak_traffic_hour);
        setText("ins-revenue", insights.highest_revenue_area);
        setText("ins-repeat", insights.repeat_offender_zone);
    }

    function populateLiveAlertFeed(alerts) {
        const feedEl = document.getElementById("cc-live-feed");
        if (!feedEl) return;
        
        feedEl.innerHTML = "";
        if (!alerts || alerts.length === 0) {
            feedEl.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px;">No active command alerts.</div>`;
            return;
        }
        
        alerts.forEach(a => {
            const timeStr = a.timestamp.split(" ")[1] || a.timestamp;
            let badgeColor = "green";
            if (a.severity === "HIGH") badgeColor = "red";
            else if (a.severity === "MEDIUM") badgeColor = "orange";
            
            let actionText = "Surveillance active";
            if (a.severity === "HIGH") actionText = "👮 Deploy patrol unit";
            else if (a.severity === "MEDIUM") actionText = "🚨 Dispatch officer";
            
            const item = document.createElement("div");
            item.className = "feed-item";
            item.innerHTML = `
                <div class="feed-item-header">
                    <span class="feed-time">${timeStr}</span>
                    <span class="feed-badge ${badgeColor}">${a.severity}</span>
                </div>
                <div class="feed-msg">${a.status}</div>
                <div class="feed-action">
                    <span>${actionText}</span>
                </div>
            `;
            feedEl.appendChild(item);
        });
    }

    let alertSimulationInterval = null;
    function startAlertSimulation() {
        if (alertSimulationInterval) return;
        
        const LOCATIONS = [
            "Silk Board Junction, Bengaluru",
            "Whitefield ITPL Road, Bengaluru",
            "Electronic City Phase 1, Bengaluru",
            "Marathahalli Junction, Bengaluru",
            "Hebbal Flyover, Bengaluru",
            "KR Puram Bridge, Bengaluru",
            "Koramangala 80ft Road, Bengaluru",
            "HSR Layout 27th Main, Bengaluru",
            "Majestic Bus Station, Bengaluru",
            "Yelahanka Circle, Bengaluru"
        ];
        
        const VIOLATIONS = [
            { type: "HELMET_VIOLATION", text: "Helmet non-compliance detected" },
            { type: "TRIPLE_RIDING", text: "Triple riding motorcycle violation detected" },
            { type: "WRONG_SIDE_DRIVING", text: "Dangerous wrong-side driving detected" },
            { type: "ILLEGAL_PARKING", text: "Illegal obstruction parking detected" },
            { type: "SEATBELT_VIOLATION", text: "Seatbelt compliance infraction detected" }
        ];
        
        const CONGESTION_MESSAGES = [
            "Severe bumper-to-bumper queue building up. recommended patrol unit deployment.",
            "Vehicle density exceeding threshold. Traffic flow speed reduced to <15 km/h.",
            "Gridlock forming at intersection. Requesting manual override signals."
        ];
        
        alertSimulationInterval = setInterval(() => {
            const feedEl = document.getElementById("cc-live-feed");
            if (!feedEl) return;
            
            if (feedEl.textContent.includes("No active command alerts")) {
                feedEl.innerHTML = "";
            }
            
            const date = new Date();
            const timeStr = date.toLocaleTimeString("en-US", { hour12: false });
            
            let isViolation = Math.random() < 0.6;
            let severity = "LOW";
            let msg = "";
            let actionText = "Surveillance active";
            let badgeColor = "green";
            
            const loc = LOCATIONS[Math.floor(Math.random() * LOCATIONS.length)];
            const shortLoc = loc.split(",")[0];
            
            if (isViolation) {
                const viol = VIOLATIONS[Math.floor(Math.random() * VIOLATIONS.length)];
                msg = `🚨 VIOLATION: ${viol.text} at ${shortLoc}. Auto-challan ticket dispatched.`;
                
                if (viol.type === "WRONG_SIDE_DRIVING" || viol.type === "TRIPLE_RIDING") {
                    severity = "HIGH";
                    badgeColor = "red";
                    actionText = "👮 Deploy patrol unit";
                } else {
                    severity = "MEDIUM";
                    badgeColor = "orange";
                    actionText = "🚨 Dispatch officer";
                }
            } else {
                const cong = CONGESTION_MESSAGES[Math.floor(Math.random() * CONGESTION_MESSAGES.length)];
                msg = `⚠️ CONGESTION: ${cong} Location: ${shortLoc}.`;
                severity = "HIGH";
                badgeColor = "red";
                actionText = "👮 Dispatch traffic unit";
            }
            
            const item = document.createElement("div");
            item.className = "feed-item";
            item.innerHTML = `
                <div class="feed-item-header">
                    <span class="feed-time">${timeStr}</span>
                    <span class="feed-badge ${badgeColor}">${severity}</span>
                </div>
                <div class="feed-msg">${msg}</div>
                <div class="feed-action">
                    <span>${actionText}</span>
                </div>
            `;
            
            feedEl.insertBefore(item, feedEl.firstChild);
            
            if (feedEl.children.length > 15) {
                feedEl.removeChild(feedEl.lastChild);
            }
            
            liveAlertsCount++;
            const policeAlertsEl = document.getElementById("cc-police-alerts");
            if (policeAlertsEl) policeAlertsEl.textContent = liveAlertsCount;
            
            if (isViolation) {
                const totalViolEl = document.getElementById("cc-violations-today");
                if (totalViolEl) {
                    const currentVal = parseInt(totalViolEl.textContent) || 0;
                    totalViolEl.textContent = currentVal + 1;
                }
            }
        }, 9000);
    }

    // --- City Analytics Tabbed Charts Implementation (v4.0) ---
    function loadChartTelemetry() {
        fetch("/api/detailed_charts")
            .then(res => res.json())
            .then(data => {
                chartTelemetry = data;
                const activeTabBtn = document.querySelector(".chart-tab-btn.active");
                const currentChart = activeTabBtn ? activeTabBtn.getAttribute("data-chart") : "hourly";
                renderAnalyticsTabChart(currentChart);
            })
            .catch(err => console.error("Error loading detailed chart statistics:", err));
    }

    function renderAnalyticsTabChart(chartType) {
        if (!chartTelemetry) return;
        const canvas = document.getElementById("analyticsChart");
        if (!canvas) return;
        
        const ctx = canvas.getContext("2d");
        if (analyticsChartInstance) analyticsChartInstance.destroy();
        
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.05)';
        
        let config = {};
        
        if (chartType === "hourly") {
            const labels = chartTelemetry.hourly.map(item => item.hour);
            const values = chartTelemetry.hourly.map(item => item.count);
            config = {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Violations Count',
                        data: values,
                        borderColor: '#00f0ff',
                        backgroundColor: 'rgba(0, 240, 255, 0.05)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2,
                        pointBackgroundColor: '#00f0ff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                        x: { grid: { display: false } }
                    }
                }
            };
        } else if (chartType === "weekday") {
            const labels = chartTelemetry.weekday.map(item => item.day);
            const values = chartTelemetry.weekday.map(item => item.count);
            config = {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Violations Count',
                        data: values,
                        backgroundColor: 'rgba(255, 184, 0, 0.55)',
                        borderColor: '#ffb800',
                        borderWidth: 1.5,
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                        x: { grid: { display: false } }
                    }
                }
            };
        } else if (chartType === "weekend") {
            const labels = chartTelemetry.weekend.map(item => item.day);
            const values = chartTelemetry.weekend.map(item => item.count);
            config = {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Violations Count',
                        data: values,
                        backgroundColor: 'rgba(255, 77, 109, 0.55)',
                        borderColor: '#ff4d6d',
                        borderWidth: 1.5,
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                        x: { grid: { display: false } }
                    }
                }
            };
        } else if (chartType === "monthly") {
            config = {
                type: 'line',
                data: {
                    labels: chartTelemetry.monthly.labels,
                    datasets: [{
                        label: 'Violations',
                        data: chartTelemetry.monthly.counts,
                        borderColor: '#0df0a6',
                        backgroundColor: 'rgba(13, 240, 166, 0.05)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2.5,
                        pointBackgroundColor: '#0df0a6'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                        x: { grid: { display: false } }
                    }
                }
            };
        } else if (chartType === "location") {
            const labels = chartTelemetry.location_wise.map(item => item.location);
            const values = chartTelemetry.location_wise.map(item => item.count);
            config = {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Violations Count',
                        data: values,
                        backgroundColor: 'rgba(0, 240, 255, 0.4)',
                        borderColor: '#00f0ff',
                        borderWidth: 1,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                        y: { grid: { display: false } }
                    }
                }
            };
        } else if (chartType === "comparison") {
            config = {
                type: 'doughnut',
                data: {
                    labels: ['Weekdays (Mon-Fri)', 'Weekends (Sat-Sun)'],
                    datasets: [{
                        data: [chartTelemetry.weekend_vs_weekday.weekday, chartTelemetry.weekend_vs_weekday.weekend],
                        backgroundColor: ['#00f0ff', '#ff4d6d'],
                        borderWidth: 0,
                        hoverOffset: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { boxWidth: 12, padding: 20 }
                        }
                    }
                }
            };
        }
        
        analyticsChartInstance = new Chart(ctx, config);
    }

    function initChartTabs() {
        const chartBtns = document.querySelectorAll(".chart-tab-btn");
        chartBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                chartBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                const chartType = btn.getAttribute("data-chart");
                renderAnalyticsTabChart(chartType);
            });
        });
    }

    function initDashboardData() {
        // Fetch overview metrics
        fetch("/api/metrics")
            .then(res => res.json())
            .then(data => {
                const totalTodayEl = document.getElementById("cc-violations-today") || document.getElementById("metric-total-today");
                const alertsEl = document.getElementById("cc-police-alerts") || document.getElementById("metric-active-alerts");
                const pendingEl = document.getElementById("cc-pending-challans") || document.getElementById("metric-pending-challans");
                
                // Animate numeric counters
                if (totalTodayEl) animateValue(totalTodayEl, 0, parseInt(data.total_violations_today) || 0, 1000);
                if (alertsEl) animateValue(alertsEl, 0, parseInt(data.active_alerts) || 0, 1000);
                if (pendingEl) animateValue(pendingEl, 0, parseInt(data.pending_challans) || 0, 1000);
            })
            .catch(err => console.error("Error loading metrics:", err));

        // Fetch chart telemetry
        fetch("/api/charts")
            .then(res => res.json())
            .then(data => {
                renderCharts(data);
            })
            .catch(err => console.error("Error loading chart data:", err));

        // Fetch repeat offenders & hotspots for city analytics tab
        fetch("/api/analytics")
            .then(res => res.json())
            .then(data => {
                populateAnalyticsLists(data);
                // Populate Repeat Offenders card on dashboard command center (Phase 6)
                populateRepeatOffenders(data.repeat_offenders);
            })
            .catch(err => console.error("Error loading analytics:", err));

        // Fetch enforcement log
        fetchLogs();

        // Fetch recommendations (Phase 7)
        loadPatrolRecommendations();

        // Fetch predictive violation intelligence (Phase 8)
        loadPredictiveIntel();

        // Fetch active deployed patrols board
        loadDeployedPatrols();

        // Fetch AI Performance Metrics (Phase 3)
        loadAIPerformanceMetrics();
    }

    function renderCharts(data) {
        // Chart.js Default styling tweaks for dark mode
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.05)';

        // Trend Line Chart
        const ctxTrend = document.getElementById("trendChart").getContext("2d");
        if (trendChartInstance) trendChartInstance.destroy();
        trendChartInstance = new Chart(ctxTrend, {
            type: 'line',
            data: {
                labels: data.trends.labels,
                datasets: [{
                    label: 'Violations Detected',
                    data: data.trends.counts,
                    borderColor: '#00f0ff',
                    backgroundColor: 'rgba(0, 240, 255, 0.05)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointBackgroundColor: '#00f0ff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });

        // Breakdown Doughnut Chart
        const ctxBreakdown = document.getElementById("breakdownChart").getContext("2d");
        if (breakdownChartInstance) breakdownChartInstance.destroy();
        
        const bData = data.breakdown;
        breakdownChartInstance = new Chart(ctxBreakdown, {
            type: 'doughnut',
            data: {
                labels: ['Helmet Non-compliance', 'Triple Riding', 'Wrong-side Driving', 'Illegal Parking'],
                datasets: [{
                    data: [
                        bData.HELMET_VIOLATION || 0,
                        bData.TRIPLE_RIDING || 0,
                        bData.WRONG_SIDE_DRIVING || 0,
                        bData.ILLEGAL_PARKING || 0
                    ],
                    backgroundColor: ['#ff4d6d', '#ffb800', '#00f0ff', '#0df0a6'],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, padding: 15 }
                    }
                }
            }
        });




    }

    function populateAnalyticsLists(data) {
        // 1. Top Congested Areas
        const congestedList = document.getElementById("congested-list");
        if (congestedList && data.top_congested_areas) {
            congestedList.innerHTML = "";
            data.top_congested_areas.forEach(item => {
                const li = document.createElement("li");
                li.innerHTML = `
                    <span>📈 ${item.location || 'Unknown'}</span>
                    <strong>${item.avg_density || 0} Vehicles</strong>
                `;
                congestedList.appendChild(li);
            });
        }

        // 2. Hotspots (Top Violation Areas)
        const hsList = document.getElementById("hotspots-list");
        if (hsList && data.hotspots) {
            hsList.innerHTML = "";
            data.hotspots.forEach(hs => {
                const li = document.createElement("li");
                li.innerHTML = `
                    <span>📍 ${hs.location || 'Unknown'}</span>
                    <strong style="color: var(--accent-amber);">${hs.violation_count || 0} Cases</strong>
                `;
                hsList.appendChild(li);
            });
        }

        // 3. Repeat Offenders
        const roList = document.getElementById("repeat-offenders-list");
        if (roList && data.repeat_offenders) {
            roList.innerHTML = "";
            data.repeat_offenders.forEach(ro => {
                const li = document.createElement("li");
                li.innerHTML = `
                    <span>🚘 Vehicle <strong>${ro.plate_number || 'UNKNOWN'}</strong></span>
                    <span class="r-badge">${ro.violations_count || 0} Infractions</span>
                `;
                roList.appendChild(li);
            });
        }

        // 4. Camera Heatmap
        const cameraGrid = document.getElementById("camera-heatmap-grid");
        if (cameraGrid && data.camera_nodes_heatmap) {
            cameraGrid.innerHTML = "";
            data.camera_nodes_heatmap.forEach(cam => {
                const node = document.createElement("div");
                const statusClass = (cam.status || 'NORMAL').toLowerCase();
                node.className = `camera-node-status ${statusClass}`;
                node.innerHTML = `
                    <div class="camera-id">${cam.camera_id || 'CAM'}</div>
                    <div class="camera-location">${cam.location || 'Unknown'}</div>
                    <span class="status-tag">${cam.status || 'NORMAL'}</span>
                `;
                cameraGrid.appendChild(node);
            });
        }

        // 5. Live Alerts Feed
        const alertsBody = document.getElementById("alerts-table-body");
        if (alertsBody && data.live_alerts) {
            alertsBody.innerHTML = "";
            data.live_alerts.forEach(alert => {
                const row = document.createElement("tr");
                const sevClass = `severity-${alert.severity.toLowerCase()}`;
                row.innerHTML = `
                    <td>${alert.timestamp}</td>
                    <td><strong>${alert.location}</strong></td>
                    <td><span class="${sevClass}">${alert.severity}</span></td>
                    <td><span class="status-badge alerts-status">${alert.status}</span></td>
                `;
                alertsBody.appendChild(row);
            });
        }

        // 6. SMS Logs
        const smsBody = document.getElementById("sms-table-body");
        if (smsBody && data.sms_logs) {
            smsBody.innerHTML = "";
            if (data.sms_logs.length === 0) {
                smsBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 10px;">No SMS notifications sent yet.</td></tr>`;
            } else {
                data.sms_logs.forEach(sms => {
                    const row = document.createElement("tr");
                    let statusClass = "status-delivered";
                    if (sms.status === "FAILED") statusClass = "status-failed";
                    else if (sms.status === "DEMO_SENT") statusClass = "status-demo";
                    const messageText = sms.message || "";
                    const challanText = sms.challan_id ? `<div class="sms-challan-id">${sms.challan_id}</div>` : "";
                    
                    row.innerHTML = `
                        <td>${sms.timestamp}</td>
                        <td title="${messageText.replace(/"/g, "&quot;")}"><span class="sms-type">${sms.type}</span>${challanText}</td>
                        <td><strong>${sms.recipient}</strong></td>
                        <td><span class="${statusClass}">${sms.status}</span></td>
                    `;
                    smsBody.appendChild(row);
                });
            }
        }
    }

    function fetchLogs() {
        const tableBody = document.getElementById("violations-table-body");
        fetch("/api/logs")
            .then(res => res.json())
            .then(logs => {
                loadedLogs = logs; // Save logs globally
                tableBody.innerHTML = "";
                if (logs.length === 0) {
                    tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted);">No violation records logged in the database yet.</td></tr>`;
                    return;
                }
                
                logs.forEach(log => {
                    const row = document.createElement("tr");
                    const typeClass = log.violation_type.toLowerCase().split("_")[0];
                    row.innerHTML = `
                        <td><a href="#" class="challan-link" data-challan-id="${log.challan_id}" style="color: var(--accent-cyan); text-decoration: none; font-weight: 600; font-family: monospace; border-bottom: 1px dashed var(--accent-cyan);">${log.challan_id}</a></td>
                        <td>${log.timestamp}</td>
                        <td>${log.location}</td>
                        <td><span style="font-family: monospace; font-size: 0.85rem; color: var(--text-secondary);">${log.camera_id}</span></td>
                        <td><span class="badge ${typeClass}">${log.violation_type}</span></td>
                        <td><strong style="font-family: monospace; letter-spacing: 0.5px;">${log.plate_number || 'UNKNOWN'}</strong></td>
                        <td style="color: var(--accent-red); font-weight: 600;">₹${log.amount}</td>
                        <td title="OCR confidence">${(Number(log.ocr_confidence || 0) * 100).toFixed(0)}%</td>
                        <td><span class="status-badge">${log.status}</span></td>
                    `;
                    tableBody.appendChild(row);
                });
                
                // Bind Modal clicks
                bindThumbClicks();
                bindChallanClicks();
            })
            .catch(err => {
                console.error("Error loading logs:", err);
                tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--accent-red);">Failed to retrieve records. Make sure backend is running.</td></tr>`;
            });
    }

    // 3. Image Upload Pipeline handling
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const uploadForm = document.getElementById("upload-form");
    const resultsDisplay = document.getElementById("results-display");

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    ["dragleave", "drop"].forEach(event => {
        dropZone.addEventListener(event, () => dropZone.classList.remove("dragover"));
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateDropZoneLabel(e.dataTransfer.files[0].name);
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) {
            updateDropZoneLabel(fileInput.files[0].name);
        }
    });

    function updateDropZoneLabel(filename) {
        dropZone.querySelector(".drop-text").textContent = `Selected: ${filename}`;
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function setImageSrc(id, value) {
        const element = document.getElementById(id);
        if (element) element.src = value;
    }

    function showUploadResults(resData) {
        const placeholder = document.querySelector(".placeholder-msg");
        if (placeholder) placeholder.style.display = "none";

        const resultsContent = document.querySelector(".results-content");
        if (resultsContent) resultsContent.style.display = "block";

        const processingMs = Number(resData.processing_time_ms) || 0;
        setText("res-speed", `${processingMs.toFixed(0)} ms`);
        setText("res-count", resData.detections_count ?? 0);

        const timestamp = new Date().getTime();
        const resImg = document.getElementById("res-img");
        const resVideo = document.getElementById("res-video");
        
        if (resData.evidence_video_path) {
            if (resImg) resImg.style.display = "none";
            if (resVideo) {
                resVideo.src = `/${resData.evidence_video_path}?t=${timestamp}`;
                resVideo.style.display = "block";
            }
        } else {
            if (resVideo) {
                resVideo.pause();
                resVideo.style.display = "none";
            }
            if (resImg && resData.evidence_image_path) {
                resImg.src = `/${resData.evidence_image_path}?t=${timestamp}`;
                resImg.style.display = "block";
            }
        }

        const debugPaths = resData.ocr_debug_paths || (resData.ocr_debug && resData.ocr_debug.debug_paths) || {};
        const vehicleCropPath = debugPaths.vehicle_crop || debugPaths.legacy_vehicle_crop || "outputs/vehicle_crop.jpg";
        const plateCropPath = debugPaths.plate_crop || debugPaths.legacy_plate_crop || "outputs/plate_crop.jpg";
        const enhancedPlatePath = debugPaths.enhanced_plate || debugPaths.legacy_enhanced_plate || "outputs/enhanced_plate.jpg";

        setImageSrc("ocr-vehicle-crop", `/${vehicleCropPath}?t=${timestamp}`);
        setImageSrc("ocr-plate-crop", `/${plateCropPath}?t=${timestamp}`);
        setImageSrc("ocr-enhanced-plate", `/${enhancedPlatePath}?t=${timestamp}`);

        setText("ocr-detected-plate", resData.detected_plate || "UNKNOWN");
        const ocrConfidence = Number(resData.ocr_confidence) || 0;
        setText("ocr-confidence", `${(ocrConfidence * 100).toFixed(0)}%`);
        setText("ocr-engine", resData.ocr_engine || "none");

        const violationsList = document.getElementById("res-violations-list");
        if (!violationsList) return;

        const violations = Array.isArray(resData.violations) ? resData.violations : [];
        violationsList.innerHTML = "";

        if (violations.length === 0) {
            violationsList.innerHTML = `<li><span style="color: var(--text-muted);">No violation infraction flags triggered in this frame.</span></li>`;
            return;
        }

        violations.forEach(v => {
            const li = document.createElement("li");
            const violationType = v.type || v.violation_type || "VIOLATION";
            const cls = violationType.toLowerCase().split("_")[0];
            li.className = cls;
            li.innerHTML = `
                <div>
                    <strong>${violationType}</strong>
                    <div style="color: var(--text-secondary); font-size: 0.75rem;">${v.details || ""}</div>
                </div>
                <span class="plate">${v.plate_number || "UNKNOWN"}</span>
            `;
            violationsList.appendChild(li);
        });
    }

    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const btnProcess = document.getElementById("btn-process");
        btnProcess.textContent = "Processing Frame Inference...";
        btnProcess.disabled = true;

        const formData = new FormData(uploadForm);

        try {
            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

            const responseText = await response.text();
            let resData;
            try {
                resData = JSON.parse(responseText);
            } catch (parseError) {
                throw new Error(`TrafficFlow Backend returned a non-JSON response (${response.status}).`);
            }

            btnProcess.textContent = "Execute Inference Pipeline";
            btnProcess.disabled = false;
            
            if (!response.ok || resData.error) {
                showToast("Processing failed: " + (resData.error || `HTTP ${response.status}`), "error");
                return;
            }

            showUploadResults(resData);

            // Refresh logs and charts
            initDashboardData();
        } catch (err) {
            btnProcess.textContent = "Execute Inference Pipeline";
            btnProcess.disabled = false;
            console.error("Upload failed:", err);
            showToast("Server unreachable. Make sure Flask is running at port 5000.", "error", 6000);
        }
    });

    // 4. Client-side Search Filter
    const searchInput = document.getElementById("search-input");
    searchInput.addEventListener("input", () => {
        const query = searchInput.value.toLowerCase();
        const rows = document.querySelectorAll("#violations-table-body tr");
        
        rows.forEach(row => {
            const cells = Array.from(row.getElementsByTagName("td"));
            if (cells.length > 1) {
                const text = cells.map(c => c.textContent.toLowerCase()).join(" ");
                if (text.includes(query)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            }
        });
    });

    // 5. Image Modal Review Box
    const modal = document.getElementById("image-modal");
    const modalImg = document.getElementById("modal-img");
    const captionText = document.getElementById("modal-caption");
    const closeBtn = document.querySelector(".close-modal");

    function bindThumbClicks() {
        const thumbBtns = document.querySelectorAll(".evidence-thumb-btn");
        thumbBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                modal.style.display = "block";
                modalImg.src = btn.getAttribute("data-img");
                captionText.textContent = btn.getAttribute("data-title");
            });
        });
    }

    closeBtn.addEventListener("click", () => {
        modal.style.display = "none";
    });

    window.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.style.display = "none";
        }
    });

    // 6. CSV and PDF Export hooks
    document.getElementById("btn-export-csv").addEventListener("click", () => {
        window.location.href = "/api/export/csv";
    });

    document.getElementById("btn-export-pdf").addEventListener("click", () => {
        fetch("/api/export/pdf")
            .then(res => res.json())
            .then(data => {
                showToast(`Evidence package compiled! Package: ${data.package_name} — ${data.records_compiled} records.`, "success", 5000);
            })
            .catch(err => showToast("Error building PDF evidence package.", "error"));
    });

    // --- Safety Hub & Detailed Modal Interactive Implementation ---

    // Video database mapping
    let VIDEO_DATABASE = [
        {
            id: "helmet_safety",
            category: "Helmet Safety",
            title: "Why Helmets Save Lives",
            desc: "An in-depth look at how ISI-certified helmets protect the brain from impact force during accidents.",
            duration: "3:15",
            localPath: "/static/videos/helmet_safety.mp4",
            youtubeKey: "HELMET_VIOLATION",
            thumbnail: "https://images.unsplash.com/photo-1609630875171-b1321377ee65?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "triple_riding",
            category: "Triple Riding Risks",
            title: "Dangers of Triple Riding",
            desc: "See how carrying two passengers on a two-wheeler compromises vehicle balance and extends braking distance.",
            duration: "2:45",
            localPath: "/static/videos/triple_riding.mp4",
            youtubeKey: "TRIPLE_RIDING",
            thumbnail: "https://images.unsplash.com/photo-1558981806-ec527fa84c39?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "wrong_way_driving",
            category: "Wrong Side Driving",
            title: "Lane Discipline and Road Safety",
            desc: "Learn why driving against the traffic flow direction leads to fatal head-on collisions at junctions.",
            duration: "3:30",
            localPath: "/static/videos/wrong_way_driving.mp4",
            youtubeKey: "WRONG_SIDE_DRIVING",
            thumbnail: "https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "traffic_signal",
            category: "Traffic Signal Rules",
            title: "Obeying the Traffic Lights",
            desc: "A breakdown of rules at signalized intersections, stop-line compliance, and yellow light timing safety.",
            duration: "2:10",
            localPath: "",
            youtubeKey: "TRAFFIC_SIGNAL_RULE",
            thumbnail: "https://images.unsplash.com/photo-1510935515286-9a2df752d5b6?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "seatbelt_awareness",
            category: "Seatbelt Awareness",
            title: "Seatbelt Awareness Guide",
            desc: "Demonstrating how three-point seatbelts prevent occupant ejection and load impact spread in car crashes.",
            duration: "3:05",
            localPath: "",
            youtubeKey: "SEATBELT_VIOLATION",
            thumbnail: "https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "illegal_parking",
            category: "Illegal Parking",
            title: "Smart Municipal Parking Etiquettes",
            desc: "Understanding no-parking curves, yellow line indicators, and how illegal obstruction impacts overall block traffic.",
            duration: "1:55",
            localPath: "",
            youtubeKey: "ILLEGAL_PARKING",
            thumbnail: "https://images.unsplash.com/photo-1506015391300-4802dc74de2e?w=500&auto=format&fit=crop&q=60"
        },
        {
            id: "emergency_vehicle",
            category: "Emergency Vehicle Awareness",
            title: "Yielding to Emergency Vehicles",
            desc: "Crucial instructions on how to clear lanes and move aside for ambulances and fire trucks in dense gridlocks.",
            duration: "2:20",
            localPath: "",
            youtubeKey: "EMERGENCY_VEHICLE",
            thumbnail: "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=500&auto=format&fit=crop&q=60"
        }
    ];

    // Quiz Questions Database
    const QUIZ_QUESTIONS = [
        {
            question: "Under Section 129 of the Indian Motor Vehicles Act, what protective gear is mandatory for two-wheeler riders?",
            options: [
                "Heavy leather gloves",
                "An ISI-certified safety helmet securely fastened",
                "Knee pads and elbow guards",
                "Reflective safety vest"
            ],
            answer: 1,
            explanation: "Section 129 mandates ISI-certified helmets for both rider and pillion passenger, securely fastened."
        },
        {
            question: "What is the standard legal fine amount for a Helmet violation in Bengaluru?",
            options: [
                "₹500 fine and verbal warning",
                "₹1,000 fine and up to 3 months license suspension",
                "₹2,500 fine and towing of vehicle",
                "₹5,000 fine and imprisonment"
            ],
            answer: 1,
            explanation: "Helmet violation carries a ₹1,000 fine and a potential 3-month driver's license suspension."
        },
        {
            question: "How many riders are legally permitted on a two-wheeled motorcycle under Section 128 of the IMV Act?",
            options: [
                "Maximum 3 persons (if children are carried)",
                "Maximum 1 person (rider only)",
                "Maximum 2 persons (rider and one pillion passenger)",
                "No limit as long as they fit on the seat"
            ],
            answer: 2,
            explanation: "Section 128 restricts two-wheelers to a maximum of two riders (the rider and one passenger)."
        },
        {
            question: "Triple riding increases which hazard significantly?",
            options: [
                "Fuel consumption by 80%",
                "Steering imbalance and braking distance by over 40%",
                "Wear and tear on the engine oil",
                "The insurance premium cost"
            ],
            answer: 1,
            explanation: "Carrying a third passenger shifts the center of gravity, causing steering wobbles and extending braking distance by 40%."
        },
        {
            question: "What is the penalty for driving on the wrong side of the road (Dangerous Driving, Section 184)?",
            options: [
                "₹100 spot fine",
                "₹1,000 fine only",
                "₹5,000 fine and potential license suspension/imprisonment",
                "Towing charges only"
            ],
            answer: 2,
            explanation: "Wrong side driving is prosecuted under Section 184 (Dangerous Driving), carrying a fine of up to ₹5,000 and possible jail time."
        },
        {
            question: "What percentage of fatal two-wheeler road accidents involve head injuries?",
            options: [
                "Approximately 15%",
                "Approximately 35%",
                "Approximately 50%",
                "Approximately 70% or more"
            ],
            answer: 3,
            explanation: "Statistics show that over 70% of fatal motorcycle accidents are caused by head injuries due to non-compliance with helmets."
        },
        {
            question: "At a signalized intersection, what does a solid yellow light indicate?",
            options: [
                "Speed up to cross before the light turns red",
                "Stop before the white stop-line unless it is unsafe to do so",
                "Proceed with caution without stopping",
                "Yield to pedestrian crossing only"
            ],
            answer: 1,
            explanation: "A yellow signal means you must stop before the stop-line unless you are too close to stop safely."
        },
        {
            question: "Which of the following is correct regarding seatbelt compliance in passenger cars?",
            options: [
                "Only the driver needs to wear a seatbelt",
                "Only the front-seat passenger and driver need seatbelts",
                "All forward-facing occupants (both front and rear) must wear seatbelts",
                "Seatbelts are optional within city limits"
            ],
            answer: 2,
            explanation: "Central Motor Vehicles Rules mandate that all forward-facing occupants (including rear passengers) must wear seatbelts."
        },
        {
            question: "When an emergency vehicle (Ambulance/Fire Engine) approaches with siren active, what must you do?",
            options: [
                "Speed up to stay ahead of it",
                "Stop immediately in the middle of your lane",
                "Move to the edge of the road to yield right of way",
                "Ignore it if you are in a traffic queue"
            ],
            answer: 2,
            explanation: "Drivers must draw their vehicles to the side of the road to yield free passage to emergency vehicles."
        },
        {
            question: "Where is parking strictly prohibited under the Motor Vehicles Act?",
            options: [
                "Within 15 meters of a bus stop or junction",
                "On footpaths, pedestrian crossings, and yellow lines",
                "Near a fire hydrant or on a bridge",
                "All of the above"
            ],
            answer: 3,
            explanation: "Parking is prohibited near junctions, bus stops, bridges, footpaths, pedestrian crossings, and fire hydrants to prevent accidents."
        }
    ];

    // Bind Challan links to open the detailed modal
    function bindChallanClicks() {
        const challanLinks = document.querySelectorAll(".challan-link");
        challanLinks.forEach(link => {
            link.addEventListener("click", (e) => {
                e.preventDefault();
                const challanId = link.getAttribute("data-challan-id");
                const log = loadedLogs.find(l => l.challan_id === challanId);
                if (log) {
                    openChallanModal(log);
                }
            });
        });
    }

    // Open Challan Details Modal
    function openChallanModal(log) {
        const challanModal = document.getElementById("challan-modal");
        if (!challanModal) return;
        
        // Configure header with PDF download link
        document.getElementById("modal-challan-id").innerHTML = `CHALLAN: ${log.challan_id} <a href="/challans/${log.challan_id}.pdf" target="_blank" class="btn secondary" style="font-size: 0.72rem; padding: 4px 8px; margin-left: 10px; text-decoration: none; display: inline-flex; align-items: center; gap: 4px; vertical-align: middle; width: auto;">📥 PDF</a>`;
        
        const badge = document.getElementById("modal-violation-badge");
        badge.textContent = log.violation_type;
        const typeClass = log.violation_type.toLowerCase().split("_")[0];
        badge.className = `badge ${typeClass}`;
        
        // Configure tabs - show ALL tabs!
        const tabs = document.querySelectorAll("#challan-modal .tab-btn");
        tabs.forEach(btn => {
            btn.style.display = "block";
            if (btn.getAttribute("data-tab") === "tab-annotated") {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
        
        // Set images
        const timestamp = new Date().getTime();
        document.getElementById("modal-annotated-img").src = `/${log.evidence_image_path}?t=${timestamp}`;
        document.getElementById("modal-original-img").src = `/${log.evidence_path}/original.jpg?t=${timestamp}`;
        
        // Activate default tab (annotated)
        document.getElementById("tab-annotated").classList.add("active");
        document.getElementById("tab-original").classList.remove("active");
        document.getElementById("tab-video").classList.remove("active");
        
        // Clear player container to stop background audio
        document.getElementById("player-container").innerHTML = "";
        
        // Populate Telemetry info
        const infoGrid = document.querySelector("#challan-modal .info-grid");
        if (infoGrid) {
            infoGrid.innerHTML = `
                <div><span class="label">Date & Time</span><span class="val">${log.timestamp}</span></div>
                <div><span class="label">Location</span><span class="val">${log.location}</span></div>
                <div><span class="label">Camera ID</span><span class="val">${log.camera_id}</span></div>
                <div><span class="label">Detected Plate</span><span class="val monospace">${log.plate_number || 'UNKNOWN'}</span></div>
                <div><span class="label">OCR Confidence</span><span class="val">${(Number(log.ocr_confidence || 0) * 100).toFixed(0)}%</span></div>
                <div><span class="label">OCR Engine</span><span class="val">${log.ocr_engine || "none"}</span></div>
                <div><span class="label">Fine Amount</span><span class="val text-danger">₹${log.amount}</span></div>
            `;
        }
        
        // Show recommended safety video based on violation type
        const matchingVideo = VIDEO_DATABASE.find(v => v.youtubeKey === log.violation_type) 
            || VIDEO_DATABASE.find(v => v.id === "helmet_safety"); // default fallback
            
        if (matchingVideo) {
            document.getElementById("modal-rec-title").textContent = matchingVideo.title;
            document.getElementById("modal-rec-desc").textContent = matchingVideo.desc;
            
            // Wire "Watch Now" action in the recommended block
            const watchRecBtn = document.getElementById("modal-btn-watch-rec");
            watchRecBtn.onclick = () => {
                // Switch to video tab
                tabs.forEach(btn => {
                    if (btn.getAttribute("data-tab") === "tab-video") {
                        btn.classList.add("active");
                    } else {
                        btn.classList.remove("active");
                    }
                });
                document.getElementById("tab-annotated").classList.remove("active");
                document.getElementById("tab-original").classList.remove("active");
                document.getElementById("tab-video").classList.add("active");
                
                // Play video
                loadVideoIntoPlayer(matchingVideo);
            };
        }
        
        // Show modal
        challanModal.style.display = "block";
    }

    // Play Safety Video Directly from Safety Library
    function playVideoInModal(video) {
        // Redirect to our dedicated YouTube player modal
        playVideoInYTPlayer(video);
    }

    // Dynamic YouTube Player API Integration and Watch Tracking
    let ytPlayerInstance = null;
    let trackingInterval = null;
    let activeVideoRecord = null;
    let maxWatchedPercentage = 0;
    let isVideoCompleted = false;

    // Load YouTube API script dynamically
    if (!window.YT) {
        const tag = document.createElement('script');
        tag.src = "https://www.youtube.com/iframe_api";
        const firstScriptTag = document.getElementsByTagName('script')[0];
        firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
    }

    window.onYouTubeIframeAPIReady = function() {
        console.log("YouTube Player API Ready.");
    };

    function playVideoInYTPlayer(video) {
        activeVideoRecord = video;
        maxWatchedPercentage = 0;
        isVideoCompleted = false;
        
        // Populate modal text details
        document.getElementById("video-modal-title").textContent = video.title;
        document.getElementById("video-modal-category").textContent = video.category;
        document.getElementById("video-modal-duration").textContent = `Duration: ${video.duration}`;
        document.getElementById("video-modal-description").textContent = video.description || video.desc || "";
        
        // Open Dedicated Video modal
        const modal = document.getElementById("video-player-modal");
        modal.style.display = "block";
        
        // Empty the container
        document.getElementById("youtube-player-container").innerHTML = '<div id="yt-player-target"></div>';
        
        // Create player
        ytPlayerInstance = new YT.Player('yt-player-target', {
            height: '100%',
            width: '100%',
            videoId: video.youtube_id,
            playerVars: {
                'autoplay': 1,
                'rel': 0,
                'modestbranding': 1,
                'enablejsapi': 1
            },
            events: {
                'onStateChange': onPlayerStateChange
            }
        });
    }

    function onPlayerStateChange(event) {
        if (event.data === YT.PlayerState.PLAYING) {
            if (!trackingInterval) {
                trackingInterval = setInterval(trackProgressPercentage, 1000);
            }
        } else {
            if (trackingInterval) {
                clearInterval(trackingInterval);
                trackingInterval = null;
            }
            if (event.data === YT.PlayerState.ENDED) {
                isVideoCompleted = true;
                maxWatchedPercentage = 100;
                saveProgressToBackend();
            }
        }
    }

    function trackProgressPercentage() {
        if (ytPlayerInstance && ytPlayerInstance.getCurrentTime && ytPlayerInstance.getDuration) {
            const current = ytPlayerInstance.getCurrentTime();
            const total = ytPlayerInstance.getDuration();
            if (total > 0) {
                const pct = (current / total) * 100;
                if (pct > maxWatchedPercentage) {
                    maxWatchedPercentage = Math.round(pct);
                }
            }
        }
    }

    function saveProgressToBackend() {
        if (!activeVideoRecord) return;
        
        let totalDurationSec = 0;
        if (ytPlayerInstance && ytPlayerInstance.getDuration) {
            totalDurationSec = ytPlayerInstance.getDuration();
        }
        
        if (totalDurationSec <= 0) {
            const parts = activeVideoRecord.duration.split(":");
            totalDurationSec = parseInt(parts[0]) * 60 + parseInt(parts[1]);
        }
        
        const compPct = isVideoCompleted ? 100 : Math.min(100, maxWatchedPercentage);
        const watchDuration = Math.round((compPct / 100.0) * totalDurationSec);
        
        fetch("/api/video_views", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                video_id: activeVideoRecord.youtube_id,
                video_title: activeVideoRecord.title,
                category: activeVideoRecord.category,
                watch_duration: watchDuration,
                completion_percentage: compPct
            })
        })
        .then(res => res.json())
        .then(data => {
            // Refresh safety analytics and locking mechanisms
            loadSafetyHubData();
            showToast("Watch progress updated!", "success");
        })
        .catch(err => console.error("Error saving video watch progress:", err));
        
        activeVideoRecord = null;
    }

    // Close dedicated video player modal
    const closeVideoModalBtn = document.getElementById("close-video-modal");
    if (closeVideoModalBtn) {
        closeVideoModalBtn.onclick = () => {
            saveProgressToBackend();
            document.getElementById("video-player-modal").style.display = "none";
            if (ytPlayerInstance) {
                try {
                    ytPlayerInstance.destroy();
                } catch(e) {
                    console.error(e);
                }
                ytPlayerInstance = null;
            }
            if (trackingInterval) {
                clearInterval(trackingInterval);
                trackingInterval = null;
            }
        };
    }

    // Load video into modal container (legacy/challan recommended block trigger)
    function loadVideoIntoPlayer(video) {
        playVideoInYTPlayer(video);
        document.getElementById("challan-modal").style.display = "none";
    }

    // Log video view transaction (legacy, kept for signature protection)
    function logVideoWatch(videoId, category) {
        // Redundant - handled by YouTube state triggers
    }

    // Legacy scoreboard loader (maps to new analytics helper)
    function loadVideoAnalytics() {
        loadSafetyHubData();
    }

    // Advanced safety awareness data loader
    let completedVideosCount = 0;
    let completedVideoCategories = [];
    let safetyTrendsChartInstance = null;

    function loadSafetyHubData() {
        fetch("/api/safety_analytics")
            .then(res => res.json())
            .then(data => {
                // Update scoreboards
                const totalEl = document.getElementById("stats-videos-watched");
                const viewedEl = document.getElementById("stats-most-viewed-cat");
                const scoreEl = document.getElementById("stats-safety-score");
                
                if (totalEl) totalEl.textContent = data.total_videos_watched || "0";
                if (viewedEl) {
                    viewedEl.textContent = data.most_popular_categories.length > 0 
                        ? data.most_popular_categories[0].category 
                        : "None";
                }
                
                completedVideosCount = data.completed_categories_count || 0;
                completedVideoCategories = data.completed_categories || [];
                
                // Calculate Safety Awareness Score
                const videoCompletionPct = data.video_completion_rate || 0.0;
                const savedQuizScore = parseInt(localStorage.getItem("trafficflow_quiz_score") || "0");
                const safetyScoreValue = Math.round((videoCompletionPct * 0.5) + (savedQuizScore * 0.5));
                
                if (scoreEl) {
                    renderSafetyBadges(safetyScoreValue);
                }
                
                // Quiz Lock Control
                const startQuizBtn = document.getElementById("btn-start-quiz");
                const quizStartScreen = document.getElementById("quiz-start-screen");
                if (startQuizBtn && quizStartScreen) {
                    // Remove any existing lock text
                    const lockText = quizStartScreen.querySelector(".quiz-lock-warning");
                    if (lockText) lockText.remove();
                    
                    if (completedVideosCount >= 1) {
                        startQuizBtn.disabled = false;
                        startQuizBtn.innerHTML = "Start Safety Challenge";
                        startQuizBtn.style.opacity = "1";
                        startQuizBtn.style.cursor = "pointer";
                    } else {
                        startQuizBtn.disabled = true;
                        startQuizBtn.innerHTML = "🔒 Start Safety Challenge (Locked)";
                        startQuizBtn.style.opacity = "0.6";
                        startQuizBtn.style.cursor = "not-allowed";
                        
                        const warn = document.createElement("p");
                        warn.className = "quiz-lock-warning";
                        warn.style.cssText = "color: #ff4d6d; font-size: 0.82rem; margin-top: 12px; font-weight: 600;";
                        warn.textContent = "⚠️ Please watch at least 1 safety video completely to unlock the challenge.";
                        startQuizBtn.after(warn);
                    }
                }
                
                // Certificate Lock Control
                const previewPanel = document.getElementById("certificate-preview-panel");
                const viewCertBtn = document.getElementById("btn-view-certificate");
                const certCanvasContainer = document.getElementById("cert-canvas-container");
                if (previewPanel) {
                    // Remove old warning
                    const oldWarn = previewPanel.querySelector(".cert-lock-warning");
                    if (oldWarn) oldWarn.remove();
                    
                    if (completedVideosCount >= 3 && savedQuizScore >= 70) {
                        if (viewCertBtn) viewCertBtn.style.display = "inline-block";
                        previewPanel.style.opacity = "1";
                        previewPanel.style.pointerEvents = "auto";
                    } else {
                        if (viewCertBtn) viewCertBtn.style.display = "none";
                        if (certCanvasContainer) certCanvasContainer.style.display = "none";
                        
                        const warn = document.createElement("div");
                        warn.className = "cert-lock-warning";
                        warn.style.cssText = "margin-top: 15px; padding: 10px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; font-size: 0.78rem; color: #ff6b6b; text-align: center;";
                        
                        const left = Math.max(0, 3 - completedVideosCount);
                        let text = "";
                        if (left > 0 && savedQuizScore < 70) {
                            text = `Watch ${left} more video(s) and score 70%+ on the quiz to unlock.`;
                        } else if (left > 0) {
                            text = `Watch ${left} more video(s) to unlock.`;
                        } else {
                            text = `Score 70%+ on the quiz to unlock (Current best: ${savedQuizScore}%).`;
                        }
                        warn.innerHTML = `🔒 <strong>Certificate Locked</strong><br>${text}`;
                        previewPanel.appendChild(warn);
                    }
                }
                
                // Populate Recently Watched
                renderRecentlyWatched(data.most_viewed_videos || []);
                
                // Populate Police analytics tables
                populatePoliceTables(data);
                
                // Render trends chart
                renderSafetyTrendsChart(data.awareness_trends || []);
            })
            .catch(err => console.error("Error loading safety analytics:", err));
    }

    function renderSafetyBadges(score) {
        const scoreEl = document.getElementById("stats-safety-score");
        if (!scoreEl) return;
        
        let badgeName = "None";
        let badgeColor = "#64748b";
        
        if (score >= 90) {
            badgeName = "Safety Citizen";
            badgeColor = "#00f0ff";
        } else if (score >= 80) {
            badgeName = "Gold";
            badgeColor = "#ffb800";
        } else if (score >= 50) {
            badgeName = "Silver";
            badgeColor = "#e2e8f0";
        } else if (score >= 20) {
            badgeName = "Bronze";
            badgeColor = "#cd7f32";
        }
        
        scoreEl.innerHTML = `${score}% <span style="font-size: 0.7rem; display: block; margin-top: 4px; color: ${badgeColor}; font-weight: 700; text-shadow: 0 0 10px ${badgeColor}33;">🛡️ ${badgeName} Badge</span>`;
    }

    function renderRecentlyWatched(watchedList) {
        const container = document.getElementById("safety-recents-container");
        const grid = document.getElementById("video-recents-grid");
        if (!container || !grid) return;
        
        if (watchedList.length === 0) {
            container.style.display = "none";
            return;
        }
        
        container.style.display = "block";
        grid.innerHTML = "";
        
        // Show top 3 recently watched videos
        let renderedCount = 0;
        watchedList.forEach(w => {
            if (renderedCount >= 3) return;
            const video = VIDEO_DATABASE.find(v => v.title === w.video_title);
            if (!video) return;
            
            renderedCount++;
            const card = document.createElement("div");
            card.className = "video-card glass";
            card.style.cssText = "padding: 10px; display: flex; gap: 12px; align-items: center; border-radius: 8px; border: 1px solid var(--border-color); background: rgba(255,255,255,0.01); transition: transform 0.2s, box-shadow 0.2s;";
            
            card.innerHTML = `
                <div style="position: relative; width: 80px; height: 50px; border-radius: 6px; overflow: hidden; flex-shrink: 0;">
                    <img src="${video.thumbnail}" style="width: 100%; height: 100%; object-fit: cover;">
                    <div style="position: absolute; inset: 0; background: rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; font-size: 0.8rem; color: #fff;">▶</div>
                </div>
                <div style="display: flex; flex-direction: column; overflow: hidden;">
                    <span style="font-size: 0.65rem; color: var(--accent-cyan); font-weight: 600; text-transform: uppercase;">${video.category}</span>
                    <h5 style="font-size: 0.8rem; font-weight: 700; color: #fff; margin: 2px 0 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;">${video.title}</h5>
                    <span style="font-size: 0.65rem; color: var(--text-muted); margin-top: 2px;">Views: ${w.view_count}</span>
                </div>
            `;
            
            card.style.cursor = "pointer";
            card.addEventListener("mouseover", () => {
                card.style.transform = "translateY(-2px)";
                card.style.boxShadow = "0 4px 12px rgba(0,240,255,0.1)";
            });
            card.addEventListener("mouseout", () => {
                card.style.transform = "none";
                card.style.boxShadow = "none";
            });
            card.onclick = () => {
                playVideoInYTPlayer(video);
            };
            grid.appendChild(card);
        });
    }

    function populatePoliceTables(data) {
        const topicsBody = document.getElementById("safety-topics-table-body");
        const wardsBody = document.getElementById("safety-wards-table-body");
        
        if (topicsBody) {
            topicsBody.innerHTML = "";
            if (data.most_popular_categories.length === 0) {
                topicsBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:var(--text-muted);">No safety topics viewed yet.</td></tr>`;
            } else {
                data.most_popular_categories.forEach(cat => {
                    const compPct = Math.round(data.category_completion[cat.category] || 0.0);
                    let badgeColor = "var(--text-muted)";
                    if (compPct >= 90) badgeColor = "var(--accent-emerald)";
                    else if (compPct >= 50) badgeColor = "var(--accent-amber)";
                    
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="font-weight: 600; color: #fff; border-bottom: 1px solid var(--border-color); padding: 8px;">${cat.category}</td>
                        <td style="border-bottom: 1px solid var(--border-color); padding: 8px;">${cat.view_count} Views</td>
                        <td style="color: ${badgeColor}; font-weight:700; border-bottom: 1px solid var(--border-color); padding: 8px;">${compPct}% Complete</td>
                    `;
                    topicsBody.appendChild(tr);
                });
            }
        }
        
        if (wardsBody) {
            wardsBody.innerHTML = "";
            if (data.awareness_trends.length === 0) {
                wardsBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">No ward statistics available.</td></tr>`;
            } else {
                data.awareness_trends.forEach(ward => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="font-weight: 600; color: #fff; border-bottom: 1px solid var(--border-color); padding: 8px;">${ward.location} Ward</td>
                        <td style="border-bottom: 1px solid var(--border-color); padding: 8px;">${ward.violation_count} Incidents</td>
                        <td style="color: var(--accent-cyan); font-weight:700; border-bottom: 1px solid var(--border-color); padding: 8px;">${ward.awareness_rate}%</td>
                        <td style="color: var(--accent-emerald); font-weight:700; border-bottom: 1px solid var(--border-color); padding: 8px;">-${ward.reduction_percentage}% Fines</td>
                    `;
                    wardsBody.appendChild(tr);
                });
            }
        }
    }

    function renderSafetyTrendsChart(trends) {
        const ctx = document.getElementById("safetyCorrelationChart");
        if (!ctx) return;
        
        if (safetyTrendsChartInstance) {
            safetyTrendsChartInstance.destroy();
        }
        
        const labels = trends.map(t => t.location);
        const awarenessRates = trends.map(t => t.awareness_rate);
        const reductions = trends.map(t => t.reduction_percentage);
        
        safetyTrendsChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Awareness Rate (%)',
                        data: awarenessRates,
                        backgroundColor: 'rgba(0, 240, 255, 0.45)',
                        borderColor: '#00f0ff',
                        borderWidth: 1.5,
                        borderRadius: 4,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Violation Reduction (%)',
                        data: reductions,
                        type: 'line',
                        borderColor: '#0df0a6',
                        backgroundColor: 'rgba(13, 240, 166, 0.15)',
                        borderWidth: 2.5,
                        tension: 0.35,
                        pointBackgroundColor: '#0df0a6',
                        yAxisID: 'y'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Outfit', size: 10 }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#64748b', font: { family: 'Outfit', size: 9 } }
                    },
                    y: {
                        position: 'left',
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#64748b',
                            font: { family: 'Outfit' },
                            callback: value => value + "%"
                        },
                        min: 0,
                        max: 100
                    }
                }
            }
        });
    }

    // Load safety rules cards
    function loadRulesDirectory() {
        const grid = document.getElementById("rules-directory-grid");
        if (!grid) return;
        
        fetch("/api/rules")
            .then(res => res.json())
            .then(rules => {
                grid.innerHTML = "";
                Object.keys(rules).forEach(key => {
                    const rule = rules[key];
                    const card = document.createElement("div");
                    card.className = "rule-card glass";
                    card.setAttribute("data-title", rule.title.toLowerCase());
                    card.setAttribute("data-desc", rule.description.toLowerCase());
                    
                    let extraInfo = "";
                    if (rule.suspension) {
                        extraInfo = `<div class="rule-section" style="color: var(--accent-red); margin-top: 5px;">⚠️ License impact: ${rule.suspension}</div>`;
                    } else if (rule.tow_charge) {
                        extraInfo = `<div class="rule-section" style="color: var(--accent-amber); margin-top: 5px;">⚠️ Towing: ${rule.tow_charge}</div>`;
                    } else if (rule.imprisonment) {
                        extraInfo = `<div class="rule-section" style="color: var(--accent-red); margin-top: 5px;">⚠️ Penalty: ${rule.imprisonment}</div>`;
                    }
                    
                    card.innerHTML = `
                        <div class="rule-header">
                            <div class="rule-title-box">
                                <h4>${rule.title}</h4>
                                <span class="rule-section">${rule.section}</span>
                            </div>
                            <span class="rule-fine-badge">Fine: ₹${rule.fine}</span>
                        </div>
                        <p class="rule-desc">${rule.description}</p>
                        ${extraInfo}
                        <div class="rule-recommendation" style="margin-top: 15px;">
                            <strong>BTP Advice:</strong> ${rule.recommendation}
                        </div>
                    `;
                    grid.appendChild(card);
                });
            })
            .catch(err => console.error("Error loading rules:", err));
    }

    // Render video library items
    function renderVideoLibrary(filterCategory = "all") {
        const grid = document.getElementById("video-library-grid");
        if (!grid) return;
        
        grid.innerHTML = "";
        const filtered = filterCategory === "all" 
            ? VIDEO_DATABASE 
            : VIDEO_DATABASE.filter(v => v.category === filterCategory);
            
        if (filtered.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">No videos found in this category.</div>`;
            return;
        }
        
        // Fetch view completion rates to overlay progress bars
        fetch("/api/safety_analytics")
            .then(res => res.json())
            .then(analyticsData => {
                const completionMap = analyticsData.category_completion || {};
                
                filtered.forEach(video => {
                    const compPct = Math.round(completionMap[video.category] || 0.0);
                    const isCompleted = compPct >= 90;
                    
                    const card = document.createElement("div");
                    card.className = "video-card";
                    card.setAttribute("data-title", video.title.toLowerCase());
                    card.setAttribute("data-desc", video.description.toLowerCase());
                    
                    let completionBadge = "";
                    if (isCompleted) {
                        completionBadge = `<span style="position: absolute; top: 10px; right: 10px; z-index: 10; background: var(--accent-emerald); color: #020617; font-size: 0.65rem; font-weight: 700; padding: 2px 8px; border-radius: 20px; box-shadow: 0 2px 8px rgba(13,240,166,0.3);">Completed ✓</span>`;
                    }
                    
                    let progressBar = "";
                    if (compPct > 0) {
                        progressBar = `
                            <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 4px; background: rgba(255,255,255,0.15);">
                                <div style="height: 100%; width: ${compPct}%; background: ${isCompleted ? 'var(--accent-emerald)' : 'var(--accent-cyan)'}; transition: width 0.3s;"></div>
                            </div>
                        `;
                    }
                    
                    card.innerHTML = `
                        <div class="video-thumbnail" style="position: relative;">
                            ${completionBadge}
                            <img src="${video.thumbnail}" alt="${video.title}">
                            <span class="video-duration">${video.duration}</span>
                            <div class="video-play-overlay">
                                <div class="play-icon-circle">▶</div>
                            </div>
                            ${progressBar}
                        </div>
                        <div class="video-info">
                            <span class="video-category">${video.category}</span>
                            <h4 class="video-title">${video.title}</h4>
                            <p class="video-desc">${video.description}</p>
                            <div class="video-card-actions">
                                <button class="watch-btn" data-id="${video.youtube_id}">📺 Watch Now</button>
                            </div>
                        </div>
                    `;
                    
                    const playTrigger = () => {
                        playVideoInYTPlayer(video);
                    };
                    card.querySelector(".video-thumbnail").addEventListener("click", playTrigger);
                    card.querySelector(".watch-btn").addEventListener("click", playTrigger);
                    
                    grid.appendChild(card);
                });
            })
            .catch(err => {
                console.error("Error fetching safety views for library render:", err);
            });
    }

    // Quiz functions
    function startQuiz() {
        currentQuestionIndex = 0;
        quizScore = 0;
        document.getElementById("quiz-start-screen").style.display = "none";
        document.getElementById("quiz-result-screen").style.display = "none";
        document.getElementById("quiz-question-screen").style.display = "block";
        document.getElementById("cert-canvas-container").style.display = "none";
        showQuestion();
    }

    function showQuestion() {
        const question = QUIZ_QUESTIONS[currentQuestionIndex];
        document.getElementById("quiz-progress-text").textContent = `Question ${currentQuestionIndex + 1} of ${QUIZ_QUESTIONS.length}`;
        const progressPercent = ((currentQuestionIndex + 1) / QUIZ_QUESTIONS.length) * 100;
        document.getElementById("quiz-progress-bar").style.width = `${progressPercent}%`;
        
        document.getElementById("quiz-question-title").textContent = question.question;
        
        const optionsList = document.getElementById("quiz-options-list");
        optionsList.innerHTML = "";
        
        selectedOptionIndex = null;
        document.getElementById("btn-next-question").style.display = "none";
        
        question.options.forEach((opt, idx) => {
            const btn = document.createElement("div");
            btn.className = "quiz-option";
            btn.innerHTML = `
                <span>${opt}</span>
                <span class="quiz-option-status"></span>
            `;
            btn.addEventListener("click", () => {
                if (selectedOptionIndex !== null) return;
                
                selectedOptionIndex = idx;
                const isCorrect = idx === question.answer;
                
                if (isCorrect) {
                    quizScore++;
                    btn.classList.add("correct");
                    btn.querySelector(".quiz-option-status").textContent = "✓";
                } else {
                    btn.classList.add("incorrect");
                    btn.querySelector(".quiz-option-status").textContent = "✗";
                    
                    const correctBtn = optionsList.children[question.answer];
                    correctBtn.classList.add("correct");
                    correctBtn.querySelector(".quiz-option-status").textContent = "✓";
                }
                
                document.getElementById("btn-next-question").style.display = "block";
            });
            optionsList.appendChild(btn);
        });
    }

    function nextQuestion() {
        currentQuestionIndex++;
        if (currentQuestionIndex < QUIZ_QUESTIONS.length) {
            showQuestion();
        } else {
            showQuizResults();
        }
    }

    function showQuizResults() {
        document.getElementById("quiz-question-screen").style.display = "none";
        document.getElementById("quiz-result-screen").style.display = "block";
        
        const scorePercent = Math.round((quizScore / QUIZ_QUESTIONS.length) * 100);
        document.getElementById("quiz-score-percent").textContent = `${scorePercent}%`;
        document.getElementById("quiz-result-desc").textContent = `You scored ${quizScore} out of ${QUIZ_QUESTIONS.length} questions correct.`;
        
        const emojiEl = document.getElementById("quiz-result-emoji");
        const titleEl = document.getElementById("quiz-result-title");
        const certBtn = document.getElementById("btn-view-certificate");
        
        // Save quiz score to localStorage
        const prevBest = parseInt(localStorage.getItem("trafficflow_quiz_score") || "0");
        if (scorePercent > prevBest) {
            localStorage.setItem("trafficflow_quiz_score", scorePercent.toString());
        }
        
        // Refresh safety hub locks & score
        loadSafetyHubData();
        
        if (scorePercent >= 70) {
            emojiEl.textContent = "🏆";
            titleEl.textContent = "Congratulations! Safety Challenge Cleared";
            certBtn.style.display = "inline-block";
        } else {
            emojiEl.textContent = "⚠️";
            titleEl.textContent = "Safety Challenge Failed";
            certBtn.style.display = "none";
        }
    }

    // Dynamic Canvas Certificate Generator
    function drawCertificate() {
        const canvas = document.getElementById("certificate-canvas");
        if (!canvas) return;
        
        const ctx = canvas.getContext("2d");
        
        canvas.width = 800;
        canvas.height = 600;
        
        const userName = prompt("Please enter your full name for the certificate:") || "Citizen Rider";
        
        // Background slate gradient
        const grad = ctx.createRadialGradient(400, 300, 50, 400, 300, 500);
        grad.addColorStop(0, "#111827");
        grad.addColorStop(1, "#030712");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, 800, 600);
        
        // Double borders
        ctx.strokeStyle = "#ffb800";
        ctx.lineWidth = 6;
        ctx.strokeRect(20, 20, 760, 560);
        
        ctx.strokeStyle = "#00f0ff";
        ctx.lineWidth = 2;
        ctx.strokeRect(30, 30, 740, 540);
        
        // Corner accents
        ctx.fillStyle = "#00f0ff";
        ctx.fillRect(30, 30, 25, 4);
        ctx.fillRect(30, 30, 4, 25);
        ctx.fillRect(745, 30, 25, 4);
        ctx.fillRect(766, 30, 4, 25);
        ctx.fillRect(30, 566, 25, 4);
        ctx.fillRect(30, 545, 4, 25);
        ctx.fillRect(745, 566, 25, 4);
        ctx.fillRect(766, 545, 4, 25);
        
        // Texts
        ctx.textAlign = "center";
        ctx.fillStyle = "#94a3b8";
        ctx.font = "bold 13px 'Outfit', sans-serif";
        ctx.fillText("BENGALURU TRAFFIC POLICE — SMART ENFORCEMENT", 400, 80);
        
        ctx.fillStyle = "#ffb800";
        ctx.font = "bold 32px 'Outfit', sans-serif";
        ctx.fillText("CERTIFICATE OF COMPLIANCE", 400, 130);
        
        ctx.fillStyle = "#00f0ff";
        ctx.font = "14px 'Outfit', sans-serif";
        ctx.fillText("ROAD SAFETY & AWARENESS CHALLENGE", 400, 165);
        
        ctx.fillStyle = "#f1f5f9";
        ctx.font = "italic 16px 'Outfit', sans-serif";
        ctx.fillText("This is proudly awarded to", 400, 220);
        
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 38px 'Outfit', sans-serif";
        ctx.fillText(userName, 400, 275);
        
        // Horizontal line
        ctx.strokeStyle = "rgba(0, 240, 255, 0.4)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(250, 290);
        ctx.lineTo(550, 290);
        ctx.stroke();
        
        ctx.fillStyle = "#94a3b8";
        ctx.font = "15px 'Outfit', sans-serif";
        ctx.fillText("for demonstrating superior knowledge of road rules, speed limits,", 400, 330);
        ctx.fillText("and defensive driving guidelines aligned with BTP Smart City standards.", 400, 355);
        
        const savedQuizScore = parseInt(localStorage.getItem("trafficflow_quiz_score") || "70");
        ctx.fillStyle = "#0df0a6";
        ctx.font = "bold 18px 'Outfit', sans-serif";
        ctx.fillText(`Evaluation Score: ${savedQuizScore}% — PASS`, 400, 405);
        
        const today = new Date().toLocaleDateString("en-IN", {
            day: "numeric",
            month: "long",
            year: "numeric"
        });
        const serial = `TF-${Math.floor(100000 + Math.random() * 900000)}`;
        
        ctx.textAlign = "left";
        ctx.fillStyle = "#64748b";
        ctx.font = "12px monospace";
        ctx.fillText(`DATE: ${today}`, 60, 480);
        ctx.fillText(`CERTIFICATE ID: ${serial}`, 60, 500);
        
        // Signatures
        ctx.textAlign = "center";
        ctx.strokeStyle = "rgba(148, 163, 184, 0.2)";
        ctx.lineWidth = 1;
        
        ctx.beginPath();
        ctx.moveTo(150, 525);
        ctx.lineTo(290, 525);
        ctx.stroke();
        
        ctx.fillStyle = "#94a3b8";
        ctx.font = "12px 'Outfit', sans-serif";
        ctx.fillText("BTP Commissioner", 220, 542);
        
        ctx.beginPath();
        ctx.moveTo(510, 525);
        ctx.lineTo(650, 525);
        ctx.stroke();
        ctx.fillText("TrafficFlow Director", 580, 542);
        
        // Signatures lines draw
        ctx.strokeStyle = "#00f0ff";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(180, 518);
        ctx.bezierCurveTo(190, 510, 230, 510, 240, 522);
        ctx.bezierCurveTo(250, 528, 210, 522, 220, 515);
        ctx.stroke();
        
        ctx.strokeStyle = "#ffb800";
        ctx.beginPath();
        ctx.moveTo(540, 516);
        ctx.bezierCurveTo(550, 505, 590, 512, 600, 520);
        ctx.bezierCurveTo(610, 524, 570, 520, 580, 512);
        ctx.stroke();
        
        // Seal Graphic
        ctx.strokeStyle = "rgba(255, 184, 0, 0.3)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(400, 480, 35, 0, Math.PI * 2);
        ctx.stroke();
        
        ctx.fillStyle = "rgba(255, 184, 0, 0.05)";
        ctx.fill();
        
        ctx.fillStyle = "#ffb800";
        ctx.font = "8px 'Outfit', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("OFFICIAL", 400, 478);
        ctx.fillText("BTP SEAL", 400, 488);
        
        document.getElementById("cert-canvas-container").style.display = "block";
        
        const downloadBtn = document.getElementById("btn-download-cert");
        downloadBtn.onclick = () => {
            const link = document.createElement("a");
            link.download = `TrafficFlow_Safety_Certificate_${userName.replace(/\s+/g, "_")}.png`;
            link.href = canvas.toDataURL("image/png");
            link.click();
        };
    }

    // Initialize Safety Learning Hub Layout and triggers
    function initSafetyHub() {
        // Fetch Video Database Configurations
        fetch("/api/video_links")
            .then(res => res.json())
            .then(data => {
                VIDEO_DATABASE = data;
                renderVideoLibrary("all");
            })
            .catch(err => console.error("Error loading video links config:", err));

        loadRulesDirectory();
        loadSafetyHubData();
        
        // Search filter input binding
        const safetySearchInput = document.getElementById("safety-search-input");
        if (safetySearchInput) {
            safetySearchInput.addEventListener("input", () => {
                const query = safetySearchInput.value.toLowerCase().trim();
                
                // Filter Video cards
                const videoCards = document.querySelectorAll("#video-library-grid .video-card");
                videoCards.forEach(card => {
                    const title = card.getAttribute("data-title") || "";
                    const desc = card.getAttribute("data-desc") || "";
                    if (title.includes(query) || desc.includes(query)) {
                        card.style.display = "";
                    } else {
                        card.style.display = "none";
                    }
                });
                
                // Filter Rules cards
                const ruleCards = document.querySelectorAll("#rules-directory-grid .rule-card");
                ruleCards.forEach(card => {
                    const title = card.getAttribute("data-title") || "";
                    const desc = card.getAttribute("data-desc") || "";
                    if (title.includes(query) || desc.includes(query)) {
                        card.style.display = "";
                    } else {
                        card.style.display = "none";
                    }
                });
            });
        }

        // Bind Category Filters
        const filterBtns = document.querySelectorAll(".category-filters .filter-btn");
        filterBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                filterBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                const cat = btn.getAttribute("data-category");
                
                // Translate visual filters to category database names
                let filterVal = "all";
                if (cat === "Helmet Safety") filterVal = "Helmet Safety";
                else if (cat === "Triple Riding Risks") filterVal = "Triple Riding Risks";
                else if (cat === "Traffic Signal Rules") filterVal = "Traffic Signal Rules";
                else if (cat === "Seatbelt Awareness") filterVal = "Seatbelt Awareness";
                else if (cat === "Wrong Side Driving") filterVal = "Wrong Side Driving";
                else if (cat === "Illegal Parking") filterVal = "Illegal Parking";
                else if (cat === "Emergency Vehicle Awareness") filterVal = "Emergency Vehicles";
                
                renderVideoLibrary(filterVal);
            });
        });
        
        // Bind featured banner play button
        const featuredPlayBtn = document.getElementById("btn-watch-featured");
        if (featuredPlayBtn) {
            featuredPlayBtn.addEventListener("click", () => {
                const video = VIDEO_DATABASE.find(v => v.youtube_id === "P23dMAd92B4") || VIDEO_DATABASE[0];
                if (video) playVideoInModal(video);
            });
        }
        
        // Bind Quiz buttons
        const startQuizBtn = document.getElementById("btn-start-quiz");
        if (startQuizBtn) startQuizBtn.onclick = startQuiz;
        
        const nextQuestBtn = document.getElementById("btn-next-question");
        if (nextQuestBtn) nextQuestBtn.onclick = nextQuestion;
        
        const viewCertBtn = document.getElementById("btn-view-certificate");
        if (viewCertBtn) viewCertBtn.onclick = drawCertificate;
        
        const restartQuizBtn = document.getElementById("btn-restart-quiz");
        if (restartQuizBtn) restartQuizBtn.onclick = startQuiz;

        // Close Challan Modal handlers
        const closeChallanModalBtn = document.getElementById("close-challan-modal");
        if (closeChallanModalBtn) {
            closeChallanModalBtn.addEventListener("click", () => {
                document.getElementById("challan-modal").style.display = "none";
                document.getElementById("player-container").innerHTML = ""; // Stop video playback
            });
        }

        // Tab triggers inside modal
        const tabBtns = document.querySelectorAll("#challan-modal .tab-btn");
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                tabBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                
                const tabId = btn.getAttribute("data-tab");
                const contents = document.querySelectorAll("#challan-modal .tab-content");
                contents.forEach(c => c.classList.remove("active"));
                
                const activeContent = document.getElementById(tabId);
                if (activeContent) activeContent.classList.add("active");
                
                // Stop video playback if we leave the video tab
                if (tabId !== "tab-video") {
                    document.getElementById("player-container").innerHTML = "";
                } else {
                    const titleText = document.getElementById("modal-challan-id").textContent;
                    if (titleText.startsWith("CHALLAN:")) {
                        const challanId = titleText.split(" ")[1].split(" ")[0].trim();
                        const log = loadedLogs.find(l => l.challan_id === challanId);
                        if (log) {
                            const matchingVideo = VIDEO_DATABASE.find(v => v.youtube_id === log.violation_type) 
                                || VIDEO_DATABASE.find(v => v.id === "helmet_safety") || VIDEO_DATABASE[0];
                            if (matchingVideo) {
                                loadVideoIntoPlayer(matchingVideo);
                            }
                        }
                    }
                }
            });
        });
    }

    // --- CCTV Streams Grid Simulation (Phase 5) ---
    function startCCTVFeedsSim() {
        const canvases = [
            document.getElementById("cctv-canvas-1"),
            document.getElementById("cctv-canvas-2"),
            document.getElementById("cctv-canvas-3"),
            document.getElementById("cctv-canvas-4")
        ];
        
        const colors = ["#00f0ff", "#0df0a6", "#ffb800", "#ff4d6d"];
        
        canvases.forEach((canvas, idx) => {
            if (!canvas) return;
            const ctx = canvas.getContext("2d");
            let width = canvas.width = 320;
            let height = canvas.height = 180;
            
            let vehicles = [
                { x: 40, y: 70, dx: 1.2, type: "CAR", size: [24, 16] },
                { x: 140, y: 110, dx: 1.8, type: "BIKE", size: [12, 18] },
                { x: 250, y: 60, dx: 1.0, type: "TRUCK", size: [36, 22] }
            ];
            
            function drawFrame() {
                // Check if the current section is command-center to save CPU
                const ccSec = document.getElementById("command-center");
                if (ccSec && !ccSec.classList.contains("active")) {
                    requestAnimationFrame(drawFrame);
                    return;
                }
                
                // Dark background
                ctx.fillStyle = "#030712";
                ctx.fillRect(0, 0, width, height);
                
                // Draw grid lanes
                ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(0, height * 0.45);
                ctx.lineTo(width, height * 0.45);
                ctx.moveTo(0, height * 0.85);
                ctx.lineTo(width, height * 0.85);
                ctx.stroke();
                
                ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
                ctx.setLineDash([8, 8]);
                ctx.beginPath();
                ctx.moveTo(0, height * 0.65);
                ctx.lineTo(width, height * 0.65);
                ctx.stroke();
                ctx.setLineDash([]);
                
                // Animate and draw simulated detections
                vehicles.forEach(v => {
                    v.x += v.dx;
                    if (v.x > width + 30) {
                        v.x = -30;
                    }
                    
                    // Vehicle bounding box
                    ctx.strokeStyle = colors[idx];
                    ctx.lineWidth = 1.2;
                    ctx.strokeRect(v.x, v.y, v.size[0], v.size[1]);
                    
                    // Tag overlay
                    ctx.fillStyle = colors[idx];
                    ctx.font = "bold 7px monospace";
                    ctx.fillText(`${v.type} ${(0.82 + Math.random()*0.15).toFixed(2)}`, v.x, v.y - 4);
                });
                
                // Simulated scanning telemetry line
                const scanLineY = (Date.now() / 20) % height;
                ctx.strokeStyle = "rgba(0, 240, 255, 0.03)";
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(0, scanLineY);
                ctx.lineTo(width, scanLineY);
                ctx.stroke();
                
                requestAnimationFrame(drawFrame);
            }
            drawFrame();
        });
    }

    // --- Repeat Offenders Card Dashboard population (Phase 6) ---
    function populateRepeatOffenders(offenders) {
        const roContainer = document.getElementById("repeat-offenders-container");
        if (!roContainer) return;
        roContainer.innerHTML = "";
        
        if (!offenders || offenders.length === 0) {
            roContainer.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px;">No repeat offenses recorded.</div>`;
            return;
        }
        
        offenders.forEach(ro => {
            const count = parseInt(ro.violations_count) || 0;
            let statusLabel = "WARNING";
            let statusClass = "score-medium";
            if (count >= 3) {
                statusLabel = "BLACKLISTED";
                statusClass = "score-critical";
            }
            
            const card = document.createElement("div");
            card.className = "ro-cc-card";
            card.innerHTML = `
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <span class="ro-cc-plate">${ro.plate_number || 'UNKNOWN'}</span>
                    <span style="font-size:0.75rem; color:var(--text-secondary);">Last: ${(ro.last_violation || 'None').replace(/_/g, ' ')}</span>
                </div>
                <div style="text-align:right; display:flex; flex-direction:column; gap:4px; align-items:flex-end;">
                    <strong style="color:#fff; font-size:0.9rem;">${count} Violations</strong>
                    <span class="hotspot-score-badge ${statusClass}" style="font-size:0.65rem; padding:1px 6px; font-weight:600; min-width:auto; height:auto; line-height:1.2;">${statusLabel}</span>
                </div>
            `;
            roContainer.appendChild(card);
        });
    }

    // --- Patrol Recommendations Card (Phase 7) ---
    function loadPatrolRecommendations() {
        const recContainer = document.getElementById("patrol-deployments-container");
        if (!recContainer) return;
        
        fetch("/api/recommendations")
            .then(res => res.json())
            .then(data => {
                recContainer.innerHTML = "";
                if (!data || data.length === 0) {
                    recContainer.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px;">No patrol dispatches suggested.</div>`;
                    return;
                }
                
                data.forEach((rec, idx) => {
                    let riskClass = "score-low";
                    if (rec.risk_level === "CRITICAL") riskClass = "score-critical";
                    else if (rec.risk_level === "HIGH") riskClass = "score-high";
                    else if (rec.risk_level === "MEDIUM") riskClass = "score-medium";
                    
                    const isDispatched = rec.status === "DISPATCHED";
                    const btnText = isDispatched ? "Deployed ✓" : "Dispatch Patrol";
                    const btnClass = isDispatched ? "rec-dispatch-btn dispatched" : "rec-dispatch-btn";
                    const btnDisabled = isDispatched ? "disabled" : "";

                    const card = document.createElement("div");
                    card.className = "rec-cc-card";
                    card.innerHTML = `
                        <div class="rec-cc-header">
                            <span class="rec-cc-loc">${rec.location}</span>
                            <span class="hotspot-score-badge ${riskClass}" style="font-size:0.68rem; padding:2px 6px; min-width:auto; height:auto; line-height:1.2;">${rec.risk_level}</span>
                        </div>
                        <div class="rec-cc-action">${rec.suggested_action}</div>
                        <div class="rec-cc-footer">
                            <span style="font-size:0.75rem; color:var(--text-secondary);">Rec: <strong>${rec.officers_recommended} Officers</strong></span>
                            <button class="${btnClass}" id="cc-dispatch-btn-${idx}" ${btnDisabled}>${btnText}</button>
                        </div>
                    `;
                    recContainer.appendChild(card);
                    
                    // Bind simulated dispatch action
                    const btn = document.getElementById(`cc-dispatch-btn-${idx}`);
                    if (!isDispatched) {
                        btn.addEventListener("click", () => {
                            btn.disabled = true;
                            btn.textContent = "Deploying...";
                            
                            fetch("/api/dispatch", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    location: rec.location,
                                    action: rec.suggested_action,
                                    camera_id: rec.camera_id
                                })
                           })
                           .then(res => res.json())
                           .then(dispatchRes => {
                               if (dispatchRes.status === "success") {
                                   btn.textContent = "Deployed ✓";
                                   btn.className = "rec-dispatch-btn dispatched";
                                   btn.disabled = true;
                                   showToast(`Patrol dispatched to ${rec.location}!`, "success");
                                   // Trigger full data pull to update logs, notification tables, and charts!
                                   initDashboardData();
                               } else {
                                   showToast("Dispatch failed: " + (dispatchRes.error || "Unknown error"), "error");
                                   btn.disabled = false;
                                   btn.textContent = "Dispatch Patrol";
                               }
                           })
                           .catch(err => {
                               console.error(err);
                               showToast("Dispatch failed — check server connection.", "error");
                               btn.disabled = false;
                               btn.textContent = "Dispatch Patrol";
                           });
                        });
                    }
                });
            })
            .catch(err => console.error("Error loading patrol recommendations:", err));
    }

    // --- Predictive Intelligence forecasting (Phase 8) ---
    function loadPredictiveIntel() {
        const container = document.getElementById("predictive-intel-container");
        if (!container) return;
        
        fetch("/api/predictions")
            .then(res => res.json())
            .then(data => {
                container.innerHTML = "";
                if (!data.forecast) {
                    container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px;">Forecast data unavailable.</div>`;
                    return;
                }
                
                data.forecast.slice(0, 4).forEach(f => {
                    const probPercent = Math.round(f.violation_probability * 100);
                    let color = "var(--accent-emerald)";
                    if (probPercent > 70) color = "var(--accent-red)";
                    else if (probPercent > 40) color = "var(--accent-amber)";
                    
                    const row = document.createElement("div");
                    row.className = "pred-cc-row";
                    row.innerHTML = `
                        <span class="pred-time">${f.time} Forecast</span>
                        <div style="text-align: right; display:flex; gap:12px; align-items:center;">
                            <span style="font-size:0.75rem; color:var(--text-muted);">Risk:</span>
                            <span class="pred-prob" style="color: ${color};">${probPercent}%</span>
                            <span style="font-size:0.75rem; color:var(--text-muted);">Congestion:</span>
                            <span style="font-size:0.82rem; font-weight:700; color:#fff;">${f.congestion_index}</span>
                        </div>
                    `;
                    container.appendChild(row);
                });
                
                const summaryBox = document.createElement("div");
                summaryBox.style.cssText = "margin-top: 10px; background: rgba(0,240,255,0.03); border: 1px dashed rgba(0,240,255,0.15); border-radius: 8px; padding: 10px; font-size: 0.78rem; line-height: 1.4; color: var(--text-secondary);";
                summaryBox.innerHTML = `
                    <strong>🔮 Predictive Insight:</strong> Peak congestion risk forecast at <strong>${data.insights.peak_hour}</strong> around <strong>${data.insights.highest_probability_location}</strong>. <em>Action: ${data.insights.recommended_surveillance_alert}</em>
                `;
                container.appendChild(summaryBox);
            })
            .catch(err => console.error("Error loading predictions:", err));
    }

    // --- Active Deployed Patrols Board wiring ---
    function loadDeployedPatrols() {
        const container = document.getElementById("deployed-officers-container");
        const badge = document.getElementById("deployed-count-badge");
        if (!container) return;

        fetch("/api/deployed_patrols")
            .then(res => res.json())
            .then(data => {
                if (badge) badge.textContent = `${data.count || 0} Deployed`;

                container.innerHTML = "";
                if (!data.deployed || data.deployed.length === 0) {
                    container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px; grid-column: 1/-1;">No patrols dispatched yet. Use the Dispatch Patrol buttons above.</div>`;
                    return;
                }

                data.deployed.forEach(patrol => {
                    const card = document.createElement("div");
                    card.className = "rec-cc-card";
                    card.style.cssText = "background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.08); padding: 12px; border-radius: 8px; display: flex; flex-direction: column; gap: 6px;";

                    const timeStr = patrol.timestamp.split(" ")[1] || patrol.timestamp;

                    card.innerHTML = `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <strong style="color: #fff; font-size: 0.88rem;">${patrol.location}</strong>
                            <span class="hotspot-score-badge score-high" style="font-size: 0.65rem; padding: 2px 6px; min-width: auto; height: auto; line-height: 1.2; background: rgba(0, 240, 255, 0.15); border: 1px solid rgba(0, 240, 255, 0.4); color: #00f0ff;">ACTIVE</span>
                        </div>
                        <div style="font-size: 0.82rem; color: var(--text-secondary);">${patrol.status}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted); text-align: right; margin-top: 4px;">Time: ${timeStr}</div>
                    `;
                    container.appendChild(card);
                });
            })
            .catch(err => console.error("Error loading deployed patrols:", err));
    }

    // --- AI Performance Metrics Card (Phase 3) ---
    function loadAIPerformanceMetrics() {
        const container = document.getElementById("ai-performance-container");
        if (!container) return;
        
        fetch("/api/evaluation")
            .then(res => res.json())
            .then(data => {
                container.innerHTML = "";
                if (!data || !data.class_statistics) {
                    container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 20px;">AI metrics unavailable.</div>`;
                    return;
                }
                
                // Add Inference Time
                const latencyRow = document.createElement("div");
                latencyRow.style.cssText = "display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--border-color); font-weight: 600; color: var(--accent-cyan); font-size: 0.8rem;";
                latencyRow.innerHTML = `
                    <span>⚡ Avg Inference Speed</span>
                    <span>${data.inference_time_ms} ms</span>
                `;
                container.appendChild(latencyRow);
                
                const stats = data.class_statistics;
                const classes = [
                    { key: "HELMET_VIOLATION", label: "Helmet Detection" },
                    { key: "TRIPLE_RIDING", label: "Triple Riding" },
                    { key: "WRONG_SIDE_DRIVING", label: "Wrong Side Driving" },
                    { key: "ILLEGAL_PARKING", label: "Illegal Parking" },
                    { key: "OCR_ACCURACY", label: "OCR Accuracy" }
                ];
                
                classes.forEach(cls => {
                    const cStat = stats[cls.key] || { precision: 90, recall: 88, f1: 89, map: 86 };
                    const row = document.createElement("div");
                    row.style.cssText = "display: flex; flex-direction: column; gap: 2px; margin-bottom: 6px; font-size: 0.76rem;";
                    row.innerHTML = `
                        <div style="display: flex; justify-content: space-between; font-weight: 600; color: #fff;">
                            <span>${cls.label}</span>
                            <span style="color: var(--accent-cyan);">F1: ${cStat.f1}%</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.68rem; color: var(--text-secondary);">
                            <span>P: ${cStat.precision}%</span>
                            <span>R: ${cStat.recall}%</span>
                            <span>mAP: ${cStat.map || cStat.precision}%</span>
                        </div>
                    `;
                    container.appendChild(row);
                });
            })
            .catch(err => console.error("Error loading AI performance metrics:", err));
    }

    // --- AI Assistant Chatbot (Phase 10) ---
    function initAIChatbot() {
        const widget = document.getElementById("chatbot-widget");
        const launcher = document.getElementById("chatbot-launcher");
        const closeBtn = document.getElementById("chatbot-close-btn");
        const form = document.getElementById("chatbot-form");
        const input = document.getElementById("chatbot-input");
        const messagesContainer = document.getElementById("chatbot-messages");
        
        if (!widget || !launcher) return;
        
        launcher.addEventListener("click", () => {
            widget.style.display = widget.style.display === "flex" ? "none" : "flex";
        });
        
        closeBtn.addEventListener("click", () => {
            widget.style.display = "none";
        });
        
        form.addEventListener("submit", (e) => {
            e.preventDefault();
            const val = input.value.trim();
            if (!val) return;
            
            appendChatMessage("user", val);
            input.value = "";
            
            const loadingId = appendChatMessage("bot", "Querying BTP database...");
            
            fetch("/api/ai_assistant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: val })
            })
            .then(res => res.json())
            .then(data => {
                const loadingMsg = document.getElementById(loadingId);
                if (loadingMsg) {
                    loadingMsg.innerHTML = formatBotMessage(data.response);
                }
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            })
            .catch(err => {
                const loadingMsg = document.getElementById(loadingId);
                if (loadingMsg) {
                    loadingMsg.textContent = "Error running query. Please try again.";
                }
            });
        });
        
        function appendChatMessage(sender, text) {
            const msg = document.createElement("div");
            const id = "chat-msg-" + Date.now();
            msg.id = id;
            msg.className = `message ${sender}`;
            msg.textContent = text;
            messagesContainer.appendChild(msg);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            return id;
        }
        
        function formatBotMessage(text) {
            let formatted = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            formatted = formatted.replace(/- \*(.*?)\*/g, '<li>$1</li>');
            formatted = formatted.replace(/\n/g, '<br>');
            return formatted;
        }
    }

    // Run Initializers
    initCommandCenter();
    initDashboardData();
    initSafetyHub();
    initChartTabs();
    initAIChatbot();
});
