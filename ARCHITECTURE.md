# Architecture Diagram

```mermaid
graph TB
    subgraph Frontend["Frontend (React + Vite)"]
        UI[App.tsx]
        Composer[Composer.tsx]
        MessageCard[MessageCard.tsx]
        BreakdownTable[BreakdownTable.tsx]
        Charts[Charts.tsx]
        ComparisonTable[ComparisonTable.tsx]
        EvidencePanel[EvidencePanel.tsx]
        ConfidenceBadge[ConfidenceBadge.tsx]
        ScopePicker[ScopePicker.tsx]
        APIClient[api.ts]
    end

    subgraph API["FastAPI Layer (app/api.py)"]
        AskEndpoint["POST /ask"]
        AskSpecEndpoint["POST /ask_spec"]
        ExportEndpoint["POST /export"]
        HealthEndpoint["GET /health"]
        EfficiencyEndpoint["GET /efficiency"]
    end

    subgraph Planning["NLQ → QuerySpec Pipeline"]
        NLQDates["nlq_dates.py<br/>Deterministic date extraction"]
        Planner["planner.py<br/>LLM → QuerySpec + coercion"]
        StubPlanner["stub_planner.py<br/>Keyword fallback (dev only)"]
        SchemaContext["schema_context.py<br/>Schema description for prompt"]
        Spec["spec.py<br/>QuerySpec / DateRange / Filters"]
    end

    subgraph Validation["Guardrails"]
        Validator["validator.py<br/>Reject / clarify / repair"]
        Boundary["boundary.py<br/>Data-model boundary audit"]
        Scope["scope.py<br/>Row-level access (entity/account)"]
    end

    subgraph Execution["Deterministic SQL Engine"]
        Compiler["compiler.py<br/>QuerySpec → parameterised SQL"]
        Dates["dates.py<br/>Relative date resolution"]
        DB["db.py<br/>DuckDB (read-only)"]
    end

    subgraph PostProcessing["Post-Processing"]
        Narrator["narrator.py<br/>Results → plain English"]
        Anomaly["anomaly.py<br/>Robust z-score outlier detection"]
        Confidence["confidence.py<br/>Deterministic confidence badge"]
    end

    subgraph ETL["Load-Time ETL (scripts/)"]
        LoadData["load_data.py"]
        Enrich["enrich.py<br/>Counterparty parsing + categorisation"]
        Crypto["crypto.py<br/>AES-256 decrypt + surrogate keys"]
        DataDict["data_dictionary.py<br/>Schema from DATA_DICTIONARY.md"]
    end

    subgraph ExternalModel["LLM Provider (app/llm.py)"]
        LLM["Ollama / Gemini / Hosted API<br/>config/models.yaml"]
    end

    subgraph Storage["Data Layer"]
        DuckDB[(finance.duckdb<br/>txn_enriched view)]
        SemanticLayer["semantic_layer.yaml"]
    end

    %% Frontend → API
    APIClient -->|HTTP| AskEndpoint
    APIClient -->|HTTP| AskSpecEndpoint
    APIClient -->|HTTP| ExportEndpoint
    APIClient -->|HTTP| HealthEndpoint

    %% API → Planning
    AskEndpoint --> NLQDates
    NLQDates -->|DateRange| Planner
    Planner --> SchemaContext
    Planner -->|chat_json| LLM
    Planner -->|QuerySpec| Spec
    AskEndpoint -.->|STUB mode| StubPlanner

    %% API → Validation → Execution
    AskEndpoint --> Validator
    Validator --> Compiler
    Compiler --> Dates
    Compiler --> DB
    Scope -.->|WHERE predicate| Compiler
    DB --> DuckDB
    Compiler --> SemanticLayer

    %% API → Post-Processing
    AskEndpoint --> Narrator
    Narrator -->|narrate| LLM
    AskEndpoint --> Anomaly
    AskEndpoint --> Confidence

    %% Boundary enforcement
    Boundary -.->|audit trail| LLM

    %% ETL → Storage
    LoadData --> Enrich
    LoadData --> Crypto
    LoadData --> DataDict
    LoadData --> DuckDB

    %% Styling
    classDef frontend fill:#4FC3F7,stroke:#0288D1,color:#000
    classDef api fill:#81C784,stroke:#388E3C,color:#000
    classDef planning fill:#FFB74D,stroke:#F57C00,color:#000
    classDef validation fill:#E57373,stroke:#D32F2F,color:#fff
    classDef execution fill:#9575CD,stroke:#512DA8,color:#fff
    classDef postproc fill:#4DB6AC,stroke:#00796B,color:#000
    classDef etl fill:#A1887F,stroke:#5D4037,color:#fff
    classDef external fill:#F06292,stroke:#C2185B,color:#fff
    classDef storage fill:#FFD54F,stroke:#FFA000,color:#000

    class UI,Composer,MessageCard,BreakdownTable,Charts,ComparisonTable,EvidencePanel,ConfidenceBadge,ScopePicker,APIClient frontend
    class AskEndpoint,AskSpecEndpoint,ExportEndpoint,HealthEndpoint,EfficiencyEndpoint api
    class NLQDates,Planner,StubPlanner,SchemaContext,Spec planning
    class Validator,Boundary,Scope validation
    class Compiler,Dates,DB execution
    class Narrator,Anomaly,Confidence postproc
    class LoadData,Enrich,Crypto,DataDict etl
    class LLM external
    class DuckDB,SemanticLayer storage
```

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant API as FastAPI
    participant NLQ as nlq_dates
    participant Plan as Planner
    participant LLM
    participant Val as Validator
    participant Comp as Compiler
    participant Duck as DuckDB
    participant Narr as Narrator
    participant Anom as Anomaly
    participant Conf as Confidence

    User->>Frontend: "How much did I spend last month?"
    Frontend->>API: POST /ask {question}

    API->>NLQ: extract dates deterministically
    NLQ-->>API: DateRange(relative, month, offset=-1)

    API->>Plan: plan_with_confidence(question)
    Plan->>LLM: chat_json(system_prompt, question)
    LLM-->>Plan: {dataset, metric, filters, group_by}
    Plan->>Plan: coerce() — fix small-model mistakes
    Plan-->>API: PlanResult(QuerySpec, confidence)

    API->>Val: validate(spec)
    Val->>Duck: check counterparty/category exist
    Val-->>API: Verdict(ok, repaired spec)

    API->>Comp: compile_sql(spec, anchor_date)
    Comp-->>API: parameterised SQL + params

    API->>Duck: run(sql, params)
    Duck-->>API: DataFrame (breakdown)

    API->>Comp: compile_evidence_sql(spec)
    API->>Duck: run(evidence_sql)
    Duck-->>API: DataFrame (evidence rows)

    API->>Narr: narrate(question, df, spec, window)
    Narr->>LLM: describe results in English
    LLM-->>Narr: narrative text
    Narr->>Narr: numeric_guard — verify no hallucinated numbers
    Narr-->>API: answer text

    API->>Anom: compile_anomaly_sql → run → from_scan
    Anom-->>API: anomaly flags

    API->>Conf: assess(spec, row_count, warnings)
    Conf-->>API: Assessment(level, reasons)

    API-->>Frontend: Answer JSON
    Frontend-->>User: Narration + breakdown + evidence + confidence badge
```

## Key Design Principles

| Principle | Implementation |
|---|---|
| **Model never sees data** | `boundary.py` audits every outbound call; model receives question + schema only |
| **Deterministic dates** | `nlq_dates.py` resolves "last month" before the LLM runs |
| **Coerce, then validate** | `planner.coerce()` fixes predictable small-model mistakes; `validator.py` checks against real data |
| **One repair, then refuse** | A second LLM failure becomes an honest refusal, never a guess |
| **Self-consistency confidence** | `plan_with_confidence` samples the planner N times; disagreement lowers the badge |
| **ETL, not per-query** | Counterparty parsing, categorisation, crypto, and anomaly stats run once at load time |
| **Semantic layer as contract** | `semantic_layer.yaml` is the single source of truth for datasets, metrics, dimensions |
