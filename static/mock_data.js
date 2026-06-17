// ═══════════════════════════════════════════════════════════════════
// CLIENT-SIDE MOCK DATA — makes the dashboard work without a backend
// Detects file:// protocol or server unavailability and returns mock data.
// ═══════════════════════════════════════════════════════════════════

(function() {
    const _isOffline = window.location.protocol === 'file:';
    if (!_isOffline) return; // Only activate when opened as a local file

    console.log('[mock] Running in offline/demo mode — using embedded mock data');

    function ts(minAgo) {
        return new Date(Date.now() - minAgo * 60000).toISOString();
    }

    function mockJson(data, delay) {
        return new Promise(r => setTimeout(() => r(new Response(JSON.stringify(data), {
            status: 200, headers: { 'Content-Type': 'application/json' }
        })), delay || 50));
    }

    // ── Mock Workloads ──────────────────────────────────────────────
    function getWorkloads(ns) {
        const p = ns && ns !== 'default' ? ns + '-' : '';
        return [
            {name:p+'frontend-deployment',type:'Deployment',status:'1/1',ready:1,total:1,age:ts(120),labels:{app:'frontend',image:'frontend:v2.4.1',chart:'frontend-1.8.0',team:'platform'}},
            {name:p+'backend-api',type:'Deployment',status:'2/2',ready:2,total:2,age:ts(300),labels:{app:'backend-api',image:'backend-api:v3.1.2',chart:'backend-2.5.0',team:'core'}},
            {name:p+'database-statefulset',type:'StatefulSet',status:'1/1',ready:1,total:1,age:ts(600)},
            {name:p+'log-collector',type:'DaemonSet',status:'3/3',ready:3,total:3,age:ts(1000)},
            {name:p+'frontend-pod-1',type:'Pod',status:'Running',ready:1,total:1,containers:[{name:'nginx'}],age:ts(110)},
            {name:p+'backend-pod-multi',type:'Pod',status:'Running',ready:2,total:2,containers:[{name:'api-server'},{name:'sidecar-proxy'}],age:ts(45)},
            {name:p+'billing-service',type:'Deployment',status:'3/3',ready:3,total:3,age:ts(5000),labels:{app:'billing',image:'billing-service:v1.12.0',chart:'billing-3.1.0',team:'finance'}},
            {name:p+'ml-inference',type:'Deployment',status:'1/1',ready:1,total:1,age:ts(300),labels:{app:'ml-inference',image:'ml-inference:v0.9.5-beta',chart:'ml-inference-0.3.2',team:'ml'}},
            {name:p+'payment-processor-0',type:'Pod',status:'CrashLoopBackOff',ready:0,total:1,containers:[{name:'processor'}],age:ts(15)},
            {name:p+'analytics-job-oom',type:'Pod',status:'OOMKilled',ready:0,total:1,containers:[{name:'spark-driver'}],age:ts(5)},
            {name:p+'sidecar-missing',type:'Pod',status:'ImagePullBackOff',ready:0,total:2,containers:[{name:'main'},{name:'sidecar'}],age:ts(2)},
            {name:p+'api-gateway-v2',type:'Pod',status:'Pending',ready:0,total:1,containers:[{name:'gateway'}],age:ts(1)},
            {name:p+'init-demo-pod',type:'Pod',status:'Running',ready:1,total:1,containers:[{name:'app'},{name:'init-setup',type:'init'}],age:ts(10)},
            {name:p+'db-creds',type:'Secret',status:'Active',ready:1,total:1,age:ts(500)},
            {name:p+'app-config',type:'ConfigMap',status:'Active',ready:1,total:1,age:ts(400)},
            {name:p+'nginx-config',type:'ConfigMap',status:'Active',ready:1,total:1,age:ts(800)},
            {name:p+'db-migration-v4',type:'Job',status:'Succeeded',ready:1,total:1,age:ts(60),job_active:0,job_succeeded:1,job_failed:0,job_completions:1,job_parallelism:1},
            {name:p+'report-generator',type:'Job',status:'Running',ready:2,total:5,age:ts(8),job_active:3,job_succeeded:2,job_failed:0,job_completions:5,job_parallelism:3},
            {name:p+'data-import-failed',type:'Job',status:'Failed',ready:0,total:1,age:ts(120),job_active:0,job_succeeded:0,job_failed:3,job_completions:1,job_parallelism:1},
            {name:p+'cleanup-cron-7q2xp',type:'Job',status:'Pending',ready:0,total:1,age:ts(1),job_active:0,job_succeeded:0,job_failed:0,job_completions:1,job_parallelism:1},
        ];
    }

    // ── Mock Services ───────────────────────────────────────────────
    const SERVICES = [
        {name:'frontend',type:'LoadBalancer',cluster_ip:'10.0.0.1',ports:'80:3000',age:'2d'},
        {name:'backend-api',type:'ClusterIP',cluster_ip:'10.0.0.2',ports:'8080',age:'5d'},
        {name:'database-svc',type:'ClusterIP',cluster_ip:'10.0.0.3',ports:'5432',age:'10d'}
    ];

    // ── Mock VirtualServices ────────────────────────────────────────
    const VIRTUAL_SERVICES = [
        {name:'api-gateway-vs',hosts:'api.dummyapp-dev.internal, api.example.com',gateways:'istio-ingressgateway, mesh',age:'14d',http_routes:2,description:'Canary split: 90% stable / 10% canary',route_summary:[{destination:'api-gateway-stable',weight:90},{destination:'api-gateway-canary',weight:10}],timeout:'10s',retries:{attempts:3,per_try_timeout:'3s'}},
        {name:'payment-processor-vs',hosts:'payment-processor.dummyapp-dev.svc.cluster.local',gateways:'mesh',age:'7d',http_routes:1,description:'Single destination with strict timeout',route_summary:[{destination:'payment-processor',weight:100}],timeout:'5s',retries:{attempts:2,per_try_timeout:'2s'},fault:{delay:{percentage:0.1,fixed_delay:'500ms'}}},
        {name:'frontend-vs',hosts:'frontend.dummyapp-dev.internal, www.example.com',gateways:'istio-ingressgateway',age:'22d',http_routes:3,description:'Header-based A/B test routing',route_summary:[{destination:'frontend-v2',weight:null,match:'header: x-canary=true'},{destination:'frontend-v1',weight:100}],timeout:'15s',retries:{attempts:3,per_try_timeout:'5s'}},
        {name:'analytics-service-vs',hosts:'analytics.dummyapp-dev.svc.cluster.local',gateways:'mesh',age:'3d',http_routes:1,description:'Fault injection for chaos testing — 5% HTTP 503',route_summary:[{destination:'analytics-service',weight:100}],timeout:'30s',fault:{abort:{percentage:5,http_status:503}}},
        {name:'database-svc-vs',hosts:'database-svc.dummyapp-dev.svc.cluster.local',gateways:'mesh',age:'30d',http_routes:1,description:'TCP route — no timeout or retry policy ⚠️',route_summary:[{destination:'database-statefulset',weight:100}],timeout:null,retries:null},
    ];

    // ── Mock Security Scan ──────────────────────────────────────────
    const SECURITY_SCAN = {findings:[
        {severity:'CRITICAL',category:'Container Security',resource:'payment-processor-0',issue:'Container running as root user (UID 0)',remediation:'Add `securityContext.runAsNonRoot: true` and set `runAsUser: 1000`',refs:'CIS-5.2.6'},
        {severity:'HIGH',category:'Resource Limits',resource:'frontend-deployment',issue:'No memory limit set — risk of OOMKill on neighbours',remediation:'Set `resources.limits.memory` to prevent unbounded usage',refs:'CIS-5.4.1'},
        {severity:'HIGH',category:'Image Security',resource:'sidecar-missing',issue:'Using :latest tag — no version pinning',remediation:'Pin to a specific image digest or semantic version tag',refs:'CIS-5.5.1'},
        {severity:'MEDIUM',category:'Network Policy',resource:'backend-api',issue:'No NetworkPolicy restricting ingress traffic',remediation:'Create a NetworkPolicy to whitelist allowed sources',refs:'CIS-5.3.2'},
        {severity:'LOW',category:'Labels',resource:'database-statefulset',issue:'Missing recommended labels (app.kubernetes.io/version)',remediation:'Add standard Kubernetes labels for better observability',refs:'K8s-Labels'},
    ]};

    // ── Mock Optimizer ──────────────────────────────────────────────
    const C = 60;
    const OPTIMIZER = {
        cost_rate_per_core:C, currency:'EUR', metrics_source:'gemini-estimation',
        total_current_monthly_cost:1434, total_recommended_monthly_cost:343.5, total_monthly_saving:1090.5,
        summary:'Gemini analysed 7 workloads. Current estimated monthly cost is €1434/month at €60/core. Total potential monthly saving: €1091 (76% reduction).',
        recommendations:[
            {resource:'billing-service',kind:'Deployment',replicas:3,type:'Cost Saving 📉',reason:'CPU requests set to 4.0 cores but usage is ~12%. Over-provisioned by 88%.',actual_usage_cpu:'0.48 cores',actual_usage_mem:'380 MiB',estimated_utilization:'~12% CPU, ~45% Memory',current_cpu_request:'4000m',current_cpu_limit:'8000m',current_mem_request:'2Gi',current_mem_limit:'8Gi',suggested_cpu_request:'650m',suggested_cpu_limit:'1300m',suggested_mem_request:'512Mi',suggested_mem_limit:'1Gi',current_monthly_cost:720,recommended_monthly_cost:117,monthly_saving:603,action:'kubectl set resources deploy/billing-service --requests=cpu=650m,memory=512Mi --limits=cpu=1300m,memory=1Gi',severity:'high',ai_insight:'Billing services are IO-bound; CPU usage is low but memory should account for connection pools.'},
            {resource:'frontend-deployment',kind:'Deployment',replicas:2,type:'Stability Risk ⚠️',reason:'No memory limit set. Usage ~45 MiB but without a limit the pod can OOM-kill neighbours.',actual_usage_cpu:'~0.03 cores',actual_usage_mem:'~45 MiB',estimated_utilization:'~3% CPU',current_cpu_request:'500m',current_cpu_limit:'not-set',current_mem_request:'not-set',current_mem_limit:'not-set',suggested_cpu_request:'50m',suggested_cpu_limit:'200m',suggested_mem_request:'64Mi',suggested_mem_limit:'128Mi',current_monthly_cost:60,recommended_monthly_cost:6,monthly_saving:54,action:'kubectl set resources deploy/frontend-deployment --requests=cpu=50m,memory=64Mi --limits=cpu=200m,memory=128Mi',severity:'high',ai_insight:'nginx serves static assets and rarely needs more than 100m CPU.'},
            {resource:'ml-inference',kind:'Deployment',replicas:1,type:'Performance Risk 📈',reason:'CPU usage (0.82 cores) exceeds request (0.50 cores). Under-provisioned.',actual_usage_cpu:'0.82 cores',actual_usage_mem:'6100 MiB',estimated_utilization:'~82% CPU, ~88% Memory',current_cpu_request:'500m',current_cpu_limit:'1000m',current_mem_request:'4Gi',current_mem_limit:'8Gi',suggested_cpu_request:'1100m',suggested_cpu_limit:'2200m',suggested_mem_request:'6Gi',suggested_mem_limit:'8Gi',current_monthly_cost:49.2,recommended_monthly_cost:66,monthly_saving:-16.8,action:'kubectl set resources deploy/ml-inference --requests=cpu=1100m,memory=6Gi',severity:'high',ai_insight:'ML inference workloads are CPU-intensive; throttling causes latency spikes.'},
        ]
    };

    // ── Mock RCA ────────────────────────────────────────────────────
    function mockRca(name) {
        return {resource:name,status:'CrashLoopBackOff',root_cause:'Container exceeded memory limit (OOMKilled). JVM heap set to 512m but container limit is 256Mi.',evidence:['Last State: OOMKilled (exit code 137)','Container memory usage peaked at 248Mi / 256Mi limit','JVM flags: -Xmx512m exceeds container memory limit'],severity:'critical',remediation:['Increase memory limit to at least 768Mi','Set JVM heap to 70% of container limit: -Xmx537m','Add memory request equal to limit for QoS Guaranteed'],kubectl_hints:['kubectl describe pod '+name+' | grep -A5 "Last State"','kubectl top pod '+name,'kubectl set resources deployment/'+name+' --limits=memory=768Mi']};
    }

    // ── Mock Diagnose ───────────────────────────────────────────────
    function mockDiagnose(name) {
        return {name:name,status:'CrashLoopBackOff',verdict:'❌ Pod is crash-looping due to OOMKilled',crash_reason:'Container exceeded memory limit',evidence:['Exit code 137 (SIGKILL by OOM killer)','Memory usage: 248Mi / 256Mi limit'],risk_level:'critical',recommendations:['Increase memory limit to 768Mi','Reduce JVM heap size','Add liveness probe with adequate initialDelaySeconds'],kubectl_hints:['kubectl describe pod '+name,'kubectl logs '+name+' --previous']};
    }

    // ── Mock Events ─────────────────────────────────────────────────
    function mockEvents(name) {
        const t = new Date().toISOString();
        const evts = [
            {type:'Normal',reason:'Scheduled',message:'Successfully assigned default/'+name+' to node-1',count:1,last_timestamp:t},
            {type:'Normal',reason:'Pulling',message:'Pulling image "my-app:latest"',count:1,last_timestamp:t},
            {type:'Normal',reason:'Started',message:'Started container main',count:1,last_timestamp:t}
        ];
        if (name.includes('payment') || name.includes('crash')) {
            evts.push({type:'Warning',reason:'BackOff',message:'Back-off restarting failed container',count:5,last_timestamp:t});
        }
        return {events:evts};
    }

    // ── Mock YAML ───────────────────────────────────────────────────
    function mockYaml(name) {
        return {yaml:'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: '+name+'\n  namespace: default\n  labels:\n    app: '+name+'\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: '+name+'\n  template:\n    metadata:\n      labels:\n        app: '+name+'\n    spec:\n      containers:\n      - name: main\n        image: '+name+':latest\n        ports:\n        - containerPort: 8080\n        resources:\n          requests:\n            cpu: 100m\n            memory: 128Mi\n          limits:\n            cpu: 500m\n            memory: 256Mi'};
    }

    // ── Mock Logs ───────────────────────────────────────────────────
    function mockLogs(name) {
        return {logs:'2024-01-15T10:30:01Z [INFO] Starting application '+name+'...\n2024-01-15T10:30:02Z [INFO] Connected to database\n2024-01-15T10:30:03Z [INFO] Listening on port 8080\n2024-01-15T10:30:15Z [WARN] High memory usage detected: 240Mi/256Mi\n2024-01-15T10:30:16Z [ERROR] java.lang.OutOfMemoryError: Java heap space\n2024-01-15T10:30:16Z [FATAL] Process killed by OOM killer (exit 137)'};
    }

    // ── Mock ConfigMap ──────────────────────────────────────────────
    function mockConfigMap(name) {
        return {name:name,data:{'DATABASE_URL':'postgres://user:pass@db:5432/mydb','LOG_LEVEL':'info','FEATURE_FLAGS':'{"new_ui":true,"beta_api":false}','MAX_RETRIES':'3'}};
    }

    // ── Mock Secret ─────────────────────────────────────────────────
    function mockSecret(name) {
        return {name:name,data:{'DB_PASSWORD':'c3VwZXJfc2VjcmV0XzEyMw==','API_KEY':'YWJjZGVmMTIzNDU2','TLS_CERT':'LS0tLS1CRUdJTi...'}};
    }

    // ── Mock Health Pulse ───────────────────────────────────────────
    function mockHealthPulse() {
        return {overall_health:'Degraded',score:62,summary:'2 of 7 pods are in a failed state. Payment processor is crash-looping, analytics job OOMKilled.',risks:[{level:'critical',message:'payment-processor-0 in CrashLoopBackOff — 5 restarts in 15 min'},{level:'high',message:'analytics-job-oom terminated by OOM killer'},{level:'medium',message:'sidecar-missing: ImagePullBackOff on sidecar container'}],positive_signals:['frontend-deployment: healthy, 1/1 ready','backend-api: healthy, 2/2 ready','billing-service: healthy, 3/3 ready']};
    }

    // ── Mock Network Health ─────────────────────────────────────────
    function mockNetworkHealth() {
        return {overall:'Healthy',score:85,findings:[{severity:'warning',message:'payment-processor-vs has fault injection enabled (delay 500ms on 0.1%)'},{severity:'info',message:'database-svc-vs has no timeout/retry policy configured'}],recommendations:['Add timeout policy to database-svc-vs','Review fault injection settings on payment-processor-vs']};
    }

    // ── Mock Summarize Logs ─────────────────────────────────────────
    function mockSummarizeLogs() {
        return {summary:'**Pattern detected: OOMKilled** — Container exceeded memory limit.\n\n**Evidence:**\n- `java.lang.OutOfMemoryError: Java heap space` at 10:30:16Z\n- Memory peaked at 240Mi / 256Mi limit\n- Process killed with exit code 137 (SIGKILL)\n\n**Root cause:** JVM heap (-Xmx512m) exceeds container memory limit (256Mi).\n\n**Recommended action:** Increase container memory limit to 768Mi or reduce JVM heap to -Xmx180m.'};
    }

    // ── Mock AI Query ───────────────────────────────────────────────
    function mockAiQuery(body) {
        const q = (body.query || '').toLowerCase();
        if (q.includes('failed') || q.includes('crash') || q.includes('error'))
            return {action:'filter',target:'Pod',criteria:{status:'Failed'},count:null,message:'✨ Filtering for failed / crashing pods...'};
        if (q.includes('running') || q.includes('healthy'))
            return {action:'filter',target:'Pod',criteria:{status:'Running'},count:null,message:'✅ Showing only running pods...'};
        if (q.includes('scale'))
            return {action:'scale',target:'frontend-deployment',count:3,criteria:{},message:'🚀 Scaling frontend-deployment to 3 replicas...'};
        if (q.includes('reset') || q.includes('clear') || q.includes('all'))
            return {action:'reset',target:'',criteria:{},count:null,message:'🔄 Showing all resources, filters cleared.'};
        if (q.includes('help'))
            return {action:'explain',target:'',criteria:{},count:null,message:'🤖 Here\'s what I can do.',reply:'I understand: filter, scale, restart, delete, logs, events, YAML, analyze, and more.'};
        return {action:'explain',target:'',criteria:{},count:null,message:'💡 Gemini answered your question.',reply:'I understood: "'+body.query+'". Try: "show failed pods", "scale frontend to 3", or "why is payment crashing".'};
    }

    // ── Mock Converse (Chat) ────────────────────────────────────────
    function mockConverse(body) {
        return {reply:'I\'m running in **demo mode** (no backend connected). In production, I would use Gemini Function Calling to query your live Kubernetes cluster.\n\nTry the **Ask AI** search bar for quick commands, or run the dashboard with `python mock_app.py` for full functionality.',tools_used:['demo_mode'],session_id:'demo-session'};
    }

    // ── Mock Generate YAML ──────────────────────────────────────────
    function mockGenerateYaml(body) {
        const desc = body.prompt || 'nginx app';
        return {yaml:'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: generated-app\nspec:\n  replicas: 2\n  selector:\n    matchLabels:\n      app: generated-app\n  template:\n    metadata:\n      labels:\n        app: generated-app\n    spec:\n      containers:\n      - name: app\n        image: nginx:1.25\n        ports:\n        - containerPort: 80\n        resources:\n          requests:\n            cpu: 100m\n            memory: 128Mi\n          limits:\n            cpu: 500m\n            memory: 256Mi\n---\napiVersion: v1\nkind: Service\nmetadata:\n  name: generated-app-svc\nspec:\n  selector:\n    app: generated-app\n  ports:\n  - port: 80\n    targetPort: 80\n  type: ClusterIP'};
    }

    // ── Generic mock for AI analysis endpoints ──────────────────────
    function mockGenericAi(name) {
        return {name:name||'unknown',verdict:'✅ Analysis complete (demo mode)',summary:'This is a mock analysis. Run with `python mock_app.py` for full Gemini-powered analysis.',risks:[],recommendations:['Connect to a backend server for live analysis'],score:75,overall_health:'Healthy'};
    }

    // ── Route matcher ───────────────────────────────────────────────
    const _realFetch = window.fetch.bind(window);
    window.fetch = async function(url, opts) {
        if (typeof url !== 'string') url = url.toString();
        
        // Non-API calls pass through
        if (!url.includes('/api/')) {
            try { return await _realFetch(url, opts); } catch(e) { throw e; }
        }

        // Parse body for POST requests
        let body = {};
        if (opts && opts.body) {
            try { body = JSON.parse(opts.body); } catch(e) {}
        }

        // Extract URL params
        const u = new URL(url, 'http://localhost');
        const ns = u.searchParams.get('namespace') || 'default';
        const pathParts = u.pathname.split('/').filter(Boolean); // ['api','workloads'] etc

        console.log('[mock] Intercepted:', u.pathname);

        // ── Route matching ──────────────────────────────────────────
        if (u.pathname === '/api/workloads') return mockJson(getWorkloads(ns));
        if (u.pathname === '/api/services') return mockJson(SERVICES);
        if (u.pathname === '/api/virtualservices') return mockJson(VIRTUAL_SERVICES);
        if (u.pathname === '/api/pod-stats') return mockJson({Running:5,Pending:1,Succeeded:2,Failed:2,Unknown:0});
        if (u.pathname === '/api/ping') return mockJson('ok');
        if (u.pathname === '/api/health') return mockJson({ok:true,ts:new Date().toISOString()});
        if (u.pathname === '/api/auth/status') return mockJson({authenticated:true,ts:new Date().toISOString()});
        if (u.pathname === '/api/ai/status') return mockJson({available:true,model:'gemini-2.5-flash (demo)',status:'ready',cache_entries:0,error:null});
        if (u.pathname === '/api/ai/optimize') return mockJson(OPTIMIZER, 500);
        if (u.pathname === '/api/ai/security_scan') return mockJson(SECURITY_SCAN, 400);
        if (u.pathname === '/api/ai/query') return mockJson(mockAiQuery(body), 300);
        if (u.pathname === '/api/ai/converse') return mockJson(mockConverse(body), 400);
        if (u.pathname === '/api/ai/converse/reset') return mockJson({ok:true});
        if (u.pathname === '/api/ai/generate_yaml') return mockJson(mockGenerateYaml(body), 500);
        if (u.pathname === '/api/ai/summarize_logs') return mockJson(mockSummarizeLogs(), 400);
        if (u.pathname === '/api/ai/rca') return mockJson(mockRca(body.name || 'payment-processor-0'), 600);
        if (u.pathname === '/api/ai/health_pulse') return mockJson(mockHealthPulse(), 300);
        if (u.pathname === '/api/ai/network_health') return mockJson(mockNetworkHealth(), 300);
        if (u.pathname === '/api/ai/explain_configmap') return mockJson({explanation:'**Purpose**: ConfigMap provides runtime configuration.\n\n**Keys**: DATABASE_URL, LOG_LEVEL, FEATURE_FLAGS, MAX_RETRIES.\n\n⚠️ DATABASE_URL contains a password — move to a Secret.'}, 400);

        // Pod-specific endpoints: /api/pods/<name>/logs, /api/events/<name>, /api/yaml/<name>
        if (u.pathname.startsWith('/api/pods/') && u.pathname.endsWith('/logs')) {
            const podName = pathParts[2];
            return mockJson(mockLogs(podName), 200);
        }
        if (u.pathname.startsWith('/api/pods/') && u.pathname.endsWith('/all_logs')) {
            const podName = pathParts[2];
            return mockJson({containers:{main:mockLogs(podName).logs}}, 200);
        }
        if (u.pathname.startsWith('/api/pods/') && u.pathname.endsWith('/containers')) {
            return mockJson({containers:['main','sidecar']}, 100);
        }
        if (u.pathname.startsWith('/api/events/')) {
            const name = pathParts[2];
            return mockJson(mockEvents(name), 200);
        }
        if (u.pathname.startsWith('/api/yaml/')) {
            const name = pathParts[2];
            return mockJson(mockYaml(name), 200);
        }
        if (u.pathname.startsWith('/api/secrets/')) {
            const name = pathParts[2];
            return mockJson(mockSecret(name), 100);
        }
        if (u.pathname.startsWith('/api/configmaps/')) {
            const name = pathParts[2];
            return mockJson(mockConfigMap(name), 100);
        }

        // Action endpoints
        if (u.pathname === '/api/scale') return mockJson({message:'Mock: Scaled '+body.name+' to '+(body.count||1)+' replicas',new_replicas:body.count||1}, 200);
        if (u.pathname === '/api/restart') return mockJson({message:'Mock: Rolling restart triggered for '+body.name+'. New pods will be ready in ~30s.'}, 200);
        if (u.pathname === '/api/delete') return mockJson({message:'Mock: Deleted '+body.name+' successfully.'}, 200);
        if (u.pathname === '/api/workloads/env') return mockJson({env:[{name:'DATABASE_URL',value:'postgres://user:***@db:5432/mydb'},{name:'LOG_LEVEL',value:'info'},{name:'NODE_ENV',value:'production'}]}, 100);

        // AI analysis endpoints — return generic mock
        if (u.pathname.startsWith('/api/ai/')) {
            const name = body.name || body.resource || 'unknown';
            return mockJson(mockGenericAi(name), 400);
        }

        // Fallback
        console.warn('[mock] No handler for:', u.pathname);
        return mockJson({error:'Mock: No handler for this endpoint'}, 50);
    };
})();
