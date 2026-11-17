const C = {
  accent: '#2dd4bf', green: '#34d399', red: '#f87171',
  amber: '#fbbf24', muted: '#8b98a5', border: '#1f2a33'
};

let chart = null;
let summaryData = [];

function cpkClass(cpk) {
  if (cpk === null) return '';
  if (cpk >= 1.33) return 'good';
  if (cpk >= 1.0) return 'mid';
  return 'bad';
}

async function loadSummary() {
  const res = await fetch('/api/summary');
  const data = await res.json();
  summaryData = data.summary;
  renderKpis();
  renderCards();
  buildSelectors();
}

function renderKpis() {
  const products = new Set(summaryData.map(s => s.product));
  const params = summaryData.length;
  const results = summaryData.reduce((n, s) => n + s.stats.count, 0);
  const oos = summaryData.filter(s => s.status === 'OOS').length;
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="num">${products.size}</div><div class="label">Products</div></div>
    <div class="kpi"><div class="num">${params}</div><div class="label">Parameters tracked</div></div>
    <div class="kpi"><div class="num">${results}</div><div class="label">Batch results</div></div>
    <div class="kpi danger"><div class="num">${oos}</div><div class="label">Parameters OOS</div></div>`;
}

function renderCards() {
  document.getElementById('cards').innerHTML = summaryData.map(s => {
    const st = s.stats;
    const oosHtml = s.oos_batches.length
      ? `<div class="oos-list"><span class="oos-label">OOS batches</span>${s.oos_batches.map(b => `<span class="tag">${b}</span>`).join('')}</div>`
      : '';
    return `
    <div class="pcard ${s.status === 'OOS' ? 'oos' : ''}">
      <div class="pcard-head">
        <span class="pcard-param">${s.parameter}</span>
        <span class="badge ${s.status === 'OOS' ? 'oos' : 'pass'}">${s.status}</span>
      </div>
      <div class="pcard-product">${s.product}</div>
      <div class="stat-row">
        <div class="stat"><div class="v cpk ${cpkClass(st.cpk)}">${st.cpk ?? 'n/a'}</div><div class="k">Cpk</div></div>
        <div class="stat"><div class="v">${st.mean}</div><div class="k">Mean</div></div>
        <div class="stat"><div class="v">${st.std}</div><div class="k">Std dev</div></div>
        <div class="stat"><div class="v">${st.min} - ${st.max}</div><div class="k">Range</div></div>
        <div class="stat"><div class="v">${st.count}</div><div class="k">Batches</div></div>
      </div>
      ${oosHtml}
    </div>`;
  }).join('');
}

function buildSelectors() {
  const products = [...new Set(summaryData.map(s => s.product))];
  const pSel = document.getElementById('product-select');
  pSel.innerHTML = products.map(p => `<option>${p}</option>`).join('');
  pSel.onchange = () => { buildParamSelect(); loadTrend(); };
  document.getElementById('param-select').onchange = loadTrend;
  buildParamSelect();
  loadTrend();
}

function buildParamSelect() {
  const product = document.getElementById('product-select').value;
  const params = summaryData.filter(s => s.product === product).map(s => s.parameter);
  document.getElementById('param-select').innerHTML = params.map(p => `<option>${p}</option>`).join('');
}

async function loadTrend() {
  const product = document.getElementById('product-select').value;
  const parameter = document.getElementById('param-select').value;
  if (!product || !parameter) return;
  const res = await fetch(`/api/trend?product=${encodeURIComponent(product)}&parameter=${encodeURIComponent(parameter)}`);
  const d = await res.json();

  document.getElementById('spec-badge').innerHTML = d.spec_changed
    ? '<span class="badge warn">Spec changed during period</span>' : '';

  const labels = d.points.map(p => p.batch_no);
  const values = d.points.map(p => p.result);
  const pointColors = d.points.map(p => p.status === 'OOS' ? C.red : C.accent);
  const pointSizes = d.points.map(p => p.status === 'OOS' ? 6 : 3);

  const datasets = [{
    label: d.parameter,
    data: values,
    borderColor: C.accent,
    backgroundColor: 'rgba(45,212,191,.08)',
    fill: true,
    tension: 0.25,
    pointBackgroundColor: pointColors,
    pointBorderColor: pointColors,
    pointRadius: pointSizes,
  }];
  if (d.lsl !== null) datasets.push({
    label: `LSL (${d.lsl})`, data: labels.map(() => d.lsl),
    borderColor: C.red, borderDash: [6, 6], pointRadius: 0, fill: false,
  });
  if (d.usl !== null) datasets.push({
    label: `USL (${d.usl})`, data: labels.map(() => d.usl),
    borderColor: C.red, borderDash: [6, 6], pointRadius: 0, fill: false,
  });

  if (chart) chart.destroy();
  chart = new Chart(document.getElementById('trend-chart'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: C.muted } },
        tooltip: {
          callbacks: {
            title: (items) => {
              const p = d.points[items[0].dataIndex];
              return `${p.batch_no} - ${p.mfg_date} (${p.status})`;
            }
          }
        }
      },
      scales: {
        x: { ticks: { color: C.muted, maxTicksLimit: 10 }, grid: { color: 'rgba(31,42,51,.5)' } },
        y: { ticks: { color: C.muted }, grid: { color: 'rgba(31,42,51,.5)' },
             title: { display: true, text: d.unit, color: C.muted } }
      }
    }
  });
}

loadSummary();
