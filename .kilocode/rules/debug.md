# Smart Repo‑Aware Debug Prompt (Unified)

A complete, repo‑aware debugging workflow with runnable examples and operational guardrails. Use this to get minimal, correct fixes fast.

## Quick Start (Copy/paste skeleton)

```text
You are debugging THIS repository. Do NOT refactor broadly—land the minimal, safe fix. Preserve public contracts unless explicitly asked otherwise.

Context
- Repo root: [path]
- Stack: [language(s)/framework(s)/versions]; OS: [e.g., macOS 14.x]; Tooling: [pytest/jest/go test/etc.]
- Services/dependencies: [DB, queues, docker-compose profile]
- Recent changes: [link commit/PR or summary]

Problem Summary
- One-liner: [e.g., Crash when processing empty input]
- Severity/Impact: [P0/P1/P2/P3]

Reproduction
- Steps (copy-pasteable):
  1) [deps/install]
  2) [build/run/tests]
  3) [input/sample data]
- Seed/data: [paste minimal sample]
- Repro rate: [always/intermittent]

Expected vs Actual
- Expected: [...]
- Actual: [... + top/bottom 10 lines of stack/log]
- First bad version: [commit/tag/date or unknown]

Artifacts
- Key snippets (10–30 lines) with file paths:
  - `path/to/file1.ext`: [...]
  - `path/to/file2.ext` (caller/test): [...]
- Error/stack excerpt:
  ```
  [stack/log excerpt]
  ```

What’s Been Tried
- [hypothesis], result: [pass/fail/observed]
- [hypothesis], result: [pass/fail/observed]

Constraints & Guardrails
- Backward compatibility unless specified; keep error text stable.
- Minimal diff; tests required; no style churn or moving files.
- Performance budget: [e.g., O(n) ok; no extra network calls]
- Security/compliance constraints: [notes]

Deliverables (Output)
1) Root cause (precise file/symbol refs)
2) Fix overview (why minimal/correct)
3) Patch (unified diff) for:
   - `path/to/fileA.ext`
   - `path/to/test_file.ext`
4) Tests (what/why they cover)
5) Verification steps (exact commands)
6) Risk & rollback plan

Acceptance
- Repro passes post-fix
- All tests pass: [command]
- No new warnings/errors in logs: [command]
```

## Short Variant (token‑light)

```text
Bug: [one-liner]. Stack: [lang/versions]. Env: [OS/tools].
Repro: [commands + sample input]. Expected vs Actual: [...].
Artifacts: [paths + stack excerpt]. Constraints: [compat, perf, minimal diff].
Output: root cause, minimal patch, tests, verification, risks.
```

## Repo Context (Auto‑Generated Fingerprint)

```markdown
# Repo Fingerprint
Generated: 2025-08-21T20:37:26-05:00
Repo root: /Users/justinadams/Downloads/Context-memory-main

## Recent commits
(none)

## Uncommitted changes
(clean or not a git repo)

## Last commit diff (stat)
(n/a)

## Top-level entries
- .env.development
- .env.example
- .env.production
- .github
- .gitignore
- .pre-commit-config.yaml
- .qoder
- CHANGELOG.md
- CONTRIBUTING.md
- DEPLOYMENT.md
- Dockerfile
- FRONTEND_REVIEW_REPORT.md
- README.md
- docker-compose.local.yml
- docker-compose.yml
- docs
- infra
- k8s
- pyproject.toml
- pytest.ini
- remote_key
- remote_key.pub
- repo-fingerprint.md
- requirements-dev.txt
- requirements.txt
- scripts
- server
- zen-mcp-server

## Stack indicators
- Node/TS: no
- Python pyproject: yes
- Python requirements: yes
- Go: no
- Java Maven: no
- Java Gradle: no
- Docker compose: yes

## Language footprint
2394 py
1156 pyc
 59 md
 50 typed
 44 txt
 42 dist-info/wheel
 42 dist-info/requested
 42 dist-info/record
 42 dist-info/metadata
 42 dist-info/installer
 19 dist-info/licenses/license
 16 yml
 16 pyi
 13 sample
 13 json
 11 tf
  9 sh
  9 html
  7 tpl
  6 so
  6 ps1
  6 exe
  6 dist-info/license
  4 yaml
  4 ini
  3 gitignore
  3 dist-info/licenses/copying
  3 bat
  2 toml
  2 pem

## Tool versions
- node: v24.5.0
- npm: 11.5.1
- pnpm: 10.14.0
- python3: 
- java: The operation couldn’t be completed. Unable to locate a Java Runtime.

## Auto-detected test commands
- pytest -q

## Flaky repro harness (choose one)
- Python: for i in {1..50}; do pytest -q -k '<pattern>' --maxfail=1 || { echo "Failed on iter $i"; break; }; done
- Node:   for i in {1..50}; do npx jest -i --runInBand -t '<pattern>' || break; done
- Go:     for i in {1..50}; do go test -run <TestName> -count=1 ./... || break; done
```

---

## Smart Context Loader (Repo Fingerprint)

```bash
set -euo pipefail
printf "Repo root: "; git rev-parse --show-toplevel 2>/dev/null || echo "(not a git repo)"
echo "\nRecent commits:"; git log --oneline -n 8 2>/dev/null || true

echo "\nChanged files (uncommitted):"; git status --porcelain 2>/dev/null || true

echo "\nRecent diff (last commit):"; git show --stat -n 1 2>/dev/null | sed -n '1,30p' || true

# Stack indicators
ls -1 | sed -n '1,200p' | awk '{print "- " $0}'
if [ -f package.json ]; then echo "\nNode/TS detected"; jq -r '.engines? // {} | to_entries[] | "- " + .key + ": " + .value' package.json 2>/dev/null || true; fi
[ -f pyproject.toml ] && echo "\nPython (pyproject) detected"
[ -f requirements.txt ] && echo "\nPython (requirements.txt) detected"
[ -f go.mod ] && echo "\nGo detected"
[ -f pom.xml ] && echo "\nMaven detected"
[ -f build.gradle ] || [ -f gradle.properties ] && echo "\nGradle detected"

# Monorepo hints
for d in apps packages services backend frontend modules; do [ -d "$d" ] && echo "monorepo dir: $d"; done

# Language footprint
if command -v git >/dev/null 2>&1; then git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -nr | head -n 30; else find . -type f | sed 's/.*\.//' | sort | uniq -c | sort -nr | head -n 30; fi

# Auto-detected test commands
if [ -f pytest.ini ] || grep -q "\[tool.pytest.ini_options\]" pyproject.toml 2>/dev/null; then echo "pytest -q"; fi
if [ -f package.json ] && jq -e '.scripts.test' package.json >/dev/null 2>&1; then echo "npm test -s (or: npx jest -i --runInBand --detectOpenHandles)"; fi
# Go
[ -f go.mod ] && echo "go test ./..."
# Java
[ -f pom.xml ] && echo "mvn -q test"; [ -f gradlew ] && echo "./gradlew test"
```

- Attach the exact command used + env versions (Node/Python, JAVA_HOME, GOPATH).

### Repo‑Specific Test/Run Commands (Python FastAPI + pytest)

```bash
# Local virtualenv & deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Local run (from repo root)
PYTHONPATH=server python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Local tests (from repo root; pytest.ini sets testpaths=server/tests)
PYTHONPATH=server python -m pytest -v
# or
PYTHONPATH=server pytest -q

# Docker Compose up (detached)
docker-compose -f docker-compose.local.yml -p context-memory-gateway up -d

# Compose test (ensure we run inside /app/server in the container)
docker-compose -f docker-compose.local.yml -p context-memory-gateway exec app sh -lc "cd /app/server && python -m pytest -v"

# Compose logs
docker-compose -f docker-compose.local.yml -p context-memory-gateway logs -f app
```

Notes
- The app import path is `app.main:app` in `server/app/main.py`.
- Compose service dependencies: Postgres (5432), Redis (6379), Qdrant (6333). App listens on 8000.

## Flaky/Intermittent Repro Harness

- Python
```bash
for i in {1..50}; do pytest -q -k '<test_pattern>' --maxfail=1 || { echo "Failed on iter $i"; break; }; done
```
- Node/Jest
```bash
for i in {1..50}; do npx jest -i --runInBand -t '<test_pattern>' || break; done
```
- Go
```bash
for i in {1..50}; do go test -run <TestName> -count=1 ./... || break; done
```

## Search Accelerator (Error/Stack/Regressions)

```bash
ERR="<paste exact error string or regex>"
if command -v rg >/dev/null 2>&1; then
  rg -nS "$ERR" --hidden -g '!node_modules' -g '!*dist*' -g '!*.min.*'
else
  grep -RIn --exclude-dir=node_modules --exclude-dir=.git "$ERR" .
fi

# First-bad-version (git bisect helper)
# git bisect start BAD_COMMIT GOOD_COMMIT
# git bisect run <your test command returning non-zero on failure>
```

---

## Core Analytical Framework

- **Phase 1: Comprehensive Understanding**
  - Map the architecture; identify all components
  - Trace data flow from entry points
  - Document dependencies, interfaces, integrations
  - Recognize patterns and architectural decisions
- **Phase 2: Sequential Deep Analysis**
  - Start at the first observable symptom
  - Follow execution paths forward
  - Track state changes per call
  - Validate assumptions with evidence
- **Phase 3: Pattern Recognition**
  - Identify recurring structures/behaviors
  - Spot deviations and edge cases
  - Detect timing dependencies/races
- **Phase 4: Root Cause Identification**
  - Systematic elimination to isolate issues
  - Verify hypotheses via deduction + evidence
  - Establish clear causation chains
- **Phase 5: Solution Architecture**
  - Design robust, minimal fixes
  - Align with existing patterns/constraints
  - Strengthen error handling/resilience
  - Optimize performance without obscurity

## Investigation Protocol

1) Establish expected behavior from specs
2) Map actual behavior via observation
3) Identify divergence points
4) Trace causation to origin
5) Validate findings via multiple paths
6) Design solutions that strengthen integrity

## Output Format Requirements

- **Problem Identification**: observed behavior, expected vs actual, impact
- **Root Cause Analysis**: step‑by‑step trace with evidence
- **Solution Proposal**: minimal, complete fix; side effects + mitigations
- **Verification Strategy**: tests, edge cases, performance implications

## Minimal‑Fix Guardrails (Do/Don’t)

- **Do**: small, test‑backed patches; keep signatures stable; comment subtle logic
- **Don’t**: move/rename files, reformat broadly, add deps unless essential

## Triage Matrix

- **P0**: crash/data‑loss/security; blocks release
- **P1**: major feature broken; workaround exists
- **P2**: minor bug/UX; batchable
- **P3**: nit/cleanup; only with nearby work

## Observability Quick Add

- **Logging**: structured logs at divergence points (inputs/ids/durations)
- **Tracing**: wrap async boundaries with correlation ids
- **Metrics**: count error types; histogram latencies on hot paths
- **Feature Flags**: gate risky changes for rollback

## Performance/Memory Smoke Tests

- Node
```bash
node --trace-gc --trace-gc-verbose app.js 2>&1 | tee gc.log
node --cpu-prof app.js; ls -1 *.cpuprofile | tail -n1
```
- Python
```bash
python -X tracemalloc -m pytest -q 2>&1 | tee mem.trace
python - <<'PY' 
import timeit
print(timeit.timeit('sum(range(10000))', number=1000))
PY
```
- Go
```bash
go test ./... -run=NONE -bench=. -benchmem
```

## LLM Execution Protocol (Repo‑Aware)

- **Read**: open diff/blame around failing lines; read caller/callee/utilities first
- **Prioritize**: start at first symptom; bias to last‑change footprint for regressions
- **Propose**: minimal patch; preserve contracts and error text; add/adjust tests
- **Verify**: exact test/runtime commands; show before/after evidence
- **Deliver**: unified diff, updated tests, risks + rollback, migration notes if any

## Output Contract (Enforced)

1) Root cause with file/symbol refs
2) Minimal patch (unified diff)
3) Tests added/updated
4) Verification steps and artifacts
5) Risk & rollback plan

---

## Debug Output Examples

### Example 1: Async State Corruption (Race Condition)

- **Issue**: Race condition in state updates
- **Root Cause**: Multiple async operations modify shared state without synchronization
- **Evidence Chain**:
  1. Thread A begins state update at t=1234567.123
  2. Thread B reads stale state at t=1234567.124
  3. Thread B computes new value based on stale state
  4. Thread A completes write at t=1234567.125
  5. Thread B overwrites with incorrect value at t=1234567.126
- **Fix**: optimistic locking/version checks; isolate critical sections; atomic updates
- **Verification**: stress test with 1000 concurrent ops; assert final state

### Example 2: Memory Leak Pattern (Event Listeners)

- **Issue**: Event listeners not removed, retained references
- **Memory Growth**: 45MB → 385MB after 1000 ops; ~15k orphaned listeners
- **Solution**: WeakMap storage; cleanup on destroy; AbortController cancellation
- **Impact**: −85% memory; GC 120ms → 15ms; responsiveness +40%

---

## Language‑Specific Deep Analysis Examples

### TypeScript/JavaScript — Async State Management Analysis

```ts
// Example: Async State Management Analysis
// Note: Stubs like fetchAndTransform() are illustrative.
type ProcessedData = any;

class DataProcessor {
  private cache = new Map<string, Promise<ProcessedData>>();
  private activeRequests = new Set<string>();

  async processData(id: string): Promise<ProcessedData> {
    if (this.cache.has(id)) return this.cache.get(id)!;

    if (this.activeRequests.has(id)) {
      await this.waitForCompletion(id);
      return this.cache.get(id)!;
    }

    this.activeRequests.add(id);

    try {
      const promise = this.fetchAndTransform(id)
        .then((data) => this.validate(data))
        .then((validated) => this.enhance(validated))
        .finally(() => {
          this.activeRequests.delete(id);
        });

      this.cache.set(id, promise);
      return await promise;
    } catch (err) {
      this.cache.delete(id);
      this.handleError(err, id);
      throw err;
    }
  }

  private async fetchAndTransform(_id: string): Promise<any> { return {}; }
  private validate<T>(x: T): T { return x; }
  private enhance<T>(x: T): T { return x; }
  private async waitForCompletion(_id: string): Promise<void> { /* no-op */ }
  private handleError(_err: unknown, _id: string): void { /* log */ }
}
```

### Python — Complex Data Pipeline Debugging

```python
from collections import defaultdict
from typing import List, Any

class PipelineError(Exception):
    pass

class DataPipeline:
    def __init__(self):
        self._processors: List[Any] = []
        self._cache = {}
        self._metrics = defaultdict(list)

    def process_stream(self, data_stream):
        """
        ANALYSIS FRAMEWORK:
        1. Track data transformations at each stage
        2. Monitor memory consumption patterns
        3. Identify bottlenecks in pipeline
        """
        for batch in self._batch_generator(data_stream):
            batch_id = self._generate_batch_id(batch)
            try:
                result = batch
                for processor in self._processors:
                    pre_state = self._capture_state(result)
                    result = processor.transform(result)
                    post_state = self._capture_state(result)
                    self._metrics[processor.name].append({
                        'input_size': len(pre_state),
                        'output_size': len(post_state),
                        'transformation_time': getattr(processor, 'last_duration', None)
                    })
                    if self._detect_memory_anomaly(pre_state, post_state):
                        self._investigate_memory_pattern(processor)
                self._update_cache(batch_id, result)
                yield result
            except Exception as e:
                self._rollback_state(batch_id)
                self._log_pipeline_state(e, batch_id)
                raise PipelineError(f"Failed at batch {batch_id}") from e

    def _batch_generator(self, stream, size: int = 1000):
        batch = []
        for item in stream:
            batch.append(item)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch

    # Stubs for completeness
    def _generate_batch_id(self, batch):
        return hash(tuple(batch))
    def _capture_state(self, value):
        return list(value) if isinstance(value, list) else [value]
    def _detect_memory_anomaly(self, _a, _b):
        return False
    def _investigate_memory_pattern(self, _processor):
        pass
    def _update_cache(self, key, value):
        self._cache[key] = value
    def _rollback_state(self, _key):
        pass
    def _log_pipeline_state(self, _e, _id):
        pass
```

### JavaScript — Event‑Driven Architecture Analysis

```js
class EventBus {
  constructor() {
    this.handlers = new Map();
  }

  async emit(event, data) {
    const eventHandlers = this.handlers.get(event) || [];
    const results = await Promise.allSettled(
      eventHandlers.map(async (handler) => {
        const startTime = performance.now();
        try {
          const context = this.createContext?.(event, data);
          const result = await Promise.race([
            handler.callback.call(handler.context, data, context),
            this.createTimeout?.(handler.timeout)
          ]);
          this.recordMetrics?.(handler, startTime, 'success');
          return result;
        } catch (error) {
          this.recordMetrics?.(handler, startTime, 'error');
          error.handlerInfo = { event, handlerId: handler.id, duration: performance.now() - startTime };
          if (handler.retryPolicy && this.retryWithBackoff) {
            return this.retryWithBackoff(handler, data, error);
          }
          throw error;
        }
      })
    );
    return this.aggregateResults ? this.aggregateResults(results, event) : results;
  }
}
```

### TypeScript — Complex Type System Analysis

```ts
type DeepPartial<T> = T extends object ? { [P in keyof T]?: DeepPartial<T[P]> } : T;

interface StateManager<T extends Record<string, any>> {
  state: T;
  history: Array<Partial<T>>;
  setState<K extends keyof T>(key: K, value: T[K] | ((prev: T[K]) => T[K])): void;
  getState<K extends keyof T>(key: K): T[K];
}

class ReactiveStore<T extends Record<string, any>> implements StateManager<T> {
  state: T;
  history: Array<Partial<T>> = [];
  private subscribers = new Map<keyof T, Set<Function>>();

  constructor(initialState: T) {
    this.state = new Proxy(initialState, {
      set: (target, property, value) => {
        if (property in target) {
          const oldValue = (target as any)[property];
          if (this.hasChanged(oldValue, value)) {
            this.history.push({ [property as any]: oldValue } as Partial<T>);
            (target as any)[property] = value;
            this.notifySubscribers(property as keyof T, value, oldValue);
          }
        }
        return true;
      },
      get: (target, property) => {
        this.trackAccess(property as keyof T);
        return (target as any)[property];
      }
    });
  }

  setState<K extends keyof T>(key: K, value: T[K] | ((prev: T[K]) => T[K])): void {
    const newValue = typeof value === 'function' ? (value as any)(this.state[key]) : value;
    this.validateType(key, newValue);
    (this.state as any)[key] = newValue;
  }

  private hasChanged(a: any, b: any) { return a !== b; }
  private notifySubscribers(_k: keyof T, _v: any, _o: any) {}
  private trackAccess(_k: keyof T) {}
  private validateType(_k: keyof T, _v: any): _v is T[keyof T] { return true; }
}
```

### Python — Decorator/Concurrency Debugging

```python
import functools
import inspect
import time
import asyncio
import threading
import contextvars
import contextlib
from collections import defaultdict, Counter
from typing import Any, Callable, TypeVar, List

T = TypeVar('T')

class DebugMeta(type):
    def __new__(mcs, name, bases, namespace):
        for attr_name, attr_value in list(namespace.items()):
            if callable(attr_value) and not attr_name.startswith('_'):
                namespace[attr_name] = mcs._instrument_method(attr_value, attr_name)
        cls = super().__new__(mcs, name, bases, namespace)
        cls._debug_metrics = {}
        cls._call_graph = defaultdict(list)
        return cls

    @staticmethod
    def _instrument_method(method: Callable, method_name: str) -> Callable:
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            call_signature = inspect.signature(method)
            bound_args = call_signature.bind(self, *args, **kwargs)
            bound_args.apply_defaults()
            context = {
                'method': method_name,
                'args': bound_args.arguments,
            }
            try:
                start_time = time.perf_counter()
                result = method(self, *args, **kwargs)
                duration = time.perf_counter() - start_time
                self._record_success(context, result, duration)
                return result
            except Exception as e:
                self._record_failure(context, e)
                raise
        return wrapper

class ConcurrentProcessor(metaclass=DebugMeta):
    def __init__(self):
        self._lock = threading.RLock()
        self._data = {}
        self._futures = {}

    async def process_concurrent(self, items: List[Any]) -> List[Any]:
        semaphore = asyncio.Semaphore(10)

        async def process_with_limit(item):
            async with semaphore:
                context_var = contextvars.ContextVar('item_id')
                token = context_var.set(id(item))
                try:
                    async with self._get_processor(item) as processor:
                        result = await processor.process(item)
                        self._correlate_result(item, result)
                        return result
                finally:
                    context_var.reset(token)

        tasks = [asyncio.create_task(process_with_limit(item)) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._filter_results(results, items)

    def _filter_results(self, results: List[Any], items: List[Any]) -> List[Any]:
        valid_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                self._log_error(f"Failed processing item {items[idx]}: {result}")
                valid_results.append(self._get_fallback_value(items[idx]))
            else:
                valid_results.append(result)
        return valid_results

    @contextlib.asynccontextmanager
    async def _get_processor(self, item):
        processor = None
        try:
            processor = await self._acquire_from_pool()
            processor.configure(item)
            yield processor
        finally:
            if processor:
                await self._release_to_pool(processor)

    async def _acquire_from_pool(self):
        class P:
            last_duration = 0.0
            name = 'proc'
            async def process(self, x):
                await asyncio.sleep(0)
                return x
            def configure(self, _):
                pass
        return P()
    async def _release_to_pool(self, _):
        pass
    def _correlate_result(self, _i, _r):
        pass
    def _log_error(self, _m: str):
        pass
    def _get_fallback_value(self, _i: Any):
        return None
    def _record_success(self, _c, _r, _d):
        pass
    def _record_failure(self, _c, _e):
        pass
```

---

## Advanced Debugging Techniques

### TypeScript — Performance Bottleneck Identification

```ts
interface PerformanceMetric {
  name: string;
  duration: number;
  memoryDelta: number;
  timestamp: number;
  context?: any;
  callStack?: string;
}

class PerformanceAnalyzer {
  private metrics: Map<string, PerformanceMetric[]> = new Map();
  private thresholds: Map<string, number> = new Map();

  async profileMethod<T>(name: string, fn: () => Promise<T>, context?: any): Promise<T> {
    const startMark = `${name}-start-${Date.now()}`;
    const endMark = `${name}-end-${Date.now()}`;
    performance.mark(startMark);
    const startMemory = this.captureMemoryUsage();
    try {
      const result = await fn();
      performance.mark(endMark);
      performance.measure(name, startMark, endMark);
      const measure: any = performance.getEntriesByName(name)[0];
      const endMemory = this.captureMemoryUsage();
      const metric: PerformanceMetric = {
        name,
        duration: measure?.duration ?? 0,
        memoryDelta: endMemory - startMemory,
        timestamp: Date.now(),
        context,
        callStack: new Error().stack
      };
      this.recordMetric(metric);
      this.checkThresholds(metric);
      return result;
    } catch (error) {
      this.recordError(name, error);
      throw error;
    } finally {
      performance.clearMarks(startMark);
      performance.clearMarks(endMark);
      performance.clearMeasures(name);
    }
  }

  private captureMemoryUsage(): number { return 0; }
  private recordMetric(_m: PerformanceMetric) {}
  private recordError(_n: string, _e: unknown) {}
  private calculateSeverity(d: number, t: number) { return d / t; }
  private detectNPlusOnePattern(_name: string) { return false; }

  private checkThresholds(metric: PerformanceMetric): void {
    const threshold = this.thresholds.get(metric.name);
    if (threshold && metric.duration > threshold) {
      this.reportBottleneck({
        metric,
        threshold,
        severity: this.calculateSeverity(metric.duration, threshold),
        recommendations: this.generateOptimizations(metric)
      });
    }
  }

  private reportBottleneck(_report: any) {}

  private generateOptimizations(metric: PerformanceMetric): string[] {
    const suggestions: string[] = [];
    if (metric.memoryDelta > 1024 * 1024) {
      suggestions.push('Consider object pooling');
      suggestions.push('Review data structure efficiency');
    }
    if (metric.duration > 100) {
      suggestions.push('Use async/parallel processing');
      suggestions.push('Implement caching');
    }
    if (this.detectNPlusOnePattern(metric.name)) {
      suggestions.push('Detected N+1 query pattern — batch operations');
    }
    return suggestions;
  }
}
```

### JavaScript — Memory Leak Detection (Reference Tracking)

```js
class MemoryLeakDetector {
  constructor() {
    this.references = new WeakMap();
  }
  track(object, context) {
    const metadata = {
      timestamp: Date.now(),
      context,
      stackTrace: new Error().stack,
      initialSize: this.calculateSize(object)
    };
    this.references.set(object, metadata);
    this.scheduleMemoryCheck(object);
  }
  scheduleMemoryCheck(object) {
    setTimeout(() => {
      if (this.references.has(object)) {
        const currentSize = this.calculateSize(object);
        const metadata = this.references.get(object);
        if (currentSize > metadata.initialSize * 1.5) {
          this.reportPotentialLeak(object, metadata, currentSize);
        }
        this.scheduleMemoryCheck(object);
      }
    }, 5000);
  }
  calculateSize(obj) {
    let size = 0;
    const seen = new WeakSet();
    function traverse(current) {
      if (current === null || current === undefined) return;
      if (typeof current !== 'object') return;
      if (seen.has(current)) return;
      seen.add(current);
      size += 8;
      for (const key in current) {
        size += key.length * 2;
        traverse(current[key]);
      }
    }
    traverse(obj);
    return size;
  }
  reportPotentialLeak(_obj, _meta, _size) {
    // Hook up your reporting
  }
}
```

### Python — Race Condition Detection (Heuristic)

```python
import time
import traceback
from collections import Counter

class RaceConditionDetector:
    def __init__(self):
        self._access_log = []
        self._potential_races = []

    def monitor_access(self, resource_id: str, access_type: str, thread_id: int):
        ts = time.perf_counter()
        rec = {
            'resource': resource_id,
            'type': access_type,  # 'read' or 'write'
            'thread': thread_id,
            'timestamp': ts,
            'stack': traceback.extract_stack()
        }
        self._access_log.append(rec)
        self._detect_concurrent_access(rec)

    def _detect_concurrent_access(self, current: dict):
        CONCURRENCY_WINDOW = 0.001
        for previous in reversed(self._access_log[-100:]):
            if previous['resource'] != current['resource']:
                continue
            if previous['thread'] == current['thread']:
                continue
            time_diff = current['timestamp'] - previous['timestamp']
            if time_diff < CONCURRENCY_WINDOW:
                if current['type'] == 'write' or previous['type'] == 'write':
                    self._potential_races.append({
                        'resource': current['resource'],
                        'threads': [previous['thread'], current['thread']],
                        'pattern': f"{previous['type']}-{current['type']}",
                        'time_diff': time_diff,
                        'stacks': [previous['stack'], current['stack']]
                    })
                    self._report_race_condition(current['resource'])

    def _report_race_condition(self, resource_id: str):
        races = [r for r in self._potential_races if r['resource'] == resource_id]
        if races:
            report = {
                'resource': resource_id,
                'occurrence_count': len(races),
                'patterns': Counter(r['pattern'] for r in races),
                'involved_threads': set(sum([r['threads'] for r in races], [])),
            }
            print(f"RACE CONDITION DETECTED: {report}")
```

---

## Repo‑Specific Tuning Template

Fill once; keep near the top of the doc for your repo.

- **Primary languages/frameworks**: [...]
- **Package managers**: npm/yarn/pnpm, pip/poetry/pipenv, go, maven/gradle
- **Test runners**: jest/mocha/vitest, pytest/nose, go test, junit
- **Launch commands**: [...]
- **Important env vars**: [...]
- **Services (docker/docker‑compose)**: [...]
- **Hotspot dirs/files**: [...]
- **Ignore dirs**: node_modules, dist, build, coverage, .git, vendor
- **Perf budgets**: [...]

## Token Budget & Reading Rules

- Read only files on the failing path first (caller/callee/utilities)
- Use blame/diff to limit scope; avoid repo‑wide scans without signal
- Quote exact lines/blocks; provide minimal, precise diffs
- Ask for clarifications when ambiguity remains

## PR Review Gates

- New/updated tests cover the fix and at least one adjacent edge case
- CI passes; no new lints; logging/metrics added if relevant
- Risk noted; rollback is trivial (feature flag or revert)
