#!/bin/bash
BASE="http://127.0.0.1:8080"
NS="namespace-dev"
PASS=0
FAIL=0
ERRORS=""

test_endpoint() {
    local method="$1" url="$2" data="$3" desc="$4"
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" --max-time 10 "$url" 2>&1)
    else
        response=$(curl -s -w "\n%{http_code}" --max-time 10 -X POST -H "Content-Type: application/json" -d "$data" "$url" 2>&1)
    fi
    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed '$d')
    if [ "$http_code" = "200" ]; then
        echo "$body" | python3 -m json.tool > /dev/null 2>&1
        if [ $? -eq 0 ]; then PASS=$((PASS+1)); echo "✅ $desc"
        elif echo "$body" | head -1 | grep -q "<!DOCTYPE\|<html"; then PASS=$((PASS+1)); echo "✅ $desc (HTML)"
        else FAIL=$((FAIL+1)); echo "❌ $desc (invalid JSON)"; ERRORS="$ERRORS\n  ❌ $desc: invalid JSON"; fi
    else FAIL=$((FAIL+1)); echo "❌ $desc (HTTP $http_code)"; ERRORS="$ERRORS\n  ❌ $desc: HTTP $http_code"; fi
}

echo "═══════════════════════════════════════════════════════"
echo "  GDC Dashboard — Corrected E2E Test Suite"
echo "═══════════════════════════════════════════════════════"

echo ""
echo "── Page & Core APIs ──────────────────────────────────"
test_endpoint GET "$BASE/" "" "Main page loads"
test_endpoint GET "$BASE/api/workloads?namespace=$NS" "" "List workloads"
test_endpoint GET "$BASE/api/services?namespace=$NS" "" "List services"
test_endpoint GET "$BASE/api/virtualservices?namespace=$NS" "" "List VirtualServices"

echo ""
echo "── YAML API ──────────────────────────────────────────"
test_endpoint GET "$BASE/api/yaml/namespace-dev-frontend-deployment?type=Deployment&namespace=$NS" "" "YAML: Deployment"
test_endpoint GET "$BASE/api/yaml/namespace-dev-frontend-pod-1?type=Pod&namespace=$NS" "" "YAML: Pod"
test_endpoint GET "$BASE/api/yaml/namespace-dev-app-config?type=ConfigMap&namespace=$NS" "" "YAML: ConfigMap"
test_endpoint GET "$BASE/api/yaml/namespace-dev-db-creds?type=Secret&namespace=$NS" "" "YAML: Secret"
test_endpoint GET "$BASE/api/yaml/namespace-dev-database-statefulset?type=StatefulSet&namespace=$NS" "" "YAML: StatefulSet"

echo ""
echo "── Deployment → Pods ─────────────────────────────────"
test_endpoint GET "$BASE/api/deployments/namespace-dev-backend-api/pods?namespace=$NS" "" "Pods: backend"
test_endpoint GET "$BASE/api/deployments/namespace-dev-billing-service/pods?namespace=$NS" "" "Pods: billing"
test_endpoint GET "$BASE/api/deployments/namespace-dev-frontend-deployment/pods?namespace=$NS" "" "Pods: frontend"
test_endpoint GET "$BASE/api/deployments/namespace-dev-database-statefulset/pods?namespace=$NS" "" "Pods: database"

echo ""
echo "── AI Health ─────────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/health_pulse" '{"namespace":"'$NS'","workloads":[{"name":"test","status":"Running","type":"Pod"}]}' "Health pulse"
test_endpoint POST "$BASE/api/ai/health_check" '{"name":"deploy","kind":"Deployment","ready":2,"total":2}' "Health check (OK)"
test_endpoint POST "$BASE/api/ai/health_check" '{"name":"deploy","kind":"Deployment","ready":0,"total":2}' "Health check (critical)"

echo ""
echo "── AI Workload Analysis ──────────────────────────────"
test_endpoint POST "$BASE/api/ai/pod_triage" '{"name":"pod-crash","status":"CrashLoopBackOff"}' "Pod triage (crash)"
test_endpoint POST "$BASE/api/ai/pod_triage" '{"name":"pod-ok","status":"Running"}' "Pod triage (running)"
test_endpoint POST "$BASE/api/ai/daemonset_insight" '{"name":"log-collector","ready":3,"total":3}' "DaemonSet insight (full)"
test_endpoint POST "$BASE/api/ai/daemonset_insight" '{"name":"log-collector","ready":2,"total":3}' "DaemonSet insight (gap)"
test_endpoint POST "$BASE/api/ai/configmap_impact" '{"name":"app-config"}' "ConfigMap impact"
test_endpoint POST "$BASE/api/ai/secret_audit" '{"name":"db-creds","age":"180d"}' "Secret audit (overdue)"
test_endpoint POST "$BASE/api/ai/secret_audit" '{"name":"db-creds","age":"30d"}' "Secret audit (ok)"
test_endpoint POST "$BASE/api/ai/explain_resource" '{"name":"app-config","kind":"ConfigMap"}' "Explain ConfigMap"
test_endpoint POST "$BASE/api/ai/explain_resource" '{"name":"db-creds","kind":"Secret"}' "Explain Secret"

echo ""
echo "── AI Self-Heal ──────────────────────────────────────"
for s in CrashLoopBackOff OOMKilled ImagePullBackOff ErrImagePull Pending Failed; do
    test_endpoint POST "$BASE/api/ai/self_heal" "{\"name\":\"test\",\"kind\":\"Deployment\",\"status\":\"$s\"}" "Self-heal ($s)"
done
test_endpoint POST "$BASE/api/heal/execute" '{"name":"test","kind":"Deployment","action":"restart","dry_run":true}' "Heal execute (dry)"
test_endpoint POST "$BASE/api/heal/execute" '{"name":"test","kind":"Deployment","action":"rollback","dry_run":false}' "Heal execute (rollback)"

echo ""
echo "── AI Network ────────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/network_health" '{"namespace":"'$NS'","services":[{"name":"svc","type":"ClusterIP"}],"virtual_services":[]}' "Network health"
test_endpoint POST "$BASE/api/ai/service_analyze" '{"name":"svc","type":"ClusterIP","ports":"80:8080"}' "Service analyze"
test_endpoint POST "$BASE/api/ai/service_dependency" '{"name":"svc","namespace":"'$NS'"}' "Service dependency"
test_endpoint POST "$BASE/api/ai/service_risk" '{"name":"svc","type":"LoadBalancer","ports":"443","namespace":"'$NS'"}' "Service risk (LB)"
test_endpoint POST "$BASE/api/ai/service_risk" '{"name":"svc","type":"NodePort","ports":"30080","namespace":"'$NS'"}' "Service risk (NodePort)"
test_endpoint POST "$BASE/api/ai/service_risk" '{"name":"svc","type":"ClusterIP","ports":"80","namespace":"'$NS'"}' "Service risk (ClusterIP)"
test_endpoint POST "$BASE/api/ai/vs_route_analysis" '{"name":"vs","hosts":["test.com"],"gateways":["gw"]}' "VS route analysis"
test_endpoint POST "$BASE/api/ai/vs_traffic_policy" '{"name":"vs","namespace":"'$NS'"}' "VS traffic policy"

echo ""
echo "── Vuln Scan ─────────────────────────────────────────"
test_endpoint GET "$BASE/api/vuln_scan" "" "Vulnerability scan"

echo ""
echo "── Chat (Converse) ───────────────────────────────────"
test_endpoint POST "$BASE/api/ai/converse" '{"message":"Why is payment crashing?","session_id":"test123","namespace":"'$NS'","workloads":[]}' "AI converse"
test_endpoint POST "$BASE/api/ai/chat" '{"message":"test"}' "AI chat (legacy)"

echo ""
echo "── Optimizer ─────────────────────────────────────────"
test_endpoint GET "$BASE/api/ai/optimize?namespace=$NS" "" "Optimizer (GET)"

echo ""
echo "── YAML Generator ────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/generate_yaml" '{"description":"nginx deployment 3 replicas"}' "YAML generator"

echo ""
echo "── ConfigMap Explain (GET) ───────────────────────────"
test_endpoint GET "$BASE/api/ai/explain_configmap?name=app-config&namespace=$NS" "" "Explain ConfigMap (GET)"

echo ""
echo "── Pod Logs ──────────────────────────────────────────"
test_endpoint GET "$BASE/api/pod/namespace-dev-frontend-pod-1/logs?namespace=$NS" "" "Pod logs"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  TOTAL: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════"
if [ $FAIL -gt 0 ]; then echo ""; echo "FAILURES:"; echo -e "$ERRORS"; fi
