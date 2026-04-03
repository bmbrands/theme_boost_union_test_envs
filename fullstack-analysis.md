# Fullstack Analysis: Connecting the React Frontend to the Python Backend

## Executive Summary

The React frontend (`moodle-provisioner-frontend`) is a **fully mocked UI prototype** — it has no real API calls. Every action (create, start, stop, delete) manipulates in-memory React state with `useState`. The Python backend has a solid domain layer but only exposes a CLI interface (via `fire`). The GUI entry point (`gui.py`) throws `UserInterfaceNotYetImplemented`.

Connecting these two requires building an **HTTP REST API layer** in the Python backend and replacing the frontend's mock state management with real `fetch`/`axios` calls.

---

## Table of Contents

- [1. Current State of the Frontend](#1-current-state-of-the-frontend)
- [2. Current State of the Python Backend](#2-current-state-of-the-python-backend)
- [3. The Gap — What's Missing](#3-the-gap--whats-missing)
- [4. How Well Suited Is Python to Serve This?](#4-how-well-suited-is-python-to-serve-this)
- [5. How Well Suited Is the Frontend?](#5-how-well-suited-is-the-frontend)
- [6. API Design — Mapping Backend Operations to REST Endpoints](#6-api-design--mapping-backend-operations-to-rest-endpoints)
- [7. Data Model Mapping — Frontend vs Backend](#7-data-model-mapping--frontend-vs-backend)
- [8. Long-Running Operations & WebSockets](#8-long-running-operations--websockets)
- [9. Authentication & Security](#9-authentication--security)
- [10. Network Topology — Backend in a DMZ](#10-network-topology--backend-in-a-dmz)
- [11. Recommended Plan Forward](#11-recommended-plan-forward)
- [12. Estimated Effort per Phase](#12-estimated-effort-per-phase)

---

## 1. Current State of the Frontend

### Tech Stack
- **React 19** + TypeScript + Vite
- **Radix UI** (46 primitives) + Tailwind CSS
- **No HTTP client** — no `axios`, no `fetch` calls, no API service layer
- **sonner** for toast notifications, **recharts** for metrics charts

### What It Renders
- Environment table with expandable container rows
- Create/delete environments, start/stop containers
- Plugin catalog management
- User management with roles (Tester / Administrator)
- Audit log with filtering and CSV export
- Host metrics dashboard (CPU, memory, disk)
- Provisioning timeline with step-by-step progress

### How It Currently Works (100% Mock)

| Feature | Implementation | Real API needed? |
|:--------|:---------------|:-----------------|
| `handleCreateEnvironment()` | Creates objects in `useState`, simulates provisioning with `setTimeout` | Yes — `POST /api/infrastructures/{name}/build` |
| `handleStartContainer()` | Sets status to `"starting"`, then `"running"` after 2s timeout | Yes — `POST /api/environments/{name}/{version}/start` |
| `handleStopContainer()` | Sets status to `"stopping"`, then `"stopped"` after 2s timeout | Yes — `POST /api/environments/{name}/{version}/stop` |
| `handleDeleteEnvironment()` | Removes from array: `prev.filter(env => env.id !== id)` | Yes — `DELETE /api/infrastructures/{name}` |
| `useAuth.login()` | Finds user in `mockUsers` array by email, ignores password | Yes — real auth endpoint |
| `useSystemMetrics` | Generates random numbers: `cpu: 75-95%`, `memory: 85-100%` | Yes — real host metrics |
| `useAuditLog` | Appends to in-memory array | Yes — persistent audit storage |
| Provisioning timeline | `setTimeout` chain simulating steps | Yes — real progress via WebSocket/SSE |
| Webhook simulation | Creates fake environment with PR data | Yes — GitHub webhook endpoint |

**Key finding:** URLs like `https://focused-cray.92-205-184-244.plesk.page/filters/5.0.2/` are hardcoded strings in mock data — they are never fetched or navigated to programmatically. That's why Chrome DevTools shows no network calls.

### Frontend Mock Data Inventory

```
src/App.tsx               → mockEnvironments (6 environments, hardcoded)
src/types/user.ts         → mockUsers (7 users), defaultRoles (2 roles)
src/types/plugin.ts       → mockPlugins (2 plugins), mockPluginVersions
src/hooks/useAuditLog.ts  → mockAuditLogs (6 entries)
src/hooks/useSystemMetrics.ts → generateMockMetrics() (random numbers)
```

---

## 2. Current State of the Python Backend

### Tech Stack
- **Python 3.10+** with Poetry
- **dependency-injector** — DI container hierarchy
- **fire** — CLI framework
- **docker** SDK — container management
- **GitPython** — git operations
- **Jinja2** — template rendering
- **PyYAML** — YAML persistence ("database")
- **loguru** — structured logging

### Architecture

```
Application (DI root)
├── CrossCuttingConcerns
│   ├── ApplicationConfigManager   ← reads config.yml + env.local.yml
│   ├── InfrastructureYAMLParser   ← YAML "database" (infrastructure.yaml)
│   ├── TemplateEngine             ← Jinja2 templates (.env, nginx, local.yml)
│   └── Logger                     ← loguru wrapper
├── Domain
│   ├── Testbed                    ← init (clone moodle-docker, create dirs)
│   ├── TestInfrastructure         ← setup/build/teardown
│   └── TestContainer              ← start/stop/restart/destroy per version
├── Adapters
│   └── MoodleDownloader           ← downloads Moodle archives
└── Core (BoostUnionTestEnvCore)   ← orchestrator, 9 operations
```

### Core Operations (the API surface)

| Method | What it does | Duration |
|:-------|:-------------|:---------|
| `init_testbed()` | Clone moodle-docker, create dirs, download smartdata.php | ~30s |
| `list_infrastructures()` | Read infrastructure.yaml, return all infras | Instant |
| `setup_infrastructure(name, git_ref)` | Clone Boost Union at ref, create dirs | ~15s |
| `build_infrastructure(name, *versions)` | Download Moodle, extract, create Docker containers, generate configs | 1-5 min per version |
| `start_environment(name, *versions)` | docker-compose up + install DB + set theme + load test data | 30-90s per version |
| `stop_environment(name, *versions)` | docker-compose stop | ~5s |
| `restart_environment(name, *versions)` | docker-compose restart | ~10s |
| `destroy_environment(name, *versions)` | docker-compose down + remove nginx config | ~10s |
| `teardown_infrastructure(name)` | Destroy all containers, remove entire infra directory | ~30s |

### State Management (infrastructure.yaml)

```yaml
# This is the backend's "database" — a flat YAML file
iterinaire:
  git_ref:
    reference: main
    type: BRANCH
  moodles:
    5.1.3:
      admin_pw: mxqVoQwlPievCcBM7fvi6RdoppyZnjBX
      db_port: '63134'
      status: STARTED
      url: http://localhost:63133
      www_port: '63133'
```

---

## 3. The Gap — What's Missing

### Backend Side (Python)
1. **No HTTP server** — only a CLI entry point exists
2. **No REST API** — no routes, no request/response handling
3. **No authentication** — CLI runs as local user
4. **No WebSocket/SSE** — long operations (build, start) block synchronously
5. **No CORS** — no cross-origin headers
6. **No async support** — all Docker operations are synchronous/blocking
7. **State is file-based** — YAML file, no concurrent access handling

### Frontend Side (React)
1. **No API service layer** — no `fetch`, no `axios`, no API client
2. **No error handling for network requests** — all operations are infallible
3. **No loading states tied to real operations** — `setTimeout` fakes everything
4. **Data model mismatch** — frontend `Environment` ≠ backend infrastructure.yaml structure
5. **Features without backend equivalent** — user management, audit log, metrics, plugins catalog, webhook handler

---

## 4. How Well Suited Is Python to Serve This?

### Verdict: Well suited, with the right framework

Python is an excellent choice for this backend API. Here's why:

| Aspect | Assessment | Details |
|:-------|:-----------|:--------|
| **REST API frameworks** | Excellent | FastAPI (recommended), Flask, Django REST |
| **Async support** | Good with FastAPI | FastAPI uses `asyncio`; Docker SDK calls can run in thread pool |
| **WebSocket/SSE** | Native in FastAPI | `fastapi.WebSocket`, `sse-starlette` for progress streaming |
| **Docker SDK** | Already in use | `docker` Python SDK is mature and reliable |
| **Authentication** | Many options | `python-jose` (JWT), `passlib` (password hashing), FastAPI Security utilities |
| **Existing DI container** | Compatible | `dependency-injector` works well with FastAPI |
| **CORS** | Built-in middleware | `fastapi.middleware.cors.CORSMiddleware` |
| **Deployment** | Standard | `uvicorn` (ASGI server), runs behind nginx on the Plesk server |

### Recommended Framework: FastAPI

FastAPI is the best fit because:

1. **Type-safe** — uses Pydantic models (similar to TypeScript interfaces)
2. **Auto-generated OpenAPI docs** — Swagger UI at `/docs`, useful for frontend development
3. **Async-first** — but can run sync code in thread pools (important for blocking Docker calls)
4. **WebSocket support** — built-in, needed for provisioning progress
5. **Dependency injection** — compatible with the existing `dependency-injector` library
6. **CORS middleware** — one line to enable cross-origin requests
7. **Low learning curve** — decorator-based routing, similar to Fire's CLI pattern

### Why Not Flask or Django?

- **Flask**: No built-in async, no auto-generated API docs, no native WebSocket
- **Django**: Overkill for this project, heavy ORM not needed (data is in YAML files)

---

## 5. How Well Suited Is the Frontend?

### Verdict: Good foundation, but needs an API integration layer

**Strengths:**
- Clean component architecture — each feature in its own modal/component
- Type definitions already exist for all data structures
- Handler functions are already named correctly (`handleCreateEnvironment`, `handleStartContainer`)
- Loading/provisioning states already modeled in the UI

**Weaknesses:**
- All handlers manipulate local state only — need to add API calls
- `Environment` type doesn't match backend data structure (see Section 7)
- No centralized API client or error handling
- Some features have no backend equivalent (user management, metrics, audit log)

### What Can Be Reused As-Is
- All Radix UI components and styling
- Modal layouts and form components
- Toast notification pattern
- Table and filter components
- Provisioning timeline UI (but needs real WebSocket data)

### What Needs Rewriting
- `App.tsx` state management → move to API calls + React Query or SWR
- `useAuth` → real JWT-based authentication
- `useSystemMetrics` → real API polling
- `useAuditLog` → API-backed persistent log
- All handler functions → add `fetch()` / `axios` calls before state updates

---

## 6. API Design — Mapping Backend Operations to REST Endpoints

### Core Endpoints (matching existing backend operations)

```
# Testbed
POST   /api/testbed/init                          → core.init_testbed()

# Infrastructures (= "Environments" in frontend)
GET    /api/infrastructures                        → core.list_infrastructures()
POST   /api/infrastructures                        → core.setup_infrastructure(name, git_ref)
DELETE /api/infrastructures/{name}                 → core.teardown_infrastructure(name)

# Moodle versions within an infrastructure (= "Containers" in frontend)
POST   /api/infrastructures/{name}/build           → core.build_infrastructure(name, *versions)
POST   /api/infrastructures/{name}/{version}/start → core.start_environment(name, version)
POST   /api/infrastructures/{name}/{version}/stop  → core.stop_environment(name, version)
POST   /api/infrastructures/{name}/{version}/restart → core.restart_environment(name, version)
DELETE /api/infrastructures/{name}/{version}        → core.destroy_environment(name, version)

# WebSocket for long-running operations
WS     /api/ws/operations/{operation_id}           → stream progress for build/start
```

### New Endpoints (features the frontend expects but backend doesn't have yet)

```
# Authentication
POST   /api/auth/login                             → NEW: JWT token generation
POST   /api/auth/logout                            → NEW: token invalidation
GET    /api/auth/me                                → NEW: current user info

# System metrics
GET    /api/metrics                                → NEW: host CPU/memory/disk (psutil)

# Audit log
GET    /api/audit                                  → NEW: persistent operation log
```

### Example: Create Environment Flow

```
Frontend                          Backend API                      Backend Core
────────                          ───────────                      ────────────
CreateEnvironmentModal
  → name: "filters"
  → plugin: "theme_boost_union"
  → version: "PR#1026"
  → moodleVersions: ["5.0.2", "4.5.6"]
           │
           ▼
  POST /api/infrastructures
  { name: "filters",
    git_ref: { type: "pr", reference: "1026" } }
           │                        │
           │                        ▼
           │               core.setup_infrastructure("filters", ...)
           │               → clones Boost Union PR #1026
           │                        │
           ▼                        ▼
  POST /api/infrastructures/filters/build
  { versions: ["5.0.2", "4.5.6"] }
           │                        │
           │                        ▼
           │               core.build_infrastructure("filters", "5.0.2", "4.5.6")
           │               → downloads Moodle, creates Docker containers
           │               → streams progress via WebSocket
           ▼
  WS /api/ws/operations/{id}
  ← { step: "downloading_moodle", progress: 45% }
  ← { step: "creating_containers", progress: 80% }
  ← { step: "completed", progress: 100% }
```

---

## 7. Data Model Mapping — Frontend vs Backend

The frontend and backend use different terminology and structures. Here's the mapping:

| Frontend concept | Frontend type | Backend concept | Backend source |
|:-----------------|:-------------|:----------------|:---------------|
| `Environment` | `{ id, name, plugin, version, containers[] }` | Infrastructure | `infrastructure.yaml` top-level key |
| `Environment.name` | `string` | Infrastructure name | YAML key (e.g., `"iterinaire"`) |
| `Environment.plugin` | `string` (e.g., `"theme_boost_union"`) | — | Not stored (always Boost Union currently) |
| `Environment.version` | `string` (e.g., `"PR#1026"`) | `git_ref.reference` + `git_ref.type` | `infrastructure.yaml` |
| `MoodleContainer` | `{ id, moodleVersion, status, url, adminPassword }` | Moodle entry | `infrastructure.yaml → moodles → {version}` |
| `MoodleContainer.status` | `"running" \| "stopped" \| ...` | `status` | `"CREATED" \| "STARTED" \| "STOPPED"` |
| `MoodleContainer.url` | `string` | `url` | `http://localhost:63133` |
| `MoodleContainer.adminPassword` | `string` | `admin_pw` | `infrastructure.yaml` |
| User management | `User`, `Role`, `Permission` | — | **Does not exist in backend** |
| Audit log | `AuditLogEntry` | — | **Does not exist in backend** |
| System metrics | `SystemMetrics` | — | **Does not exist in backend** |
| Plugin catalog | `Plugin`, `PluginVersion` | — | **Does not exist in backend** (hardcoded to Boost Union) |

### API Response Model (proposed Pydantic schema)

```python
from pydantic import BaseModel
from enum import Enum

class GitRefType(str, Enum):
    BRANCH = "branch"
    TAG = "tag"
    PR = "pr"
    COMMIT = "commit"

class ContainerStatus(str, Enum):
    CREATED = "created"
    STARTED = "running"      # Map STARTED → running for frontend
    STOPPED = "stopped"

class MoodleContainerResponse(BaseModel):
    moodle_version: str
    status: ContainerStatus
    url: str
    admin_password: str
    www_port: str
    db_port: str

class InfrastructureResponse(BaseModel):
    name: str
    git_ref_type: GitRefType
    git_ref_reference: str
    moodles: dict[str, MoodleContainerResponse]

class InfrastructureListResponse(BaseModel):
    infrastructures: list[InfrastructureResponse]
```

---

## 8. Long-Running Operations & WebSockets

Several backend operations take 30 seconds to several minutes. The frontend already has a `ProvisioningTimelineModal` with step-by-step progress — but it's faked with `setTimeout`.

### The Problem

These backend operations are **synchronous and blocking**:

```python
# core.py — build_infrastructure blocks for minutes
def build_infrastructure(self, infrastructure_name: str, *versions: str):
    self.yaml.add_moodles_to_infrastructure(...)  # instant
    self.infrastructure.build(*versions)           # BLOCKS: downloads + docker create
```

### Solution: Background Tasks + WebSocket Progress

```
Option A: FastAPI BackgroundTasks + WebSocket
─────────────────────────────────────────────
1. POST /api/infrastructures/{name}/build
   → Returns immediately with { operation_id: "abc123" }
   → Starts background task

2. WS /api/ws/operations/abc123
   → Streams: { step: "download_moodle_5.0.2", status: "running" }
   → Streams: { step: "download_moodle_5.0.2", status: "completed" }
   → Streams: { step: "docker_create_5.0.2", status: "running" }
   → ...
   → Streams: { status: "completed" }

Option B: Server-Sent Events (SSE) — simpler
─────────────────────────────────────────────
1. POST /api/infrastructures/{name}/build
   → Returns SSE stream (Content-Type: text/event-stream)
   → Frontend reads with EventSource API
```

**Recommendation:** Start with **Option B (SSE)** — simpler to implement, no WebSocket library needed on either side. Upgrade to WebSocket only if bidirectional communication is needed later.

---

## 9. Authentication & Security

### Current State
- **Backend:** No auth — CLI runs as local system user
- **Frontend:** `useAuth` does `mockUsers.find(u => u.email === email)` — no password check

### Recommended Approach: JWT + API Keys

```
For production deployment:
─────────────────────────
1. Frontend sends POST /api/auth/login { email, password }
2. Backend validates credentials, returns JWT token
3. Frontend stores JWT in memory (not localStorage for XSS safety)
4. All subsequent requests include: Authorization: Bearer <token>
5. Backend middleware validates JWT on every request
```

### Implementation with FastAPI

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/api/auth/login")
async def login(credentials: LoginRequest):
    # Validate against user store
    token = create_jwt(user_id=user.id, roles=user.roles)
    return {"access_token": token}

@app.get("/api/infrastructures", dependencies=[Depends(security)])
async def list_infrastructures(token = Depends(verify_jwt)):
    return core.list_infrastructures()
```

### CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 10. Network Topology — Backend in a DMZ

If the Python backend runs in a DMZ zone where REST endpoints **cannot be exposed directly over HTTPS**, there are several alternatives. The options below are ordered from most practical to most complex.

### Option 1: Reverse Proxy via Nginx (Recommended)

The Plesk server (`focused-cray.92-205-184-244.plesk.page`) already runs Nginx with Let's Encrypt TLS certificates. Add a `location /api/` block that proxies to the Python backend over plain HTTP inside the network:

```nginx
location /api/ {
    proxy_pass http://backend-dmz-host:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket/SSE support for long-running operations
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;  # build operations can take minutes
}
```

```
┌─────────────────┐    HTTPS    ┌──────────────────────┐    HTTP     ┌─────────────────┐
│  React Frontend │ ──────────► │  Nginx (Plesk)       │ ─────────► │  Python Backend  │
│  (Browser)      │             │  TLS termination     │            │  (FastAPI/DMZ)   │
│                 │ ◄────────── │  /api/ → proxy_pass  │ ◄───────── │  port 8000       │
└─────────────────┘             └──────────────────────┘            └─────────────────┘
       Public                        Public / DMZ edge                    DMZ internal
```

**Pros:** Reuses existing infrastructure, TLS handled by Nginx, backend never exposed publicly, SSE/WebSocket proxying supported.
**Cons:** Requires network access from Plesk to the DMZ host.

### Option 2: SSH Tunnel

Forward the backend API port through SSH. No firewall or infrastructure changes needed:

```bash
# On the machine running the frontend (or the Plesk server)
ssh -L 8000:localhost:8000 user@dmz-host
```

The frontend talks to `localhost:8000` — traffic is encrypted through the SSH tunnel.

**Pros:** Zero infrastructure changes, encrypted, works immediately.
**Cons:** Fragile for production (tunnel drops), only suitable for development or occasional access.

### Option 3: VPN Mesh (Tailscale / WireGuard)

Place both the frontend server and backend on a private mesh VPN. The backend gets a private IP (e.g., `100.x.x.x`) accessible only from VPN peers.

```
┌─────────────┐        ┌──────────────────┐        ┌─────────────────┐
│  Frontend    │  VPN   │  Tailscale /     │  VPN   │  Python Backend │
│  Server     │ ◄────► │  WireGuard Mesh  │ ◄────► │  (DMZ)          │
└─────────────┘        └──────────────────┘        └─────────────────┘
  100.64.0.1                                          100.64.0.2
```

**Pros:** Zero-trust model, no public ports, encrypted peer-to-peer, works across networks.
**Cons:** Requires Tailscale/WireGuard client on both machines, additional dependency.

### Option 4: Outbound Tunnel (Cloudflare Tunnel / ngrok)

The backend runs a tunnel client that connects **outbound** to a relay service, which provides a public HTTPS URL. No inbound firewall rules needed — the backend initiates the connection.

```bash
# On the DMZ backend
cloudflared tunnel --url http://localhost:8000
# → Exposes as: https://my-tunnel.cfargotunnel.com
```

**Pros:** No inbound ports, no firewall changes, zero-trust, easy setup.
**Cons:** Dependency on third-party service, potential latency, free tier limitations.

### Option 5: Message Queue (RabbitMQ / Redis Pub/Sub)

The backend never accepts inbound connections. Instead, a lightweight API gateway (outside DMZ) publishes commands to a message queue. The backend **polls** the queue for work and publishes results back.

```
Frontend → API Gateway → Queue (RabbitMQ) ← Backend (DMZ)
                         Results Queue    → API Gateway → Frontend
```

**Pros:** Backend has zero inbound attack surface, highly decoupled.
**Cons:** Significant complexity, added latency, harder to implement real-time progress, requires queue infrastructure.

### Recommendation for This Project

**Option 1 (Reverse Proxy)** is the clear winner:
- The Nginx + TLS infrastructure already exists on the Plesk server
- The `env.prod.yml` already defines `softlinked_nginx_config_path` for generated configs
- CORS becomes unnecessary (same origin: frontend and API both served from the same domain)
- SSE/WebSocket for provisioning progress works through `proxy_pass` with the right headers
- No additional services or dependencies needed

For **local development**, use Option 2 (SSH tunnel) or simply run both frontend and backend on `localhost`.

---

## 11. Recommended Plan Forward

### Phase 1: API Foundation (Backend)

Add a FastAPI server next to the existing CLI. Both share the same `BoostUnionTestEnvCore`.

```
theme_boost_union_test_envs/
├── ui/
│   ├── cli/
│   │   └── cli.py          ← existing, keep as-is
│   ├── gui/
│   │   └── gui.py          ← replace stub with FastAPI app
│   └── api/                 ← NEW
│       ├── __init__.py
│       ├── server.py        ← FastAPI app, CORS, middleware
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── testbed.py   ← POST /api/testbed/init
│       │   ├── infrastructures.py  ← CRUD for infrastructures
│       │   └── environments.py     ← start/stop/restart/destroy
│       ├── models/
│       │   ├── __init__.py
│       │   ├── requests.py  ← Pydantic request models
│       │   └── responses.py ← Pydantic response models
│       └── auth.py          ← JWT auth (can be deferred)
```

**Deliverables:**
- `GET /api/infrastructures` — returns real data from infrastructure.yaml
- `POST /api/infrastructures` — calls `setup_infrastructure()`
- `POST /api/infrastructures/{name}/build` — calls `build_infrastructure()`
- Container lifecycle endpoints (start/stop/restart/destroy)
- CORS enabled for `localhost:5173`
- Auto-generated Swagger docs at `/docs`

### Phase 2: Frontend API Integration

Replace mock data with real API calls.

```
moodle-provisioner-frontend/src/
├── api/                     ← NEW
│   ├── client.ts            ← fetch wrapper with base URL, auth headers, error handling
│   ├── infrastructures.ts   ← API functions: listInfrastructures(), createInfrastructure(), etc.
│   └── types.ts             ← API response types (matching Pydantic models)
├── hooks/
│   ├── useAuth.ts           ← MODIFY: real login/logout API calls
│   └── useInfrastructures.ts ← NEW: React Query hook for infrastructure data
```

**Deliverables:**
- API client with error handling and auth headers
- `useInfrastructures()` hook that replaces `mockEnvironments`
- `handleCreateEnvironment()` calls `POST /api/infrastructures` + `POST /api/.../build`
- `handleStartContainer()` calls `POST /api/.../start`
- Loading spinners while operations are in progress

### Phase 3: Real-time Progress

Replace `setTimeout` provisioning simulation with SSE streams.

**Deliverables:**
- Backend emits progress events during `build` and `start` operations
- Frontend `ProvisioningTimelineModal` reads real events via `EventSource`
- Toast notifications on completion/failure

### Phase 4: Auth & Multi-user (if needed for production)

**Deliverables:**
- JWT-based authentication
- User management backed by a real store (SQLite or PostgreSQL)
- Role-based access control matching frontend's permission model
- Audit log persistence

---

## 12. Estimated Effort per Phase

| Phase | Scope | Complexity |
|:------|:------|:-----------|
| **Phase 1** | FastAPI server + 8 REST endpoints + Swagger docs | Medium — most logic already exists in `core.py` |
| **Phase 2** | Frontend API client + replace mock handlers | Medium — mechanical replacement of mock → fetch |
| **Phase 3** | SSE progress streaming for long operations | Medium — requires refactoring sync operations |
| **Phase 4** | JWT auth + user management + audit log | Large — entirely new subsystem |

### Quick Win: Phase 1 Minimal

The fastest path to a working demo:

1. `pip install fastapi uvicorn` (add to pyproject.toml)
2. Create `api/server.py` with 2 endpoints: `GET /api/infrastructures` and `POST /.../start`
3. Wire into existing DI container (the `Application` class)
4. Run with `uvicorn theme_boost_union_test_envs.ui.api.server:app --reload`
5. Frontend: add one `fetch()` call in `useEffect` to load real environments

This proves the full-stack connection works and gives you a working `list` view backed by real data.

---

## Appendix: Key Files Reference

### Backend (Python)
| File | Role |
|:-----|:-----|
| `core.py` | Orchestrator — all 9 operations live here |
| `app.py` | DI container wiring |
| `ui/cli/cli.py` | CLI interface (Fire) — wrappers around core |
| `ui/gui/gui.py` | GUI stub — `raise NotYetImplemented` |
| `cross_cutting/configuration.py` | Reads config.yml + env.local.yml |
| `cross_cutting/infrastructure_parser.py` | YAML "database" read/write |
| `domain/test_infrastructure.py` | Infrastructure operations (setup/build/teardown) |
| `domain/test_container.py` | Container operations (start/stop/restart/destroy) |

### Frontend (React/TypeScript)
| File | Role |
|:-----|:-----|
| `App.tsx` | Root component — all handlers and state |
| `components/EnvironmentsTable.tsx` | `Environment` and `MoodleContainer` type definitions + table |
| `components/CreateEnvironmentModal.tsx` | Create form |
| `hooks/useAuth.ts` | Mock authentication |
| `hooks/useAuditLog.ts` | Mock audit log |
| `hooks/useSystemMetrics.ts` | Mock metrics |
| `types/user.ts` | User/Role types + mock data |
| `types/plugin.ts` | Plugin types + mock data |
