#!/bin/bash
BASE="http://127.0.0.1:8080"
NS="namespace-dev"
PASS=0
FAIL=0
ERRORS=""

test_endpoint() {
    local method="$1"
    local url="$2"
    local data="$3"
    local desc="$4"
    
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" --max-time 10 "$url" 2>&1)
    else
        response=$(curl -s -w "\n%{http_code}" --max-time 10 -X POST -H "Content-Type: application/json" -d "$data" "$url" 2>&1)
    fi
    
    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ]; then
        # Check if response is valid JSON
        echo "$body" | python3 -m json.tool > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            PASS=$((PASS+1))
            echo "✅ PASS: $desc (HTTP $http_code)"
        else
            # Maybe it's HTML (for the main page)
            if echo "$body" | head -1 | grep -q "<!DOCTYPE\|<html"; then
                PASS=$((PASS+1))
                echo "✅ PASS: $desc (HTTP $http_code, HTML)"
            else
                FAIL=$((FAIL+1))
                echo "❌ FAIL: $desc (HTTP $http_code, invalid JSON)"
                ERRORS="$ERRORS\n  - $desc: Invalid JSON response"
            fi
        fi
    else
        FAIL=$((FAIL+1))
        echo "❌ FAIL: $desc (HTTP $http_code)"
        ERRORS="$ERRORS\n  - $desc: HTTP $http_code"
    fi
}

echo "═══════════════════════════════════════════════════════"
echo "  GDC Dashboard E2E API Test Suite"
echo "═══════════════════════════════════════════════════════"
echo ""

echo "── Core Pages ────────────────────────────────────────"
test_endpoint GET "$BASE/" "" "Main page loads"

echo ""
echo "── Workloads API ─────────────────────────────────────"
test_endpoint GET "$BASE/api/workloads?namespace=$NS" "" "List workloads"
test_endpoint GET "$BASE/api/yaml/namespace-dev-frontend-deployment?type=Deployment&namespace=$NS" "" "Get deployment YAML"
test_endpoint GET "$BASE/api/yaml/namespace-dev-frontend-pod-1?type=Pod&namespace=$NS" "" "Get pod YAML"
test_endpoint GET "$BASE/api/yaml/namespace-dev-app-config?type=ConfigMap&namespace=$NS" "" "Get configmap YAML"
test_endpoint GET "$BASE/api/yaml/namespace-dev-db-creds?type=Secret&namespace=$NS" "" "Get secret YAML"

echo ""
echo "── Networking API ────────────────────────────────────"
test_endpoint GET "$BASE/api/networking?namespace=$NS" "" "List networking resources"

echo ""
echo "── Deployment Pods API ───────────────────────────────"
test_endpoint GET "$BASE/api/deployments/namespace-dev-backend-api/pods?namespace=$NS" "" "Get deployment pods (backend)"
test_endpoint GET "$BASE/api/deployments/namespace-dev-billing-service/pods?namespace=$NS" "" "Get deployment pods (billing)"
test_endpoint GET "$BASE/api/deployments/namespace-dev-frontend-deployment/pods?namespace=$NS" "" "Get deployment pods (frontend)"

echo ""
echo "── AI Health Endpoints ───────────────────────────────"
test_endpoint POST "$BASE/api/ai/health_pulse" '{"namespace":"'$NS'","workloads":[{"name":"test","status":"Running","type":"Pod"}]}' "Health pulse"
test_endpoint POST "$BASE/api/ai/health_check" '{"name":"test-deploy","kind":"Deployment","ready":2,"total":2}' "Health check (healthy)"
test_endpoint POST "$BASE/api/ai/health_check" '{"name":"test-deploy","kind":"Deployment","ready":0,"total":2}' "Health check (critical)"

echo ""
echo "── AI Workload Analysis ──────────────────────────────"
test_endpoint POST "$BASE/api/ai/pod_triage" '{"name":"test-pod","status":"CrashLoopBackOff"}' "Pod triage (crash)"
test_endpoint POST "$BASE/api/ai/pod_triage" '{"name":"test-pod","status":"Running"}' "Pod triage (running)"
test_endpoint POST "$BASE/api/ai/daemonset_insight" '{"name":"log-collector","ready":3,"total":3}' "DaemonSet insight (full coverage)"
test_endpoint POST "$BASE/api/ai/daemonset_insight" '{"name":"log-collector","ready":2,"total":3}' "DaemonSet insight (missing node)"
test_endpoint POST "$BASE/api/ai/configmap_impact" '{"name":"app-config"}' "ConfigMap impact"
test_endpoint POST "$BASE/api/ai/secret_audit" '{"name":"db-creds","age":"180d"}' "Secret audit (overdue)"
test_endpoint POST "$BASE/api/ai/secret_audit" '{"name":"db-creds","age":"30d"}' "Secret audit (ok)"

echo ""
echo "── AI Self-Heal ──────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/self_heal" '{"name":"test","kind":"Deployment","status":"CrashLoopBackOff"}' "Self-heal (CrashLoop)"
test_endpoint POST "$BASE/api/ai/self_heal" '{"name":"test","kind":"Deployment","status":"OOMKilled"}' "Self-heal (OOMKilled)"
test_endpoint POST "$BASE/api/ai/self_heal" '{"name":"test","kind":"Deployment","status":"ImagePullBackOff"}' "Self-heal (ImagePull)"
test_endpoint POST "$BASE/api/ai/self_heal" '{"name":"test","kind":"Deployment","status":"Pending"}' "Self-heal (Pending)"
test_endpoint POST "$BASE/api/ai/self_heal" '{"name":"test","kind":"Deployment","status":"Failed"}' "Self-heal (Failed)"
test_endpoint POST "$BASE/api/heal/execute" '{"name":"test","kind":"Deployment","action":"restart","dry_run":true}' "Heal execute (dry run)"
test_endpoint POST "$BASE/api/heal/execute" '{"name":"test","kind":"Deployment","action":"restart","dry_run":false}' "Heal execute (live)"

echo ""
echo "── AI Network Analysis ───────────────────────────────"
test_endpoint POST "$BASE/api/ai/network_health" '{"namespace":"'$NS'","services":[{"name":"test-svc","type":"ClusterIP"}],"virtual_services":[]}' "Network health pulse"
test_endpoint POST "$BASE/api/ai/service_analyze" '{"name":"test-svc","type":"ClusterIP","ports":"80:8080"}' "Service analyze"
test_endpoint POST "$BASE/api/ai/service_dependency" '{"name":"test-svc","namespace":"'$NS'"}' "Service dependency"
test_endpoint POST "$BASE/api/ai/service_risk" '{"name":"test-svc","type":"LoadBalancer","ports":"443","namespace":"'$NS'"}' "Service risk (LoadBalancer)"
test_endpoint POST "$BASE/api/ai/service_risk" '{"name":"test-svc","type":"ClusterIP","ports":"80","namespace":"'$NS'"}' "Service risk (ClusterIP)"
test_endpoint POST "$BASE/api/ai/vs_route_analysis" '{"name":"test-vs","hosts":["test.example.com"],"gateways":["istio-gateway"]}' "VS route analysis"
test_endpoint POST "$BASE/api/ai/vs_traffic_policy" '{"name":"test-vs","namespace":"'$NS'"}' "VS traffic policy"

echo ""
echo "── Vulnerability Scan ────────────────────────────────"
test_endpoint GET "$BASE/api/vuln_scan" "" "Vulnerability scan"

echo ""
echo "── AI Chat ───────────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/ask" '{"question":"Why is my pod crashing?","namespace":"'$NS'"}' "AI chat question"

echo ""
echo "── Smart Resource Optimizer ──────────────────────────"
test_endpoint POST "$BASE/api/ai/optimizer" '{"namespace":"'$NS'","workloads":[{"name":"test-deploy","type":"Deployment","status":"Running","ready":2,"total":2}]}' "Resource optimizer"

echo ""
echo "── YAML Generator ────────────────────────────────────"
test_endpoint POST "$BASE/api/ai/generate_yaml" '{"description":"Create a deployment for nginx with 3 replicas"}' "YAML generator"

echo ""
echo "── Explain Resource ──────────────────────────────────"
test_endpoint POST "$BASE/api/explain_resource" '{"name":"app-config","kind":"ConfigMap"}' "Explain ConfigMap"
test_endpoint POST "$BASE/api/explain_resource" '{"name":"db-creds","kind":"Secret"}' "Explain Secret"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════"
if [ $FAIL -gt 0 ]; then
    echo ""
    echo "Failed tests:"
    echo -e "$ERRORS"
fi
echo ""
