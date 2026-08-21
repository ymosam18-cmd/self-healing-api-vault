"""
Architecture Documentation for Self-Healing API Vault
Complete system design, components, and operational patterns
"""

# Self-Healing API Vault - Architecture Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Core Components](#core-components)
3. [Architecture Diagram](#architecture-diagram)
4. [Design Patterns](#design-patterns)
5. [Data Flow](#data-flow)
6. [Security Architecture](#security-architecture)
7. [Deployment Architecture](#deployment-architecture)
8. [Operational Patterns](#operational-patterns)

---

## System Overview

### Purpose
The Self-Healing API Vault is a sophisticated credential management system that provides:
- **Automatic credential rotation** using dual-key strategy
- **Self-healing capabilities** with intelligent fallback mechanisms
- **Transparent credential management** with intelligent caching
- **High availability** with graceful degradation
- **Audit trail** for compliance and debugging

### Key Characteristics
- **Zero-downtime rotation**: Dual-key strategy allows service continuity during rotation
- **Self-healing**: Automatic recovery from Vault connectivity issues
- **Intelligent caching**: Reduced Vault dependency with smart cache invalidation
- **Grace periods**: Dual-key validity during transition phases
- **Audit logging**: Complete history of all credential operations

---

## Core Components

### 1. VaultClient
**Purpose**: Direct interface to HashiCorp Vault

**Responsibilities**:
- Authenticate with Vault using token or other auth methods
- Read/write secrets to Vault KV engine
- Monitor Vault health
- Handle Vault API errors and retries

**Key Methods**:
```python
get_secret(path: str) -> dict
put_secret(path: str, data: dict) -> dict
delete_secret(path: str) -> None
is_healthy() -> bool
```

**Error Handling**:
- Connection errors → retry with exponential backoff
- Authentication errors → propagate immediately
- Validation errors → log and return error response

### 2. CredentialCache
**Purpose**: In-memory or Redis-based caching layer

**Responsibilities**:
- Store credentials with TTL-based expiration
- Thread-safe operations using locks
- Provide cache statistics
- Handle cache invalidation

**Key Methods**:
```python
set(key: str, value: dict, ttl: int = None)
get(key: str) -> Optional[dict]
invalidate(key: str) -> None
clear_all() -> None
is_expired(key: str) -> bool
get_stats() -> dict
```

**Design Decision**: TTL-based expiration prevents serving stale credentials while reducing Vault load.

### 3. DualKeyRotationManager
**Purpose**: Implements zero-downtime credential rotation

**Architecture**:
```
┌─────────────────────────────────────────┐
│   Dual-Key Rotation Strategy            │
├─────────────────────────────────────────┤
│ Phase 1: Create New Key                 │
│   - Generate new API key                │
│   - Store as "current" in Vault         │
│   - Keep old key as "previous"          │
│                                          │
│ Phase 2: Grace Period (600s)            │
│   - Both keys active in external service│
│   - Clients transition to new key       │
│   - Cache invalidated                   │
│                                          │
│ Phase 3: Finalize Rotation              │
│   - Remove old key from external service│
│   - Update Vault with new state         │
│   - Record in rotation history          │
└─────────────────────────────────────────┘
```

**Key Methods**:
```python
rotate_key(path: str, new_key: dict) -> dict
finalize_rotation(path: str) -> dict
get_rotation_status(path: str) -> dict
```

**Grace Period Logic**:
- Prevents immediate revocation of old credentials
- Allows clients to migrate to new keys
- Configurable via `GRACE_PERIOD` env var (default: 600s)

### 4. SelfHealingManager
**Purpose**: Implements intelligent error recovery

**Responsibilities**:
- Handle Vault connectivity failures
- Manage retry logic with exponential backoff
- Provide cache-based fallback
- Track retry attempts per service

**Recovery Hierarchy**:
```
1. Try Vault (Primary)
   ↓
2. If fails, check cache (Fallback)
   ↓
3. If no cache, retry with exponential backoff
   ↓
4. If max retries exceeded, raise error with context
```

**Key Methods**:
```python
handle_vault_error(service: str, error: Exception) -> Optional[dict]
reset_retries(service: str) -> None
get_retry_status() -> dict
```

**Exponential Backoff Formula**:
```
delay = RETRY_BACKOFF_BASE ^ attempt_number
Max attempts: MAX_RETRIES (default: 3)
Base: RETRY_BACKOFF_BASE (default: 2)
Example: 2^1=2s, 2^2=4s, 2^3=8s
```

### 5. Flask REST API
**Purpose**: Expose credential operations via HTTP

**Endpoints**:
```
GET  /health                      - System health check
GET  /api/credentials/<service>   - Retrieve credentials
POST /api/rotate/<service>        - Initiate rotation
GET  /api/status/<service>        - Get credential status
GET  /api/cache/stats             - Cache statistics
POST /api/cache/clear             - Clear cache
```

**Request/Response Format**:
```json
{
  "status": "success|error",
  "data": {...},
  "timestamp": "2026-08-21T09:00:00Z",
  "request_id": "uuid"
}
```

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────┐
│              External Services                         │
│  (GitHub, Slack, Stripe, Custom APIs)                │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │   Flask REST API        │
        │  /api/credentials/{..}  │
        │  /api/rotate/{..}       │
        │  /health                │
        └────────┬────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    Request Middleware                     │
        │  - Rate limiting                          │
        │  - Authentication                         │
        │  - Request validation                     │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    Self-Healing Manager                   │
        │  - Error handling                         │
        │  - Retry logic                            │
        │  - Fallback coordination                  │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    CredentialCache (Redis/In-Memory)      │
        │  - TTL-based expiration                   │
        │  - Thread-safe operations                 │
        │  - Fallback source                        │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    Rotation Manager                       │
        │  - Dual-key rotation                      │
        │  - Grace period management                │
        │  - History tracking                       │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    Vault Client                           │
        │  - Secret read/write                      │
        │  - Health checks                          │
        │  - Error handling                         │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    HashiCorp Vault                        │
        │  - KV Secrets Engine                      │
        │  - Auth methods                           │
        │  - Audit logging                          │
        └────────┬──────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │    PostgreSQL (Audit DB)                  │
        │  - Credential history                     │
        │  - Rotation logs                          │
        │  - Compliance audit trail                 │
        └──────────────────────────────────────────┘
```

---

## Design Patterns

### 1. Dependency Injection
All major components receive dependencies via constructor:
```python
manager = DualKeyRotationManager(vault_client, cache)
```

**Benefits**:
- Easy to mock for testing
- Loose coupling between components
- Flexible configuration

### 2. Adapter Pattern
VaultClient adapts Vault API responses to internal format:
```python
vault_response = {...}  # Raw Vault API response
internal_format = vault_client.get_secret(path)  # Standardized format
```

### 3. Strategy Pattern
Error handling strategy is injected:
```python
# Option 1: Direct Vault access
get_credentials(service, use_fallback=False)

# Option 2: With fallback
get_credentials(service, use_fallback=True)
```

### 4. Chain of Responsibility
Credential retrieval follows a chain:
1. Check cache
2. If miss, try Vault
3. If Vault fails, try cache fallback
4. If all fail, raise error

### 5. Observer Pattern
Health checks trigger cache invalidation:
```python
@app.before_request
def check_vault_health():
    if not vault_client.is_healthy():
        switch_to_fallback_mode()
```

---

## Data Flow

### Credential Retrieval Flow
```
Request: GET /api/credentials/github?include_previous=true

1. Validate request parameters
2. Check rate limiting
3. Authenticate request (if required)
4. Query cache for "github"
   ├─ HIT: Return cached value
   └─ MISS: Proceed to Vault
5. Query Vault for secret at "api-keys/github"
   ├─ SUCCESS: Cache result, return to client
   ├─ FAIL: Try cache fallback
   │   ├─ HIT: Return with "source: fallback"
   │   └─ MISS: Raise error
   └─ FAIL (no fallback): Invoke self-healing
6. Add request to audit log
7. Return response

Response Format:
{
  "status": "success",
  "source": "vault|cache|fallback",
  "credentials": {
    "api_key": "sk_...",
    "previous_key": "sk_...",  # If include_previous=true
    "status": "active",
    "version": 5
  },
  "cached_at": "2026-08-21T09:00:00Z",
  "expires_at": "2026-08-21T10:00:00Z"
}
```

### Rotation Flow
```
Request: POST /api/rotate/github
Body: { "new_key": "sk_new_..." }

1. Validate new key format
2. Invoke rotation manager
3. Phase 1: Create dual keys
   - Store new_key as "current"
   - Keep old_key as "previous"
   - Set grace_period_until = now + GRACE_PERIOD
4. Invalidate cache for "github"
5. Start grace period timer
6. Phase 2 (automatic via scheduler):
   - After GRACE_PERIOD seconds
   - Finalize rotation
   - Remove previous_key
   - Update version number
7. Record in rotation history
8. Return rotation status

Response Format:
{
  "status": "success",
  "message": "Rotation initiated",
  "phase": "dual_key_active",
  "new_key_active": true,
  "previous_key_active": true,
  "grace_period_seconds": 600,
  "grace_period_until": "2026-08-21T10:10:00Z"
}
```

---

## Security Architecture

### 1. Authentication & Authorization
```
┌─────────────────────┐
│  API Request        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  Authentication Layer               │
├─────────────────────────────────────┤
│  ✓ Bearer Token (JWT)               │
│  ✓ API Key                          │
│  ✓ mTLS (optional)                  │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  Authorization Layer                │
├─────────────────────────────────────┤
│  ✓ Service-based permissions        │
│  ✓ Operation-based permissions      │
│  ✓ Rate limiting per user/service   │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  Request Processing                 │
└─────────────────────────────────────┘
```

### 2. Data Security
- **In Transit**: TLS 1.3 encryption
- **At Rest**: Vault encryption + PostgreSQL encryption
- **In Memory**: Credentials cleared after use
- **Logs**: Sensitive data masked/redacted

### 3. Vault Security
- **Auth Methods**: Token, AppRole, K8s, JWT
- **Policies**: Least privilege principle
- **Audit Logging**: All operations recorded
- **Encryption**: All secrets encrypted at rest

### 4. Network Security
- **CORS**: Configurable allowed origins
- **Rate Limiting**: Per-IP and per-user limits
- **HTTPS Enforcement**: Production only
- **Security Headers**: HSTS, CSP, X-Frame-Options

---

## Deployment Architecture

### Docker Compose Stack
```yaml
Services:
├── Vault (HashiCorp)
│   └── Port 8200
├── PostgreSQL (Audit DB)
│   └── Port 5432
├── Redis (Cache)
│   └── Port 6379
├── Self-Healing API
│   └── Port 5000
└── Nginx (Reverse Proxy)
    └── Port 80/443
```

### Kubernetes Deployment
```yaml
Namespace: vault-system

Components:
├── Vault StatefulSet
│   ├── 3 replicas
│   └── Persistent volumes
├── API Deployment
│   ├── 3 replicas
│   └── Horizontal Pod Autoscaler
├── PostgreSQL StatefulSet
│   └── Persistent volume
├── Redis StatefulSet
│   └── Persistent volume
└── Ingress
    └── TLS termination
```

---

## Operational Patterns

### 1. Health Check Strategy
```python
# Periodic health checks every HEALTH_CHECK_INTERVAL
- Vault connectivity
- Database connectivity
- Cache availability
- External service connectivity

Health Status:
- HEALTHY: All systems operational
- DEGRADED: Some systems failing, using fallbacks
- CRITICAL: Multiple systems failing
```

### 2. Monitoring & Alerting
```
Metrics to Monitor:
├── Vault connectivity (%) 
├── Cache hit ratio (%)
├── Rotation success rate (%)
├── Error rate (%)
├── API latency (p50, p95, p99)
├── Rotation duration (seconds)
└── Retry attempts (count)

Alert Thresholds:
├── Vault unavailable > 5 minutes
├── Error rate > 5%
├── Cache hit ratio < 50%
├── Rotation failure > 2 consecutive
└── API latency p95 > 5 seconds
```

### 3. Scheduled Tasks
```
APScheduler Jobs:
├── Health check every 60 seconds
├── Finalize rotations (grace period completion)
├── Auto-rotate services every ROTATION_INTERVAL
├── Cache cleanup (expired entries)
├── Audit log rotation
└── Backup encryption keys
```

### 4. Logging Strategy
```
Log Levels:
├── DEBUG: Detailed operation flow (development)
├── INFO: Important events (production)
├── WARNING: Degradation, retries
├── ERROR: Failures, exceptions
└── CRITICAL: System-wide failures

Log Format:
{
  "timestamp": "2026-08-21T09:00:00Z",
  "level": "INFO",
  "service": "SelfHealingManager",
  "message": "Credential rotation initiated",
  "request_id": "uuid",
  "service_name": "github",
  "duration_ms": 250
}
```

---

## Resilience Patterns

### 1. Circuit Breaker
```
State Machine:
CLOSED (normal) 
  ├─ consecutive failures ≥ threshold
  └─ → OPEN (fail fast)
    ├─ timeout elapsed
    └─ → HALF_OPEN (test recovery)
      ├─ test succeeds
      └─ → CLOSED
      or
      ├─ test fails
      └─ → OPEN
```

### 2. Fallback Strategy
```
Primary: Vault
├─ Fallback 1: Cache
│  ├─ Fallback 2: Stale cache
│  │  └─ Error: Return 503 Service Unavailable
```

### 3. Bulkhead Pattern
```
Separate thread pools:
├── Vault I/O operations
├── Cache operations
├── Database operations
└── External API calls

Prevents cascading failures across operations.
```

### 4. Timeout Strategy
```
API Request: 30s timeout
Vault Operation: 10s timeout
Database Query: 5s timeout
Cache Operation: 1s timeout
```

---

## Configuration Hierarchy

```
Default (config.py)
    ↓
Environment-specific (DevelopmentConfig, TestingConfig, ProductionConfig)
    ↓
Environment variables (.env)
    ↓
Runtime overrides
```

Priority: Runtime > Environment > Environment-specific > Default

---

## Extension Points

### Adding New Services
1. Add service name to `SERVICES_TO_ROTATE`
2. Configure Vault path: `secret/api-keys/{service}`
3. Implement rotation logic if custom
4. Add monitoring/alerting rules

### Custom Authentication
1. Extend `VaultClient` auth methods
2. Implement custom JWT validation
3. Add to Flask auth middleware

### Custom Cache Backend
1. Implement `ICache` interface
2. Support `set`, `get`, `invalidate`, `clear_all`
3. Pass to app initialization

---

## Performance Characteristics

### Latency Targets
```
Cache HIT:     < 50ms
Vault Query:   < 500ms (including network)
Rotation:      < 2000ms
API Response:  < 1000ms (p95)
```

### Throughput
```
Single Instance (4 workers):
├── Requests/sec: ~1000 rps
├── Concurrent connections: ~500
├── Cached operations: ~5000 rps
└── Vault operations: ~100 rps (rate limited)
```

### Storage
```
Cache (in-memory):
├── Default size: 1000 entries
├── Avg entry size: 500 bytes
├── Max memory: ~500 MB

Database (PostgreSQL):
├── Audit log retention: 90 days
├── Avg storage: ~10 MB/month
└── Index size: ~2 MB
```

---

## References

- HashiCorp Vault: https://www.vaultproject.io/
- APScheduler: https://apscheduler.readthedocs.io/
- Flask: https://flask.palletsprojects.com/
- Redis: https://redis.io/
- PostgreSQL: https://www.postgresql.org/

---

**Last Updated**: 2026-08-21
**Version**: 1.0.0
**Maintainer**: Saksham Yadav
