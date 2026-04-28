from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime, timedelta
import os
import re

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# Mock Data Generation
def get_mock_timestamp(minutes_ago):
    return (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + "Z"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/ping')
def api_ping():
    """Ultra-lightweight keepalive — no K8s call, just proves the worker is alive."""
    return 'ok', 200

@app.route('/api/auth/status')
def api_auth_status():
    """Auth status check — proves auth is valid."""
    return jsonify({
        'authenticated': True,
        'ts': datetime.utcnow().isoformat()
    })

@app.route('/api/health')
def api_health():
    """Lightweight liveness ping."""
    return jsonify({'ok': True, 'ts': datetime.utcnow().isoformat()})

@app.route('/api/ai/status')
def api_ai_status():
    """AI readiness status — mock always returns ready."""
    return jsonify({
        'available': True,
        'model': 'gemini-2.5-flash (mock)',
        'status': 'ready',
        'cache_entries': 0,
        'error': None
    })

@app.route('/api/pod-stats')
def get_pod_stats():
    """Mock pod phase statistics."""
    namespace = request.args.get('namespace', 'default')
    return jsonify({
        'Running': 5,
        'Pending': 1,
        'Succeeded': 2,
        'Failed': 2,
        'Unknown': 0
    })

@app.route('/api/vuln_scan/debug')
def vuln_scan_debug():
    """Mock Trivy diagnostic endpoint."""
    namespace = request.args.get('namespace', 'default')
    return jsonify({
        'trivy_binary': '/usr/local/bin/trivy (mock)',
        'trivy_version': 'Version: 0.52.0 (mock)',
        'db_status': 'OK',
        'test_scan_alpine': 'SUCCESS — found 3 vulnerabilities in alpine:3.19 (mock)',
        'namespace': namespace,
        'images_found': [
            'frontend:v2.4.1',
            'backend-api:v3.1.2',
            'billing-service:v1.12.0',
            'ml-inference:v0.9.5-beta',
            'postgres:15',
            'envoy:v1.27.0',
            'fluentbit:2.2.0'
        ],
        'image_count': 7,
        'test_real_image': 'backend-api:v3.1.2',
        'test_real_result': 'SUCCESS — found 12 vulnerabilities (mock)',
        'status': 'OK',
        'message': 'Mock diagnostic — all checks simulated as passing.'
    })

@app.route('/api/workloads')
def get_workloads():
    namespace = request.args.get('namespace', 'default')
    prefix = f"{namespace}-" if namespace != 'default' else ""
    
    
    # Check for mock scaling state
    global MOCK_SCALES
    if 'MOCK_SCALES' not in globals(): MOCK_SCALES = {}

    def get_scale(name, default_ready, default_total):
        if name in MOCK_SCALES:
            total = MOCK_SCALES[name]
            # Simulate "scaling up" time or just be instant for demo
            ready = total 
            return f"{ready}/{total}", ready, total
        return f"{default_ready}/{default_total}", default_ready, default_total

    s_front, r_front, t_front = get_scale(f'{prefix}frontend-deployment', 1, 1)
    s_back, r_back, t_back = get_scale(f'{prefix}backend-api', 2, 2)
    s_bill, r_bill, t_bill = get_scale(f'{prefix}billing-service', 3, 3)
    s_ml, r_ml, t_ml = get_scale(f'{prefix}ml-inference', 1, 1)
    s_db, r_db, t_db = get_scale(f'{prefix}database-statefulset', 1, 1)
    s_log, r_log, t_log = get_scale(f'{prefix}log-collector', 3, 3)

    data = [
        {'name': f'{prefix}frontend-deployment', 'type': 'Deployment', 'status': s_front, 'ready': r_front, 'total': t_front, 'age': get_mock_timestamp(120),
         'labels': {'app': 'frontend', 'image': 'frontend:v2.4.1', 'chart': 'frontend-1.8.0', 'team': 'platform'}},
        {'name': f'{prefix}backend-api', 'type': 'Deployment', 'status': s_back, 'ready': r_back, 'total': t_back, 'age': get_mock_timestamp(300),
         'labels': {'app': 'backend-api', 'image': 'backend-api:v3.1.2', 'chart': 'backend-2.5.0', 'team': 'core'}},
        {'name': f'{prefix}database-statefulset', 'type': 'StatefulSet', 'status': s_db, 'ready': r_db, 'total': t_db, 'age': get_mock_timestamp(600)},
        {'name': f'{prefix}log-collector', 'type': 'DaemonSet', 'status': s_log, 'ready': r_log, 'total': t_log, 'age': get_mock_timestamp(1000)},
        {'name': f'{prefix}frontend-pod-1', 'type': 'Pod', 'status': 'Running', 'ready': 1, 'total': 1, 'containers': [{'name': 'nginx'}], 'age': get_mock_timestamp(110)},
        {'name': f'{prefix}backend-pod-multi', 'type': 'Pod', 'status': 'Running', 'ready': 2, 'total': 2, 'containers': [{'name': 'api-server'}, {'name': 'sidecar-proxy'}], 'age': get_mock_timestamp(45)},
        # Optimizer Mock workloads
        {'name': f'{prefix}billing-service', 'type': 'Deployment', 'status': s_bill, 'ready': r_bill, 'total': t_bill, 'age': get_mock_timestamp(5000),
         'labels': {'app': 'billing', 'image': 'billing-service:v1.12.0', 'chart': 'billing-3.1.0', 'team': 'finance'}},
        {'name': f'{prefix}ml-inference', 'type': 'Deployment', 'status': s_ml, 'ready': r_ml, 'total': t_ml, 'age': get_mock_timestamp(300),
         'labels': {'app': 'ml-inference', 'image': 'ml-inference:v0.9.5-beta', 'chart': 'ml-inference-0.3.2', 'team': 'ml'}},
    ]
    data.extend([
        {'name': f'{prefix}payment-processor-0', 'type': 'Pod', 'status': 'CrashLoopBackOff', 'ready': 0, 'total': 1, 'containers': [{'name': 'processor'}], 'age': get_mock_timestamp(15)},
        {'name': f'{prefix}analytics-job-oom', 'type': 'Pod', 'status': 'OOMKilled', 'ready': 0, 'total': 1, 'containers': [{'name': 'spark-driver'}], 'age': get_mock_timestamp(5)},
        {'name': f'{prefix}sidecar-missing', 'type': 'Pod', 'status': 'ImagePullBackOff', 'ready': 0, 'total': 2, 'containers': [{'name': 'main'}, {'name': 'sidecar'}], 'age': get_mock_timestamp(2)},
        {'name': f'{prefix}api-gateway-v2', 'type': 'Pod', 'status': 'Pending', 'ready': 0, 'total': 1, 'containers': [{'name': 'gateway'}], 'age': get_mock_timestamp(1)},
        {'name': f'{prefix}init-demo-pod', 'type': 'Pod', 'status': 'Running', 'ready': 1, 'total': 1, 'containers': [{'name': 'app'}, {'name': 'init-setup', 'type': 'init'}], 'age': get_mock_timestamp(10)},
        # Secrets
        {'name': f'{prefix}db-creds', 'type': 'Secret', 'status': 'Active', 'ready': 1, 'total': 1, 'age': get_mock_timestamp(500)},
        # ConfigMaps
        {'name': f'{prefix}app-config', 'type': 'ConfigMap', 'status': 'Active', 'ready': 1, 'total': 1, 'age': get_mock_timestamp(400)},
        {'name': f'{prefix}nginx-config', 'type': 'ConfigMap', 'status': 'Active', 'ready': 1, 'total': 1, 'age': get_mock_timestamp(800)},
        # Jobs — use new schema with job_* counter fields
        {
            'name': f'{prefix}db-migration-v4', 'type': 'Job', 'status': 'Succeeded',
            'ready': 1, 'total': 1, 'age': get_mock_timestamp(60),
            'job_active': 0, 'job_succeeded': 1, 'job_failed': 0,
            'job_completions': 1, 'job_parallelism': 1,
        },
        {
            'name': f'{prefix}report-generator', 'type': 'Job', 'status': 'Running',
            'ready': 2, 'total': 5, 'age': get_mock_timestamp(8),
            'job_active': 3, 'job_succeeded': 2, 'job_failed': 0,
            'job_completions': 5, 'job_parallelism': 3,
        },
        {
            'name': f'{prefix}data-import-failed', 'type': 'Job', 'status': 'Failed',
            'ready': 0, 'total': 1, 'age': get_mock_timestamp(120),
            'job_active': 0, 'job_succeeded': 0, 'job_failed': 3,
            'job_completions': 1, 'job_parallelism': 1,
        },
        {
            'name': f'{prefix}cleanup-cron-7q2xp', 'type': 'Job', 'status': 'Pending',
            'ready': 0, 'total': 1, 'age': get_mock_timestamp(1),
            'job_active': 0, 'job_succeeded': 0, 'job_failed': 0,
            'job_completions': 1, 'job_parallelism': 1,
        },
    ])
    return jsonify(data)

@app.route('/api/services')
def get_services():
    # Mock Services
    namespace = request.args.get('namespace', 'default')
    return jsonify([
        {'name': 'frontend', 'type': 'LoadBalancer', 'cluster_ip': '10.0.0.1', 'ports': '80:3000', 'age': '2d'},
        {'name': 'backend-api', 'type': 'ClusterIP', 'cluster_ip': '10.0.0.2', 'ports': '8080', 'age': '5d'},
        {'name': 'database-svc', 'type': 'ClusterIP', 'cluster_ip': '10.0.0.3', 'ports': '5432', 'age': '10d'}
    ])

@app.route('/api/virtualservices')
def get_virtualservices():
    """Rich mock VirtualServices to demonstrate Networking + AI features."""
    ns = request.args.get('namespace', 'dbsleuth-dev')
    return jsonify([
        {
            'name': 'api-gateway-vs',
            'hosts': 'api.dbsleuth-dev.internal, api.example.com',
            'gateways': 'istio-ingressgateway, mesh',
            'age': '14d',
            'http_routes': 2,
            'description': 'Canary split: 90% stable / 10% canary',
            'route_summary': [
                {'destination': 'api-gateway-stable', 'weight': 90},
                {'destination': 'api-gateway-canary', 'weight': 10},
            ],
            'timeout': '10s',
            'retries': {'attempts': 3, 'per_try_timeout': '3s'},
        },
        {
            'name': 'payment-processor-vs',
            'hosts': 'payment-processor.dbsleuth-dev.svc.cluster.local',
            'gateways': 'mesh',
            'age': '7d',
            'http_routes': 1,
            'description': 'Single destination with strict timeout',
            'route_summary': [
                {'destination': 'payment-processor', 'weight': 100},
            ],
            'timeout': '5s',
            'retries': {'attempts': 2, 'per_try_timeout': '2s'},
            'fault': {'delay': {'percentage': 0.1, 'fixed_delay': '500ms'}},
        },
        {
            'name': 'frontend-vs',
            'hosts': 'frontend.dbsleuth-dev.internal, www.example.com',
            'gateways': 'istio-ingressgateway',
            'age': '22d',
            'http_routes': 3,
            'description': 'Header-based A/B test routing',
            'route_summary': [
                {'destination': 'frontend-v2', 'weight': None, 'match': 'header: x-canary=true'},
                {'destination': 'frontend-v1', 'weight': 100},
            ],
            'timeout': '15s',
            'retries': {'attempts': 3, 'per_try_timeout': '5s'},
        },
        {
            'name': 'analytics-service-vs',
            'hosts': 'analytics.dbsleuth-dev.svc.cluster.local',
            'gateways': 'mesh',
            'age': '3d',
            'http_routes': 1,
            'description': 'Fault injection for chaos testing — 5% HTTP 503',
            'route_summary': [
                {'destination': 'analytics-service', 'weight': 100},
            ],
            'timeout': '30s',
            'fault': {'abort': {'percentage': 5, 'http_status': 503}},
        },
        {
            'name': 'database-svc-vs',
            'hosts': 'database-svc.dbsleuth-dev.svc.cluster.local',
            'gateways': 'mesh',
            'age': '30d',
            'http_routes': 1,
            'description': 'TCP route — no timeout or retry policy ⚠️',
            'route_summary': [
                {'destination': 'database-statefulset', 'weight': 100},
            ],
            'timeout': None,
            'retries': None,
        },
        {
            'name': 'external-payments-egress-vs',
            'hosts': 'api.stripe.com',
            'gateways': 'mesh',
            'age': '10d',
            'http_routes': 1,
            'description': 'Egress to Stripe API — externally controlled service entry',
            'route_summary': [
                {'destination': 'api.stripe.com', 'weight': 100},
            ],
            'timeout': '8s',
            'retries': {'attempts': 1, 'per_try_timeout': '8s'},
        },
    ])


@app.route('/api/ai/explain_configmap')
def explain_configmap():
    """Mock Gemini ConfigMap explanation."""
    import time
    time.sleep(1.2)
    name = request.args.get('name', 'unknown')
    return jsonify({
        "explanation": (
            f"**Purpose**: The `{name}` ConfigMap configures the application runtime environment "
            f"for the associated microservice. It is typically mounted as environment variables "
            f"or as a volume into the workload pods.\n\n"
            f"**Key breakdown**:\n"
            f"- **DATABASE_URL** — Connection string used by the application to reach the database. "
            f"Should be validated for correct format.\n"
            f"- **LOG_LEVEL** — Controls application verbosity (`debug`, `info`, `warn`, `error`). "
            f"Production should be `info` or `warn` to avoid log volume overhead.\n"
            f"- **FEATURE_FLAGS** — JSON object enabling/disabling feature toggles without redeployment.\n"
            f"- **MAX_RETRIES** — Retry policy for downstream HTTP calls; set too high can cause cascading failures.\n\n"
            f"⚠️ **Security concern**: `DATABASE_URL` appears to contain a plaintext password. "
            f"This should be moved to a Kubernetes **Secret** and referenced via `secretKeyRef` "
            f"instead of being stored in a ConfigMap.\n\n"
            f"✅ **Recommendation**: Split sensitive keys into a dedicated Secret. "
            f"Apply `immutable: true` to this ConfigMap if the values are stable to reduce API server load."
        )
    })

@app.route('/api/ai/optimize')
def ai_optimize():

    """Mock AI-powered optimizer with full new schema including metrics fields."""
    import time
    time.sleep(2.0)  # simulate Gemini analysis latency

    COST_PER_CORE = 60.0  # EUR per core per month

    recommendations = [
        # ── Deployments ───────────────────────────────────────────────────────
        {
            "resource": "billing-service",
            "kind": "Deployment",
            "replicas": 3,
            "type": "Cost Saving 📉",
            "reason": "CPU requests set to 4.0 cores but billing services typically run at ~12% CPU. Actual measured usage: 0.48 cores/replica. You are being billed on REQUESTS (4 cores) — not usage (0.48 cores). Over-provisioned by 88%.",
            "actual_usage_cpu": "0.48 cores (measured)",
            "actual_usage_mem": "380 MiB (measured)",
            "capacity_headroom_pct": "94%",
            "billable_cores": 4.0,
            "billing_basis": "requests",
            "estimated_utilization": "~12% CPU, ~45% Memory",
            "current_cpu_request": "4000m",
            "current_cpu_limit": "8000m",
            "current_mem_request": "2Gi",
            "current_mem_limit": "8Gi",
            "suggested_cpu_request": "650m",
            "suggested_cpu_limit": "1300m",
            "suggested_mem_request": "512Mi",
            "suggested_mem_limit": "1Gi",
            "current_monthly_cost": round(4.0 * COST_PER_CORE * 3, 2),
            "recommended_monthly_cost": round(0.65 * COST_PER_CORE * 3, 2),
            "monthly_saving": round((4.0 - 0.65) * COST_PER_CORE * 3, 2),
            "action": "kubectl set resources deploy/billing-service --requests=cpu=650m,memory=512Mi --limits=cpu=1300m,memory=1Gi",
            "severity": "high",
            "ai_insight": "Billing/payment services are IO-bound (DB + HTTP); CPU usage is low but memory should account for connection pools."
        },
        {
            "resource": "frontend-deployment",
            "kind": "Deployment",
            "replicas": 2,
            "type": "Stability Risk ⚠️",
            "reason": "No memory limit set. Usage is ~45 MiB but without a limit the pod can consume unlimited node memory and OOM-kill neighbours.",
            "actual_usage_cpu": "~0.03 cores (estimated)",
            "actual_usage_mem": "~45 MiB (estimated)",
            "capacity_headroom_pct": "N/A",
            "billable_cores": 0.5,
            "billing_basis": "requests",
            "estimated_utilization": "~3% CPU, ~50Mi Memory",
            "current_cpu_request": "500m",
            "current_cpu_limit": "not-set",
            "current_mem_request": "not-set",
            "current_mem_limit": "not-set",
            "suggested_cpu_request": "50m",
            "suggested_cpu_limit": "200m",
            "suggested_mem_request": "64Mi",
            "suggested_mem_limit": "128Mi",
            "current_monthly_cost": round(0.5 * COST_PER_CORE * 2, 2),
            "recommended_monthly_cost": round(0.05 * COST_PER_CORE * 2, 2),
            "monthly_saving": round((0.5 - 0.05) * COST_PER_CORE * 2, 2),
            "action": "kubectl set resources deploy/frontend-deployment --requests=cpu=50m,memory=64Mi --limits=cpu=200m,memory=128Mi",
            "severity": "high",
            "ai_insight": "nginx serves static assets and rarely needs more than 100m CPU. Add limits to protect co-located workloads."
        },
        {
            "resource": "ml-inference",
            "kind": "Deployment",
            "replicas": 1,
            "type": "Performance Risk 📈",
            "reason": "Actual CPU usage (0.82 cores) exceeds request (0.50 cores). Kubernetes throttles this pod when CPU hits the limit. Billed on USAGE — under-provisioned.",
            "actual_usage_cpu": "0.82 cores (measured)",
            "actual_usage_mem": "6100 MiB (measured)",
            "capacity_headroom_pct": "18%",
            "billable_cores": 0.82,
            "billing_basis": "usage",
            "estimated_utilization": "~82% CPU, ~88% Memory",
            "current_cpu_request": "500m",
            "current_cpu_limit": "1000m",
            "current_mem_request": "4Gi",
            "current_mem_limit": "8Gi",
            "suggested_cpu_request": "1100m",
            "suggested_cpu_limit": "2200m",
            "suggested_mem_request": "6Gi",
            "suggested_mem_limit": "8Gi",
            "current_monthly_cost": round(0.82 * COST_PER_CORE * 1, 2),
            "recommended_monthly_cost": round(1.1 * COST_PER_CORE * 1, 2),
            "monthly_saving": round((0.82 - 1.1) * COST_PER_CORE * 1, 2),
            "action": "kubectl set resources deploy/ml-inference --requests=cpu=1100m,memory=6Gi --limits=cpu=2200m,memory=8Gi",
            "severity": "high",
            "ai_insight": "ML inference workloads are CPU-intensive during active requests; throttling causes latency spikes and degraded model response times."
        },
        {
            "resource": "checkout-service",
            "kind": "Deployment",
            "replicas": 2,
            "type": "Right-Sized ✅",
            "reason": "Spring Boot service at ~42% CPU utilisation of request. Billing on requests is correct. Memory well-bounded by JVM heap settings.",
            "actual_usage_cpu": "0.21 cores (measured)",
            "actual_usage_mem": "368 MiB (measured)",
            "capacity_headroom_pct": "58%",
            "billable_cores": 0.5,
            "billing_basis": "requests",
            "estimated_utilization": "~42% CPU, ~72% Memory",
            "current_cpu_request": "500m",
            "current_cpu_limit": "1000m",
            "current_mem_request": "512Mi",
            "current_mem_limit": "1Gi",
            "suggested_cpu_request": "500m",
            "suggested_cpu_limit": "1000m",
            "suggested_mem_request": "512Mi",
            "suggested_mem_limit": "1Gi",
            "current_monthly_cost": round(0.5 * COST_PER_CORE * 2, 2),
            "recommended_monthly_cost": round(0.5 * COST_PER_CORE * 2, 2),
            "monthly_saving": 0.0,
            "action": "No changes needed. Monitor JVM GC pause time if latency increases.",
            "severity": "low",
            "ai_insight": "Spring Boot services at moderate traffic are typically well-provisioned at 500m/1 core with adequate burst headroom."
        },
        # ── StatefulSets ──────────────────────────────────────────────────────
        {
            "resource": "database-statefulset",
            "kind": "StatefulSet",
            "replicas": 1,
            "type": "Performance Risk 📈",
            "reason": "PostgreSQL memory is critically undersized at 256Mi limit. Measured usage is 241 MiB — at 94% capacity, shared_buffers is starved. Under-provisioned, billed on usage.",
            "actual_usage_cpu": "0.19 cores (measured)",
            "actual_usage_mem": "241 MiB (measured)",
            "capacity_headroom_pct": "62%",
            "billable_cores": 0.25,
            "billing_basis": "requests",
            "estimated_utilization": "~25% CPU, ~94% Memory",
            "current_cpu_request": "250m",
            "current_cpu_limit": "500m",
            "current_mem_request": "256Mi",
            "current_mem_limit": "256Mi",
            "suggested_cpu_request": "500m",
            "suggested_cpu_limit": "2000m",
            "suggested_mem_request": "1Gi",
            "suggested_mem_limit": "2Gi",
            "current_monthly_cost": round(0.25 * COST_PER_CORE * 1, 2),
            "recommended_monthly_cost": round(0.5 * COST_PER_CORE * 1, 2),
            "monthly_saving": round((0.25 - 0.5) * COST_PER_CORE * 1, 2),
            "action": "kubectl patch statefulset database-statefulset -p '{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"postgres\",\"resources\":{\"requests\":{\"cpu\":\"500m\",\"memory\":\"1Gi\"},\"limits\":{\"cpu\":\"2000m\",\"memory\":\"2Gi\"}}}]}}}}' ",
            "severity": "high",
            "ai_insight": "PostgreSQL shared_buffers alone needs 25% of available RAM. 256Mi is dangerously undersized for any non-trivial workload."
        },
        {
            "resource": "redis-cache",
            "kind": "StatefulSet",
            "replicas": 1,
            "type": "Cost Saving 📉",
            "reason": "Redis requests 2 cores but is single-threaded — measured usage is only 0.07 cores. Billed on REQUESTS (2 cores). Over-provisioned by 96.5%.",
            "actual_usage_cpu": "0.07 cores (measured)",
            "actual_usage_mem": "290 MiB (measured)",
            "capacity_headroom_pct": "98%",
            "billable_cores": 2.0,
            "billing_basis": "requests",
            "estimated_utilization": "~7% CPU, ~55% Memory",
            "current_cpu_request": "2000m",
            "current_cpu_limit": "4000m",
            "current_mem_request": "512Mi",
            "current_mem_limit": "1Gi",
            "suggested_cpu_request": "100m",
            "suggested_cpu_limit": "500m",
            "suggested_mem_request": "512Mi",
            "suggested_mem_limit": "1Gi",
            "current_monthly_cost": round(2.0 * COST_PER_CORE * 1, 2),
            "recommended_monthly_cost": round(0.1 * COST_PER_CORE * 1, 2),
            "monthly_saving": round((2.0 - 0.1) * COST_PER_CORE * 1, 2),
            "action": "kubectl set resources statefulset/redis-cache --requests=cpu=100m,memory=512Mi --limits=cpu=500m,memory=1Gi",
            "severity": "medium",
            "ai_insight": "Redis is single-threaded for command processing; allocating 2 full cores creates significant wasted billing spend per month."
        },
        # ── DaemonSets ────────────────────────────────────────────────────────
        {
            "resource": "log-collector-daemonset",
            "kind": "DaemonSet",
            "replicas": 3,
            "type": "Cost Saving 📉",
            "reason": "Fluentd DaemonSet requests 1 core per node but measured usage is 0.06 cores. Billed on REQUESTS across 3 nodes = €180/month. Over-provisioned by 94%.",
            "actual_usage_cpu": "0.18 cores total (0.06 cores/node, measured)",
            "actual_usage_mem": "182 MiB total (measured)",
            "capacity_headroom_pct": "97%",
            "billable_cores": 1.0,
            "billing_basis": "requests",
            "estimated_utilization": "~6% CPU, ~36% Memory",
            "current_cpu_request": "1000m",
            "current_cpu_limit": "2000m",
            "current_mem_request": "512Mi",
            "current_mem_limit": "1Gi",
            "suggested_cpu_request": "100m",
            "suggested_cpu_limit": "500m",
            "suggested_mem_request": "256Mi",
            "suggested_mem_limit": "512Mi",
            "current_monthly_cost": round(1.0 * COST_PER_CORE * 3, 2),
            "recommended_monthly_cost": round(0.1 * COST_PER_CORE * 3, 2),
            "monthly_saving": round((1.0 - 0.1) * COST_PER_CORE * 3, 2),
            "action": "kubectl set resources daemonset/log-collector-daemonset --requests=cpu=100m,memory=256Mi --limits=cpu=500m,memory=512Mi",
            "severity": "medium",
            "ai_insight": "DaemonSets multiply their cost per node; over-provisioning a log collector by 10× silently inflates cluster-wide billing."
        },
    ]

    total_current     = sum(r["current_monthly_cost"]     for r in recommendations)
    total_recommended = sum(r["recommended_monthly_cost"] for r in recommendations)
    total_saving      = total_current - total_recommended

    return jsonify({
        "cost_rate_per_core":             COST_PER_CORE,
        "currency":                       "EUR",
        "metrics_source":                 "gemini-estimation",
        "total_current_monthly_cost":     round(total_current, 2),
        "total_recommended_monthly_cost": round(total_recommended, 2),
        "total_monthly_saving":           round(total_saving, 2),
        "summary": (
            f"AI analysed {len(recommendations)} workloads using AI-estimated usage (no metrics-server found). "
            f"Current estimated monthly cost is €{total_current:.0f}/month at €60/core. "
            f"Key savings: billing-service (4 cores → 650m, billed on requests), redis-cache (2 cores → 100m), "
            f"and the log-collector DaemonSet are the biggest over-provisioning offenders. "
            f"Total potential monthly saving: €{total_saving:.0f} ({int(total_saving/total_current*100)}% reduction)."
        ),
        "recommendations": recommendations
    })




@app.route('/api/ai/query', methods=['POST'])
def ai_query():
    """Mock AI-powered NLU command interpreter.
    Simulates Gemini intent classification — returns the exact same JSON schema
    as the real endpoint so the frontend handler works identically.
    """
    import time
    time.sleep(0.6)  # simulate Gemini latency

    data = request.json
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    query = data.get('query', '').strip()
    q = query.lower()

    # ── Available mock resources (mirrors what Gemini would see as context) ──
    mock_resources = [
        "payment-processor-0", "frontend-deployment", "analytics-worker",
        "checkout-service", "api-gateway", "database-statefulset"
    ]

    def best_match(words):
        """Return the mock resource that best matches any word in the query."""
        for r in mock_resources:
            for w in words:
                if w in r or r.split('-')[0] == w:
                    return r
        return words[0] if words else ''

    def extract_target(stop_words):
        words = [w for w in q.split() if w not in stop_words and len(w) > 2]
        return best_match(words)

    # ── EARLY: Educational/Explanation queries (check BEFORE K8s action keywords) ──
    # This must come first so "explain OOMKilled" doesn't get caught by "delete/kill"
    # and "what is a StatefulSet" doesn't get caught by "describe"
    _explain_prefixes = ["what is", "what are", "explain", "how do i", "how to",
                         "what does", "difference between", "generate a",
                         "create a deployment", "write a yaml", "oomkill",
                         "imagepullbackoff", "requests vs", "liveness probe",
                         "readiness probe", "statefulset vs", "daemonset vs"]
    if any(x in q for x in _explain_prefixes):
        # Build targeted explanation for common topics
        explanations = {
            'oomkill': (
                "**OOMKilled** means the pod's container exceeded its memory `limit` and the Linux kernel's OOM killer terminated it.\n"
                "**Fix:** Increase the container memory limit (`resources.limits.memory`) or reduce heap/JVM settings.\n"
                "Check with: `kubectl describe pod <name>` and look for `OOMKilled` in the `Last State` section."
            ),
            'imagepullbackoff': (
                "**ImagePullBackOff** means Kubernetes cannot pull the container image.\n"
                "Common causes: wrong image name/tag, private registry without credentials (`imagePullSecrets`), or image doesn't exist.\n"
                "Debug: `kubectl describe pod <name>` → look at Events for the exact pull error."
            ),
            'requests vs': (
                "**Requests** = the CPU/memory Kubernetes *guarantees* to your pod (used for scheduling).\n"
                "**Limits** = the maximum your pod can use before it gets throttled (CPU) or killed (memory).\n"
                "**Best practice:** set requests ≈ actual average usage and limits ≈ 2× requests for headroom."
            ),
            'liveness probe': (
                "A **liveness probe** lets Kubernetes know if your container is healthy. If it fails, K8s restarts the container.\n"
                "```yaml\nlivenessProbe:\n  httpGet:\n    path: /healthz\n    port: 8080\n  initialDelaySeconds: 15\n  periodSeconds: 10\n```\n"
                "Also consider a `readinessProbe` to control when traffic is sent to the pod."
            ),
            'statefulset': (
                "A **StatefulSet** gives pods stable network identities and persistent storage — unlike Deployments where pods are interchangeable.\n"
                "Use for: databases (PostgreSQL, MySQL, Redis), Kafka, Elasticsearch.\n"
                "Pods are named `my-sts-0`, `my-sts-1`, …, and are started/stopped in order."
            ),
            'generate a': (
                "Here's a minimal Deployment YAML:\n"
                "```yaml\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: my-app\nspec:\n  replicas: 2\n  selector:\n    matchLabels:\n      app: my-app\n  template:\n    metadata:\n      labels:\n        app: my-app\n    spec:\n      containers:\n      - name: my-app\n        image: nginx:1.25\n        ports:\n        - containerPort: 80\n        resources:\n          requests:\n            cpu: 100m\n            memory: 128Mi\n          limits:\n            cpu: 500m\n            memory: 256Mi\n```"
            ),
            'namespace': (
                f"A **namespace** is a virtual cluster inside Kubernetes for isolating workloads.\n"
                f"Your current namespace is **{data.get('namespace','(unknown)')}**.\n"
                "Use `kubectl get all -n <namespace>` to see everything in a namespace."
            ),
        }
        reply = next((v for k, v in explanations.items() if k in q), None)
        if not reply:
            reply = (
                f"I understood you're asking about: *\"{query}\".*\n"
                "As a Kubernetes AI assistant I can explain any K8s concept — try asking about: "
                "OOMKilled, ImagePullBackOff, requests vs limits, liveness probes, StatefulSet vs Deployment, "
                "or ask me to generate a YAML template."
            )
        return jsonify({'action': 'explain', 'target': '', 'criteria': {}, 'count': None,
                        'message': '💡 AI answered your Kubernetes question.',
                        'reply': reply})

    # ── Intent classification (mimics Gemini's output) ─────────────────────
    # IMPORTANT: Diagnostic/analyze intent MUST come before filter intent.
    # Queries like "why is my app crashing" contain the word "crash" but should
    # trigger RCA, not a pod list filter.
    _analyze_keywords = ["analyze", "rca", "why", "diagnose", "investigate",
                         "troubleshoot", "root cause", "what's wrong", "whats wrong",
                         "fix", "debug", "crashing", "failing", "keeps restarting",
                         "keeps failing", "what is wrong", "issue with"]
    if any(x in q for x in _analyze_keywords):
        stop = {"analyze", "rca", "why", "is", "my", "app", "diagnose", "investigate",
                "troubleshoot", "broken", "crashing", "failing", "the", "root", "cause",
                "of", "what", "wrong", "fix", "debug", "keeps", "restarting", "issue", "with"}
        target = extract_target(stop)
        # If no specific resource matched, default to the first known failing mock resource
        if not target:
            target = "payment-processor-0"
        return jsonify({'action': 'analyze', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'🔬 Running AI Root Cause Analysis on `{target}`...'})

    elif any(x in q for x in ["show all", "reset", "clear", "everything", "all pods"]):
        return jsonify({'action': 'reset', 'target': '', 'criteria': {}, 'count': None,
                        'message': '🔄 Showing all resources, filters cleared.'})

    # Only filter for explicit "list/show/get" style queries with no diagnostic intent
    elif any(x in q for x in ["show failed", "list failed", "get failed", "failed pods",
                               "show crashed", "crashloop", "show errors", "not working",
                               "what pods are", "which pods are"]):
        return jsonify({'action': 'filter', 'target': 'Pod',
                        'criteria': {'status': 'Failed'},
                        'count': None,
                        'message': '✨ Filtering for failed / crashing pods...'})

    elif any(x in q for x in ["running", "healthy", "ok pods", "show running"]):
        return jsonify({'action': 'filter', 'target': 'Pod',
                        'criteria': {'status': 'Running'},
                        'count': None,
                        'message': '✅ Showing only running pods...'})

    elif "pending" in q:
        return jsonify({'action': 'filter', 'target': 'Pod',
                        'criteria': {'status': 'Pending'},
                        'count': None,
                        'message': '⏳ Filtering for pending pods...'})

    elif "scale" in q or "replicas" in q or "increase" in q or "decrease" in q:
        m = re.search(r'(\d+)', q)
        count = int(m.group(1)) if m else 1
        stop = {"scale", "up", "down", "to", "replicas", "pods", "increase", "decrease", "the", "set"}
        target = extract_target(stop)
        return jsonify({'action': 'scale', 'target': target, 'count': count, 'criteria': {},
                        'message': f'🚀 Scaling `{target}` to {count} replica{"s" if count != 1 else ""}...'})

    elif any(x in q for x in ["log", "logs", "tail", "stdout"]):
        stop = {"show", "me", "get", "logs", "log", "for", "the", "fetch", "tail", "from"}
        target = extract_target(stop)
        return jsonify({'action': 'logs', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'📋 Opening logs for `{target}`...'})

    elif any(x in q for x in ["delete", "remove", "kill", "destroy"]):
        stop = {"delete", "remove", "kill", "destroy", "the", "pod", "deployment"}
        target = extract_target(stop)
        return jsonify({'action': 'delete', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'🗑️ Preparing to delete `{target}`...'})

    elif any(x in q for x in ["describe", "config", "env", "environment", "variables"]):
        stop = {"describe", "show", "get", "config", "env", "for", "the", "environment", "variables"}
        target = extract_target(stop)
        return jsonify({'action': 'describe', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'🔍 Opening config for `{target}`...'})

    elif any(x in q for x in ["restart", "rollout restart", "redeploy", "bounce"]):
        stop = {"restart", "rollout", "redeploy", "bounce", "the", "deployment", "statefulset"}
        target = extract_target(stop)
        return jsonify({'action': 'restart', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'♻️ Initiating rolling restart for `{target}`...'})

    elif any(x in q for x in ["events", "what happened", "history", "recent events"]):
        stop = {"events", "what", "happened", "to", "history", "recent", "for", "the", "show"}
        target = extract_target(stop)
        return jsonify({'action': 'events', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'📅 Showing recent events for `{target}`...'})

    elif "yaml" in q and not any(x in q for x in ["generator", "generate"]):
        stop = {"get", "show", "yaml", "for", "the", "definition"}
        target = extract_target(stop)
        return jsonify({'action': 'yaml', 'target': target, 'criteria': {}, 'count': None,
                        'message': f'📄 Fetching YAML for `{target}`...', 'reply': None})

    # ── Navigation ──────────────────────────────────────────────────────────
    elif any(x in q for x in ["go to optimizer", "open optimizer", "navigate to optimizer", "cost optimizer", "resource optimizer"]):
        return jsonify({'action': 'navigate', 'target': 'optimizer', 'criteria': {}, 'count': None,
                        'message': '💰 Opening Smart Resource Optimizer...', 'reply': None})

    elif any(x in q for x in ["go to security", "open security", "security scan", "navigate to security"]):
        return jsonify({'action': 'navigate', 'target': 'security', 'criteria': {}, 'count': None,
                        'message': '🛡️ Opening Security Scan...', 'reply': None})

    elif any(x in q for x in ["networking", "services", "ingress", "network tab"]):
        return jsonify({'action': 'navigate', 'target': 'networking', 'criteria': {}, 'count': None,
                        'message': '🌐 Switching to Networking view...', 'reply': None})

    elif any(x in q for x in ["yaml generator", "generate yaml"]):
        return jsonify({'action': 'navigate', 'target': 'yaml-gen', 'criteria': {}, 'count': None,
                        'message': '✨ Opening YAML Generator...', 'reply': None})

    # ── Cost & Optimization ─────────────────────────────────────────────────
    elif any(x in q for x in ["cost", "saving", "savings", "over-provision", "over provision",
                                "right-siz", "right siz", "cpu limit", "resource limit",
                                "monthly spend", "compute", "billing", "provisioned"]):
        return jsonify({'action': 'optimize', 'target': 'optimizer', 'criteria': {}, 'count': None,
                        'message': '💰 Running Smart Resource Optimizer — analysing cost and provisioning...', 'reply': None})

    # ── Security ────────────────────────────────────────────────────────────
    elif any(x in q for x in ["vulnerability", "vulnerabilities", "run as root", "root user",
                                "rbac", "privilege", "secret", "configmap secret",
                                "security posture", "compliance", "latest tag", ":latest"]):
        return jsonify({'action': 'security', 'target': 'security', 'criteria': {}, 'count': None,
                        'message': '🛡️ Running Security Scan — checking for vulnerabilities and misconfigurations...', 'reply': None})

    # ── Explain / Education ─────────────────────────────────────────────────
    elif any(x in q for x in ["what is", "what are", "explain", "how do i", "how to",
                                "what does", "difference between", "liveness probe",
                                "readiness probe", "statefulset", "daemonset", "namespace",
                                "oomkill", "imagepullbackoff", "requests vs", "limits",
                                "generate a", "create a deployment", "write a yaml"]):
        # Build targeted explanation for common topics
        explanations = {
            'oomkill': (
                "**OOMKilled** means the pod's container exceeded its memory `limit` and the Linux kernel's OOM killer terminated it.\n"
                "**Fix:** Increase the container memory limit (`resources.limits.memory`) or reduce heap/JVM settings.\n"
                "Check with: `kubectl describe pod <name>` and look for `OOMKilled` in the `Last State` section."
            ),
            'imagepullbackoff': (
                "**ImagePullBackOff** means Kubernetes cannot pull the container image.\n"
                "Common causes: wrong image name/tag, private registry without credentials (`imagePullSecrets`), or image doesn't exist.\n"
                "Debug: `kubectl describe pod <name>` → look at Events for the exact pull error."
            ),
            'requests vs': (
                "**Requests** = the CPU/memory Kubernetes *guarantees* to your pod (used for scheduling).\n"
                "**Limits** = the maximum your pod can use before it gets throttled (CPU) or killed (memory).\n"
                "**Best practice:** set requests ≈ actual average usage and limits ≈ 2× requests for headroom."
            ),
            'liveness probe': (
                "A **liveness probe** lets Kubernetes know if your container is healthy. If it fails, K8s restarts the container.\n"
                "Example in YAML:\n```yaml\nlivenessProbe:\n  httpGet:\n    path: /healthz\n    port: 8080\n  initialDelaySeconds: 15\n  periodSeconds: 10\n```\n"
                "Also consider a `readinessProbe` to control when traffic is sent to the pod."
            ),
            'statefulset': (
                "A **StatefulSet** gives pods stable network identities and persistent storage — unlike Deployments where pods are interchangeable.\n"
                "Use for: databases (PostgreSQL, MySQL, Redis), Kafka, Elasticsearch.\n"
                "Pods are named `my-sts-0`, `my-sts-1`, …, and are started/stopped in order."
            ),
            'namespace': (
                f"A **namespace** is a virtual cluster inside Kubernetes for isolating workloads.\n"
                f"Your current namespace is **{data.get('namespace','(unknown)')}**.\n"
                "Use `kubectl get all -n <namespace>` to see everything in a namespace."
            ),
            'generate a': (
                "Here's a minimal Deployment YAML:\n"
                "```yaml\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: my-app\nspec:\n  replicas: 2\n  selector:\n    matchLabels:\n      app: my-app\n  template:\n    metadata:\n      labels:\n        app: my-app\n    spec:\n      containers:\n      - name: my-app\n        image: nginx:1.25\n        ports:\n        - containerPort: 80\n        resources:\n          requests:\n            cpu: 100m\n            memory: 128Mi\n          limits:\n            cpu: 500m\n            memory: 256Mi\n```"
            ),
        }
        reply = next((v for k, v in explanations.items() if k in q), None)
        if not reply:
            reply = (
                f"I understood you're asking about: *\"{query}\".* \n"
                "As a Kubernetes AI assistant, I can explain any K8s concept — try asking about: "
                "OOMKilled, ImagePullBackOff, requests vs limits, liveness probes, StatefulSet vs Deployment, "
                "or ask me to generate a YAML template."
            )
        return jsonify({'action': 'explain', 'target': '', 'criteria': {}, 'count': None,
                        'message': '💡 AI answered your Kubernetes question.',
                        'reply': reply})

    elif "help" in q or "what can you" in q or "commands" in q:
        return jsonify({
            'action': 'explain', 'target': '', 'criteria': {}, 'count': None,
            'message': '🤖 Here\'s what I can do for you.',
            'reply': (
                "I'm your AI-powered Kubernetes assistant. I understand natural language — just type what you need:\n\n"
                "**Filter:** \"show failed pods\", \"list running deployments\"\n"
                "**Actions:** \"scale billing to 3\", \"restart frontend\", \"delete pod xyz\"\n"
                "**Diagnose:** \"why is payment crashing\", \"analyze checkout-service\"\n"
                "**Logs/Events:** \"show logs for api-gateway\", \"events for database\"\n"
                "**Cost:** \"what's my monthly compute cost\", \"which pods are over-provisioned\"\n"
                "**Security:** \"run a security scan\", \"which pods run as root\"\n"
                "**Explain:** \"what is OOMKilled\", \"explain requests vs limits\"\n"
                "**Navigate:** \"go to optimizer\", \"switch to networking\""
            )
        })

    else:
        return jsonify({
            'action': 'chat', 'target': '', 'criteria': {}, 'count': None,
            'message': f'🤖 AI: here\'s what I found.',
            'reply': (
                f"I interpreted your query as a general question about this namespace. "
                f"For \"**{query}**\" — I can help more specifically if you mention a resource name, action, or topic. "
                "Try: \"show failed pods\", \"why is payment crashing\", \"run security scan\", or \"explain OOMKilled\"."
            )
        })

@app.route('/api/ai/summarize_logs', methods=['POST'])
def summarize_logs():
    import time
    time.sleep(0.8)
    data = request.json or {}
    pod_name  = data.get('pod_name', '')
    logs_text = data.get('logs', '')
    source    = pod_name or 'provided log text'
    combined  = (pod_name + logs_text).lower()

    if 'payment' in combined or 'crash' in combined:
        summary = (
            f'Pod `{pod_name or "pod"}` is FAILING — CrashLoopBackOff due to database connectivity failure. '
            'The init container db-check cannot reach PostgreSQL at 10.0.0.5:5432, '
            'blocking the processor container from starting and causing a nil pointer panic on startup. '
            'The sidecar-proxy confirms the issue with an open circuit breaker on the payment-db cluster.'
        )
        errors = [
            'ConnectionRefused: cannot reach postgres at 10.0.0.5:5432 (init container db-check)',
            'panic: runtime error: nil pointer dereference in main.connectDB (processor)',
            'Circuit breaker OPEN for cluster payment-db (sidecar-proxy)',
        ]
        recommendations = [
            'kubectl get pod -l app=postgres — verify database is running',
            'kubectl describe pod ' + (pod_name or 'POD_NAME') + ' — check DB_HOST env var',
            'kubectl rollout restart deployment postgres — to recover database',
            'Add connection retry with exponential backoff in application code',
        ]
    elif 'oom' in combined or 'analytics' in combined or 'memory' in combined:
        summary = (
            f'Pod `{pod_name or "pod"}` is FAILED — OOMKilled by the kernel due to JVM heap exhaustion. '
            'The Spark job loaded a 48GB dataset into a 5GB JVM heap. At 91% utilization GC paused the JVM, '
            'and the OOM killer terminated the spark-driver container. The metrics-sidecar lost connection immediately after.'
        )
        errors = [
            'java.lang.OutOfMemoryError: Java heap space (spark-driver)',
            'JVM heap at 91% — GC pressure critical before OOM kill',
            'OOM killer terminated spark-driver process (exit signal 9)',
        ]
        recommendations = [
            'kubectl set resources deployment analytics-job --limits=memory=64Gi',
            'Set SPARK_DRIVER_MEMORY=16g and spark.memory.fraction=0.6',
            'Partition input dataset to reduce peak memory usage per task',
            'Add alert: jvm_heap_used_bytes > 85% of container memory limit',
        ]
    else:
        summary = (
            f'Pod `{source}` is HEALTHY — no errors or anomalies detected across all containers. '
            'All containers started successfully, health checks are passing, and no connection failures were observed.'
        )
        errors = []
        recommendations = ['No action required — all containers healthy.']

    return jsonify({
        'summary': summary,
        'errors': errors,
        'recommendations': recommendations,
        'critical_errors': errors,
        'gemini_powered': False,
        'containers_analyzed': max(1, combined.count('=== container:')),
    })

@app.route('/api/scale', methods=['POST'])
def scale_workload():
    import time
    time.sleep(0.4)
    data = request.json or {}
    action = data.get('action', 'set')
    target_name = data.get('name', '')
    kind = data.get('type', 'Deployment')
    count = data.get('count')

    global MOCK_SCALES
    if 'MOCK_SCALES' not in globals():
        MOCK_SCALES = {}

    # Default starting replicas matching mock data
    INITIAL_REPLICAS = {
        'frontend-deployment': 1, 'backend-api': 2, 'billing-service': 3,
        'ml-inference': 1, 'database-statefulset': 1, 'log-collector': 3,
    }
    default = INITIAL_REPLICAS.get(target_name, 1)
    current = MOCK_SCALES.get(target_name, default)

    if action == 'up':
        new_count = current + 1
    elif action == 'down':
        new_count = max(0, current - 1)
    elif action == 'set' and count is not None:
        new_count = int(count)
    else:
        new_count = current

    MOCK_SCALES[target_name] = new_count
    return jsonify({
        'message': f'Mock: Scaled {target_name} ({kind}) to {new_count} replicas',
        'new_replicas': new_count
    })

@app.route('/api/restart', methods=['POST'])
def restart_workload():
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('type', 'Deployment')
    return jsonify({'message': f'Mock: Rolling restart triggered for {kind} {name}. New pods will be ready in ~30s.'})


@app.route('/api/events/<name>')
def get_resource_events(name):
    timestamp = datetime.utcnow().isoformat() + "Z"
    events = [
        {'type': 'Normal', 'reason': 'Scheduled', 'message': f'Successfully assigned default/{name} to node-1', 'count': 1, 'last_timestamp': timestamp},
        {'type': 'Normal', 'reason': 'Pulling', 'message': 'Pulling image "my-app:latest"', 'count': 1, 'last_timestamp': timestamp},
        {'type': 'Normal', 'reason': 'Started', 'message': 'Started container main', 'count': 1, 'last_timestamp': timestamp}
    ]
    if 'crash' in name:
        events.append({'type': 'Warning', 'reason': 'BackOff', 'message': 'Back-off restarting failed container', 'count': 5, 'last_timestamp': timestamp})
    
    return jsonify({'events': events})

@app.route('/api/yaml/<name>')
def get_resource_yaml(name):
    """Return a realistic YAML manifest for any resource by looking up actual mock data."""
    kind = request.args.get('type', 'Pod')
    ns = request.args.get('namespace', 'default')
    prefix = f"{ns}-" if ns != 'default' else ""

    # ── Look up from services ──
    if kind == 'Service':
        svc_data = [
            {'name': 'frontend', 'type': 'LoadBalancer', 'cluster_ip': '10.0.0.1', 'ports': '80:3000'},
            {'name': 'backend-api', 'type': 'ClusterIP', 'cluster_ip': '10.0.0.2', 'ports': '8080'},
            {'name': 'database-svc', 'type': 'ClusterIP', 'cluster_ip': '10.0.0.3', 'ports': '5432'},
        ]
        svc = next((s for s in svc_data if s['name'] == name), None)
        if svc:
            port_str = svc['ports']
            port_parts = port_str.split(':')
            port = int(port_parts[0])
            target_port = int(port_parts[1]) if len(port_parts) > 1 else port
            mock_yaml = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": svc['name'], "namespace": ns, "labels": {"app": svc['name']}},
                "spec": {
                    "type": svc['type'],
                    "selector": {"app": svc['name']},
                    "ports": [{"port": port, "targetPort": target_port, "protocol": "TCP"}],
                    "clusterIP": svc['cluster_ip'],
                }
            }
            return jsonify({'yaml': mock_yaml})

    # ── Look up from virtualservices ──
    if kind == 'VirtualService':
        mock_yaml = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {"name": name, "namespace": ns},
            "spec": {
                "hosts": [name.replace('-vs', '')],
                "gateways": ["istio-ingressgateway"],
                "http": [{"route": [{"destination": {"host": name.replace('-vs', ''), "port": {"number": 8080}}, "weight": 100}]}]
            }
        }
        return jsonify({'yaml': mock_yaml})

    # ── Look up from workloads (Deployment, StatefulSet, DaemonSet, Pod, Job, ConfigMap, Secret) ──
    # Build workloads list (simplified — no request context for get_workloads)
    workloads = []
    deployments = [
        {'name': f'{prefix}frontend-deployment', 'image': 'frontend:v2.4.1', 'replicas': 1, 'labels': {'app': 'frontend', 'chart': 'frontend-1.8.0', 'team': 'platform'}},
        {'name': f'{prefix}backend-api', 'image': 'backend-api:v3.1.2', 'replicas': 2, 'labels': {'app': 'backend-api', 'chart': 'backend-2.5.0', 'team': 'core'}},
        {'name': f'{prefix}billing-service', 'image': 'billing-service:v1.12.0', 'replicas': 3, 'labels': {'app': 'billing', 'chart': 'billing-3.1.0', 'team': 'finance'}},
        {'name': f'{prefix}ml-inference', 'image': 'ml-inference:v0.9.5-beta', 'replicas': 1, 'labels': {'app': 'ml-inference', 'chart': 'ml-inference-0.3.2', 'team': 'ml'}},
    ]

    # Check for scaling overrides
    global MOCK_SCALES
    if 'MOCK_SCALES' not in globals():
        MOCK_SCALES = {}

    if kind in ('Deployment', 'StatefulSet', 'DaemonSet'):
        dep = next((d for d in deployments if d['name'] == name), None)
        replicas = MOCK_SCALES.get(name, dep['replicas'] if dep else 1)
        image = dep['image'] if dep else f'{name.split("-")[0]}:latest'
        labels = dep.get('labels', {'app': name.split('-')[0]}) if dep else {'app': name.split('-')[0]}

        api_version = "apps/v1"
        if kind == 'StatefulSet':
            image = 'postgres:15.4'
            labels = {'app': 'database', 'component': 'postgresql'}

        mock_yaml = {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": {"name": name, "namespace": ns, "labels": labels},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": {"app": labels.get('app', name.split('-')[0])}},
                "template": {
                    "metadata": {"labels": {"app": labels.get('app', name.split('-')[0])}},
                    "spec": {
                        "containers": [{
                            "name": "main",
                            "image": image,
                            "ports": [{"containerPort": 8080}],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"}
                            },
                            "env": [
                                {"name": "APP_ENV", "value": ns},
                                {"name": "LOG_LEVEL", "value": "info"},
                            ]
                        }]
                    }
                }
            }
        }
        return jsonify({'yaml': mock_yaml})

    if kind == 'Pod':
        # Find matching pod
        pod_containers = {
            'frontend-pod-1': [{'name': 'nginx', 'image': 'frontend:v2.4.1'}],
            'backend-pod-multi': [{'name': 'api-server', 'image': 'backend-api:v3.1.2'}, {'name': 'sidecar-proxy', 'image': 'envoy:v1.28'}],
            'payment-processor-0': [{'name': 'processor', 'image': 'payment-service:v2.0.1'}],
            'analytics-job-oom': [{'name': 'spark-driver', 'image': 'spark:3.5.0'}],
            'sidecar-missing': [{'name': 'main', 'image': 'app:v1.0'}, {'name': 'sidecar', 'image': 'invalid-registry/sidecar:missing'}],
            'api-gateway-v2': [{'name': 'gateway', 'image': 'api-gateway:v2.0.0-rc1'}],
            'init-demo-pod': [{'name': 'app', 'image': 'demo-app:latest'}],
        }
        short_name = name.replace(prefix, '')
        containers = pod_containers.get(short_name, [{'name': 'main', 'image': f'{name}:latest'}])
        mock_yaml = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "namespace": ns, "labels": {"app": short_name.split('-')[0]}},
            "spec": {
                "containers": [{
                    "name": c['name'],
                    "image": c['image'],
                    "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "512Mi"}},
                } for c in containers]
            }
        }
        return jsonify({'yaml': mock_yaml})

    if kind == 'ConfigMap':
        cm_data = {
            'app-config': {"DATABASE_URL": "postgresql://db:5432/app", "CACHE_TTL": "300", "LOG_LEVEL": "info", "MAX_CONNECTIONS": "50"},
            'nginx-config': {"nginx.conf": "server { listen 80; location / { proxy_pass http://backend:8080; } }"},
        }
        short_name = name.replace(prefix, '')
        mock_yaml = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": ns},
            "data": cm_data.get(short_name, {"config.yaml": "key: value"})
        }
        return jsonify({'yaml': mock_yaml})

    if kind == 'Secret':
        mock_yaml = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": ns},
            "type": "Opaque",
            "data": {"username": "YWRtaW4=", "password": "c3VwZXItc2VjcmV0LXBhc3N3b3Jk"}
        }
        return jsonify({'yaml': mock_yaml})

    if kind == 'Job':
        mock_yaml = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "namespace": ns},
            "spec": {
                "completions": 1,
                "parallelism": 1,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [{"name": "job", "image": f"{name.split('-')[0]}-runner:latest", "command": ["python", "run.py"]}]
                    }
                }
            }
        }
        return jsonify({'yaml': mock_yaml})

    # Fallback
    mock_yaml = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": ns},
        "spec": {}
    }
    return jsonify({'yaml': mock_yaml})

@app.route('/api/ai/analyze_logs', methods=['POST'])
def mock_analyze_logs():
    data = request.json
    pod_name = data.get('pod_name')
    # Simulate processing time
    import time
    time.sleep(1.5)
    return jsonify({
        'analysis': f"""## AI Analysis for {pod_name} ♊
        
**Root Cause**: The application failed to connect to the database.
**Error Pattern**: `ConnectionRefusedError: [Errno 111] Connection refused` found in `main` container logs.

**Recommended Fix**:
1. Check if the `database-statefulset` is running.
2. Verify the `DB_HOST` environment variable in `{pod_name}` matches the service DNS `database-service`.
3. Ensure network policies allow traffic on port 5432.
"""
    })

@app.route('/api/ai/chat', methods=['POST'])
def mock_chat():
    data = request.json
    message = data.get('message', '')
    import time
    time.sleep(1.0)
    
    response = f"I am a Mock AI Agent. You asked: '{message}'.\n\nI can help you analyze logs or check resource status."
    
    if "why" in message.lower() or "error" in message.lower():
        response = """**Potential Issue Detected** ⚠️
        
Based on the cluster state, I see that **payment-processor-0** is in `CrashLoopBackOff`.
This is likely due to a missing secret `stripe-api-key`.
"""
    return jsonify({'response': response})




@app.route('/api/delete', methods=['POST'])
def delete_resource():
    import time
    time.sleep(0.5)
    return jsonify({'message': f"Mock: Deleted resource"})

@app.route('/api/ai/rca', methods=['POST'])
def ai_rca():
    """Mock AI-powered RCA. Returns structured SRE-quality analysis
    matching the exact output format of the real Gemini endpoint.
    """
    import time
    time.sleep(1.5)  # simulate Gemini latency

    data = request.json
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    name   = data.get('name', 'unknown')
    kind   = data.get('type', 'Deployment')
    status = data.get('status', '')
    combined = (name + status).lower()

    if status == 'CrashLoopBackOff' or 'payment' in combined or 'crash' in combined:
        analysis = f"""## 🚨 Root Cause
`{name}` is in **CrashLoopBackOff** because the application cannot establish a connection to the PostgreSQL database. The pod repeatedly starts, fails immediately on DB connect, and is killed — evidenced by `ConnectionRefusedError (10.0.0.5:5432)` in the first 2 seconds of every container start.

## 🔍 Evidence
- `[ERROR] ConnectionRefusedError: [Errno 111] Connection refused (10.0.0.5:5432)` — main container log, line 1
- `[K8s Event] BackOff: Back-off restarting failed container (x8 in 12m)`
- `[K8s Event] Killing: Container main failed liveness probe, will be restarted`
- Init container `db-migration` exited 0 — schema is not the issue
- `database-statefulset` pod shows `0/1 Ready` — database itself is down

## 💥 Impact
- **Payment processing is fully offline** — all checkout requests are failing with 503
- `payment-processor-0` has restarted 8 times in the last 12 minutes
- Downstream `order-service` is accumulating retries and approaching its own circuit breaker threshold

## ✅ Remediation Steps
1. `kubectl rollout restart statefulset/database-statefulset -n {data.get('namespace','default')}` — recover the database pod
2. Verify `DB_HOST` env var: `kubectl get deploy {name} -o jsonpath='{{.spec.template.spec.containers[0].env}}'`
3. Once DB is up, `{name}` will self-heal — monitor with: `kubectl get pods -w -l app={name.split('-')[0]}`
4. If DB is healthy but connection still fails, check NetworkPolicy: `kubectl get networkpolicy -n {data.get('namespace','default')}`

## 🛡️ Prevention
1. Add a **liveness probe** with an appropriate `initialDelaySeconds` (≥30s) so K8s doesn't kill the container before DB is ready
2. Add a **readiness probe** with `failureThreshold: 3` to gate traffic until DB connection is confirmed healthy"""

    elif status == 'OOMKilled' or 'oom' in combined or 'analytics' in combined:
        analysis = f"""## 🚨 Root Cause
`{name}` was **OOMKilled** by the Linux kernel OOM killer. The JVM heap grew beyond the container memory limit of `1Gi` when processing a large dataset, causing the container to be forcibly terminated. The JVM flag `-Xmx512m` is set far below the container limit, indicating the JVM can allocate native memory beyond heap that pushes total RSS over the limit.

## 🔍 Evidence
- `[WARN] Memory usage at 85%` — seen 4 minutes before kill
- `[ERROR] java.lang.OutOfMemoryError: Java heap space` — JVM heap exhausted
- `[KERN] cgroup out of memory: Kill process 4821 (java) score 999 or sacrifice child` — OOM killer log
- K8s Event: `OOMKilling: Memory cgroup out of memory: Killed process 4821`
- Container limit: `1Gi` | RSS at kill: `~1.1Gi`

## 💥 Impact
- Batch analytics job has failed mid-execution — data pipeline is stalled
- Downstream reporting dashboards will show stale data until the job completes
- Job has been retried 3 times — each run costs ~5 min of wasted compute

## ✅ Remediation Steps
1. Increase container memory limit: set `resources.limits.memory: 2Gi` in Deployment spec
2. Align JVM heap: add env var `JAVA_OPTS=-Xmx1536m -Xms512m`
3. Apply the change: `kubectl rollout restart deployment/{name} -n {data.get('namespace','default')}`
4. Long-term: partition input dataset into smaller chunks to reduce peak memory

## 🛡️ Prevention
1. Set `resources.requests.memory == resources.limits.memory` (Guaranteed QoS) so the kernel prefers to kill other pods first
2. Add a **memory usage alert** at 80% of limit using Prometheus `container_memory_working_set_bytes`"""

    elif status == 'ImagePullBackOff' or status == 'ErrImagePull':
        analysis = f"""## 🚨 Root Cause
`{name}` cannot start because Kubernetes cannot pull the container image. The image tag does not exist in the registry — either a bad tag was pushed, or the deployment was updated with a non-existent version.

## 🔍 Evidence
- `[K8s Event] Failed: Error response from daemon: manifest for registry/app:v99 not found: manifest unknown`
- `[K8s Event] BackOff: Back-off pulling image "registry/app:v99"`
- `kubectl describe pod` shows `ImagePullBackOff` under `Reason`

## 💥 Impact
- New pods cannot start — rolling update is stuck
- Previous replica set is still running (old version still serving traffic)
- No user impact yet, but deployment is blocked

## ✅ Remediation Steps
1. Check available tags: `docker manifest inspect registry/app:<tag>` or check your registry UI
2. Rollback immediately: `kubectl rollout undo deployment/{name} -n {data.get('namespace','default')}`
3. Fix the image tag in your deployment pipeline and re-deploy

## 🛡️ Prevention
1. Use **image digest pinning** (`image: registry/app@sha256:...`) instead of mutable tags
2. Add an image existence check to your CI/CD pipeline before triggering a rolling update"""

    elif status == 'Pending':
        analysis = f"""## 🚨 Root Cause
`{name}` pods are stuck in **Pending** because no node in the cluster has sufficient CPU to satisfy the pod's resource requests. The scheduler cannot place the pod.

## 🔍 Evidence
- `[K8s Event] FailedScheduling: 0/3 nodes are available: 3 Insufficient cpu, 1 node(s) had untolerated taint`
- Pod resource request: `cpu: 2000m` — all nodes have < 2 vCPU available
- `kubectl top nodes` shows all nodes at >85% CPU utilization

## 💥 Impact
- Deployment rollout is blocked — new version is not serving traffic
- If this is a scale-up event, the service may be under-provisioned under high load

## ✅ Remediation Steps
1. Add a node to the cluster, or enable cluster autoscaler if not already active
2. Temporarily reduce CPU request: `resources.requests.cpu: 500m` to unblock scheduling
3. Check for resource quota limits: `kubectl describe resourcequota -n {data.get('namespace','default')}`

## 🛡️ Prevention
1. Set a **PodDisruptionBudget** and configure cluster autoscaler with scale-up triggers
2. Review and right-size resource requests based on actual p99 usage from Prometheus metrics"""

    else:
        analysis = f"""## 🚨 Root Cause
No critical issues detected. `{name}` ({kind}) is currently in `{status}` state and appears to be operating normally.

## 🔍 Evidence
- All containers passed readiness and liveness probes
- No Error or Fatal log lines found across any container
- No abnormal K8s events in the last 30 minutes
- Resource usage within normal bounds

## 💥 Impact
No user-facing impact detected.

## ✅ Remediation Steps
No immediate action required. Continue monitoring.

## 🛡️ Prevention
1. Ensure readiness and liveness probes are configured for all containers
2. Set up alerting on pod restarts > 3 in 10 minutes"""

    return jsonify({'analysis': analysis})





@app.route('/api/ai/security_scan')
def security_scan():
    """Mock AI-powered comprehensive security audit.
    Returns rich findings across all 9 categories matching the real endpoint schema.
    """
    import time
    time.sleep(1.8)  # simulate Gemini latency

    risks = [
        # ── Pod Security ──────────────────────────────────────────────────────
        {
            "severity": "Critical",
            "category": "Pod Security",
            "resource": "database-statefulset",
            "kind": "StatefulSet",
            "issue": "Container 'postgres' runs as root (runAsUser=0, runAsNonRoot not set)",
            "remediation": "Set securityContext.runAsUser: 999 and securityContext.runAsNonRoot: true",
            "cve_references": ["CIS-5.2.6"],
            "ai_insight": "Root containers can escape to the host if paired with other misconfigurations like hostPath mounts."
        },
        {
            "severity": "Critical",
            "category": "Pod Security",
            "resource": "log-collector-daemonset",
            "kind": "DaemonSet",
            "issue": "Container 'fluentd' is privileged (securityContext.privileged: true)",
            "remediation": "Remove securityContext.privileged: true; use specific capabilities instead",
            "cve_references": ["CIS-5.2.1"],
            "ai_insight": "Privileged DaemonSet containers run on every node and have full host access — a critical blast radius."
        },
        {
            "severity": "High",
            "category": "Pod Security",
            "resource": "frontend-deployment",
            "kind": "Deployment",
            "issue": "Container 'nginx' missing allowPrivilegeEscalation: false",
            "remediation": "Add securityContext.allowPrivilegeEscalation: false to container spec",
            "cve_references": ["CIS-5.2.5"],
            "ai_insight": "Without this flag, a compromised process can gain additional privileges via setuid binaries."
        },
        {
            "severity": "High",
            "category": "Pod Security",
            "resource": "analytics-worker",
            "kind": "Deployment",
            "issue": "Container 'spark-driver' missing readOnlyRootFilesystem: true",
            "remediation": "Add securityContext.readOnlyRootFilesystem: true; mount writable tmpfs for /tmp",
            "cve_references": ["CIS-5.2.7"],
            "ai_insight": "A writable root filesystem lets an attacker persist malware or modify app binaries at runtime."
        },
        # ── Network Policy ────────────────────────────────────────────────────
        {
            "severity": "High",
            "category": "Network Policy",
            "resource": "default (namespace)",
            "kind": "Namespace",
            "issue": "No NetworkPolicy found — all pod-to-pod and pod-to-internet traffic is unrestricted",
            "remediation": "Create a default-deny NetworkPolicy then allowlist required flows",
            "cve_references": ["CIS-5.3.2", "NSA-Section-5"],
            "ai_insight": "Without NetworkPolicy, a compromised pod can freely reach any service or exfiltrate data to the internet."
        },
        # ── RBAC ──────────────────────────────────────────────────────────────
        {
            "severity": "High",
            "category": "RBAC",
            "resource": "default",
            "kind": "ServiceAccount",
            "issue": "Default ServiceAccount has automountServiceAccountToken: true — all pods inherit a valid API token",
            "remediation": "Set automountServiceAccountToken: false on the default ServiceAccount; create dedicated SAs per workload",
            "cve_references": ["CIS-5.1.6"],
            "ai_insight": "Any compromised pod can use the mounted token to query or modify the Kubernetes API."
        },
        {
            "severity": "Critical",
            "category": "RBAC",
            "resource": "ci-pipeline-binding",
            "kind": "RoleBinding",
            "issue": "RoleBinding grants cluster-admin to ServiceAccount 'ci-runner' — wildcard (*) on all resources",
            "remediation": "Scope to specific verbs/resources: e.g. get/list/update on deployments only",
            "cve_references": ["CIS-5.1.1"],
            "ai_insight": "cluster-admin grants full control; a compromised CI runner can delete or exfiltrate any cluster resource."
        },
        # ── Image Security ────────────────────────────────────────────────────
        {
            "severity": "High",
            "category": "Image Security",
            "resource": "frontend-deployment",
            "kind": "Deployment",
            "issue": "Container 'nginx' uses image tag 'latest' (nginx:latest) — mutable tag",
            "remediation": "Pin to an immutable digest: nginx@sha256:<digest>",
            "cve_references": ["CIS-5.4.1"],
            "ai_insight": "The 'latest' tag can silently introduce breaking changes or malicious layers on the next pull."
        },
        {
            "severity": "Medium",
            "category": "Image Security",
            "resource": "analytics-worker",
            "kind": "Deployment",
            "issue": "Image 'spark:3.4' pulled from Docker Hub (no registry prefix) — unauthenticated public registry",
            "remediation": "Mirror to your private registry and use the full registry path: registry.internal/spark:3.4",
            "cve_references": ["CIS-5.4.2"],
            "ai_insight": "Docker Hub rate limits and namespace squatting attacks make unregistered images a supply chain risk."
        },
        # ── Resource Management ───────────────────────────────────────────────
        {
            "severity": "Medium",
            "category": "Resource Management",
            "resource": "checkout-service",
            "kind": "Deployment",
            "issue": "Container 'app' missing CPU and memory limits",
            "remediation": "Set resources.limits.cpu: '500m' and resources.limits.memory: '256Mi'",
            "cve_references": ["CIS-5.2.5"],
            "ai_insight": "Unlimited containers can consume all node resources, causing OOM kills on co-located pods."
        },
        {
            "severity": "Low",
            "category": "Resource Management",
            "resource": "api-gateway",
            "kind": "Deployment",
            "issue": "Container 'envoy' missing resource requests — scheduler cannot make optimal placement decisions",
            "remediation": "Set resources.requests.cpu: '100m' and resources.requests.memory: '128Mi'",
            "cve_references": ["CIS-5.2.5"],
            "ai_insight": "Without requests, the scheduler may overcommit nodes leading to eviction storms under load."
        },
        # ── Availability ──────────────────────────────────────────────────────
        {
            "severity": "Medium",
            "category": "Availability",
            "resource": "payment-processor",
            "kind": "Deployment",
            "issue": "Single replica (replicas: 1) — no high availability, any node restart causes downtime",
            "remediation": "Set replicas: 2 minimum; add a PodDisruptionBudget with minAvailable: 1",
            "cve_references": ["NSA-Section-3"],
            "ai_insight": "Single-replica critical workloads create a single point of failure for payment flows."
        },
        {
            "severity": "Low",
            "category": "Availability",
            "resource": "api-gateway",
            "kind": "Deployment",
            "issue": "Container 'envoy' missing readinessProbe — traffic may be routed before the app is ready",
            "remediation": "Add readinessProbe with httpGet on /healthz and failureThreshold: 3",
            "cve_references": ["CIS-5.2.x"],
            "ai_insight": "Without a readiness probe, Kubernetes sends traffic during startup before the proxy is initialised."
        },
        # ── ConfigMap Security ────────────────────────────────────────────────
        {
            "severity": "High",
            "category": "ConfigMap Security",
            "resource": "app-config",
            "kind": "ConfigMap",
            "issue": "ConfigMap 'app-config' contains key 'db_password' — sensitive values must use Kubernetes Secrets",
            "remediation": "Move to a Secret and mount via env.valueFrom.secretKeyRef or volumeMount",
            "cve_references": ["CIS-5.4.1", "NSA-Section-4"],
            "ai_insight": "ConfigMaps are stored in etcd without encryption and visible to anyone with 'kubectl get cm' access — never store credentials here."
        },
        {
            "severity": "High",
            "category": "ConfigMap Security",
            "resource": "tls-config",
            "kind": "ConfigMap",
            "issue": "ConfigMap 'tls-config' contains key 'private_key' — TLS private keys must not be stored in ConfigMaps",
            "remediation": "Use a Secret of type kubernetes.io/tls created by cert-manager or kubectl create secret tls",
            "cve_references": ["CIS-5.4.1"],
            "ai_insight": "Private keys in ConfigMaps are accessible to any pod in the namespace via volume mounts without RBAC restriction on Secret resources."
        },
        # ── Secrets Management ────────────────────────────────────────────────
        {
            "severity": "High",
            "category": "Secrets Management",
            "resource": "database-statefulset",
            "kind": "StatefulSet",
            "issue": "Container 'postgres' has DB_PASSWORD passed as plaintext env var (not from secretKeyRef)",
            "remediation": "Use env.valueFrom.secretKeyRef referencing a Kubernetes Secret; encrypt etcd at rest",
            "cve_references": ["CIS-5.4.1", "NSA-Section-4"],
            "ai_insight": "Plaintext secrets in pod specs are visible to anyone with 'kubectl get pod -o yaml' access."
        },
        {
            "severity": "Medium",
            "category": "Secrets Management",
            "resource": "app-secrets",
            "kind": "Secret",
            "issue": "Opaque Secret 'app-secrets' contains 9 keys — overloaded secrets violate least-privilege (all-or-nothing access)",
            "remediation": "Split into scoped Secrets (e.g. db-credentials, api-keys) with separate RBAC policies",
            "cve_references": ["CIS-5.4.1"],
            "ai_insight": "A single overloaded Secret means any pod granted access gets all credentials, widening the blast radius of a compromise."
        },
    ]

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for r in risks:
        severity_counts[r["severity"]] = severity_counts.get(r["severity"], 0) + 1

    total = len(risks)
    critical = severity_counts["Critical"]
    high = severity_counts["High"]

    return jsonify({
        "executive_summary": (
            f"The namespace has {total} security findings including {critical} Critical and {high} High severity issues. "
            "The most urgent concerns are a privileged DaemonSet with full host access, a cluster-admin RoleBinding granted to the CI ServiceAccount, and a database container running as root with a plaintext password in its environment. "
            "No NetworkPolicy is applied, leaving all pod-to-pod communication unrestricted."
        ),
        "severity_counts": severity_counts,
        "risks": risks
    })



@app.route('/api/pods/<name>/containers')
def mock_get_pod_containers(name):
    """Return mock containers for a pod — used by the console container selector."""
    # Mock containers based on pod name patterns
    if 'multi' in name or 'backend' in name:
        containers = [
            {'name': 'app', 'image': 'backend-service:v2.1.0'},
            {'name': 'sidecar-proxy', 'image': 'envoy:v1.27.0'},
            {'name': 'log-collector', 'image': 'fluentbit:2.2.0'},
        ]
    elif 'payment' in name or 'processor' in name:
        containers = [
            {'name': 'processor', 'image': 'payment-processor:v1.8.3'},
            {'name': 'sidecar-proxy', 'image': 'envoy:v1.27.0'},
        ]
    else:
        containers = [{'name': name.split('-')[0], 'image': f'{name.split("-")[0]}:latest'}]
    return jsonify({'containers': containers})


@app.route('/api/pods/<name>/logs')
def get_pod_logs(name):
    # Mock Logs
    if 'crash' in name or 'payment' in name:
        return jsonify({'logs': "[INFO] Starting application...\n[INFO] Connecting to DB...\n[ERROR] ConnectionRefused: Failed to connect to DB at 10.0.0.5:5432\n[FATAL] panic: runtime error: invalid memory address or nil pointer dereference\n"})
    elif 'oom' in name:
        return jsonify({'logs': "[INFO] Spark Driver starting...\n[INFO] Loading dataset...\n[WARN] Memory usage at 90%\n[ERROR] java.lang.OutOfMemoryError: Java heap space\n[INFO] Shutting down...\n"})
    else:
        return jsonify({'logs': "[INFO] Application started successfully.\n[INFO] Listening on port 8080.\n[INFO] Health check passed.\n"})


@app.route('/api/pods/<name>/all_logs')
def get_pod_all_logs(name):
    ns = request.args.get('namespace', 'default')
    if 'payment' in name or 'crash' in name:
        containers = {
            '[init] db-check': (
                '[INFO]  2026-02-20T14:00:01Z Init container starting\n'
                '[INFO]  2026-02-20T14:00:02Z Checking database connectivity at 10.0.0.5:5432\n'
                '[ERROR] 2026-02-20T14:00:05Z ConnectionRefused: cannot reach postgres at 10.0.0.5:5432\n'
                '[WARN]  2026-02-20T14:00:05Z Retrying in 5s (attempt 1/3)\n'
                '[ERROR] 2026-02-20T14:00:10Z ConnectionRefused: cannot reach postgres at 10.0.0.5:5432\n'
                '[FATAL] 2026-02-20T14:00:15Z All retries exhausted, init container failed\n'
            ),
            'processor': (
                '[INFO]  2026-02-20T14:00:16Z Payment processor starting\n'
                '[FATAL] 2026-02-20T14:00:20Z panic: nil pointer dereference in main.connectDB\n'
                '[INFO]  2026-02-20T14:00:21Z Container exiting with code 1\n'
            ),
            'sidecar-proxy': (
                '[INFO]  2026-02-20T14:00:01Z Envoy proxy starting\n'
                '[WARN]  2026-02-20T14:00:05Z Upstream 10.0.0.5:5432 health check failed\n'
                '[ERROR] 2026-02-20T14:00:10Z Circuit breaker OPEN for cluster payment-db\n'
            ),
        }
    elif 'oom' in name or 'analytics' in name:
        containers = {
            'spark-driver': (
                '[INFO]  2026-02-20T09:00:00Z Spark Driver v3.4 starting\n'
                '[INFO]  2026-02-20T09:00:05Z Loading dataset: gs://data/events-20260219.parquet (48GB)\n'
                '[WARN]  2026-02-20T09:08:00Z JVM heap usage at 91% - GC pressure high\n'
                '[ERROR] 2026-02-20T09:10:00Z java.lang.OutOfMemoryError: Java heap space\n'
                '[ERROR] 2026-02-20T09:10:00Z     at org.apache.spark.sql.execution.columnar.DefaultCachedBatch\n'
                '[INFO]  2026-02-20T09:10:01Z JVM killed by OOM killer\n'
            ),
            'metrics-sidecar': (
                '[INFO]  2026-02-20T09:00:00Z Prometheus metrics exporter starting on :9090\n'
                '[WARN]  2026-02-20T09:08:00Z jvm_gc_pause_seconds_sum increasing rapidly\n'
                '[ERROR] 2026-02-20T09:10:01Z Lost connection to spark-driver (container stopped)\n'
            ),
        }
    elif 'sidecar-missing' in name:
        containers = {
            'main': (
                '[INFO]  2026-02-20T14:30:00Z Application started, waiting for sidecar\n'
                '[WARN]  2026-02-20T14:30:30Z Sidecar not ready after 30s, proceeding without it\n'
                '[INFO]  2026-02-20T14:30:31Z Server listening on :8080\n'
            ),
            'sidecar': (
                '[ERROR] ImagePullBackOff: Failed to pull image myregistry.io/sidecar:v2.1-beta\n'
                '[ERROR] rpc error: code=Unknown desc=failed to pull: unexpected status code 401 Unauthorized\n'
                '[WARN]  Back-off pulling image myregistry.io/sidecar:v2.1-beta\n'
            ),
        }
    elif 'init' in name:
        containers = {
            '[init] setup': (
                '[INFO]  2026-02-20T13:00:00Z Running schema migration (flyway)\n'
                '[INFO]  2026-02-20T13:00:05Z Successfully validated 12 migrations\n'
                '[INFO]  2026-02-20T13:00:07Z Applied migration version 2.4.1 successfully\n'
            ),
            'app': (
                '[INFO]  2026-02-20T13:00:12Z Init completed - booting application\n'
                '[INFO]  2026-02-20T13:00:14Z Connected to DB (schema v2.4.1)\n'
                '[INFO]  2026-02-20T13:00:15Z Server ready on :3000\n'
            ),
        }
    elif 'backend' in name or 'multi' in name:
        containers = {
            'api-server': (
                '[INFO]  2026-02-20T14:00:00Z FastAPI server starting (uvicorn 0.21)\n'
                '[INFO]  2026-02-20T14:00:01Z Connected to Redis at redis:6379\n'
                '[INFO]  2026-02-20T14:00:02Z Connected to PostgreSQL at postgres:5432\n'
                '[INFO]  2026-02-20T14:00:04Z Application ready. Listening on 0.0.0.0:8000\n'
                '[INFO]  2026-02-20T14:10:00Z POST /api/v1/process -> 200 (145ms)\n'
            ),
            'sidecar-proxy': (
                '[INFO]  2026-02-20T14:00:00Z Envoy proxy v1.28 starting\n'
                '[INFO]  2026-02-20T14:00:01Z Cluster local_service (127.0.0.1:8000) healthy\n'
                '[INFO]  2026-02-20T14:10:00Z 200 POST /api/v1/process (148ms)\n'
            ),
        }
    else:
        containers = {
            'nginx': (
                '[INFO]  2026-02-20T14:00:00Z nginx/1.25.3 starting\n'
                '[INFO]  2026-02-20T14:00:01Z Listening on 0.0.0.0:80 and 0.0.0.0:443\n'
                '[INFO]  2026-02-20T14:01:00Z 200 GET / (1ms)\n'
                '[INFO]  2026-02-20T14:02:00Z 200 GET /api/health (0ms)\n'
            ),
        }
    return jsonify({'containers': containers, 'pod': name})

@app.route('/api/workloads/env')
def get_workload_env():
    # Mock Env Vars — rich realistic data for demo
    name = request.args.get('name', 'unknown')
    w_type = request.args.get('type', 'Deployment')
    return jsonify({
        'env': [
            {'container': 'main', 'name': 'DB_HOST',        'value': '10.0.0.3'},
            {'container': 'main', 'name': 'DB_PORT',        'value': '5432'},
            {'container': 'main', 'name': 'DB_PASSWORD',    'value': 'postgres123'},  # plaintext!
            {'container': 'main', 'name': 'LOG_LEVEL',      'value': 'DEBUG'},
            {'container': 'main', 'name': 'APP_ENV',        'value': 'production'},
            {'container': 'main', 'name': 'MAX_RETRIES',    'value': '3'},
            {'container': 'main', 'name': 'API_KEY',        'value': 'Secret: api-keys (key: api-key)'},
            {'container': 'sidecar', 'name': 'METRICS_PORT', 'value': '9090'},
            {'container': 'sidecar', 'name': 'TRACE_ENABLED', 'value': 'true'},
        ],
        'config_maps': ['app-config', 'feature-flags'],
        'secrets': ['db-creds', 'api-keys']
    })

@app.route('/api/secrets/<name>')
def get_secret(name):
    # Mock Secret Content
    return jsonify({
        'data': {
            'username': 'admin',
            'password': 'super-secret-password-decoded',
            'api-key': 'sk-prod-abc123xyz789'
        }
    })

@app.route('/api/configmaps/<name>')
def get_configmap(name):
    import json as _json
    configs = {
        'app-config': {
            'DATABASE_URL': 'postgresql://app:postgres123@10.0.0.3:5432/appdb',
            'MAX_CONNECTIONS': '20',
            'TIMEOUT_SECONDS': '30',
            'ENABLE_CACHE': 'true',
        },
        'feature-flags': {
            'enable_new_checkout': 'true',
            'enable_beta_ui': 'false',
            'dark_mode_default': 'true',
        }
    }
    return jsonify({'data': configs.get(name, {'key': 'value', 'setting': 'example'})})

@app.route('/api/ai/describe_workload', methods=['POST'])
def describe_workload_ai():
    """Mock AI-powered workload config analysis."""
    import time
    time.sleep(1.0)
    data = request.json or {}
    name     = data.get('name', 'unknown')
    kind     = data.get('kind', 'Deployment')
    ns       = data.get('namespace', 'default')
    env_vars = data.get('env', [])
    secrets  = data.get('secrets', [])
    cms      = data.get('config_maps', [])

    # Detect plaintext secrets from the env list
    flags = []
    for e in env_vars:
        k = e.get('name', '').upper()
        v = str(e.get('value', ''))
        if any(x in k for x in ['PASSWORD', 'SECRET', 'TOKEN', 'KEY', 'PASS', 'CRED']):
            if 'Secret:' not in v and 'secret' not in v.lower():
                flags.append({
                    'severity': 'high',
                    'message': f'`{e["name"]}` contains a plaintext value — move it to a Kubernetes Secret and reference via `secretKeyRef`.'
                })
    if any(e.get('name') == 'LOG_LEVEL' and str(e.get('value', '')).upper() == 'DEBUG' for e in env_vars):
        flags.append({'severity': 'medium',
                      'message': '`LOG_LEVEL=DEBUG` is set — verbose logging in production increases storage costs and may expose sensitive request payloads.'})
    if not secrets:
        flags.append({'severity': 'medium',
                      'message': 'No Kubernetes Secrets referenced — ensure all sensitive values use `secretKeyRef` or `envFrom.secretRef`.'})
    if cms:
        flags.append({'severity': 'low',
                      'message': f'ConfigMap `{cms[0]}` — verify it contains no sensitive values (passwords, tokens). Use Secrets for credentials.'})

    return jsonify({
        'summary': (
            f'**{kind}** `{name}` (namespace: `{ns}`) is configured with {len(env_vars)} environment variables '
            f'across {len(set(e.get("container") for e in env_vars))} container(s). '
            f'It references {len(cms)} ConfigMap(s) for application settings and {len(secrets)} Secret(s) for credentials. '
            f'AI detected {len([f for f in flags if f["severity"] == "high"])} high-severity and '
            f'{len([f for f in flags if f["severity"] == "medium"])} medium-severity configuration issues.'
        ),
        'security_flags': flags or [{'severity': 'low', 'message': 'No critical configuration issues detected.'}],
        'recommendations': [
            f'Move `DB_PASSWORD` to a Kubernetes Secret and reference with `secretKeyRef` in the Deployment spec.',
            f'Change `LOG_LEVEL` to `info` or `warn` for production workloads.',
            f'Apply `immutable: true` to ConfigMap `{cms[0] if cms else name}-config` if values are stable — reduces API server load.',
        ],
        'kubectl_hints': [
            f'kubectl get deployment {name} -n {ns} -o jsonpath="{{.spec.template.spec.containers[*].env}}"',
            f'kubectl describe secret db-creds -n {ns}',
            f'kubectl set env deployment/{name} LOG_LEVEL=info -n {ns}',
        ],
        'gemini_powered': True,
    })



# ──────────────────────────────────────────────
# Feature 1: Multi-Container Log Correlation
# ──────────────────────────────────────────────
@app.route('/api/ai/correlate_logs', methods=['POST'])
def mock_correlate_logs():
    import time
    time.sleep(1.2)
    data = request.json or {}
    pod_name = data.get('pod_name', 'unknown-pod')
    ns       = data.get('namespace', 'default')
    c        = pod_name.lower()

    if 'payment' in c or 'crash' in c:
        pods = [pod_name, 'backend-pod-multi', 'frontend-pod-1']
        corr = (
            '## Cross-Pod Log Correlation: `' + pod_name + '`\n\n'
            '**Namespace:** `' + ns + '` | **Pods:** ' + ', '.join('`'+p+'`' for p in pods) + ' | **Containers:** 7 total\n\n'
            '---\n\n'
            '### Causal Chain Timeline\n\n'
            '| Time | Pod | Container | Event |\n'
            '|------|-----|-----------|-------|\n'
            '| T+0s | `' + pod_name + '` | `[init] db-check` | `[ERROR] ConnectionRefused: postgres at 10.0.0.5:5432` |\n'
            '| T+1s | `' + pod_name + '` | `sidecar-proxy` | `[ERROR] Circuit breaker OPEN for cluster payment-db` |\n'
            '| T+3s | `backend-pod-multi` | `api-server` | `[WARN] DB pool exhausted, queuing requests` |\n'
            '| T+5s | `' + pod_name + '` | `processor` | `[FATAL] panic: nil pointer dereference in main.connectDB -> CrashLoopBackOff` |\n'
            '| T+8s | `backend-pod-multi` | `sidecar-proxy` | `[ERROR] upstream connect error - 503 from backend` |\n'
            '| T+9s | `frontend-pod-1` | `nginx` | `[WARN] 502 Bad Gateway on /api/checkout - upstream unreachable` |\n'
            '\n---\n\n'
            '### Root Cause\n'
            'PostgreSQL `database-statefulset` is unreachable at `10.0.0.5:5432`. The failure cascades:\n\n'
            '1. `' + pod_name + '` init container (db-check) cannot connect -> blocks processor -> **CrashLoopBackOff**\n'
            '2. `backend-pod-multi` connection pool exhausts -> 503s to sidecar-proxy\n'
            '3. `frontend-pod-1` nginx receives 502s on checkout requests\n\n'
            '### Recommended Fixes\n'
            '1. `kubectl get pod -l app=postgres` -- verify database pod is running\n'
            '2. `kubectl rollout restart statefulset/database-statefulset` -- flush idle connections\n'
            '3. Increase `max_connections` in postgres ConfigMap from 100 to 200\n'
            '4. Add PgBouncer as connection pooler to prevent pool exhaustion\n\n'
            '### Log Statistics\n\n'
            '| Pod | Containers | ERROR | WARN |\n'
            '|-----|-----------|-------|------|\n'
            '| `' + pod_name + '` | 3 | 8 | 2 |\n'
            '| `backend-pod-multi` | 2 | 3 | 4 |\n'
            '| `frontend-pod-1` | 1 | 0 | 2 |\n'
        )

    elif 'oom' in c or 'analytics' in c:
        pods = [pod_name, 'backend-pod-multi']
        corr = (
            '## Cross-Pod Log Correlation: `' + pod_name + '`\n\n'
            '**Namespace:** `' + ns + '` | **Pods:** ' + ', '.join('`'+p+'`' for p in pods) + ' | **Containers:** 4 total\n\n'
            '---\n\n'
            '### Causal Chain Timeline\n\n'
            '| Time | Pod | Container | Event |\n'
            '|------|-----|-----------|-------|\n'
            '| T+0m | `' + pod_name + '` | `spark-driver` | `[INFO] Loading 48GB dataset into 5GB JVM heap` |\n'
            '| T+8m | `' + pod_name + '` | `spark-driver` | `[WARN] JVM heap at 91% - GC pause 3.2s` |\n'
            '| T+10m | `' + pod_name + '` | `spark-driver` | `[ERROR] java.lang.OutOfMemoryError: Java heap space` |\n'
            '| T+10m | kernel | OOM killer | `Kill process 4821 (java) score 999 - OOMKilled` |\n'
            '| T+10m | `' + pod_name + '` | `metrics-sidecar` | `[ERROR] Lost connection to spark-driver` |\n'
            '| T+11m | `backend-pod-multi` | `api-server` | `[WARN] analytics-job health check returning 503` |\n'
            '\n---\n\n'
            '### Root Cause\n'
            'Spark job loaded a 48GB dataset into a 5GB JVM heap. OOM kill cascades:\n\n'
            '1. spark-driver GC pauses increasing -> heap exhausted -> OOM killed\n'
            '2. metrics-sidecar loses connection -> stops exporting Prometheus metrics\n'
            '3. backend-pod-multi health checks against analytics service start failing\n\n'
            '### Recommended Fixes\n'
            '1. `kubectl set resources deployment analytics-job --limits=memory=64Gi`\n'
            '2. Add `SPARK_DRIVER_MEMORY=16g` env var and `spark.memory.fraction=0.6`\n'
            '3. Partition input dataset to reduce single-job peak memory\n'
            '4. Add OOM alert: jvm_heap_used_bytes > 85% of container memory limit\n\n'
            '### Log Statistics\n\n'
            '| Pod | Containers | ERROR | WARN |\n'
            '|-----|-----------|-------|------|\n'
            '| `' + pod_name + '` | 2 | 4 | 3 |\n'
            '| `backend-pod-multi` | 2 | 0 | 2 |\n'
        )

    elif 'sidecar-missing' in c:
        pods = [pod_name, 'frontend-pod-1']
        corr = (
            '## Cross-Pod Log Correlation: `' + pod_name + '`\n\n'
            '**Namespace:** `' + ns + '` | **Pods:** ' + ', '.join('`'+p+'`' for p in pods) + ' | **Containers:** 3 total\n\n'
            '---\n\n'
            '### Causal Chain Timeline\n\n'
            '| Time | Pod | Container | Event |\n'
            '|------|-----|-----------|-------|\n'
            '| T+0s | `' + pod_name + '` | `sidecar` | `[ERROR] ImagePullBackOff: 401 Unauthorized for myregistry.io/sidecar:v2.1-beta` |\n'
            '| T+30s | `' + pod_name + '` | `main` | `[WARN] Sidecar not ready after 30s, running without mTLS` |\n'
            '| T+2m | `frontend-pod-1` | `nginx` | `[WARN] TLS handshake failed to ' + pod_name + ' - sidecar missing` |\n'
            '\n---\n\n'
            '### Root Cause\n'
            'Image pull failure for `myregistry.io/sidecar:v2.1-beta` due to missing registry credentials (401 Unauthorized).\n\n'
            '### Recommended Fixes\n'
            '1. `kubectl create secret docker-registry myregistry-creds --docker-server=myregistry.io`\n'
            '2. Add `imagePullSecrets` to the pod spec\n'
            '3. Use a stable image tag instead of `-beta`\n'
        )

    else:
        pods = [pod_name, 'backend-pod-multi', 'frontend-pod-1', 'init-demo-pod']
        corr = (
            '## Cross-Pod Log Correlation: `' + pod_name + '`\n\n'
            '**Namespace:** `' + ns + '` | **Pods analysed:** All pods | **Containers:** All containers\n\n'
            '---\n\n'
            '### No Cross-Service Failures Detected\n\n'
            'All containers across `' + pod_name + '` and sibling pods are healthy. No error propagation patterns found.\n\n'
            '### Log Health Summary\n\n'
            '| Pod | Status | ERROR | WARN |\n'
            '|-----|--------|-------|------|\n'
            '| `' + pod_name + '` | Healthy | 0 | 0 |\n'
            '| `backend-pod-multi` | Healthy | 0 | 0 |\n'
            '| `frontend-pod-1` | Healthy | 0 | 0 |\n'
            '| `init-demo-pod` | Healthy | 0 | 0 |\n\n'
            '### Notable Events (Non-Error)\n\n'
            '| Time | Pod | Event |\n'
            '|------|-----|-------|\n'
            '| T+0m | `' + pod_name + '` | Server ready on :80 |\n'
            '| T+1m | `' + pod_name + '` | 200 GET /api/health (0ms) |\n'
            '| T+5m | `backend-pod-multi` | 200 POST /api/v1/process (145ms) |\n\n'
            '**No action required.** Continue monitoring with existing alerts.\n'
        )

    return jsonify({
        'correlation': corr,
        'summary': corr,
        'pod_name': pod_name,
        'pods_analyzed': pods if 'pods' in dir() else [pod_name],
        'gemini_powered': False,
    })


# ──────────────────────────────────────────────
# Feature 2: Conversational Multi-turn Agent
# ──────────────────────────────────────────────
MOCK_SESSIONS = {}  # {session_id: [{'role': 'user'|'assistant', 'content': str}]}

@app.route('/api/ai/converse', methods=['POST'])
def mock_converse():
    import time
    time.sleep(0.8)

    session_id = request.headers.get('X-Session-Id', 'default')
    data = request.json
    message = data.get('message', '').strip()

    if not message:
        return jsonify({'error': 'No message provided'}), 400

    history = MOCK_SESSIONS.setdefault(session_id, [])
    history.append({'role': 'user', 'content': message})
    turn = len([m for m in history if m['role'] == 'user'])

    msg_lower = message.lower()

    # Simulate Gemini Function Calling agent responses
    # Priority routing: check specific sub-topics FIRST before generic handlers
    _is_restart = any(x in msg_lower for x in ['restart', 'crashloop', 'back-off', 'backoff', 'keeps restarting'])
    _is_imagepull = any(x in msg_lower for x in ['imagepull', 'registry', 'image pull'])

    if _is_restart:
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_pods(field_selector=status.phase!=Running)` → 2 unhealthy
> `k8s_get_pod_restart_counts()` → checking restart history

---

**Pods with Restart Issues:**

| Pod | Restarts | Status | Last Exit | Reason |
|---|---|---|---|---|
| `payment-processor-0` | **8** | CrashLoopBackOff | 3m ago | Error (exit 1) |
| `analytics-job-oom` | **3** | OOMKilled | 1h ago | OOMKilled (exit 137) |

**Root Cause — `payment-processor-0`:**
```
[FATAL] ConnectionRefused: cannot reach postgres at 10.0.0.5:5432
[FATAL] panic: nil pointer dereference in main.connectDB
```
→ Database pod is healthy but the connection string may be wrong.

**Fix:**
```bash
kubectl describe pod payment-processor-0   # Check DB_HOST env var
kubectl rollout restart statefulset/database-statefulset
kubectl logs payment-processor-0 --previous   # See crash logs
```"""

    elif _is_imagepull:
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_pod_images(namespace=default)` → scanning images

---

**Container Images in Namespace:**

| Pod | Container | Image | Status |
|---|---|---|---|
| `frontend-6c8d` | main | `frontend:v2.4.1` | ✅ Running |
| `backend-api-9a1` | main | `backend-api:v3.1.2` | ✅ Running |
| `billing-service-8b7` | main | `billing:v1.12.0` | ✅ Running |
| `ml-inference-4d2` | main | `ml-inference:v0.9.5-beta` | ✅ Running |
| `payment-processor-0` | processor | `payment:v1.8.3` | ❌ CrashLoop |

**⚠️ No ImagePullBackOff issues detected.**

**If you see ImagePullBackOff:**
```bash
kubectl describe pod <pod-name>    # Check Events for pull error
# Common fixes:
# 1. Wrong image name/tag → fix in deployment spec
# 2. Private registry → add imagePullSecrets
# 3. Image doesn't exist → verify in container registry
```"""

    elif any(x in msg_lower for x in ['crash', 'failing', 'broken', 'why is', 'what is wrong', 'not working']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_pods` → found 2 unhealthy pods  
> `k8s_describe_pod(payment-processor-0)` → phase=Failed, restarts=8  
> `k8s_get_pod_logs(payment-processor-0)` → fetched last 150 lines  
> `k8s_get_pod_events(payment-processor-0)` → 3 Warning events found

---

**Root Cause:** `payment-processor-0` is in `CrashLoopBackOff`.

From the **live logs** I just fetched:
```
[FATAL] ConnectionRefused: cannot reach postgres at 10.0.0.5:5432
[FATAL] panic: nil pointer dereference in main.connectDB
```

**Live events** show: `BackOff: restarting failed container` (8 times in 45 minutes).

**Fix:**
```bash
kubectl rollout restart statefulset/database-statefulset
kubectl get pods -w  # Watch recovery
```

Should I also check if `database-statefulset` is healthy?"""

    elif any(x in msg_lower for x in ['helm', 'chart', 'version']) or ('image' in msg_lower and not any(x in msg_lower for x in ['imagepull', 'pull', 'registry'])):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_deployment_status(payment-service)` → fetching live deployment spec

---

**Deployment: payment-service**

| Field | Value |
|---|---|
| **Helm chart** | `payment-service-3.2.1` |
| **Helm release** | `prod-payment-service` |
| **App version** | `v1.8.3` |
| **Managed by** | `Helm` |

**Containers & images:**
- `processor` → `gcr.io/my-project/payment-processor:v1.8.3` (**version: v1.8.3**)
- `sidecar-proxy` → `envoy:v1.27.0` (**version: v1.27.0**)

All containers are running on image versions from the last deploy 3 days ago."""

    elif ('pod' in msg_lower and any(x in msg_lower for x in ['list', 'status', 'show', 'all'])) or msg_lower.strip() in ['pods', 'list pods', 'show pods', 'running pods', 'all pods']:
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_pods(namespace=default)` → 9 pods found

---

| Pod | Phase | Ready | Restarts | Node |
|---|---|---|---|---|
| `api-gateway-7d9f` | Running | 1/1 | 0 | worker-1 |
| `frontend-6c8d` | Running | 1/1 | 0 | worker-2 |
| `payment-processor-0` | Failed | 0/2 | 8 | worker-1 |
| `backend-pod-multi-5f6` | Running | 3/3 | 0 | worker-3 |
| `analytics-job-oom` | Failed | 0/1 | 3 | worker-2 |
| `billing-service-8b7` | Running | 1/1 | 0 | worker-1 |
| `database-statefulset-0` | Running | 1/1 | 0 | worker-3 |
| `cache-deployment-3c1` | Running | 1/1 | 0 | worker-2 |
| `monitoring-pod-abc` | Running | 1/1 | 0 | worker-1 |

⚠️ **2 pods need attention:** `payment-processor-0` and `analytics-job-oom`"""

    elif any(x in msg_lower for x in ['event', 'warning']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_namespace_events(namespace=default, event_type=Warning)` → 5 warning events

---

**Recent Warning Events:**

| Resource | Reason | Message |
|---|---|---|
| `payment-processor-0` | BackOff | Back-off restarting failed container |
| `payment-processor-0` | Failed | Error: ErrImagePull on sidecar-proxy |
| `analytics-job-oom` | OOMKilling | Container spark-driver exceeded memory limit |
| `database-statefulset-0` | Unhealthy | Liveness probe failed: connection refused |
| `frontend-6c8d` | ScalingReplicaSet | Scaled up replica set from 1 to 2 |"""

    elif any(x in msg_lower for x in ['service', 'port', 'svc']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_services(namespace=default)` → 6 services found

---

| Service | Type | ClusterIP | Ports |
|---|---|---|---|
| `api-gateway-svc` | LoadBalancer | 10.0.1.50 | 443/TCP→8080 |
| `frontend-svc` | ClusterIP | 10.0.1.51 | 80/TCP→3000 |
| `payment-svc` | ClusterIP | 10.0.1.52 | 8080/TCP→8080 |
| `database-svc` | ClusterIP | 10.0.1.53 | 5432/TCP→5432 |
| `cache-svc` | ClusterIP | 10.0.1.54 | 6379/TCP→6379 |
| `monitoring-svc` | NodePort | 10.0.1.55 | 9090/TCP→9090 |"""

    elif any(x in msg_lower for x in ['configmap', 'app-config']) or (msg_lower.strip() in ['config', 'show config', 'show configmap']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_configmap(app-config)` → fetched 6 keys

---

**ConfigMap: app-config**

| Key | Value |
|---|---|
| `DB_HOST` | `database-svc.default.svc.cluster.local` |
| `DB_PORT` | `5432` |
| `LOG_LEVEL` | `info` |
| `MAX_CONNECTIONS` | `100` |
| `FEATURE_FLAGS` | `{"new_checkout": true, "dark_mode": false}` |
| `API_TIMEOUT_MS` | `5000` |

⚠️ Note: `DB_HOST` is set to the K8s service DNS — this is correct for in-cluster access."""

    elif any(x in msg_lower for x in ['memory', 'oom', 'ram', 'heap', 'memory limit', 'memory usage']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_top_pods(namespace=default)` → fetched resource usage
> `k8s_describe_pod(*)` → checking OOM events

---

**Memory Usage by Pod:**

| Pod | Usage | Request | Limit | % of Limit |
|---|---|---|---|---|
| `database-statefulset-0` | **241 MiB** | 256Mi | 256Mi | ⚠️ **94%** |
| `billing-service-8b7` | 380 MiB | 2Gi | 8Gi | 4.6% |
| `analytics-job-oom` | **OOMKilled** | 4Gi | 5Gi | 💀 Exceeded |
| `frontend-6c8d` | 45 MiB | — | — | ⚠️ No limit set |
| `ml-inference-4d2` | 6100 MiB | 4Gi | 8Gi | 74% |

**⚠️ Issues Found:**
1. `analytics-job-oom` — **OOMKilled**: JVM heap exhausted loading 48GB dataset into 5GB limit
2. `database-statefulset-0` — At **94% memory** — `shared_buffers` is starved, OOM imminent
3. `frontend-6c8d` — **No memory limit set** — can OOM-kill neighbours

**Recommendations:**
```bash
kubectl set resources deploy/analytics-job --limits=memory=64Gi
kubectl patch statefulset database-statefulset -p '{"spec":{"template":{"spec":{"containers":[{"name":"postgres","resources":{"limits":{"memory":"2Gi"}}}]}}}}'
```"""

    elif any(x in msg_lower for x in ['cpu', 'throttl', 'slow', 'latency', 'performance']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_top_pods(namespace=default)` → fetched CPU metrics
> `k8s_get_pod_resource_limits(*)` → checking throttling

---

**CPU Usage by Pod:**

| Pod | Usage | Request | Limit | Throttled? |
|---|---|---|---|---|
| `ml-inference-4d2` | **820m** | 500m | 1000m | ⚠️ **Yes — 64% throttled** |
| `billing-service-8b7` | 480m | 4000m | 8000m | No (over-provisioned) |
| `backend-api-9a1` | 210m | 500m | 1000m | No |
| `frontend-6c8d` | 30m | 500m | — | No (no limit) |

**⚠️ Issues Found:**
1. `ml-inference` — CPU usage (820m) exceeds request (500m). Being **throttled** causing latency spikes
2. `billing-service` — Over-provisioned by **88%** (using 480m of 4000m request)

**Fix throttling:**
```bash
kubectl set resources deploy/ml-inference --requests=cpu=1100m --limits=cpu=2200m
```

**Reduce waste:**
```bash
kubectl set resources deploy/billing-service --requests=cpu=650m --limits=cpu=1300m
```"""

    elif any(x in msg_lower for x in ['deploy', 'rollout', 'replica', 'unavailable', 'deployment status']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_deployments(namespace=default)` → 4 deployments found
> `k8s_get_rollout_status(*)` → checking rollout health

---

**Deployment Status:**

| Deployment | Ready | Up-to-Date | Available | Strategy | Age |
|---|---|---|---|---|---|
| `frontend-deployment` | 1/1 | 1 | 1 | RollingUpdate | 3d |
| `backend-api` | 2/2 | 2 | 2 | RollingUpdate | 5d |
| `billing-service` | 3/3 | 3 | 3 | RollingUpdate | 7d |
| `ml-inference` | 1/1 | 1 | 1 | Recreate | 1d |

**All deployments are healthy.** ✅

**Recent Rollout History (billing-service):**
| Revision | Change | Timestamp |
|---|---|---|
| 3 (current) | Image → `billing:v1.12.0` | 2h ago |
| 2 | Image → `billing:v1.11.2` | 3d ago |
| 1 | Initial deploy | 7d ago |

**Useful commands:**
```bash
kubectl rollout status deploy/<name>
kubectl rollout history deploy/<name>
kubectl rollout undo deploy/<name>      # Rollback
```"""

    elif any(x in msg_lower for x in ['pvc', 'storage', 'volume', 'disk', 'persistent']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_pvcs(namespace=default)` → 2 PVCs found
> `k8s_describe_pvc(*)` → checking storage status

---

**Persistent Volume Claims:**

| PVC | Status | Capacity | StorageClass | Used By |
|---|---|---|---|---|
| `postgres-data-0` | ✅ Bound | 50Gi | `standard-rwo` | `database-statefulset-0` |
| `redis-data-0` | ✅ Bound | 10Gi | `standard-rwo` | `redis-cache-0` |

**Disk Usage (estimated):**
- `postgres-data-0`: **32Gi / 50Gi** (64%) — healthy
- `redis-data-0`: **2.1Gi / 10Gi** (21%) — healthy

**⚠️ No PVC issues detected.** Both volumes are bound and accessible.

**Useful commands:**
```bash
kubectl get pvc -n <namespace>
kubectl describe pvc <name>
kubectl exec <pod> -- df -h /data    # Check actual disk usage
```"""

    elif any(x in msg_lower for x in ['network', 'dns', 'connect', 'timeout', 'unreachable', 'connection refused']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_services()` → 6 services found
> `k8s_get_endpoints(*)` → checking endpoint health
> `k8s_check_network_policies()` → checking restrictions

---

**Service Endpoint Health:**

| Service | Endpoints | Healthy? |
|---|---|---|
| `frontend-svc` | 1 pod | ✅ |
| `backend-api-svc` | 2 pods | ✅ |
| `payment-svc` | 0 pods | ❌ **No endpoints!** |
| `database-svc` | 1 pod | ✅ |
| `cache-svc` | 1 pod | ✅ |

**⚠️ `payment-svc` has no ready endpoints** — the payment-processor pod is in CrashLoopBackOff.

**DNS Resolution Test:**
```
database-svc.default.svc.cluster.local → 10.0.1.53 ✅
payment-svc.default.svc.cluster.local → (no endpoints) ❌
```

**Common Connectivity Fixes:**
```bash
# Verify service selector matches pod labels
kubectl get endpoints payment-svc
kubectl describe svc payment-svc

# Test DNS from a pod
kubectl exec <pod> -- nslookup database-svc
```"""

    elif any(x in msg_lower for x in ['secret', 'credential', 'password', 'token']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_secrets(namespace=default)` → 4 secrets found

---

**Secrets in Namespace:**

| Secret | Type | Keys | Age |
|---|---|---|---|
| `db-credentials` | Opaque | `username`, `password` | 30d |
| `api-keys` | Opaque | `stripe-key`, `sendgrid-key` | 15d |
| `tls-cert` | kubernetes.io/tls | `tls.crt`, `tls.key` | 7d |
| `default-token-*` | SA token | `ca.crt`, `token`, `namespace` | 30d |

**⚠️ Security Notes:**
- `db-credentials` is mounted in `database-statefulset` — ✅ correct
- `api-keys` is referenced by `billing-service` via `secretKeyRef` — ✅ correct
- TLS cert expires in **23 days** — consider auto-rotation

**Useful commands:**
```bash
kubectl get secrets -n <namespace>
kubectl describe secret <name>
kubectl get secret <name> -o jsonpath='{.data.<key>}' | base64 -d
```"""

    elif any(x in msg_lower for x in ['rbac', 'permission', 'forbidden', 'access denied', 'unauthorized']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_rolebindings(namespace=default)` → checking RBAC
> `k8s_check_can_i(*)` → testing permissions

---

**RBAC Bindings in Namespace:**

| RoleBinding | Role | Subjects |
|---|---|---|
| `admin-binding` | `admin` | Group: `platform-team` |
| `developer-binding` | `edit` | Group: `dev-team` |
| `ci-deployer` | `deployer` | SA: `ci-pipeline` |

**Common 403 Fixes:**
- `RBAC: access denied` in Envoy → Check `AuthorizationPolicy` (Istio mesh)
- `forbidden: User "X" cannot...` → Check Kubernetes RBAC (RoleBinding)

```bash
# Check what a service account can do
kubectl auth can-i --list --as=system:serviceaccount:default:my-sa

# Check if you can scale deployments
kubectl auth can-i update deployments --namespace=default
```"""

    elif any(x in msg_lower for x in ['hpa', 'autoscal', 'auto-scal', 'scale automatic']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_hpa(namespace=default)` → 1 HPA found

---

**Horizontal Pod Autoscalers:**

| HPA | Target | Min | Max | Current | Replicas |
|---|---|---|---|---|---|
| `backend-api` | CPU: 70% | 2 | 10 | 42% | 2 |

**Status:** HPA is stable — current CPU (42%) is below target (70%), no scaling needed.

**⚠️ Services without HPA:**
- `billing-service` (3 replicas, fixed) — consider adding HPA
- `ml-inference` (1 replica) — burst traffic not auto-handled

**Add HPA:**
```bash
kubectl autoscale deployment billing-service --cpu-percent=70 --min=2 --max=8
```"""

    elif any(x in msg_lower for x in ['job', 'cronjob', 'batch', 'scheduled']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_jobs(namespace=default)` → 2 jobs found
> `k8s_list_cronjobs(namespace=default)` → 1 cronjob found

---

**Jobs:**

| Job | Status | Completions | Duration | Age |
|---|---|---|---|---|
| `analytics-job` | ❌ Failed | 0/1 | — | 2h |
| `db-migration-v12` | ✅ Complete | 1/1 | 45s | 1d |

**CronJobs:**

| CronJob | Schedule | Last Run | Status |
|---|---|---|---|
| `log-cleanup` | `0 3 * * *` | 3:00 AM today | ✅ Success |

**⚠️ `analytics-job` failed** — OOMKilled (see memory analysis).

**Useful commands:**
```bash
kubectl get jobs
kubectl describe job analytics-job
kubectl logs job/analytics-job
kubectl delete job analytics-job    # Cleanup failed job
```"""

    elif any(x in msg_lower for x in ['node', 'scheduling', 'unschedulable', 'taint', 'cordon']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_nodes()` → 3 nodes found

---

**Node Status:**

| Node | Status | Roles | CPU | Memory | Pods |
|---|---|---|---|---|---|
| `worker-1` | ✅ Ready | worker | 4 cores | 16Gi | 4/110 |
| `worker-2` | ✅ Ready | worker | 4 cores | 16Gi | 3/110 |
| `worker-3` | ✅ Ready | worker | 8 cores | 32Gi | 2/110 |

**All nodes are schedulable.** ✅

**If pods are Pending (unschedulable):**
```bash
kubectl describe pod <pending-pod>    # Check Events section
kubectl get nodes -o wide
kubectl describe node <node-name>     # Check Allocatable vs Allocated
kubectl top nodes                     # Check actual usage
```"""

    elif any(x in msg_lower for x in ['namespace', 'overview', 'summary', 'health check', 'cluster status']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_namespace_summary(default)` → aggregating...

---

**📊 Namespace Summary: `default`**

| Category | Count | Healthy | Issues |
|---|---|---|---|
| **Pods** | 9 | 7 | 2 (CrashLoop, OOMKilled) |
| **Deployments** | 4 | 4/4 ready | — |
| **StatefulSets** | 1 | 1/1 ready | memory pressure |
| **DaemonSets** | 1 | 3/3 ready | over-provisioned |
| **Services** | 6 | 5 with endpoints | 1 no endpoints |
| **ConfigMaps** | 3 | — | — |
| **Secrets** | 4 | — | TLS expiring in 23d |
| **PVCs** | 2 | 2 Bound | — |
| **Jobs** | 2 | 1 Complete | 1 Failed |

**🔴 Critical Issues:**
1. `payment-processor-0` — CrashLoopBackOff (DB unreachable)
2. `analytics-job-oom` — OOMKilled (memory limit too low)

**🟡 Warnings:**
3. `database-statefulset-0` — Memory at 94% of limit
4. `frontend` — No memory limits set
5. `billing-service` — CPU over-provisioned by 88%"""

    elif any(x in msg_lower for x in ['restart', 'crashloop', 'back-off', 'backoff', 'keeps restarting']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_list_pods(field_selector=status.phase!=Running)` → 2 unhealthy
> `k8s_get_pod_restart_counts()` → checking restart history

---

**Pods with Restart Issues:**

| Pod | Restarts | Status | Last Exit | Reason |
|---|---|---|---|---|
| `payment-processor-0` | **8** | CrashLoopBackOff | 3m ago | Error (exit 1) |
| `analytics-job-oom` | **3** | OOMKilled | 1h ago | OOMKilled (exit 137) |

**Root Cause — `payment-processor-0`:**
```
[FATAL] ConnectionRefused: cannot reach postgres at 10.0.0.5:5432
[FATAL] panic: nil pointer dereference in main.connectDB
```
→ Database pod is healthy but the connection string may be wrong.

**Fix:**
```bash
kubectl describe pod payment-processor-0   # Check DB_HOST env var
kubectl rollout restart statefulset/database-statefulset
kubectl logs payment-processor-0 --previous   # See crash logs
```"""

    elif any(x in msg_lower for x in ['image', 'pull', 'imagepull', 'registry', 'tag']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_pod_images(namespace=default)` → scanning images

---

**Container Images in Namespace:**

| Pod | Container | Image | Status |
|---|---|---|---|
| `frontend-6c8d` | main | `frontend:v2.4.1` | ✅ Running |
| `backend-api-9a1` | main | `backend-api:v3.1.2` | ✅ Running |
| `billing-service-8b7` | main | `billing:v1.12.0` | ✅ Running |
| `ml-inference-4d2` | main | `ml-inference:v0.9.5-beta` | ✅ Running |
| `payment-processor-0` | processor | `payment:v1.8.3` | ❌ CrashLoop |

**⚠️ No ImagePullBackOff issues detected.**

**If you see ImagePullBackOff:**
```bash
kubectl describe pod <pod-name>    # Check Events for pull error
# Common fixes:
# 1. Wrong image name/tag → fix in deployment spec
# 2. Private registry → add imagePullSecrets
# 3. Image doesn't exist → verify in container registry
```"""

    elif any(x in msg_lower for x in ['best practice', 'recommend', 'improve', 'optimize', 'suggestion']):
        reply = """🔍 **Analysing namespace against K8s best practices...**

---

**🏆 Best Practice Assessment:**

| Check | Status | Detail |
|---|---|---|
| Resource requests set | ⚠️ | `frontend` missing requests |
| Resource limits set | ❌ | `frontend` has no memory limit |
| Liveness probes | ⚠️ | 2 deployments missing probes |
| Readiness probes | ⚠️ | 2 deployments missing probes |
| Pod Disruption Budgets | ❌ | None configured |
| HPA configured | ⚠️ | Only 1 of 4 deployments |
| Anti-affinity rules | ❌ | Not set (single-AZ risk) |
| Image tags pinned | ✅ | All using versioned tags |
| Network policies | ⚠️ | No NetworkPolicy resources |
| Security context | ❌ | `database` runs as root |

**Top 3 Recommendations:**
1. **Add memory limits** to `frontend` — prevents OOM-killing neighbours
2. **Add liveness/readiness probes** — enables self-healing
3. **Add PodDisruptionBudget** — protects availability during node drains

Would you like me to generate the YAML for any of these?"""

    elif any(x in msg_lower for x in ['log', 'logs', 'stderr', 'stdout', 'error log']):
        reply = """🔍 **Calling live K8s tools...**

> `k8s_get_pod_logs(payment-processor-0, tail=50)` → fetched logs

---

**Recent Logs — `payment-processor-0` (last 10 lines):**

```
2026-04-28T10:45:01Z [INFO]  Starting payment-processor v1.8.3
2026-04-28T10:45:02Z [INFO]  Initialising database connection pool...
2026-04-28T10:45:02Z [WARN]  DB connection attempt 1/3 failed
2026-04-28T10:45:05Z [WARN]  DB connection attempt 2/3 failed
2026-04-28T10:45:08Z [WARN]  DB connection attempt 3/3 failed
2026-04-28T10:45:08Z [FATAL] ConnectionRefused: cannot reach postgres at 10.0.0.5:5432
2026-04-28T10:45:08Z [FATAL] panic: runtime error: nil pointer dereference
2026-04-28T10:45:08Z [FATAL]   goroutine 1 [running]:
2026-04-28T10:45:08Z [FATAL]   main.connectDB(0x0, 0x0)
2026-04-28T10:45:08Z [FATAL] Process exiting with code 1
```

**Analysis:** The app retries DB connection 3 times then panics due to nil pointer on the failed connection handle.

**Useful log commands:**
```bash
kubectl logs <pod> --tail=100           # Last 100 lines
kubectl logs <pod> --previous           # Logs from crashed container
kubectl logs <pod> -c istio-proxy       # Sidecar proxy logs
kubectl logs <pod> --since=1h           # Last hour only
```"""

    elif any(x in msg_lower for x in ['help', 'what can', 'capabilit']):
        reply = """I'm your **GDC Cluster Agent** — powered by AI with **live Kubernetes API access**.

I can help with these topics:

| Category | Example Questions |
|---|---|
| 🔴 **Troubleshooting** | *"Why is payment crashing?"*, *"Show crash loops"* |
| 📋 **Logs** | *"Show logs for payment-processor"*, *"Any errors in logs?"* |
| 💾 **Memory/OOM** | *"Which pods use most memory?"*, *"Why was my pod OOMKilled?"* |
| ⚡ **CPU/Throttling** | *"Is anything being CPU throttled?"*, *"Show CPU usage"* |
| 🚀 **Deployments** | *"Show deployment status"*, *"Rollout history"* |
| 🌐 **Networking** | *"Any DNS issues?"*, *"Which services have no endpoints?"* |
| 💽 **Storage** | *"Show PVC status"*, *"Any disk pressure?"* |
| 🔐 **Secrets** | *"List secrets"*, *"When does TLS cert expire?"* |
| 🛡️ **RBAC** | *"Why am I getting 403?"*, *"Check permissions"* |
| 📈 **Autoscaling** | *"Is HPA configured?"*, *"Add autoscaling"* |
| ⏱️ **Jobs** | *"Show failed jobs"*, *"CronJob status"* |
| 🖥️ **Nodes** | *"Node status"*, *"Why is my pod Pending?"* |
| 📊 **Overview** | *"Namespace summary"*, *"Cluster health check"* |
| 🏆 **Best Practices** | *"Any recommendations?"*, *"What should I improve?"* |
| 🐳 **Images** | *"What image versions?"*, *"ImagePullBackOff help"* |
| ⚙️ **Config** | *"Show ConfigMap"*, *"What's in app-config?"* |
| 📅 **Events** | *"Show warning events"*, *"What happened recently?"* |
| 🎛️ **Services** | *"What services exist?"*, *"Show exposed ports"* |
| 🔖 **Helm** | *"What Helm chart?"*, *"Show image versions"* |

Just ask naturally — I understand context and follow-up questions!"""

    else:
        if turn == 1:
            reply = f"""🔍 **Calling live K8s tools...**

> `k8s_list_pods()` → found 9 pods  
> `k8s_list_deployments()` → found 4 deployments

---

You asked: *"{message}"*

I can see **9 pods** running in the cluster. **7 are healthy**, but **2 need attention**:
- `payment-processor-0` → CrashLoopBackOff (8 restarts)
- `analytics-job-oom` → OOMKilled

Would you like me to investigate these, or is there something specific you'd like to check?"""
        else:
            reply = f"""Following up on our conversation...

You mentioned: *"{message}"*

Based on the live cluster data, my recommendation is to first stabilise `payment-processor-0` (fix the DB connection), then re-evaluate resource limits on `analytics-job-oom`. Would you like a step-by-step action plan?"""

    history.append({'role': 'assistant', 'content': reply})

    # Suggest follow-up prompts
    suggested = []
    r = reply.lower()
    if 'crash' in r or 'oomkill' in r or 'backoff' in r:
        suggested = ['Show memory usage by pod', 'Check database-statefulset health', 'Show me the raw logs']
    elif 'memory' in r or 'ram' in r:
        suggested = ['Show CPU usage too', 'Any best practice recommendations?', 'Namespace overview']
    elif 'cpu' in r or 'throttl' in r:
        suggested = ['Show memory usage', 'Any pods over-provisioned?', 'Is HPA configured?']
    elif 'deploy' in r or 'rollout' in r:
        suggested = ['Show pod status', 'Any warning events?', 'Check image versions']
    elif 'pvc' in r or 'storage' in r:
        suggested = ['Show node status', 'Namespace summary', 'Any pods failing?']
    elif 'network' in r or 'dns' in r or 'endpoint' in r:
        suggested = ['Show services and ports', 'Any RBAC denials?', 'Check pod connectivity']
    elif 'secret' in r or 'credential' in r:
        suggested = ['Show ConfigMap values', 'Any RBAC issues?', 'Best practice check']
    elif 'rbac' in r or 'permission' in r:
        suggested = ['Show namespace summary', 'Any 403 in proxy logs?', 'List services']
    elif 'hpa' in r or 'autoscal' in r:
        suggested = ['Show CPU usage', 'Show memory usage', 'Deployment status']
    elif 'job' in r or 'cronjob' in r:
        suggested = ['Show logs for failed job', 'Memory usage by pod', 'Events for analytics-job']
    elif 'node' in r or 'schedul' in r:
        suggested = ['Namespace summary', 'Any pending pods?', 'Show resource usage']
    elif 'best practice' in r or 'recommend' in r:
        suggested = ['Show memory usage', 'Show CPU usage', 'Generate YAML for probes']
    elif 'image' in r or 'pull' in r:
        suggested = ['Show deployment status', 'Any warning events?', 'Helm chart versions']
    elif 'helm' in r or 'version' in r or 'image' in r:
        suggested = ['What version is frontend running?', 'List all deployments', 'Which pods are unhealthy?']
    elif 'event' in r or 'warning' in r:
        suggested = ['Show logs for payment-processor-0', 'Run diagnose on payment-processor-0', 'Namespace overview']
    elif 'service' in r or 'port' in r:
        suggested = ['Any network connectivity issues?', 'Show pod status', 'Check DNS resolution']
    elif 'help' in r or 'capable' in r:
        suggested = ['Namespace summary', 'Show memory usage', 'Why is payment crashing?']
    elif 'log' in r:
        suggested = ['Why is this pod crashing?', 'Show warning events', 'Memory usage by pod']
    else:
        suggested = ['Namespace summary', 'Show memory usage', 'Any warning events?']

    return jsonify({
        'reply': reply,
        'session_id': session_id,
        'turn': turn,
        'suggested_prompts': suggested
    })



@app.route('/api/ai/converse/reset', methods=['POST'])
def mock_converse_reset():
    session_id = request.headers.get('X-Session-Id', 'default')
    MOCK_SESSIONS.pop(session_id, None)
    return jsonify({'status': 'cleared', 'session_id': session_id})


# ──────────────────────────────────────────────
# Feature 3: Natural Language YAML Generation
# ──────────────────────────────────────────────
@app.route('/api/ai/generate_yaml', methods=['POST'])
def mock_generate_yaml():
    import time
    time.sleep(1.2)

    data = request.json or {}
    # Accept both 'prompt' (frontend field) and 'description' (legacy)
    description = (data.get('prompt') or data.get('description', '')).lower()
    namespace = data.get('namespace', 'default')

    # Extract a clean name from the description
    name_candidates = [w for w in description.split() if w.isalpha() and len(w) > 3
                       and w not in ('create', 'with', 'that', 'have', 'wants', 'need',
                                     'deployment', 'service', 'configmap', 'replica',
                                     'memory', 'limit', 'nginx', 'redis', 'postgres')]
    resource_name = name_candidates[0] if name_candidates else 'my-app'

    # Detect replica count
    import re
    replica_match = re.search(r'(\d+)\s*(?:replica|pod|instance)', description)
    replicas = int(replica_match.group(1)) if replica_match else 2

    # Detect memory
    mem_match = re.search(r'(\d+\s*(?:mi|gi)b?)', description)
    memory = mem_match.group(1).upper().replace(' ', '').replace('B', '') if mem_match else '256Mi'
    if not memory.endswith('i'):
        memory += 'i'

    # Detect image
    if 'redis' in description:
        image = 'redis:7-alpine'
    elif 'nginx' in description or 'frontend' in description:
        image = 'nginx:1.25-alpine'
    elif 'postgres' in description or 'database' in description:
        image = 'postgres:15-alpine'
    elif 'node' in description or 'express' in description:
        image = 'node:20-alpine'
    else:
        image = f'{resource_name}:latest'

    if 'service' in description and 'deployment' not in description:
        yaml_output = f"""apiVersion: v1
kind: Service
metadata:
  name: {resource_name}-svc
  namespace: {namespace}
  labels:
    app: {resource_name}
spec:
  selector:
    app: {resource_name}
  ports:
    - name: http
      port: 80
      targetPort: 8080
      protocol: TCP
  type: ClusterIP"""

    elif 'configmap' in description:
        yaml_output = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {resource_name}-config
  namespace: {namespace}
  labels:
    app: {resource_name}
data:
  APP_ENV: production
  LOG_LEVEL: info
  DB_HOST: database-svc
  DB_PORT: "5432"
  config.json: |
    {{
      "timeout": 5000,
      "retries": 3,
      "poolSize": 10
    }}"""

    elif 'hpa' in description or 'autoscal' in description:
        yaml_output = f"""apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {resource_name}-hpa
  namespace: {namespace}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {resource_name}
  minReplicas: {replicas}
  maxReplicas: {replicas * 5}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80"""

    else:
        # Default: Deployment
        yaml_output = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {resource_name}
  namespace: {namespace}
  labels:
    app: {resource_name}
    managed-by: gdc-dashboard
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: {resource_name}
  template:
    metadata:
      labels:
        app: {resource_name}
    spec:
      containers:
        - name: {resource_name}
          image: {image}
          ports:
            - containerPort: 8080
              name: http
          resources:
            requests:
              cpu: 100m
              memory: {memory}
            limits:
              cpu: 500m
              memory: {memory}
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
          env:
            - name: APP_ENV
              value: production
            - name: LOG_LEVEL
              value: info
      restartPolicy: Always"""

    return jsonify({'yaml': yaml_output, 'resource_name': resource_name})



@app.route('/api/ai/analyze_workload', methods=['POST'])
def mock_analyze_workload():
    import random
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('kind', 'Deployment')
    ns = data.get('namespace', 'default')
    bad = any(x in name for x in ['payment','crash','oom','failed','missing'])
    score = random.randint(25, 55) if bad else random.randint(88, 98)
    status = 'Critical' if score < 50 else 'Degraded' if score < 80 else 'Healthy'
    risks = []
    if bad:
        risks = [
            {'severity': 'Critical', 'description': f'Pods in {name} are crash-looping. Init container fails to connect to database.', 'action': f'kubectl get pods -l app={name.split("-")[0]} -n {ns}'},
            {'severity': 'High', 'description': 'Readiness probe failing — no traffic routed.', 'action': 'Verify probe path matches app health endpoint.'},
        ]
    return jsonify({
        'health_score': score, 'health_status': status,
        'summary': f'{kind} `{name}` is {"experiencing critical issues" if bad else "fully healthy with all replicas ready"}.',
        'risks': risks,
        'kubectl_hints': [
            f'kubectl get pods -l app={name.split("-")[0]} -n {ns}',
            f'kubectl describe {kind.lower()} {name} -n {ns}',
            f'kubectl logs -l app={name.split("-")[0]} --tail=50 -n {ns}',
        ],
        'positive_signals': [] if bad else ['All replicas healthy', 'Resource limits set', 'Probes configured'],
        'gemini_powered': False
    })

@app.route('/api/ai/diagnose', methods=['POST'])
def mock_diagnose():
    """Unified diagnose endpoint — merges Analyze + Health Check into one response."""
    import random, time
    time.sleep(0.8)
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('kind', 'Deployment')
    ns = data.get('namespace', 'default')
    ready = data.get('ready', 1)
    total = data.get('total', 1)
    ratio = ready / max(total, 1)

    bad = any(x in name for x in ['payment', 'crash', 'oom', 'failed', 'missing'])

    # Health score + verdict
    score = random.randint(25, 55) if bad else random.randint(88, 98)
    if score < 50:
        verdict, verdict_color, verdict_icon = 'Critical', '#dc3545', '🔴'
    elif score < 80:
        verdict, verdict_color, verdict_icon = 'Degraded', '#e6a000', '⚠️'
    else:
        verdict, verdict_color, verdict_icon = 'Healthy', '#0f9d58', '✅'

    # Risks
    risks = []
    if bad:
        risks = [
            {'severity': 'Critical', 'description': f'Pods in {name} are crash-looping. Init container fails to connect to database.',
             'action': f'kubectl get pods -l app={name.split("-")[0]} -n {ns}'},
            {'severity': 'High', 'description': 'Readiness probe failing — no traffic routed.',
             'action': 'Verify probe path matches app health endpoint.'},
        ]

    # Replica advice
    if total == 1:
        replica_advice = '⚠️ **Single replica** — no HA. Add at least 1 more replica for availability.'
    elif total >= 5:
        replica_advice = f'Running {total} replicas — consider HPA for dynamic scaling.'
    else:
        replica_advice = f'{total} replicas — appropriate for this workload.'

    return jsonify({
        'health_score': score,
        'verdict': verdict,
        'verdict_color': verdict_color,
        'verdict_icon': verdict_icon,
        'summary': f'{kind} `{name}` is {"experiencing critical issues" if bad else "fully healthy with all replicas ready"}. **{ready}/{total}** pods ready.',
        'risks': risks,
        'positive_signals': [] if bad else ['All replicas healthy', 'Resource limits set', 'Probes configured', 'Rolling update strategy'],
        'replica_advice': replica_advice,
        'rollout_advice': 'Use `maxUnavailable: 1`, `maxSurge: 1` for zero-downtime rolling updates.',
        'resource_advice': 'Set CPU/memory requests and limits. Recommended: `requests.cpu=100m`, `limits.cpu=500m`.',
        'kubectl_hints': [
            f'kubectl rollout status {kind.lower()}/{name} -n {ns}',
            f'kubectl describe {kind.lower()} {name} -n {ns}',
            f'kubectl logs -l app={name.split("-")[0]} --tail=50 -n {ns}',
            f'kubectl top pods -l app={name.split("-")[0]} -n {ns}',
        ],
        'gemini_powered': False
    })

@app.route('/api/ai/diagnose_pod', methods=['POST'])
def mock_diagnose_pod():
    data = request.json or {}
    pod = data.get('pod_name', 'unknown')
    if 'payment' in pod or 'crash' in pod:
        return jsonify({
            'health_status': 'CrashLooping', 'severity': 'critical',
            'crash_reason': 'OOMKilled: container exceeded 512Mi memory limit',
            'root_cause': 'Init container db-check cannot connect to PostgreSQL at 10.0.0.5:5432, blocking the processor container.',
            'evidence': ['[FATAL] ConnectionRefused: cannot reach postgres at 10.0.0.5:5432', '[FATAL] panic: nil pointer dereference in main.connectDB'],
            'container_health': {
                'db-check': {'status': 'error', 'summary': 'Init failing — DB unreachable'},
                'processor': {'status': 'error', 'summary': 'Crash on startup (init failed)'},
                'sidecar-proxy': {'status': 'warning', 'summary': 'Circuit breaker open'},
            },
            'remediation_steps': [
                {'step': 1, 'action': 'Verify PostgreSQL pod is running', 'command': f'kubectl get pod -l app=postgres -n default'},
                {'step': 2, 'action': 'Check DB_HOST env var', 'command': f'kubectl describe pod {pod} -n default'},
                {'step': 3, 'action': 'Restart DB if needed', 'command': 'kubectl rollout restart deployment postgres'},
            ],
            'kubectl_hints': [
                f'kubectl logs {pod} --previous --tail=50',
                f'kubectl describe pod {pod}',
                'kubectl get events --sort-by=.lastTimestamp | tail -20',
            ],
            'prevention': 'Add PodDisruptionBudget for DB and use connection retry with backoff.',
            'gemini_powered': False
        })
    elif 'oom' in pod or 'analytics' in pod:
        return jsonify({
            'health_status': 'Failed', 'severity': 'critical',
            'crash_reason': 'OOMKilled: JVM heap exhausted loading 48GB dataset into 5GB limit',
            'root_cause': 'Job loaded a 48GB dataset into a 5GB JVM heap, triggering OutOfMemoryError and OOM kill.',
            'evidence': ['[ERROR] java.lang.OutOfMemoryError: Java heap space', '[WARN] JVM heap at 91%'],
            'container_health': {
                'spark-driver': {'status': 'error', 'summary': 'OOMKilled'},
                'metrics-sidecar': {'status': 'warning', 'summary': 'Lost connection post-kill'}
            },
            'remediation_steps': [{'step': 1, 'action': 'Increase memory limit to 64Gi', 'command': f'kubectl set resources deployment analytics-job --limits=memory=64Gi'}],
            'kubectl_hints': [
                f'kubectl logs {pod} --previous --tail=100',
                f'kubectl describe pod {pod}',
                'kubectl top pods --sort-by=memory | head -10',
            ],
            'prevention': 'Set Spark memory fraction to 0.6 and alert on jvm_heap_used_bytes > 85%.',
            'gemini_powered': False
        })
    else:
        return jsonify({
            'health_status': 'Healthy', 'severity': 'ok',
            'crash_reason': None,
            'root_cause': 'No issues detected. All containers running normally.',
            'evidence': ['[INFO] Application ready', '[INFO] Health check passed'],
            'container_health': {'main': {'status': 'ok', 'summary': 'Running and healthy'}},
            'remediation_steps': [],
            'kubectl_hints': [
                f'kubectl logs {pod} --tail=50',
                f'kubectl describe pod {pod}',
            ],
            'prevention': 'Continue monitoring.',
            'gemini_powered': False
        })


@app.route('/api/ai/job_insights', methods=['POST'])
def mock_job_insights():
    data = request.json or {}
    job = data.get('job_name', 'unknown')
    ns = data.get('namespace', 'default')
    if 'failed' in job or 'import' in job:
        return jsonify({'status': 'Failed', 'gemini_powered': False,
            'summary': f'Job `{job}` failed after 3 retries. The import pipeline could not access the source S3 bucket.',
            'failure_reason': 'IAM role missing s3:GetObject on prod-data-lake bucket. Credentials expired.',
            'error_evidence': ['AccessDenied: s3:GetObject on arn:aws:s3:::prod-data-lake/events/2026-02-20/*.parquet'],
            'retry_strategy': 'Fix IAM role first, then delete and recreate the job.',
            'performance_insight': 'When healthy, completes in ~8 minutes.',
            'kubectl_hints': [f'kubectl delete job {job}', f'kubectl get events --field-selector involvedObject.name={job}']})
    elif 'report' in job:
        return jsonify({'status': 'Running', 'gemini_powered': False,
            'summary': f'Job `{job}` is processing chunks in parallel (3 active, 2 done). On track to complete in ~12min.',
            'failure_reason': 'No failure', 'error_evidence': [],
            'retry_strategy': 'No retry needed.',
            'performance_insight': 'Consider increasing parallelism from 3 to 5 to reduce runtime.',
            'kubectl_hints': [f'kubectl logs -l job-name={job} --tail=20', f'kubectl get pods -l job-name={job}']})
    else:
        return jsonify({'status': 'Succeeded', 'gemini_powered': False,
            'summary': f'Job `{job}` completed successfully. Well within SLA.',
            'failure_reason': 'No failure', 'error_evidence': [],
            'retry_strategy': 'No retry needed.',
            'performance_insight': 'Completed in under 2 minutes.',
            'kubectl_hints': [f'kubectl logs -l job-name={job}']})

@app.route('/api/ai/explain_resource', methods=['POST'])
def mock_explain_resource():
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('kind', 'ConfigMap')
    if kind == 'Secret':
        return jsonify({'purpose': f'Secret `{name}` holds database credentials (username + password) used to authenticate against PostgreSQL.',
            'key_breakdown': {'username': 'DB username for auth', 'password': 'DB password — rotate every 90 days'},
            'security_concerns': [
                {'severity': 'High', 'concern': 'Password mounted as plaintext env var (visible in kubectl describe pod)', 'recommendation': 'Use External Secrets Operator or Vault'},
                {'severity': 'Medium', 'concern': 'No rotation policy configured', 'recommendation': 'Set up automatic rotation via secrets management platform'},
            ],
            'recommendations': ['Use External Secrets Operator', 'Enable secret encryption at rest', 'Restrict RBAC to only the service account that needs this secret'],
            'risk_level': 'review',
            'rotation_advice': 'Rotate every 90 days minimum, immediately if breach suspected.',
            'gemini_powered': False})
    else:
        return jsonify({'purpose': f'ConfigMap `{name}` provides application-level configuration including timeouts, retry policies, and feature flags for connected services.',
            'key_breakdown': {'timeout': 'Request timeout in ms (5000 = 5s)', 'retries': 'HTTP retry count', 'theme': 'UI color theme', 'show_beta': 'Feature flag for beta users'},
            'security_concerns': [
                {'severity': 'Low', 'concern': 'show_beta=true exposes unstable features to all users', 'recommendation': 'Gate per-user with a feature flag service'},
            ],
            'recommendations': ['Use a dedicated feature flag service', 'Document key purposes in-line'],
            'risk_level': 'safe',
            'gemini_powered': False})




# ── NEW: Gemini Workloads AI Endpoints ──────────────────────────────────────

@app.route('/api/ai/health_pulse', methods=['POST'])
def mock_health_pulse():
    """Namespace-wide health score and top issues."""
    import time, random
    time.sleep(0.5)
    data = request.json or {}
    ns = data.get('namespace', 'default')
    workloads = data.get('workloads', [])
    total = max(len(workloads), 1)
    failing = [w for w in workloads if w.get('status') in ('Failed','CrashLoopBackOff','Error','OOMKilled','ImagePullBackOff')]
    score = max(10, 100 - int((len(failing)/total)*60) - random.randint(0,10))
    issues = []
    if failing:
        issues.append({'severity':'critical','resource':failing[0].get('name','unknown'),'kind':failing[0].get('type','Pod'),
            'issue':f"{failing[0].get('name')} is in **{failing[0].get('status')}** state — may cause service degradation.",
            'action':f"kubectl describe pod {failing[0].get('name')} -n {ns}"})
    issues += [
        {'severity':'warning','resource':'dbsleuth-dev-ml-inference','kind':'Deployment',
         'issue':'Running with **1 replica** — no redundancy. A pod failure will cause full outage.',
         'action':'kubectl scale deployment dbsleuth-dev-ml-inference --replicas=2'},
        {'severity':'info','resource':'dbsleuth-dev-billing-service','kind':'Deployment',
         'issue':'`LOG_LEVEL=DEBUG` detected — may expose sensitive data in production logs.',
         'action':'Set LOG_LEVEL=INFO in the ConfigMap or deployment env section'},
        {'severity':'info','resource':'api-token','kind':'Secret',
         'issue':'Secret `api-token` has not been rotated in **180 days** — exceeds 90-day policy.',
         'action':'kubectl create secret generic api-token --from-literal=token=$(openssl rand -base64 32)'}
    ]
    return jsonify({'score':score,'grade':'A' if score>=90 else('B' if score>=75 else('C' if score>=60 else 'D')),
        'namespace':ns,'total_resources':total,'failing_count':len(failing),'issues':issues[:4],
        'summary':f"Namespace **{ns}** is {'healthy' if score>=80 else 'showing signs of degradation'}. {len(failing)} resource(s) need attention.",
        'gemini_powered':False})


@app.route('/api/ai/health_check', methods=['POST'])
def mock_health_check():
    """Deployment/StatefulSet deep health verdict."""
    import time
    time.sleep(0.6)
    data = request.json or {}
    name = data.get('name','unknown')
    kind = data.get('kind','Deployment')
    ready = data.get('ready',1)
    total = data.get('total',1)
    ratio = ready / max(total,1)
    if ratio >= 1.0:
        verdict,verdict_color,verdict_icon,verdict_label = 'healthy','#0f9d58','✅','Healthy'
    elif ratio >= 0.5:
        verdict,verdict_color,verdict_icon,verdict_label = 'degraded','#e6a000','⚠️','Degraded'
    else:
        verdict,verdict_color,verdict_icon,verdict_label = 'critical','#dc3545','🔴','Critical'
    replica_advice = 'Replica count looks appropriate for a non-critical service.'
    if total == 1:
        replica_advice = '**Single replica detected** — no HA. Add at least 1 more replica to prevent downtime during updates.'
    elif total >= 5:
        replica_advice = f'Running {total} replicas — may be over-provisioned. Consider HPA to dynamically scale this.'
    return jsonify({'verdict':verdict,'verdict_label':verdict_label,'verdict_icon':verdict_icon,'verdict_color':verdict_color,
        'summary':f'**{name}** ({kind}) is **{ready}/{total}** pods ready.',
        'replica_advice':replica_advice,
        'rollout_recommendation':'Use rolling update with `maxUnavailable: 1` and `maxSurge: 1` to avoid downtime.',
        'resource_advice':'Set CPU/memory requests and limits to prevent noisy-neighbour issues. Recommended: `requests.cpu=100m`, `limits.cpu=500m`.',
        'kubectl_hints':[f'kubectl rollout status {kind.lower()}/{name}',f'kubectl describe {kind.lower()} {name}',
            f'kubectl get events --field-selector involvedObject.name={name} --sort-by=.lastTimestamp',
            f'kubectl top pods -l app={name.split("-")[0]}'],
        'gemini_powered':False})


@app.route('/api/ai/daemonset_insight', methods=['POST'])
def mock_daemonset_insight():
    """DaemonSet node coverage and toleration analysis."""
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name','unknown')
    ready = data.get('ready',3)
    total = data.get('total',3)
    missing = max(0, total - ready)
    return jsonify({'coverage_summary':f'`{name}` scheduled on **{ready}/{total}** nodes.',
        'missing_nodes':missing,'coverage_percent':int((ready/max(total,1))*100),
        'issues':[{'node':'gke-cluster-gpu-pool-001','reason':'Node taint `nvidia.com/gpu=present:NoSchedule` — DaemonSet toleration missing.',
            'fix':f'Add toleration to {name}: `key: nvidia.com/gpu, operator: Exists, effect: NoSchedule`'}] if missing>0 else [],
        'toleration_advice':'Tolerations correct for standard nodes. Add `nvidia.com/gpu` toleration if GPU nodes are in scope.' if missing==0 else 'Missing toleration preventing scheduling on specialised nodes.',
        'resource_usage':'DaemonSet pods consuming ~120Mi/node. Consider `resources.limits.memory=256Mi` if OOMKill events occur.',
        'kubectl_hints':[f'kubectl get daemonset {name} -o wide',f'kubectl describe daemonset {name}',f'kubectl get pods -l name={name.split("-")[0]} -o wide'],
        'gemini_powered':False})


@app.route('/api/ai/pod_triage', methods=['POST'])
def mock_pod_triage():
    """Smart pod log triage — error patterns, crash reason, sibling impact."""
    import time
    time.sleep(0.7)
    data = request.json or {}
    name = data.get('name','unknown')
    status = data.get('status','Running')
    crash_reason = 'OOMKilled' if 'ml' in name else ('CrashLoopBackOff' if 'backend' in name else 'Unknown')
    if status != 'Running':
        patterns = [
            {'pattern':'java.lang.OutOfMemoryError','count':14,'severity':'critical','last_seen':'2m ago'},
            {'pattern':'Connection refused (127.0.0.1:5432)','count':6,'severity':'high','last_seen':'8m ago'},
            {'pattern':'WARN  slow query detected (>500ms)','count':43,'severity':'medium','last_seen':'1m ago'},
        ]
    else:
        patterns = [
            {'pattern':'WARN  slow query detected (>500ms)','count':12,'severity':'medium','last_seen':'3m ago'},
            {'pattern':'INFO  cache miss ratio 38%','count':5,'severity':'low','last_seen':'5m ago'},
        ]
        crash_reason = None
    return jsonify({'pod':name,
        'triage_summary':f'Pod **{name}** — {len(patterns)} log pattern(s). {"Immediate action required." if status!="Running" else "Stable but has performance warnings."}',
        'crash_reason':crash_reason,'restart_advised':status not in ('Running','Succeeded'),
        'error_patterns':patterns,
        'affected_siblings':[{'name':name.rsplit('-',1)[0]+'-sidecar','relationship':'shares ConfigMap `app-config`','risk':'medium'}] if '-' in name else [],
        'recommended_action':'Increase memory limit from 512Mi to 1Gi and add `resources.requests.memory=512Mi`.' if crash_reason=='OOMKilled'
            else 'Check PostgreSQL connectivity and ensure DB service is reachable within the namespace.',
        'kubectl_hints':[f'kubectl logs {name} --previous --tail=50',f'kubectl describe pod {name}',f'kubectl top pod {name}'],
        'gemini_powered':False})


@app.route('/api/ai/configmap_impact', methods=['POST'])
def mock_configmap_impact():
    """Which workloads reference this ConfigMap and blast-radius analysis."""
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name','unknown')
    return jsonify({'configmap':name,
        'summary':f'ConfigMap **{name}** is referenced by **3 workloads** in this namespace.',
        'consumers':[
            {'name':'dbsleuth-dev-frontend-deployment','kind':'Deployment','mounted_as':'env','critical_keys':['API_ENDPOINT','TIMEOUT_MS']},
            {'name':'dbsleuth-dev-backend-api','kind':'Deployment','mounted_as':'volumeMount (/etc/config)','critical_keys':['DB_HOST','POOL_SIZE']},
            {'name':'nightly-report-job','kind':'Job','mounted_as':'env','critical_keys':['REPORT_RECIPIENTS']},
        ],
        'risky_keys':[
            {'key':'LOG_LEVEL','value':'DEBUG','risk':'medium','note':'Debug logging in production — may expose PII in logs'},
            {'key':'FEATURE_BETA','value':'true','risk':'low','note':'Beta feature flag active — ensure rollback plan exists'},
        ],
        'blast_radius':'Deleting or misconfiguring this ConfigMap would immediately break **2 running Deployments** and fail the next Job run.',
        'kubectl_hints':[f'kubectl get configmap {name} -o yaml', f'kubectl describe configmap {name}',
            f"kubectl get pods -o json | jq '.items[] | select(.spec.volumes[].configMap.name==\"{name}\") | .metadata.name'"],
        'gemini_powered':False})


@app.route('/api/ai/secret_audit', methods=['POST'])
def mock_secret_audit():
    """Full secret audit: freshness, consumers, orphan detection, rotation plan."""
    import time
    time.sleep(0.6)
    data = request.json or {}
    name = data.get('name','unknown')
    age = str(data.get('age','180d'))
    age_days = int(''.join(filter(str.isdigit, age)) or 90) if 'd' in age else 45
    overdue = age_days > 90
    return jsonify({'secret':name,'age_days':age_days,'rotation_overdue':overdue,
        'risk_level':'high' if overdue else 'medium',
        'risk_summary':f'Secret **{name}** is **{age_days} days old** — {"rotation OVERDUE (policy: 90 days)." if overdue else "within rotation policy."}',
        'consumers':[
            {'name':'dbsleuth-dev-backend-api','kind':'Deployment','mount_method':'secretRef (env)'},
            {'name':'dbsleuth-dev-billing-service','kind':'Deployment','mount_method':'volumeMount'},
        ],
        'is_orphaned':False,
        'security_flags':[
            {'severity':'high','message':'Secret mounted as env var — visible in process list and `kubectl describe pod`. Use volumeMount or Vault instead.'},
            {'severity':'medium','message':'No ServiceAccount RBAC restriction — any pod in the namespace can read this secret.'},
        ] if overdue else [
            {'severity':'low','message':'Consider restricting RBAC so only the consuming ServiceAccount can read this secret.'},
        ],
        'rotation_plan':{'recommended_interval':'90 days','next_rotation_by':'2026-03-15',
            'command':f'kubectl create secret generic {name} --from-literal=token=$(openssl rand -base64 32) --dry-run=client -o yaml | kubectl apply -f -'},
        'kubectl_hints':[f'kubectl get secret {name} -o yaml',f'kubectl describe secret {name}',
            f'kubectl auth can-i get secret/{name} --as=system:serviceaccount:default:default'],
        'gemini_powered':False})


# ── NEW: Gemini Networking AI Endpoints ────────────────────────────────────

@app.route('/api/ai/network_health', methods=['POST'])
def mock_network_health():
    """Network-wide health pulse for Services + VirtualServices."""
    import time, random
    time.sleep(0.4)
    data = request.json or {}
    ns = data.get('namespace', 'default')
    services = data.get('services', [])
    vs_list = data.get('virtual_services', [])

    lb_count = sum(1 for s in services if s.get('type') == 'LoadBalancer')
    nodeport_count = sum(1 for s in services if s.get('type') == 'NodePort')
    vs_count = len(vs_list)
    svc_count = len(services)
    score = max(20, 100 - lb_count * 8 - nodeport_count * 5 - (10 if vs_count == 0 and svc_count > 0 else 0))
    score = min(score, 100) - random.randint(0, 5)

    issues = []
    lb_svcs = [s['name'] for s in services if s.get('type') == 'LoadBalancer']
    if lb_svcs:
        issues.append({
            'severity': 'warning',
            'resource': lb_svcs[0], 'kind': 'Service',
            'issue': f'**{lb_svcs[0]}** is a LoadBalancer — externally exposed. Ensure firewall rules and NetworkPolicy are in place.',
            'action': f'kubectl describe service {lb_svcs[0]} -n {ns}'
        })
    if nodeport_count > 0:
        issues.append({
            'severity': 'warning',
            'resource': 'NodePort services', 'kind': 'Service',
            'issue': f'**{nodeport_count} NodePort** service(s) found — port exposed on every cluster node. Consider switching to ClusterIP + Ingress.',
            'action': f'kubectl get services -n {ns} --field-selector spec.type=NodePort'
        })
    if vs_count == 0 and svc_count > 0:
        issues.append({
            'severity': 'info',
            'resource': 'mesh coverage', 'kind': 'VirtualService',
            'issue': 'No VirtualServices found — traffic management (retries, timeouts, canary) is not configured for this namespace.',
            'action': 'Consider adding Istio VirtualService resources for fine-grained traffic control.'
        })
    issues.append({
        'severity': 'info',
        'resource': 'database-svc', 'kind': 'Service',
        'issue': 'Service `database-svc` on port **5432** has no VirtualService — no timeout or retry policy configured.',
        'action': f'kubectl apply -f database-svc-vs.yaml -n {ns}'
    })

    return jsonify({
        'score': score,
        'grade': 'A' if score >= 90 else ('B' if score >= 75 else ('C' if score >= 60 else 'D')),
        'namespace': ns,
        'service_count': svc_count,
        'vs_count': vs_count,
        'lb_count': lb_count,
        'issues': issues[:4],
        'summary': f'Namespace **{ns}** has {svc_count} services and {vs_count} VirtualServices. {lb_count} externally exposed.',
        'gemini_powered': False
    })


@app.route('/api/ai/service_analyze', methods=['POST'])
def mock_service_analyze():
    """Explains a Service purpose, selector targeting, port mapping."""
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name', 'unknown')
    svc_type = data.get('type', 'ClusterIP')
    ports = data.get('ports', '80')

    type_notes = {
        'ClusterIP': 'Internal-only service — accessible only within the cluster. This is the most secure service type.',
        'LoadBalancer': 'Externally exposed via a cloud load balancer. Ensure proper firewall rules and NetworkPolicy are configured.',
        'NodePort': 'Exposes the service on every node\'s IP at a static port. Avoid in production — use Ingress or LoadBalancer instead.',
        'ExternalName': 'Maps the service to an external DNS name. No proxying — DNS CNAME alias only.',
    }
    return jsonify({
        'service': name,
        'purpose': f'Service `{name}` routes traffic to pods matching its label selector. It acts as a stable internal DNS name and load balancer for its pod set.',
        'type_explanation': type_notes.get(svc_type, f'{svc_type} service type.'),
        'port_breakdown': [
            {'port': ports.split(':')[0] if ':' in ports else ports,
             'protocol': 'TCP',
             'target': ports.split(':')[1] if ':' in ports else ports,
             'note': 'Primary application port — ensure the target port matches your container\'s EXPOSE directive.'}
        ],
        'selector_advice': 'Ensure the selector labels match exactly the labels on your target pods. A mismatch will result in 503 errors with no obvious log output.',
        'health_check': 'No readiness probe detected on target pods — service may route to pods that are not yet ready.',
        'kubectl_hints': [
            f'kubectl describe service {name}',
            f'kubectl get endpoints {name}',
            f'kubectl get pods -l app={name.split("-")[0]} --show-labels',
        ],
        'gemini_powered': False
    })


@app.route('/api/ai/service_dependency', methods=['POST'])
def mock_service_dependency():
    """Which Pods/Deployments this service routes to, and which VSes expose it."""
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name', 'unknown')
    ns = data.get('namespace', 'default')
    base = name.split('-')[0]
    return jsonify({
        'service': name,
        'summary': f'Service **{name}** connects to **2 workloads** and is referenced by **1 VirtualService**.',
        'consumers': [
            {'name': f'{base}-deployment', 'kind': 'Deployment', 'ready': '2/2', 'relationship': 'selector match (app=' + base + ')'},
            {'name': f'{base}-pod-canary', 'kind': 'Pod', 'ready': '1/1', 'relationship': 'selector match (app=' + base + ', track=canary)'},
        ],
        'virtual_services': [
            {'name': f'{base}-vs', 'hosts': [name], 'exposes_externally': True}
        ],
        'ingresses': [],
        'blast_radius': f'Deleting `{name}` would break **{base}-deployment** immediately — DNS name would become unresolvable within the cluster.',
        'kubectl_hints': [
            f'kubectl get endpoints {name} -o yaml',
            f'kubectl get virtualservices -n {ns} -o yaml | grep -A5 {name}',
            f'kubectl get pods -n {ns} --show-labels | grep {base}',
        ],
        'gemini_powered': False
    })


@app.route('/api/ai/service_risk', methods=['POST'])
def mock_service_risk():
    """Security risk scan — exposure, NetworkPolicy, port conflicts."""
    import time
    time.sleep(0.6)
    data = request.json or {}
    name = data.get('name', 'unknown')
    svc_type = data.get('type', 'ClusterIP')
    ports = data.get('ports', '80')
    ns = data.get('namespace', 'default')

    risks = []
    if svc_type == 'LoadBalancer':
        risks.append({'severity': 'high', 'issue': f'`{name}` is a **LoadBalancer** — directly exposed to the internet. No firewall or WAF layer detected.',
                      'fix': 'Add a NetworkPolicy or restrict access via cloud firewall rules (source IP ranges).'})
        risks.append({'severity': 'medium', 'issue': 'No TLS termination detected on the LoadBalancer — traffic may be unencrypted in transit.',
                      'fix': 'Configure SSL certificate via cloud annotation or use an Ingress with TLS.'})
    elif svc_type == 'NodePort':
        risks.append({'severity': 'high', 'issue': '**NodePort** exposes a port on every node\'s external IP. This bypasses standard Ingress security controls.',
                      'fix': 'Switch to ClusterIP and add an Ingress resource with TLS termination.'})
    else:
        risks.append({'severity': 'low', 'issue': f'`{name}` is ClusterIP — internal only. No external exposure risk.',
                      'fix': 'Good. Ensure NetworkPolicy restricts which pods can reach this service.'})

    risks.append({'severity': 'medium', 'issue': 'No **NetworkPolicy** found restricting ingress to this service — any pod in the namespace can reach it.',
                  'fix': f'kubectl apply -f - <<EOF\napiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: allow-{name}\n  namespace: {ns}\nspec:\n  podSelector:\n    matchLabels:\n      app: {name.split("-")[0]}\n  ingress:\n  - from:\n    - podSelector:\n        matchLabels:\n          role: frontend\nEOF'})

    return jsonify({
        'service': name,
        'risk_level': 'high' if svc_type in ('LoadBalancer', 'NodePort') else 'low',
        'risk_summary': f'Service **{name}** ({svc_type}) — {"externally exposed, immediate action recommended." if svc_type in ("LoadBalancer","NodePort") else "internal only, low risk."}',
        'risks': risks,
        'kubectl_hints': [
            f'kubectl describe service {name} -n {ns}',
            f'kubectl get networkpolicies -n {ns}',
            f'kubectl auth can-i get service/{name} --as=system:serviceaccount:{ns}:default',
        ],
        'gemini_powered': False
    })


@app.route('/api/ai/vs_route_analysis', methods=['POST'])
def mock_vs_route_analysis():
    """VirtualService routing rules explained in plain English."""
    import time
    time.sleep(0.5)
    data = request.json or {}
    name = data.get('name', 'unknown')
    hosts = data.get('hosts', [])
    gateways = data.get('gateways', [])

    has_gateway = bool(gateways and gateways != [''])
    return jsonify({
        'virtual_service': name,
        'summary': f'VirtualService **{name}** manages traffic for host(s): `{"`, `".join(hosts) if hosts else name}`. {"Exposed via gateway — externally reachable." if has_gateway else "Mesh-internal only (no gateway)."}',
        'route_rules': [
            {'match': 'All traffic (no match condition)', 'destination': f'{name.replace("-vs","")}-svc', 'port': 80,
             'weight': 90, 'note': 'Stable version — receives 90% of traffic.'},
            {'match': 'header: x-canary: true', 'destination': f'{name.replace("-vs","")}-svc-canary', 'port': 80,
             'weight': 10, 'note': 'Canary version — 10% traffic split for gradual rollout.'},
        ],
        'timeout_policy': '30s global timeout — requests exceeding this are aborted with 504.',
        'retry_policy': '3 retries on 5xx errors with 2s per-try timeout.',
        'fault_injection': None,
        'issues': [
            {'severity': 'warning', 'issue': '10% canary weight detected. Ensure your canary pod is **ready and passing healthchecks** before increasing weight.',
             'fix': f'kubectl get pods -l track=canary -n default'}
        ],
        'kubectl_hints': [
            f'kubectl describe virtualservice {name}',
            f'kubectl get virtualservice {name} -o yaml',
            f'istioctl analyze -n default',
        ],
        'gemini_powered': False
    })


@app.route('/api/ai/vs_traffic_policy', methods=['POST'])
def mock_vs_traffic_policy():
    """Traffic policy health — canary split, misrouting risks, fault injection."""
    import time
    time.sleep(0.6)
    data = request.json or {}
    name = data.get('name', 'unknown')
    ns = data.get('namespace', 'default')
    return jsonify({
        'virtual_service': name,
        'policy_summary': f'VirtualService **{name}** has a **canary split (90/10)**. Traffic policy is partially configured.',
        'canary_health': {
            'status': 'active',
            'stable_weight': 90,
            'canary_weight': 10,
            'recommendation': 'Canary looks healthy. If error rates are acceptable, gradually increase canary to 25%, 50%, then 100%.'
        },
        'missing_policies': [
            {'policy': 'Circuit Breaker', 'severity': 'medium',
             'note': 'No DestinationRule with outlier detection — a failing upstream will not be ejected from the load balancer pool.',
             'fix': f'Add a DestinationRule with outlierDetection for {name.replace("-vs","")}-svc'},
            {'policy': 'Fault Injection', 'severity': 'low',
             'note': 'No fault injection configured — consider adding delay/abort faults for chaos testing in staging.'},
        ],
        'traffic_risks': [
            {'risk': 'No mTLS PeerAuthentication policy — traffic between services may be unencrypted within the mesh.',
             'severity': 'high', 'fix': f'kubectl apply PeerAuthentication with mtls mode STRICT in {ns}'}
        ],
        'kubectl_hints': [
            f'kubectl get virtualservice {name} -o yaml',
            f'kubectl get destinationrule -n {ns}',
            f'istioctl proxy-config cluster deploy/{name.replace("-vs","")} -n {ns}',
            f'kubectl get peerauthentication -n {ns}',
        ],
        'gemini_powered': False
    })


@app.route('/api/ai/self_heal', methods=['POST'])
def mock_self_heal():
    import random
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('kind', 'Deployment')
    status = data.get('status', 'CrashLoopBackOff')

    # Map status to mock diagnosis
    diagnoses = {
        'CrashLoopBackOff': {
            'root_cause': 'Container exits immediately due to a missing environment variable `DATABASE_URL`. The application panics on startup.',
            'confidence': 91,
            'error_type': 'CrashLoopBackOff',
            'action': 'restart',
            'action_label': 'Restart Deployment',
            'risk_level': 'low',
            'patch_preview': 'kubectl rollout restart deployment/' + name,
            'details': 'Pod has restarted 7 times in the last 10 minutes. Logs show: panic: DATABASE_URL not set.',
            'kubectl_hints': [
                'kubectl logs ' + name + ' -n default --previous',
                'kubectl describe pod -l app=' + name + ' -n default',
                'kubectl rollout restart deployment/' + name + ' -n default',
            ]
        },
        'OOMKilled': {
            'root_cause': 'Container exceeded its memory limit of 256Mi. The process was killed by the OOM killer.',
            'confidence': 97,
            'error_type': 'OOMKilled',
            'action': 'patch_resources',
            'action_label': 'Increase Memory Limit to 512Mi',
            'risk_level': 'medium',
            'patch_preview': 'kubectl patch deployment ' + name + ' -p \'{"spec":{"template":{"spec":{"containers":[{"name":"' + name + '","resources":{"limits":{"memory":"512Mi"}}}]}}}}\'',
            'details': 'Memory limit was 256Mi. Peak usage reached 254Mi before OOM kill. Recommend doubling limit.',
            'kubectl_hints': [
                'kubectl top pod -l app=' + name + ' -n default',
                'kubectl describe pod -l app=' + name + ' -n default | grep -A5 OOM',
            ]
        },
        'ImagePullBackOff': {
            'root_cause': 'Image `gcr.io/my-project/frontend:lates` not found — likely a typo in the tag (`lates` instead of `latest`).',
            'confidence': 88,
            'error_type': 'ImagePullBackOff',
            'action': 'patch_image',
            'action_label': 'Fix Image Tag to :latest',
            'risk_level': 'medium',
            'patch_preview': 'kubectl set image deployment/' + name + ' ' + name + '=gcr.io/my-project/frontend:latest',
            'details': 'Event: Failed to pull image "gcr.io/my-project/frontend:lates": rpc error: not found.',
            'kubectl_hints': [
                'kubectl describe pod -l app=' + name + ' -n default | grep -i image',
                'kubectl set image deployment/' + name + ' ' + name + '=gcr.io/my-project/frontend:latest -n default',
            ]
        },
        'ErrImagePull': {
            'root_cause': 'Image pull failed due to missing `imagePullSecret`. The registry requires authentication.',
            'confidence': 85,
            'error_type': 'ErrImagePull',
            'action': 'patch_image',
            'action_label': 'Add imagePullSecret',
            'risk_level': 'medium',
            'patch_preview': 'kubectl patch deployment ' + name + ' -p \'{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}}}\'',
            'details': 'Event: Failed to pull image: unauthorized: authentication required.',
            'kubectl_hints': [
                'kubectl get secrets -n default | grep docker',
                'kubectl patch serviceaccount default -p \'{"imagePullSecrets":[{"name":"regcred"}]}\' -n default',
            ]
        },
        'Pending': {
            'root_cause': 'Pod has been Pending for 8 minutes. No nodes match the nodeSelector `disktype=ssd`. Only 0/3 nodes have this label.',
            'confidence': 83,
            'error_type': 'Pending',
            'action': 'patch_selector',
            'action_label': 'Remove Invalid NodeSelector',
            'risk_level': 'low',
            'patch_preview': 'kubectl patch deployment ' + name + ' --type=json -p \'[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]\'',
            'details': 'Scheduler event: 0/3 nodes matched node selector. Suggested fix: remove or correct nodeSelector.',
            'kubectl_hints': [
                'kubectl get nodes --show-labels | grep disktype',
                'kubectl describe pod -l app=' + name + ' -n default | grep -A5 Events',
            ]
        },
        'Failed': {
            'root_cause': 'Deployment was updated 12 minutes ago and pods immediately began failing. Likely a bad configuration in the latest revision.',
            'confidence': 78,
            'error_type': 'Failed',
            'action': 'rollback',
            'action_label': 'Rollback to Previous Revision',
            'risk_level': 'low',
            'patch_preview': 'kubectl rollout undo deployment/' + name,
            'details': 'kubectl rollout history shows revision 4 introduced the failure. Revision 3 was stable.',
            'kubectl_hints': [
                'kubectl rollout history deployment/' + name + ' -n default',
                'kubectl rollout undo deployment/' + name + ' -n default',
                'kubectl rollout status deployment/' + name + ' -n default',
            ]
        },
    }

    diag = diagnoses.get(status, {
        'root_cause': 'AI identified an unexpected container failure. Recommend checking recent config changes and pod events.',
        'confidence': 65,
        'error_type': status,
        'action': 'restart',
        'action_label': 'Restart Pod',
        'risk_level': 'low',
        'patch_preview': 'kubectl delete pod -l app=' + name + ' -n default',
        'details': 'No specific pattern matched. Manual investigation recommended.',
        'kubectl_hints': [
            'kubectl describe pod -l app=' + name + ' -n default',
            'kubectl logs -l app=' + name + ' -n default',
        ]
    })

    return jsonify({
        'name': name,
        'kind': kind,
        'status': status,
        **diag
    })


@app.route('/api/heal/execute', methods=['POST'])
def mock_heal_execute():
    data = request.json or {}
    name = data.get('name', 'unknown')
    kind = data.get('kind', 'Deployment')
    action = data.get('action', 'restart')
    dry_run = data.get('dry_run', False)

    action_messages = {
        'restart':         f'Restarted {kind} {name} — new pods will be created within 30 seconds.',
        'rollback':        f'Rolled back {kind} {name} to previous revision.',
        'patch_resources': f'Memory limit for {kind} {name} patched to 512Mi.',
        'patch_image':     f'Image tag for {kind} {name} corrected to :latest.',
        'patch_selector':  f'NodeSelector removed from {kind} {name}.',
        'delete_pod':      f'Failed pod deleted — {kind} controller will recreate it.',
    }

    msg = action_messages.get(action, f'Action {action} applied to {name}.')

    if dry_run:
        return jsonify({
            'status': 'dry_run',
            'message': f'[DRY RUN] Would apply: {msg}',
            'applied': False,
            'dry_run': True
        })

    return jsonify({
        'status': 'success',
        'message': msg,
        'applied': True,
        'dry_run': False
    })


@app.route('/api/vuln_scan')
def mock_vuln_scan():
    """Mock OSS Vulnerability Scan endpoint — simulates Trivy output."""
    risks = [
        {
            "severity": "Critical",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-frontend-deployment",
            "kind": "Deployment",
            "image": "nginx:1.21.0",
            "package": "nginx",
            "installed_version": "1.21.0",
            "fixed_version": "1.25.3",
            "issue": "CVE-2021-23017 — nginx resolver off-by-one heap write allows remote code execution via crafted DNS response",
            "remediation": "kubectl set image deployment/dbsleuth-dev-frontend-deployment main=nginx:1.25.3",
            "cve_references": ["CVE-2021-23017"],
            "ai_insight": "This nginx version predates multiple critical patches; updating to 1.25.3 resolves all known RCE vectors."
        },
        {
            "severity": "Critical",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-backend-api",
            "kind": "Deployment",
            "image": "python:3.9-slim",
            "package": "openssl",
            "installed_version": "1.1.1k",
            "fixed_version": "1.1.1n",
            "issue": "CVE-2022-0778 — OpenSSL infinite loop via malformed certificate allows denial of service",
            "remediation": "Rebuild image on python:3.11-slim or python:3.9-slim-bookworm (includes patched openssl)",
            "cve_references": ["CVE-2022-0778"],
            "ai_insight": "Base OS packages in python:3.9-slim are outdated; pinning to a newer slim variant mitigates this without code changes."
        },
        {
            "severity": "High",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-billing-service",
            "kind": "Deployment",
            "image": "node:16-alpine",
            "package": "zlib",
            "installed_version": "1.2.11",
            "fixed_version": "1.2.12",
            "issue": "CVE-2018-25032 — zlib memory corruption when compressing certain inputs (ZLIB_MODIFIER stack overflow)",
            "remediation": "Rebuild on node:18-alpine or node:20-alpine (zlib >= 1.2.12 in musl libc)",
            "cve_references": ["CVE-2018-25032"],
            "ai_insight": "node:16-alpine reached EOL in Sept 2023; migrating to node:20-alpine addresses this and several other OS-level CVEs."
        },
        {
            "severity": "High",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-backend-api",
            "kind": "Deployment",
            "image": "python:3.9-slim",
            "package": "pip (cryptography)",
            "installed_version": "38.0.1",
            "fixed_version": "41.0.6",
            "issue": "CVE-2023-49083 — cryptography library NULL pointer dereference via malformed PKCS12 data",
            "remediation": "Add RUN pip install --upgrade cryptography>=41.0.6 to Dockerfile",
            "cve_references": ["CVE-2023-49083"],
            "ai_insight": "Python dependency cryptography 38.x has multiple CVEs; upgrading pip dependencies as part of the build is best practice."
        },
        {
            "severity": "High",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-ml-inference",
            "kind": "Deployment",
            "image": "pytorch/pytorch:1.13.0-cuda11.6-cudnn8-runtime",
            "package": "torch",
            "installed_version": "1.13.0",
            "fixed_version": "2.0.1",
            "issue": "CVE-2022-45907 — PyTorch deserialization of untrusted data via torch.load() allows arbitrary code execution",
            "remediation": "Update to pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime and pin torch>=2.0.1",
            "cve_references": ["CVE-2022-45907"],
            "ai_insight": "ML inference workloads that persist model artifacts via torch.load() are particularly exposed; upgrading and using weights_only=True is mandatory."
        },
        {
            "severity": "Medium",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-frontend-deployment",
            "kind": "Deployment",
            "image": "nginx:1.21.0",
            "package": "libssl1.1",
            "installed_version": "1.1.1k",
            "fixed_version": "1.1.1n",
            "issue": "CVE-2022-0778 — OpenSSL infinite loop in BN_mod_sqrt() when parsing EC certificates",
            "remediation": "Update base image to nginx:1.25.3 (ships with patched libssl)",
            "cve_references": ["CVE-2022-0778"],
            "ai_insight": "Base image update to nginx:1.25.3 resolves this along with the Critical CVE-2021-23017 finding above."
        },
        {
            "severity": "Medium",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-billing-service",
            "kind": "Deployment",
            "image": "node:16-alpine",
            "package": "npm (glob-parent)",
            "installed_version": "5.1.1",
            "fixed_version": "5.1.2",
            "issue": "CVE-2020-28469 — glob-parent ReDoS vulnerable to catastrophic backtracking on crafted input",
            "remediation": "npm audit fix --force inside the image build, or update to node:18-alpine",
            "cve_references": ["CVE-2020-28469"],
            "ai_insight": "ReDoS in glob-parent affects any server that accepts user-controlled file path inputs."
        },
        {
            "severity": "Low",
            "category": "OSS Vulnerability",
            "resource": "dbsleuth-dev-backend-api",
            "kind": "Deployment",
            "image": "python:3.9-slim",
            "package": "curl",
            "installed_version": "7.74.0",
            "fixed_version": "7.86.0",
            "issue": "CVE-2022-32207 — curl insufficient validation of cookies can lead to cookie injection",
            "remediation": "RUN apt-get upgrade curl in Dockerfile, or migrate to python:3.11-slim",
            "cve_references": ["CVE-2022-32207"],
            "ai_insight": "Low-severity curl issue; lower priority than the cryptography and OpenSSL findings in this workload."
        },
    ]

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for r in risks:
        severity_counts[r["severity"]] = severity_counts.get(r["severity"], 0) + 1

    return jsonify({
        "scan_source": "trivy-mock",
        "images_scanned": 4,
        "trivy_version": "0.48.3 (mock)",
        "executive_summary": (
            "OSS vulnerability scan found 2 Critical CVEs (nginx RCE and OpenSSL DoS) across 4 images. "
            "The frontend nginx:1.21.0 image is the most urgent — a single image update to nginx:1.25.3 eliminates both the Critical and Medium findings. "
            "The ML inference workload is running a 2-year-old PyTorch base; rebuilding on PyTorch 2.1.0 is strongly recommended."
        ),
        "severity_counts": severity_counts,
        "risks": risks
    })



# ── Terminal / Console ─────────────────────────────────────────────────
@socketio.on('connect_terminal')
def handle_connect_terminal(data):
    """Mock terminal connection — emits a welcome banner + prompt."""
    pod_name = data.get('pod', '')
    container_name = data.get('container', '')
    emit('terminal_output', {'data': f'\x1b[1;32mConnected to {pod_name} / {container_name}\x1b[0m\r\n'})
    emit('terminal_output', {'data': f'root@{pod_name}:/app# '})
    # Simulate some output for unhealthy pods
    if 'crash' in pod_name or 'processor' in pod_name:
        import time; time.sleep(0.3)
        emit('terminal_output', {'data': '\r\n[ERROR] ConnectionRefused: Failed to connect to DB\r\n'})
        emit('terminal_output', {'data': f'root@{pod_name}:/app# '})
    elif 'oom' in pod_name:
        import time; time.sleep(0.3)
        emit('terminal_output', {'data': '\r\n[KERN] OutOfMemory: Kill process 123 (java)\r\nKilled\r\n'})

@socketio.on('terminal_input')
def handle_terminal_input(data):
    """Echo back user input as mock shell response."""
    text = data.get('data', '')
    if text == '\r':
        emit('terminal_output', {'data': '\r\nroot@pod:/app# '})
    else:
        emit('terminal_output', {'data': text})


@app.route('/api/deployments/<name>/pods')
def get_deployment_pods(name):
    """Return mock pods + containers for a deployment (used by Console)."""
    ns = request.args.get('namespace', 'default')
    if 'backend' in name:
        pods = [{'name': f'{name}-pod-abc12', 'containers': [
            {'name': 'api-server', 'image': 'backend-api:v2.1.0'},
            {'name': 'sidecar-proxy', 'image': 'envoy:v1.27.0'}
        ]}]
    elif 'billing' in name:
        pods = [{'name': f'{name}-pod-def34', 'containers': [
            {'name': 'billing-app', 'image': 'billing-service:v3.0'},
            {'name': 'sidecar-proxy', 'image': 'envoy:v1.27.0'},
            {'name': 'log-collector', 'image': 'fluentbit:2.2.0'}
        ]}]
    elif 'database' in name:
        pods = [{'name': f'{name}-0', 'containers': [
            {'name': 'postgres', 'image': 'postgres:15'}
        ]}]
    else:
        pods = [{'name': f'{name}-pod-xyz99', 'containers': [
            {'name': name.split('-')[0], 'image': f'{name.split("-")[0]}:latest'}
        ]}]
    return jsonify({'pods': pods})


if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    from geventwebsocket.handler import WebSocketHandler
    print(" * Starting mock GDC Dashboard on http://127.0.0.1:8080")
    server = WSGIServer(('127.0.0.1', 8080), app, handler_class=WebSocketHandler)
    server.serve_forever()
