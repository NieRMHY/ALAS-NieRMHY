(function() {
    function setTooltipContent(tipEl, rows) {
        if (!tipEl || !Array.isArray(rows)) return;
        while (tipEl.firstChild) {
            tipEl.removeChild(tipEl.firstChild);
        }
        rows.forEach(function(row) {
            if (!row) return;
            var div = document.createElement('div');
            if (row.style && typeof row.style === 'object') {
                Object.keys(row.style).forEach(function(k) {
                    div.style[k] = row.style[k];
                });
            }
            if (row.parts && Array.isArray(row.parts)) {
                row.parts.forEach(function(part) {
                    if (!part) return;
                    if (part.type === 'text') {
                        var span = document.createElement('span');
                        span.textContent = part.value != null ? String(part.value) : '';
                        if (part.style && typeof part.style === 'object') {
                            Object.keys(part.style).forEach(function(k) {
                                span.style[k] = part.style[k];
                            });
                        }
                        div.appendChild(span);
                    } else if (part.type === 'bold') {
                        var b = document.createElement('b');
                        b.textContent = part.value != null ? String(part.value) : '';
                        if (part.style && typeof part.style === 'object') {
                            Object.keys(part.style).forEach(function(k) {
                                b.style[k] = part.style[k];
                            });
                        }
                        div.appendChild(b);
                    }
                });
            }
            tipEl.appendChild(div);
        });
    }

    var chartType = "__CHART_TYPE__";
    var labels = __LABELS__;
    var opens  = __OPENS__;
    var highs  = __HIGHS__;
    var lows   = __LOWS__;
    var closes = __CLOSES__;
    var counts = __COUNTS__;
    var ap = __AP__;
    var avg = __AVG__;
    var isDetailMode = __IS_DETAIL_MODE__;
    var sources = __SOURCES__;
    var yellowCoins = __YELLOW_COINS__;
    var purpleCoins = __PURPLE_COINS__;
    var coinsSources = __COINS_SOURCES__;
    var showCoins = __SHOW_COINS__;
    var nn = chartType === 'line' ? ap.length : labels.length;
    if (nn < 1) return;

    var chartId = "__CHART_ID__";
    var cv = document.getElementById(chartId);
    if (!cv) return;
    var tipEl = document.getElementById(chartId + "_tip");
    var ovCv = document.getElementById(chartId + "_ov");

    var dpr = window.devicePixelRatio || 1;
    var W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ovCv.width = W * dpr; ovCv.height = H * dpr;
    ovCv.style.width = W + "px"; ovCv.style.height = H + "px";

    var ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);
    var oc = ovCv.getContext("2d");

    // 硬币刻度标签布局常量
    var COIN_TICK_X = 8;            // 右侧刻度标签相对 pad.r 的水平偏移
    var COIN_TICK_BASELINE = 4;     // 单币时文字基线垂直偏移
    var COIN_TICK_STACK_GAP = 12;   // 双币堆叠时紫币相对黄币的垂直偏移

    var pad = {t: 20, r: showCoins ? 72 : 20, b: 52, l: 52};
    var gW = W - pad.l - pad.r, gH = H - pad.t - pad.b;

    var allMin = Infinity, allMax = -Infinity;
    if (chartType === 'line') {
        for (var i = 0; i < nn; i++) {
            if (ap[i] < allMin) allMin = ap[i];
            if (ap[i] > allMax) allMax = ap[i];
        }
    } else {
        for (var i = 0; i < nn; i++) {
            if (lows[i] < allMin) allMin = lows[i];
            if (highs[i] > allMax) allMax = highs[i];
        }
    }
    var rng = allMax - allMin || 1;
    allMin -= rng * 0.08;
    allMax += rng * 0.08;

    // ---- 黄币独立范围 ----
    var yellowMin = Infinity, yellowMax = -Infinity;
    var yellowCoinsLen = yellowCoins ? yellowCoins.length : 0;
    var hasYellowCoins = showCoins && chartType === 'line' && yellowCoinsLen > 0;
    if (hasYellowCoins) {
        for (var i = 0; i < yellowCoinsLen; i++) {
            if (yellowCoins[i] === null || yellowCoins[i] === undefined) continue;
            if (yellowCoins[i] < yellowMin) yellowMin = yellowCoins[i];
            if (yellowCoins[i] > yellowMax) yellowMax = yellowCoins[i];
        }
        if (yellowMin === Infinity) yellowMin = 0;
        if (yellowMax === -Infinity) yellowMax = 1000;
        var yellowRng = yellowMax - yellowMin || 1;
        yellowMin -= yellowRng * 0.08;
        yellowMax += yellowRng * 0.08;
    }

    // ---- 紫币独立范围 ----
    var purpleMin = Infinity, purpleMax = -Infinity;
    var purpleCoinsLen = purpleCoins ? purpleCoins.length : 0;
    var hasPurpleCoins = showCoins && chartType === 'line' && purpleCoinsLen > 0;
    if (hasPurpleCoins) {
        for (var i = 0; i < purpleCoinsLen; i++) {
            if (purpleCoins[i] === null || purpleCoins[i] === undefined) continue;
            if (purpleCoins[i] < purpleMin) purpleMin = purpleCoins[i];
            if (purpleCoins[i] > purpleMax) purpleMax = purpleCoins[i];
        }
        if (purpleMin === Infinity) purpleMin = 0;
        if (purpleMax === -Infinity) purpleMax = 1000;
        var purpleRng = purpleMax - purpleMin || 1;
        purpleMin -= purpleRng * 0.08;
        purpleMax += purpleRng * 0.08;
    }

    var hasCoins = hasYellowCoins || hasPurpleCoins;

    // 硬币绘制参数化配置（颜色 / 范围 / 垂直偏移），driven by drawCoinTicks
    var COIN_CONFIGS = [
        { has: hasYellowCoins, color: "#ffd54f", dataMin: yellowMin, dataMax: yellowMax, offsetY: 0 },
        { has: hasPurpleCoins, color: "#ce93d8", dataMin: purpleMin,  dataMax: purpleMax,  offsetY: hasYellowCoins ? COIN_TICK_STACK_GAP : 0 }
    ];

    function xOfLine(i) { return pad.l + (i / Math.max(nn - 1, 1)) * gW; }
    // 通用 Y 坐标映射：将 value 从 [rangeMin, rangeMax] 映射到绘图区域（所有纵向映射的唯一来源）
    function yScale(value, rangeMin, rangeMax) {
        return pad.t + gH - (value - rangeMin) / (rangeMax - rangeMin) * gH;
    }
    function yOf(v) { return yScale(v, allMin, allMax); }
    function yOfYellow(v) { return yScale(v, yellowMin, yellowMax); }
    function yOfPurple(v) { return yScale(v, purpleMin, purpleMax); }

    function drawCoinTicks(ctx, yOfMain, mainMin, mainMax) {
        if (!hasCoins) return;
        ctx.font = "10px -apple-system, sans-serif";
        ctx.textAlign = "left";
        for (var i = 0; i <= 5; i++) {
            var mainVal = mainMin + (mainMax - mainMin) * (i / 5);
            var y = yOfMain(mainVal);
            for (var ci = 0; ci < COIN_CONFIGS.length; ci++) {
                var cfg = COIN_CONFIGS[ci];
                if (!cfg.has) continue;
                var val = cfg.dataMin + (cfg.dataMax - cfg.dataMin) * (i / 5);
                ctx.fillStyle = cfg.color;
                ctx.fillText(Math.round(val), W - pad.r + COIN_TICK_X, y + COIN_TICK_BASELINE + cfg.offsetY);
            }
        }
    }

    function drawCoinsLine(xOf, start, end) {
        if (!hasCoins) return;

        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.setLineDash([4, 2]);

        if (hasYellowCoins) {
            ctx.beginPath();
            ctx.strokeStyle = "#ffd54f";
            var startedYellow = false;
            for (var i = start; i < end && i < yellowCoinsLen; i++) {
                if (yellowCoins[i] === null || yellowCoins[i] === undefined) {
                    startedYellow = false;
                    continue;
                }
                var x = xOf(i), y = yOfYellow(yellowCoins[i]);
                if (!startedYellow) { ctx.moveTo(x, y); startedYellow = true; }
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
        }

        if (hasPurpleCoins) {
            ctx.beginPath();
            ctx.strokeStyle = "#ce93d8";
            var startedPurple = false;
            for (var i = start; i < end && i < purpleCoinsLen; i++) {
                if (purpleCoins[i] === null || purpleCoins[i] === undefined) {
                    startedPurple = false;
                    continue;
                }
                var x = xOf(i), y = yOfPurple(purpleCoins[i]);
                if (!startedPurple) { ctx.moveTo(x, y); startedPurple = true; }
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
        }

        ctx.setLineDash([]);
    }

    var candleSpace = gW / nn;
    var candleW = Math.max(3, Math.min(candleSpace * 0.6, 30));
    function xCenter(i) { return pad.l + candleSpace * (i + 0.5); }

    ctx.fillStyle = "#1a1a2e";
    ctx.fillRect(0, 0, W, H);

    ctx.strokeStyle = "#2a2a3e";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#666";
    ctx.font = "11px -apple-system, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var i = 0; i <= 5; i++) {
        var v = allMin + (allMax - allMin) * (i / 5);
        var y = yOf(v);
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
        ctx.fillText(Math.round(v), pad.l - 8, y);
    }

    drawCoinTicks(ctx, yOf, allMin, allMax);

    var avgY = yOf(avg);
    ctx.save();
    ctx.strokeStyle = "#ff9800";
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, avgY); ctx.lineTo(W - pad.r, avgY); ctx.stroke();
    ctx.restore();
    ctx.fillStyle = "#ff9800";
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("均值:" + avg, W - pad.r - 4, avgY - 8);

    ctx.fillStyle = "#666";
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    if (chartType === 'line') {
        var labelStep = Math.max(1, Math.floor(nn / 8));
        for (var i = 0; i < nn; i += labelStep) {
            ctx.save();
            ctx.translate(xOfLine(i), H - pad.b + 8);
            ctx.rotate(0.4);
            ctx.fillText(labels[i], 0, 0);
            ctx.restore();
        }
    } else {
        var labelStep = Math.max(1, Math.floor(nn / 12));
        for (var i = 0; i < nn; i += labelStep) {
            ctx.fillText(labels[i], xCenter(i), H - pad.b + 8);
        }
    }

    if (chartType === 'line') {
        var grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + gH);
        grad.addColorStop(0, "rgba(100,120,160,0.18)");
        grad.addColorStop(1, "rgba(100,120,160,0.02)");
        ctx.beginPath();
        ctx.moveTo(xOfLine(0), yOf(ap[0]));
        for (var i = 1; i < nn; i++) {
            if (nn < 30) {
                var x0 = xOfLine(i-1), y0 = yOf(ap[i-1]), x1 = xOfLine(i), y1 = yOf(ap[i]);
                var cpx = (x0 + x1) / 2;
                ctx.bezierCurveTo(cpx, y0, cpx, y1, x1, y1);
            } else {
                ctx.lineTo(xOfLine(i), yOf(ap[i]));
            }
        }
        ctx.lineTo(xOfLine(nn-1), pad.t + gH);
        ctx.lineTo(xOfLine(0), pad.t + gH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        for (var i = 1; i < nn; i++) {
            ctx.beginPath();
            ctx.moveTo(xOfLine(i-1), yOf(ap[i-1]));
            var segmentColor = ap[i] >= ap[i-1] ? "#ef5350" : "#26a69a";
            ctx.strokeStyle = segmentColor;
            if (nn < 30) {
                var x0 = xOfLine(i-1), y0 = yOf(ap[i-1]), x1 = xOfLine(i), y1 = yOf(ap[i]);
                var cpx = (x0 + x1) / 2;
                ctx.bezierCurveTo(cpx, y0, cpx, y1, x1, y1);
            } else {
                ctx.lineTo(xOfLine(i), yOf(ap[i]));
            }
            ctx.stroke();
        }
        if (nn < 60) {
            for (var i = 0; i < nn; i++) {
                ctx.beginPath();
                ctx.arc(xOfLine(i), yOf(ap[i]), 3.5, 0, Math.PI * 2);
                var dotColor = (i > 0 && ap[i] < ap[i-1]) ? "#26a69a" : "#ef5350";
                ctx.fillStyle = dotColor;
                ctx.fill();
                ctx.strokeStyle = "#1a1a2e";
                ctx.lineWidth = 1.5;
                ctx.stroke();
            }
        }
    } else {
        for (var i = 0; i < nn; i++) {
            var cx = xCenter(i);
            var o = opens[i], h = highs[i], l = lows[i], c = closes[i];
            var isUp = c > o;
            var isDown = c < o;
            var isFlat = c === o;
            var color = isFlat ? "#888" : (isUp ? "#ef5350" : "#26a69a");

            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(cx, yOf(h));
            ctx.lineTo(cx, yOf(l));
            ctx.stroke();

            var bodyTop = yOf(Math.max(o, c));
            var bodyBot = yOf(Math.min(o, c));
            var bodyH = Math.max(bodyBot - bodyTop, 1);

            if (isUp || isDown) {
                ctx.fillStyle = color;
                ctx.fillRect(cx - candleW / 2, bodyTop, candleW, bodyH);
            } else {
                ctx.beginPath();
                ctx.moveTo(cx - candleW / 2, yOf(o));
                ctx.lineTo(cx + candleW / 2, yOf(o));
                ctx.stroke();
            }
        }

        function drawMA(days, maColor) {
            if (nn < days) return;
            ctx.beginPath();
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = maColor;
            var started = false;
            for (var i = days - 1; i < nn; i++) {
                var sum = 0;
                for (var j = 0; j < days; j++) sum += closes[i - j];
                var maVal = sum / days;
                var x = xCenter(i), y = yOf(maVal);
                if (!started) { ctx.moveTo(x, y); started = true; }
                else { ctx.lineTo(x, y); }
            }
            ctx.stroke();
        }
        drawMA(5, "#ffeb3b");
        drawMA(10, "#e91e63");
    }

    drawCoinsLine(xOfLine, 0, nn);

    cv.addEventListener("mousemove", function(e) {
        var rect = cv.getBoundingClientRect();
        var mx_ = e.clientX - rect.left;
        var my_ = e.clientY - rect.top;

        oc.setTransform(1, 0, 0, 1, 0, 0);
        oc.clearRect(0, 0, ovCv.width, ovCv.height);

        if (mx_ < pad.l || mx_ > W - pad.r || my_ < pad.t || my_ > pad.t + gH) {
            tipEl.style.display = "none";
            return;
        }

        oc.scale(dpr, dpr);

        if (chartType === 'line') {
            var visibleStart = Math.max(0, Math.floor(panOffset));
            var visibleCount = Math.ceil(nn / zoomLevel);
            var visibleEnd = Math.min(nn, visibleStart + visibleCount);
            var visibleNn = visibleEnd - visibleStart;

            var dMin = Infinity, dMax = -Infinity;
            for (var i = visibleStart; i < visibleEnd; i++) {
                if (ap[i] < dMin) dMin = ap[i];
                if (ap[i] > dMax) dMax = ap[i];
            }
            if (dMin === Infinity) dMin = 0;
            if (dMax === -Infinity) dMax = 100;
            var drng = dMax - dMin || 1;
            dMin -= drng * 0.1;
            dMax += drng * 0.1;

            var xScale = gW / Math.max(visibleNn - 1, 1);
            var idx = Math.round(visibleStart + (mx_ - pad.l) / xScale);
            idx = Math.max(0, Math.min(nn - 1, idx));
            var px = pad.l + (idx - visibleStart) * xScale;
            var py = yScale(ap[idx], dMin, dMax);

            oc.strokeStyle = "rgba(255,255,255,0.18)";
            oc.lineWidth = 1;
            oc.setLineDash([4, 3]);
            oc.beginPath(); oc.moveTo(px, pad.t); oc.lineTo(px, pad.t + gH); oc.stroke();
            oc.beginPath(); oc.moveTo(pad.l, py); oc.lineTo(W - pad.r, py); oc.stroke();
            oc.setLineDash([]);

            oc.beginPath(); oc.arc(px, py, 6, 0, Math.PI * 2);
            oc.fillStyle = "rgba(100,181,246,0.3)"; oc.fill();
            oc.beginPath(); oc.arc(px, py, 4, 0, Math.PI * 2);
            oc.fillStyle = "#64b5f6"; oc.fill();
            oc.strokeStyle = "#fff"; oc.lineWidth = 2; oc.stroke();
            oc.setTransform(1, 0, 0, 1, 0, 0);

            var diff = idx > 0 ? (ap[idx] - ap[idx - 1]) : 0;
            var isUp = diff >= 0;
            var dc = isUp ? "#ef5350" : "#26a69a";
            var ds = (isUp ? "+" : "") + diff;
            var tooltipRows = [
                { style: { color: "#888", marginBottom: "4px", fontWeight: "600" }, parts: [{ type: 'text', value: labels[idx] }] },
                { parts: [{ type: 'text', value: "体力: " }, { type: 'bold', value: String(ap[idx]), style: { color: "#64b5f6" } }] },
                { parts: [{ type: 'text', value: "单次变化: " }, { type: 'bold', value: ds, style: { color: dc } }] }
            ];

            if (isDetailMode) {
                var source = sources && sources[idx] ? sources[idx] : '-';
                var sourceColor = source === 'cl1' ? '#64b5f6' : (source === 'meow' ? '#ff9800' : '#888');
                tooltipRows.push({ parts: [{ type: 'text', value: "来源: " }, { type: 'bold', value: source, style: { color: sourceColor } }] });
            }

            if (hasYellowCoins && idx < yellowCoinsLen && yellowCoins[idx] !== null && yellowCoins[idx] !== undefined) {
                var yc = yellowCoins[idx];
                var ycDiff = idx > 0 && yellowCoins[idx - 1] !== null && yellowCoins[idx - 1] !== undefined ? (yc - yellowCoins[idx - 1]) : 0;
                var ycColor = ycDiff >= 0 ? "#ef5350" : "#26a69a";
                var ycDiffStr = (ycDiff >= 0 ? "+" : "") + ycDiff;
                tooltipRows.push({ parts: [{ type: 'text', value: "黄币: " }, { type: 'bold', value: String(yc), style: { color: "#ffd54f" } }, { type: 'text', value: " (" + ycDiffStr + ")", style: { color: ycColor } }] });
            }

            if (hasPurpleCoins && idx < purpleCoinsLen && purpleCoins[idx] !== null && purpleCoins[idx] !== undefined) {
                var pc = purpleCoins[idx];
                var pcDiff = idx > 0 && purpleCoins[idx - 1] !== null && purpleCoins[idx - 1] !== undefined ? (pc - purpleCoins[idx - 1]) : 0;
                var pcColor = pcDiff >= 0 ? "#ef5350" : "#26a69a";
                var pcDiffStr = (pcDiff >= 0 ? "+" : "") + pcDiff;
                tooltipRows.push({ parts: [{ type: 'text', value: "紫币: " }, { type: 'bold', value: String(pc), style: { color: "#ce93d8" } }, { type: 'text', value: " (" + pcDiffStr + ")", style: { color: pcColor } }] });
            }

            setTooltipContent(tipEl, tooltipRows);
        } else {
            var idx = Math.floor((mx_ - pad.l) / candleSpace);
            idx = Math.max(0, Math.min(nn - 1, idx));
            var cx = xCenter(idx);

            oc.strokeStyle = "rgba(255,255,255,0.18)";
            oc.lineWidth = 1;
            oc.setLineDash([4, 3]);
            oc.beginPath(); oc.moveTo(cx, pad.t); oc.lineTo(cx, pad.t + gH); oc.stroke();
            oc.beginPath(); oc.moveTo(pad.l, my_); oc.lineTo(W - pad.r, my_); oc.stroke();
            oc.setLineDash([]);

            oc.strokeStyle = "#fff";
            oc.lineWidth = 1;
            oc.globalAlpha = 0.15;
            oc.fillStyle = "#fff";
            oc.fillRect(cx - candleW / 2 - 2, pad.t, candleW + 4, gH);
            oc.globalAlpha = 1.0;
            oc.setTransform(1, 0, 0, 1, 0, 0);

            var o = opens[idx], h = highs[idx], l = lows[idx], c_ = closes[idx];
            var chg = c_ - o;
            var chgPct = o !== 0 ? ((chg / o) * 100).toFixed(1) : "0.0";
            var isUp = c_ >= o;
            var dc = isUp ? "#ef5350" : "#26a69a";
            var chgSign = chg >= 0 ? "+" : "";

            var ma5Val = "-";
            if (idx >= 4) {
                var sum5 = 0; for(var j=0; j<5; j++) sum5+=closes[idx-j];
                ma5Val = (sum5/5).toFixed(1);
            }
            var ma10Val = "-";
            if (idx >= 9) {
                var sum10 = 0; for(var j=0; j<10; j++) sum10+=closes[idx-j];
                ma10Val = (sum10/10).toFixed(1);
            }

            setTooltipContent(tipEl, [
                { style: { color: "#888", marginBottom: "4px", fontWeight: "600" }, parts: [{ type: 'text', value: labels[idx] }] },
                { parts: [
                    { type: 'text', value: "开盘: " },
                    { type: 'bold', value: String(o) },
                    { type: 'text', value: "  MA5(5期平均): " + ma5Val, style: { marginLeft: "8px", color: "#ffeb3b" } }
                ]},
                { parts: [
                    { type: 'text', value: "收盘: " },
                    { type: 'bold', value: String(c_), style: { color: dc } },
                    { type: 'text', value: "  MA10(10期平均): " + ma10Val, style: { marginLeft: "8px", color: "#e91e63" } }
                ]},
                { parts: [{ type: 'text', value: "最高: " }, { type: 'bold', value: String(h), style: { color: "#ef5350" } }] },
                { parts: [{ type: 'text', value: "最低: " }, { type: 'bold', value: String(l), style: { color: "#26a69a" } }] },
                { parts: [{ type: 'text', value: "涨跌: " }, { type: 'bold', value: chgSign + chg + " (" + chgSign + chgPct + "%)", style: { color: dc } }] },
                { style: { color: "#666", marginTop: "4px" }, parts: [{ type: 'text', value: "数据点密度: " + counts[idx] }] }
            ]);
        }

        tipEl.style.display = "block";
        var tx = (chartType === 'line' ? px : cx) + 18;
        var ty = my_ - 60;
        if (tx + 180 > W) tx = (chartType === 'line' ? px : cx) - 200;
        if (ty < 8) ty = my_ + 18;
        tipEl.style.left = tx + "px";
        tipEl.style.top = ty + "px";
    });

    cv.addEventListener("mouseleave", function() {
        tipEl.style.display = "none";
        oc.setTransform(1, 0, 0, 1, 0, 0);
        oc.clearRect(0, 0, ovCv.width, ovCv.height);
    });

    if (chartType === 'line') {
        var zoomLevel = 1.0;
        var panOffset = 0;
        var maxZoom = 5.0;
        var minZoom = 0.5;

        function renderDetailChart() {
            var visibleStart = Math.max(0, Math.floor(panOffset));
            var visibleCount = Math.ceil(nn / zoomLevel);
            var visibleEnd = Math.min(nn, visibleStart + visibleCount);
            var visibleNn = visibleEnd - visibleStart;

            var dMin = Infinity, dMax = -Infinity;
            for (var i = visibleStart; i < visibleEnd; i++) {
                if (ap[i] < dMin) dMin = ap[i];
                if (ap[i] > dMax) dMax = ap[i];
            }
            if (dMin === Infinity) dMin = 0;
            if (dMax === -Infinity) dMax = 100;
            var drng = dMax - dMin || 1;
            dMin -= drng * 0.1;
            dMax += drng * 0.1;

            ctx.fillStyle = "#1a1a2e";
            ctx.fillRect(0, 0, W, H);

            ctx.strokeStyle = "#2a2a3e";
            ctx.lineWidth = 1;
            ctx.fillStyle = "#666";
            ctx.font = "11px -apple-system, sans-serif";
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            for (var i = 0; i <= 5; i++) {
                var v = dMin + (dMax - dMin) * (i / 5);
                var y = yScale(v, dMin, dMax);
                ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
                ctx.fillText(Math.round(v), pad.l - 8, y);
            }

            var xScale = gW / Math.max(visibleNn - 1, 1);
            function dxOf(i) { return pad.l + (i - visibleStart) * xScale; }
            function dyOf(v) { return yScale(v, dMin, dMax); }

            drawCoinTicks(ctx, dyOf, dMin, dMax);

            ctx.fillStyle = "#666";
            ctx.font = "10px -apple-system, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";

            var dgrad = ctx.createLinearGradient(0, pad.t, 0, pad.t + gH);
            dgrad.addColorStop(0, "rgba(100,181,246,0.15)");
            dgrad.addColorStop(1, "rgba(100,181,246,0.02)");
            ctx.beginPath();
            ctx.moveTo(dxOf(visibleStart), dyOf(ap[visibleStart]));
            for (var i = visibleStart + 1; i < visibleEnd; i++) {
                ctx.lineTo(dxOf(i), dyOf(ap[i]));
            }
            ctx.lineTo(dxOf(visibleEnd - 1), pad.t + gH);
            ctx.lineTo(dxOf(visibleStart), pad.t + gH);
            ctx.closePath();
            ctx.fillStyle = dgrad;
            ctx.fill();

            ctx.lineWidth = 1.5;
            ctx.lineJoin = "round";
            for (var i = visibleStart + 1; i < visibleEnd; i++) {
                ctx.beginPath();
                ctx.moveTo(dxOf(i - 1), dyOf(ap[i - 1]));
                ctx.strokeStyle = ap[i] >= ap[i - 1] ? "#ef5350" : "#26a69a";
                ctx.lineTo(dxOf(i), dyOf(ap[i]));
                ctx.stroke();
            }

            var dotInterval = Math.max(1, Math.floor(visibleNn / 50));
            for (var i = visibleStart; i < visibleEnd; i += dotInterval) {
                ctx.beginPath();
                ctx.arc(dxOf(i), dyOf(ap[i]), 2.5, 0, Math.PI * 2);
                var dotColor = (i > visibleStart && ap[i] < ap[i - 1]) ? "#26a69a" : "#ef5350";
                ctx.fillStyle = dotColor;
                ctx.fill();
            }

            drawCoinsLine(dxOf, visibleStart, visibleEnd);

            var labelInterval = Math.max(1, Math.floor(visibleNn / 8));
            for (var i = visibleStart; i < visibleEnd; i += labelInterval) {
                var lx = dxOf(i);
                ctx.save();
                ctx.translate(lx, H - pad.b + 8);
                ctx.rotate(0.3);
                ctx.fillText(labels[i], 0, 0);
                ctx.restore();
            }
        }

        renderDetailChart();

        var isDragging = false;
        var dragStartX = 0;
        var dragStartPan = 0;

        cv.addEventListener("mousedown", function(e) {
            isDragging = true;
            dragStartX = e.clientX;
            dragStartPan = panOffset;
            cv.style.cursor = "grabbing";
        });

        document.addEventListener("mousemove", function(e) {
            if (!isDragging) return;
            var dx = e.clientX - dragStartX;
            var visibleCount = Math.ceil(nn / zoomLevel);
            var xScale = gW / Math.max(visibleCount - 1, 1);
            var newPan = dragStartPan - dx / xScale;
            var maxPan = Math.max(0, nn - visibleCount);
            panOffset = Math.max(0, Math.min(maxPan, newPan));
            renderDetailChart();
        });

        document.addEventListener("mouseup", function() {
            if (isDragging) {
                isDragging = false;
                cv.style.cursor = "crosshair";
            }
        });

        cv.addEventListener("wheel", function(e) {
            e.preventDefault();
            var rect = cv.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
            var newZoom = Math.max(minZoom, Math.min(maxZoom, zoomLevel * zoomFactor));
            if (newZoom !== zoomLevel) {
                var visibleCountBefore = Math.ceil(nn / zoomLevel);
                var visibleCountAfter = Math.ceil(nn / newZoom);
                var xScaleBefore = gW / Math.max(visibleCountBefore - 1, 1);
                var mouseIdx = panOffset + (mx - pad.l) / xScaleBefore;
                zoomLevel = newZoom;
                var xScaleAfter = gW / Math.max(visibleCountAfter - 1, 1);
                panOffset = Math.max(0, mouseIdx - (mx - pad.l) / xScaleAfter);
                var maxPan = Math.max(0, nn - visibleCountAfter);
                panOffset = Math.max(0, Math.min(maxPan, panOffset));
                renderDetailChart();
            }
        }, { passive: false });

        var zoomInBtn = document.getElementById(chartId + "_zoom_in");
        var zoomOutBtn = document.getElementById(chartId + "_zoom_out");
        var zoomResetBtn = document.getElementById(chartId + "_reset");

        if (zoomInBtn) {
            zoomInBtn.addEventListener("click", function() {
                zoomLevel = Math.min(maxZoom, zoomLevel * 1.5);
                var visibleCount = Math.ceil(nn / zoomLevel);
                var maxPan = Math.max(0, nn - visibleCount);
                panOffset = Math.min(panOffset, maxPan);
                renderDetailChart();
            });
        }

        if (zoomOutBtn) {
            zoomOutBtn.addEventListener("click", function() {
                zoomLevel = Math.max(minZoom, zoomLevel / 1.5);
                renderDetailChart();
            });
        }

        if (zoomResetBtn) {
            zoomResetBtn.addEventListener("click", function() {
                zoomLevel = 1.0;
                panOffset = 0;
                renderDetailChart();
            });
        }
    }
})();