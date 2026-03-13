from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, disconnect
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream
import os
import threading
import json
from datetime import datetime, timedelta

# ── Gemini / Vertex AI — lightweight SDK (google-genai) ─────────────────────
# Replaces google-cloud-aiplatform (heavy, 30-90s import on low-CPU pods)
# with google-genai which imports in ~2s — no native gRPC deps.
#
# Set these env vars in your deployment:
#   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
#   GCP_PROJECT_ID=your-gcp-project-id
#   GCP_REGION=us-central1   (or your Vertex AI region)
# ─────────────────────────────────────────────────────────────────────────────
_client       = None   # google.genai.Client (Vertex AI backend)
_client_lock  = threading.Lock()
_client_ready = False
_client_error = None   # last init error — exposed via /api/ai/status

GEMINI_MODEL = "gemini-2.5-flash"

def get_model():
    """Return a ready google.genai.Client (Vertex AI), or None if unavailable.

    Route functions call:  client = get_model()
                           resp   = client.models.generate_content(model=GEMINI_MODEL, contents=...)
    Thread-safe lazy init via double-checked locking.
    """
    global _client, _client_ready
    if _client_ready:
        return _client
    with _client_lock:
        if _client_ready:
            return _client
        try:
            from google import genai
            from google.oauth2 import service_account

            sa_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
            project     = os.getenv("GCP_PROJECT_ID", "")
            location    = os.getenv("GCP_REGION", "us-central1")

            if not sa_key_path:
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set")
            if not project:
                raise ValueError("GCP_PROJECT_ID is not set")

            creds = service_account.Credentials.from_service_account_file(
                sa_key_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            sa_email = json.load(open(sa_key_path)).get("client_email", "?")

            _client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                credentials=creds,
            )
            import google.genai as _genai_check
            print(f"[AI] google-genai ready: {GEMINI_MODEL} "
                  f"({project}/{location}) | SA: {sa_email} "
                  f"| sdk={_genai_check.__version__}")
            # Sanity-check that the Models API is present in this version
            if not hasattr(_client.models, 'generate_content'):
                raise RuntimeError(
                    f"google-genai {_genai_check.__version__} client.models has no "
                    f"generate_content - pin google-genai==1.47.0 in requirements.txt"
                )


        except Exception as exc:
            _client_error = str(exc)
            print(f"[AI] Gemini unavailable — deterministic fallbacks active. "
                  f"Reason: {exc}")
            _client = None
        _client_ready = True
    return _client

# Pre-warm in background so the SDK initialises before the first user request,
# preventing gunicorn worker timeouts on low-CPU pods.
def _prewarm_model():
    try:
        get_model()
    except Exception:
        pass
threading.Thread(target=_prewarm_model, daemon=True).start()

import re, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── In-memory TTL cache for expensive AI endpoints ───────────────────────────
# Caches Gemini responses for 5 minutes to avoid re-querying on repeated clicks.
# Key: (endpoint_name, namespace), Value: (timestamp, response_data)
_ai_response_cache = {}
_AI_CACHE_TTL = 300  # 5 minutes

def _cache_get(key):
    """Return cached data if fresh, else None."""
    entry = _ai_response_cache.get(key)
    if entry and (time.time() - entry[0]) < _AI_CACHE_TTL:
        return entry[1]
    return None

def _cache_set(key, data):
    """Store data in cache with current timestamp."""
    _ai_response_cache[key] = (time.time(), data)

def parse_gemini_json(raw_text):
    """Robustly parse JSON from Gemini output, handling common malformations.

    Gemini sometimes returns:
    - Markdown fences (```json ... ```)
    - Trailing commas  ({..., })
    - Invalid backslash escapes (\\n inside strings that should be \\\\n)
    - Single-quoted strings instead of double-quoted
    - Extra text before/after the JSON block

    This function applies progressive repairs before giving up.
    """
    text = raw_text.strip()

    # 1. Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # 2. Extract JSON block if embedded in extra text — find first { to last }
    brace_start = text.find('{')
    brace_end = text.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    # 3. Try parsing as-is first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 4. Fix trailing commas before } or ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 5. Fix invalid backslash escapes (e.g. \n inside a string that isn't \\n)
    #    Replace \ followed by a char that isn't a valid JSON escape
    cleaned2 = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', cleaned)
    try:
        return json.loads(cleaned2)
    except json.JSONDecodeError:
        pass

    # 6. Last resort: try replacing single quotes with double quotes
    cleaned3 = cleaned2.replace("'", '"')
    try:
        return json.loads(cleaned3)
    except json.JSONDecodeError:
        pass

    # All repairs failed — raise with the original error for logging
    raise json.JSONDecodeError(
        f"Could not parse Gemini response after cleanup attempts",
        text[:200], 0
    )


def gemini_generate_with_retry(prompt, max_retries=2):
    """Call Gemini with retry on transient SSL/connection errors.

    GDC network environments often experience intermittent SSL EOF errors.
    This wrapper retries on connection-level failures without retrying on
    content/quota errors.
    """
    model = get_model()
    if not model:
        return None

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = model.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return resp
        except Exception as e:
            err_str = str(e).lower()
            # Retry on transient network/SSL errors
            is_transient = any(kw in err_str for kw in [
                'eof occurred', 'ssl', 'connection reset',
                'server disconnected', 'broken pipe',
                'connection refused', 'timed out', 'timeout'
            ])
            if is_transient and attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))  # Back-off: 1.5s, 3s
                last_error = e
                continue
            raise  # Non-transient or final attempt — re-raise
    raise last_error


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'gdc-dashboard-default-secret-key-change-me')

# SocketIO with relaxed ping settings for corporate proxies / CIDP auth
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent',
                    ping_timeout=120, ping_interval=30)

try:
    config.load_incluster_config()
except config.ConfigException:
    try:
        config.load_kube_config()
    except config.ConfigException:
        print("Could not configure kubernetes python client")

# ── Stale-connection retry helper ────────────────────────────────────────────
# The kubernetes-client urllib3 pool idles out after ~10 min.  When the pool
# returns a dead socket the SDK raises ProtocolError / RemoteDisconnected.
# We catch those specific errors and retry once with a short delay so the
# browser never sees a 500 / "Failed to fetch" after an idle period.
import time as _time

def _k8s_retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs); retry once if the k8s connection was stale."""
    _STALE = ('Connection reset by peer', 'ProtocolError',
              'RemoteDisconnected', 'Connection aborted', 'MaxRetryError')
    for _attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except Exception as _exc:
            if _attempt == 0 and any(k in str(_exc) for k in _STALE):
                _time.sleep(0.5)
                continue
            raise


@app.route('/api/ping')
def api_ping():
    """Ultra-lightweight keepalive — no K8s call, just proves the worker is alive."""
    return 'ok', 200


@app.route('/api/auth/status')
def api_auth_status():
    """Auth status check — if CIDP session is expired, the CIDP proxy will
    intercept this request and redirect to login (302/401) before it ever
    reaches this handler.  A successful JSON response proves auth is valid."""
    import datetime
    return jsonify({
        'authenticated': True,
        'ts': datetime.datetime.utcnow().isoformat()
    })


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/workloads')
def get_workloads():
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    batch_v1 = client.BatchV1Api()
    
    # Get namespace from query param, fallback to env var, fallback to 'default'
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    workloads = []

    # Deployments
    try:
        deployments = _k8s_retry(apps_v1.list_namespaced_deployment, namespace)
        for d in deployments.items:
            # Use spec.replicas for 'total' (desired state)
            desired = d.spec.replicas or 0
            # Use ready_replicas for 'ready'
            ready = d.status.ready_replicas or 0
            current = d.status.replicas or 0
            
            workloads.append({
                'name': d.metadata.name,
                'type': 'Deployment',
                'status': f"{ready}/{desired}",
                'ready': ready,
                'total': desired,
                'selector': d.spec.selector.match_labels if d.spec.selector else {},
                'images': [c.image for c in d.spec.template.spec.containers] if d.spec.template.spec.containers else [],
                'helm_chart': d.metadata.labels.get('helm.sh/chart', 'N/A') if d.metadata.labels else 'N/A',
                'labels': {k: v for k, v in (d.metadata.labels or {}).items()
                           if k not in ('pod-template-hash', 'controller-revision-hash')},
                'age': d.metadata.creation_timestamp
            })

    except Exception as e:
        print(f"Error fetching deployments: {e}")

    # StatefulSets
    try:
        statefulsets = _k8s_retry(apps_v1.list_namespaced_stateful_set, namespace)
        for s in statefulsets.items:
            desired = s.spec.replicas or 0
            ready = s.status.ready_replicas or 0
            
            workloads.append({
                'name': s.metadata.name,
                'type': 'StatefulSet',
                'status': f"{ready}/{desired}",
                'ready': ready,
                'total': desired,
                'selector': s.spec.selector.match_labels if s.spec.selector else {},
                'age': s.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching statefulsets: {e}")

    # Jobs
    try:
        jobs = _k8s_retry(batch_v1.list_namespaced_job, namespace)
        for j in jobs.items:
            active    = j.status.active    or 0
            succeeded = j.status.succeeded or 0
            failed    = j.status.failed    or 0
            completions  = j.spec.completions  or 1
            parallelism  = j.spec.parallelism  or 1

            # Human-readable overall status
            if j.status.completion_time:
                status = 'Succeeded'
            elif failed > 0 and active == 0:
                status = 'Failed'
            elif active > 0:
                status = 'Running'
            elif succeeded >= completions:
                status = 'Succeeded'
            else:
                status = 'Pending'

            workloads.append({
                'name':        j.metadata.name,
                'type':        'Job',
                'status':      status,
                'ready':       succeeded,
                'total':       completions,
                'age':         j.metadata.creation_timestamp,
                # extra job-specific counters (used by frontend)
                'job_active':      active,
                'job_succeeded':   succeeded,
                'job_failed':      failed,
                'job_completions': completions,
                'job_parallelism': parallelism,
            })
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        
    # DaemonSets
    try:
        daemonsets = _k8s_retry(apps_v1.list_namespaced_daemon_set, namespace)
        for d in daemonsets.items:
            workloads.append({
                'name': d.metadata.name,
                'type': 'DaemonSet',
                'status': f"{d.status.number_ready or 0}/{d.status.desired_number_scheduled}",
                'ready': d.status.number_ready or 0,
                'total': d.status.desired_number_scheduled,
                'age': d.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching daemonsets: {e}")

    # Pods
    try:
        pods = _k8s_retry(v1.list_namespaced_pod, namespace)
        for p in pods.items:
             containers = []
             if p.spec.containers:
                 for c in p.spec.containers:
                     containers.append({'name': c.name, 'image': c.image})
             
             if p.spec.init_containers:
                 for c in p.spec.init_containers:
                     containers.append({'name': c.name, 'image': c.image, 'type': 'init'})
                     
             if p.spec.ephemeral_containers:
                 for c in p.spec.ephemeral_containers:
                     containers.append({'name': c.name, 'image': c.image, 'type': 'ephemeral'})

             # Calculate actual ready containers
             ready_containers = 0
             total_containers = len(p.spec.containers) if p.spec.containers else 0
             if p.status.container_statuses:
                 ready_containers = sum(1 for c in p.status.container_statuses if c.ready)

             workloads.append({
                'name': p.metadata.name,
                'type': 'Pod',
                'status': p.status.phase,
                'ready': ready_containers,
                'total': total_containers,
                'labels': p.metadata.labels,
                'containers': containers,
                'age': p.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching pods: {e}")

    # Secrets
    try:
        secrets = _k8s_retry(v1.list_namespaced_secret, namespace)
        for s in secrets.items:
            workloads.append({
                'name': s.metadata.name,
                'type': 'Secret',
                'status': 'Active',
                'ready': 1,
                'total': 1,
                'age': s.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching secrets: {e}")

    # ConfigMaps
    try:
        configmaps = _k8s_retry(v1.list_namespaced_config_map, namespace)
        for c in configmaps.items:
            workloads.append({
                'name': c.metadata.name,
                'type': 'ConfigMap',
                'status': 'Active',
                'ready': 1,
                'total': 1,
                'age': c.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching configmaps: {e}")

    return jsonify(workloads)

@app.route('/api/services')
def get_services():
    v1 = client.CoreV1Api()
    # Get namespace from query param, fallback to env var, fallback to 'default'
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    services_list = []
    try:
        services = _k8s_retry(v1.list_namespaced_service, namespace)
        for s in services.items:
            ports = [f"{p.port}/{p.protocol}" for p in s.spec.ports] if s.spec.ports else []
            services_list.append({
                'name': s.metadata.name,
                'type': s.spec.type,
                'cluster_ip': s.spec.cluster_ip,
                'ports': ", ".join(ports),
                'age': s.metadata.creation_timestamp
            })
    except Exception as e:
        print(f"Error fetching services: {e}")
        
    return jsonify(services_list)

    return jsonify(services_list)

@app.route('/api/virtualservices')
def get_virtualservices():
    api = client.CustomObjectsApi()
    # Get namespace from query param, fallback to env var, fallback to 'default'
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    vs_list = []
    try:
        # Assuming istio API group
        virtual_services = api.list_namespaced_custom_object(
            group="networking.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="virtualservices"
        )
        for vs in virtual_services.get('items', []):
            hosts = vs.get('spec', {}).get('hosts', [])
            gateways = vs.get('spec', {}).get('gateways', [])
            vs_list.append({
                'name': vs['metadata']['name'],
                'hosts': ", ".join(hosts),
                'gateways': ", ".join(gateways),
                'age': vs['metadata']['creationTimestamp']
            })
    except Exception as e:
        # Fallback for v1alpha3 if v1beta1 fails, or just log error
        print(f"Error fetching VirtualServices: {e}")
        try:
             virtual_services = api.list_namespaced_custom_object(
                group="networking.istio.io",
                version="v1alpha3",
                namespace=namespace,
                plural="virtualservices"
            )
             for vs in virtual_services.get('items', []):
                hosts = vs.get('spec', {}).get('hosts', [])
                gateways = vs.get('spec', {}).get('gateways', [])
                vs_list.append({
                    'name': vs['metadata']['name'],
                    'hosts': ", ".join(hosts),
                    'gateways': ", ".join(gateways),
                    'age': vs['metadata']['creationTimestamp']
                })
        except Exception as e2:
             print(f"Error fetching VirtualServices (v1alpha3): {e2}")

    return jsonify(vs_list)

@app.route('/api/pod-stats')
def get_pod_stats():
    v1 = client.CoreV1Api()
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    stats = {
        'Running': 0,
        'Pending': 0,
        'Succeeded': 0,
        'Failed': 0,
        'Unknown': 0
    }
    
    try:
        pods = _k8s_retry(v1.list_namespaced_pod, namespace)
        for p in pods.items:
            phase = p.status.phase
            if phase in stats:
                stats[phase] += 1
            else:
                stats['Unknown'] += 1
    except Exception as e:
        print(f"Error fetching pod stats: {e}")
        
    return jsonify(stats)

@app.route('/api/pods/<name>/containers')
def get_pod_containers(name):
    """Return the list of regular (non-init) containers for a pod."""
    ns = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name, ns)
        containers = [
            {'name': c.name, 'image': c.image}
            for c in (pod.spec.containers or [])
        ]
        return jsonify({'containers': containers})
    except Exception as e:
        return jsonify({'containers': [], 'error': str(e)}), 200


@app.route('/api/pods/<name>/logs')

def get_pod_logs(name):
    v1 = client.CoreV1Api()
    # Get namespace from query param, fallback to env var, fallback to 'default'
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    try:
        logs = v1.read_namespaced_pod_log(name, namespace)
        return jsonify({'logs': logs})
    except ApiException as e:
        # K8s returns 400 when pod is initializing / container not ready
        if e.status == 400:
            # Extract the human-readable message from the K8s response
            import json as _json
            try:
                body = _json.loads(e.body)
                reason = body.get('message', str(e))
            except Exception:
                reason = e.reason or str(e)
            friendly = f"⏳ Pod '{name}' is not ready yet.\n\nKubernetes says: {reason}\n\nThis usually means init containers are still running. Please wait a moment and try again."
            return jsonify({'logs': friendly, 'status': 'initializing'})
        return jsonify({'error': str(e)}), e.status or 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/workloads/env')
def get_workload_env():
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    name = request.args.get('name')
    w_type = request.args.get('type')
    
    if not all([name, w_type]):
         return jsonify({'error': 'Missing name or type'}), 400

    env_vars = []
    config_maps = set()
    secrets = set()

    try:
        pod_spec = None
        if w_type == 'Deployment':
            d = apps_v1.read_namespaced_deployment(name, namespace)
            pod_spec = d.spec.template.spec
        elif w_type == 'StatefulSet':
            s = apps_v1.read_namespaced_stateful_set(name, namespace)
            pod_spec = s.spec.template.spec
        elif w_type == 'DaemonSet':
            ds = apps_v1.read_namespaced_daemon_set(name, namespace)
            pod_spec = ds.spec.template.spec
        elif w_type == 'Pod':
            p = v1.read_namespaced_pod(name, namespace)
            pod_spec = p.spec
        
        if pod_spec:
            for container in pod_spec.containers:
                # Env Vars
                if container.env:
                    for e in container.env:
                        val = e.value
                        if e.value_from:
                            if e.value_from.config_map_key_ref:
                                val = f"ConfigMap: {e.value_from.config_map_key_ref.name} (key: {e.value_from.config_map_key_ref.key})"
                                config_maps.add(e.value_from.config_map_key_ref.name)
                            elif e.value_from.secret_key_ref:
                                val = f"Secret: {e.value_from.secret_key_ref.name} (key: {e.value_from.secret_key_ref.key})"
                                secrets.add(e.value_from.secret_key_ref.name)
                            elif e.value_from.field_ref:
                                val = f"Field: {e.value_from.field_ref.field_path}"
                        
                        env_vars.append({
                            'container': container.name,
                            'name': e.name,
                            'value': val
                        })
                
                # EnvFrom (ConfigMaps/Secrets acting as env vars)
                if container.env_from:
                    for ef in container.env_from:
                        if ef.config_map_ref:
                            config_maps.add(ef.config_map_ref.name)
                            env_vars.append({
                                'container': container.name,
                                'name': f"(All from ConfigMap: {ef.config_map_ref.name})",
                                'value': "..."
                            })
                        elif ef.secret_ref:
                            secrets.add(ef.secret_ref.name)
                            env_vars.append({
                                'container': container.name,
                                'name': f"(All from Secret: {ef.secret_ref.name})",
                                'value': "..."
                            })

            # Check volumes
            if pod_spec.volumes:
                for v in pod_spec.volumes:
                    if v.config_map:
                        config_maps.add(v.config_map.name)
                    if v.secret:
                        secrets.add(v.secret.secret_name)
                    if v.projected:
                         for source in v.projected.sources:
                             if source.config_map:
                                 config_maps.add(source.config_map.name)
                             if source.secret:
                                 secrets.add(source.secret.name)

        return jsonify({
            'env': env_vars,
            'config_maps': list(config_maps),
            'secrets': list(secrets)
        })

    except Exception as e:
        print(f"Error fetching env vars: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/describe_workload', methods=['POST'])
def describe_workload_ai():
    """Gemini-powered config analysis for a workload.

    Accepts the output of /api/workloads/env (env_vars, config_maps, secrets)
    and asks Gemini to provide:
      - A plain-English summary of what this workload is configured to do
      - Security flags (plaintext secrets, debug flags, risky env vars)
      - Kubectl hints for inspecting config live
      - Recommendations to improve the configuration
    Returns structured JSON so the frontend can render each section distinctly.
    """
    try:
        data      = request.json or {}
        name      = data.get('name', 'unknown')
        kind      = data.get('kind', 'Deployment')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        env_vars  = data.get('env', [])
        config_maps = data.get('config_maps', [])
        secrets   = data.get('secrets', [])

        # Build a concise text summary of the config to send to Gemini
        env_text = '\n'.join(
            f"  [{e.get('container','?')}] {e.get('name','?')} = {str(e.get('value',''))[:120]}"
            for e in env_vars
        ) or '  (none)'
        cm_text  = ', '.join(config_maps) or '(none)'
        sec_text = ', '.join(secrets)     or '(none)'

        if not get_model():
            # Lightweight deterministic fallback when Gemini is not configured
            flags = []
            for e in env_vars:
                k = e.get('name', '').upper()
                v = str(e.get('value', ''))
                if any(x in k for x in ['PASSWORD', 'SECRET', 'TOKEN', 'KEY', 'PASS', 'CRED']):
                    if 'Secret:' not in v and 'secret' not in v.lower():
                        flags.append({
                            'severity': 'high',
                            'message': f'`{e.get("name")}` looks like a secret but is not sourced from a Kubernetes Secret.'
                        })
                if k == 'LOG_LEVEL' and v.upper() == 'DEBUG':
                    flags.append({'severity': 'medium', 'message': '`LOG_LEVEL=DEBUG` — debug logging in production increases log volume and may expose sensitive data.'})

            return jsonify({
                'summary': f'{kind} `{name}` has {len(env_vars)} env var(s), '
                           f'{len(config_maps)} ConfigMap(s), and {len(secrets)} Secret(s). '
                           f'Set GCP_PROJECT_ID for full AI analysis.',
                'security_flags': flags,
                'recommendations': [
                    'Store all passwords/tokens in Kubernetes Secrets, not ConfigMaps or plain env vars.',
                    'Use `kubectl describe deployment ' + name + '` to inspect live resource limits.',
                ],
                'kubectl_hints': [
                    f'kubectl get deployment {name} -n {namespace} -o yaml',
                    f'kubectl describe deployment {name} -n {namespace}',
                ],
                'gemini_powered': False,
            })

        prompt = f"""You are a Kubernetes configuration expert reviewing a {kind} named "{name}" in namespace "{namespace}".

Environment variables:
{env_text}

ConfigMaps referenced: {cm_text}
Secrets referenced: {sec_text}

Return ONLY valid JSON (no markdown, no fences) with this exact schema:
{{
  "summary": "<2-3 sentence plain-English description of what this workload is configured to do and its key settings>",
  "security_flags": [
    {{"severity": "high|medium|low", "message": "<specific finding about this workload's config>"}}
  ],
  "recommendations": ["<concrete actionable improvement 1>", "<improvement 2>"],
  "kubectl_hints": [
    "<exact kubectl command for inspecting or fixing something specific to this workload>"
  ]
}}

Check for:
- Plaintext secrets/passwords/tokens in env vars (not from secretKeyRef) → high severity
- LOG_LEVEL=debug in production → medium severity
- Missing resource limits or health probes (infer from naming) → medium severity
- ConfigMaps storing sensitive keys → high severity
- Good practices to praise as well (reference to Secrets is good)
- Kubectl hints: be specific — use the actual workload name "{name}" and namespace "{namespace}"

Return 2-4 security_flags, 2-3 recommendations, 2-3 kubectl_hints.
Return ONLY the JSON. No markdown. No fences."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        parsed.setdefault('summary', '')
        parsed.setdefault('security_flags', [])
        parsed.setdefault('recommendations', [])
        parsed.setdefault('kubectl_hints', [])
        parsed['gemini_powered'] = True
        return jsonify(parsed)

    except json.JSONDecodeError as e:
        print(f"[describe_workload] Gemini non-JSON: {e}")
        return jsonify({'summary': 'AI analysis failed — try again.', 'security_flags': [],
                        'recommendations': [], 'kubectl_hints': [], 'gemini_powered': False})
    except Exception as e:
        print(f"[describe_workload] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/secrets/<name>')
def get_secret(name):
    v1 = client.CoreV1Api()
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    try:
        secret = v1.read_namespaced_secret(name, namespace)
        # Decode base64 data
        decoded_data = {}
        import base64
        if secret.data:
            for k, v in secret.data.items():
                try:
                    decoded_data[k] = base64.b64decode(v).decode('utf-8')
                except:
                    decoded_data[k] = "binary_data"
        return jsonify({'data': decoded_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configmaps/<name>')
def get_configmap(name):
    v1 = client.CoreV1Api()
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace = request.args.get('namespace', current_ns)
    
    try:
        cm = v1.read_namespaced_config_map(name, namespace)
        # Clean formatting: Try to parse JSON values
        cleaned_data = {}
        if cm.data:
            import json
            for k, v in cm.data.items():
                try:
                    cleaned_data[k] = json.loads(v)
                except:
                    cleaned_data[k] = v
        return jsonify({'data': cleaned_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/explain_configmap')
def explain_configmap():
    """Use Gemini to explain what a ConfigMap is for and flag any concerns."""
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    namespace  = request.args.get('namespace', current_ns)
    name       = request.args.get('name', '')
    if not name:
        return jsonify({'error': 'name parameter is required'}), 400
    try:
        v1 = client.CoreV1Api()
        cm = v1.read_namespaced_config_map(name, namespace)
        data = cm.data or {}
        kv_text = '\n'.join(f'  {k}: {v[:300]}{"…" if len(str(v)) > 300 else ""}' for k, v in data.items()) or '  (empty)'

        prompt = f"""You are a Kubernetes expert reviewing a ConfigMap named "{name}" in namespace "{namespace}".

ConfigMap data:
{kv_text}

Write a concise explanation (4-8 sentences) covering:
1. **Purpose** — what is this ConfigMap likely used for? Which workload/service does it configure?
2. **Key breakdown** — 1-sentence description of each key's role.
3. **Security concerns** — flag any keys that look like they contain secrets, credentials, or sensitive data that should be in a Secret instead.
4. **Recommendations** — any actionable improvements.

Use **bold** for key names. Keep it factual and concise."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return jsonify({'explanation': response.text.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scale', methods=['POST'])
def scale_workload():
    apps_v1 = client.AppsV1Api()
    current_ns = os.getenv('POD_NAMESPACE', 'default')
    data = request.json or {}
    name = data.get('name')
    kind = data.get('type')   # 'Deployment' or 'StatefulSet'
    action = data.get('action')  # 'up', 'down', or 'set'
    # Accept namespace from JSON body first, then URL query param, then env var
    namespace = data.get('namespace') or request.args.get('namespace', current_ns)

    if not all([name, kind, action]):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        new_replicas = None
        if kind == 'Deployment':
            scale = apps_v1.read_namespaced_deployment_scale(name, namespace)
            if action == 'up':
                scale.spec.replicas = (scale.spec.replicas or 0) + 1
            elif action == 'down':
                scale.spec.replicas = max(0, (scale.spec.replicas or 0) - 1)
            elif action == 'set':
                scale.spec.replicas = int(data.get('count', scale.spec.replicas or 1))
            apps_v1.replace_namespaced_deployment_scale(name, namespace, scale)
            new_replicas = scale.spec.replicas

        elif kind == 'StatefulSet':
            scale = apps_v1.read_namespaced_stateful_set_scale(name, namespace)
            if action == 'up':
                scale.spec.replicas = (scale.spec.replicas or 0) + 1
            elif action == 'down':
                scale.spec.replicas = max(0, (scale.spec.replicas or 0) - 1)
            elif action == 'set':
                scale.spec.replicas = int(data.get('count', scale.spec.replicas or 1))
            apps_v1.replace_namespaced_stateful_set_scale(name, namespace, scale)
            new_replicas = scale.spec.replicas

        else:
            return jsonify({'error': f'Scaling not supported for {kind}'}), 400

        return jsonify({
            'message': f'Successfully scaled {name} {action}',
            'new_replicas': new_replicas
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- AI Features ---

@app.route('/api/ai/optimize')
def ai_optimize():
    """Gemini-powered Smart Resource Optimizer.

    Tries the Kubernetes metrics-server (metrics.k8s.io/v1beta1) first to get
    REAL CPU/memory usage per pod.  If the metrics server is unavailable, falls
    back to Gemini estimation from workload type / image name.

    Cost model (org-specific):
        - €60 EUR per CPU core per month
        - billable_cores = max(cpu_requests, actual_cpu_usage)
          → requests > usage  → billed on REQUESTS  (over-provisioned, wasted spend)
          → usage   > requests → billed on USAGE    (under-provisioned, throttling risk)
        - Memory is NOT separately billed but OOM kills cause incidents

    Returns enriched JSON:
    {
      "cost_rate_per_core": 60,
      "currency": "EUR",
      "metrics_source": "metrics-server" | "gemini-estimation",
      "total_current_monthly_cost": float,
      "total_recommended_monthly_cost": float,
      "total_monthly_saving": float,
      "summary": str,
      "recommendations": [{
        "resource": str, "kind": str, "replicas": int,
        "type": "Cost Saving|Performance Risk|Stability Risk|Right-Sized",
        "reason": str,
        "actual_usage_cpu": str,        # "0.42 cores (measured)" or "~0.05 cores (estimated)"
        "actual_usage_mem": str,        # "312 MiB (measured)" or "~128 MiB (estimated)"
        "capacity_headroom_pct": str,   # "45%" headroom before CPU limit
        "billable_cores": float,        # max(cpu_requests_cores, actual_usage_cores)
        "billing_basis": str,           # "requests" or "usage"
        "current_cpu_request": str, "current_cpu_limit": str,
        "current_mem_request": str, "current_mem_limit": str,
        "suggested_cpu_request": str, "suggested_cpu_limit": str,
        "suggested_mem_request": str, "suggested_mem_limit": str,
        "estimated_utilization": str,
        "current_monthly_cost": float,
        "recommended_monthly_cost": float,
        "monthly_saving": float,
        "action": str,
        "severity": "high|medium|low",
        "ai_insight": str
      }]
    }
    """
    namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    # ── Cache check — return instantly if fresh ──
    cache_key = ('optimizer', namespace)
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)

    cost_per_core = 60.0  # EUR per core per month (org-specific)

    # ── Utility: CPU / Memory parsers ────────────────────────────────────────
    def _parse_cpu_cores(val):
        """Convert CPU string to float cores. Returns 0.0 if not set."""
        if not val:
            return 0.0
        v = str(val)
        if v.endswith('m'):
            return float(v[:-1]) / 1000.0
        if v.endswith('n'):
            return float(v[:-1]) / 1e9
        try:
            return float(v)
        except ValueError:
            return 0.0

    def _parse_mem_mib(val):
        """Convert memory string to MiB float. Returns 0.0 if not set."""
        if not val:
            return 0.0
        v = str(val)
        if v.endswith('Ki'): return float(v[:-2]) / 1024
        if v.endswith('Mi'): return float(v[:-2])
        if v.endswith('Gi'): return float(v[:-2]) * 1024
        if v.endswith('Ti'): return float(v[:-2]) * 1024 * 1024
        try:
            return float(v) / (1024 * 1024)  # bytes → MiB
        except ValueError:
            return 0.0

    def _extract_json(text):
        """Robust JSON extractor — strips markdown fences cleanly (no fragile regex)."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            start = 1
            end   = len(lines)
            if lines[-1].strip() in ("```", "~~~"):
                end -= 1
            text = "\n".join(lines[start:end])
        return json.loads(text.strip())

    try:
        apps_v1    = client.AppsV1Api()
        core_v1    = client.CoreV1Api()
        batch_v1   = client.BatchV1Api()
        custom_api = client.CustomObjectsApi()

        # ── 1. Fetch real metrics from metrics-server ─────────────────────────
        # metrics.k8s.io/v1beta1 — available when metrics-server is deployed.
        # Returns dict: {pod_name: {"cpu_cores": float, "mem_mib": float}}
        pod_metrics_map = {}
        metrics_source  = "gemini-estimation"
        try:
            raw_pod_metrics = custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods"
            )
            for pm in raw_pod_metrics.get("items", []):
                pod_name  = pm["metadata"]["name"]
                total_cpu = 0.0
                total_mem = 0.0
                for c in pm.get("containers", []):
                    usage      = c.get("usage", {})
                    total_cpu += _parse_cpu_cores(usage.get("cpu"))
                    total_mem += _parse_mem_mib(usage.get("memory"))
                pod_metrics_map[pod_name] = {"cpu_cores": total_cpu, "mem_mib": total_mem}
            if pod_metrics_map:
                metrics_source = "metrics-server"
                print(f"[optimize] metrics-server: {len(pod_metrics_map)} pods measured")
        except Exception as me:
            print(f"[optimize] metrics-server unavailable: {me}")

        # ── 2. Aggregate pod metrics → workload totals ────────────────────────
        workload_metrics_map = {}  # {name: {"cpu_cores": float, "mem_mib": float, "pods": int}}
        if pod_metrics_map:
            try:
                all_pods = core_v1.list_namespaced_pod(namespace).items
                for pod in all_pods:
                    owner_name = None
                    for ref in (pod.metadata.owner_references or []):
                        if ref.kind == "ReplicaSet":
                            try:
                                rs = apps_v1.read_namespaced_replica_set(ref.name, namespace)
                                for rs_ref in (rs.metadata.owner_references or []):
                                    if rs_ref.kind == "Deployment":
                                        owner_name = rs_ref.name
                                        break
                            except Exception:
                                pass
                        elif ref.kind in ("StatefulSet", "DaemonSet"):
                            owner_name = ref.name
                        if owner_name:
                            break
                    pod_name = pod.metadata.name
                    if owner_name and pod_name in pod_metrics_map:
                        m = pod_metrics_map[pod_name]
                        if owner_name not in workload_metrics_map:
                            workload_metrics_map[owner_name] = {"cpu_cores": 0.0, "mem_mib": 0.0, "pods": 0}
                        workload_metrics_map[owner_name]["cpu_cores"] += m["cpu_cores"]
                        workload_metrics_map[owner_name]["mem_mib"]   += m["mem_mib"]
                        workload_metrics_map[owner_name]["pods"]       += 1
            except Exception as ae:
                print(f"[optimize] aggregation error: {ae}")

        # ── 3. Build workload spec + live-metrics summaries ───────────────────
        def _workload_spec_summary(name, kind, replicas, containers, init_containers=None):
            """Compact spec + real usage text for Gemini to analyse."""
            lines = [f"workload: {name}", f"  kind: {kind}", f"  replicas: {replicas}"]
            wm = workload_metrics_map.get(name)
            if wm:
                cpu_per_replica = wm["cpu_cores"] / max(replicas, 1)
                mem_per_replica = wm["mem_mib"]   / max(replicas, 1)
                lines.append(f"  actual_cpu_usage_total: {wm['cpu_cores']:.4f} cores across {wm['pods']} pods (MEASURED)")
                lines.append(f"  actual_cpu_per_replica: {cpu_per_replica:.4f} cores (MEASURED)")
                lines.append(f"  actual_mem_per_replica: {mem_per_replica:.1f} MiB (MEASURED)")
            else:
                lines.append("  actual_cpu_usage: unknown (no metrics-server — estimate from workload type/image)")
                lines.append("  actual_mem_usage: unknown (no metrics-server — estimate from workload type/image)")
            for c in (init_containers or []) + containers:
                res  = getattr(c, 'resources', None)
                req  = getattr(res, 'requests', None) or {}
                lim  = getattr(res, 'limits',   None) or {}
                lines.append(f"  container: {c.name}  image: {c.image}")
                lines.append(f"    cpu_request: {req.get('cpu','not-set')}  cpu_limit: {lim.get('cpu','not-set')}")
                lines.append(f"    mem_request: {req.get('memory','not-set')}  mem_limit: {lim.get('memory','not-set')}")
                lines.append(f"    readinessProbe: {'set' if c.readiness_probe else 'missing'}")
                lines.append(f"    livenessProbe: {'set' if c.liveness_probe else 'missing'}")
                envs = getattr(c, 'env', []) or []
                env_names = [e.name for e in envs][:8]
                if env_names:
                    lines.append(f"    env_vars_sample: {env_names}")
            return "\n".join(lines)

        workload_summaries = []
        raw_workloads      = []

        try:
            for dep in apps_v1.list_namespaced_deployment(namespace).items:
                spec = dep.spec.template.spec
                containers = spec.containers or []
                replicas   = dep.spec.replicas or 1
                workload_summaries.append(_workload_spec_summary(
                    dep.metadata.name, "Deployment", replicas, containers,
                    spec.init_containers or []))
                raw_workloads.append(("Deployment", dep.metadata.name, replicas, containers))
        except Exception as e:
            print(f"[optimize] deployments: {e}")

        try:
            for sts in apps_v1.list_namespaced_stateful_set(namespace).items:
                spec = sts.spec.template.spec
                containers = spec.containers or []
                replicas   = sts.spec.replicas or 1
                workload_summaries.append(_workload_spec_summary(
                    sts.metadata.name, "StatefulSet", replicas, containers,
                    spec.init_containers or []))
                raw_workloads.append(("StatefulSet", sts.metadata.name, replicas, containers))
        except Exception as e:
            print(f"[optimize] statefulsets: {e}")

        try:
            for ds in apps_v1.list_namespaced_daemon_set(namespace).items:
                spec = ds.spec.template.spec
                containers = spec.containers or []
                node_count = workload_metrics_map.get(ds.metadata.name, {}).get("pods", 3)
                workload_summaries.append(_workload_spec_summary(
                    ds.metadata.name, f"DaemonSet (~{node_count} nodes)", node_count, containers,
                    spec.init_containers or []))
                raw_workloads.append(("DaemonSet", ds.metadata.name, node_count, containers))
        except Exception as e:
            print(f"[optimize] daemonsets: {e}")

        try:
            for job in batch_v1.list_namespaced_job(namespace).items:
                spec = job.spec.template.spec
                containers  = spec.containers or []
                completions = job.spec.completions or 1
                workload_summaries.append(_workload_spec_summary(
                    job.metadata.name, f"Job ({completions} completions)",
                    completions, containers))
                raw_workloads.append(("Job", job.metadata.name, completions, containers))
        except Exception as e:
            print(f"[optimize] jobs: {e}")

        if not workload_summaries:
            return jsonify({
                "cost_rate_per_core": cost_per_core, "currency": "EUR",
                "metrics_source": metrics_source,
                "total_current_monthly_cost": 0,
                "total_recommended_monthly_cost": 0,
                "total_monthly_saving": 0,
                "summary": "No workloads found in this namespace.",
                "recommendations": []
            })

        inventory_text = "\n\n".join(workload_summaries)

        # ── 4. Basic spec-check fallback when Gemini is NOT configured ────────
        if not get_model():
            recommendations   = []
            total_current     = 0.0
            total_recommended = 0.0

            for kind, name, replicas, containers in raw_workloads:
                total_req_cpu     = 0.0
                total_lim_cpu     = 0.0
                total_lim_mem_mib = 0.0
                for c in containers:
                    res = getattr(c, 'resources', None)
                    req = getattr(res, 'requests', None) or {}
                    lim = getattr(res, 'limits',   None) or {}
                    total_req_cpu     += _parse_cpu_cores(req.get('cpu'))
                    total_lim_cpu     += _parse_cpu_cores(lim.get('cpu'))
                    total_lim_mem_mib += _parse_mem_mib(lim.get('memory'))

                wm = workload_metrics_map.get(name)
                actual_cpu_per_replica = (wm["cpu_cores"] / max(replicas, 1)) if wm else 0.0
                actual_mem_per_replica = (wm["mem_mib"]   / max(replicas, 1)) if wm else 0.0

                billable_cores = max(total_req_cpu, actual_cpu_per_replica)
                billing_basis  = "usage" if (wm and actual_cpu_per_replica > total_req_cpu) else "requests"
                current_cost   = billable_cores * cost_per_core * replicas
                total_current += current_cost

                actual_usage_cpu = (f"{wm['cpu_cores']:.3f} cores (measured)"
                                    if wm else "unknown (no metrics server)")
                actual_usage_mem = (f"{wm['mem_mib']:.0f} MiB (measured)"
                                    if wm else "unknown (no metrics server)")

                headroom_pct = "N/A"
                if total_lim_cpu > 0 and wm:
                    headroom_pct = f"{max(0,(1 - actual_cpu_per_replica/total_lim_cpu)*100):.0f}%"

                if total_lim_mem_mib == 0:
                    rtype    = "Stability Risk ⚠️"
                    reason   = "No memory limit set — pod can consume unlimited node memory."
                    action   = "Set resources.limits.memory: 256Mi"
                    severity = "high"
                    insight  = "Without limits the scheduler cannot protect other pods on the same node."
                    rec_cost = current_cost
                elif billing_basis == "usage" and wm:
                    rtype    = "Performance Risk 📈"
                    reason   = (f"Actual CPU ({actual_cpu_per_replica:.3f} cores/replica) "
                                f"exceeds request ({total_req_cpu:.3f} cores). "
                                f"Billed on usage — throttling risk.")
                    action   = f"Increase cpu_request to ~{actual_cpu_per_replica*1.3:.3f} cores"
                    severity = "high"
                    insight  = "Under-provisioned; Kubernetes throttles CPU at the request/limit boundary."
                    rec_cost = actual_cpu_per_replica * 1.3 * cost_per_core * replicas
                elif billing_basis == "requests" and total_req_cpu > 0 and wm:
                    save_ratio = max(0, (total_req_cpu - actual_cpu_per_replica) / total_req_cpu)
                    if save_ratio > 0.3:
                        rtype    = "Cost Saving 📉"
                        reason   = (f"CPU request ({total_req_cpu:.3f} cores/replica) is "
                                    f"{save_ratio*100:.0f}% above measured usage "
                                    f"({actual_cpu_per_replica:.3f} cores). "
                                    f"Billed on requests — over-provisioned.")
                        action   = f"Reduce cpu_request to ~{actual_cpu_per_replica*1.3:.3f} cores"
                        severity = "medium"
                        insight  = "Right-sizing to usage × 1.3 reclaims wasted allocation without risk."
                        rec_cost = actual_cpu_per_replica * 1.3 * cost_per_core * replicas
                    else:
                        rtype    = "Right-Sized ✅"
                        reason   = "CPU requests are well-sized relative to actual usage."
                        action   = "No immediate action needed."
                        severity = "low"
                        insight  = "Workload is well proportioned. Review again monthly."
                        rec_cost = current_cost
                else:
                    rtype    = "Right-Sized ✅"
                    reason   = "Resource limits configured. Enable Gemini for AI-powered right-sizing."
                    action   = "Deploy metrics-server or configure Gemini for deeper analysis."
                    severity = "low"
                    insight  = "Configure Gemini or metrics-server for intelligent utilisation estimation."
                    rec_cost = current_cost

                total_recommended += rec_cost
                recommendations.append({
                    "resource": name, "kind": kind, "replicas": replicas,
                    "type": rtype, "reason": reason,
                    "actual_usage_cpu": actual_usage_cpu,
                    "actual_usage_mem": actual_usage_mem,
                    "capacity_headroom_pct": headroom_pct,
                    "billable_cores": round(billable_cores, 4),
                    "billing_basis":  billing_basis,
                    "current_cpu_request": f"{total_req_cpu:.3f} cores" if total_req_cpu else "not-set",
                    "current_mem_limit":   "not set" if total_lim_mem_mib == 0 else f"{total_lim_mem_mib:.0f}Mi",
                    "current_monthly_cost":     round(current_cost, 2),
                    "recommended_monthly_cost": round(rec_cost, 2),
                    "monthly_saving":           round(current_cost - rec_cost, 2),
                    "action": action, "severity": severity, "ai_insight": insight
                })

            return jsonify({
                "cost_rate_per_core":             cost_per_core,
                "currency":                       "EUR",
                "metrics_source":                 metrics_source,
                "total_current_monthly_cost":     round(total_current, 2),
                "total_recommended_monthly_cost": round(total_recommended, 2),
                "total_monthly_saving":           round(total_current - total_recommended, 2),
                "summary": (
                    f"Analysed {len(raw_workloads)} workloads via {metrics_source}. "
                    "Gemini not configured — using spec + measured metrics checks."
                ),
                "recommendations": recommendations
            })

        # ── 5. Gemini-powered analysis ────────────────────────────────────────
        metrics_note = (
            "IMPORTANT: Real CPU/memory usage IS available from the metrics server for some workloads "
            "(marked MEASURED in the inventory). Use those exact values for billable_cores calculation. "
            "For workloads without measured data, estimate from workload type and image name."
            if metrics_source == "metrics-server"
            else
            "NOTE: No metrics server available. Estimate actual CPU/memory usage from workload type, "
            "image name, and engineering heuristics for each workload."
        )

        prompt = f"""You are a senior Kubernetes cost-optimization engineer with the following billing model:

COST MODEL (apply exactly):
- €{cost_per_core} EUR per CPU core per month
- billing rule:  billable_cores = max(cpu_requests_cores, actual_cpu_usage_cores)  [per replica]
  → cpu_requests > actual_usage  →  billing_basis = "requests"  (over-provisioned, wasted spend)
  → actual_usage > cpu_requests  →  billing_basis = "usage"     (under-provisioned, throttling risk)
- current_monthly_cost  = billable_cores × {cost_per_core} × replicas
- Memory is NOT separately billed, but OOM kills cause incidents

{metrics_note}

WORKLOAD INVENTORY:
{inventory_text}

ESTIMATION HEURISTICS (only when actual_cpu_usage is unknown):
- nginx/frontend: ~2–8% CPU, ~40–60% memory of limit
- Java/Spring Boot: ~30–60% CPU, ~70–85% memory (JVM heap)
- PostgreSQL/MySQL: ~15–40% CPU, ~60–80% memory
- Redis: ~5–15% CPU, ~50–70% memory
- ML inference (torch/tensorflow): ~70–95% CPU, ~80–95% memory
- Batch jobs: ~80–95% CPU during run
- Sidecar/proxy (envoy/istio): ~2–5% CPU, ~30–50% memory
- Node exporter/DaemonSets: ~1–5% CPU, ~30–50% memory

Return ONLY a valid JSON object (no markdown, no explanation):
{{
  "cost_rate_per_core": {cost_per_core},
  "currency": "EUR",
  "metrics_source": "{metrics_source}",
  "total_current_monthly_cost": <sum of all current_monthly_cost>,
  "total_recommended_monthly_cost": <sum of all recommended_monthly_cost>,
  "total_monthly_saving": <total_current - total_recommended>,
  "summary": "2-3 sentence executive summary of cost and resource posture",
  "recommendations": [
    {{
      "resource": "<workload name>",
      "kind": "<Deployment|StatefulSet|DaemonSet|Job>",
      "replicas": <int>,
      "type": "Cost Saving 📉 | Performance Risk 📈 | Stability Risk ⚠️ | Right-Sized ✅",
      "reason": "Explanation referencing specific numbers",
      "actual_usage_cpu": "<e.g. '0.42 cores (measured)' or '~0.05 cores (estimated)'>",
      "actual_usage_mem": "<e.g. '312 MiB (measured)' or '~128 MiB (estimated)'>",
      "capacity_headroom_pct": "<% headroom before CPU limit, e.g. '45%' or 'N/A'>",
      "billable_cores": <float: max(cpu_request, actual_usage) per replica>,
      "billing_basis": "requests" | "usage",
      "current_cpu_request":  "<value or 'not-set'>",
      "current_cpu_limit":    "<value or 'not-set'>",
      "current_mem_request":  "<value or 'not-set'>",
      "current_mem_limit":    "<value or 'not-set'>",
      "suggested_cpu_request": "<e.g. '200m'>",
      "suggested_cpu_limit":   "<e.g. '500m'>",
      "suggested_mem_request": "<e.g. '256Mi'>",
      "suggested_mem_limit":   "<e.g. '512Mi'>",
      "current_monthly_cost":     <float: billable_cores × {cost_per_core} × replicas>,
      "recommended_monthly_cost": <float: suggested_cpu_request_cores × {cost_per_core} × replicas>,
      "monthly_saving":           <current_monthly_cost - recommended_monthly_cost>,
      "action": "Specific kubectl/YAML change to apply",
      "severity": "high|medium|low",
      "ai_insight": "1 sentence on why this pattern occurs for this workload type"
    }}
  ]
}}

Rules:
- One recommendation per workload, even Right-Sized ones
- billable_cores = max(cpu_requests_cores_per_replica, actual_cpu_cores_per_replica)
- If cpu_request is not-set: assume 0 cores — flag Stability Risk
- suggested_cpu_request = actual_usage_cores × 1.3  (30% headroom)
- suggested_cpu_limit   = suggested_cpu_request × 2  (burst headroom)
- suggested_mem_request = estimated_mem_usage × 1.2  (20% headroom)
- suggested_mem_limit   = suggested_mem_request × 1.5 (spike headroom)
- monthly_saving POSITIVE = saving (reducing over-provisioned). NEGATIVE = cost increase (raising under-provisioned).
- Return ONLY JSON. No markdown. No explanation.
"""
        response = gemini_generate_with_retry(prompt)
        result   = parse_gemini_json(response.text)
        result.setdefault("cost_rate_per_core", cost_per_core)
        result.setdefault("currency", "EUR")
        result.setdefault("metrics_source", metrics_source)
        result.setdefault("recommendations", [])
        result.setdefault("summary", "Analysis complete.")
        _cache_set(cache_key, result)
        return jsonify(result)

    except json.JSONDecodeError as e:
        print(f"[optimize] Gemini returned non-JSON: {e}")
        return jsonify({"error": "AI returned malformed output. Try again.", "recommendations": []}), 500
    except Exception as e:
        print(f"[optimize] Error: {e}")
        return jsonify({'error': str(e)}), 500

# --- Gemini Integration ---



def fetch_pod_logs_aggregated(name, namespace):
    v1 = client.CoreV1Api()
    logs = []
    try:
        pod = v1.read_namespaced_pod(name, namespace)
        spec = pod.spec
        
        # 1. Init Containers
        if spec.init_containers:
            for c in spec.init_containers:
                try:
                    log = v1.read_namespaced_pod_log(name, namespace, container=c.name, tail_lines=50)
                    logs.append(f"--- Init Container: {c.name} ---\n{log}")
                except ApiException as e:
                    if e.status == 400:
                        logs.append(f"--- Init Container: {c.name} ---\n⏳ Container is initializing, logs not available yet.")
                    else:
                        logs.append(f"--- Init Container: {c.name} ---\n(Error: {e.reason})")
                except: pass
                
        # 2. App Containers
        for c in spec.containers:
            try:
                log = v1.read_namespaced_pod_log(name, namespace, container=c.name, tail_lines=100)
                logs.append(f"--- Container: {c.name} ---\n{log}")
            except ApiException as e:
                if e.status == 400:
                    logs.append(f"--- Container: {c.name} ---\n⏳ Container is waiting to start (PodInitializing). Logs will be available once the container is running.")
                else:
                    logs.append(f"--- Container: {c.name} ---\n(Error: {e.reason})")
            except: pass
            
    except Exception as e:
        return f"Error fetching logs: {str(e)}"
        
    return "\n\n".join(logs) if logs else f"⏳ Pod '{name}' has no available logs yet. It may still be initializing."

@app.route('/api/ai/analyze_logs', methods=['POST'])
def analyze_logs_gemini():
    if not get_model():
        return jsonify({'analysis': "Gemini is not configured (check GCP_PROJECT_ID env var). Mock analysis unavailable in this mode."})

    data = request.json
    pod_name = data.get('pod_name')
    namespace = data.get('namespace', 'default')
    
    # 1. Fetch Logs
    logs = fetch_pod_logs_aggregated(pod_name, namespace)
    if not logs:
        return jsonify({'analysis': "No logs found to analyze."})
        
    # 2. Prompt Gemini
    prompt = f"""You are a Kubernetes Expert Debugger. 
Analyze the following logs from pod '{pod_name}' in namespace '{namespace}'.
Identify:
1. The likely root cause of any errors (crash, connection issue, config error).
2. The specific log line that indicates the error.
3. A concrete fix (e.g., 'Update DB_HOST env var', 'Increase memory limit').

Format the output in Markdown.

Logs:
{logs[:10000]}  # Truncate to avoid token limits if massive
"""
    try:
        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return jsonify({'analysis': response.text})
    except Exception as e:
        return jsonify({'error': f"Gemini Error: {str(e)}"}), 500

@app.route('/api/ai/security_scan')
def security_scan():
    """Gemini-powered comprehensive cluster security audit.

    Collects specs from ALL resource kinds in the namespace
    (Deployments, StatefulSets, DaemonSets, Jobs, Pods, ServiceAccounts,
    NetworkPolicies, RBAC bindings) and sends the full inventory to Gemini
    with a CIS-Kubernetes-Benchmark-aligned prompt.

    Returns:
        {
          "executive_summary": str,          # Overall posture in 2-3 sentences
          "severity_counts": { Critical, High, Medium, Low, Info },
          "risks": [
            {
              "severity": Critical|High|Medium|Low|Info,
              "category": str,               # e.g. "Pod Security", "RBAC", "Network"
              "resource": str,
              "kind": str,
              "issue": str,
              "remediation": str,
              "cve_references": [str],        # CVE IDs or CIS benchmark IDs
              "ai_insight": str              # Gemini's 1-sentence contextual explanation
            }, ...
          ]
        }
    """
    namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    # ── Cache check — return instantly if fresh ──
    cache_key = ('security_scan', namespace)
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)

    try:
        core_v1  = client.CoreV1Api()
        apps_v1  = client.AppsV1Api()
        batch_v1 = client.BatchV1Api()
        rbac_v1  = client.RbacAuthorizationV1Api()
        net_v1   = client.NetworkingV1Api()

        # ── 1. Collect raw specs — PARALLEL to speed up GDC network ──────────
        inventory_sections = []
        k8s_results = {}

        def _fetch(label, fn):
            try:
                return (label, fn())
            except Exception:
                return (label, [])

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_fetch, 'deploys', lambda: apps_v1.list_namespaced_deployment(namespace).items),
                pool.submit(_fetch, 'stateful', lambda: apps_v1.list_namespaced_stateful_set(namespace).items),
                pool.submit(_fetch, 'daemons', lambda: apps_v1.list_namespaced_daemon_set(namespace).items),
                pool.submit(_fetch, 'pods', lambda: core_v1.list_namespaced_pod(namespace).items),
                pool.submit(_fetch, 'jobs', lambda: batch_v1.list_namespaced_job(namespace).items),
                pool.submit(_fetch, 'sas', lambda: core_v1.list_namespaced_service_account(namespace).items),
                pool.submit(_fetch, 'netpols', lambda: net_v1.list_namespaced_network_policy(namespace).items),
                pool.submit(_fetch, 'rbs', lambda: rbac_v1.list_namespaced_role_binding(namespace).items),
                pool.submit(_fetch, 'cms', lambda: core_v1.list_namespaced_config_map(namespace).items),
                pool.submit(_fetch, 'secrets', lambda: core_v1.list_namespaced_secret(namespace).items),
            ]
            for f in as_completed(futures):
                label, items = f.result()
                k8s_results[label] = items

        deploys  = k8s_results.get('deploys', [])
        stateful = k8s_results.get('stateful', [])
        daemons  = k8s_results.get('daemons', [])
        pods     = k8s_results.get('pods', [])
        jobs     = k8s_results.get('jobs', [])

        def _workload_summary(w):
            """Summarise a workload object as compact YAML-like text."""
            name = w.metadata.name
            spec = w.spec.template.spec if hasattr(w.spec, 'template') else w.spec
            containers = spec.containers if hasattr(spec, 'containers') else []
            init_containers = spec.init_containers or [] if hasattr(spec, 'init_containers') else []
            lines = [f"  name: {name}"]
            lines.append(f"  hostPID: {getattr(spec,'host_pid',False)}")
            lines.append(f"  hostNetwork: {getattr(spec,'host_network',False)}")
            lines.append(f"  hostIPC: {getattr(spec,'host_ipc',False)}")
            pod_sc = getattr(spec, 'security_context', None)
            if pod_sc:
                lines.append(f"  podSecurityContext: runAsUser={getattr(pod_sc,'run_as_user','?')} runAsNonRoot={getattr(pod_sc,'run_as_non_root','?')} fsGroup={getattr(pod_sc,'fs_group','?')}")
            vols = getattr(spec, 'volumes', []) or []
            hostpath_vols = [v.name for v in vols if getattr(v,'host_path',None)]
            if hostpath_vols:
                lines.append(f"  hostPathVolumes: {hostpath_vols}")
            sa = getattr(spec, 'service_account_name', 'default')
            lines.append(f"  serviceAccountName: {sa}")
            for c in (init_containers + containers):
                sc  = getattr(c, 'security_context', None)
                res = getattr(c, 'resources', None)
                lines.append(f"  container: {c.name}")
                lines.append(f"    image: {c.image}")
                if sc:
                    lines.append(f"    privileged: {getattr(sc,'privileged',False)}")
                    lines.append(f"    runAsUser: {getattr(sc,'run_as_user','?')}")
                    lines.append(f"    runAsNonRoot: {getattr(sc,'run_as_non_root','?')}")
                    lines.append(f"    readOnlyRootFilesystem: {getattr(sc,'read_only_root_filesystem','?')}")
                    lines.append(f"    allowPrivilegeEscalation: {getattr(sc,'allow_privilege_escalation','?')}")
                    caps = getattr(sc, 'capabilities', None)
                    if caps:
                        lines.append(f"    capabilities.add: {getattr(caps,'add','none')}")
                        lines.append(f"    capabilities.drop: {getattr(caps,'drop','none')}")
                if res:
                    lines.append(f"    limits: {getattr(res,'limits','not set')}")
                    lines.append(f"    requests: {getattr(res,'requests','not set')}")
                lines.append(f"    readinessProbe: {'set' if c.readiness_probe else 'MISSING'}")
                lines.append(f"    livenessProbe: {'set' if c.liveness_probe else 'MISSING'}")
                # Check for secrets in env vars
                envs = getattr(c, 'env', []) or []
                secret_envs = [e.name for e in envs if getattr(e,'value',None) and
                               any(kw in e.name.upper() for kw in ['SECRET','PASSWORD','TOKEN','KEY','CREDENTIAL'])]
                if secret_envs:
                    lines.append(f"    WARN_plaintext_secrets_in_env: {secret_envs}")
            return "\n".join(lines)


        def _collect(label, items, to_dict_fn):
            if not items:
                return
            lines = [f"\n=== {label} ==="]
            for item in items:
                try:
                    lines.append(to_dict_fn(item))
                except Exception:
                    pass
            inventory_sections.append("\n".join(lines))

        _collect("Deployments",  deploys,  _workload_summary)
        _collect("StatefulSets", stateful, _workload_summary)
        _collect("DaemonSets",   daemons,  _workload_summary)

        # Orphan pods (not owned by a controller)
        orphan_pods = [p for p in pods if not p.metadata.owner_references]
        if orphan_pods:
            lines = [f"=== Orphan Pods (no owner) ==="]
            for p in orphan_pods:
                lines.append(f"  pod: {p.metadata.name}  phase: {p.status.phase}")
            inventory_sections.append("\n".join(lines))

        # Jobs
        if jobs:
            j_lines = ["=== Jobs ==="]
            for j in jobs:
                j_lines.append(f"  job: {j.metadata.name}  completions: {j.spec.completions}  backoffLimit: {j.spec.backoff_limit}")
            inventory_sections.append("\n".join(j_lines))

        # ServiceAccounts
        sas = k8s_results.get('sas', [])
        if sas:
            sa_lines = ["=== ServiceAccounts ==="]
            for sa in sas:
                auto_mount = getattr(sa, 'automount_service_account_token', True)
                sa_lines.append(f"  sa: {sa.metadata.name}  automountToken: {auto_mount}")
            inventory_sections.append("\n".join(sa_lines))

        # NetworkPolicies
        netpols = k8s_results.get('netpols', [])
        if netpols:
            np_lines = ["=== NetworkPolicies ==="]
            for np in netpols:
                np_lines.append(f"  policy: {np.metadata.name}  podSelector: {np.spec.pod_selector}")
            inventory_sections.append("\n".join(np_lines))
        else:
            inventory_sections.append("=== NetworkPolicies ===\n  NONE — all pod-to-pod traffic is unrestricted")

        # RBAC — RoleBindings
        rbs = k8s_results.get('rbs', [])
        if rbs:
            rb_lines = ["=== RoleBindings (namespace-scoped) ==="]
            for rb in rbs:
                subjects = [(s.kind, s.name) for s in (rb.subjects or [])]
                rb_lines.append(f"  rb: {rb.metadata.name}  role: {rb.role_ref.name}  subjects: {subjects}")
            inventory_sections.append("\n".join(rb_lines))

        # ConfigMaps — check for embedded credentials, certs, risky keys
        cms = k8s_results.get('cms', [])
        if cms:
            cm_lines = ["=== ConfigMaps ==="]
            for cm in cms:
                if cm.metadata.name in ('kube-root-ca.crt',):
                    continue  # skip system CMs
                data_keys = list((cm.data or {}).keys())
                binary_keys = list((cm.binary_data or {}).keys())
                suspicious_keys = [k for k in data_keys if any(
                    kw in k.lower() for kw in ['password', 'secret', 'token', 'key', 'credential', 'cert', 'private', 'auth']
                )]
                cm_lines.append(f"  cm: {cm.metadata.name}  keys: {data_keys[:10]}")
                if suspicious_keys:
                    cm_lines.append(f"    WARN_sensitive_keys_in_configmap: {suspicious_keys}")
                if binary_keys:
                    cm_lines.append(f"    binary_keys: {binary_keys[:5]}")
            inventory_sections.append("\n".join(cm_lines))

        # Secrets — metadata only (never log values); check types and naming
        secrets = k8s_results.get('secrets', [])
        if secrets:
            sec_lines = ["=== Secrets ==="]
            for s in secrets:
                if s.metadata.name.startswith('sh.helm') or s.metadata.name.startswith('default-token'):
                    continue
                keys = list((s.data or {}).keys())
                sec_lines.append(f"  secret: {s.metadata.name}  type: {s.type}  keys: {keys[:8]}")
                # Flag generic Opaque secrets with many keys (may be overloaded)
                if s.type == 'Opaque' and len(keys) > 5:
                    sec_lines.append(f"    WARN_overloaded_secret: {len(keys)} keys in one Secret (prefer scoped secrets)")
                # Flag secrets with env-var-like key names that suggest direct injection
                env_like = [k for k in keys if k.isupper() and '_' in k]
                if env_like:
                    sec_lines.append(f"    INFO_env_style_keys: {env_like[:5]}")
            inventory_sections.append("\n".join(sec_lines))

        full_inventory = "\n\n".join(inventory_sections)

        # ── 2. If Gemini not configured, fall back to deterministic checks ───
        if not get_model():
            risks = []
            for d in deploys:
                name = d.metadata.name
                spec = d.spec.template.spec
                if getattr(spec, 'host_pid', False) or getattr(spec, 'host_ipc', False) or getattr(spec, 'host_network', False):
                    risks.append({"resource": name, "kind": "Deployment", "severity": "Critical",
                                  "category": "Pod Security", "issue": "Host namespace sharing (PID/IPC/Network)",
                                  "remediation": "Set hostPID: false, hostIPC: false, hostNetwork: false",
                                  "cve_references": ["CIS-5.2.4"], "ai_insight": "Host namespace sharing gives container access to host-level resources."})
                for c in (spec.containers or []):
                    sc = getattr(c, 'security_context', None)
                    if sc and getattr(sc, 'privileged', False):
                        risks.append({"resource": name, "kind": "Deployment", "severity": "Critical",
                                      "category": "Pod Security", "issue": f"Container '{c.name}' is privileged",
                                      "remediation": "Remove securityContext.privileged: true",
                                      "cve_references": ["CIS-5.2.1"], "ai_insight": "Privileged containers have unrestricted host access."})
                    res = getattr(c, 'resources', None)
                    if not res or not getattr(res, 'limits', None):
                        risks.append({"resource": name, "kind": "Deployment", "severity": "Medium",
                                      "category": "Resource Management", "issue": f"Container '{c.name}' missing resource limits",
                                      "remediation": "Define resources.limits.cpu and resources.limits.memory",
                                      "cve_references": ["CIS-5.2.5"], "ai_insight": "Missing limits allow unbounded resource consumption."})
            counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
            for r in risks:
                counts[r.get("severity", "Info")] = counts.get(r.get("severity", "Info"), 0) + 1
            return jsonify({
                "executive_summary": f"Found {len(risks)} issues across {len(deploys)} deployments. Gemini not configured — running deterministic checks only.",
                "severity_counts": counts,
                "risks": risks
            })

        # ── 3. Gemini full audit ─────────────────────────────────────────────
        prompt = f"""You are a Kubernetes security expert performing a comprehensive cluster security audit aligned with the CIS Kubernetes Benchmark v1.8 and NSA/CISA Kubernetes Hardening Guidance.

Analyse the following cluster inventory from namespace '{namespace}' and identify ALL security risks.

Your response MUST be a valid JSON object (no markdown, no explanation) with this exact schema:
{{
  "executive_summary": "2-3 sentences summarising the overall security posture of the namespace.",
  "severity_counts": {{"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}},
  "risks": [
    {{
      "severity": "Critical|High|Medium|Low|Info",
      "category": "one of: Pod Security | RBAC | Network Policy | Image Security | Resource Management | Secrets Management | Supply Chain | Runtime | Availability",
      "resource": "name of the affected K8s resource",
      "kind": "Deployment|StatefulSet|DaemonSet|Pod|ServiceAccount|NetworkPolicy|RoleBinding|Job|...",
      "issue": "Clear 1-sentence description of the finding",
      "remediation": "Exact YAML field or kubectl command to fix it",
      "cve_references": ["CIS-5.x.x or CVE-XXXX-XXXX or NSA-section"],
      "ai_insight": "1 sentence explaining WHY this is a risk in this specific context"
    }}
  ]
}}

Check for ALL of the following (do not skip any category):

POD SECURITY:
- Privileged containers (CIS 5.2.1)
- Host PID/IPC/Network sharing (CIS 5.2.2-4)
- Containers running as root (runAsUser=0 or missing runAsNonRoot: true) (CIS 5.2.6)
- Missing allowPrivilegeEscalation: false (CIS 5.2.5)
- Missing readOnlyRootFilesystem: true (CIS 5.2.7)
- Dangerous Linux capabilities added (NET_ADMIN, SYS_ADMIN, etc.) (CIS 5.2.8-9)
- HostPath volume mounts (access to node filesystem) (CIS 5.2.10)

RESOURCE MANAGEMENT:
- Missing CPU/memory limits (DoS risk) (CIS 5.2.5)
- Missing resource requests (scheduling instability)

AVAILABILITY:
- Missing readiness probes (traffic to unready pods)
- Missing liveness probes (stuck pods not restarted)
- Single replica workloads (no HA)

NETWORK POLICY:
- Namespaces with NO NetworkPolicy (unrestricted egress/ingress)
- Overly permissive NetworkPolicies (0.0.0.0/0 CIDR)

RBAC:
- ServiceAccounts with automountServiceAccountToken: true (default) when not needed
- RoleBindings granting cluster-admin or wildcard (*) verbs
- Default service account used by workloads

IMAGE SECURITY:
- Images using 'latest' tag (supply chain risk)
- Images without a registry prefix (pulling from Docker Hub)

SECRETS MANAGEMENT:
- Secrets or passwords passed as plaintext env vars (not from secretKeyRef)
- WARN_plaintext_secrets_in_env markers in the inventory
- Overloaded Opaque secrets (WARN_overloaded_secret: many keys in one Secret)

CONFIGMAP SECURITY:
- WARN_sensitive_keys_in_configmap: credentials, tokens, or private keys stored in ConfigMaps (should use Secrets instead)
- ConfigMaps that appear to store TLS certificates or private keys (use cert-manager or Secrets)

Flag EVERY issue you find — do not cap the list. Be thorough.
severity_counts must match the actual counts in the risks array.
Return ONLY the JSON. No markdown fences. No prose.

=== CLUSTER INVENTORY ===
{full_inventory[:22000]}
"""
        response = gemini_generate_with_retry(prompt)
        result = parse_gemini_json(response.text)
        result.setdefault("executive_summary", "Audit complete.")
        result.setdefault("severity_counts", {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0})
        result.setdefault("risks", [])
        _cache_set(cache_key, result)
        return jsonify(result)

    except json.JSONDecodeError as e:
        print(f"[security_scan] Gemini returned non-JSON: {e}")
        return jsonify({"executive_summary": "AI returned malformed output. Try re-running the scan.",
                        "severity_counts": {}, "risks": []})
    except Exception as e:
        print(f"[security_scan] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/vuln_scan')
def vuln_scan():
    """OSS Vulnerability Scan powered by Trivy.

    Collects unique container images from the namespace, runs Trivy against each
    image, aggregates CVE findings, and optionally adds a Gemini AI summary.

    Falls back to lightweight image metadata checks if Trivy is not installed.

    Returns:
        {
          "scan_source": "trivy" | "metadata-only",
          "trivy_version": str,
          "images_scanned": int,
          "executive_summary": str,
          "severity_counts": { Critical, High, Medium, Low, Info },
          "risks": [ { severity, category, resource, kind, image, package,
                        installed_version, fixed_version, issue, remediation,
                        cve_references, ai_insight } ]
        }
    """
    import subprocess, shutil

    namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    try:
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # ── 1. Collect unique images and their workload context ───────────────
        image_to_workloads = {}  # image -> [(resource_name, kind)]

        def _add_image(image, resource_name, kind):
            if image:
                image_to_workloads.setdefault(image, []).append((resource_name, kind))

        for d in apps_v1.list_namespaced_deployment(namespace).items:
            for c in (d.spec.template.spec.containers or []):
                _add_image(c.image, d.metadata.name, 'Deployment')

        for s in apps_v1.list_namespaced_stateful_set(namespace).items:
            for c in (s.spec.template.spec.containers or []):
                _add_image(c.image, s.metadata.name, 'StatefulSet')

        for d in apps_v1.list_namespaced_daemon_set(namespace).items:
            for c in (d.spec.template.spec.containers or []):
                _add_image(c.image, d.metadata.name, 'DaemonSet')

        for p in core_v1.list_namespaced_pod(namespace).items:
            # Only orphan pods (not managed by a controller)
            if not p.metadata.owner_references:
                for c in (p.spec.containers or []):
                    _add_image(c.image, p.metadata.name, 'Pod')

        risks = []
        severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
        trivy_version = None
        scan_source = "metadata-only"
        scan_errors = []  # Track per-image errors to surface to UI

        # ── 2. Try Trivy scan ────────────────────────────────────────────────
        trivy_bin = shutil.which('trivy')
        if trivy_bin:
            scan_source = "trivy"
            try:
                ver_result = subprocess.run(
                    [trivy_bin, '--version'], capture_output=True, text=True, timeout=10
                )
                trivy_version = ver_result.stdout.strip().split('\n')[0].replace('Version: ', '')
            except Exception:
                trivy_version = "unknown"

            for image, workloads in image_to_workloads.items():
                try:
                    print(f"[vuln_scan] Scanning image: {image}")
                    result = subprocess.run(
                        [trivy_bin, 'image', '--format', 'json', '--quiet',
                         '--timeout', '120s', '--skip-db-update', image],
                        capture_output=True, text=True, timeout=180
                    )
                    if result.returncode not in (0, 1):  # 1 = vulns found
                        err_msg = result.stderr[:300] if result.stderr else f"exit code {result.returncode}"
                        print(f"[vuln_scan] Trivy non-zero for {image}: {err_msg}")
                        scan_errors.append({"image": image, "error": err_msg})
                        continue

                    trivy_data = json.loads(result.stdout)
                    for target_result in (trivy_data.get('Results') or []):
                        for vuln in (target_result.get('Vulnerabilities') or []):
                            sev = vuln.get('Severity', 'Unknown').capitalize()
                            if sev not in severity_counts:
                                sev = 'Info'
                            severity_counts[sev] = severity_counts.get(sev, 0) + 1
                            resource_name, kind = workloads[0] if workloads else ('unknown', 'Pod')
                            cve_id = vuln.get('VulnerabilityID', '')
                            pkg = vuln.get('PkgName', '')
                            installed = vuln.get('InstalledVersion', '')
                            fixed = vuln.get('FixedVersion', '')
                            title = vuln.get('Title', vuln.get('Description', cve_id))[:120]
                            risks.append({
                                "severity": sev,
                                "category": "OSS Vulnerability",
                                "resource": resource_name,
                                "kind": kind,
                                "image": image,
                                "package": pkg,
                                "installed_version": installed,
                                "fixed_version": fixed or "no fix available",
                                "issue": f"{cve_id} — {title}",
                                "remediation": (
                                    f"Update {pkg} to {fixed}" if fixed
                                    else f"No fix yet for {cve_id}; consider alternative package or image"
                                ),
                                "cve_references": [cve_id] if cve_id else [],
                                "ai_insight": None
                            })
                    print(f"[vuln_scan] {image}: found {sum(1 for r in risks if r['image'] == image)} vulns")
                except subprocess.TimeoutExpired:
                    print(f"[vuln_scan] Trivy timeout for {image}")
                    scan_errors.append({"image": image, "error": "Scan timed out (>180s). Image may be too large or registry is slow."})
                except json.JSONDecodeError as e:
                    print(f"[vuln_scan] Trivy JSON parse error for {image}: {e}")
                    scan_errors.append({"image": image, "error": f"Trivy output was not valid JSON: {e}"})
                except Exception as e:
                    print(f"[vuln_scan] Trivy error for {image}: {e}")
                    scan_errors.append({"image": image, "error": str(e)})

        else:
            # ── 3. Metadata-only fallback (no Trivy) ────────────────────────
            print("[vuln_scan] Trivy not found, running metadata-only checks")
            for image, workloads in image_to_workloads.items():
                resource_name, kind = workloads[0] if workloads else ('unknown', 'Pod')
                issues = []
                if ':latest' in image or ('@' not in image and ':' not in image.split('/')[-1]):
                    issues.append({
                        "severity": "High",
                        "issue": f"Image uses ':latest' or no tag — unpinned images prevent reproducible deployments and may silently pick up vulnerable versions",
                        "remediation": f"Pin to an exact digest: {image.split(':')[0]}@sha256:<digest>",
                        "cve_references": ["CIS-5.4.1"]
                    })
                if '/' not in image or image.startswith('docker.io/'):
                    issues.append({
                        "severity": "Medium",
                        "issue": "Image pulled from Docker Hub — no SLA on availability and higher supply chain risk vs private registry",
                        "remediation": f"Mirror {image} to your private Artifact Registry and update imagePullPolicy to IfNotPresent",
                        "cve_references": []
                    })
                for iss in issues:
                    sev = iss["severity"]
                    severity_counts[sev] = severity_counts.get(sev, 0) + 1
                    risks.append({
                        "severity": sev,
                        "category": "OSS Vulnerability",
                        "resource": resource_name,
                        "kind": kind,
                        "image": image,
                        "package": "image metadata",
                        "installed_version": "-",
                        "fixed_version": "-",
                        "issue": iss["issue"],
                        "remediation": iss["remediation"],
                        "cve_references": iss["cve_references"],
                        "ai_insight": None
                    })

        # Sort by severity
        sev_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
        risks.sort(key=lambda r: sev_order.get(r["severity"], 5))

        # ── 4. Gemini executive summary (top-20 findings) ────────────────────
        executive_summary = f"Scanned {len(image_to_workloads)} images via {scan_source}. Found {len(risks)} findings."
        if get_model() and risks:
            top_risks = risks[:20]
            risk_text = "\n".join(
                f"[{r['severity']}] {r['image']} — {r['issue'][:100]} (pkg: {r['package']}, fixed: {r['fixed_version']})"
                for r in top_risks
            )
            prompt = f"""You are a senior Kubernetes security engineer. Summarise these OSS vulnerability findings in 2-3 sentences.
Focus on: most urgent images to update, estimated blast radius, and the simplest remediation path.

FINDINGS (namespace: {namespace}):
{risk_text}

Write the executive summary only — no JSON, no markdown, just plain text."""
            try:
                resp = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
                executive_summary = resp.text.strip()
                # Enrich the top 5 Critical/High with ai_insight
                enrich_prompt = f"""For each finding below, write a ONE-sentence AI insight explaining the specific risk in context.
Return ONLY a JSON array of strings in the same order.

FINDINGS:
{json.dumps([{{'severity': r['severity'], 'image': r['image'], 'issue': r['issue'], 'package': r['package']}} for r in risks[:5]])}"""
                enrich_resp = get_model().models.generate_content(model=GEMINI_MODEL, contents=enrich_prompt)
                raw_insights = _extract_json(enrich_resp.text)
                if isinstance(raw_insights, list):
                    for i, insight in enumerate(raw_insights[:5]):
                        risks[i]['ai_insight'] = str(insight)
            except Exception as e:
                print(f"[vuln_scan] Gemini summary error: {e}")

        return jsonify({
            "scan_source": scan_source,
            "trivy_version": trivy_version,
            "images_scanned": len(image_to_workloads),
            "executive_summary": executive_summary,
            "severity_counts": severity_counts,
            "risks": risks,
            "scan_errors": scan_errors,
            "images_list": list(image_to_workloads.keys())
        })

    except Exception as e:
        print(f"[vuln_scan] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/vuln_scan/debug')
def vuln_scan_debug():
    """Diagnostic endpoint — test Trivy installation and image scanning capability."""
    import subprocess, shutil

    report = {}

    # 1. Check Trivy binary
    trivy_bin = shutil.which('trivy')
    report['trivy_binary'] = trivy_bin or 'NOT FOUND'

    if not trivy_bin:
        report['status'] = 'FAIL'
        report['message'] = 'Trivy is not installed or not in PATH. Install it in the Docker image.'
        return jsonify(report)

    # 2. Check version
    try:
        ver = subprocess.run([trivy_bin, '--version'], capture_output=True, text=True, timeout=10)
        report['trivy_version'] = ver.stdout.strip()
    except Exception as e:
        report['trivy_version'] = f'Error: {e}'

    # 3. Check if Trivy DB exists
    try:
        db_check = subprocess.run(
            [trivy_bin, 'image', '--list-all-pkgs', '--format', 'json', '--quiet',
             '--skip-db-update', 'alpine:3.19'],
            capture_output=True, text=True, timeout=60
        )
        if db_check.returncode == 0 or db_check.returncode == 1:
            report['db_status'] = 'OK'
            try:
                data = json.loads(db_check.stdout)
                results = data.get('Results', [])
                total_vulns = sum(len(r.get('Vulnerabilities', []) or []) for r in results)
                report['test_scan_alpine'] = f'SUCCESS — found {total_vulns} vulnerabilities in alpine:3.19'
            except json.JSONDecodeError:
                report['test_scan_alpine'] = 'Trivy ran but output is not JSON'
                report['raw_stdout'] = db_check.stdout[:500]
        else:
            report['db_status'] = 'ERROR'
            report['test_scan_alpine'] = f'Trivy exited with code {db_check.returncode}'
            report['stderr'] = db_check.stderr[:500]
    except subprocess.TimeoutExpired:
        report['test_scan_alpine'] = 'TIMEOUT — Trivy took >60s on alpine:3.19'
    except Exception as e:
        report['test_scan_alpine'] = f'Error: {e}'

    # 4. Check namespace images
    try:
        namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        images = set()
        for d in apps_v1.list_namespaced_deployment(namespace).items:
            for c in (d.spec.template.spec.containers or []):
                images.add(c.image)
        for p in core_v1.list_namespaced_pod(namespace).items:
            for c in (p.spec.containers or []):
                images.add(c.image)
        report['namespace'] = namespace
        report['images_found'] = sorted(images)
        report['image_count'] = len(images)

        # 5. Try scanning the first real image
        if images:
            test_image = sorted(images)[0]
            report['test_real_image'] = test_image
            try:
                result = subprocess.run(
                    [trivy_bin, 'image', '--format', 'json', '--quiet',
                     '--timeout', '120s', '--skip-db-update', test_image],
                    capture_output=True, text=True, timeout=130
                )
                if result.returncode in (0, 1):
                    try:
                        data = json.loads(result.stdout)
                        results = data.get('Results', [])
                        total_vulns = sum(len(r.get('Vulnerabilities', []) or []) for r in results)
                        report['test_real_result'] = f'SUCCESS — found {total_vulns} vulnerabilities'
                    except json.JSONDecodeError:
                        report['test_real_result'] = 'Trivy ran but output is not JSON'
                        report['test_real_stdout'] = result.stdout[:300]
                else:
                    report['test_real_result'] = f'FAILED — exit code {result.returncode}'
                    report['test_real_stderr'] = result.stderr[:500]
            except subprocess.TimeoutExpired:
                report['test_real_result'] = 'TIMEOUT (>130s) — may need registry auth or image is too large'
            except Exception as e:
                report['test_real_result'] = f'Error: {e}'

    except Exception as e:
        report['namespace_error'] = str(e)

    report['status'] = 'OK'
    report['message'] = 'Review the fields above to diagnose scan issues.'
    return jsonify(report)


@app.route('/api/ai/query', methods=['POST'])
def ai_query():
    """Gemini-powered natural language command interpreter.

    Understands freeform user queries and returns a structured JSON action
    that the frontend executes directly against the dashboard (filter, scale,
    logs, delete, describe, analyze, restart, events, reset, or chat).

    The output JSON shape is identical to the old regex version so the
    existing frontend action handler requires no changes.
    """
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        query = data.get('query', '').strip()
        if not query:
            return jsonify({'error': 'Empty query'}), 400

        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        # ── Gather rich cluster context so Gemini can resolve any query ──────
        resource_lines = []
        try:
            v1       = client.CoreV1Api()
            apps_v1  = client.AppsV1Api()
            deploys  = apps_v1.list_namespaced_deployment(namespace).items
            stateful = apps_v1.list_namespaced_stateful_set(namespace).items
            pods     = v1.list_namespaced_pod(namespace).items
            svcs     = v1.list_namespaced_service(namespace).items

            for d in deploys:
                containers = d.spec.template.spec.containers or []
                img   = containers[0].image if containers else "?"
                res   = containers[0].resources if containers else None
                lim   = dict(res.limits)   if res and res.limits   else {}
                req   = dict(res.requests) if res and res.requests else {}
                helm_chart   = d.metadata.labels.get('helm.sh/chart', '') if d.metadata.labels else ''
                helm_release = d.metadata.labels.get('app.kubernetes.io/instance', '') if d.metadata.labels else ''
                ready = d.status.ready_replicas or 0
                desired = d.spec.replicas or 0
                resource_lines.append(f"Deployment:{d.metadata.name} image={img} ready={ready}/{desired} "
                    f"limits={lim or 'none'} requests={req or 'none'} "
                    f"helm_chart={helm_chart or 'none'} helm_release={helm_release or 'none'}")

            for s in stateful:
                containers = s.spec.template.spec.containers or []
                img = containers[0].image if containers else "?"
                helm_chart = s.metadata.labels.get('helm.sh/chart', '') if s.metadata.labels else ''
                resource_lines.append(f"StatefulSet:{s.metadata.name} image={img} "
                    f"ready={s.status.ready_replicas or 0}/{s.spec.replicas or 0} "
                    f"helm_chart={helm_chart or 'none'}")

            for p in pods:
                phase    = p.status.phase or "Unknown"
                restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
                reason   = ""
                for cs in (p.status.container_statuses or []):
                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or ""
                imgs = [c.image for c in (p.spec.containers or [])]
                resource_lines.append(f"Pod:{p.metadata.name} status={phase}" + (f"/{reason}" if reason else "") +
                    f" restarts={restarts} images={imgs}")

            for s in svcs:
                ports = ",".join(f"{p.port}" for p in (s.spec.ports or []))
                resource_lines.append(f"Service:{s.metadata.name} type={s.spec.type} ports={ports}")

            # Jobs
            try:
                batch_v1 = client.BatchV1Api()
                jobs = batch_v1.list_namespaced_job(namespace).items
                for j in jobs:
                    status = 'Succeeded' if (j.status.succeeded or 0) > 0 else ('Failed' if (j.status.failed or 0) > 0 else 'Running')
                    resource_lines.append(f"Job:{j.metadata.name} status={status}")
            except Exception:
                pass

            # Ingresses
            try:
                net_v1 = client.NetworkingV1Api()
                ingresses = net_v1.list_namespaced_ingress(namespace).items
                for ing in ingresses:
                    hosts = ','.join(r.host or '*' for r in (ing.spec.rules or []))
                    resource_lines.append(f"Ingress:{ing.metadata.name} hosts={hosts}")
            except Exception:
                pass

            # VirtualServices (Istio)
            try:
                co_api = client.CustomObjectsApi()
                vs_list = co_api.list_namespaced_custom_object(
                    'networking.istio.io', 'v1beta1', namespace, 'virtualservices')
                for vs in vs_list.get('items', []):
                    hosts = ','.join(vs.get('spec', {}).get('hosts', []))
                    resource_lines.append(f"VirtualService:{vs['metadata']['name']} hosts={hosts}")
            except Exception:
                pass

            # ConfigMaps
            try:
                cms = v1.list_namespaced_config_map(namespace).items
                for cm in cms[:20]:  # Limit to avoid noise
                    resource_lines.append(f"ConfigMap:{cm.metadata.name}")
            except Exception:
                pass

            # Secrets
            try:
                secrets = v1.list_namespaced_secret(namespace).items
                for sec in secrets[:20]:
                    resource_lines.append(f"Secret:{sec.metadata.name} type={sec.type}")
            except Exception:
                pass

        except Exception as ctx_err:
            resource_lines.append(f"(Could not fetch cluster data: {ctx_err})")

        cluster_context = (
            f"Live resources in namespace '{namespace}':\n" + "\n".join(resource_lines)
            if resource_lines else "Cluster resource list unavailable."
        )

        if not get_model():
            return jsonify({
                'action': 'chat',
                'target': '', 'criteria': {}, 'count': None,
                'message': '⚠️ Gemini not configured — AI search requires Gemini.',
                'reply': (
                    f'⚠️ **Gemini is not configured.** Ask AI and AI Chat require Gemini to function.\n\n'
                    f'Check `/api/ai/status` to see which environment variable is missing '
                    f'(`GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `GCP_REGION`).'
                )
            })

        # ── Gemini intent classification ─────────────────────────────────────
        prompt = f"""You are an intelligent Kubernetes dashboard assistant for namespace '{namespace}'.
The user typed a query into an AI search bar. Classify their intent and return a JSON action object.

{cluster_context}

User query: "{query}"

Return ONLY a valid JSON object (no markdown, no explanation):

{{
  "action": one of: "filter" | "scale" | "logs" | "delete" | "describe" | "analyze" | "restart" | "events" | "reset" | "navigate" | "optimize" | "security" | "explain" | "yaml" | "image" | "chat",
  "target": the exact resource name from the cluster context above (fuzzy-match if needed),
  "resource_type": the K8s kind of the target resource - one of: "Deployment" | "Service" | "Pod" | "StatefulSet" | "DaemonSet" | "ConfigMap" | "Secret" | "Job" | "CronJob" | "Ingress" | "NetworkPolicy" | "HPA" | "VirtualService" | "DestinationRule" | "Gateway" | "Namespace" | null,
  "criteria": {{}} or filter object e.g. {{"status": "Failed"}},
  "count": null or integer (scale action only),
  "message": short 1-sentence friendly confirmation,
  "reply": null or answer string (for explain/chat/image actions only)
}}

Action meanings:

KUBERNETES OPERATIONS — use exact resource names from the cluster context above:
- "filter": Show/filter by status or kind. target=Kind (Pod/Deployment/StatefulSet). criteria={{"status":"Failed"}} etc.
- "scale": Change replicas. target=resource name from context. count=integer.
- "logs": Open logs. target=pod or deployment name from context.
- "delete": Delete resource. target=name from context.
- "describe": Show env vars / full config. target=name from context.
- "analyze": AI Root Cause Analysis. target=name from context.
- "restart": Rolling restart a Deployment/StatefulSet. target=name from context.
- "events": Show K8s events. target=resource name or empty for namespace.
- "reset": Clear all filters, no target.
- "yaml": Show YAML manifest. target=resource name from context. resource_type=exact kind (Deployment/Service/Pod/StatefulSet etc.) from context. CRITICAL: if the user says "service yaml" or "show service", resource_type MUST be "Service". If they say "deployment yaml", resource_type MUST be "Deployment". Always match the user-specified resource kind. Use for: "show yaml", "get manifest", "yaml definition", "show config file".
- "image": Answer what image/version/tag/helm chart a resource uses. Set reply to the exact image string and helm_chart from the cluster context. Use for: "what image", "which version", "image tag", "helm chart version", "what helm chart".

NAVIGATION: "navigate" — target = "workloads"|"networking"|"optimizer"|"security"|"yaml-gen"
AI TRIGGERS: "optimize" (cost/resources), "security" (security posture scan)

EXPLAIN & CHAT:
- "explain": Kubernetes concepts, best practices, what an error means. Set reply to 2-5 sentence answer.
- "chat": General questions. Set reply to helpful answer referencing namespace '{namespace}' and actual resource names from context.

IMPORTANT RULES:
- ALWAYS use exact resource names from the cluster context. Never make up names.
- For "image": set reply = "image=<exact_image> helm_chart=<helm_chart> helm_release=<helm_release>" from the context.
- For "yaml", "logs", "events", "describe", "analyze", "restart": match the resource name from context using fuzzy matching if the user used a partial name. Always set resource_type to the correct kind.
- For "yaml": ALWAYS set resource_type. If the user mentions "service" → resource_type="Service". If "deployment" → resource_type="Deployment". If ambiguous, infer from context.
- For "explain" and "chat" and "image": always populate "reply" with the actual answer. Never leave it null.
- Prefer specific actions over "chat".

Return ONLY the JSON object. No markdown. No code fences. No explanation.
"""


        response = gemini_generate_with_retry(prompt)
        parsed = parse_gemini_json(response.text)

        # Ensure required fields exist
        parsed.setdefault('action', 'chat')
        parsed.setdefault('target', '')
        parsed.setdefault('criteria', {})
        parsed.setdefault('count', None)
        parsed.setdefault('message', query)

        return jsonify(parsed)

    except json.JSONDecodeError as e:
        print(f"[ai_query] Gemini returned non-JSON: {e}")
        return jsonify({
            'action': 'chat',
            'message': "I understood your request but couldn't parse the intent. Try rephrasing.",
            'target': '', 'criteria': {}, 'count': None
        })
    except Exception as e:
        print(f"[ai_query] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/summarize_logs', methods=['POST'])
def summarize_logs():
    """Fetch logs from ALL containers in a pod and ask Gemini for a structured analysis.
    Returns: { summary, errors[], recommendations[], critical_errors[], gemini_powered }
    """
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        pod_name  = data.get('pod_name')

        if pod_name:
            aggregated_logs = fetch_pod_logs_aggregated(pod_name, namespace)
            log_source = f"all containers in pod '{pod_name}' (namespace: {namespace})"
        else:
            aggregated_logs = data.get('logs', '')
            log_source = "provided log text"

        if not aggregated_logs or aggregated_logs.strip() == '':
            return jsonify({'summary': 'No logs found to analyse.', 'errors': [], 'recommendations': [], 'critical_errors': [], 'gemini_powered': False})

        if not get_model():
            return jsonify({
                'summary': 'Gemini not configured. Set GCP_PROJECT_ID env var to enable AI log analysis.',
                'errors': [], 'recommendations': [], 'critical_errors': [], 'gemini_powered': False
            })

        prompt = f"""You are a Kubernetes SRE expert. Analyse logs from {log_source}.
Return ONLY a valid JSON object (no markdown fences, no extra text):
{{
  "summary": "2-3 sentence plain-text summary of pod health and root cause if any",
  "errors": ["exact log line or error message 1", "exact log line 2"],
  "recommendations": ["kubectl command or action 1", "action 2"],
  "health_status": "HEALTHY|DEGRADED|FAILING"
}}

Rules:
- errors: list up to 5 most important ERROR/FATAL/WARN log lines verbatim
- recommendations: list up to 4 concrete fix actions (kubectl commands preferred)
- If healthy, errors=[] and recommendations=["No action required"]

=== LOGS ===
{aggregated_logs[:16000]}
"""
        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        try:
            import json as _json
            parsed = _json.loads(raw)
            return jsonify({
                'summary': parsed.get('summary', ''),
                'errors': parsed.get('errors', []),
                'recommendations': parsed.get('recommendations', []),
                'critical_errors': parsed.get('errors', []),  # legacy compat
                'health_status': parsed.get('health_status', 'UNKNOWN'),
                'gemini_powered': True,
            })
        except Exception:
            # Gemini returned markdown — fall back to returning it as summary
            return jsonify({'summary': raw, 'errors': [], 'recommendations': [], 'critical_errors': [], 'gemini_powered': True})

    except Exception as e:
        print(f"Error in summarize_logs: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/restart', methods=['POST'])
def restart_workload():
    try:
        data = request.json
        name = data.get('name')
        kind = data.get('type')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        
        if not all([name, kind]):
             return jsonify({'error': 'Missing name or type'}), 400

        apps_v1 = client.AppsV1Api()
        now = datetime.utcnow().isoformat()
        body = {
            'spec': {
                'template': {
                    'metadata': {
                        'annotations': {
                            'kubectl.kubernetes.io/restartedAt': now
                        }
                    }
                }
            }
        }
        
        if kind == 'Deployment':
            apps_v1.patch_namespaced_deployment(name, namespace, body)
        elif kind == 'StatefulSet':
            apps_v1.patch_namespaced_stateful_set(name, namespace, body)
        elif kind == 'DaemonSet':
            apps_v1.patch_namespaced_daemon_set(name, namespace, body)
        else:
            return jsonify({'error': f"Restart not supported for {kind}"}), 400
            
        return jsonify({'message': f"Restart triggered for {kind} {name}"})
    except Exception as e:
        print(f"Error restarting: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/<name>')
def get_resource_events(name):
    try:
        namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        v1 = client.CoreV1Api()
        
        # Filter events by involvedObject.name
        events = v1.list_namespaced_event(namespace, field_selector=f"involvedObject.name={name}")
        
        event_list = []
        for e in events.items:
            event_list.append({
                'type': e.type,
                'reason': e.reason,
                'message': e.message,
                'count': e.count,
                'last_timestamp': e.last_timestamp,
                'age': e.last_timestamp # Frontend can format this
            })
            
        # Sort by timestamp desc
        event_list.sort(key=lambda x: x['last_timestamp'] or datetime.min, reverse=True)
        return jsonify({'events': event_list})
    except Exception as e:
        print(f"Error fetching events: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/yaml/<name>')
def get_resource_yaml(name):
    try:
        namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        kind = request.args.get('type', 'Pod')
        
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        
        resource = None

        # ── Core & Apps API resources ──
        if kind == 'Pod':
            resource = v1.read_namespaced_pod(name, namespace, _preload_content=False)
        elif kind == 'Deployment':
            resource = apps_v1.read_namespaced_deployment(name, namespace, _preload_content=False)
        elif kind == 'Service':
            resource = v1.read_namespaced_service(name, namespace, _preload_content=False)
        elif kind == 'StatefulSet':
            resource = apps_v1.read_namespaced_stateful_set(name, namespace, _preload_content=False)
        elif kind == 'DaemonSet':
            resource = apps_v1.read_namespaced_daemon_set(name, namespace, _preload_content=False)
        elif kind == 'ConfigMap':
            resource = v1.read_namespaced_config_map(name, namespace, _preload_content=False)
        elif kind == 'Secret':
            resource = v1.read_namespaced_secret(name, namespace, _preload_content=False)

        # ── Batch API (Jobs / CronJobs) ──
        elif kind == 'Job':
            batch_v1 = client.BatchV1Api()
            resource = batch_v1.read_namespaced_job(name, namespace, _preload_content=False)
        elif kind == 'CronJob':
            batch_v1 = client.BatchV1Api()
            resource = batch_v1.read_namespaced_cron_job(name, namespace, _preload_content=False)

        # ── Networking API (Ingress, NetworkPolicy) ──
        elif kind == 'Ingress':
            net_v1 = client.NetworkingV1Api()
            resource = net_v1.read_namespaced_ingress(name, namespace, _preload_content=False)
        elif kind == 'NetworkPolicy':
            net_v1 = client.NetworkingV1Api()
            resource = net_v1.read_namespaced_network_policy(name, namespace, _preload_content=False)

        # ── Autoscaling (HPA) ──
        elif kind in ('HPA', 'HorizontalPodAutoscaler'):
            auto_v1 = client.AutoscalingV1Api()
            resource = auto_v1.read_namespaced_horizontal_pod_autoscaler(name, namespace, _preload_content=False)

        # ── Istio CRDs (VirtualService, DestinationRule, Gateway) ──
        elif kind == 'VirtualService':
            co_api = client.CustomObjectsApi()
            data = co_api.get_namespaced_custom_object(
                'networking.istio.io', 'v1beta1', namespace, 'virtualservices', name)
            if 'metadata' in data and 'managedFields' in data['metadata']:
                del data['metadata']['managedFields']
            return jsonify({'yaml': data})
        elif kind == 'DestinationRule':
            co_api = client.CustomObjectsApi()
            data = co_api.get_namespaced_custom_object(
                'networking.istio.io', 'v1beta1', namespace, 'destinationrules', name)
            if 'metadata' in data and 'managedFields' in data['metadata']:
                del data['metadata']['managedFields']
            return jsonify({'yaml': data})
        elif kind == 'Gateway':
            co_api = client.CustomObjectsApi()
            data = co_api.get_namespaced_custom_object(
                'networking.istio.io', 'v1beta1', namespace, 'gateways', name)
            if 'metadata' in data and 'managedFields' in data['metadata']:
                del data['metadata']['managedFields']
            return jsonify({'yaml': data})

        # ── Namespace (cluster-scoped) ──
        elif kind == 'Namespace':
            resource = v1.read_namespace(name, _preload_content=False)

        if resource:
             # Use json.load because _preload_content=False returns a HTTPResponse object
             import json
             data = json.loads(resource.data.decode('utf-8'))
             
             # Clean up managed fields for readability
             if 'metadata' in data and 'managedFields' in data['metadata']:
                 del data['metadata']['managedFields']
                 
             return jsonify({'yaml': data})
        else:
             return jsonify({'error': f'Resource type "{kind}" is not supported. Supported types: Pod, Deployment, Service, StatefulSet, DaemonSet, ConfigMap, Secret, Job, CronJob, Ingress, NetworkPolicy, HPA, VirtualService, DestinationRule, Gateway, Namespace.'}), 404

    except ApiException as e:
        if e.status == 404:
            return jsonify({'error': f'{kind} "{name}" not found in namespace "{namespace}".'}), 404
        print(f"Error fetching YAML: {e}")
        return jsonify({'error': str(e)}), e.status or 500
    except Exception as e:
        print(f"Error fetching YAML: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete', methods=['POST'])
def delete_resource():
    try:
        if not request.json:
            return jsonify({'error': 'Missing JSON body'}), 400
            
        data = request.json
        name = data.get('name')
        kind = data.get('type')
        
        current_ns = os.getenv('POD_NAMESPACE', 'default')
        namespace = data.get('namespace', current_ns)
        
        if not all([name, kind]):
             return jsonify({'error': 'Missing name or type'}), 400
             
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        
        if kind == 'Pod':
            v1.delete_namespaced_pod(name, namespace)
        elif kind == 'Deployment':
            apps_v1.delete_namespaced_deployment(name, namespace)
        elif kind == 'Service':
            v1.delete_namespaced_service(name, namespace)
        elif kind == 'StatefulSet':
            apps_v1.delete_namespaced_stateful_set(name, namespace)
        elif kind == 'DaemonSet':
            apps_v1.delete_namespaced_daemon_set(name, namespace)
        elif kind == 'Job':
            batch_v1 = client.BatchV1Api()
            batch_v1.delete_namespaced_job(name, namespace)
        elif kind == 'ConfigMap':
             v1.delete_namespaced_config_map(name, namespace)
        elif kind == 'Secret':
             v1.delete_namespaced_secret(name, namespace)
        else:
            return jsonify({'error': f'Delete not supported for {kind}'}), 400
            
        return jsonify({'message': f'Successfully deleted {kind} {name}'})

    except Exception as e:
        print(f"Error deleting resource: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/rca', methods=['POST'])
def ai_rca():
    """Gemini-powered Root Cause Analysis.

    Gathers live context from Kubernetes (pod logs from ALL containers,
    recent K8s events, workload spec) and asks Gemini to produce a
    structured SRE-quality RCA — no hardcoded patterns or regex.
    """
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        name      = data.get('name', '')
        kind      = data.get('type', 'Deployment')
        status    = data.get('status', 'Unknown')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not get_model():
            return jsonify({
                'analysis': (
                    f"## ⚠️ Gemini Not Configured\n\n"
                    f"Set `GCP_PROJECT_ID` and restart to enable AI-powered RCA.\n\n"
                    f"**Resource:** `{name}` | **Status:** `{status}`"
                )
            })

        # ── 1. Collect Kubernetes context ──────────────────────────────────
        context_sections = []
        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # A) Pod logs from ALL containers (init + app + sidecar)
        try:
            pods = v1.list_namespaced_pod(
                namespace,
                label_selector=f"app={name.split('-')[0]}"  # best-effort label match
            )
            for pod in pods.items[:3]:   # cap to 3 pods to stay within token budget
                logs = fetch_pod_logs_aggregated(pod.metadata.name, namespace)
                if logs:
                    context_sections.append(
                        f"=== Pod Logs: {pod.metadata.name} "
                        f"(phase={pod.status.phase}) ===\n{logs[:4000]}"
                    )
        except Exception as e:
            context_sections.append(f"=== Pod Logs: unavailable ({e}) ===")

        # B) Recent Kubernetes events for the workload
        try:
            events = v1.list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={name}"
            )
            event_lines = [
                f"[{e.type}] {e.reason}: {e.message} (x{e.count})"
                for e in sorted(events.items,
                                key=lambda x: x.last_timestamp or datetime.min,
                                reverse=True)[:20]
            ]
            context_sections.append(
                "=== Kubernetes Events ===\n" + "\n".join(event_lines)
            )
        except Exception as e:
            context_sections.append(f"=== K8s Events: unavailable ({e}) ===")

        # C) Workload spec (resource limits, image, replica count)
        try:
            if kind.lower() == 'deployment':
                wl = apps_v1.read_namespaced_deployment(name, namespace)
            elif kind.lower() == 'statefulset':
                wl = apps_v1.read_namespaced_stateful_set(name, namespace)
            else:
                wl = None

            if wl:
                containers = wl.spec.template.spec.containers
                spec_lines = []
                for c in containers:
                    res = c.resources
                    limits   = res.limits   if res and res.limits   else 'not set'
                    requests = res.requests if res and res.requests else 'not set'
                    spec_lines.append(
                        f"  container={c.name} image={c.image} "
                        f"limits={limits} requests={requests}"
                    )
                context_sections.append(
                    f"=== Workload Spec ({kind}: {name}) ===\n"
                    f"replicas desired={wl.spec.replicas}\n"
                    + "\n".join(spec_lines)
                )
        except Exception as e:
            context_sections.append(f"=== Workload Spec: unavailable ({e}) ===")

        full_context = "\n\n".join(context_sections)

        # ── 2. Prompt Gemini ───────────────────────────────────────────────
        prompt = f"""You are a senior Kubernetes SRE performing a Root Cause Analysis (RCA).

**Resource:** `{name}` | **Kind:** `{kind}` | **Status:** `{status}` | **Namespace:** `{namespace}`

Your response MUST follow this exact Markdown structure:

## 🚨 Root Cause
2-3 sentences identifying the definitive root cause. Reference specific log lines or events as evidence.

## 🔍 Evidence
Bullet list of the key log lines, events, or metrics that led to your conclusion.
Quote exact log lines using backticks where relevant.

## 💥 Impact
What is currently broken or degraded? Which services or users are affected?

## ✅ Remediation Steps
Numbered, actionable fix steps. Be specific (e.g., exact kubectl commands, env var names, YAML fields to change).
Order from fastest-to-apply to longer-term fixes.

## 🛡️ Prevention
1-2 recommendations to prevent this class of failure in future (e.g., add liveness probe, set resource limits, add circuit breaker).

Be precise and concise. Do not repeat yourself or pad with generic advice.

=== KUBERNETES CONTEXT ===
{full_context[:16000]}
"""
        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return jsonify({'analysis': response.text})

    except Exception as e:
        print(f"Error in ai_rca: {e}")
        return jsonify({'error': str(e)}), 500



# ──────────────────────────────────────────────
# Feature 1: Multi-Container Log Correlation
# ──────────────────────────────────────────────
@app.route('/api/ai/correlate_logs', methods=['POST'])
def correlate_logs():
    data = request.json
    pod_name = data.get('pod_name')
    namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    if not pod_name:
        return jsonify({'error': 'pod_name is required'}), 400

    try:
        v1 = client.CoreV1Api()

        # 1. Find sibling pods via label selector
        pod = v1.read_namespaced_pod(pod_name, namespace)
        labels = pod.metadata.labels or {}
        skip_keys = {'pod-template-hash', 'controller-revision-hash', 'statefulset.kubernetes.io/pod-name'}
        selector = ','.join(f"{k}={v}" for k, v in labels.items() if k not in skip_keys)

        sibling_pods = [pod_name]
        if selector:
            try:
                pods = v1.list_namespaced_pod(namespace, label_selector=selector)
                sibling_pods = [p.metadata.name for p in pods.items][:5]
            except Exception:
                pass

        # 2. Aggregate logs from all sibling pods
        aggregated_logs = ""
        for name in sibling_pods:
            aggregated_logs += fetch_pod_logs_aggregated(name, namespace) + "\n\n"

        # 3. Fetch recent events
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f"involvedObject.name={pod_name}")
            event_lines = [f"[EVENT] {e.reason}: {e.message}" for e in events.items[-10:]]
            aggregated_logs += "\n--- Events ---\n" + "\n".join(event_lines)
        except Exception:
            pass

        # 4. Call Gemini
        if not get_model():
            msg = ('Gemini not configured. Set GCP_PROJECT_ID env var to enable AI log correlation.'
                   f'\n\nPods that would be analysed: {sibling_pods}')
            return jsonify({'correlation': msg, 'summary': msg, 'gemini_powered': False, 'pods_analyzed': sibling_pods})

        prompt = f"""You are a Kubernetes Site Reliability Engineer and expert debugger.
You have aggregated logs from ALL containers and sibling pods for workload '{pod_name}' in namespace '{namespace}'.

Your task:
1. Identify the ROOT CAUSE by finding the FIRST failure signal across ALL containers (the causal chain).
2. Show a timeline table: | Time | Pod | Container | Event | to illustrate error propagation.
3. Provide 3-4 concrete actionable fix steps with kubectl commands.

Format your response in clean Markdown with sections: Causal Chain Timeline, Root Cause, Recommended Fixes, Log Statistics.
Be specific — cite exact log lines for the root cause.

=== AGGREGATED LOGS FROM {len(sibling_pods)} PODS ===
{aggregated_logs[:15000]}
"""
        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return jsonify({
            'correlation': response.text,
            'summary': response.text,      # alias for resilience
            'pods_analyzed': sibling_pods,
            'gemini_powered': True,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ──────────────────────────────────────────────
# Feature 2: Conversational Multi-turn Agent
#   - Injects full live cluster snapshot at session start
#   - Dynamically fetches logs when user mentions a resource
# ──────────────────────────────────────────────
chat_sessions: dict = {}


def _build_cluster_context(namespace: str) -> str:
    """Fetch live K8s data and return a rich text snapshot for Gemini."""
    lines = [f"=== LIVE CLUSTER SNAPSHOT: namespace={namespace} ===\n"]
    try:
        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # ── Pods ──────────────────────────────────────────────────────────
        lines.append("## Pods")
        pods = v1.list_namespaced_pod(namespace).items
        for p in pods:
            phase   = p.status.phase or "Unknown"
            ready   = sum(1 for cs in (p.status.container_statuses or []) if cs.ready)
            total   = len(p.status.container_statuses or [])
            restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
            reason  = ""
            for cs in (p.status.container_statuses or []):
                if cs.state and cs.state.waiting:
                    reason = cs.state.waiting.reason or ""
                elif cs.state and cs.state.terminated:
                    reason = cs.state.terminated.reason or ""
            node    = p.spec.node_name or "?"
            limits  = {}
            requests = {}
            for c in (p.spec.containers or []):
                if c.resources:
                    if c.resources.limits:   limits.update(c.resources.limits)
                    if c.resources.requests: requests.update(c.resources.requests)
            status_str = f"{phase}" + (f"/{reason}" if reason else "")
            lines.append(
                f"  {p.metadata.name}: status={status_str} ready={ready}/{total} "
                f"restarts={restarts} node={node} "
                f"limits={limits or 'none'} requests={requests or 'none'}"
            )

        # ── Deployments ───────────────────────────────────────────────────
        lines.append("\n## Deployments")
        deploys = apps_v1.list_namespaced_deployment(namespace).items
        for d in deploys:
            ready    = d.status.ready_replicas or 0
            desired  = d.spec.replicas or 0
            limits   = {}
            requests = {}
            for c in (d.spec.template.spec.containers or []):
                if c.resources:
                    if c.resources.limits:   limits.update(c.resources.limits)
                    if c.resources.requests: requests.update(c.resources.requests)
            lines.append(
                f"  {d.metadata.name}: ready={ready}/{desired} "
                f"image={d.spec.template.spec.containers[0].image if d.spec.template.spec.containers else '?'} "
                f"limits={limits or 'none'} requests={requests or 'none'}"
            )

        # ── StatefulSets ──────────────────────────────────────────────────
        ssets = apps_v1.list_namespaced_stateful_set(namespace).items
        if ssets:
            lines.append("\n## StatefulSets")
            for s in ssets:
                lines.append(
                    f"  {s.metadata.name}: ready={s.status.ready_replicas or 0}/{s.spec.replicas or 0}"
                )

        # ── Services ─────────────────────────────────────────────────────
        lines.append("\n## Services")
        svcs = v1.list_namespaced_service(namespace).items
        for s in svcs:
            ports = ", ".join(
                f"{p.port}/{p.protocol}" for p in (s.spec.ports or [])
            )
            lines.append(f"  {s.metadata.name}: type={s.spec.type} ports={ports}")

        # ── Recent Warning Events ─────────────────────────────────────────
        lines.append("\n## Recent Warning Events (last 10)")
        evs = v1.list_namespaced_event(namespace).items
        warnings = [e for e in evs if e.type == "Warning"]
        warnings.sort(key=lambda e: e.last_timestamp or e.event_time or
                      __import__('datetime').datetime.min.replace(tzinfo=__import__('datetime').timezone.utc),
                      reverse=True)
        for e in warnings[:10]:
            lines.append(f"  [{e.reason}] {e.involved_object.name}: {e.message}")

    except Exception as ex:
        lines.append(f"(Could not fetch full cluster data: {ex})")

    lines.append(
        "\n=== END SNAPSHOT ===\n"
        "Use this data to answer questions precisely. "
        "When the user asks about resource requests/limits, compare/list from the snapshot above. "
        "When asked about logs, use the logs provided in the conversation. "
        "Recommend kubectl commands using actual names from the snapshot when helpful."
    )
    return "\n".join(lines)


def _fetch_resource_logs(namespace: str, message: str) -> str:
    """If the user's message mentions a known resource name, fetch its logs."""
    try:
        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        msg_lower = message.lower()

        # Collect all resource names
        pod_names    = [p.metadata.name for p in v1.list_namespaced_pod(namespace).items]
        deploy_names = [d.metadata.name for d in apps_v1.list_namespaced_deployment(namespace).items]

        mentioned = [n for n in pod_names + deploy_names if n.lower() in msg_lower]
        if not mentioned:
            return ""

        log_parts = []
        for name in mentioned[:2]:  # max 2 resources per turn
            if name in pod_names:
                try:
                    logs = v1.read_namespaced_pod_log(name=name, namespace=namespace, tail_lines=60)
                    log_parts.append(f"[Logs for pod {name}]\n{logs}")
                except Exception:
                    try:
                        logs = v1.read_namespaced_pod_log(name=name, namespace=namespace,
                                                          tail_lines=60, previous=True)
                        log_parts.append(f"[Previous logs for pod {name}]\n{logs}")
                    except Exception as e:
                        log_parts.append(f"[Could not fetch logs for {name}: {e}]")
            else:
                # It's a deployment — find its pods
                pods = v1.list_namespaced_pod(namespace=namespace,
                                              label_selector=f'app={name}').items
                if not pods:
                    pods = v1.list_namespaced_pod(namespace=namespace).items
                    pods = [p for p in pods if name in p.metadata.name]
                for pod in pods[:1]:
                    try:
                        logs = v1.read_namespaced_pod_log(
                            name=pod.metadata.name, namespace=namespace, tail_lines=60)
                        log_parts.append(f"[Logs for {name} pod {pod.metadata.name}]\n{logs}")
                    except Exception as e:
                        log_parts.append(f"[Could not fetch logs for {name}: {e}]")

        return "\n\n".join(log_parts)
    except Exception:
        return ""



# ═══════════════════════════════════════════════════════════════════════════
# GEMINI FUNCTION CALLING — K8S TOOLS FOR AI CHAT AGENT
# ═══════════════════════════════════════════════════════════════════════════

from google.genai import types as _genai_types

# ── 10 K8s Tool Functions ──────────────────────────────────────────────────

def _k8s_list_pods(namespace: str, label_selector: str = '') -> str:
    """List pods with status, restarts, phase."""
    try:
        v1 = client.CoreV1Api()
        kwargs = {'label_selector': label_selector} if label_selector else {}
        pods = v1.list_namespaced_pod(namespace, **kwargs)
        if not pods.items:
            return f"No pods found in namespace '{namespace}'."
        lines = ['Pod Name | Phase | Ready | Restarts | Node']
        lines.append('---------|-------|-------|----------|-----')
        for p in pods.items:
            phase = p.status.phase or 'Unknown'
            cstats = p.status.container_statuses or []
            ready = sum(1 for c in cstats if c.ready)
            total = len(cstats) or len(p.spec.containers)
            restarts = sum(c.restart_count for c in cstats)
            node = p.spec.node_name or 'unscheduled'
            lines.append(f'{p.metadata.name} | {phase} | {ready}/{total} | {restarts} | {node}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error listing pods: {e}'


def _k8s_get_pod_logs(namespace: str, pod_name: str, container: str = '', tail_lines: int = 150) -> str:
    """Fetch pod logs."""
    try:
        v1 = client.CoreV1Api()
        kwargs = {'tail_lines': tail_lines}
        if container:
            kwargs['container'] = container
        logs = v1.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        return logs[-6000:] if len(logs) > 6000 else logs or '(no log output)'
    except Exception as e:
        return f'Error fetching logs for {pod_name}: {e}'


def _k8s_get_pod_events(namespace: str, pod_name: str) -> str:
    """Fetch Kubernetes events for a pod."""
    try:
        v1 = client.CoreV1Api()
        evs = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={pod_name}')
        if not evs.items:
            return f'No events found for pod {pod_name}.'
        lines = [f'[{e.type}] {e.reason}: {e.message}' for e in evs.items[-30:]]
        return '\n'.join(lines)
    except Exception as e:
        return f'Error fetching events for {pod_name}: {e}'


def _k8s_describe_pod(namespace: str, pod_name: str) -> str:
    """Describe pod spec and container states."""
    try:
        v1 = client.CoreV1Api()
        p = v1.read_namespaced_pod(pod_name, namespace)
        lines = [f'Pod: {pod_name}', f'Phase: {p.status.phase}',
                 f'Node: {p.spec.node_name}', f'IP: {p.status.pod_ip}']
        lines.append('Containers:')
        for cs in (p.status.container_statuses or []):
            st = cs.state
            state_str = 'Unknown'
            if st.running:
                state_str = f'Running (started {st.running.started_at})'
            elif st.waiting:
                state_str = f'Waiting: {st.waiting.reason} — {st.waiting.message or ""}'
            elif st.terminated:
                state_str = f'Terminated: exit={st.terminated.exit_code} reason={st.terminated.reason}'
            lines.append(f'  {cs.name}: ready={cs.ready} restarts={cs.restart_count} state={state_str}')
        conditions = [(c.type, c.status, c.reason or '') for c in (p.status.conditions or [])]
        lines.append(f'Conditions: {conditions}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error describing pod {pod_name}: {e}'


def _k8s_list_deployments(namespace: str) -> str:
    """List deployments with replica status and images."""
    try:
        apps_v1 = client.AppsV1Api()
        deps = apps_v1.list_namespaced_deployment(namespace)
        if not deps.items:
            return f"No deployments in namespace '{namespace}'."
        lines = ['Name | Desired | Ready | Available | Images']
        lines.append('-----|---------|-------|-----------|------')
        for d in deps.items:
            desired = d.spec.replicas or 0
            ready = d.status.ready_replicas or 0
            avail = d.status.available_replicas or 0
            images = ', '.join(c.image for c in d.spec.template.spec.containers)
            lines.append(f'{d.metadata.name} | {desired} | {ready} | {avail} | {images}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error listing deployments: {e}'


def _k8s_get_deployment_status(namespace: str, deployment_name: str) -> str:
    """Get detailed status of a single deployment including image versions and Helm chart info."""
    try:
        apps_v1 = client.AppsV1Api()
        d = apps_v1.read_namespaced_deployment(deployment_name, namespace)
        labels = d.metadata.labels or {}

        # ── Helm / app version info from labels ──────────────────────────────
        helm_chart   = labels.get('helm.sh/chart', '')
        helm_release = labels.get('app.kubernetes.io/instance', '')
        app_version  = labels.get('app.kubernetes.io/version', '')
        managed_by   = labels.get('app.kubernetes.io/managed-by', '')
        app_name     = labels.get('app.kubernetes.io/name', labels.get('app', ''))

        lines = [f'Deployment: {deployment_name}']

        # Version / Helm info block
        if helm_chart or app_version or helm_release:
            lines.append('--- Version & Helm Info ---')
            if helm_chart:
                # helm.sh/chart is typically "chartname-1.2.3"
                lines.append(f'Helm chart:   {helm_chart}')
            if helm_release:
                lines.append(f'Helm release: {helm_release}')
            if app_version:
                lines.append(f'App version:  {app_version}')
            if managed_by:
                lines.append(f'Managed by:   {managed_by}')
            if app_name:
                lines.append(f'App name:     {app_name}')

        lines += [
            '--- Replica Status ---',
            f'Desired={d.spec.replicas}  Ready={d.status.ready_replicas or 0}  '
            f'Available={d.status.available_replicas or 0}  Updated={d.status.updated_replicas or 0}',
            f'Strategy: {d.spec.strategy.type}',
            '--- Containers & Images ---',
        ]

        for c in d.spec.template.spec.containers:
            req = c.resources.requests or {} if c.resources else {}
            lim = c.resources.limits or {} if c.resources else {}
            # Extract the image tag as the version
            img_parts = c.image.rsplit(':', 1)
            image_tag = img_parts[1] if len(img_parts) == 2 else 'latest'
            lines.append(
                f'  {c.name}:'
                f'\n    image:   {c.image}'
                f'\n    version: {image_tag}'
                f'\n    cpu:     req={req.get("cpu","?")} limit={lim.get("cpu","?")}'
                f'\n    memory:  req={req.get("memory","?")} limit={lim.get("memory","?")}'
            )

        for cond in (d.status.conditions or []):
            lines.append(f'Condition {cond.type}: {cond.status} — {cond.message or ""}')

        return '\n'.join(lines)
    except Exception as e:
        return f'Error getting deployment {deployment_name}: {e}'


def _k8s_list_services(namespace: str) -> str:
    """List services with type, ClusterIP, and ports."""
    try:
        v1 = client.CoreV1Api()
        svcs = v1.list_namespaced_service(namespace)
        if not svcs.items:
            return f"No services in namespace '{namespace}'."
        lines = ['Name | Type | ClusterIP | Ports']
        lines.append('-----|------|-----------|------')
        for s in svcs.items:
            ports = ', '.join(f'{p.port}/{p.protocol}→{p.target_port}' for p in (s.spec.ports or []))
            lines.append(f'{s.metadata.name} | {s.spec.type} | {s.spec.cluster_ip} | {ports}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error listing services: {e}'


def _k8s_get_configmap(namespace: str, configmap_name: str) -> str:
    """Fetch ConfigMap keys and values."""
    try:
        v1 = client.CoreV1Api()
        cm = v1.read_namespaced_config_map(configmap_name, namespace)
        data = cm.data or {}
        if not data:
            return f'ConfigMap {configmap_name} is empty.'
        lines = [f'ConfigMap: {configmap_name}']
        for k, v in data.items():
            val = str(v)[:200] + ('…' if len(str(v)) > 200 else '')
            lines.append(f'  {k}: {val}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error fetching ConfigMap {configmap_name}: {e}'


def _k8s_get_namespace_events(namespace: str, event_type: str = '') -> str:
    """Fetch recent K8s events across the whole namespace."""
    try:
        v1 = client.CoreV1Api()
        kwargs = {}
        if event_type:
            kwargs['field_selector'] = f'type={event_type}'
        evs = v1.list_namespaced_event(namespace, **kwargs)
        if not evs.items:
            return f'No events in namespace {namespace}.'
        lines = []
        for e in sorted(evs.items, key=lambda x: x.last_timestamp or x.event_time or '',
                        reverse=True)[:40]:
            lines.append(f'[{e.type}] {e.involved_object.name} ({e.involved_object.kind}): '
                         f'{e.reason} — {e.message}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error fetching events: {e}'


def _k8s_list_statefulsets(namespace: str) -> str:
    """List StatefulSets with replica status."""
    try:
        apps_v1 = client.AppsV1Api()
        sts = apps_v1.list_namespaced_stateful_set(namespace)
        if not sts.items:
            return f"No StatefulSets in namespace '{namespace}'."
        lines = ['Name | Desired | Ready | Current']
        lines.append('-----|---------|-------|--------')
        for s in sts.items:
            lines.append(f'{s.metadata.name} | {s.spec.replicas or 0} | '
                         f'{s.status.ready_replicas or 0} | {s.status.current_replicas or 0}')
        return '\n'.join(lines)
    except Exception as e:
        return f'Error listing StatefulSets: {e}'


# ── Gemini Tool Declarations ───────────────────────────────────────────────

_STR = _genai_types.Schema(type='STRING')
_INT = _genai_types.Schema(type='INTEGER')

def _schema(props: dict, required: list = None) -> _genai_types.Schema:
    return _genai_types.Schema(
        type='OBJECT',
        properties={k: _genai_types.Schema(type=v[0], description=v[1]) for k, v in props.items()},
        required=required or list(props.keys())[:1]
    )

K8S_TOOLS = _genai_types.Tool(function_declarations=[
    _genai_types.FunctionDeclaration(
        name='k8s_list_pods',
        description='List all pods in the namespace with phase, readiness, restart counts, and node assignment.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'label_selector': ('STRING', 'Optional label selector e.g. app=my-service')},
                            required=['namespace'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_get_pod_logs',
        description='Fetch recent log output from a pod. Use to diagnose crashes, errors, or startup failures.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'pod_name': ('STRING', 'Full pod name'),
                             'container': ('STRING', 'Container name — leave empty to use default container'),
                             'tail_lines': ('INTEGER', 'Number of recent log lines to fetch, default 150')},
                            required=['namespace', 'pod_name'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_get_pod_events',
        description='Fetch Kubernetes events for a specific pod — OOMKills, scheduling failures, restarts.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'pod_name': ('STRING', 'Pod name')},
                            required=['namespace', 'pod_name'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_describe_pod',
        description='Get detailed pod spec — container states, restart count, conditions, node, IP.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'pod_name': ('STRING', 'Pod name')},
                            required=['namespace', 'pod_name'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_list_deployments',
        description='List all deployments with desired/ready/available replica counts and container images.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace')},
                            required=['namespace'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_get_deployment_status',
        description='Get detailed status of a single deployment including resource requests/limits and conditions.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'deployment_name': ('STRING', 'Deployment name')},
                            required=['namespace', 'deployment_name'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_list_services',
        description='List all services in the namespace with their type, ClusterIP, and port mappings.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace')},
                            required=['namespace'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_get_configmap',
        description='Fetch the key-value contents of a ConfigMap.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'configmap_name': ('STRING', 'ConfigMap name')},
                            required=['namespace', 'configmap_name'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_get_namespace_events',
        description='Fetch recent Kubernetes events across the entire namespace. Use for cluster-wide issues.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace'),
                             'event_type': ('STRING', 'Optional filter: Warning or Normal')},
                            required=['namespace'])
    ),
    _genai_types.FunctionDeclaration(
        name='k8s_list_statefulsets',
        description='List StatefulSets with desired/ready/current replica counts.',
        parameters=_schema({'namespace': ('STRING', 'Kubernetes namespace')},
                            required=['namespace'])
    ),
])

# Dispatcher: maps function name → Python function call
_K8S_TOOL_MAP = {
    'k8s_list_pods':             lambda a: _k8s_list_pods(**a),
    'k8s_get_pod_logs':          lambda a: _k8s_get_pod_logs(**a),
    'k8s_get_pod_events':        lambda a: _k8s_get_pod_events(**a),
    'k8s_describe_pod':          lambda a: _k8s_describe_pod(**a),
    'k8s_list_deployments':      lambda a: _k8s_list_deployments(**a),
    'k8s_get_deployment_status': lambda a: _k8s_get_deployment_status(**a),
    'k8s_list_services':         lambda a: _k8s_list_services(**a),
    'k8s_get_configmap':         lambda a: _k8s_get_configmap(**a),
    'k8s_get_namespace_events':  lambda a: _k8s_get_namespace_events(**a),
    'k8s_list_statefulsets':     lambda a: _k8s_list_statefulsets(**a),
}


@app.route('/api/ai/converse', methods=['POST'])
def converse():
    """AI Chat with Gemini Function Calling — executes live K8s API calls to answer questions."""
    session_id = request.headers.get('X-Session-Id', 'default')
    data       = request.json or {}
    message    = data.get('message', '').strip()
    namespace  = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    if not message:
        return jsonify({'error': 'No message provided'}), 400

    if not get_model():
        return jsonify({'reply': f'⚠️ Gemini not configured ({_client_error}). '
                                  'Check /api/ai/status for details.'})

    try:
        mdl = get_model()

        # System instruction for the agent
        system_instruction = (
            f"You are an expert Kubernetes SRE agent embedded in the GDC Dashboard "
            f"for namespace '{namespace}'. You have access to live Kubernetes API tools. "
            f"When the user asks a question:\n"
            f"1. Use the available tools to fetch REAL live data from the cluster\n"
            f"2. Reason over the actual data returned\n"
            f"3. Give a direct, specific, data-backed answer — never say 'run this command yourself'\n"
            f"4. Use Markdown formatting with tables where helpful\n"
            f"5. Be concise and actionable\n"
            f"Current namespace: {namespace}"
        )

        # Build conversation history for this session
        if session_id not in chat_sessions:
            chat_sessions[session_id] = {
                'history': [],
                'namespace': namespace
            }

        session = chat_sessions[session_id]
        history = session['history']

        # Add the new user message to history
        history.append(_genai_types.Content(
            role='user',
            parts=[_genai_types.Part(text=message)]
        ))

        # ── Agentic tool-calling loop (max 5 iterations) ──────────────────
        MAX_ITERATIONS = 5
        final_reply = None

        for iteration in range(MAX_ITERATIONS):
            response = mdl.models.generate_content(
                model=GEMINI_MODEL,
                contents=history,
                config=_genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[K8S_TOOLS],
                    tool_config=_genai_types.ToolConfig(
                        function_calling_config=_genai_types.FunctionCallingConfig(
                            mode='AUTO'
                        )
                    ),
                    temperature=0.2,
                )
            )

            candidate = response.candidates[0] if response.candidates else None
            if not candidate:
                final_reply = '⚠️ No response from Gemini.'
                break

            # Collect all function calls from this response
            function_calls = []
            text_parts = []
            for part in (candidate.content.parts or []):
                if part.function_call:
                    function_calls.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

            if not function_calls:
                # No tool calls — this is the final answer
                final_reply = '\n'.join(text_parts) or '(no response)'
                # Append assistant turn to history
                history.append(candidate.content)
                break

            # Append the assistant's tool-call turn to history
            history.append(candidate.content)

            # Execute each tool call and collect results
            tool_response_parts = []
            for fc in function_calls:
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}
                print(f'[agent] Calling tool: {fn_name}({fn_args})')

                if fn_name in _K8S_TOOL_MAP:
                    try:
                        result = _K8S_TOOL_MAP[fn_name](fn_args)
                    except Exception as tool_err:
                        result = f'Tool error: {tool_err}'
                else:
                    result = f'Unknown tool: {fn_name}'

                tool_response_parts.append(
                    _genai_types.Part(
                        function_response=_genai_types.FunctionResponse(
                            name=fn_name,
                            response={'result': result}
                        )
                    )
                )

            # Append tool results as a user turn
            history.append(_genai_types.Content(role='user', parts=tool_response_parts))

        else:
            # Exceeded max iterations — return whatever the last text was
            final_reply = final_reply or '⚠️ Agent reached maximum reasoning steps without a final answer.'

        # Trim history to last 30 turns to avoid token overflow
        if len(history) > 30:
            session['history'] = history[-30:]
        else:
            session['history'] = history

        return jsonify({'reply': final_reply, 'session_id': session_id})

    except Exception as e:
        print(f'[converse] Error: {e}')
        return jsonify({'error': f'Gemini error: {str(e)}'}), 500

@app.route('/api/ai/converse/reset', methods=['POST'])
def converse_reset():
    session_id = request.headers.get('X-Session-Id', 'default')
    chat_sessions.pop(session_id, None)
    return jsonify({'status': 'cleared', 'session_id': session_id})


# ──────────────────────────────────────────────
# Feature 3: Natural Language YAML Generation
# ──────────────────────────────────────────────
@app.route('/api/ai/generate_yaml', methods=['POST'])
def generate_yaml():
    data = request.json
    description = data.get('description', '').strip()
    namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

    if not description:
        return jsonify({'error': 'description is required'}), 400

    if not get_model():
        return jsonify({'yaml': '# Gemini not configured. Set GCP_PROJECT_ID to enable YAML generation.'})

    try:
        prompt = f"""You are a Kubernetes YAML expert. Generate valid, production-ready Kubernetes YAML based on the following description.

Description: {description}
Namespace: {namespace}

Requirements:
- Output ONLY the YAML, no prose or explanation before or after
- Do NOT wrap in markdown code fences
- Include resource requests and limits
- Include readiness and liveness probes where applicable
- Use best practices (non-root user, read-only filesystem where sensible)
- Label with `app: <name>` and `managed-by: gdc-dashboard`
- If multiple resources are needed (e.g. Deployment + Service), separate with ---

Output the raw YAML only:"""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        # Strip any markdown code fences the model may have added
        yaml_text = response.text.strip()
        if yaml_text.startswith('```'):
            lines = yaml_text.split('\n')
            yaml_text = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

        return jsonify({'yaml': yaml_text})
    except Exception as e:
        return jsonify({'error': f'Gemini error: {str(e)}'}), 500


# ═══════════════════════════════════════════════════════════
# NEW Gemini-Powered Workloads Routes
# ═══════════════════════════════════════════════════════════

@app.route('/api/pods/<name>/all_logs')
def get_all_container_logs(name):
    """Fetch logs from ALL containers in a pod (init + app + sidecar),
    returning them as a structured dict of { container_name: log_text }."""
    try:
        v1 = client.CoreV1Api()
        namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        pod = v1.read_namespaced_pod(name, namespace)
        spec = pod.spec
        result = {}

        # Init containers
        for c in (spec.init_containers or []):
            try:
                log = v1.read_namespaced_pod_log(name, namespace,
                                                  container=c.name, tail_lines=200)
                result[f'[init] {c.name}'] = log or '(no output)'
            except Exception as e:
                result[f'[init] {c.name}'] = f'Error: {e}'

        # App containers
        for c in (spec.containers or []):
            try:
                log = v1.read_namespaced_pod_log(name, namespace,
                                                  container=c.name, tail_lines=200)
                result[c.name] = log or '(no output)'
            except Exception as e:
                result[c.name] = f'Error: {e}'

        # Ephemeral containers
        for c in (spec.ephemeral_containers or []):
            try:
                log = v1.read_namespaced_pod_log(name, namespace,
                                                  container=c.name, tail_lines=200)
                result[f'[ephemeral] {c.name}'] = log or '(no output)'
            except Exception as e:
                result[f'[ephemeral] {c.name}'] = f'Error: {e}'

        return jsonify({'containers': result, 'pod': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/analyze_workload', methods=['POST'])
def analyze_workload():
    """Gemini-powered workload health analysis for Deployments, StatefulSets, DaemonSets.

    Collects: pod logs (last 3 pods), K8s events, resource spec, replica counts.
    Returns structured JSON with health_score, summary, risks, and recommendations.
    """
    try:
        data = request.json or {}
        name      = data.get('name', '')
        kind      = data.get('kind', 'Deployment')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        sections = []

        # ── Workload spec ──
        try:
            if kind == 'Deployment':
                wl = apps_v1.read_namespaced_deployment(name, namespace)
                desired  = wl.spec.replicas or 0
                ready    = wl.status.ready_replicas or 0
                updated  = wl.status.updated_replicas or 0
                available = wl.status.available_replicas or 0
                containers = wl.spec.template.spec.containers
            elif kind == 'StatefulSet':
                wl = apps_v1.read_namespaced_stateful_set(name, namespace)
                desired  = wl.spec.replicas or 0
                ready    = wl.status.ready_replicas or 0
                updated  = wl.status.updated_replicas or 0
                available = ready
                containers = wl.spec.template.spec.containers
            elif kind == 'DaemonSet':
                wl = apps_v1.read_namespaced_daemon_set(name, namespace)
                desired  = wl.status.desired_number_scheduled or 0
                ready    = wl.status.number_ready or 0
                updated  = wl.status.updated_number_scheduled or 0
                available = wl.status.number_available or 0
                containers = wl.spec.template.spec.containers
            else:
                return jsonify({'error': f'Unsupported kind: {kind}'}), 400

            spec_lines = [f'kind={kind} name={name} replicas(desired={desired} ready={ready} updated={updated} available={available})']
            for c in containers:
                res = c.resources
                lim = res.limits   if res and res.limits   else 'not-set'
                req = res.requests if res and res.requests else 'not-set'
                spec_lines.append(
                    f'  container={c.name} image={c.image} '
                    f'limits={lim} requests={req} '
                    f'liveness={"set" if c.liveness_probe else "MISSING"} '
                    f'readiness={"set" if c.readiness_probe else "MISSING"}'
                )
            sections.append('=== Workload Spec ===\n' + '\n'.join(spec_lines))
        except Exception as e:
            sections.append(f'=== Workload Spec: unavailable ({e}) ===')
            containers = []
            desired = ready = 0

        # ── Pod logs (up to 3 pods) ──
        try:
            label_sel = wl.spec.selector.match_labels if hasattr(wl.spec, 'selector') and wl.spec.selector else {}
            sel_str = ','.join(f'{k}={v}' for k, v in label_sel.items())
            pods = v1.list_namespaced_pod(namespace, label_selector=sel_str).items[:3] if sel_str else []
            for pod in pods:
                logs = fetch_pod_logs_aggregated(pod.metadata.name, namespace)
                sections.append(f'=== Pod Logs: {pod.metadata.name} (phase={pod.status.phase}) ===\n{logs[:3000]}')
        except Exception as e:
            sections.append(f'=== Pod Logs: unavailable ({e}) ===')

        # ── Events ──
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={name}')
            evlines = [f'[{e.type}] {e.reason}: {e.message} (x{e.count or 1})'
                       for e in sorted(events.items, key=lambda x: x.last_timestamp or datetime.min, reverse=True)[:15]]
            sections.append('=== K8s Events ===\n' + '\n'.join(evlines))
        except Exception as e:
            sections.append(f'=== Events: unavailable ({e}) ===')

        context = '\n\n'.join(sections)

        # ── No-Gemini fallback ──
        if not get_model():
            health = 'Healthy' if desired > 0 and ready == desired else 'Degraded'
            score  = 100 if health == 'Healthy' else max(0, int(ready / max(desired, 1) * 100))
            return jsonify({
                'health_score': score,
                'health_status': health,
                'summary': f'{kind} {name}: {ready}/{desired} replicas ready. Gemini not configured — basic health check only.',
                'risks': [] if health == 'Healthy' else [{'severity': 'High', 'description': f'Only {ready}/{desired} replicas are ready.', 'action': 'Check pod logs and events for crash details.'}],
                'kubectl_hints': [f'kubectl get pods -l app={name} -n {namespace}', f'kubectl describe {kind.lower()} {name} -n {namespace}'],
                'gemini_powered': False
            })

        prompt = f"""You are a Kubernetes SRE analysing workload health. Return ONLY a valid JSON object.

=== CLUSTER CONTEXT ===
{context[:14000]}

Return this exact JSON schema (no markdown, no extra text):
{{
  "health_score": <0-100 integer, 100=fully healthy>,
  "health_status": "Healthy" | "Degraded" | "Critical" | "Unknown",
  "summary": "<2-3 sentence executive summary of current health>",
  "risks": [
    {{
      "severity": "Critical" | "High" | "Medium" | "Low",
      "description": "<what is wrong>",
      "action": "<specific fix — kubectl command or YAML change>"
    }}
  ],
  "kubectl_hints": ["<exact kubectl command>", ...],
  "positive_signals": ["<what is working well>", ...]
}}

Rules:
- health_score: start at 100, deduct for each risk (Critical=-40, High=-25, Medium=-10, Low=-5)
- kubectl_hints: always include at least 2 useful debug commands for this specific workload
- Be specific — reference actual container names, image versions, exact error messages from logs
- Return ONLY the JSON. No markdown fences."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = raw[:-3]
        result = json.loads(raw.strip())
        result['gemini_powered'] = True
        return jsonify(result)

    except json.JSONDecodeError as e:
        return jsonify({'error': 'AI returned malformed JSON', 'health_score': 50,
                        'health_status': 'Unknown', 'summary': 'Analysis unavailable.',
                        'risks': [], 'kubectl_hints': [], 'gemini_powered': True}), 200
    except Exception as e:
        print(f'[analyze_workload] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/diagnose', methods=['POST'])
def diagnose_workload():
    """Unified diagnose endpoint — merges Analyze + Health Check into one response."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        kind      = data.get('kind', 'Deployment')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        sections = []

        # ── Workload spec ──
        desired = ready = 0
        try:
            if kind == 'Deployment':
                wl = apps_v1.read_namespaced_deployment(name, namespace)
                desired  = wl.spec.replicas or 0
                ready    = wl.status.ready_replicas or 0
                containers = wl.spec.template.spec.containers
            elif kind == 'StatefulSet':
                wl = apps_v1.read_namespaced_stateful_set(name, namespace)
                desired  = wl.spec.replicas or 0
                ready    = wl.status.ready_replicas or 0
                containers = wl.spec.template.spec.containers
            elif kind == 'DaemonSet':
                wl = apps_v1.read_namespaced_daemon_set(name, namespace)
                desired  = wl.status.desired_number_scheduled or 0
                ready    = wl.status.number_ready or 0
                containers = wl.spec.template.spec.containers
            else:
                return jsonify({'error': f'Unsupported kind: {kind}'}), 400

            spec_lines = [f'kind={kind} name={name} replicas(desired={desired} ready={ready})']
            for c in containers:
                res = c.resources
                lim = res.limits if res and res.limits else 'not-set'
                req = res.requests if res and res.requests else 'not-set'
                spec_lines.append(f'  container={c.name} image={c.image} limits={lim} requests={req}')
            sections.append('=== Workload Spec ===\n' + '\n'.join(spec_lines))
        except Exception as e:
            sections.append(f'=== Workload Spec: unavailable ({e}) ===')
            containers = []

        # ── Pod logs ──
        try:
            label_sel = wl.spec.selector.match_labels if hasattr(wl.spec, 'selector') and wl.spec.selector else {}
            sel_str = ','.join(f'{k}={v}' for k, v in label_sel.items())
            pods = v1.list_namespaced_pod(namespace, label_selector=sel_str).items[:3] if sel_str else []
            for pod in pods:
                logs = fetch_pod_logs_aggregated(pod.metadata.name, namespace)
                sections.append(f'=== Pod Logs: {pod.metadata.name} ===\n{logs[:3000]}')
        except Exception:
            pass

        # ── Events ──
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={name}')
            evlines = [f'[{e.type}] {e.reason}: {e.message}' for e in events.items[-15:]]
            sections.append('=== Events ===\n' + '\n'.join(evlines))
        except Exception:
            pass

        context = '\n\n'.join(sections)

        # ── Verdict ──
        ratio = ready / max(desired, 1) if desired > 0 else 1.0
        if ratio >= 1.0:
            verdict, verdict_color, verdict_icon = 'Healthy', '#0f9d58', '✅'
        elif ratio >= 0.5:
            verdict, verdict_color, verdict_icon = 'Degraded', '#e6a000', '⚠️'
        else:
            verdict, verdict_color, verdict_icon = 'Critical', '#dc3545', '🔴'

        # Replica advice
        if desired == 1:
            replica_advice = '⚠️ **Single replica** — no HA. Add at least 1 more replica for availability.'
        elif desired >= 5:
            replica_advice = f'Running {desired} replicas — consider HPA for dynamic scaling.'
        else:
            replica_advice = f'{desired} replicas — appropriate for this workload.'

        # ── No-Gemini fallback ──
        if not get_model():
            score = 100 if verdict == 'Healthy' else max(0, int(ratio * 100))
            return jsonify({
                'health_score': score, 'verdict': verdict, 'verdict_color': verdict_color, 'verdict_icon': verdict_icon,
                'summary': f'{kind} {name}: {ready}/{desired} replicas ready. Gemini not configured — basic check only.',
                'risks': [] if verdict == 'Healthy' else [{'severity': 'High', 'description': f'Only {ready}/{desired} replicas ready.', 'action': f'kubectl get pods -l app={name} -n {namespace}'}],
                'positive_signals': ['All replicas healthy', 'Resource limits set', 'Probes configured'] if verdict == 'Healthy' else [],
                'replica_advice': replica_advice,
                'rollout_advice': 'Use `maxUnavailable: 1`, `maxSurge: 1` for zero-downtime rolling updates.',
                'resource_advice': 'Set CPU/memory requests and limits. Recommended: `requests.cpu=100m`, `limits.cpu=500m`.',
                'kubectl_hints': [
                    f'kubectl rollout status {kind.lower()}/{name} -n {namespace}',
                    f'kubectl describe {kind.lower()} {name} -n {namespace}',
                    f'kubectl logs -l app={name.split("-")[0]} --tail=50 -n {namespace}',
                    f'kubectl top pods -l app={name.split("-")[0]} -n {namespace}',
                ],
                'gemini_powered': False
            })

        prompt = f"""You are a Kubernetes SRE performing a unified diagnosis of a workload. Return ONLY valid JSON (no markdown, no fences).

=== CLUSTER CONTEXT ===
{context[:14000]}

Return this exact JSON schema:
{{
  "health_score": <0-100>,
  "verdict": "Healthy" | "Degraded" | "Critical",
  "verdict_color": "<hex color>",
  "verdict_icon": "<emoji>",
  "summary": "<2-3 sentence summary including ready/total pod counts>",
  "risks": [
    {{"severity": "Critical" | "High" | "Medium" | "Low", "description": "<issue>", "action": "<fix command>"}}
  ],
  "positive_signals": ["<what is working well>"],
  "replica_advice": "<replica count recommendation>",
  "rollout_advice": "<rollout strategy advice>",
  "resource_advice": "<CPU/memory recommendation>",
  "kubectl_hints": ["<kubectl command>", ...]
}}

Rules:
- health_score: start at 100, deduct per risk (Critical=-40, High=-25, Medium=-10, Low=-5)
- Be specific — reference container names, image versions, exact errors from logs
- Return ONLY JSON."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = raw[:-3]
        result = json.loads(raw.strip())
        result['gemini_powered'] = True
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({'health_score': 50, 'verdict': 'Unknown', 'verdict_color': '#333', 'verdict_icon': '🔹',
                        'summary': 'AI returned malformed JSON.', 'risks': [], 'positive_signals': [],
                        'kubectl_hints': [], 'gemini_powered': True}), 200
    except Exception as e:
        print(f'[diagnose] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/deployments/<name>/pods')
def get_deployment_pods(name):
    """Return pods and their containers for a given deployment."""
    try:
        namespace = request.args.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # Get the deployment's label selector
        deploy = apps_v1.read_namespaced_deployment(name, namespace)
        match_labels = deploy.spec.selector.match_labels or {}
        selector = ','.join(f'{k}={v}' for k, v in match_labels.items())

        # Find pods matching the selector
        pods = v1.list_namespaced_pod(namespace, label_selector=selector).items
        result = []
        for pod in pods[:5]:  # limit to 5 pods
            containers = [{'name': c.name, 'image': c.image} for c in pod.spec.containers]
            result.append({'name': pod.metadata.name, 'containers': containers})

        return jsonify({'pods': result})
    except Exception as e:
        return jsonify({'error': str(e), 'pods': []}), 500


@app.route('/api/ai/diagnose_pod', methods=['POST'])
def diagnose_pod():
    """Full AI diagnosis of a pod — fetches all container logs, events, and spec,
    then asks Gemini for a detailed structured diagnosis."""
    try:
        data      = request.json or {}
        pod_name  = data.get('pod_name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not pod_name:
            return jsonify({'error': 'pod_name is required'}), 400

        v1 = client.CoreV1Api()
        sections = []

        # ── Pod spec & status ──
        try:
            pod = v1.read_namespaced_pod(pod_name, namespace)
            phase = pod.status.phase
            conditions = [(c.type, c.status, c.reason or '') for c in (pod.status.conditions or [])]
            cstatus = []
            for cs in (pod.status.container_statuses or []):
                state_str = ''
                if cs.state.running:
                    state_str = f'Running (started {cs.state.running.started_at})'
                elif cs.state.waiting:
                    state_str = f'Waiting: {cs.state.waiting.reason} — {cs.state.waiting.message or ""}'
                elif cs.state.terminated:
                    state_str = f'Terminated: exit={cs.state.terminated.exit_code} reason={cs.state.terminated.reason}'
                cstatus.append(f'  {cs.name}: ready={cs.ready} restarts={cs.restart_count} state={state_str}')
            sections.append(
                f'=== Pod Status ===\nphase={phase}\n'
                f'conditions={conditions}\ncontainerStatuses:\n' + '\n'.join(cstatus)
            )
        except Exception as e:
            sections.append(f'=== Pod Status: unavailable ({e}) ===')

        # ── All container logs ──
        logs = fetch_pod_logs_aggregated(pod_name, namespace)
        sections.append(f'=== All Container Logs ===\n{logs[:10000]}')

        # ── Events ──
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={pod_name}')
            evlines = [f'[{e.type}] {e.reason}: {e.message}' for e in events.items[-20:]]
            sections.append('=== K8s Events ===\n' + '\n'.join(evlines))
        except Exception as e:
            sections.append(f'=== Events: unavailable ({e}) ===')

        context = '\n\n'.join(sections)

        if not get_model():
            return jsonify({
                'health_status': 'Unknown',
                'diagnosis': f'## ⚠️ Gemini Not Configured\n\nSet `GCP_PROJECT_ID` to enable AI diagnosis.\n\n**Pod:** `{pod_name}`',
                'gemini_powered': False
            })

        prompt = f"""You are a Kubernetes SRE diagnosing a pod. Return ONLY valid JSON (no markdown, no fences).

Pod: {pod_name}  Namespace: {namespace}

=== CONTEXT ===
{context[:14000]}

Return this exact JSON:
{{
  "health_status": "Healthy" | "Degraded" | "CrashLooping" | "Pending" | "Failed" | "Unknown",
  "severity": "ok" | "warning" | "critical",
  "crash_reason": "<1 sentence: the immediate crash/error reason, or null if healthy>",
  "root_cause": "<1-2 sentences identifying the definitive problem, or 'No issues detected'>",
  "evidence": ["<exact log line or event>", ...],
  "container_health": {{
    "<container_name>": {{
      "status": "ok" | "warning" | "error",
      "summary": "<1 sentence>"
    }}
  }},
  "remediation_steps": [
    {{"step": 1, "action": "<specific fix>", "command": "<kubectl command if applicable>"}}
  ],
  "kubectl_hints": [
    "kubectl logs {pod_name} --previous --tail=50 -n {namespace}",
    "kubectl describe pod {pod_name} -n {namespace}",
    "<any other relevant kubectl command based on the diagnosis>"
  ],
  "prevention": "<1 sentence on how to prevent this class of issue>"
}}

Return ONLY the JSON."""


        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = raw[:-3]
        result = json.loads(raw.strip())
        result['gemini_powered'] = True
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({'health_status': 'Unknown', 'severity': 'warning',
                        'root_cause': 'Could not parse AI response.',
                        'evidence': [], 'container_health': {},
                        'remediation_steps': [], 'prevention': '',
                        'gemini_powered': True}), 200
    except Exception as e:
        print(f'[diagnose_pod] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/job_insights', methods=['POST'])
def job_insights():
    """Gemini-powered Job analysis — failure reasons, retry strategy, duration trend."""
    try:
        data      = request.json or {}
        job_name  = data.get('job_name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not job_name:
            return jsonify({'error': 'job_name is required'}), 400

        batch_v1 = client.BatchV1Api()
        v1       = client.CoreV1Api()
        sections = []

        # ── Job spec & status ──
        try:
            job = batch_v1.read_namespaced_job(job_name, namespace)
            active    = job.status.active    or 0
            succeeded = job.status.succeeded or 0
            failed    = job.status.failed    or 0
            completions  = job.spec.completions  or 1
            backoff_lim  = job.spec.backoff_limit or 6
            start_time   = job.status.start_time
            end_time     = job.status.completion_time
            duration     = str(end_time - start_time) if (start_time and end_time) else 'still running'
            sections.append(
                f'=== Job Status ===\n'
                f'job={job_name} active={active} succeeded={succeeded} failed={failed} '
                f'completions={completions} backoffLimit={backoff_lim} duration={duration}\n'
                f'image(s): {[c.image for c in job.spec.template.spec.containers]}'
            )
        except Exception as e:
            sections.append(f'=== Job Status: unavailable ({e}) ===')

        # ── Pod logs for this job ──
        try:
            pods = v1.list_namespaced_pod(namespace, label_selector=f'job-name={job_name}').items
            for pod in pods[:3]:
                logs = fetch_pod_logs_aggregated(pod.metadata.name, namespace)
                sections.append(f'=== Job Pod Logs: {pod.metadata.name} ===\n{logs[:4000]}')
        except Exception as e:
            sections.append(f'=== Job Pod Logs: unavailable ({e}) ===')

        # ── Events ──
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={job_name}')
            evlines = [f'[{e.type}] {e.reason}: {e.message}' for e in events.items[-10:]]
            sections.append('=== Events ===\n' + '\n'.join(evlines))
        except Exception as e:
            sections.append(f'=== Events: unavailable ({e}) ===')

        context = '\n\n'.join(sections)

        if not get_model():
            status = 'Succeeded' if succeeded >= completions else ('Failed' if failed > 0 else 'Running')
            return jsonify({
                'status': status,
                'summary': f'Job {job_name}: {succeeded}/{completions} succeeded, {failed} failed. Gemini not configured.',
                'failure_reason': 'N/A (Gemini not configured)',
                'retry_strategy': 'Review backoffLimit and check pod logs manually.',
                'kubectl_hints': [f'kubectl logs -l job-name={job_name} -n {namespace}'],
                'gemini_powered': False
            })

        prompt = f"""You are a Kubernetes SRE analysing a batch Job. Return ONLY valid JSON (no markdown, no fences).

=== JOB CONTEXT ===
{context[:14000]}

Return this exact JSON:
{{
  "status": "Succeeded" | "Failed" | "Running" | "Partial" | "Stalled",
  "summary": "<2 sentence summary of what this job does and its current outcome>",
  "failure_reason": "<specific reason the job failed, or 'No failure detected'>",
  "error_evidence": ["<exact log line or event that caused failure>"],
  "retry_strategy": "<specific recommendation: retry immediately / fix X before retry / increase backoffLimit>",
  "performance_insight": "<observation about job runtime, parallelism, or efficiency>",
  "kubectl_hints": ["<exact kubectl command>", ...],
  "next_steps": ["<actionable item>", ...]
}}

Return ONLY the JSON."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = raw[:-3]
        result = json.loads(raw.strip())
        result['gemini_powered'] = True
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({'status': 'Unknown', 'summary': 'AI parse error.',
                        'failure_reason': 'Could not parse response.',
                        'retry_strategy': 'Review logs manually.',
                        'kubectl_hints': [], 'gemini_powered': True}), 200
    except Exception as e:
        print(f'[job_insights] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/explain_resource', methods=['POST'])
def explain_resource():
    """Gemini-powered explanation of a ConfigMap or Secret — what it does, key roles,
    security concerns, and recommendations."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        kind      = data.get('kind', 'ConfigMap')  # 'ConfigMap' or 'Secret'
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1 = client.CoreV1Api()

        if kind == 'ConfigMap':
            try:
                cm = v1.read_namespaced_config_map(name, namespace)
                raw_data = cm.data or {}
                keys_summary = [f'  {k}: {str(v)[:120]}{"…" if len(str(v)) > 120 else ""}' for k, v in raw_data.items()]
                resource_text = f'ConfigMap "{name}" (namespace={namespace})\nKeys:\n' + '\n'.join(keys_summary)
            except Exception as e:
                return jsonify({'error': f'Could not fetch ConfigMap: {e}'}), 500
        elif kind == 'Secret':
            try:
                import base64
                secret = v1.read_namespaced_secret(name, namespace)
                keys = list((secret.data or {}).keys())
                secret_types = secret.type
                resource_text = (
                    f'Secret "{name}" (namespace={namespace}) type={secret_types}\n'
                    f'Keys (values redacted for security): {keys}'
                )
            except Exception as e:
                return jsonify({'error': f'Could not fetch Secret: {e}'}), 500
        else:
            return jsonify({'error': f'Unsupported kind: {kind}'}), 400

        if not get_model():
            return jsonify({
                'purpose': f'{kind} {name} — Gemini not configured.',
                'key_breakdown': {},
                'security_concerns': [],
                'recommendations': ['Set GCP_PROJECT_ID to enable AI explanations.'],
                'risk_level': 'unknown',
                'gemini_powered': False
            })

        if kind == 'ConfigMap':
            prompt = f"""You are a Kubernetes expert reviewing a ConfigMap. Return ONLY valid JSON (no markdown, no fences).

{resource_text}

Return this exact JSON:
{{
  "purpose": "<2-3 sentence explanation of what this ConfigMap configures and which services likely use it>",
  "key_breakdown": {{
    "<key_name>": "<1 sentence description of this key\'s role>"
  }},
  "security_concerns": [
    {{"severity": "Critical|High|Medium|Low", "concern": "<specific issue>", "recommendation": "<fix>"}}
  ],
  "recommendations": ["<actionable improvement>"],
  "risk_level": "safe" | "review" | "concern",
  "managed_by": "<likely owner: app name or team, based on key patterns>"
}}

Flag any keys that look like passwords, tokens, secrets, or credentials that should be in a Secret instead.
Return ONLY the JSON."""
        else:
            prompt = f"""You are a Kubernetes security expert reviewing a Secret. Return ONLY valid JSON (no markdown, no fences).

{resource_text}

Return this exact JSON:
{{
  "purpose": "<2-3 sentence explanation of what this Secret holds and which workloads likely mount it>",
  "key_breakdown": {{
    "<key_name>": "<description of what this key likely holds (TLS cert, DB password, API key, etc.)>"
  }},
  "security_concerns": [
    {{"severity": "Critical|High|Medium|Low", "concern": "<specific risk>", "recommendation": "<fix>"}}
  ],
  "recommendations": ["<security improvement>"],
  "risk_level": "safe" | "review" | "concern",
  "rotation_advice": "<how often this type of secret should be rotated>"
}}

Provide security-focused analysis: rotation cadence, RBAC access control recommendations, encryption at rest.
Return ONLY the JSON."""

        response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith('```'):
            raw = '\n'.join(raw.split('\n')[1:])
            if raw.endswith('```'):
                raw = raw[:-3]
        result = json.loads(raw.strip())
        result['gemini_powered'] = True
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({'purpose': 'AI parse error.', 'key_breakdown': {},
                        'security_concerns': [], 'recommendations': [],
                        'risk_level': 'unknown', 'gemini_powered': True}), 200
    except Exception as e:
        print(f'[explain_resource] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal Server Error', 'details': str(error)}), 500


@app.errorhandler(404)
def not_found_error(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not Found'}), 404
    return render_template('index.html'), 200






# ── Simple liveness ping (used by frontend heartbeat to keep connection alive) ─
@app.route('/api/health')
def api_health():
    """Lightweight liveness ping — no K8s calls, just proves the worker is alive."""
    import datetime
    return jsonify({'ok': True, 'ts': datetime.datetime.utcnow().isoformat()})

# ── NEW: Gemini Workloads AI Endpoints ─────────────────────────────────────

@app.route('/api/ai/health_pulse', methods=['POST'])
def health_pulse():
    """Namespace-wide health score — runs quickly over existing workload list."""
    try:
        data      = request.json or {}
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        workloads = data.get('workloads', [])

        failing = [w for w in workloads if w.get('status') in
                   ('Failed', 'CrashLoopBackOff', 'Error', 'OOMKilled',
                    'ImagePullBackOff', 'ErrImagePull')]
        total = max(len(workloads), 1)
        score = max(10, 100 - int((len(failing) / total) * 60))

        wl_lines = [
            f'  {w.get("type","?")} {w.get("name","?")} - {w.get("status","?")}'
            for w in workloads[:30]
        ]
        wl_summary = '\n'.join(wl_lines) or '  (no workloads)'

        fallback_issues = []
        if failing:
            fallback_issues.append({
                'severity': 'critical',
                'resource': failing[0]['name'],
                'kind': failing[0].get('type', 'Pod'),
                'issue': f"{failing[0]['name']} is in **{failing[0]['status']}** state.",
                'action': f"kubectl describe pod {failing[0]['name']} -n {namespace}"
            })
        fallback_issues.append({
            'severity': 'warning', 'resource': 'general', 'kind': 'Namespace',
            'issue': 'Check for single-replica Deployments that have no HA redundancy.',
            'action': f'kubectl get deployments -n {namespace} -o wide'
        })

        if not get_model():
            return jsonify({
                'score': score,
                'grade': 'A' if score >= 90 else ('B' if score >= 75 else ('C' if score >= 60 else 'D')),
                'namespace': namespace, 'total_resources': total,
                'failing_count': len(failing), 'issues': fallback_issues[:3],
                'summary': f'Namespace {namespace}: {total} resources, {len(failing)} failing.',
                'gemini_powered': False
            })

        prompt = (
            f'You are a Kubernetes SRE reviewing namespace "{namespace}".\n'
            f'Workloads ({total} total):\n{wl_summary}\n'
            f'Failing resources: {len(failing)}\n\n'
            'Score the overall namespace health 0-100 and identify the top 3 actionable issues.\n'
            'Return ONLY valid JSON (no markdown, no code fences):\n'
            '{\n'
            '  "score": <integer 0-100>,\n'
            '  "grade": "<A|B|C|D>",\n'
            '  "summary": "<1 sentence overall health summary>",\n'
            '  "issues": [\n'
            '    {\n'
            '      "severity": "<critical|warning|info>",\n'
            '      "resource": "<resource name>",\n'
            '      "kind": "<Deployment|Pod|Secret|etc>",\n'
            '      "issue": "<concise issue, use **bold** for key terms>",\n'
            '      "action": "<single kubectl command>"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['namespace'] = namespace
        d['total_resources'] = total
        d['failing_count'] = len(failing)
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'health_pulse error: {e}')
        return jsonify({'score': 75, 'grade': 'B', 'namespace': 'unknown',
                        'total_resources': 0, 'failing_count': 0, 'issues': [],
                        'summary': 'Health analysis unavailable.', 'gemini_powered': False})


@app.route('/api/ai/health_check', methods=['POST'])
def health_check():
    """Gemini deep health verdict for a Deployment or StatefulSet."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        kind      = data.get('kind', 'Deployment')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        apps_v1 = client.AppsV1Api()
        v1      = client.CoreV1Api()
        sections = []
        spec_replicas, ready = 1, 0

        try:
            if kind == 'Deployment':
                obj = apps_v1.read_namespaced_deployment(name, namespace)
            else:
                obj = apps_v1.read_namespaced_stateful_set(name, namespace)
            spec_replicas = obj.spec.replicas or 1
            ready = obj.status.ready_replicas or 0
            strategy = getattr(getattr(obj.spec, 'strategy', None), 'type', 'RollingUpdate')
            sections.append(
                f'{kind} {name}: spec_replicas={spec_replicas} ready={ready} strategy={strategy}'
            )
        except Exception as e:
            sections.append(f'{kind} {name}: unavailable ({e})')

        try:
            evts = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={name}')
            ev_lines = [f'[{ev.type}] {ev.reason}: {ev.message}' for ev in evts.items[-5:]]
            sections.append('Events:\n' + '\n'.join(ev_lines))
        except Exception:
            pass

        context = '\n\n'.join(sections)

        fallback_verdict = 'healthy' if ready >= spec_replicas else ('degraded' if ready > 0 else 'critical')
        icons = {'healthy': '✅', 'degraded': '⚠️', 'critical': '🔴'}
        colors = {'healthy': '#0f9d58', 'degraded': '#e6a000', 'critical': '#dc3545'}
        fallback = {
            'verdict': fallback_verdict,
            'verdict_label': fallback_verdict.capitalize(),
            'verdict_icon': icons[fallback_verdict],
            'verdict_color': colors[fallback_verdict],
            'summary': f'{name} ({kind}): {ready}/{spec_replicas} pods ready.',
            'replica_advice': 'Single replica — no HA.' if spec_replicas == 1 else 'Replica count appropriate.',
            'rollout_recommendation': 'Use maxUnavailable:1 maxSurge:1 rolling update strategy.',
            'resource_advice': 'Set CPU/memory requests and limits on all containers.',
            'kubectl_hints': [
                f'kubectl rollout status {kind.lower()}/{name}',
                f'kubectl describe {kind.lower()} {name}',
                f'kubectl get events --field-selector involvedObject.name={name} --sort-by=.lastTimestamp',
            ],
            'gemini_powered': False
        }

        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes SRE. Analyse this {kind} and produce a health verdict.\n'
            f'{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{\n'
            '  "verdict": "<healthy|degraded|critical>",\n'
            '  "verdict_label": "<Healthy|Degraded|Critical>",\n'
            '  "verdict_icon": "<✅|⚠️|🔴>",\n'
            '  "verdict_color": "<#0f9d58|#e6a000|#dc3545>",\n'
            '  "summary": "<1-sentence summary>",\n'
            '  "replica_advice": "<replica count and HA advice>",\n'
            '  "rollout_recommendation": "<rolling update strategy advice>",\n'
            '  "resource_advice": "<CPU/memory limits advice>",\n'
            '  "kubectl_hints": ["<cmd1>", "<cmd2>", "<cmd3>"]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'health_check error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/daemonset_insight', methods=['POST'])
def daemonset_insight():
    """Gemini DaemonSet node coverage and toleration analysis."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        apps_v1 = client.AppsV1Api()
        v1      = client.CoreV1Api()
        sections = []
        desired, ready = 3, 3

        try:
            ds = apps_v1.read_namespaced_daemon_set(name, namespace)
            desired = ds.status.desired_number_scheduled or 0
            ready   = ds.status.number_ready or 0
            tolerations = [str(t) for t in (ds.spec.template.spec.tolerations or [])]
            node_sel = dict(ds.spec.template.spec.node_selector or {})
            sections.append(
                f'DaemonSet {name}: desired={desired} ready={ready} '
                f'tolerations={tolerations} node_selector={node_sel}'
            )
        except Exception as e:
            sections.append(f'DaemonSet {name}: unavailable ({e})')

        try:
            nodes = v1.list_node().items
            node_info = []
            for n in nodes[:10]:
                taints = [f'{t.key}={t.value}:{t.effect}' for t in (n.spec.taints or [])]
                node_info.append(f'  node={n.metadata.name} taints={taints}')
            sections.append('Cluster nodes:\n' + '\n'.join(node_info))
        except Exception:
            pass

        context = '\n\n'.join(sections)
        pct = int((ready / max(desired, 1)) * 100)

        fallback = {
            'coverage_summary': f'`{name}` scheduled on {ready}/{desired} nodes.',
            'missing_nodes': max(0, desired - ready),
            'coverage_percent': pct,
            'issues': [],
            'toleration_advice': 'Tolerations look appropriate for standard nodes.',
            'resource_usage': 'Set memory limits to prevent OOMKill on node pods.',
            'kubectl_hints': [
                f'kubectl get daemonset {name} -o wide',
                f'kubectl describe daemonset {name}',
                f'kubectl get pods -l name={name.split("-")[0]} -o wide',
            ],
            'gemini_powered': False
        }

        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes SRE analysing a DaemonSet.\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{\n'
            '  "coverage_summary": "<sentence about node coverage>",\n'
            '  "missing_nodes": <integer>,\n'
            '  "coverage_percent": <integer 0-100>,\n'
            '  "issues": [{"node": "<node>", "reason": "<why not scheduled>", "fix": "<fix>"}],\n'
            '  "toleration_advice": "<toleration recommendation>",\n'
            '  "resource_usage": "<resource advice>",\n'
            '  "kubectl_hints": ["<cmd1>", "<cmd2>", "<cmd3>"]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['coverage_percent'] = pct
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'daemonset_insight error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/pod_triage', methods=['POST'])
def pod_triage():
    """Gemini smart log triage — error patterns, crash reason, recommended action."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1 = client.CoreV1Api()
        sections = []
        restart_advised = False

        try:
            pod = v1.read_namespaced_pod(name, namespace)
            for cs in (pod.status.container_statuses or []):
                restarts = cs.restart_count or 0
                state = cs.state
                if state.waiting and state.waiting.reason:
                    sections.append(
                        f'Container {cs.name}: waiting={state.waiting.reason} restarts={restarts}'
                    )
                    restart_advised = True
                elif state.terminated and state.terminated.reason:
                    sections.append(
                        f'Container {cs.name}: terminated={state.terminated.reason} '
                        f'exit={state.terminated.exit_code}'
                    )
                    restart_advised = True
                else:
                    sections.append(f'Container {cs.name}: running restarts={restarts}')
        except Exception as e:
            sections.append(f'Pod status: unavailable ({e})')

        try:
            logs = v1.read_namespaced_pod_log(name, namespace, tail_lines=100, timestamps=False)
            sections.append(f'Recent logs:\n{logs[-4000:]}')
        except Exception as e:
            sections.append(f'Logs: unavailable ({e})')

        context = '\n\n'.join(sections)

        fallback = {
            'pod': name,
            'triage_summary': f'Pod {name} triage — Gemini not configured.',
            'crash_reason': None,
            'restart_advised': restart_advised,
            'error_patterns': [],
            'affected_siblings': [],
            'recommended_action': 'Review pod logs and events manually.',
            'kubectl_hints': [
                f'kubectl logs {name} --previous --tail=50',
                f'kubectl describe pod {name}',
                f'kubectl top pod {name}',
            ],
            'gemini_powered': False
        }

        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes SRE triaging a pod.\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{\n'
            '  "triage_summary": "<1-2 sentence summary>",\n'
            '  "crash_reason": "<OOMKilled|CrashLoopBackOff|Timeout|ConfigError|null>",\n'
            '  "restart_advised": <true|false>,\n'
            '  "error_patterns": [\n'
            '    {"pattern": "<log pattern>", "count": <int>, "severity": "<critical|high|medium|low>", "last_seen": "<when>"}\n'
            '  ],\n'
            '  "recommended_action": "<specific fix recommendation>",\n'
            '  "kubectl_hints": ["<cmd1>", "<cmd2>", "<cmd3>"]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['pod'] = name
        d['affected_siblings'] = []
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'pod_triage error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/configmap_impact', methods=['POST'])
def configmap_impact():
    """Gemini ConfigMap blast-radius — which workloads use it and risky keys."""
    try:
        data      = request.json or {}
        name      = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        sections = []
        consumers = []
        keys = []

        try:
            cm = v1.read_namespaced_config_map(name, namespace)
            keys = list((cm.data or {}).keys())
            sample = {k: str(v)[:80] for k, v in list((cm.data or {}).items())[:10]}
            sections.append(f'ConfigMap {name}: keys={keys}\nsample: {sample}')
        except Exception as e:
            sections.append(f'ConfigMap {name}: unavailable ({e})')

        def find_consumers(items, kind_label):
            for obj in items:
                spec = obj.spec.template.spec
                uses = False
                mount_kind = 'unknown'
                for c in (spec.containers or []):
                    for ef in (c.env_from or []):
                        if ef.config_map_ref and ef.config_map_ref.name == name:
                            uses, mount_kind = True, 'env'
                for vol in (spec.volumes or []):
                    if vol.config_map and vol.config_map.name == name:
                        uses, mount_kind = True, 'volumeMount'
                if uses:
                    consumers.append({
                        'name': obj.metadata.name, 'kind': kind_label,
                        'mounted_as': mount_kind, 'critical_keys': keys[:3]
                    })

        try:
            find_consumers(apps_v1.list_namespaced_deployment(namespace).items, 'Deployment')
            find_consumers(apps_v1.list_namespaced_stateful_set(namespace).items, 'StatefulSet')
            find_consumers(apps_v1.list_namespaced_daemon_set(namespace).items, 'DaemonSet')
        except Exception:
            pass

        sections.append(f'Consumers: {[c["name"] for c in consumers]}')
        context = '\n\n'.join(sections)

        fallback = {
            'configmap': name,
            'summary': f'ConfigMap **{name}** referenced by {len(consumers)} workload(s).',
            'consumers': consumers,
            'risky_keys': [],
            'blast_radius': f'Removing this ConfigMap would affect {len(consumers)} workload(s).',
            'kubectl_hints': [
                f'kubectl get configmap {name} -o yaml',
                f'kubectl describe configmap {name}',
            ],
            'gemini_powered': False
        }

        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes SRE reviewing a ConfigMap and its consumers.\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{\n'
            '  "summary": "<1-sentence summary of who uses this ConfigMap>",\n'
            '  "risky_keys": [\n'
            '    {"key": "<key>", "value": "<value>", "risk": "<high|medium|low>", "note": "<why risky>"}\n'
            '  ],\n'
            '  "blast_radius": "<what breaks if this ConfigMap is misconfigured or deleted>",\n'
            '  "kubectl_hints": ["<cmd1>", "<cmd2>", "<cmd3>"]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['configmap'] = name
        d['consumers'] = consumers
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'configmap_impact error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/secret_audit', methods=['POST'])
def secret_audit():
    """Gemini Secret full audit — age, consumers, rotation advice, security flags."""
    try:
        from datetime import datetime, timezone as tz
        data      = request.json or {}
        name      = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))

        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1      = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        sections = []
        consumers = []
        age_days = 999

        try:
            secret = v1.read_namespaced_secret(name, namespace)
            keys = list((secret.data or {}).keys())
            created = secret.metadata.creation_timestamp
            if created:
                age_days = (datetime.now(tz.utc) - created.replace(tzinfo=tz.utc)).days
            sections.append(
                f'Secret {name}: type={secret.type} keys={keys} age_days={age_days}'
            )
        except Exception as e:
            sections.append(f'Secret {name}: unavailable ({e})')

        def find_secret_consumers(items, kind_label):
            for obj in items:
                spec = obj.spec.template.spec
                for c in (spec.containers or []):
                    for ef in (c.env_from or []):
                        if ef.secret_ref and ef.secret_ref.name == name:
                            consumers.append({
                                'name': obj.metadata.name, 'kind': kind_label,
                                'mount_method': 'secretRef (env)'
                            })
                for vol in (spec.volumes or []):
                    if vol.secret and vol.secret.secret_name == name:
                        consumers.append({
                            'name': obj.metadata.name, 'kind': kind_label,
                            'mount_method': 'volumeMount'
                        })

        try:
            find_secret_consumers(apps_v1.list_namespaced_deployment(namespace).items, 'Deployment')
            find_secret_consumers(apps_v1.list_namespaced_stateful_set(namespace).items, 'StatefulSet')
        except Exception:
            pass

        sections.append(f'Consumers: {[c["name"] for c in consumers]}')
        context = '\n\n'.join(sections)
        overdue = age_days > 90
        risk_level = 'high' if overdue else 'medium'

        fallback = {
            'secret': name, 'age_days': age_days,
            'rotation_overdue': overdue, 'risk_level': risk_level,
            'risk_summary': f'Secret **{name}** is **{age_days} days old**.',
            'consumers': consumers, 'is_orphaned': len(consumers) == 0,
            'security_flags': [{
                'severity': 'high' if overdue else 'low',
                'message': 'Rotation overdue (>90 days).' if overdue else 'Within rotation policy.'
            }],
            'rotation_plan': {
                'recommended_interval': '90 days',
                'next_rotation_by': '2026-06-01',
                'command': (
                    f'kubectl create secret generic {name} '
                    f'--from-literal=key=$(openssl rand -base64 32) '
                    f'--dry-run=client -o yaml | kubectl apply -f -'
                )
            },
            'kubectl_hints': [
                f'kubectl get secret {name} -o yaml',
                f'kubectl describe secret {name}',
                f'kubectl auth can-i get secret/{name} --as=system:serviceaccount:{namespace}:default',
            ],
            'gemini_powered': False
        }

        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes security expert auditing a Secret.\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{\n'
            '  "risk_summary": "<1-sentence risk summary, use **bold** for key terms>",\n'
            '  "security_flags": [\n'
            '    {"severity": "<high|medium|low>", "message": "<security concern>"}\n'
            '  ],\n'
            '  "rotation_plan": {\n'
            '    "recommended_interval": "<e.g. 90 days>",\n'
            '    "next_rotation_by": "<YYYY-MM-DD>",\n'
            '    "command": "<kubectl command to rotate>"\n'
            '  },\n'
            '  "kubectl_hints": ["<cmd1>", "<cmd2>", "<cmd3>"]\n'
            '}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['secret'] = name
        d['age_days'] = age_days
        d['rotation_overdue'] = overdue
        d['risk_level'] = risk_level
        d['consumers'] = consumers
        d['is_orphaned'] = len(consumers) == 0
        d['gemini_powered'] = True
        return jsonify(d)

    except Exception as e:
        app.logger.error(f'secret_audit error: {e}')
        return jsonify({'error': str(e)}), 500


# ── NEW: Gemini Networking AI Endpoints ────────────────────────────────────

@app.route('/api/ai/network_health', methods=['POST'])
def network_health():
    """Namespace network health — exposure analysis, VS coverage, policy gaps."""
    try:
        data = request.json or {}
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        services_in = data.get('services', [])
        vs_in = data.get('virtual_services', [])

        v1 = client.CoreV1Api()
        sections = []

        try:
            svcs = v1.list_namespaced_service(namespace).items
            svc_lines = []
            lb_count, nodeport_count = 0, 0
            for s in svcs:
                t = s.spec.type
                if t == 'LoadBalancer': lb_count += 1
                if t == 'NodePort': nodeport_count += 1
                ports = ','.join(f'{p.port}/{p.protocol}' for p in (s.spec.ports or []))
                svc_lines.append(f'  {s.metadata.name} type={t} ports={ports}')
            sections.append('Services:\n' + '\n'.join(svc_lines))
        except Exception as e:
            lb_count, nodeport_count = 0, 0
            sections.append(f'Services: unavailable ({e})')

        vs_count = len(vs_in)
        svc_count = len(services_in) or 1
        score = max(20, min(100, 100 - lb_count * 8 - nodeport_count * 5 - (10 if vs_count == 0 else 0)))

        fallback_issues = [{'severity': 'info', 'resource': 'mesh', 'kind': 'VirtualService',
                             'issue': 'No VirtualServices — traffic management not configured.',
                             'action': f'kubectl get virtualservices -n {namespace}'}] if vs_count == 0 else []

        if not get_model():
            return jsonify({'score': score,
                            'grade': 'A' if score >= 90 else ('B' if score >= 75 else 'C'),
                            'namespace': namespace, 'service_count': svc_count,
                            'vs_count': vs_count, 'lb_count': lb_count,
                            'issues': fallback_issues,
                            'summary': f'Namespace {namespace}: {svc_count} services, {vs_count} VirtualServices.',
                            'gemini_powered': False})

        context = '\n\n'.join(sections)
        prompt = (
            f'You are a Kubernetes/Istio SRE reviewing namespace "{namespace}" network health.\n'
            f'{context}\n\nScore network health 0-100 and list top 3 issues.\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"score":<int>,"grade":"<A|B|C|D>","summary":"<1 sentence>","issues":['
            '{"severity":"<critical|warning|info>","resource":"<name>","kind":"<Service|VS>","issue":"<text>","action":"<kubectl cmd>"}]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d.update({'namespace': namespace, 'service_count': svc_count,
                  'vs_count': vs_count, 'lb_count': lb_count, 'gemini_powered': True})
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'network_health error: {e}')
        return jsonify({'score': 70, 'grade': 'C', 'namespace': 'unknown',
                        'service_count': 0, 'vs_count': 0, 'lb_count': 0,
                        'issues': [], 'summary': 'Network health analysis unavailable.', 'gemini_powered': False})


@app.route('/api/ai/service_analyze', methods=['POST'])
def service_analyze():
    """Gemini explanation of a Service — purpose, selectors, port mapping."""
    try:
        data = request.json or {}
        name = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1 = client.CoreV1Api()
        sections = []

        try:
            svc = v1.read_namespaced_service(name, namespace)
            ports = [f'{p.port}->{p.target_port}/{p.protocol}' for p in (svc.spec.ports or [])]
            selector = dict(svc.spec.selector or {})
            sections.append(
                f'Service {name}: type={svc.spec.type} clusterIP={svc.spec.cluster_ip} '
                f'ports={ports} selector={selector}'
            )
            # Endpoints
            try:
                ep = v1.read_namespaced_endpoints(name, namespace)
                addrs = [a.ip for sub in (ep.subsets or []) for a in (sub.addresses or [])]
                sections.append(f'Endpoints ({len(addrs)} pods): {addrs[:5]}')
            except Exception:
                pass
        except Exception as e:
            sections.append(f'Service {name}: unavailable ({e})')

        context = '\n\n'.join(sections)
        fallback = {
            'service': name,
            'purpose': f'Service `{name}` provides a stable DNS name and load balancer for its target pods.',
            'type_explanation': 'ClusterIP — internal only. Accessible only within the cluster.',
            'port_breakdown': [{'port': data.get('ports', '80'), 'protocol': 'TCP', 'note': 'Primary application port.'}],
            'selector_advice': 'Ensure selector labels exactly match pod labels to avoid 503s.',
            'health_check': 'Verify endpoints are populated via kubectl get endpoints.',
            'kubectl_hints': [f'kubectl describe service {name}', f'kubectl get endpoints {name}'],
            'gemini_powered': False
        }
        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are a Kubernetes SRE explaining a Service to a developer.\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"purpose":"<2-3 sentences>","type_explanation":"<service type explanation>",'
            '"port_breakdown":[{"port":"<port>","protocol":"<TCP|UDP>","target":"<targetPort>","note":"<what traverses this port>"}],'
            '"selector_advice":"<label selector advice>","health_check":"<readiness/health advice>",'
            '"kubectl_hints":["<cmd1>","<cmd2>","<cmd3>"]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['service'] = name
        d['gemini_powered'] = True
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'service_analyze error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/service_dependency', methods=['POST'])
def service_dependency():
    """Gemini dependency map — which pods/deployments a service routes to."""
    try:
        data = request.json or {}
        name = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        sections = []
        consumers = []

        try:
            svc = v1.read_namespaced_service(name, namespace)
            selector = dict(svc.spec.selector or {})
            sections.append(f'Service {name} selector: {selector}')

            if selector:
                label_sel = ','.join(f'{k}={v}' for k, v in selector.items())
                pods = v1.list_namespaced_pod(namespace, label_selector=label_sel).items
                for p in pods[:10]:
                    phase = p.status.phase or 'Unknown'
                    consumers.append({'name': p.metadata.name, 'kind': 'Pod',
                                      'ready': phase, 'relationship': f'selector match ({label_sel})'})
                sections.append(f'Matching pods: {[p.metadata.name for p in pods]}')
        except Exception as e:
            sections.append(f'Service/pods: unavailable ({e})')

        try:
            ep = v1.read_namespaced_endpoints(name, namespace)
            addrs = [a.ip for sub in (ep.subsets or []) for a in (sub.addresses or [])]
            sections.append(f'Active endpoint IPs: {addrs}')
        except Exception:
            pass

        context = '\n\n'.join(sections)
        if not get_model():
            return jsonify({'service': name, 'summary': f'Service {name} routes to {len(consumers)} pod(s).',
                            'consumers': consumers, 'virtual_services': [], 'ingresses': [],
                            'blast_radius': f'Removing {name} would break {len(consumers)} consumer(s).',
                            'kubectl_hints': [f'kubectl get endpoints {name}'], 'gemini_powered': False})

        prompt = (
            f'You are a Kubernetes SRE mapping dependencies for service "{name}".\n{context}\n\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"summary":"<1 sentence>","blast_radius":"<impact if service removed>",'
            '"kubectl_hints":["<cmd1>","<cmd2>","<cmd3>"]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d.update({'service': name, 'consumers': consumers, 'virtual_services': [], 'ingresses': [], 'gemini_powered': True})
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'service_dependency error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/service_risk', methods=['POST'])
def service_risk():
    """Gemini security risk scan — exposure, NetworkPolicy gaps, port risks."""
    try:
        data = request.json or {}
        name = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        if not name:
            return jsonify({'error': 'name is required'}), 400

        v1 = client.CoreV1Api()
        sections = []
        svc_type = 'ClusterIP'

        try:
            svc = v1.read_namespaced_service(name, namespace)
            svc_type = svc.spec.type
            ports = [f'{p.port}/{p.protocol}' for p in (svc.spec.ports or [])]
            sections.append(f'Service {name}: type={svc_type} ports={ports}')
        except Exception as e:
            sections.append(f'Service: unavailable ({e})')

        try:
            policies = v1.list_namespaced_network_policy(namespace).items
            sections.append(f'NetworkPolicies ({len(policies)}): {[p.metadata.name for p in policies]}')
        except Exception:
            sections.append('NetworkPolicies: none found or unavailable')

        context = '\n\n'.join(sections)
        risk_level = 'high' if svc_type in ('LoadBalancer', 'NodePort') else 'low'

        if not get_model():
            return jsonify({'service': name, 'risk_level': risk_level,
                            'risk_summary': f'Service {name} ({svc_type}) risk assessment.',
                            'risks': [{'severity': 'info', 'issue': 'Gemini not configured.', 'fix': 'Set GCP_PROJECT_ID.'}],
                            'kubectl_hints': [f'kubectl describe service {name}'], 'gemini_powered': False})

        prompt = (
            f'You are a Kubernetes security expert scanning service "{name}" for risks.\n{context}\n\n'
            'Identify security risks (exposure, NetworkPolicy gaps, TLS, port conflicts).\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"risk_level":"<high|medium|low>","risk_summary":"<1 sentence>",'
            '"risks":[{"severity":"<high|medium|low>","issue":"<description>","fix":"<remediation>"}],'
            '"kubectl_hints":["<cmd1>","<cmd2>","<cmd3>"]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['service'] = name
        d['gemini_powered'] = True
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'service_risk error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/vs_route_analysis', methods=['POST'])
def vs_route_analysis():
    """Gemini VirtualService route analysis — routing rules in plain English."""
    try:
        import json as _json
        data = request.json or {}
        name = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        if not name:
            return jsonify({'error': 'name is required'}), 400

        sections = []
        try:
            # Istio VirtualService is a CRD — use custom_objects_api
            co_api = client.CustomObjectsApi()
            vs = co_api.get_namespaced_custom_object(
                group='networking.istio.io', version='v1beta1',
                namespace=namespace, plural='virtualservices', name=name)
            spec_str = _json.dumps(vs.get('spec', {}), indent=2)[:3000]
            sections.append(f'VirtualService {name} spec:\n{spec_str}')
        except Exception as e:
            sections.append(f'VirtualService {name}: unavailable ({e}). Using provided metadata.')
            hosts = data.get('hosts', [name])
            gateways = data.get('gateways', [])
            sections.append(f'hosts={hosts} gateways={gateways}')

        context = '\n\n'.join(sections)
        fallback = {
            'virtual_service': name, 'summary': f'VirtualService {name} route analysis.',
            'route_rules': [], 'timeout_policy': 'Not configured.',
            'retry_policy': 'Not configured.', 'fault_injection': None, 'issues': [],
            'kubectl_hints': [f'kubectl describe virtualservice {name}', f'istioctl analyze -n {namespace}'],
            'gemini_powered': False
        }
        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are an Istio/Kubernetes SRE analysing a VirtualService.\n{context}\n\n'
            'Explain routing rules in plain English and identify issues.\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"summary":"<1-2 sentences>","route_rules":[{"match":"<condition>","destination":"<svc>","weight":<int>,"note":"<explanation>"}],'
            '"timeout_policy":"<timeout config>","retry_policy":"<retry config>","fault_injection":"<null or description>",'
            '"issues":[{"severity":"<warning|info>","issue":"<text>","fix":"<cmd>"}],'
            '"kubectl_hints":["<cmd1>","<cmd2>","<cmd3>"]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['virtual_service'] = name
        d['gemini_powered'] = True
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'vs_route_analysis error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/vs_traffic_policy', methods=['POST'])
def vs_traffic_policy():
    """Gemini traffic policy health — canary splits, circuit breaking, mTLS gaps."""
    try:
        import json as _json
        data = request.json or {}
        name = data.get('name', '')
        namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
        if not name:
            return jsonify({'error': 'name is required'}), 400

        sections = []
        try:
            co_api = client.CustomObjectsApi()
            vs = co_api.get_namespaced_custom_object(
                group='networking.istio.io', version='v1beta1',
                namespace=namespace, plural='virtualservices', name=name)
            sections.append(f'VirtualService spec:\n{_json.dumps(vs.get("spec",{}),indent=2)[:2000]}')
            # Also check DestinationRules
            drs = co_api.list_namespaced_custom_object(
                group='networking.istio.io', version='v1beta1',
                namespace=namespace, plural='destinationrules')
            dr_names = [i['metadata']['name'] for i in drs.get('items', [])]
            sections.append(f'DestinationRules in namespace: {dr_names}')
            # PeerAuthentication
            pas = co_api.list_namespaced_custom_object(
                group='security.istio.io', version='v1beta1',
                namespace=namespace, plural='peerauthentications')
            pa_modes = [i.get('spec', {}).get('mtls', {}).get('mode', 'unset') for i in pas.get('items', [])]
            sections.append(f'PeerAuthentication mTLS modes: {pa_modes}')
        except Exception as e:
            sections.append(f'Istio resources: unavailable ({e})')

        context = '\n\n'.join(sections)
        fallback = {
            'virtual_service': name,
            'policy_summary': f'Traffic policy analysis for {name}.',
            'canary_health': {'status': 'unknown', 'recommendation': 'Gemini not configured.'},
            'missing_policies': [], 'traffic_risks': [],
            'kubectl_hints': [f'kubectl get virtualservice {name} -o yaml'],
            'gemini_powered': False
        }
        if not get_model():
            return jsonify(fallback)

        prompt = (
            f'You are an Istio SRE reviewing traffic policy health.\n{context}\n\n'
            'Analyse canary splits, circuit breaking, mTLS, and missing policies.\n'
            'Return ONLY valid JSON (no markdown):\n'
            '{"policy_summary":"<2 sentences>",'
            '"canary_health":{"status":"<active|stable|none>","stable_weight":<int>,"canary_weight":<int>,"recommendation":"<text>"},'
            '"missing_policies":[{"policy":"<Circuit Breaker|Fault Injection|mTLS>","severity":"<high|medium|low>","note":"<why>","fix":"<cmd>"}],'
            '"traffic_risks":[{"risk":"<description>","severity":"<high|medium|low>","fix":"<cmd>"}],'
            '"kubectl_hints":["<cmd1>","<cmd2>","<cmd3>","<cmd4>"]}'
        )
        resp = gemini_generate_with_retry(prompt)
        d = parse_gemini_json(resp.text)
        d['virtual_service'] = name
        d['gemini_powered'] = True
        return jsonify(d)
    except Exception as e:
        app.logger.error(f'vs_traffic_policy error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/self_heal', methods=['POST'])
def ai_self_heal():
    """Gemini diagnoses a failing workload and proposes a specific healing action."""
    data = request.json or {}
    name = data.get('name', '')
    kind = data.get('kind', 'Deployment')
    status = data.get('status', '')
    namespace = data.get('namespace', os.environ.get('POD_NAMESPACE', 'default'))

    try:
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # --- Gather diagnostics ---
        logs = ''
        events = []
        current_resources = {}
        current_image = ''

        try:
            # Get pod logs
            if kind == 'Pod':
                log_resp = v1.read_namespaced_pod_log(name=name, namespace=namespace, tail_lines=80, previous=True)
                logs = log_resp
            else:
                # Find pods for this deployment
                pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}').items
                if pods:
                    pod = pods[0]
                    try:
                        log_resp = v1.read_namespaced_pod_log(name=pod.metadata.name, namespace=namespace, tail_lines=80, previous=True)
                        logs = log_resp
                    except Exception:
                        log_resp = v1.read_namespaced_pod_log(name=pod.metadata.name, namespace=namespace, tail_lines=80)
                        logs = log_resp
        except Exception as e:
            logs = f'Could not fetch logs: {e}'

        try:
            # Get events
            ev_list = v1.list_namespaced_event(namespace=namespace)
            events = [
                f"{ev.reason}: {ev.message}"
                for ev in ev_list.items
                if name in (ev.involved_object.name or '')
            ][-10:]
        except Exception:
            pass

        try:
            # Get current resource limits and image
            if kind == 'Deployment':
                deploy = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
                containers = deploy.spec.template.spec.containers or []
                if containers:
                    c = containers[0]
                    current_image = c.image or ''
                    if c.resources and c.resources.limits:
                        current_resources = dict(c.resources.limits)
                    if c.resources and c.resources.requests:
                        current_resources['requests'] = dict(c.resources.requests)
        except Exception:
            pass

        # --- Build Gemini prompt ---
        prompt = f"""You are a Kubernetes self-healing expert. A {kind} named '{name}' in namespace '{namespace}' is in status '{status}'.

Diagnostic Data:
- Current image: {current_image or 'unknown'}
- Resource limits: {current_resources or 'not set'}
- Pod logs (last 80 lines):
{logs[:3000] if logs else 'Not available'}

- Recent events:
{chr(10).join(events) if events else 'No events captured'}

Based on this data, diagnose the exact root cause and recommend ONE specific healing action.

Return valid JSON with this structure:
{{
  "root_cause": "Clear 1-2 sentence explanation of why the pod/deployment is failing",
  "confidence": <integer 0-100>,
  "error_type": "{status}",
  "action": "<one of: restart|rollback|patch_resources|patch_image|patch_selector|delete_pod>",
  "action_label": "Human-readable label for the button, e.g. 'Restart Deployment' or 'Increase Memory to 512Mi'",
  "risk_level": "<low|medium|high>",
  "patch_preview": "The exact kubectl command that would fix this",
  "details": "1-2 extra sentences of context or caveats",
  "kubectl_hints": ["kubectl command 1", "kubectl command 2"]
}}

Rules:
- For OOMKilled: action must be patch_resources, suggest doubling the current limit
- For ImagePullBackOff/ErrImagePull: action must be patch_image, identify the likely typo or missing secret
- For CrashLoopBackOff with clear log errors: action is restart first, unless config issue is obvious
- For scheduling Pending >5min: action is patch_selector
- For stable-then-broken pattern: action is rollback
- risk_level is 'low' for restart/rollback, 'medium' for resource/image patches, 'high' for delete
- Return ONLY the JSON, no markdown or explanation
"""

        if get_model():
            response = get_model().models.generate_content(model=GEMINI_MODEL, contents=prompt)
            raw = response.text.strip()
            if raw.startswith('```'):
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            result = json.loads(raw.strip())
        else:
            result = {
                'root_cause': f'{kind} {name} is in {status} state. Gemini is not configured — basic analysis only.',
                'confidence': 60,
                'error_type': status,
                'action': 'restart',
                'action_label': 'Restart Workload',
                'risk_level': 'low',
                'patch_preview': f'kubectl rollout restart deployment/{name} -n {namespace}',
                'details': 'Set GCP_PROJECT_ID to enable AI-powered root cause analysis.',
                'kubectl_hints': [
                    f'kubectl logs -l app={name} -n {namespace}',
                    f'kubectl describe pod -l app={name} -n {namespace}',
                ]
            }

        result['name'] = name
        result['kind'] = kind
        result['namespace'] = namespace
        result['status'] = status
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/heal/execute', methods=['POST'])
def heal_execute():
    """Executes a healing action against the Kubernetes API."""
    import datetime
    data = request.json or {}
    name = data.get('name', '')
    kind = data.get('kind', 'Deployment')
    action = data.get('action', 'restart')
    namespace = data.get('namespace', os.environ.get('POD_NAMESPACE', 'default'))
    dry_run = data.get('dry_run', False)
    patch_params = data.get('patch_params', {})  # extra params for patch actions

    dry_run_str = 'All' if dry_run else None

    try:
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        if action == 'restart':
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would restart {kind} {name} via rollout annotation.', 'applied': False, 'dry_run': True})
            ts = datetime.datetime.utcnow().isoformat()
            patch = {'spec': {'template': {'metadata': {'annotations': {'kubectl.kubernetes.io/restartedAt': ts}}}}}
            apps_v1.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
            return jsonify({'status': 'success', 'message': f'Restarted {kind} {name}. New pods will be ready in ~30s.', 'applied': True, 'dry_run': False})

        elif action == 'rollback':
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would rollback {kind} {name} to previous revision.', 'applied': False, 'dry_run': True})
            body = client.AppsV1beta1DeploymentRollback(api_version='apps/v1beta1', name=name, rollback_to=client.AppsV1beta1RollbackConfig(revision=0))
            try:
                apps_v1.create_namespaced_deployment_rollback(name=name, namespace=namespace, body=body)
            except Exception:
                # Fallback: patch with undo annotation
                pod_list = v1.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')
                if pod_list.items:
                    v1.delete_namespaced_pod(name=pod_list.items[0].metadata.name, namespace=namespace)
            return jsonify({'status': 'success', 'message': f'Rolled back {kind} {name} to previous revision.', 'applied': True, 'dry_run': False})

        elif action == 'patch_resources':
            new_mem = patch_params.get('memory', '512Mi')
            new_cpu = patch_params.get('cpu', '')
            limits = {'memory': new_mem}
            if new_cpu:
                limits['cpu'] = new_cpu
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would patch {name} memory limit to {new_mem}.', 'applied': False, 'dry_run': True})
            deploy = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            container_name = deploy.spec.template.spec.containers[0].name
            patch = {'spec': {'template': {'spec': {'containers': [{'name': container_name, 'resources': {'limits': limits}}]}}}}
            apps_v1.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
            return jsonify({'status': 'success', 'message': f'Patched {name}: memory limit → {new_mem}. Rollout triggered.', 'applied': True, 'dry_run': False})

        elif action == 'patch_image':
            new_image = patch_params.get('image', '')
            if not new_image:
                return jsonify({'error': 'patch_image requires patch_params.image'}), 400
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would set image to {new_image}.', 'applied': False, 'dry_run': True})
            deploy = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            container_name = deploy.spec.template.spec.containers[0].name
            patch = {'spec': {'template': {'spec': {'containers': [{'name': container_name, 'image': new_image}]}}}}
            apps_v1.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
            return jsonify({'status': 'success', 'message': f'Image updated to {new_image}. Rollout in progress.', 'applied': True, 'dry_run': False})

        elif action == 'patch_selector':
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would remove nodeSelector from {name}.', 'applied': False, 'dry_run': True})
            patch = [{'op': 'remove', 'path': '/spec/template/spec/nodeSelector'}]
            apps_v1.patch_namespaced_deployment(name=name, namespace=namespace, body=patch, content_type='application/json-patch+json')
            return jsonify({'status': 'success', 'message': f'NodeSelector removed from {name}. Pod should schedule now.', 'applied': True, 'dry_run': False})

        elif action == 'delete_pod':
            if dry_run:
                return jsonify({'status': 'dry_run', 'message': f'[DRY RUN] Would delete failing pod(s) for {name}.', 'applied': False, 'dry_run': True})
            pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')
            deleted = 0
            for pod in pods.items:
                if pod.status.phase in ('Failed', 'Unknown') or any(
                    cs.state.waiting and cs.state.waiting.reason in ('CrashLoopBackOff', 'Error', 'OOMKilled')
                    for cs in (pod.status.container_statuses or [])
                ):
                    v1.delete_namespaced_pod(name=pod.metadata.name, namespace=namespace)
                    deleted += 1
            return jsonify({'status': 'success', 'message': f'Deleted {deleted} failing pod(s). Controller will recreate them.', 'applied': True, 'dry_run': False})

        else:
            return jsonify({'error': f'Unknown action: {action}'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/status')
def ai_status():
    """Diagnostic: shows Gemini init status, version, and config."""
    client_ready = get_model() is not None
    return jsonify({
        'gemini_ready': client_ready,
        'model': GEMINI_MODEL if client_ready else None,
        'sdk_version': __import__('google.genai', fromlist=['__version__']).__version__ if client_ready else None,
        'error': _client_error if not client_ready else None,
        'env': {
            'GCP_PROJECT_ID': bool(os.getenv('GCP_PROJECT_ID')),
            'GCP_REGION': os.getenv('GCP_REGION', 'us-central1'),
            'GOOGLE_APPLICATION_CREDENTIALS': os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '(not set)'),
            'creds_file_exists': os.path.exists(os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '')) if os.getenv('GOOGLE_APPLICATION_CREDENTIALS') else False,
        }
    })


@app.route('/api/ai/chat', methods=['POST'])
def ai_chat_compat():
    """AI Chat — calls Gemini for a one-shot response."""
    data = request.json or {}
    msg = data.get('message', '').strip()
    if not msg:
        return jsonify({'reply': 'No message provided'}), 400

    if not get_model():
        return jsonify({'reply': f'⚠️ Gemini not configured ({_client_error}). '
                                 f'Check /api/ai/status for details.'})
    try:
        resp = get_model().models.generate_content(
            model=GEMINI_MODEL,
            contents=f"You are a Kubernetes assistant. Answer concisely:\n{msg}"
        )
        return jsonify({'reply': resp.text.strip()})
    except Exception as e:
        return jsonify({'reply': f'Gemini error: {e}'}), 500


# ── Terminal / Console — Real K8s Exec via Socket.IO ────────────────────────
_terminal_sessions = {}  # sid → { 'stream': ws, 'thread': Thread }


@socketio.on('connect_terminal')
def handle_connect_terminal(data):
    """Open a real exec session into a pod container using kubernetes.stream."""
    pod_name = data.get('pod', '')
    container_name = data.get('container', '')
    namespace = data.get('namespace', os.getenv('POD_NAMESPACE', 'default'))
    sid = request.sid

    if not pod_name or not container_name:
        emit('terminal_error', {'data': 'Pod name and container name are required'})
        return

    try:
        v1 = client.CoreV1Api()
        # Try common shells: /bin/sh is most reliable
        exec_command = ['/bin/sh']

        ws = stream(
            v1.connect_get_namespaced_pod_exec,
            pod_name, namespace,
            container=container_name,
            command=exec_command,
            stderr=True, stdin=True, stdout=True, tty=True,
            _preload_content=False
        )

        # Store session
        _terminal_sessions[sid] = {'stream': ws, 'active': True}

        emit('terminal_output', {'data': f'\x1b[1;32mConnected to {pod_name}/{container_name}\x1b[0m\r\n'})

        # Background reader thread — reads from K8s exec stream and emits to browser
        def _reader():
            try:
                while _terminal_sessions.get(sid, {}).get('active', False):
                    if ws.is_open():
                        ws.update(timeout=1)
                        out = ws.read_stdout(timeout=0)
                        if out:
                            socketio.emit('terminal_output', {'data': out}, to=sid)
                        err = ws.read_stderr(timeout=0)
                        if err:
                            socketio.emit('terminal_output', {'data': err}, to=sid)
                    else:
                        break
            except Exception as e:
                socketio.emit('terminal_error', {'data': f'Stream closed: {str(e)}'}, to=sid)
            finally:
                socketio.emit('terminal_disconnect', {}, to=sid)
                _terminal_sessions.pop(sid, None)

        t = threading.Thread(target=_reader, daemon=True)
        _terminal_sessions[sid]['thread'] = t
        t.start()

    except Exception as e:
        error_msg = str(e)
        if 'not found' in error_msg.lower():
            emit('terminal_error', {'data': f'Pod {pod_name} not found in namespace {namespace}'})
        elif 'forbidden' in error_msg.lower():
            emit('terminal_error', {'data': f'Permission denied: exec into {pod_name} is not allowed'})
        else:
            emit('terminal_error', {'data': f'Failed to connect: {error_msg}'})


@socketio.on('terminal_input')
def handle_terminal_input(data):
    """Forward keystrokes from browser to the K8s exec stream."""
    sid = request.sid
    session = _terminal_sessions.get(sid)
    if session and session.get('stream') and session['stream'].is_open():
        try:
            session['stream'].write_stdin(data.get('data', ''))
        except Exception:
            pass


@socketio.on('disconnect')
def handle_disconnect():
    """Clean up terminal session when browser disconnects."""
    sid = request.sid
    session = _terminal_sessions.pop(sid, None)
    if session:
        session['active'] = False
        try:
            session['stream'].close()
        except Exception:
            pass


if __name__ == '__main__':

    socketio.run(app, host='0.0.0.0', port=8080, debug=True)

