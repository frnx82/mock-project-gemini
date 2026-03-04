
        let refreshInterval;

        let currentFilter = null; // { target: 'Pod', criteria: { status: 'Failed'}}
        let currentLogPodName = null; // Track which pod's logs are open for correlation// ── Session ID (persisted per browser tab) ──let chatSessionId = localStorage.getItem('gdc-chat-session');if (!chatSessionId) {chatSessionId   = 'sess-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);localStorage.setItem('gdc-chat-session', chatSessionId
        );
        }
        document.getElementById('chat-session-label' ) .innerText = 'Session: ' + chatSessionId.slice(-6);

        function switchMainTab(tab, skipSave) {
            const workloadsBtn = document.getElementById('main-tab-workloads');
            const networkingBtn = document.getElementById('main-tab-networking');
            const optimizerBtn = document.getElementById('main-tab-optimizer');
            const securityBtn = document.getElementById('main-tab-security');
            const yamlGenBtn = document.getElementById('main-tab-yaml-gen');

            const workloadsView = document.getElementById('view-workloads');
            const networkingView = document.getElementById('view-networking');
            const optimizerView = document.getElementById('view-optimizer');
            const securityView = document.getElementById('view-security');
            const yamlGenView = document.getElementById('view-yaml-gen');

            // Reset all
            [workloadsBtn, networkingBtn, optimizerBtn, securityBtn, yamlGenBtn].forEach(b => {
                  b.className = 'btn btn-default';
                if (b.id === 'main-tab-yaml-gen') { b.style.background =  ' ';  b
            .style.color = ''; }
            });
            [workloadsView, networkingView, optimizerView, securityView, yamlGenView].forEach(v => v.style.display = 'none');

            // Activate selected
            if (tab === 'workloads') {
                  workloadsBtn.className = 'btn btn-primary';
                 
             workloadsView.style.display = 'block';
            } else if (tab === 'networking') {
                networkingBtn.className = 'btn btn-primary';
            
                networkingView.style.display = 'block';
            } else if (tab === 'optimizer') {
                optimizerBtn.className = 'btn btn-primary';
                
            optimizerView.style.display = 'block';
                renderOptimizer ( );
            } else if (tab === 'security') {
                  securityBtn.className = 'btn btn-primary';
                securityView.style.display = 'block';
                  renderSecurity();
            } else if (tab === 'yaml-gen' )  {
                yamlGenBtn.className = 'btn btn-primary';
                yamlGenBtn.style.background = 'linear-gradient(135deg,#6f42c1,#5a32a3)';
                yamlGenBtn.style.color = 'white';
                yamlGenView.style.display = 'block';
            }

 
                   // Persist so refresh restores the same tab
            if (!skipSave) localStorage.setItem('gdc-main-tab', tab);
        }

        // All optimizer recommendations stored globally for filter pills
        let _optAllRecs = [];
        

        function _optSeverityColor(sev) {
            return sev === 'high' ? '#dc3545' : sev === 'medium' ? '#fd7e14' : '#28a745';
        }

         function _optTypeColor(type) {
            if (type.includes('Cost Saving')) return { bg: '#f0fff4', border:  '#86efac', accent: '#1a8032' };
            if (type.includes('Performance Risk')) return { bg: '#fff8f0', border: '#fda07a', accent: '#c05000' };
            if (type.includes('Stability  Risk')) return { bg: '#fff5f5', border: '#fca5a5', accent: '#dc3545' };
            return { bg: '#f0f8ff', border: '#93c5fd', accent:  ' #1a56db' };
        }

        function renderOptCards(recs) {
            const  c ards = document.getElementById('opt-cards');
            cards.innerHTML = '';
            if (!recs || recs.length === 0) {
                cards.innerHTML = '<div style="text-align:center;padding:30px;color:#28a745;font-size:15px;font-weight:600;">✅ All workloads are right-sized for this filter.</div>';
                return;
            }
            recs.forEach(rec => {
                const c = _optTypeColor(rec.type || '');
                const sav = (rec.monthly_saving || 0);
                const savColor = sav > 0 ? '#1a8032' : sav < 0 ? '#dc3545' : '#888';
                const savPrefix = sav > 0 ? '💚 Save €' : sav < 0 ? '⚠️ +€' : '—';
                const savText = sav !== 0 ? `${savPrefix}${Math.abs(sav).toFixed(2)}/mo` : '— No change';
                // Billing basis chip
                const basisChip = (rec.billing_basis === 'usage')
                    ? '<span style="background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:20px;padding:2px 8px;font-size:11px;font-weight:600;">🔴 Billed on USAGE</span>'
                    : '<span style="background:#e2e3e5;color:#495057;border:1px solid #ced4da;border-radius:20px;padding:2px 8px;font-size:11px;font-weight:600;">📋 Billed on Requests</span>'
                    ;
                const card = document.createElement('div');
                card.className = 'opt-card';
                card.dataset.type = rec.type || '';
                card.style.cssText = `background:${c.bg};border:1px solid ${c.border};border-left:4px solid ${c.accent};border-radius:10px;padding:14px 16px;`;
                card.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;">
            <div style="flex:1;min-width:200px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
                    <span style="font-size:15px;font-weight:700;color:${c.accent};">${rec.type || '—'}</span>
                    <span
                        style="background:${_optSeverityColor(rec.severity || 'low')};color:#fff;border-radius:20px;padding:1px 8px;font-size:11px;font-weight:600;">${(rec.severity
                        || 'low').toUpperCase()}</span>
                    ${basisChip}
                </div>
                <div style="font-size:16px;font-weight:700;color:#1a1a2e;margin-bottom:2px;">${rec.resource || '—'}
                    <span style="font-size:12px;color:#888;font-weight:400;">${rec.kind || ''} · ${rec.replicas || 0}
                        replica${rec.replicas === 1 ? '' : 's'}</span></div>
                <div style="font-size:13px;color:#444;margin-bottom:8px;line-height:1.5;">${rec.reason || ''}</div>
            </div>
            <div style="text-align:right;min-width:130px;">
                <div style="font-size:11px;color:#888;margin-bottom:2px;">Current cost</div>
                <div style="font-size:20px;font-weight:800;color:#dc3545;">€${(rec.current_monthly_cost ||
                        0).toFixed(2)}<span style="font-size:11px;font-weight:400;color:#888;">/mo</span></div>
                <div style="font-size:13px;font-weight:700;color:${savColor};margin-top:2px;">${savText}</div>
            </div>
            </div>

            <!-- Usage & Capacity Row -->
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
                <div
                    style="flex:1;min-width:130px;background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;">
                    <div style="font-size:11px;color:#888;margin-bottom:2px;">📊 Actual CPU Usage</div>
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;">${rec.actual_usage_cpu || 'unknown'}
                    </div>
                </div>
                <div
                    style="flex:1;min-width:130px;background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;">
                    <div style="font-size:11px;color:#888;margin-bottom:2px;">💾 Actual Mem Usage</div>
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;">${rec.actual_usage_mem || 'unknown'}
                    </div>
                </div>
                <div
                    style="flex:1;min-width:130px;background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;">
                    <div style="font-size:11px;color:#888;margin-bottom:2px;">🔋 Capacity Headroom</div>
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;">${rec.capacity_headroom_pct || 'N/A'}
                    </div>
                </div>
                <div
                    style="flex:1;min-width:130px;background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;">
                    <div style="font-size:11px;color:#888;margin-bottom:2px;">💳 Billable Cores</div>
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;">${rec.billable_cores != null ?
                        rec.billable_cores + ' cores' : '—'}</div>
                </div>
            </div>

            <!-- Resource specs row -->
            <div style="display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:#555;margin-bottom:10px;">
                <span style="background:rgba(255,255,255,0.6);padding:3px 8px;border-radius:4px;">CPU req:
                    <strong>${rec.current_cpu_request || '—'}</strong>&nbsp;→&nbsp;<strong
                        style="color:${c.accent};">${rec.suggested_cpu_request || '—'}</strong></span>
                <span style="background:rgba(255,255,255,0.6);padding:3px 8px;border-radius:4px;">CPU lim:
                    <strong>${rec.current_cpu_limit || '—'}</strong>&nbsp;→&nbsp;<strong
                        style="color:${c.accent};">${rec.suggested_cpu_limit || '—'}</strong></span>
                <span style="background:rgba(255,255,255,0.6);padding:3px 8px;border-radius:4px;">Mem req:
                    <strong>${rec.current_mem_request || '—'}</strong>&nbsp;→&nbsp;<strong
                        style="color:${c.accent};">${rec.suggested_mem_request || '—'}</strong></span>
                <span style="background:rgba(255,255,255,0.6);padding:3px 8px;border-radius:4px;">Mem lim:
                    <strong>${rec.current_mem_limit || '—'}</strong>&nbsp;→&nbsp;<strong
                        style="color:${c.accent};">${rec.suggested_mem_limit || '—'}</strong></span>
            </div>

            <!-- Action + AI Insight -->
            <div style="background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;margin-bottom:6px;">
                <div style="font-size:12px;color:#666;margin-bottom:2px;">🛠 RecommendedAction</div>
                <div style="font-size:13px;font-weight:600;color:${c.accent};font-family:monospace;">${rec.action || ''}
                </div>
            </div>
            ${rec.ai_insight ? `<div s
            tyl
        e="font-size:12px;color:#666;font-style:italic;margin-top:4px;">🧠
                ${rec.ai_insight}</div>` : ''}
            `;
                cards.appendChild(card);
            });
          }

        function filterOptType(type) {
              
            // Update pill styles
            document.querySelectorAll('[id^="opt-filter-"]').forEach(b => {
                b.style.background = '#f0f0f0'; b.style.color = '#333'; b.style.fontWeight = 'normal';
            });
            const activeId = type === 'all' ? 'opt-filter-all'
                : type === 'Cost Saving' ? 'opt-filter-saving'
                    : type === 'Performance Risk' ? 'opt-filter-perf'
                        : type === 'Stability R i sk' ? 'opt-filter-stability'
                              : 'opt-filter-ok';
              co
            nst activeBtn = document.getElementById(activeId);
            if (activeBtn) {
                activeBtn.style.background = '#28a745'; activeBtn.style.colo
        r = '#fff';
                activeBtn.style.fontWeight = '600';
            }

            const filtered = type === 'all' ? _optAllRecs : _optAllRecs.filter(r => (r.type || '').includes(type));
            renderOptCards(filtered);
        }

        function renderOptimizer() {
            const loading = document.getElementById('opt-loading');
            const banner = document.getElementById('opt-summary-banner');
            const filterBar = document.getElementById('opt-filter-bar');
            const cards = document.getElementById('opt-cards');
              const ns = document.getElementById('namespace-select').value;
            const header = document.querySelector('#view-optimizer .panel-header div:last-child');

            loading.style.display = 'block';
            banner.style.display = 'none';
            fil terBar.style.display = 'none';
         
                   cards.innerHTML = '';

            fetch(`/api/ai/optimize?namespace=${ns } `)
                .then(r => {
                    if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText); }); return
                    r.json();
                })
                .then(data => {
                    loading.style.display = 'none';
                    if (data.error) throw new Error(data.error);

                    _optAllRecs = data.recommendations || [];
                    const saving = data.total_monthly_saving || 0;
                    document.getElementById('opt-saving').textContent =  ' €' + Math.abs(saving).toFixed(2);
                    const pct = data.total_current_monthly_cost > 0
                        ? ((saving / data.total_current_monthly_cost) * 100).toFixed(0) : 0;
                    document.getElementById('opt-saving-pct').textContent = saving >= 0
                        ? `${pct}% reduction` : `${Math.abs(pct)}% increase (under-provisioned)`;
                    document.getElementById('opt-saving').style.color = saving >= 0 ? '#1a8032' : '#dc3545';

                    // ── Data SourceBadge ────────────────────────────
                    const src = data.metrics_source || 'gemini-estimation';
                    const srcBadge = src === 'metrics-server'
                        ? '<span style="background:#d1fae5;color:#065f46;border:1px solid #6ee7b7;border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;">📊 Metrics Server</span>'
                        : '<span style="background:#dbeafe;color:#1e40af;border:1px  s olid #93c5fd;border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;">🧠 Gemini Estimation</span>';
                    document.querySelector('#view-optimi zer .panel-header') && (() => {
                          let badge = document.getElementById('opt-src-badge');
                        if (!badge) {
                            badge = document.createElement('span');
                             badge.id = 'opt-src-badge';
                            const hdr = document.querySelector('#view-optimizer .panel-header div:first-child div:last-child');
                            if (hdr) hdr.insertAdjacentElement('afterend', badge);
                        }
                        badge.innerHTML = srcBadge;
                    })();

                    banner.style.display = 'block';
                    filterBar.style.display = 'flex';

                    // Reset active filter pill to 'All'
           
                                 document.querySelectorAll('[id^="opt-filter-
                    "]').forEach(b => {
                        b.style.background = '#f0f0f0'; b.style.color = '#333';  b .style.fontWeight = 'normal';
                    });
                    const allPill = document.getElementById('opt-filter-all');
                    if (allPill) {
                         a llPill.style.background  =  '#28a745'; allPill.style. c olor = '#fff'; allPill.style.fontWeight = '600';
                    }

                    renderOptCards(_optAllRecs);
                })
                .catch(e => {
                      loading.style.display = 'none';
                      card
                    s.innerHTML = `<div style="color:#dc3545;padding:20
                px;">⚠️ Error: ${e.message}</div>`;
                });
        }

          // All risks stored globally for category filtering
        let _secAllRisks = [];

        function renderSecurity() 
                {
 
                   const loading = document.getElementById('sec-loading');
            const cards = document.getElementById('sec-cards');
            const banner = document.getElementById('sec-summary-banner');
            const counters = document.getElementById('sec-counters');
            const filterBar = document.getElementById('sec-filter-bar');
            const ns = document.getElementById('namespace-select').value;

            loading.style.display = 'block';
            banner.style.display = 'none';
            counters.style.display = 'none';
            filterBar.style.display = 'none';
            cards.innerHTML  =  '';

            fetch(`/api/ai/security_ s can?namespace=${ns}`)
                .then ( r => {
                    if (!r.o k ) return r.json().then(e => { throw new Error(e.error || r.statusText) });
                    return r.json();
                })
                .then(data => {
                    loading.s tyle.display = 'none';
                 
                   if (data.error) throw new Error(data.error);

                    _secAll R isks = data.risks || [];

                    // ── Executive Summary ───────────────────────────
                    if (data.executive_summary) {
                        document.getElementById('sec-summary-text').textContent = data.executive_summary;
                        banner.style.display = 'block';
                    }

                    // ── Severity Counters ─────────────────────── ─ ───
    
                                    const sc = data.severity_counts || {};
                    document.getElementById('cnt-critical').textContent = sc.Critical || 0;
                    document.getElementById('cnt-high').textContent = sc.High || 0;
                    document.getElementById('cnt-medium').textContent = sc.Medium || 0;
                    document.getElementById('cnt-low').textContent = sc.Low || 0;
                    document.getElementById('cnt-info').textContent = sc.Info || 0;
                    counters.style.display = 'flex';
                    filterBar.style.display = 'flex';

                      // Reset active filter pill
                      document.querySelectorAll('[id^="sec-filter-"]').forEach(b => {
                        b.style.background = '#f0f0f0'; b.style.color = '#333'; b.style.fontWeight = 'normal';
                      });
                      const allBtn =   document.
                    getElementById('sec-filter-all');
                    allBtn.style.background = '#6f42c1'; allBtn.style.color = '#fff'; allBt n .style.fontWeight = '600';

                      renderSecCard s (_secAllRisks);
                })
                .catch
                (e => {
                    loading.style.display = 'none';
                      cards.innerHTML = `<div style="color:red;padding:20px;">⚠️ Error: ${e.message}</div>`;
                });
  
                   
           }

        function renderSecCards(risks) {
            const cards = document.getElementById('sec-cards');
            cards.innerHTML = '';

            if (!risks || risks.length === 0) {
                cards.innerHTML = `<div
                style="text-align:center;padding:30px;color:#28a745;font-size:16px;font-weight:600;">
                ✅ No security issues found in this category.
            </div>`;
                re
            turn;
            }

            const sevConfig = {
                'Critical': { color: '#dc3545', bg: '#fff5f5', border: '#fca5a5', icon: '🔴' },
                'High': { color: '#fd7e14', bg: '#fff8f0', border: '#fda07a', icon: '🟠' },
                'Medium': { color: '#c68800', bg: '#fffdf0', border: ' #ffd970', icon: '🟡' },
                'Low': { color: '#28a745', bg: '#f0fff4', border:  '#86efac', icon: '🟢' },
                'Info': { color: '#3b82f6', bg: '#f0f8ff', border:  '#93c5fd', icon: '🔵' },
            };

            risks.forEach((risk, idx) => {
                const cfg = sevConfig[risk.severity] || sevConfig['Info'];
                const refs = (risk.cve_references || []).map(r =>
                    `<span
                style="background:#eef;color:#5a32a3;font-size:10px;padding:1px 6px;border-radius:10px;font-family:monospace;">${r}</span>`
                ).join(' ');

                const card = document.createElement('div');
                card.dataset.category = risk.category || 'Other';
                card.style.cssText = `background:${cfg.bg};border:1px solid ${cfg.border};border-left:4px solid
            ${cfg.color};border-radius:8px;padding:14px 16px;transition:box-shadow 0.2s;`;

                card.innerHTML = `
            <div style="display:flex;align-items:flex-start;gap:12px;">
                <span style="font-size:18px;flex-shrink:0;margin-top:1px;">${cfg.icon}</span>
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                        <span
                            style="background:${cfg.color};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;text-transform:uppercase;">${risk.severity}</span>
                        <span
                            style="background:#eee;color:#555;font-size:10px;padding:2px 8px;border-radius:10px;">${risk.category
                    || 'General'}</span>
                        <span style="font-size:11px;color:#888;">
                            <b>${risk.resource || ''}</b> · <i>${risk.kind || ''}</i>
                        </span>
                        <span style="margin-left:auto;">${refs}</span>
                    </div>
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;margin-bottom:6px;">${risk.issue || ''}
                    </div>
                    <div
                        style="display:flex;align-items:flex-start;gap:6px;background:rgba(255,255,255,0.7);border-radius:6px;padding:8px 10px;font-size:12px;color:#444;">
                        <span style="flex-shrink:0;">🔧</span>
                        <span style="font-family:monospace;word-break:break-word;">${risk.remediation || ''}</span>
                        <button
                            onclick="navigator.clipboard.writeText(this.dataset.text).then(()=>showToast('Copied!',true))"
                            data-text="${(risk.remediation || '').replace(/" /g, '&quot;')}" title="Copy remediation"
                            style="margin-left:auto;flex-shrink:0;background:none;border:1px solid #ccc;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:10px;color:#666;">📋</button>
                    </div>
                    ${risk.ai_insight ? `
                    <div
                        style="display:flex;align-items:flex-start;gap:6px;margin-top:6px;font-size:12px;color:#6f42c1;font-style:italic;">
                        <span>✨</span><span>${risk.ai_insight}</span>
                    </div>` : ''}
                </div>
            </div>`;
    
               
                 cards.appendChild(card);
            });
        }

        function filterSecCategory(cat) {
            // Updateactive pill styling
            document.querySelectorAll('[id^="sec-filter-"]').forEach(b => {
                  b.style.background = '#f0f0f0'; b.style.color = '#333'; b.style.fontWeight = 'normal';
            });
             e vent.target.style.background = '#6f42c1';
              event.target.style.color = '#fff';
            event.target.style.fontWeight = '600';

            const filtered = cat === 'all' ? _secAllRisks : 
        _secAllRisks.filter(r => r.category === cat);
            renderSecCards(filtered);
        }



        async function fetchData() {
            const currentNamespace = document.getElementById('namespace-select').value;
            const timestampEl = document.getElementById('last-updated');

            // Only show "Updating..." if it's been a while or on first load to avoid flickering
            // timestampEl.innerText = `Updating...`;

            try {
                const [workloadsRes, servicesRes, vsRes] = await Promise.all([
                    fetch(`/api/workloads?namespace=${currentNamespace}`),
                    fetch(`/api/services?namespace=${currentNamespace}`),
                    fetch(`/api/virtualservices?namespace=${currentNamespace}`)
                ]);

                if (!workloadsRes.ok) throw new Error(`Workloads API: ${workloadsRes.statusText}`);
                if (!servicesRes.ok) throw new Error(`Services API: ${servicesRes.statusText}`);
                if (!vsRes.ok) throw new Error(`VirtualServices API: ${vsRes.statusText}`);

                const workloads = await workloadsRes.json();
                const services = await servicesRes.json();
                const virtualServices = await vsRes.json();

                if (workloads.error) throw new Error(workloads.error);
                if (services.error) throw new Error(services.error);

                renderWorkloads(workloads);
                renderNetworking(services, virtualServices);
                updatePodStats(workloads);

                timestampEl.innerText =   `Last u
            pdated: ${new Date().toLocaleTimeString()}`;
                timestampEl.style.color = "#888";
            } catch (error) {
                console.error("Fetch error", error);
                  t
            i
        mestampEl.innerText = `⚠️ UpdateFailed: ${error.message}`;
                timestampEl.style.color = "red";
            }
        }

        async function handleAIQuery() {
            const input = document.getElementById('ai-query-input');
            const query = input.value.trim();
            if (!query) return;

            const ns = document.getElementById('namespace-select').value;

            // Show spinner feedback in thebar
            input.disabled = true;
            const toast = document.getElementById('ai-message-toast');
            toast.innerHTML = `<div style="display:flex;align-items:center;gap:8px;">
                <div
                    style="width:14px;height:14px;border:2px solid #ccc;border-top:2px solid #6f42c1;border-radius:50%;animation:spin 0.7s l i near infinite;">
                </div><span>✨ Gemini is processing...</span>
            </div>`;
            toast.style.display = 'block';

            try {
                 fetch('/api/ai/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
      
                               // Send namespace so Gemini gets live cluster context
                    body: JSON.stringify({ query, namespace: ns })
                })
                    .then(r => r.json())
                    .then(asyncdata => {
                        input.disabled = false;

                        // Handle interac tions
                        if (data.action === 'filter') {
                            currentFilter = { target: data.target, criteria: data.criteria };
                            if (['Pod', 'Deployment', 'Job', 'StatefulSet', 'DaemonSet'].includes(data.target)) {
                                switchMainTab('workloads');
   
                                                         // Wait a tick for main tab valid
                                setTimeout(() => switchTab('workloads', data.target), 50);
                            }
                            if (['Service', 'VirtualService'].includes(data.target)) {
                                switchMainTab('networking');
                  
                                      setTimeout(() => switchTab('networking', data.target), 50);
                            }

                            fetchData();
                            showToast("✨ " + data.message, true);
                        } else if (data.action === 'scale') {
                            const resource = await findResourceByName(data.target, ['Deployment', 'StatefulSet']);
                             if (resource) {
                                await fetch('/api/scale', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    bo
                                    dy
                                : JSON.stringify({
                                        name: resource.name, type: resource.type, action: 'set', count: data.count,
                                        namespace: document.getElementById('namespace-select').value
                                    })
               
                             
                                        });
                                showToast("🚀 " + data.message, true);
                                burstRefresh(10); // poll 10× at 1s so replica count updates immediately} else {
                                showToast(`Could not find resource matching "${data.target}"`, false);
                            
                            }
                        } else if (data.action === 'logs') {
              
                             
                                     const resource = await findResourceByName(data.target, ['Pod']);
                            if (resource) {
                                openLogsModal(resource.name);
                                showToast("🚀 " + data.message, true);
                            } else {
                                showToast(`Could not find
                             pod matching "${data.target}"`, false);
                            }
                        } else if (data.
                            a
                        ction === 'delete') {
                            const resource = await findResourceByName(data.target, ['Pod', 'Deployment', 'Service']);
                            if (resource) {
                                deleteResource(resource.name, resource.type);
                                showToast("🚀 " + data.message, true);
               
                                     } else {
                                showToast(`Could not find resource matching "${data.target}"`, false);
                            }
                        } else if (data.action === 'describe') {
                            const resource = await findResourceByName(data.target, ['Deployment', 'Pod', 'Service']);
                            if (resource) open
                        EnvModal(resource.name, resource.type);
                            else showToast(`Could not find resource matching "${data.target}"`, false);
                        } else if (data.action === 'analyze') {
                       
                             const resource = await findResourceByName(data.target, ['Pod', 'Deployment', 'StatefulSet', 'DaemonSet']);
                            if (resource) analyzeResource(resource.name, resource.type, resource.status);
                            else showToast(`Could not find resource matching "${data.target}"`, false);
                        } else if (data.action === 'reset') {
                            currentFilter = null;
                            input.value = '';
                                                                 sh                                                 } else if (data.action === 'chat') {
                            // Show Gemini's reply — use 'reply' field if provided, fall back to   'message'const replyText = data.reply || data.message || '';let html = replyText.replace(/\*\ * (.*?)\* \*/g, '<b>$1</b>').replace(/`(.*?)`/g, '<code style="background:#444;color:#fff;padding:2px 4px;border-radius:3px;">$1</code>')
                                .replace(/\n- /g, '<br>• ')
                                .replace(/\n/g, '<br>');
                            toast.innerHT ML = `🤖 <b>Gemini:</b><br>${html}`;
                            toast.style.display = 'block';
                            // Auto-hide only short toasts; long replies stay visible
                            if (html.length < 120) setTimeout(() => { toast.style.display = 'none'; }, 8000);
                        } else if (data.acti
                                    on
                                 === 'restart') {
                            if (confirm(`AI Action: Restart ${data.target}?`)) {
                                fetch('/api/restart', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' 
                                    },

                             
                                                           body: JSON.stringify({
                                        name: data.target,
                                        type: 'Deployment', // Defaulting to deployment for now, couldbe improved
                                        namespace: document.getElementById('namespace-select').value
                                    })
                                })
                                    .then(r => r.json())
                                    .then(res => 
                        {
                                        if (res.error) showToast("Error: " + res.error, false);
                                        else showToast("🚀 " + res.message, true);
                                    });
                            }
                        } else if (data.action === 'events') {
                            // "show events for x" -> find resource first to get real name if needed, or trust AI
                            // For now, t
                        rusting AI target extraction or finding via findResourceByName
                      
                              const resource = await findResourceByName(data.target, []);
      
                                            if (resource) openEventsModal(resource.name);
                            else showToast(`Could not find resource "${data.target
                    }"`
            , false);
                        } else if (data.action === 'yaml') {
                            const resource = aw
            a
        it findResourceByName(data.target, []);
                            if (resource) openYamlModal(resource.name, resource.type);
                            else showToast(`Could not find resource "${data.target}"`, false);
                        } else if (data.action === 'navigate') {
                            showToast("🔄 " + data.message, true);
                            switchMainTab(data.target);
                        } else {
                            showToast(`🤖 ${data.message || 'Done'}`, true);
                        }

                        if (data.action !== 'chat') input.value = '';
                    })
                    .catch(e => {
                        input.disabled = false;
                        showToast("AI Error: " + e.message, false);
       
                     });
            } catch (e) {
                input.disabled = false;
                showToast("Request Error: " + e.message, false);
            }
        }

        // Helper to find resource from currently fetcheddata (wouldbebetter to havecentralized store)
        async function findResourceByName(partialName, types) {
            // Quick fetch to search
            c onst currentNamespace = document.getElementById('namespace-select').value;
           
                  const [wRes, sRes] = await Promise.all([
                fetch(`/api/workloads?nam
            espace=${currentNamespace
        e}`),
                fetch(`/api/services?namespace=${currentNamespace}`)
            ]);
            const workloads = await wRes.json();
            const services = await sRes.json();
            const all = [...workloads, ...services];

            return all.find(item => item.name.includes(partialName) && (types.len gth === 0
             
        ||
                types.includes(item.type)));
        }

        async function deleteResource(name, type) {
            if (!confirm(`AI Action: Are you sure you want to DELETE ${type} ${name}?`)) return;
            try {
                const ns = document.getElementById('namespace-select').value;
                await fetch('/api/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, type: type, namespace: ns })
                });
                showToast(`Deleted ${name}`, true);
                fetchData();
            } catch (e) { alert(e); }
        }

        function showToast(msg, autoHide) {
            const toast = document.getElementById('ai-message-toast');
            toast.innerT
        ext = msg; // Basic text, mocked markdown support
            toast.style.display = 'block';
            if (autoHide) {
                setTimeout(() => { toast.style.display = 'none'; }, 4000);
            }
        }

        function updatePodStats(workloads) {
            const pods = workloads.filter(w => w.type === 'Pod');
            const running = pods.filter(p => p.status === 'Running').length;
            const pending  =  pods.filter(p => p.status === 'Pending').length;
            const failed = pods.filter(p => p.status === 'Failed' || p.status === 'CrashLoopBackOff' || p.status ===
                'Error').length;

            const el = document.getElementById('pod-status-summary');
            el.innerHTML = `
                Pod Status:
                <span style="color:green; margin-left: 5px;">Running: ${running}</sp
                an>
                <span style="color:orange; margin-left: 10px;">Pending: ${pending}</span>
                <sp
            an style="color:red; margin-left: 10px;">Failed: ${failed}</span>
                `;
        }

        function renderWorkloads(data) {
            const tabsContainer = document.getElementById('workloads-tabs');
            const contentContainer = document.getElementById('workloads-content');

            // Only render tabs once
            if (tabsContainer.children.length === 0) {
                const types = ['Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'Pod', 'ConfigMap', 'Secret'];
                let tabBtns = '';
                let contentDivs = '';

                types.forEach((type, index) => {
                    const isActive = index === 0 ? 'active' : '';
                    tabBtns += `<button class="tab-btn ${isActive}"
                    onclick="swit
                    chTab('workloads', '${type}')">${type}s</button>`;
                    contentDivs += `<div id="workloads-${type}" cl
                    ass="tab-content ${isActive}"></div>`;
                });

                tabsContainer.innerHTML = tabBtns;
      
                     
                         contentContainer.innerHTML = contentDivs;
            }

            const types = ['Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'Pod', 'ConfigMap', 'Secret'];

            types.forEach(type => {
                let items = data. f ilter(item => item.type === type);

            
                        // Apply AI Filter ifactive
                //  N ote: We also handle sub-tab s
                    witching in handleAIQuery now
                
                if (currentFilter && currentFilter.target === type && currentFilter.criteria.status) {
                    const statusCriteria = currentFilter.criteria.status;
                    if (statusCriteria === 'Failed') {
                        items = items.filter(i => ['Failed', 'Error', 'CrashLoopBackOff', 'OOMKilled', 'ImagePullBackOff',
                            'ErrImagePull', 'CreateContainerConfigError'].includes(i.status));
                    } else if (statusCriteria === 'Running') {
                        items = items.filter(i => i.status === 'Running');
                    } else if (statusCriteria === 'Pending') {
                        item s  = items.filter(i => i.status === 'Pending');
                    }
                  }

                const container = document.getElementById(`workloads-${ t ype}`);

                if (items.length === 0) {
                    if (currentFilter && currentFilter.target === type) {
                        containe r .innerHTML = '<p>No resources found matching AI filter.</p>';
                    } else {
                        container.innerHTML = '<p>No resources found.</p>';
                    }
                    return;
                }

                let html = `<table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Status</th>
                            <th>${type === 'Job' ? 'Completions' : 'Ready' } </th>
                            <th>Age</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>`;
                html += items.map(item => {
                    // Status colour — Jobs use word status now
                    let statusColor = '#888';
                    if (item.status === 'Running' || item.status === 'Active') statusColor = '#28a745';
                    else if (item.status === 'Succeeded') statusColor = '#17a2b8';
                    else if (item.status === 'Failed') statusColor = '#dc3545';
                    else if (item.status === 'Pending') statusColor = '#fd7e14';
                    else if (item.status.includes('/')) statusColor = '#28a745'; // ready/total

                    let row = `<tr>
                            <td><strong>${item.name}</strong></td>`;

                    // Job: rich status with counter badges
                    if (type === 'Job') {
                        const statusBadge = `<span
                                style="background:${statusColor};color:#fff;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;">${item.status}</span>`;
                        let counters = '';
                 
                           if (item.job_active > 0) counters += `<span
                                style="margin-left:4px;background:#fff3cd;color:#664d03;border:1px solid #ffc107;border-radius:3px;
                    padding:1px 5px;font-size:10px;">⚙
                                ${item.job_active} active</span>`;
                          if (item.job_succeeded > 0) counters += `<span
                                style="margin-left:4px;background:#d1fae5;color:#065f46;border:1px solid #6ee7b7;border-radius:3px;padding:1px 5px;font-size:10px;">✓
                                ${item.job_succeeded} ok</span>`;
                        if (item.job_failed > 0) counters += `<span
                                style="margin-left:4px;background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;border-radius:3px;padding:1px 5px;font-size:10px;">✗
                                ${item.job_failed} failed</span>`;
                        row += `<td>${statusBadge}${counters}</td>`;
                        row += `<td><span style="font-size:12px;color:#555;">${item.job_succeeded ??
                            item.ready}/${item.job_completions ?? item.total}</span> <span
                                    style="color:#aaa;font-size:10px;">completions</span></td>`;
                    } else {
                        row += `<td style="color:${statusColor};font-weight:600">${item.status}</td>`;
                        row += `<td>${item.ready}/${item.total}</td>`;
                    }
                    row += `<td>${item.age}</td>`;

                    // Actions
                    let actions = '<div style="display:flex;gap:4px;flex-wrap:wrap;">';
                    if (['Deployment', 'StatefulSet'].includes(type)) {
                        actions += `<button class="btn btn-default" title="Scaledown"
                                    onclick="scaleWorkload('${item.name}', '${item.type}', 'down')"
                                    style="padding:3px 8px;">▼</button>`;
                        actions += `<button class="btn btn-default" title="Scale up"
                                    onclick="scaleWorkload('${item.name}', '${item.type}', 'up')"
                                    style="padding:3px 8px;">▲</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="openDeploymentLogs('${item.name}', '${item.type}')"
                                    style="font-size:11px;">📋 Logs</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="analyzeResource('${item.name}', '${item.type}', '${item.status}')"
                 
                                       style="border-color:#6f42c1;color:#6f42c1;font-size:11px;">🪄 RCA</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="analyzeDeployment('${item.name}', '${item.type}')"
                                    style="border-color:#4285F4;color:#4285F4;font-size:11px;">♊ Analyze</button>`;
                        actions += `<button class="btn btn-default" onclick="openEventsModal('${item.name}')"
                                    style="font-size:11px;">📅 Events</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="openYamlModal('${item.name}','${item.type}')" style="font-size:11px;">📄
                                    YAML</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="restartDeployment('${item.name}','${item.type}')"
                                    style="font-size:11px;">♻️ Restart</button>`;
                        actions += `<button class="btn btn-primary"
                                    onclick="openEnvModal('${item.name}', '${item.type}')" style="font-size:11px;">⚙️
                                    Config</button>`;
                    } else if (type === 'Pod') {
                        const containersJson = encodeURIComponent(JSON.stringify(item.containers || []));
                        actions += `<button class="btn btn-primary"
                                    onclick="openTerminalPrompt('${item.name}', '${containersJson}')"
                                    style="font-size:11px;">💻 Console</button>`;
                        actions += `<button class="btn btn-default" onclick="openLogsModal('${item.name}')"
                                    style="font-size:11px;">📋 Logs</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="analyzeResource('${item.name}', '${item.type}', '${item.status}')"
                                    style="border-color:#6f42c1;color:#6f42c1;font-size:11px;">🪄 RCA</button>`;
                        actions += `<button class="btn btn-default" onclick="analyzePodLogs('${item.name}')"
                                    style
                    ="border-color:#4285F4;color:#4285F4;font-size:11px;">♊ Analyze</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="openEnvModal('${item.name}', '${item.type}')" style="font-size:11px;">⚙️
                                    Config</button>`;
                    } else if (type === 'DaemonSet') {
                        actions += `<button class="btn btn-default"
                                    onclick="analyzeResource('${item.name}', '${item.type}', '${item.status}')"
                                    style="border-color:#6f42c1;color:#6f42c1;font-size:11px;">🪄 RCA</button>`;
                        actions += `<button class="btn btn-default" onclick="openEventsModal('${item.name}')"
                                    style="font-size:11px;">📅 Events</button>`;
                        actions += `<button class="btn btn-default"
                                    onclick="openYamlModal('${item.name}','${item.type}')" style="font-size:11px;">📄
                                    YAML</button>`;
                        actions += `<button class="btn btn-primary"
                                    onclick="openEnvModal('${item.name}', '${item.type}')" style="font-size:11px;"
                    >⚙️
                                    Config</button>`;
                    } else if (type === 'Job') {
                        actions += `<button class="btn btn-default"
                                    onclick="openDep
                    loymentLogs('${item.name}', '${item.type}')"
                                    style="font-size:11px;">📋 Logs</button>`;
                        actions += `<button class="btn btn-default"
                            
                            onclick="analyzeResource('${item.name}', '${item.type}', '${item.status}')"
                                    style="border-color:#6f42c1;color:
                #6f42c1;font-size:11px;">🪄 RCA</button>`;
                        actions += `<button class="btn btn-default"
       
               
                                  onclick="analyzeDeployment('${item.name}', '${item.type}')"
                                    style="border-color:#4285F4;color:#4285F4;font-size:11px;">♊ Analyze</button>`;
                        actions += `<button class="btn btn-default" onclick="openEventsModal('${item.name}')"
                                    style="font-size:11px;">📅 Events</button>`;
                          actions += `<button class="b t n btn-default"
                                    onclick="openYamlModal('${item.name}','${item.type}')" style="font-size:11px;">📄
                                    YAML</button>`;
                    } else if (type === 'ConfigMap') {
                        actions += `<button class="btn btn-default" onclick="openConfigMapModal('${item.name}')"
                         
                           style="font-size:11px;">🗂️ View</button>`;
                    } else if (type === 'Secret') {
      
                              actions += `<button class="btn btn-default" onclick="openSecretModal('${item.name}')"
                                    style="font-size:11px;">🔒 View</button>`;
                    }
                    actions += '</div>';
                    row += `<td>${actions}</td>
                        </tr>`;
                    return row;
                }).join('');

                html += `</tbody>
                </table>`;
                container.innerHTML = html;
            });
        }

        function renderNetworking(services, virtualServices) {
            const tabsContainer = document.getElementById('networking-tabs');
            const contentContainer = document.getElementById('networking-content');

            // Only render tabs once
            if (tabsContainer.children.length === 0) {
                const types = ['Service', 'VirtualService'];
                let tabBtns = '';
                let contentDivs = '';

                types.forEach((type, index) => {
                    const isActi
            ve = index === 0 ? 'active' : '';
                      tabBtns += `<button cl
            ass="tab-btn ${isActive}"
                    onclick="switchTab('networking', '${type}')">${type}s</button>`;
                    contentDivs += `<div id="networking-${type}" class="tab-content ${isActive}"></div>`;
                });

                tabsContainer.innerHTML = tabBtns;
                contentContainer.innerHTML = contentDivs;
            }

            // Services
            const svcContainer = document.getElementById('networking-Service');
            if (services.length > 0) {
                let html = `<table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Type</th>
                            <th>Cluster IP</th>
                            <th>Ports</th>
                            <th>Age</th>
                        </tr>
                    </thead>
                    <tbody>`;
                html += services.map(s => `
                        <tr>
                            <td>${s.name}</td>
                            <td>${s.type}</td>
                            <td>${s.cluster_ip}</td>
                            <td>${s.ports}</td>
             
                                   <td>${s.age}</td>
                        </tr>
                        `).join('');
                html += `
                    </tbody>
                </table>`;
                svcContainer.innerHTML = html;
            } else {
                svcContainer.innerHTML = '<p>No Services found.</p>';
            }

            // VirtualServices
            const vsContainer = document.getElementById('networking-VirtualService');
            if
             (virtualServices.length > 0) {
                  let html = `<table>
              
             
             <thead>
                        <tr>
                            <th>Name</th>
                            <th>Hosts</th>
                            <th>Gateways</th>
                            <th>Age</th>
                        </tr>
                    </thead>
                    <tbody>`;
                html += virtualServices.map(vs => {
                    // Ensure 
            hosts is an array and handle comma-separated strings
                    let hosts = Array.isArray(vs.hosts) ? vs.hosts : (vs.hosts.includes(',') ? vs.hosts.split(',') :
                     
               [vs.hosts]);
                    let hostLinks = hosts.map(h => {
                        h = h.trim();
               
                 if (h === '*') return '*'; // Don't link wildcardlet url = h.startsWith ('http') ? h : 'http://' + h;return '<a href="' + url + '" target="_blank" style="color:#4da6ff;text-
        decoration:underline;">' + h + '</a>';
                    }).join(', ');

                    return `
                        <tr>
                            <td>${vs.name}</td>
                            <td>${hostLinks}</td>
                            <td>${vs.gateways}</td>
                            <td>${vs.age}</td>
                        </tr>
                        `}).jo in('');
                html += `
                    </tbody>
                </table>`;
            
                     vsContainer.innerHTML = html;
            } else {
                vsContainer.innerHTML = '<p>No VirtualServices found.</p>';
            }
        }

        function switchTab(panel, type, skipSave) {
            const tabsContainer = document.getElementById(`${panel}-tabs`);
            const contentContainer = document.getElementById(`${panel}-content`);

            // Update buttons

                        Array.from(tabsContainer.children).forEach
        ch(btn => {
                btn.classList.toggle('active', btn.innerText.includes(type));
            });

            // Update content visibility
            Array.from(contentContainer.children).forEach(div => {
                div.classList.toggle('active', div.id === `${panel}-${type}`);
            });

            // Pe            per panel
            if (!skipSave) localStorage.setItem(`gdc-tab-${panel}`, type);
          }

        // Actions
        function closeModal(id) { document.getElementById(id).style.display = 'none'; }
        window.onclick = function (e) {
              if (e.target.classList.contains('modal')) e.target.style.display = 'none' ; 
        }

        async function scaleWorkload(name, type, action) {
              if (!confirm(`Scale ${type} ${name} ${action}?`)) return;
            try {
                const ns = document.getElementById('namespace-select').value;
                const response = await fetch('/api/scale', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                  
          body: JSON.stringify({ name: name, type: type, action: action, namespace: ns })
                });
                  const data = await response.json();
                if (!response.ok) throw new Error(data.error || response.statusText);
                if (data.error) throw new Error(data.error);

                showToast(`✅ Scaled  ${name} — updating status...`, true);
                // Burst-poll for 10s after scale so replica count updates immediately
                burstRefresh(10);
            } catch (e) { alert("Error scaling: " + e.message); }
        }

        // Poll fetchData n times, 1 second apart (usedafter mutations like scale/restart)
        function burstRefresh(times) {
              let count = 0;
            const tick = () => { fetchData(); if (++count  <  times) setTimeout(tick, 1000); };
            tick();
        }

        function openLogsModal(podName) {
            currentLogPodName = podName;
            document.getElementById('logModal').style.display = 'block';
            document.getElementById('modal-title').innerText = `Logs: ${podName}`;
            document.getElementById('log-content').innerText = "Loading...";
            document.getElementById('log-correlate-box').style.display = 'none';
            document.getElementById('log-summary-box').style.display = 'none';
            const ns = document.getElementById('namespace-select').value;
            fetch(`/api/pods/${podName}/logs?namespace=${ns}`).then(r => r.json())
                .then(d => document.getElementById('log-content').innerText = d.logs || d.error)
                .catch(e => document.getElementById('log-content').innerText = e);
        }

        function openEnvModal(name, type) {
            document.getElementById('envModal').style.display = 'block';
            document.
                getElementById('env-title').innerText = `Config: ${name}`;
            document.getElementById('env-loading').style.display = 'block';
            document.getElementById('env-content'). s tyle.display = 'none';

            const ns = document.getElementById('namespace-select').value;
            fetch(`/api/workloads/env?name=${name}&type=${type}&namespace=${ns}`)
                .then(r => r.json()
                )
 
                       .then(data => {
                    if (data.error) throw new Error(data.error);

                    document.getElementById('env-loading').style.display = 'none';
                    document.getElementById('env-content').style.display = 'bloc k ';

                    const tbody = document.querySelector('#env-table tbody');
                    tbody.innerHTML = (data.env || []).map(e => ` < tr>
                        <td>${e.container}</td>
                        < t d>${e.name}</td>
                        <td>${e.value}</td>
                      </tr>`).join('');
                    if (!data.env || data.env.length === 0) tbody.innerHTML = '<tr><td colspan="3" style="text-align: c enter;padding:12px;color:#888;">No environment variables</td></tr>';

                    document.getElementById('cm-list').innerHTML = (data.config_maps || []).map(c => `<button
                        class="btn btn-default" onclick="openConfigMapModal('${c}')">${c}</button>`).join(' ') ||
                        'Non e ';
                    document.getElementById('secret-list').innerHTML = (data.secrets || [] ) .map(s => `<button
                     
                       class="btn btn-default" onclick="openSecretModal('${s}')">🔒 ${s}</button>`).join(' ') ||
                        'None';
                })
                .catch(e => {
                    document.getElementById('env-loading').style.display = 'none';
                    document.getElementById('env-content').style.display = 'block';
                      document.querySelector('#env-table tbody').innerHTML = `<tr>
                        <td colspan="3" style="color:red;">Error fetching data: ${e.message}</td>
                    </tr>`;
                });
        }

        function openConfigMapModal(name) {
            const ns = document.getElementById('namespace-select').value;
            window._cmCurrentName = name; // store for explainConfigMap
            document.getElementById('cmContentModal').style.display = 'block';
            document.getElementById('cm-title').innerText = `🗂️ ${name}`;
            document.getElementById('cm-loading').style.display = 'block';
            document.getElementById('cm-kv-container').style.display = 'none';
            document.getElementById('cm-empty').style.display = 'none';
            document.getElementById('cm-gemini-panel').style.display = 'none';
            document.getElementById('cm-key-count').innerText = '';

            fetch(`/api/configmaps/${name}?namespace=${ns}`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('cm-loading').style.display = 'none';
                    if (data.error) {
                        document.getElementById('cm-empty').innerText = '⚠️ ' + data.error;
                        document.getElementById('cm-empty').style.display = 'block';
                        return;
                    }
                    const entries = Object.entries(data.data || {});
                    document.getElementById('cm-key-count').innerText = `${entries.length} key${entries.length !== 1 ?
                        's' : ''}`;
                    if (entries.length === 0) {
                        document.getElementById('cm-empty').style.display = 'block';
                        return;
                    }
                    const tbody = document.getElementById('cm-kv-body');
                     tbody.innerHTML  = entries.map(([k, v]) => {
                        const valStr = typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);
                        const isLong = valStr.length > 80 || valStr.includes('\n');
                        const safeK = k.replace(/'/g, "\\'");
                        const safeV = valStr.replace(/</g, '&lt;').replace(/>/g, '&gt;');
                        return `<tr style="border-bottom:1px solid #e8f4f8;">
                        <td
                            style="padding:8px 10px;font-family:monospace;font-size:0.85em;color:#17a2b8;vertical-align:top;">
                            ${k}</td>
                        <td style="padding:8px 10px;vertical-align:top;">
                            ${isLong
                                ? `
                            <pre
                                style="margin:0;background:#f8f8f8;border-radius:4px;padding:6px;font-size:0.82em;max-height:120px;overflow:auto;white-space:pre-wrap;"> ${s afeV}</pre>
                                `
                                  : `<code style="bac kground:#f4f4f4;padding:2px 6px;border-radius:3px;font-size:0.85em;">${safeV}</code>`}
                        </td>
                        <td style="padding:8px 10px;text-align:center;vertical-align:top;">
                            <button onclick="navigator.clipboard.writeText(this.dataset.val).then(() => showToast('Copied!', true))"
                                data-val="${safeV}"
                                style="background:none;border:1px solid #ccc;border-radius:4px;cursor:pointer;padding:2px 6px;font-size:11px;"
                                title="Copy value">📋</button>
                        </td>
                    </tr>`;
                    }).join('');
                    document.getElementById('cm-kv-container').style.display = 'block';
                })
                .cat ch(e  => {
                    document.getElementById('cm-loading').style.display = 'none ';
                       d o cu me nt.getElementById('cm-empty').innerText = '⚠️ ' + e;
                    document.getElementById('cm-empty').style.display = 'block';
                });
        }

                    async function explainConfigMap() {
                    const name = window._cmCurrentName;
                    const ns = document.getElementById('namespace-select').value;
                    const panel = document.getElementById('cm-gemini-panel');
                    const content = document.getEl emen tById('cm-gemini-content');
                    panel.style.display='block';
                    content.innerHTML='<span style="color:#999;">♊ Gemini is analysing this ConfigMap...</span>';
                    try {
                    const r = await
                    fetch(`/ api / ai / explain_configmap ? name = ${ encodeURIComponent(name) }& namespace=${  enc odeURIComponent(ns) } `);
                    const d = await r.json();
                    if (d.error) { content.innerText='⚠️ ' + d.error; return;}
                    let html = (d.explanation || 'No explanation returned.')
                    .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
                    .replace(/`(.*?)`/g, '<code style="background:#f0e8ff;padding:2px 5px;border-radius:3px;">$1</code>')
                    .replace(/\n/g, '<br>');
                    content.innerHTML = html;} catch (e) { content.innerText='⚠️ ' + e;}}

                    // Open logs for the first podbelonging to aDeployment/S tate fulSet
                    async function openDeploymentLogs(name, type) {
                    const ns = document.getElementById('namespace-select').value;
                    showToast(`📋 Finding pods for ${ name }...`, false);
                    try {
                    const r = await fetch(`/ api / workloads ? namespace = ${ ns }`);
                     c o nst workloads = await r.json();
                    // Find  a p od who se name starts with thedeployment name prefix
                    const prefix = name.replace(/-deployment$/, '').replace(/-statefulset$/, '');
                    const pod = workloads.find(w => w.type === 'Pod' && w.name.startsWith(prefix));
                    if (pod) {
                    openLogsModal(pod.name);} else {
                    showToast(`⚠️ No running pods  found for ${ name }`, false);}} catch (e) { showToast('Error: ' + e.message, false);}}

                    // Gemini health analysis for adeployment (uses existing RCA modal)
                    async function analyzeDeployment(name, type) {
                    const ns = document.getElementById('namespace-select').value;
                    showToast(`♊ Gemini is analysing ${ name }...`, false);
                    try {
                    const r = await fetch('/api/ai/rca', {
                    method: 'POST',
                    headers: { 'Cont ent- Type': 'application/json'},
                    body: JSON.stringify({ name, type, status: 'Running', namespace: ns})});
                    const d = await r.json();
                    const modal = document.getElementById('logModal');
                    const title = document.getElementById('modal-title');
                    const content = document.getElementById('log-content');
                    title.innerText = `♊ Gemini Analysis: ${ name }`;
                    let html = (d.analysis || d.error || 'No analysis returned.')
                    .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
                    .replace(/`(.*?)`/g, '<code style="background:#f0f0f0;padding:2px 4px;border-radius:3px;">$1</code>')
                    .replace(/\n/g, '<br>');
                    content.innerHTML = `< div style = "padding:16px;font-family:sans-serif;line-height:1.7;" > ${ html }</div >
                `;
                    modal.style.display='block';
                     showToast( '✅ Analysis  comp lete!', true);} catch (e) { showToast('Error: ' + e.message, false);}}

                    // Rolling restart for adeployment/statefulset
                    asyn cf u nction resta rtDe ployment(na m e,  type) {
                     if (!confirm(`Rolling restart ${ type } "${name}" ? `)) return;
                    const ns = document.getElementById('namespace-select').value;
                    try {
                    const r = await fetch('/api/restart', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json'},
                    body: JSON.stringify({ name, type, namespace: ns})});
                    const d = await r.json();
                    if (d.error) { showToast('Error: ' + d.error, false); return;}
                    showToast(` ♻️ Restart triggered for ${ name }`, true);
                    burstRefresh(8);} catch (e) { showToast('Error: ' + e.message, false);}}

                    function openSecretModal(name) {
                    c onst modal = document.getElementById('secretModal');
                    const title = document.getElementById('secret-title');
                    const loading = document.getElementById('secret -loading');
                     const errorDiv = document.getElementById('secret-error');
                    const dataContainer = document.getElementById('secret-data-container');
                    const tbody = document.getElementById('secret-table-body');
                    const currentNamespace = document.getElementById('namespace-select').value;

                    modal.style.display='block';
                    loading.style.display='block';
                    errorDiv.style.display='none';
                    dataContainer.style.display='none';
                    title.innerHTML = `< span >🔒</span > Secret: ${ name } <small
                style="font-size: 12px; color: #777;">(${currentNamespace})</small>`;
                    tbody.innerHTML='';

                    fetch(`/ api / secrets / ${ name }?namespace = ${ currentNamespace } `)
                    .then(r => {
                    if (!r.ok) r                  { throw n e w Error(d.error || 'Fet c h failed');});
                                             .then(data => {
                    if (data.error) throw new Error(data.error);

                    loading.style.display='none';
                    dataContainer.style.display=' bl                    // Re nderDataif (dat a.data) {Object.keys(data.data).forEach(key => {tbody.innerHTML += `
                < tr >
                        <td style="font-weight:bold; color:#0056b3;">${key}</td>
                        <td style="font-family:monospace; backgro und:#f8f8f8;">${data.data[key]}</td>
                    </tr > `;});}})
                    .catch(err => {
                    loading.style.display='none';
                    errorDiv.style.display='block';
                    errorDiv.innerText = `⛔ ${ err.message || 'Access Denied' } `;});}

                    // Current pod/container state for the open terminal
                    let _termPodName = null;
                    let _termContainers   = [];

                    function openTerminalPrompt(podName, containersJson) {
                    const containers = JSON.parse(decodeURIComponent(containersJson));
                    if (containers.length === 0) { alert('No containers found in this pod.'); return;}

                    _termPodName = podName;
                    _termContainers = containers.filter(c => c.type !== 'init'); // skip init containers
                    if (_termContainers.length === 0) _termContainers = containers; //  fallback

                     // Build the container selector pill-tabs
                    const tabs = document.getElementById('terminal-container-tabs');
                    tabs.innerHTML = _termContainers.map((c, i) => `
                < button id = "term-tab-${i}" onclick = "switchTerminalContainer(${i})"
            style = "font-size:11px;padding:3px 10px;border-radius:20px;border:1px solid #3a3a6a;background:${i===0?'#4285F4':'transparent'};color:${i===0?'#fff':'#a0a0c0'};cursor:pointer;transition:all 0.2s;" >
                ${ c.name }${ c.type === 'init' ? ' (init)' : '' }
                    </button > `).join('');

                    // Open the modal and connect to the first container
                    document.getElementById('terminalModal').style.display='block';
                    document.getElementById('terminal-title').innerText = `${ podName } `;
                    openTerminal(podName, _termContainers[0] .nam e, 0);}

                    // Switch container without closing the modal
                    function switchTerminalContainer(index) {
                    if (!_termPodName || !_termContainers[index]) return;

                    // Highlight active tab
                    _termContainers.forEach((_, i) => {
                    const btn = document.getElementById(`term - tab - ${ i } `);
                    if (!btn) return;
                    btn.style.background = i === index ? '#4285F4' : 'transparent';
                    btn.style.color = i === index ? '#fff' : '#a0a0c0';});

                    // Disconnect existing socket
                    if (socket) { socket.disconnect(); socket = null;}

                    // Clear terminal and reconnect
                    if (term) {
                    term.clear();
                    term.write(`\r\n⟳ Switching to container: ${ _termContainers[index].name } \r\n`);}

                    connectTerminalSocket(_termPodName, _termContainers[index].name);}

                    function selectContainer(podName, containerName) {
                    c loseModal( ' containerSelectModal');
                       openTerminal(podName, containerName, 0);}

                    function analyzeResource(name, type, status) {
                    document.getElementById('rcaModal').style.display='block';
                    document.getElementById('rca-loading').style.display='block';
                    document.getElementById('rca-content').style.display='none';

                    const ns = document.getElementById('namespace-select').value;

                    // Update loading message to reflect the Gemini-powered analysis
                    document.querySelector('#rca-loading p').textContent =
                    `✨ Gemini is fetching log s, events   & workload spec for ${ name }...`;

                    fetch('/api/ai/rca', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json'},
                    body: JSON.stringify({ name, type, status, namespace: ns})})
                    .then(r => {
                    if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText)});
                    return r.json();})
                     .then(data => {
                    document.getElementById('rca-loading').style.display='none';
                    const content = document.getElementById('rca-content');
                    if (data.error) throw new Error(data.error);
                    if (!data.analysis) throw new Error('No analysis returned from AI.');
                    content.style.display='block';
                    content.innerHTML = renderMarkdown(data.analysis);})
                    .catch(e => {
                    document.getElementById('rca-loading').style.display='none';
                    const content = document.getElementById('rca-content');
                    content.innerHT ML = `< sp a n style = "color:red;" >❌  Error: $ { e.mes sage }</span > `;
                    content.style.display='block';});}



                    function summarizeLogs() {
                    if (!currentLogPodName) {
                    showToast('Open a pod log first before summarizing.', false);
                    return;}
                    const ns = document.getElementById('namespace-select').value;
                    const summaryBox = document.getElementById('log-summary-box');
                    const summaryContent = document.getElementById('log-summary-content');

                    summaryBox.style.display='block';
                    summaryContent.innerHTML = `
                < div style = "display:flex;align-items:center;gap:10px;color:#6f42c1;" >
                        <div
                            style="width:18px;height:18px;border:3px solid #e0d5f5;border-top:3px solid #6f42c1;border-radius:50%;animation:spin 0.8s linear infinite;flex-shrink:0;">
                        </div>
                        <span>✨ Gemini is fetching logs from <strong>all containers</strong> and analysing...</span>
                    </div > `;

                    fetch('/api/ai/summarize_logs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json'},
                    body: JSON.stringify({ pod_name: currentLogPodName, namespace: ns})})
                    .then(r => {
                    if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText)});
                    return r.json();})
                    .then(data => {
                    if (data.error) throw new Error(data.error);
                    summaryContent.innerHTML = renderMarkdown(data.summary);})
                    .catch(e => {
                    summaryContent.innerHTML = `< sp an style =   "color:red;" >❌ Error: $ { e.messa ge }</s pan > `;});}

                    // ── Feature 1: Multi-Container Log Correlation ──
                    function correlateLogs() {
                    if (!currentLogPodName) return;
                    const ns = document.getElementById('namespace-select').value;

                    // Show in-modal result box
                    const box = document.getElementById('log-correlate-box');
                    const content = document.getElementById('log-correlate-content');
                    box.style.display='block';
                    content.innerHTML='<span style="color:#4285F4;">🔗 Fetching logs from all sibling pods...</span>';

                    // Also open thededicated modal for detailed view
                    document.getElementById('correlateModal').style.display='block';
                    document.getElementById('correlate-loading').style.display='block';
                    document.getElementById('correlate-content').style.display='none';

                    fetch('/api/ai/correlate_logs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json'},
                    body: JSON.stringify({ pod_name: currentLogPodName, namespace: ns})})
                    .then(r => r.json())
                    .then(data => {
                    if (data.error) throw new Error(data.error);
                    const html = renderMarkdown(data.analysis);
                    content.innerHTML = html;
                    document.getElementById('correlate-loading').style.display='none';
                    document.getElementById('correlate-content').style.display='block';
                    document.getElementById('correlate-content').innerHTML = html;})
                    .catch(e => {
                    content.innerHTML = `< span style = "color:red;" > Error: ${ e.message }</span > `;
                    document.getElementById(' c orrelate- load ing').innerText='Error: ' + e.message;});}

                    // ── Feature 2: Chat Drawer ──
                    function toggleChatDrawer() {
                    document.getElementById('chat-drawer').classList.toggle('open');}

                    async function sendChatMessage() {
                    const input = document.getElementById('chat-input');
                    const message = input.value.trim();
                    if (!message) return;

                    appendChatBubble('user', message);
                    input.value='';
                    input.disabled = true;

                    const typingBubble = appendChatBubble('assistant', '<em style="color:#aaa;">Gemini is thinking...</em>');

                    try {
                    const ns = document.getElementById('namespace-select').value;
                    const res = await fetch('/api/ai/converse', {
                    method: 'POST',
                    headers: {
                    'Content-Type': 'application/json',
                    'X-Session-Id': chatSessionId},
                    body: JSON.stringify({ message, namespace: ns})});
                    const data = await res.json();
                    if (data.error) throw new Error(data.error);

                    typingBubble.innerHTML = renderMarkdown(data.reply);
                    } catch (e) {
                    typingBubble.innerHTML = '<span style="color:red;">Error: ' + e.message + '</span>';
                    } finally {
                    input.disabled = false;
                    input.focus();}}

                    function appendChatBubble(role, html) {
                    const messages = document.getElementById('chat-messages');
                    const bubble = document.createElement('div');
                    bubble.className = `chat - bubble ${ role } `;
                    bubble.innerHTML = html;
                    messages.appendChild(bubble);
                    messages.scrollTop = messages.scrollHeight;
                    return bubble;}

                    async function resetChatSession() {
                    try {
                    await fetch('/api/ai/converse/reset', {
                    method: 'POST',
                    headers: { 'X-Session-Id': chatSessionId}});} catch (e) {}
                    // Generate new session ID
                    chatSessionId='sess-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);
                    localStorage.setItem('gdc-chat-session', chatSessionId);
                    document.getElementById('chat-session-label').innerText='Session: ' + chatSessionId.slice(-6);
                    document.getElementById('chat-messages').innerHTML='<div class="chat-bubble assistant">New conversation started. How can I help you?</div>';

                    // ── Feature 3: YAML Generator ──
                    function setYamlPrompt(text) {
                    document.getElementById('yaml-description').value = text;
                    document.getElementById('yaml-description').focus();}

                    async function generateYaml() {
                    const description = document.getElementById('yaml-description').value.trim();
                    if (!description) { alert('Pleasedescribe what you want to generate.'); return;}

                    const loading = document.getElementById('yaml-gen-loading');
                    const output = document.getElementById('yaml-gen-output');
                    const ns = document.getElementById('namespace-select').value;

                    loading.style.display='block';
                    output.style.display='none';

                    try {
                    const res = await fetch('/api/ai/generate_yaml', {
                    m e thod: 'POST',
                    headers: { 'Content-Type': 'application/json'}, 
                    body: JSON.stringify({ description, namespace: ns})});
                    const data = await res.json();
                    if (data.error) throw new Error(data.error);

                    output.textContent = data.yaml;
                    output.style.display='block';} catch (e) {
   
                                     output.textContent='#Error: ' + e.message;
                    output.style.display='block'; }  finally {
                    loading.style.display='none'; } }

                     function copyYaml() {
                    const text = document.getElementById('yaml-gen-output').textContent;
                    if (!text || text.startsWith('# ')) { showToast('No YAML to copy yet.', false); return;}
                    navigator.clipboard.writeText(text)
                    .then(() => showToast('✅ YAML copied to clipboard!', true))
                    .catch(() => { /* fallback */
                    const ta = document.createElement('textarea');
                    ta.value = text; docum ent . body.appendChil d(ta);
                       t a.select(); document.execCommand('copy');
                    document.body.removeChild(ta);
                    showToast('✅ YAML copied!', true);});}

                    // ── Shared Markdown renderer ──
                    function renderMarkdown(text) {
                    if (!text) return '';
                    return text
                    .replace(/## (.*)/g, '<h3 style="margin:12px 0 6px;color:#333;">$1</h3>')
                    .replace(/### (.*)/g, '<h4 style="margin:10px 0 4px;color:#555;">$1</h4>')
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    .replace(/`([^ `]+)` / g, '<code
                        style = "background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:12px;" > $1</code > ')
                    .replace(/^\| (.+) \|$/gm, (m) => { // simple table row s 
                         const ce lls =  m.slice(1, -1).split('|').map(c => `<td
                        style="padding:4px 8px;border:1px solid #ddd;">${c.trim()}</td>`).join('');
                        return `<tr>${cells}</tr>`;
                    })
                    .replace(/(<tr>.*<\ /tr >\n ?) +/gs, t => `<table
                                style = "border-collapse:collapse;margin:8px 0;font-size:13px;" > ${ t }</table > `)
                            .replace(/^- (.*)/gm, '<li style="margin-left:18px;">$1</li>')
                            .replace(/\n/g, '<br>');}


                            function openOptimizer() {
                            document.getElementById('optimizerModal').style.display='block';
                            document.getElementById('opt-content').style.display='none';

                            const currentNamespace = document.getElementById('namespace-select').value;
                            fetch(`/ api / ai / opti mize ? namespace = ${ currentNamespace }`)
                            .then(r => {
                             if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText)});
                            return r.json();})
                            .then(data => {
                            if (data.error) throw new Error(data.error);

                            document.getElementById('opt-loading').style.display='none';
                            document.getElementById('opt-content').style.display='block';
                            const tbody = document.getElementById('opt-table-body');
                            tbody.innerHTML='';

                            data.recommendations.forEach(rec => {
                            const tr = document.createElement('tr');
                            tr.innerHTML = `
                < td style = "font-weight: bold;" > ${ rec.type }</td >
                            <td>${rec.resource}</td>
                            <td>${rec.reason}</td>
                            <td style="color: #28a745; font-weight: 500;">${rec.action}</td>
                            <td>${rec.impact}</td>
                            `;
                            tbody.appendChild(tr);});

                            if (data.recommendations.length === 0) {
                            tbody.innerHTML='<tr><td colspan="5" style="text-align:center;">✅ No optimization opportunities found. Resources  are
                               efficient!</td>
                    </tr>';}}).catch(e => {document.getElementById('opt-loading').style.display='none';document.getElementById('opt-content').style.display='block';document.getElementById('opt-table-body').innerHTML = `< tr >
                <td colspan="5" style="color:red;">Error: ${e.message}</td>
                    </tr > `;});}

                    // Terminal Logic
                    let socket;
                    l et term;
                     let fitAddon;

                    function openTerminal(podName, containerName, tabIndex) {
                    try {
                    const debugEl = document.getElementById('term-debug');
                    if (debugEl) debugEl.innerText='Status: I nitializing.. .';

                    if (typeof Terminal === 'undefined') throw new Error('xterm.js is not loaded');

                    // Dispose previous terminal instance
                    if (term) { try { term.dispose();} catch(e){}}

                    term = new Terminal({
                    cursorBlink: true,
                    theme: { background: '#000', foreground: '#e0e0e0', cursor: '#4285F4'}});

                    if (typeof FitAddon !== 'undefined') {
                    fitAddon = new FitAddon.FitAddon();
                    term.loadAddon(fitAddon);}

                    setTimeout(() => {
                    try {
                     const container = document.getElementById('terminal-container');
                    if (!container) throw new Error('Terminal container div not found'); 
                     term.open(container);
                    term.resize(80, 24);
                    if (fitAddon) { try { fitAddon.fit();} catch(e){}}
                    term.write(`Connecting to ${ podName } / ${ containerName }...\r\n`);
                    connectTerminalSocket(podName, containerName);} catch(innerE) { alert('Error: ' + innerE.message);}}, 200);

                    window.addEventListener('resize', resizeTerminal);} catch(e) {
                    alert('Critical Error opening terminal: ' + e.message);}}

                    function connectTerminalSocket(podName, containerName) {
                    const debugEl = document.getElementById('term-debug');
                    if (de bugE l) { debugEl.innerText = `Status: Connecting → ${containerName}...`; debugEl.style.color='#ffd700';}

                    if (socket) { try { socket.disconnect();} catch(e){}}
                    socket = io();

                    socket.on('connect', () => {
                     i f  (debugEl)  { debugEl.innerText  =  `✅ Connected → ${ containerName }`; debugEl.style.color='#4ade80';}
                    socket.emit('connect_terminal', {
                    namespace: document.getElementById('namespace-select').value,
                    pod: podName,
                    container: containerName});});

                    socket.on('connect_error', (err) => {
                    if (debugEl) { debugEl.innerText='Status: Connection Error: ' + err; debugEl.style.color='#f87171';}
                    if (term) term.write(`\r\nConnection Error: ${ err }\r\n`);});

                    socket.on('ter minal_output', (d) => {
                    if (debugEl) debugEl.innerText = `✅ Connected → ${ containerName }`;
                    if (term) term.write(d.data);});
                    socket.on('terminal_error', (d) => { if (term) term.write(`\r\nError: ${ d.data }\r\n`);});
                     if (term) term.onData(d => socket.emit('terminal_input', { data: d}));}

                    function resizeTerminal() { if (fitAddon) fitAddon.fit();}

                    function closeTerminal() {
                    document.getElementById('terminalModal').style.display='none';
                    if (socket) socket.disconnect();
                    if (term) term.dispose();
                    window.removeEventListener('resize', resizeTerminal);}

                    function openEventsModal(name) {
                    document.getElementById('eventsModal').style.display='block';
                    document.getElementById('events-title').innerText = `Events: ${ name }`;
                    document.getElementById('events-loading').style.display='block';
                    docu ment .get Elem entById('events-table-body').innerHTML='';

                    const ns = document.getElementById('namespace-select').value;
                    fetch(`/ api / events / ${ name } ? namespace = ${ ns  }` ) 
                         .t hen( r => {
                      if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText)});
                    return r.json();})
                    .then(data => {
                    if (data.error) throw new Error(data.error);

                    document.getElementById('events-loading').style.display='none';
                    const tbody = document.getElementById('events-table-body');
                    if (data.events && data.events.length > 0) {
                    tbody.innerHTML = data.events.map(e => `
                < tr >
                        <td>${e.type}</td>
                        <td>${e.reason}</td>
                        <td>${e.message}</td>
                        <td>${e.count}</td>
                        <td>${new Date(e.last_timestamp).toLocaleString()}</td>
                    </tr >
                `).join('');} else {
                    tbody.innerHTML='<tr><t d colspan="5">No events found.</td>
                    </tr>';}}).catch(e => {document.getElementById('events-loading').innerText="Error: " + e.message;});}

                    function openSecurityHelp() {
                    document.getElementById('securityHelpModal').style.display='block';}

                    function openOptimizerHelp() {
                    document.getElementById('optimizerHelpModal').style.display='block';}

                    function openYamlModal(name, type) {
                    document.getElementById('yamlModal').style.display='block';
                    document.getElementById('yaml-title').innerText = `YAML: ${ type } ${ name }`;
                    document.getElementById('yaml-content').innerText="Loading...";

                    const ns = document.getElementById('namespace-select').value;
                    fetch(`/ api / yaml / ${ name } ? type = ${ type } & namespace=${ ns }`)
                    . then (r => {
                    if (!r.ok) return r.json().then(e => { throw new Error(e.error || r.statusText)});
                    return r.json();})
                    .then(data => {
                    if (data.error) throw new Error(data.error);

                    if (data.yaml) {
                    document.getElementById('yaml-content').innerText = JSON.stringify(data.yaml, null, 2);} else {
                    document.getElementById('yaml-content').innerText="Error: No YAML content returned.";}})
                       .catch(e => {
                    document.getEle ment ById(' yaml-content').innerText="Error: " + e.message;});}

                    function openHelpModal() {
                    document.getElementById('helpModal').style.display='block';}

                      async function analyzePodLogs(name) {
                    showToast(`🤖 Asking Gemini to analyze logs for ${ name }...`, false);
                    try {
                    const ns = document.getElementById('namespace-select').value;
                    const response = await fetch('/api/ai/analyze_logs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json'},
                    body: JSON.stringify({ pod_name: name, namespace: ns})});
                       const data = await response.json();

                    // Reuse the existing log modal (correct IDs: logModal, modal-title, log-content)
                    const modal = document.getElementById('logModal');
                    const title = document.getElementById('modal-title');
                    const content = document.getElementById('log-content');

                    if (!modal || !title || !content) {
                    showToast('⚠️ Could not open analysis modal — UI element missing.', true);
                    return;}

                    title.innerText = `Gemini Analysis: ${ name } ♊`;
                    // Simple markdown rendering (bold, code blocks, newlines)
                    let html = data.analysis || data.summary || data.error || 'No analysis returned.';
                    html = html
                    .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
                    .replace(/`(.*?)`/g, '<code
                        style="background:#f0f0f0;padding:2px 4px;border-radius:3px;">$1</code>')
                    .replace(/\n/g, '<br>');

                    content.innerHTML = `< div style = "padding:16px;font-family:sans-serif;line-height:1.7;" > ${ html }</div >
                `;
                    modal.style.display='block';

                    showToast(`✅ Analysis complete!`, true);} catch (e) {
                    showToast(`Error: ${ e } `, true);}}

                    // ── Init: restore saved tab state then start polling ──────────
                    (function restoreTabs() {
                    const mainTab = localStorage.getItem('gdc-main-tab') || 'workloads';
                    switchMainTab(mainTab, /*skipSave=*/true);

                    // Restore inner tabs for workloads and networking panels
                    ['workloads', 'networking'].forEach(panel => {
                    const saved = localStorage.getItem(`gdc - tab - ${ panel }`);
                    if (saved) {
                    try { switchTab(panel, saved, /*skipSave=*/true);} catch (e) {}}});})();

                    fetchData();
                    refreshInterval = setInterval(fetchData, 5000);
    