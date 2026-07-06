# MVP Design: Envoy One Route, Multiple Tenants, API Key Auth, Rate Limit, and Usage Metrics

## 1. Goal

Build a simple MVP LLM-as-a-Service entry point where multiple tenants share the same model endpoint.

Target architecture:

```text
Client
  |
  | x-api-key
  v
Envoy Gateway
  - API key authentication
  - one shared HTTPRoute
  - per-key RPM rate limit
  - request metrics by tenant / API key
  |
  v
Tiny LLM Gateway / Middleware
  - forwards request to vLLM
  - reads vLLM usage from response
  - emits per-tenant token metrics
  |
  v
vLLM / Gemma pod
```

The MVP should answer:

- Who is calling the model?
- How many requests did each tenant send?
- How many prompt/completion tokens did each tenant consume?
- Is a tenant exceeding the allowed RPM?
- Is the shared model pod becoming overloaded?

---

## 2. One Route, Multiple Tenants

Use one shared `HTTPRoute` for the model endpoint.

Example:

```text
POST /v1/chat/completions
POST /v1/completions
```

All tenants call the same route:

```text
https://llm.example.com/v1/chat/completions
```

Tenant identity is provided by API key:

```text
x-api-key: <tenant-api-key>
```

Envoy Gateway validates the key using `SecurityPolicy`.

The same `HTTPRoute` is used for all tenants. You do **not** need one route per tenant for the MVP.

---

## 3. API Key Authentication

Envoy Gateway can validate API keys before forwarding traffic to the backend.

Concept:

```text
x-api-key = valid -> allow request
x-api-key = missing/invalid -> reject request
```

Example shape:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: llm-api-keys
  namespace: llm-gateway
type: Opaque
stringData:
  team-a: team-a-secret
  team-b: team-b-secret
---
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: llm-api-key-auth
  namespace: llm-gateway
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: llm-route
  apiKeyAuth:
    credentialRefs:
      - group: ""
        kind: Secret
        name: llm-api-keys
    extractFrom:
      - headers:
          - x-api-key
```

Recommended MVP behavior:

```text
Missing key -> 401
Invalid key -> 401
Valid key -> forward to backend
```

Reference: Envoy Gateway `SecurityPolicy` supports API key authentication and can target Gateway API resources such as `HTTPRoute`.

---

## 4. Per-Key RPM Rate Limit

For the MVP, use request-count-based rate limiting.

Example goal:

```text
team-a -> 30 requests/minute
team-b -> 30 requests/minute
```

With one shared route, configure the rate-limit key using the `x-api-key` header value.

Concept:

```text
HTTPRoute + x-api-key=team-a-secret -> bucket A
HTTPRoute + x-api-key=team-b-secret -> bucket B
```

So each API key gets its own rate-limit bucket.

Example shape:

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: llm-rate-limit
  namespace: llm-gateway
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: llm-route
  rateLimit:
    type: Global
    global:
      rules:
        - clientSelectors:
            - headers:
                - name: x-api-key
                  type: Distinct
          limit:
            requests: 30
            unit: Minute
```

Meaning:

```text
team-a-secret -> 30 RPM
team-b-secret -> 30 RPM
team-c-secret -> 30 RPM
```

Important MVP limitation:

```text
This gives the same RPM limit to every key.
```

If different tenants need different RPM limits, you need a more advanced design.

Options:

```text
Option 1: Separate route or path by tenant/tier
Option 2: External auth service maps API key -> tenant/tier
Option 3: LLM gateway/router enforces tenant-specific policy
```

---

## 5. What Envoy Can Cover

Envoy Gateway is good for edge-level protection.

It can cover:

```text
API key authentication
Per-key request-per-minute limit
Basic burst protection
HTTP 429 when too many requests
Request count metrics
Latency metrics
Status code metrics
Basic tenant attribution if tenant ID is represented in headers/logs
```

Good MVP use:

```text
x-api-key auth + per-key RPM limit
```

Example:

```text
tenant-a -> 30 RPM
tenant-b -> 30 RPM
```

---

## 6. What Envoy Cannot Fully Cover

Envoy does **not** understand LLM token usage by default.

Envoy cannot directly know:

```text
prompt_tokens
completion_tokens
total_tokens
KV cache usage per tenant
model-level queue pressure per tenant
true token-per-minute usage
actual output length
```

Envoy can count requests, but not the LLM cost of each request.

Example:

```text
Request A:
  input = 500 tokens
  output = 100 tokens

Request B:
  input = 16k tokens
  output = 2k tokens
```

To Envoy, both are just:

```text
1 request
```

But to vLLM/GPU, Request B is much more expensive.

Therefore:

```text
RPM limit -> Envoy
Token usage -> vLLM response / LLM gateway
Per-tenant TPM -> custom middleware/router
```

---

## 7. Why a Tiny LLM Gateway Is Needed

vLLM exposes aggregate metrics from `/metrics`, but those metrics are usually not enough for per-tenant usage accounting.

vLLM OpenAI-compatible responses include usage information such as:

```json
{
  "usage": {
    "prompt_tokens": 1024,
    "completion_tokens": 430,
    "total_tokens": 1454
  }
}
```

The LLM gateway should:

1. Receive request from Envoy.
2. Read `x-request-id`, `x-tenant-id`, or `x-api-key-id`.
3. Forward request to vLLM.
4. Read `usage` from the vLLM response.
5. Emit logs and metrics per tenant.

Example joined event:

```json
{
  "request_id": "abc-123",
  "tenant_id": "team-a",
  "api_key_id": "key-a",
  "model": "gemma-26b",
  "prompt_tokens": 1024,
  "completion_tokens": 430,
  "total_tokens": 1454,
  "latency_ms": 5200,
  "status": 200
}
```

This avoids a complicated Prometheus join.

---

## 8. Request ID and Tenant ID Flow

Envoy should add or preserve a request ID:

```text
x-request-id: abc-123
```

Envoy or external auth should also provide tenant identity:

```text
x-tenant-id: team-a
x-api-key-id: key-a
```

Then the tiny LLM gateway records:

```text
request_id + tenant_id + token usage
```

Recommended MVP flow:

```text
Client
  |
  | x-api-key
  v
Envoy
  - validates API key
  - rate limits by x-api-key
  - adds/preserves x-request-id
  - optionally injects x-tenant-id / x-api-key-id
  |
  v
LLM Gateway
  - reads headers
  - calls vLLM
  - records token usage
  |
  v
vLLM
```

---

## 9. Metrics to Capture

### 9.1 Envoy Metrics

Capture request-side metrics.

Minimum:

```text
requests_total
requests_rate
rate_limited_requests_total
http_429_total
http_401_total
http_5xx_total
request_duration_ms
upstream_response_time_ms
```

Recommended labels:

```text
tenant_id
api_key_id
route
model
status_code
```

For the MVP, if Envoy cannot safely expose raw API key values, do **not** use the raw secret as a label. Use a safe identifier:

```text
api_key_id = key-a
tenant_id = team-a
```

Avoid:

```text
api_key = team-a-secret
```

because that leaks secrets into logs/metrics.

### 9.2 vLLM Metrics

Capture model health and aggregate token throughput.

Minimum:

```text
prompt_tokens_total
generation_tokens_total
time_to_first_token
time_per_output_token
request_queue_time
running_requests
waiting_requests
gpu_cache_usage
preemption_count
```

vLLM `/metrics` is useful for model health:

```text
Is the model overloaded?
Is KV cache under pressure?
Is queue length increasing?
Is TTFT getting worse?
Is output token speed decreasing?
```

But raw vLLM metrics alone usually do not give clean per-tenant token usage.

### 9.3 LLM Gateway Metrics

This is the most important layer for tenant usage.

Emit custom metrics:

```text
llm_requests_total{tenant_id, api_key_id, model, status}
llm_prompt_tokens_total{tenant_id, api_key_id, model}
llm_completion_tokens_total{tenant_id, api_key_id, model}
llm_total_tokens_total{tenant_id, api_key_id, model}
llm_request_latency_seconds{tenant_id, api_key_id, model}
llm_rate_limited_total{tenant_id, api_key_id}
llm_errors_total{tenant_id, api_key_id, error_type}
```

Optional:

```text
llm_streaming_requests_total
llm_max_output_tokens_requested
llm_context_length_requested
```

---

## 10. Request Limit vs Token Limit

### RPM

Requests per minute.

Example:

```text
30 RPM
```

Good for:

```text
Preventing too many calls
Simple onboarding
Simple edge protection
Scheduled batch workloads
```

Weakness:

```text
Does not reflect token cost
```

### TPM

Tokens per minute.

Example:

```text
100,000 tokens/minute
```

Good for:

```text
LLM cost control
GPU capacity planning
Fair tenant usage
```

Weakness:

```text
Requires token counting
Requires LLM gateway/router
Harder than RPM
```

MVP recommendation:

```text
Phase 1: RPM only with Envoy
Phase 2: Monitor tokens per tenant
Phase 3: Enforce TPM per tenant in LLM gateway
```

---

## 11. Batch Workload Clarification

When tenants say “batch,” ask what they mean.

There are three different cases.

### Case 1: Scheduled batch processing

Example:

```text
10,000 independent requests overnight
```

This is many small/medium requests spread over time.

Bottleneck:

```text
Throughput
```

RPM works well.

Questions:

```text
How many requests per batch?
How often does the batch run?
What is the completion deadline?
Can the batch be queued?
Can the client retry on 429?
```

### Case 2: Burst workload

Example:

```text
100 requests arrive at exactly 09:00
```

This is many requests at the same time.

Bottleneck:

```text
Concurrency and queue length
```

RPM helps, but is not enough if the client cannot tolerate 429 or delay.

Need later:

```text
Concurrency limit
Queue limit
Retry/backoff policy
Priority scheduling
```

### Case 3: Long-context request

Example:

```text
One request with 32k input tokens and 2k output tokens
```

This is not really batch. It is long-context inference.

Bottleneck:

```text
KV cache
GPU memory
Long latency
```

RPM does not protect well here.

Need later:

```text
Max context length
Max output tokens
TPM limit
Request timeout
```

---

## 12. What Can Be Covered in MVP

MVP can cover:

```text
One shared route
Multiple tenants
API key authentication
Same RPM limit per tenant/API key
HTTP 429 on excess request rate
Basic Envoy request metrics
vLLM aggregate model metrics
LLM gateway per-tenant usage logs
Per-tenant prompt/completion token monitoring
Basic onboarding questionnaire
Basic capacity estimate
```

Recommended MVP policy:

```text
Each tenant:
  30 RPM default
  max output tokens: 512 or 1024
  max context length: 8k or 16k
  client must retry with exponential backoff on 429
```

---

## 13. What Should Not Be Promised in MVP

Do not promise these in the first MVP unless you build extra logic:

```text
Different RPM per tenant
True TPM enforcement
Cost-based rate limiting
Fair GPU scheduling
Per-tenant concurrency limit
Per-tenant queue isolation
Billing/chargeback
Tenant self-service API key portal
SLA guarantees
Guaranteed latency under burst traffic
Long-context protection using Envoy only
```

These require additional components.

---

## 14. Onboarding Questions

### Basic Tenant Information

```text
Tenant/team name:
Application owner:
Technical contact:
Environment: dev / test / prod
Use case:
Model requested:
Expected go-live date:
```

### Workload Pattern

Ask them to select one:

```text
Interactive API
Scheduled batch processing
Burst workload
Long-context inference
Other
```

Then ask:

```text
Is this user-facing or backend automation?
Is traffic predictable or bursty?
Is traffic time-window based?
Can requests be queued?
```

### Request Volume

```text
Expected requests per day:
Average requests per minute:
Peak requests per minute:
Peak time window:
Expected growth in 1 month:
Expected growth in 3 months:
```

### Token Size

```text
Average input tokens:
Maximum input tokens:
Average output tokens:
Maximum output tokens:
Maximum context length required:
```

### Concurrency

```text
Expected concurrent requests:
Maximum concurrent requests:
Are requests synchronous or asynchronous?
Can the client wait in a queue?
Can the client retry on 429?
Does the client support exponential backoff?
```

### Latency Expectation

```text
Acceptable time to first token:
Acceptable total response time:
Is streaming required?
Is this latency-sensitive?
```

### Failure Behavior

```text
Can the application handle 429?
Can the application handle timeout?
Can the application retry safely?
Is duplicate response generation a problem?
```

### Batch-Specific Questions

```text
How many requests in one batch?
How often does the batch run?
When does it run?
How quickly must the batch finish?
Can the batch be spread over several hours?
```

### Long-Context Questions

```text
Will users send documents?
Average document size:
Maximum document size:
Do they need summarization, extraction, or Q&A?
Can documents be chunked before sending to the model?
```

---

## 15. Capacity Estimation Formula

Use this simple estimate:

```text
tokens_per_request = avg_input_tokens + avg_output_tokens

peak_TPM = peak_RPM * tokens_per_request
```

Example:

```text
avg input = 1000 tokens
avg output = 500 tokens
peak RPM = 30

tokens_per_request = 1500
peak_TPM = 30 * 1500 = 45,000 tokens/minute
```

For two tenants:

```text
team-a = 45,000 TPM
team-b = 45,000 TPM

combined = 90,000 TPM
```

Then compare this with load test results from the actual model/pod.

---

## 16. Suggested Tenant Size Categories

For one shared Gemma 26B pod on one H100, start conservative and validate with load testing.

Example MVP categories:

```text
Small tenant:
  10-20 RPM
  < 30k TPM
  concurrency 2-4

Medium tenant:
  30-60 RPM
  30k-100k TPM
  concurrency 4-8

Large tenant:
  > 60 RPM
  > 100k TPM
  concurrency 8+
  needs review/load test
```

Default MVP onboarding limit:

```text
30 RPM per tenant
max output tokens: 1024
max context length: 8k or 16k
```

---

## 17. Implementation Plan

### Phase 1: Envoy Edge MVP

Implement:

```text
Gateway
HTTPRoute
SecurityPolicy for API key auth
BackendTrafficPolicy for per-key RPM
Prometheus scraping Envoy metrics
Basic dashboard
```

Deliverable:

```text
Tenants can call one shared endpoint using x-api-key.
Invalid keys are rejected.
Each key has its own RPM bucket.
```

### Phase 2: Usage Accounting

Add tiny LLM gateway/middleware.

Implement:

```text
Read x-request-id
Read x-tenant-id or api_key_id
Forward request to vLLM
Read usage.prompt_tokens
Read usage.completion_tokens
Emit per-tenant metrics/logs
```

Deliverable:

```text
Per-tenant token usage dashboard.
```

### Phase 3: Controls Beyond RPM

Implement:

```text
Max output token enforcement
Max context length enforcement
Tenant-level TPM monitoring
Request timeout
Queue limit
```

Deliverable:

```text
Better protection from long-context and high-output workloads.
```

### Phase 4: Advanced Tenant Policy

Implement:

```text
Different RPM per tenant
TPM enforcement
Per-tenant concurrency limit
Priority classes
Billing/chargeback
Self-service onboarding
```

Deliverable:

```text
Production-grade multi-tenant LLM platform.
```

---

## 18. Recommended MVP Decision

For the first version, keep it simple:

```text
One route
One shared Gemma/vLLM backend
API key auth at Envoy
Same RPM per API key
Tenant token monitoring in tiny LLM gateway
No TPM enforcement yet
No per-tenant concurrency guarantee yet
```

Recommended wording:

```text
The MVP provides API key authentication, per-key request rate limiting, and per-tenant usage visibility. It does not yet provide true token-based quota enforcement, differentiated tenant plans, or guaranteed latency under burst traffic.
```

---

## 19. References

- Envoy Gateway API key authentication: https://gateway.envoyproxy.io/docs/tasks/security/apikey-auth/
- Envoy Gateway global rate limiting: https://gateway.envoyproxy.io/docs/tasks/traffic/global-rate-limit/
- Envoy Gateway rate limiting concepts: https://gateway.envoyproxy.io/latest/concepts/rate-limiting/
- Envoy Gateway BackendTrafficPolicy: https://gateway.envoyproxy.io/docs/concepts/gateway_api_extensions/backend-traffic-policy/
- vLLM production metrics: https://docs.vllm.ai/en/v0.20.0/usage/metrics/
- vLLM OpenAI-compatible server: https://docs.vllm.ai/en/stable/serving/openai_compatible_server/
