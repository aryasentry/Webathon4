# SkillManager - Hackathon Hexagonal Architecture

This project uses a STRICT **Hexagonal Architecture** (Ports & Adapters) to allow 5 developers to work simultaneously without conflicts.

## 1. High-Level Architecture

We have two main components:
1. **Frontend (Next.js)**: Holds the UI AND the main business logic (Core Domain).
2. **AI Service (Python)**: A stateless microservice for heavy AI processing.

### Data Flow
```mermaid
graph TD
    User(User) -->|HTTP Request| API[Next.js API Route (Controller)]
    API -->|Calls| UseCase[Core Use Case (Application Layer)]
    UseCase -->|Validates| Domain[Domain Entities (Business Rules)]
    UseCase -->|Reads/Writes| RepoPort[<Interface> Repository Port]
    UseCase -->|Requests Analysis| AIPort[<Interface> AI Service Port]
    
    subgraph Infrastructure
        PostgresAdapter[Postgres Adapter] -->|Implements| RepoPort
        AIAdapter[AI Client Adapter] -->|Implements| AIPort
    end
    
    subgraph External
        PostgresAdapter -->|SQL| Database[(PostgreSQL)]
        AIAdapter -->|HTTP| PythonService[Python AI Backend]
    end
```

## 2. Strict Rules for Contributors

1. **NO FRAMEWORKS IN CORE**: 
   - `src/core/` must NEVER import `next`, `react`, `drizzle-orm`, or `axios`.
   - It should only use standard TypeScript/JavaScript objects.
   
2. **DEPENDENCY RULE**:
   - `Infrastructure` depends on `Core`. 
   - `Core` depends on NOTHING external.
   
3. **DATABASE ACCESS**:
   - Only the **Next.js Backend** connects to the Database.
   - The **Python AI Service** is stateless. It receives data, processes it, and returns it. It DOES NOT touch the DB.

4. **API CONTRACTS**:
   - Changes to the AI Service API must be reflected in `contracts/`.
   
## 3. Directory Structure

- `frontend/src/core`: **The Inner Hexagon**. Business logic & Interfaces.
- `frontend/src/infrastructure`: **The Outer Hexagon**. Database, API Clients, Config.
- `frontend/src/app/api`: **Entry Points**. HTTP Controllers that wire everything together.
- `backend/`: **AI Microservice**.

## 4. Developer Roles (Who Owns What?)

| Role | Focus Area | Files Owned |
| :--- | :--- | :--- |
| **Dev 1 (Lead)** | **Core Domain & Ports** | `src/core/domain`, `src/core/application/*.ports.ts` |
| **Dev 2 (Logic)** | **Use Cases** | `src/core/application/*.service.ts` |
| **Dev 3 (DB)** | **Postgres Adapter** | `src/infrastructure/adapters/postgres/*` |
| **Dev 4 (AI)** | **AI Adapter & Python** | `src/infrastructure/adapters/ai-client/*`, `backend/*` |
| **Dev 5 (UI)** | **Frontend & Controllers** | `src/app/dashboard`, `src/app/api/*` |

## 5. Setup

1. **Copy Env**: `cp .env.example .env`
2. **Install Deps**: `npm install` (Frontend) / `pip install -r backend/requirements.txt` (Backend)
3. **Run Dev**: 
   - Frontend: `npm run dev`
   - Backend: `cd backend && uvicorn main:app --reload`
