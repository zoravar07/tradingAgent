# Z Money — side-effect inventory

Generated 2026-09-10 from the source on disk (every `.py` under `core/`, `agents/`, `sources/`, `api/`, `scripts/`; tests and `ui/` excluded). Every public function and method is listed once, grouped by file. A function's class is the strongest effect reachable through the calls it makes.

| Class | Meaning | Count |
|---|---|---|
| A | PURE — no I/O of any kind; same inputs, same output (clock reads are flagged in Notes) | 90 |
| B | READS EXTERNAL — network or filesystem read; the service and cost are named | 15 |
| C | READS DB — SELECT only | 14 |
| D | WRITES DB — INSERT/UPDATE/DELETE; tables named | 14 |
| E | WRITES FILESYSTEM — config, cache, spend counters, or the SQLite file via DDL; paths named | 43 |
| | Total public functions and methods | 176 |

Conventions: `\|` inside a signature is a literal `|` in a type union. "Costs money" means Anthropic API tokens, plus $0.01 per server-side web search. FMP calls are free on this plan but count against a 250-per-day budget; yfinance, Wikipedia and NASDAQ Trader are free and unmetered.

## Answers to the four questions

### 1. Broker order submission

**Zero hits.** Searched every non-venv Python file (tests included) for `ib_insync`, `ibapi`, `ibkr`, `interactive brokers`, `placeOrder`, `place_order`, `submit_order`, `submitOrder`, `.submit(`, `alpaca`, `tradier`, `schwab`, `iserver`, and the bare word `submit`. Every match is prose: docstrings in `core/money.py`, `core/nav.py`, `core/portfolio.py` describing the IBKR Flex Query CSV import and the account-dashboard currency trap, and `agents/order_builder.py` line 9 quoting the spec: "There is no submit function in this codebase." No module imports a broker SDK, defines an order-submission call, or holds broker credentials. The only broker-adjacent code paths are `PortfolioService.import_flex_csv` (reads a CSV the user exported) and `PortfolioService.mark_filled` (the user telling the app about a fill they made by hand).

### 2. Purity of `core/scoring.py` and `core/risk_rules.py`

Every public function in both modules is class A. Verified from the source, not the docstrings:

- Imports: `core/scoring.py` imports only `dataclasses`; `core/risk_rules.py` imports `dataclasses`, `typing`, and the Pydantic config models from `core/config.py`. Neither imports `time`, `datetime`, `random`, `os`, `pathlib`, `requests`, `yaml` or any DB or SDK module, and a grep for clock, randomness, `open(`, `session`, and `print(` finds nothing but one docstring.
- No function mutates its inputs: `sorted()` returns new lists, `reasons` lists are built fresh per call, dicts are only read via `.get`.
- No design violations found. Two type-level notes that do not affect purity: `evaluate_held_position` emits `CONVICTION_FLOOR`, which is missing from the `ExitTriggerType` Literal, and `ConvictionResult.derivation` returns its `contributions` dict by reference rather than a copy.

### 3. Every function that can spend Anthropic credits

Exactly two functions make the API call; five more reach them.

| Function | File | How it spends | Call site |
|---|---|---|---|
| `LLMClient.call_structured` | core/llm.py | `client.messages.parse` — up to 3 billed calls per invocation (2 retries) | `agents/screener.py::run_stage2_batch`; `agents/research.py::run_research` |
| `LLMClient.call_text` | core/llm.py | `client.messages.create` with an optional `web_search` tool — up to 12 billed calls per invocation (3 retries × 4 pause_turn continuations), plus $0.01 per search | `agents/research.py::run_news_digest` |
| `run_stage2_batch` | agents/screener.py | one `call_structured` per chunk of 40 non-held names, model `screener.stage2.model` (Haiku 4.5), no web search | `core/orchestrator.py::_run_pipeline` |
| `run_research` | agents/research.py | one `call_structured` per name, model `research.model` (Sonnet 4.6), no web search | `run_research_batch` |
| `run_research_batch` | agents/research.py | `run_research` per context | `core/orchestrator.py::_run_pipeline` |
| `run_news_digest` | agents/research.py | one `call_text` per name on a cache miss, model `research.digest_model` (Haiku 4.5), `web_search` attached with `research.web_search_max_uses` searches | `core/orchestrator.py::_run_pipeline`, only when `research.web_search_enabled` |
| `_preflight` (private) | scripts/run_live_briefing.py | one raw `anthropic_client.messages.create` probe, `max_tokens=1`, about $0.0005; bypasses `LLMClient`, so it is NOT recorded in `data/llm_spend.json` | `main`, unless `--skip-preflight` |

Everything above is reached from `scripts/run_live_briefing.py::main` and nowhere else: no API route and no other module constructs an Anthropic client. `run_nightly` spends only through the `llm` argument it is given; the test suite passes fakes.

### 4. Writers of the `proposals` table

Two insert sites, both in `core/orchestrator.py::_run_pipeline` (reached through `run_nightly`), and both set `status="proposed"`:

| Site | Trigger | Status set |
|---|---|---|
| Held-position exits (`build_exit_order` result) | trailing stop, profit band, thesis decay, conviction floor | `"proposed"`, `trigger_type` = the primary trigger |
| New-candidate BUYs (`build_buy_order` result) | conviction-sized new position that passed risk sizing | `"proposed"`, `trigger_type` = None |

No code path anywhere UPDATEs or DELETEs a `proposals` row, and nothing ever writes `filled_at`, `fill_price`, or any status other than `"proposed"`. `PortfolioService.mark_filled` records a fill against `positions` only and never touches `proposals`. The `Proposal` model declares `filled_at` and `fill_price` columns, so the Orders screen renders them, but they are always NULL.

## Inventory by file

### core/orchestrator.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `build_universe` | `def build_universe(held_tickers: list[str], watchlist: list[str], scan_tickers: list[str]) -> list[str]` | `list[str]` — upper-cased, de-duplicated merge of the three lists, held first | A | Pure; order-preserving. |
| `rotating_slice` | `def rotating_slice(pool: list[str], batch_size: int, day_index: int) -> list[str]` | `list[str]` — up to `batch_size` tickers from `pool` chosen by `day_index` offset, or `[]` if pool empty / batch_size <= 0 | A | Pure, deterministic in `day_index`. |
| `resolve_universe` | `def resolve_universe(*, held_tickers: list[str], pool: list[str], config: UniverseConfig, as_of: dt.datetime) -> list[str]` | `list[str]` — result of `build_universe` with either the whole pool or a `rotating_slice` of it, plus `config.watchlist` and `config.extra_tickers` | A | Pure given `as_of` (caller supplies the clock). |
| `run_nightly` | `def run_nightly(*, session: Session, config: Config, gateway: MarketDataGateway, llm: LLMClient, portfolio: PortfolioService, inputs: NightlyRunInputs, news_cache: FileCache \| None = None) -> Briefing` | `Briefing` — the assembled (or blocked) briefing returned by `_run_pipeline`; re-raises on failure after marking the run failed | D | Writes tables: `runs` (INSERT then attribute mutation of `status`/`finished_at`/`error`), `briefings` (INSERT `BriefingRecord`), and via `_run_pipeline`: `risk_events` (INSERT, types PRICING_GATE_BLOCKED, DATA_FETCH_FAILED, NEWS_DIGEST_FAILED, RESEARCH_FAILED, KILL_SWITCH, SIZING_REJECTED), `candidates` (INSERT, then attribute mutation of `stage2_verdict`/`stage2_material`/`stage2_passed` on loaded rows), `research_outputs` (INSERT), `conviction` (INSERT), `nav_snapshots` (INSERT via `record_nav`), `proposals` (INSERT, `status="proposed"` for both exit orders and new BUY orders; no other status value is ever set in this file), `watchlist_items` (INSERT via `_build_watchlist`), `positions` (attribute mutation of `peak_price_since_activation` on loaded rows). Reads DB: `positions`, `position_imports` (via `portfolio.list_positions`/`check_drift`), `candidates`, `conviction`+`runs` (`latest_conviction`), `research_outputs`+`runs` (`holdings_due_for_refresh`), `nav_snapshots`. Reads external: gateway (`get_current_price`, `get_screener_input`, `get_research_context`, `get_sector`, `get_cluster`, optional `prefetch`) = yfinance + FMP network calls (FMP free tier, 250/day budget); `llm` via `run_stage2_batch`, `run_news_digest` (web search), `run_research_batch` = Anthropic API calls, cost real money; `news_cache: FileCache` read/write on filesystem inside `run_news_digest`. Also writes the filesystem transitively: yfinance/FMP/news caches under `data/*_cache`, `data/fmp_call_budget.json`, `data/llm_spend.json`. Non-deterministic (clock): `_utcnow()` for `finished_at` and `BriefingRecord.created_at`. Does NOT commit; only `session.flush()`. |
| `latest_conviction` | `def latest_conviction(session: Session, ticker: str, before_run_id: int) -> StaleConviction \| None` | `StaleConviction \| None` — score/run_id/started_at of the newest `conviction` row for the ticker with `run_id < before_run_id`, or None | C | SELECT on `conviction` JOIN `runs`. Called from `_run_pipeline` for held positions without a fresh memo. |
| `holdings_due_for_refresh` | `def holdings_due_for_refresh(session: Session, held_tickers: list[str], run_id: int, refresh_days: int) -> set[str]` | `set[str]` — never-researched held tickers plus the `ceil(len(held)/refresh_days)` with the oldest memo; all held if `refresh_days <= 0`; empty set if no holdings | C | SELECT on `research_outputs` JOIN `runs` (rows with `run_id < run_id`). Short-circuits without a query when `held_tickers` empty or `refresh_days <= 0`. |

Excluded as not public or auto-generated: `MarketDataGateway` (Protocol stubs), `NightlyRunInputs` and `StaleConviction` (dataclasses with no explicit methods), all `_`-prefixed helpers (`_stage1_gate_summary`, `_run_pipeline`, `_distance_to_stop_pct`, `_overnight_changes`, `_build_watchlist`, `_utcnow`).

### core/portfolio.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `ReconciliationItem.to_dict` | `def to_dict(self) -> dict` | `dict` — `{"ticker", "action", "detail"}` from the dataclass fields | A | Pure. |
| `ReconciliationResult.as_json` | `def as_json(self) -> str` | `str` — JSON array of `item.to_dict()` for each item | A | Pure. Stored into `position_imports.reconciliation_json` by `import_flex_csv`. |
| `ReconciliationResult.summary` | `def summary(self) -> dict` | `dict` — count of items per action string | A | Pure. |
| `parse_flex_csv` | `def parse_flex_csv(source: str \| IO[str]) -> list[ImportedPosition]` | `list[ImportedPosition]` — one row per non-zero-qty STK row with a resolved avg_cost | B | Reads from the passed file-like object if `source` has `.read()` (caller's file handle; no path opened here), otherwise parses the string in memory. No network, no money. Raises `ReconciliationError` on bad headers/values. |
| `parse_flex_cash_balance` | `def parse_flex_cash_balance(source: str \| IO[str]) -> Money \| None` | `Money \| None` — `usd(sum)` of USD CASH-row Position values, or None if no AssetClass/qty column or no parseable cash row | B | Same as above: reads the caller's file-like object if given; otherwise pure string parsing. No network, no money. |
| `PortfolioService.__init__` | `def __init__(self, session: Session, config: PortfolioConfig \| None = None)` | None — stores `session` and `config` (defaults to `PortfolioConfig()`) | A | Explicitly defined constructor on a regular class. |
| `PortfolioService.get_position` | `def get_position(self, ticker: str) -> Position \| None` | `Position \| None` — the `positions` row with matching upper-cased ticker | C | SELECT `positions`. |
| `PortfolioService.list_positions` | `def list_positions(self) -> list[Position]` | `list[Position]` — all `positions` rows ordered by ticker | C | SELECT `positions`. |
| `PortfolioService.last_import` | `def last_import(self) -> PositionImport \| None` | `PositionImport \| None` — newest `position_imports` row by `imported_at` | C | SELECT `position_imports`. |
| `PortfolioService.add_manual_position` | `def add_manual_position(self, ticker: str, qty: float, avg_cost: float, opened_at: dt.datetime \| None = None, conviction_at_entry: float \| None = None) -> Position` | `Position` — the newly added row with `source="manual"` | D | INSERT `positions` (session.add + flush). Reads `positions` first via `get_position`. Non-deterministic (clock) when `opened_at` is None. Raises `PortfolioError` on duplicate/invalid. |
| `PortfolioService.edit_manual_position` | `def edit_manual_position(self, position_id: int, **fields) -> Position` | `Position` — the loaded row after `setattr` of the allowed fields | D | UPDATE `positions` via attribute mutation on a `session.get` row, then flush. Allowed fields: qty, avg_cost, opened_at, conviction_at_entry, peak_price_since_activation. |
| `PortfolioService.remove_position` | `def remove_position(self, position_id: int) -> None` | `None` — nothing returned | D | DELETE `positions` (session.delete + flush). |
| `PortfolioService.mark_filled` | `def mark_filled(self, ticker: str, action: Literal["BUY", "SELL"], qty: float, fill_price: float, filled_at: dt.datetime \| None = None, conviction_at_entry: float \| None = None) -> Position \| None` | `Position \| None` — the resulting row; None when a SELL fully closes the position | D | `positions`: INSERT (BUY with no existing row, `source="fill"`), attribute mutation of `qty`/`avg_cost`/`last_verified_at` (BUY add-on or partial SELL), DELETE (SELL closing out). Reads `positions` via `get_position`. Non-deterministic (clock) when `filled_at` is None. Does not touch `position_imports` or `proposals`. |
| `PortfolioService.import_flex_csv` | `def import_flex_csv(self, source: str \| IO[str], filename: str) -> ReconciliationResult` | `ReconciliationResult` — the result of `reconcile` on the parsed CSV rows | D | INSERT `position_imports` (with `cash_usd` from `parse_flex_cash_balance`), plus every `positions` write `reconcile` makes. Reads the caller's file-like object if given (no path opened). Non-deterministic (clock) via `reconcile`. |
| `PortfolioService.latest_cash_balance` | `def latest_cash_balance(self) -> Money \| None` | `Money \| None` — `usd(last.cash_usd)` from the newest import, or None if no import / no cash value | C | SELECT `position_imports` via `last_import`. Used by the script to populate `NightlyRunInputs.cash`. |
| `PortfolioService.reconcile` | `def reconcile(self, imported: list[ImportedPosition], filename: str = "manual-reconcile", imported_at: dt.datetime \| None = None) -> ReconciliationResult` | `ReconciliationResult` — added/matched/updated/removed items for every imported and existing ticker | D | `positions`: INSERT (`source="import"`) for new tickers, attribute mutation of `last_verified_at` (matched) or `qty`/`avg_cost`/`last_verified_at` (updated), DELETE for tickers absent from the import. Reads `positions` via `list_positions`. Does NOT write `position_imports`. Non-deterministic (clock) when `imported_at` is None. |
| `PortfolioService.check_drift` | `def check_drift(self, as_of: dt.datetime \| None = None) -> DriftStatus` | `DriftStatus` — stale flag, last import time, days since, threshold | C | SELECT `position_imports` (and `positions` when no import exists). Non-deterministic (clock) when `as_of` is None. |

Excluded: `ReconciliationError`, `PortfolioError` (exception classes, no methods), `ImportedPosition`, `DriftStatus` (dataclasses, no explicit methods), `_normalize_headers`, `_find_column`, `_costs_match`, `PortfolioService._validate_qty`, `_utcnow`.

### core/nav.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `compute_nav` | `def compute_nav(position_values: Sequence[Money], cash: Money) -> Money` | `Money` — `cash` plus every position value via `Money.__add__` | A | Pure; raises (from `Money.__add__`) on currency mismatch or a non-Money input. |
| `record_nav` | `def record_nav(session: Session, run_id: int, nav: Money, as_of: dt.datetime) -> NavStatus` | `NavStatus` — nav, peak_nav, drawdown_pct, daily_loss_pct derived against the latest prior snapshot (all zeros/peak=nav on first run) | D | INSERT `nav_snapshots` (session.add + flush). Reads `nav_snapshots` via `_latest_snapshot`. Note: the comparison baseline is the single most recent snapshot regardless of run status, so a failed/blocked run that reached this point still sets the baseline. |

Excluded: `NavStatus` (dataclass, no methods), `_latest_snapshot`.

### core/db.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `make_engine` | `def make_engine(db_path: str \| Path = DEFAULT_DB_PATH)` | (no annotation) — a SQLAlchemy `Engine` from `create_engine(url, future=True)` | E | `db_path.parent.mkdir(parents=True, exist_ok=True)` creates the parent directory of `db_path` unless the path is `:memory:`; default path is `<repo>/data/z_money.db`, so it creates `<repo>/data/`. Does not itself open or create the SQLite file (that happens on first connection). |
| `init_db` | `def init_db(engine) -> None` | `None` — nothing returned | E | `Base.metadata.create_all(engine)` executes CREATE TABLE IF NOT EXISTS for every model in `core/models.py` (positions, position_imports, runs, candidates, research_outputs, conviction, proposals, watchlist_items, risk_events, config_versions, nav_snapshots, briefings, journal_entries) — schema DDL, and for a file-backed engine this creates/writes the SQLite file at the engine's path. Classified E as the strongest effect (writes the DB file on disk); no row-level DML. |
| `make_session_factory` | `def make_session_factory(engine) -> sessionmaker[Session]` | `sessionmaker[Session]` — bound to `engine`, `future=True`, `expire_on_commit=False` | A | Pure object construction; no connection opened. |
| `session_scope` | `def session_scope(session_factory: sessionmaker[Session])` | (no annotation) — a context manager yielding a `Session`; commits on clean exit, rolls back on exception, always closes | D | `session.commit()` is the only place in these five files that commits; every flush made by the orchestrator/portfolio/nav code inside the `with` block becomes durable here. Tables written depend on the caller. Rolls back on any exception. |

### core/briefing_persistence.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `serialize_briefing` | `def serialize_briefing(briefing) -> str` | `str` — `json.dumps(dataclasses.asdict(briefing))` with datetimes rendered via `isoformat()` | A | Pure. Raises `TypeError` for any non-datetime non-JSON-native value inside the briefing. Called by `run_nightly` to fill `briefings.briefing_json`. |
| `deserialize_briefing` | `def deserialize_briefing(raw_json: str) -> dict` | `dict` — `json.loads(raw_json)`, not reconstructed into dataclasses | A | Pure. |

Excluded: `_json_default`.

### core/briefing.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `sort_actions_by_conviction` | `def sort_actions_by_conviction(items: list[ActionItem]) -> list[ActionItem]` | `list[ActionItem]` — a new list sorted by `item.order.conviction` descending (`sorted()`, input not mutated) | A | Deterministic. Only the `OrderProposal.conviction` attribute is read. |
| `sort_book_by_attention` | `def sort_book_by_attention(entries: list[BookEntry]) -> list[BookEntry]` | `list[BookEntry]` — a new list sorted by key `(not has_exit_trigger, -(conviction_at_entry - conviction_now), -weight_pct)`; decay is 0.0 when either conviction is None | A | Deterministic. Inner helper `decay_pts` is a closure. Input list not mutated. |
| `assemble_briefing` | `def assemble_briefing(*, generated_at: dt.datetime, actions_today: list[ActionItem], watching: list[WatchlistItem], overnight_changes: list[OvernightChange], book: list[BookEntry], portfolio_health: PortfolioHealth, drift: DriftStatus \| None, unresearched_holdings: list[UnresearchedHolding] \| None = None) -> Briefing` | `Briefing` — a new Briefing with actions sorted by conviction, book sorted by attention, unresearched_holdings sorted by ticker, `drift_warning` set only when `drift is not None and drift.stale`, `blocked=None` | A | Deterministic. `generated_at` is taken from the caller; no clock read here. `watching`/`overnight_changes` passed through by reference, unsorted. |
| `assemble_blocked_briefing` | `def assemble_blocked_briefing(generated_at: dt.datetime, unpriced: list[UnpricedPosition], tolerance: int, total_held: int) -> Briefing` | `Briefing` — all sections empty, `portfolio_health=PortfolioHealth()` defaults, `blocked=BlockedStatus(reason=<formatted count string>, unpriced_positions=unpriced)` | A | Deterministic. `unpriced` list stored by reference inside `BlockedStatus`, not copied. |
| `render_briefing_text` | `def render_briefing_text(briefing: Briefing) -> str` | `str` — newline-joined plain-text rendering of the five sections; returns early after the "RUN BLOCKED" block when `briefing.blocked` is set | A | Deterministic. Formats `briefing.generated_at` but does not read the clock. No I/O (no print). |

### core/cache.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `CacheEntry.is_fresh` | `def is_fresh(self, now: float \| None = None) -> bool` | `bool` — `(now - stored_at) < ttl_seconds`, with `now` defaulting to `time.time()` | A | non-deterministic (clock) when `now` is None; deterministic when `now` is supplied. |
| `FileCache.get` | `def get(self, key: str, now: float \| None = None) -> Any \| None` | `Any \| None` — the cached `value` if the JSON file for `sha256(key)` exists and the entry is fresh, else `None` | B | Reads filesystem: `<root>/<sha256(key)>.json`. Free. non-deterministic (clock) via `is_fresh` when `now` is None. Raises `KeyError`/`TypeError` on a malformed JSON payload, not caught. |
| `FileCache.peek` | `def peek(self, key: str) -> tuple[Any, float] \| None` | `tuple[Any, float] \| None` — `(raw["value"], float(raw["stored_at"]))` regardless of TTL, or `None` if the file does not exist | B | Reads filesystem: `<root>/<sha256(key)>.json`. Free. Deterministic given file contents (no clock). |
| `FileCache.set` | `def set(self, key: str, value: Any, ttl_seconds: float) -> None` | `None` — nothing returned | E | Writes filesystem: `<root>/<sha256(key)>.json` via `write_text(json.dumps(CacheEntry.__dict__))`. non-deterministic (clock): `stored_at=time.time()`. `json.dumps` raises `TypeError` for non-JSON-serialisable values. |
| `FileCache.get_or_fetch` | `def get_or_fetch(self, key: str, ttl_seconds: float, fetch_fn: Callable[[], Any]) -> tuple[Any, bool]` | `tuple[Any, bool]` — `(cached_value, True)` on a fresh hit; otherwise `(fetch_fn(), False)` after storing it | E | Reads then writes `<root>/<sha256(key)>.json` (via `get` then `set`). Calls the caller-supplied `fetch_fn`, whose effects (typically a network call that may cost money or FMP daily budget) are the caller's; this function itself makes no network call. A `fetch_fn` returning `None` is stored but every later `get` treats it as a miss. |
| `DailyCallBudget.used_today` | `def used_today(self) -> int` | `int` — `self._read().get(today_key, 0)` | B | Reads filesystem: `self.path` JSON (returns `{}` if absent). Free. non-deterministic (clock) by default: `today_fn` defaults to `time.strftime("%Y-%m-%d", time.gmtime())`; injectable via constructor. |
| `DailyCallBudget.remaining_today` | `def remaining_today(self) -> int` | `int` — `max(0, daily_limit - used_today())` | B | Reads filesystem: `self.path` (via `used_today`). Free. non-deterministic (clock) unless `today_fn` injected. |
| `DailyCallBudget.check_and_increment` | `def check_and_increment(self, n: int = 1) -> None` | `None` — nothing returned; raises `BudgetExceeded` when `used + n > daily_limit` | E | Reads then writes filesystem: `self.path` JSON, written as `{today: used+n}` only (prior days dropped); `self.path.parent` is mkdir-ed on write. non-deterministic (clock) unless `today_fn` injected. Not atomic: read-check-write race if two processes run concurrently. |

### core/config.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `load_config` | `def load_config(path: str \| Path) -> Config` | `Config` — `Config.model_validate(yaml.safe_load(path.read_text()) or {})` | B | Reads filesystem: the YAML file at `path`. Free. Raises `FileNotFoundError` if missing, `yaml.YAMLError` if malformed, `pydantic.ValidationError` on schema failure. `Config` has `extra="allow"` so unmodeled sections pass through unvalidated. No Pydantic validators are defined in this module; all config classes are field-only models with no explicit methods. |

### core/config_writer.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `read_raw` | `def read_raw(path: str \| Path) -> Any` | `Any` — a ruamel `CommentedMap` (or whatever the YAML root is) from `_yaml.load(f)` | B | Reads filesystem: `open(path)` and ruamel round-trip load. Free. Uses the module-level shared `_yaml` `YAML()` instance. |
| `write_raw` | `def write_raw(path: str \| Path, raw: Any) -> None` | `None` — nothing returned | E | Writes filesystem: `open(path, "w")` then `_yaml.dump(raw, f)`. Truncates the target before dumping; not atomic (no temp-file rename), so a dump failure leaves a partial file. |
| `dump_to_string` | `def dump_to_string(raw: Any) -> str` | `str` — `_yaml.dump(raw, StringIO()).getvalue()` | A | Deterministic given `raw`. |
| `editable_snapshot` | `def editable_snapshot(raw: Any) -> dict[str, Any]` | `dict[str, Any]` — a fresh nested plain dict with the current value of each `EDITABLE_FIELDS` path from `raw`, falling back to `default_values()` on `KeyError`/`TypeError` | A | Deterministic. Does not mutate `raw`. |
| `default_values` | `def default_values() -> dict[str, Any]` | `dict[str, Any]` — nested dict of Pydantic defaults for `portfolio`, `risk`, `screener.stage1`, `budget`, `schedule` fields | A | Deterministic. Must be kept in sync with `EDITABLE_FIELDS` by hand. |
| `apply_updates` | `def apply_updates(raw: Any, updates: dict[str, Any]) -> None` | `None` — nothing returned | A | Deterministic, but **mutates `raw` in place** (documented, intentional: sets each editable path present in `updates`; creates intermediate `{}` dicts if a section key is missing). No I/O itself; persistence happens only if the caller then calls `write_raw`. Does no validation of the incoming values. |

### core/llm.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `estimate_cost_usd` | `def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int, web_search_requests: int = 0) -> float` | `float` — `(in/1M)*input_rate + (out/1M)*output_rate + web_search_requests*0.01`; raises `UnknownModelPricing` if `model` not in `PRICING` | A | Deterministic. `PRICING` covers `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-opus-5`; any other model id raises. |
| `web_search_tool` | `def web_search_tool(model: str, max_uses: int) -> dict` | `dict` — `{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}` | A | Deterministic. The `model` parameter is unused in the body (kept so callers can pass it; the basic variant is used for every model by measured decision). |
| `MonthlySpendTracker.spent_this_month` | `def spent_this_month(self) -> float` | `float` — `self._read().get(month_key, 0.0)` | B | Reads filesystem: `self.path` JSON spend file (returns `{}` if absent). Free. non-deterministic (clock) by default: `month_fn` defaults to `time.strftime("%Y-%m", time.gmtime())`; injectable. |
| `MonthlySpendTracker.remaining_this_month` | `def remaining_this_month(self) -> float` | `float` — `max(0.0, monthly_cap_usd - spent_this_month())` | B | Reads filesystem: `self.path`. Free. non-deterministic (clock) unless `month_fn` injected. |
| `MonthlySpendTracker.is_exceeded` | `def is_exceeded(self) -> bool` | `bool` — `spent_this_month() >= monthly_cap_usd` | B | Reads filesystem: `self.path`. Free. non-deterministic (clock) unless injected. |
| `MonthlySpendTracker.record` | `def record(self, cost_usd: float) -> None` | `None` — nothing returned | E | Reads then writes filesystem: `self.path` JSON, rewritten as `{month: previous + cost_usd}` only (prior months dropped); `self.path.parent` mkdir-ed. non-deterministic (clock) unless injected. Unconditional (no cap check). Not atomic across processes. |
| `LLMClient.call_structured` | `def call_structured(self, model: str, system: str, user_message: str, output_model: type[T], max_tokens: int = 4096, max_retries: int = 2) -> StructuredResult` | `StructuredResult` — `(parsed=response.parsed_output, usage=UsageRecord(...), attempts=n)` on the first attempt whose response has a non-None `parsed_output`; raises the last captured exception or `LLMError` after `max_retries + 1` attempts; raises `MonthlyBudgetExceeded` pre-flight | E | **Network: Anthropic API via `self.client.messages.parse(...)`, COSTS MONEY** (up to `max_retries + 1 = 3` billed calls per invocation). **Writes filesystem: the spend file at `self.budget.path` via `MonthlySpendTracker.record(cost)`** after every successful API response, including responses with no `parsed_output`. Reads the spend file first via `_check_budget`. Exceptions from `parse` are swallowed and retried; a failed (exception) attempt records no spend. Budget is checked once at entry, not per retry. |
| `LLMClient.call_text` | `def call_text(self, model: str, system: str, user_message: str, tools: list[dict] \| None = None, max_tokens: int = 4096, max_retries: int = 2, max_continuations: int = 3) -> TextResult` | `TextResult` — `(text=concatenated text blocks, source_urls=de-duplicated citation URLs in first-seen order, usage=UsageRecord(... web_search_requests=total), attempts=n)` on the first attempt with non-blank text; raises last error or `LLMError` otherwise; raises `MonthlyBudgetExceeded` pre-flight | E | **Network: Anthropic API via `self.client.messages.create(**kwargs)`, COSTS MONEY** (tokens plus $0.01 per server web search); up to `(max_retries+1) * (max_continuations+1) = 12` billed calls per invocation when every attempt hits `pause_turn`. **Writes filesystem: spend file at `self.budget.path` via `MonthlySpendTracker.record`** once per attempt, both on success and on exception (partial usage is recorded if any tokens/searches accumulated before the exception). Reads spend file at entry via `_check_budget`. `pause_turn` continuation re-sends `response.content` verbatim as an assistant message. Protocol classes (excluded from rows): `AnthropicMessages.parse(*, model, max_tokens, system, messages, output_format)`, `AnthropicMessages.create(*, model, max_tokens, system, messages)`, `AnthropicClient.messages`. Note `call_text` passes `tools=` to `create`, which the Protocol signature does not declare. |

### core/models.py

No public functions or methods. The module defines only SQLAlchemy declarative classes with `mapped_column` declarations: `Base(DeclarativeBase)`, `Position` (`positions`), `PositionImport` (`position_imports`), `Run` (`runs`), `Candidate` (`candidates`), `ResearchOutput` (`research_outputs`), `Conviction` (`conviction`), `Proposal` (`proposals`), `WatchlistItem` (`watchlist_items`), `RiskEvent` (`risk_events`), `ConfigVersion` (`config_versions`), `NavSnapshot` (`nav_snapshots`), `BriefingRecord` (`briefings`), `JournalEntry` (`journal_entries`). No `@property`, no `__init__`, no validators, no hybrid properties. Importing the module has no I/O effect beyond registering metadata on `Base.metadata`.

### core/money.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `usd` | `def usd(amount: float) -> Money` | `Money` — `Money(amount, "USD")` | A | Deterministic. All other `Money` methods are dunders (`__post_init__`, `__add__`, `__radd__`, `__sub__`, `__mul__`, `__rmul__`, `__truediv__`, `__neg__`, `__lt__`, `__le__`, `__gt__`, `__ge__`, `__eq__`, `__repr__`) plus private `_check`; all are pure and deterministic, raising `CurrencyMismatch`/`TypeError` on mixed-currency or non-Money operands. |

### core/risk_rules.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `lerp_by_conviction` | `def lerp_by_conviction(score: float, at_0: float, at_100: float) -> float` | `float` — `at_0 + (clamp(score,0,100)/100) * (at_100 - at_0)` | A | pure: yes. No mutation, no clock, no randomness. |
| `update_peak_price` | `def update_peak_price(current_peak: float \| None, current_price: float) -> float` | `float` — `current_price` if `current_peak` is None, else `max(current_peak, current_price)` | A | pure: yes. |
| `check_kill_switches` | `def check_kill_switches(daily_loss_pct: float, drawdown_pct: float, config: RiskConfig) -> KillSwitchStatus` | `KillSwitchStatus` — `triggered=bool(reasons)` with a formatted reason string per breached cap (`daily_loss_pct >= max_daily_loss_pct`, `drawdown_pct >= max_drawdown_pct`) | A | pure: yes. Builds a fresh `reasons` list; `config` only read. |
| `volatility_size_multiplier` | `def volatility_size_multiplier(atr_pct_of_price: float \| None, config: RiskConfig) -> float` | `float` — `1.0` if ATR is None/<=0 or <= `reference_atr_pct_of_price`; else `max(min_volatility_size_multiplier, min(1.0, reference/atr))` | A | pure: yes. |
| `size_new_position` | `def size_new_position(conviction_score: float, atr_pct_of_price: float \| None, nav_usd: float, sector: str \| None, cluster: str \| None, current_sector_pct: dict[str, float], current_cluster_pct: dict[str, float], cash_available_usd: float, scaling: ConvictionScalingConfig, config: RiskConfig) -> SizingResult` | `SizingResult` — `approved=False, position_pct=0.0, position_usd=0.0` when the capped size falls below `min_order_value_usd`; otherwise `approved=True` with the pipeline-capped `pct`/`position_usd`, accumulated `reasons`, and the pre-cap `conviction_target_pct`/`volatility_multiplier` | A | pure: yes. `current_sector_pct`/`current_cluster_pct` only read via `.get`; new `reasons` list per call. |
| `enforce_daily_proposal_cap` | `def enforce_daily_proposal_cap(proposals: list[ScoredProposal], config: RiskConfig) -> list[ScoredProposal]` | `list[ScoredProposal]` — new list of the top `config.max_daily_proposals` by conviction descending | A | pure: yes. `sorted()` returns a new list; input not mutated. |
| `HeldPositionEvaluation.has_exit_signal` | `def has_exit_signal(self) -> bool` | `bool` — `bool(self.triggers)` | A | pure: yes. `@property`. |
| `HeldPositionEvaluation.primary_trigger` | `def primary_trigger(self) -> ExitTrigger \| None` | `ExitTrigger \| None` — `self.triggers[0]` or None | A | pure: yes. `@property`. Priority is the append order in `evaluate_held_position`: TRAILING_STOP, PROFIT_BAND, THESIS_DECAY, CONVICTION_FLOOR. |
| `trailing_stop_breached` | `def trailing_stop_breached(current_price: float, peak_price: float \| None, atr_14: float \| None, conviction_score: float, scaling: ConvictionScalingConfig) -> tuple[bool, dict]` | `tuple[bool, dict]` — `(False, {"atr_multiple", "reason": "insufficient data"})` when peak or ATR missing/<=0; else `(current_price <= peak - multiple*atr, {atr_multiple, peak_price, stop_price, current_price})` | A | pure: yes. |
| `profit_band_crossed` | `def profit_band_crossed(current_price: float, avg_cost: float, conviction_score: float, scaling: ConvictionScalingConfig) -> tuple[bool, dict]` | `tuple[bool, dict]` — `(False, {"threshold_pct", "reason": "no cost basis"})` when `avg_cost` is falsy; else `(gain_pct >= threshold, {threshold_pct, gain_pct})` | A | pure: yes. |
| `thesis_decay_triggered` | `def thesis_decay_triggered(conviction_now: float, conviction_at_entry: float \| None, config: RiskConfig) -> tuple[bool, dict]` | `tuple[bool, dict]` — `(False, {"reason": "no conviction_at_entry recorded"})` when no entry baseline; else `(drop >= thesis_decay_trigger_pts, {conviction_at_entry, conviction_now, drop_pts, threshold_pts})` | A | pure: yes. |
| `conviction_floor_triggered` | `def conviction_floor_triggered(conviction_now: float, config: RiskConfig) -> tuple[bool, dict]` | `tuple[bool, dict]` — `(conviction_now < min_hold_conviction, {conviction_now, min_hold_conviction})` | A | pure: yes. |
| `evaluate_held_position` | `def evaluate_held_position(ticker: str, current_price: float, avg_cost: float, peak_price: float \| None, atr_14: float \| None, conviction_now: float, conviction_at_entry: float \| None, scaling: ConvictionScalingConfig, config: RiskConfig, conviction_is_fresh: bool = True) -> HeldPositionEvaluation` | `HeldPositionEvaluation` — `ticker` plus a fresh `triggers` list containing an `ExitTrigger` for each of trailing stop, profit band, thesis decay that fired, and `CONVICTION_FLOOR` only when `conviction_is_fresh` | A | pure: yes. Emits `ExitTrigger(type="CONVICTION_FLOOR", ...)`, which is not a member of the `ExitTriggerType = Literal["TRAILING_STOP", "PROFIT_BAND", "THESIS_DECAY"]` annotation (type-checker mismatch, runtime fine). Module imports only `dataclasses`, `typing`, and `core.config`. |

### core/scoring.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `ConvictionResult.derivation` | `def derivation(self) -> dict` | `dict` — `{"base_score", "penalty", "final_score", "contributions", "missing_factors"}` built from the instance fields | A | pure: yes. `contributions` and `missing_factors` are returned by reference (aliased to the dataclass fields, not copied), so a caller mutating the dict mutates the result; the method itself mutates nothing. |
| `normalize_weights` | `def normalize_weights(weights: dict[str, float], present: set[str], exclude: set[str] = frozenset()) -> dict[str, float]` | `dict[str, float]` — `{}` if no active weight; else each active weight (not excluded, `> 0`, name in `present`) divided by the active total | A | pure: yes. New dict; inputs not mutated. Default `exclude=frozenset()` is immutable, so the mutable-default trap does not apply. |
| `compute_conviction` | `def compute_conviction(subscores: dict[str, float], weights: dict[str, float]) -> ConvictionResult` | `ConvictionResult` — `score=clamp(base - penalty, 0, 100)`, `base_score=sum(normalized_weight*subscore)`, `normalized_weights`, per-factor `contributions`, `penalty=sum(weight*subscore over PENALTY_ONLY_FACTORS present)`, `missing_factors` sorted; raises `ScoringError` on non-numeric/bool/out-of-range subscores or non-numeric/negative weights | A | pure: yes. Inputs only read; `set(subscores)` and `sorted(...)` produce new objects. `portfolio_fit` is excluded from the roll-up and applied as a raw (un-normalised) `weight * subscore` penalty. Module imports only `dataclasses`. |

### core/schedule.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `next_run_after` | `def next_run_after(cron_expression: str, after: dt.datetime) -> dt.datetime` | `dt.datetime` — `croniter(cron_expression, after).get_next(dt.datetime)`; raises `InvalidCronExpression` (wrapping `CroniterError`/`ValueError`) on a bad expression | A | Pure given `after`; croniter only. No clock read: the anchor is the caller's. |
| `is_due` | `def is_due(cron_expression: str, last_run_at: dt.datetime \| None, now: dt.datetime) -> bool` | `bool` — `True` when `last_run_at` is None, else `next_run_after(cron_expression, last_run_at) <= now` | A | Pure given `now`. Nothing in the codebase calls it yet (no scheduler/daemon exists; see module docstring). |

### agents/order_builder.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `build_buy_order` | `def build_buy_order(ticker: str, conviction: float, sizing: SizingResult, current_price: float, config: OrderBuilderConfig) -> OrderProposal \| None` | `OrderProposal \| None` - a BUY LIMIT `OrderProposal` (qty = floor(position_usd / price), limit = price * (1 + limit_buffer_pct/100) rounded to 2dp) or None when sizing not approved, price <= 0, or qty would be 0 | A | Pure arithmetic over inputs; reads `config.limit_buffer_pct`. No LLM. |
| `build_exit_order` | `def build_exit_order(ticker: str, held_qty: float, current_price: float, weight_pct: float, conviction: float, evaluation: HeldPositionEvaluation, config: OrderBuilderConfig) -> OrderProposal \| None` | `OrderProposal \| None` - a SELL LIMIT `OrderProposal` (PROFIT_BAND sells floor(held_qty * profit_trim_fraction), min 1; any other trigger sells floor(held_qty); limit = price * (1 - limit_buffer_pct/100)) or None when no exit signal, held_qty <= 0, price <= 0, or qty 0 | A | Pure; reads `evaluation.primary_trigger.type`, `config.profit_trim_fraction`, `config.limit_buffer_pct`. `is_trim` = quantity < held_qty. No LLM. |

### agents/research.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `ResearchMemo.subscores` | `def subscores(self) -> dict[str, float]` | `dict[str, float]` - `{factor_name: value}` for each name in `RESEARCH_SUBSCORE_NAMES` whose `Subscore.data_available` is True and value is not None; unavailable factors omitted | A | Pure over model fields. |
| `ResearchMemo.unavailable_factors` | `def unavailable_factors(self) -> list[str]` | `list[str]` - names in `RESEARCH_SUBSCORE_NAMES` whose `Subscore.data_available` is False | A | Pure. |
| `NewsDigest.ok` | `def ok(self) -> bool` | `bool` - `self.error is None` | A | `@property`. |
| `NewsDigest.found_news` | `def found_news(self) -> bool` | `bool` - True only if ok, at least one `source_urls` entry, and `NO_MATERIAL_NEWS` marker absent from `text` | A | `@property`. |
| `run_news_digest` | `def run_news_digest(llm: LLMClient, ticker: str, config: ResearchConfig, cache: FileCache \| None = None) -> NewsDigest` | `NewsDigest` - cached digest (`cached=True`) if key `news:<TICKER>:<lookback>d` is fresh in `cache`; else the `llm.call_text` result (text stripped, source_urls, usage), or a `NewsDigest(error=str(exc))` on any exception | E | Read side: `cache.get(key)` (local cache file; production root `data/news_cache`). Network side: `llm.call_text` to Anthropic, COSTS MONEY; model selected by `config.digest_model` (default `claude-haiku-4-5`); ALWAYS attaches a `web_search` tool (`web_search_tool(config.digest_model, config.web_search_max_uses)`, type `web_search_20250305`), each search $0.01; `max_tokens=1200`. Write side: `cache.set(key, {...}, config.news_cache_hours*3600)` only on success and only when `cache` is not None (JSON file under the cache root). Also `LLMClient.call_text` writes the monthly spend file via `budget.record` (production `data/llm_spend.json`). Note `config.web_search_enabled` is NOT checked here (caller's job). |
| `ResearchResult.ok` | `def ok(self) -> bool` | `bool` - `self.error is None and self.memo is not None` | A | `@property`. |
| `run_research` | `def run_research(llm: LLMClient, context: ResearchContext, config: ResearchConfig, max_tokens: int = 4096) -> ResearchResult` | `ResearchResult` - `memo=result.parsed` (a `ResearchMemo`) and `usage` on success; `memo=None, error=str(exc)` on any exception (never raises) | E | `llm.call_structured` to Anthropic, COSTS MONEY; model selected by `config.model` (`ResearchConfig.model`, default `claude-sonnet-4-6`); no web search tool attached (structured call has no `tools` parameter). Builds the user message from `context.context_text` plus `_news_section(context)` (uses `news_digest.found_news`). `call_structured` also writes the spend tracker file (`data/llm_spend.json`) via `budget.record`. |
| `run_research_batch` | `def run_research_batch(llm: LLMClient, contexts: list[ResearchContext], config: ResearchConfig) -> list[ResearchResult]` | `list[ResearchResult]` - `[run_research(llm, ctx, config) for ctx in contexts]`, one per context, in order | E | One Anthropic call per context via `run_research` (COSTS MONEY, `config.model`, no web search). Does not cap input size. |

### agents/screener.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `evaluate_stage1` | `def evaluate_stage1(item: ScreenerInput, config: Stage1Config) -> Stage1Result` | `Stage1Result` - gates (liquidity, fundamental floor, valuation band, earnings_soon), `passed = (liquidity and floor) or is_held`, `held_override`, reasons list, `rank_score` from RS-vs-SPY else price-vs-200DMA | A | Pure. ETFs (`is_etf`) auto-pass the fundamental floor. |
| `run_stage1` | `def run_stage1(items: list[ScreenerInput], config: Stage1Config) -> list[Stage1Result]` | `list[Stage1Result]` - one `evaluate_stage1` result per input, no trimming | A | Pure. |
| `select_survivors` | `def select_survivors(results: list[Stage1Result], config: Stage1Config) -> list[Stage1Result]` | `list[Stage1Result]` - all held results, then non-held passed results sorted by `rank_score` desc (None last) and cut to `config.max_survivors` | A | Pure. |
| `Stage2Result.ok` | `def ok(self) -> bool` | `bool` - `self.error is None` | A | `@property`. |
| `describe_candidate` | `def describe_candidate(item: ScreenerInput, result: Stage1Result) -> str` | `str` - one formatted data line (mcap, ADV, RS vs SPY, px vs 50/200DMA, ATR, valuation, P/E, rev growth, FCF, earnings flag) | A | Pure string formatting. |
| `run_stage2_batch` | `def run_stage2_batch(llm: LLMClient, stage1_results: list[Stage1Result], config: Stage2Config, screener_inputs: dict[str, ScreenerInput] \| None = None) -> list[Stage2Result]` | `list[Stage2Result]` - held names first (passed=True, material=False, no LLM); then one result per non-held name: scored ones carry `score`, `verdict=reason`, `usage`, `material=passed=(in top config.max_survivors by score)`; unscored ones get `passed=False` with `error` (chunk exception or "ticker missing from the ranking reply") | E | `llm.call_structured` to Anthropic, COSTS MONEY, once per chunk of `config.batch_size` non-held names; model selected by `config.model` (`Stage2Config.model`, default `claude-haiku-4-5`); no web search tool attached; `max_tokens=max(600, 60*len(chunk))`; output model `Stage2Ranking`. Spend tracker file written by `call_structured`. Held names never go to the model. |
| `select_stage2_survivors` | `def select_stage2_survivors(results: list[Stage2Result], stage1_by_ticker: dict[str, Stage1Result], config: Stage2Config) -> list[Stage2Result]` | `list[Stage2Result]` - held results, then non-held passed results sorted by (score, Stage 1 rank_score) desc and cut to `config.max_survivors` | A | Pure. Raises KeyError if a ticker is absent from `stage1_by_ticker`. |

### sources/base.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `FactorData.ok` | `def ok(self) -> bool` | `bool` - `self.error is None` | A | `@property`. `FactorSource.fetch` is an abstract stub (excluded). |

### sources/fmp.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `FMPClient.get_profile` | `def get_profile(self, ticker: str) -> dict` | `dict` - first element of the `profile` list response, or the dict/`{}` | E | Via `_get` -> `cache.get_or_fetch` (reads/writes JSON under the FMP FileCache root; production `data/cache`). On miss: `budget.check_and_increment()` writes `DailyCallBudget` file (production `data/fmp_call_budget.json`) then HTTP GET `financialmodelingprep.com/stable/profile` (FMP, free, counts against 250/day). TTL 7d. Raises `FMPError` on non-200 / "Error Message"; `BudgetExceeded` when over cap. |
| `FMPClient.get_quote` | `def get_quote(self, ticker: str) -> dict` | `dict` - first element of `quote` response or `{}` | E | Same path as get_profile; resource `quote`, TTL 20h. FMP 250/day. Not called by `LiveMarketDataGateway` (402s on this plan) but IS called by `FMPFactorSource.fetch`. |
| `FMPClient.get_income_statement` | `def get_income_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]` | `list[dict]` - `income-statement` rows or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 30d. |
| `FMPClient.get_cash_flow_statement` | `def get_cash_flow_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> list[dict]` | `list[dict]` - `cash-flow-statement` rows or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 30d. |
| `FMPClient.get_historical_prices` | `def get_historical_prices(self, ticker: str, from_date: str \| None = None, to_date: str \| None = None) -> list[dict]` | `list[dict]` - bare list from `historical-price-eod/full` (or `data["historical"]` if a dict), `[]` if empty | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 20h. |
| `FMPClient.get_earnings_surprises` | `def get_earnings_surprises(self, ticker: str, limit: int = 8) -> list[dict]` | `list[dict]` - `earnings-surprises` rows or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 7d. Resource name flagged "best-effort" in source. |
| `FMPClient.get_analyst_estimates` | `def get_analyst_estimates(self, ticker: str, period: str = "annual", limit: int = 4) -> list[dict]` | `list[dict]` - `analyst-estimates` rows or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 3d. |
| `FMPClient.get_price_target_summary` | `def get_price_target_summary(self, ticker: str) -> dict` | `dict` - first element if list, else dict, else `{}` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 3d. Best-effort resource. |
| `FMPClient.get_institutional_ownership` | `def get_institutional_ownership(self, ticker: str) -> list[dict]` | `list[dict]` - list as-is, a single dict wrapped in a list, or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 30d. Best-effort resource `institutional-ownership/symbol-positions-summary`. |
| `FMPClient.get_insider_trading` | `def get_insider_trading(self, ticker: str, limit: int = 50) -> list[dict]` | `list[dict]` - `insider-trading` rows or `[]` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 3d. Best-effort resource. |
| `FMPClient.get_sp500_constituents` | `def get_sp500_constituents(self) -> list[str]` | `list[str]` - sorted, de-duplicated, upper-cased `symbol` values from `sp500-constituent` | E | Cache root + budget file writes; FMP network on miss (250/day). TTL 30d. Documented to return HTTP 402 on this account (superseded by `sources/index_constituents.py`). |
| `FMPFactorSource.fetch` | `def fetch(self, ticker: str, ctx: RunContext) -> FactorData` | `FactorData` - `fields` dict with profile, quote, income_statement, cash_flow_statement, earnings_surprises, analyst_estimates, price_target_summary, institutional_ownership, insider_trading; or `FactorData(error=str(exc))` on `FMPError` | E | Calls 9 `FMPClient` getters in sequence (up to 9 budgeted FMP calls on a cold cache, incl. `get_quote`); each writes cache root + budget file. Only `FMPError` is caught; `BudgetExceeded` propagates. Non-deterministic (clock) when `ctx` is falsy: `dt.datetime.utcnow()`. |

### sources/index_constituents.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `normalise_symbol` | `def normalise_symbol(raw: str) -> str` | `str` - stripped, upper-cased, `.` replaced with `-` | A | Pure. |
| `parse_wikipedia_symbols` | `def parse_wikipedia_symbols(html: str) -> list[str]` | `list[str]` - sorted normalised symbols from the `id="constituents"` table's `Symbol` column; `[]` if no table / no Symbol column | A | Pure over the HTML string; uses pandas `read_html` with lxml flavor (local parse, no I/O). |
| `SP500ConstituentsSource.get_constituents` | `def get_constituents(self) -> list[str]` | `list[str]` - cached or freshly parsed symbol list (copied) | E | `cache.get_or_fetch(CACHE_KEY="index:sp500:constituents", 30d)` reads/writes JSON under the FileCache root (production `data/index_cache`). Network via injected `fetcher`; default `_default_wikipedia_fetcher` HTTP GETs Wikipedia's "List of S&P 500 companies" (free). Raises `RuntimeError` (and caches nothing) if fewer than 400 symbols parse. |

### sources/live_gateway.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `LiveMarketDataGateway.prefetch` | `def prefetch(self, tickers: list[str]) -> int` | `int` - count of tickers newly cached by `self.yf.prefetch_history([*tickers, "SPY"])` | E | `YFinanceClient.prefetch_history`: reads `yf:hist:<t>:2y` cache keys, then `cache.set` per fetched ticker (yfinance FileCache root; production `data/yf_cache`). Network via injected `batch_history_fetcher`; default `yf.download` (Yahoo Finance, free). Never raises on batch failure (returns 0). |
| `LiveMarketDataGateway.get_screener_input` | `def get_screener_input(self, ticker: str, is_held: bool) -> ScreenerInput` | `ScreenerInput` - market cap / ADV from the yfinance quote snapshot, `technical` from `compute_technical_snapshot` over yfinance bars vs SPY bars, `trailing_pe = price / eps`, FCF and revenue growth from statements (None for ETFs), `days_to_earnings=None`, `is_etf` from `etf_tickers` | E | All through `FileCache.get_or_fetch` (writes under `data/yf_cache`, and `data/cache` + `data/fmp_call_budget.json` on the FMP fallback). Network: yfinance quote snapshot (`fast_info`), income statement (limit 2) and cash flow (limit 1) via yfinance first; FMP `income-statement`/`cash-flow-statement` fallback ONLY when `is_held` (FMP, 250/day); yfinance 2y bars for ticker and SPY (SPY memoised on the instance); `yf.get_current_price` only if the snapshot had no price. Raises `RuntimeError` when statements are unavailable (non-held names, yfinance-only); no FMP call for ETFs or non-held names. |
| `LiveMarketDataGateway.get_research_context` | `def get_research_context(self, ticker: str) -> str` | `str` - multi-line research context: company/sector/market cap (FMP profile), price (yfinance), description, fundamentals lines (or "not applicable" for ETFs), technical snapshot line | E | Cache writes under `data/cache` (+ `data/fmp_call_budget.json`) and `data/yf_cache`. Network: FMP `profile` always (250/day); for non-ETFs also FMP `earnings-surprises` (limit 4), `analyst-estimates` (limit 2), `price-target-summary`, `institutional-ownership`, `insider-trading` (limit 20) = up to 6 FMP calls per name on a cold cache; income/cash-flow via yfinance with FMP fallback allowed (up to 2 more); yfinance current price and 2y bars (+SPY). Every sub-fetch wrapped in `_safe`, which folds exceptions into an `"error"` dict key / list entry instead of raising. `_safe` swallows `BudgetExceeded` too. |
| `LiveMarketDataGateway.get_current_price` | `def get_current_price(self, ticker: str) -> float` | `float` - `self.yf.get_current_price(ticker)` | E | yfinance cache `yf:price:<ticker>` (writes under `data/yf_cache`); network via injected `price_fetcher`, default `yf.Ticker(...).fast_info["lastPrice"]` (Yahoo Finance, free). Raises `YFinanceError` if no price. |
| `LiveMarketDataGateway.get_sector` | `def get_sector(self, ticker: str) -> str \| None` | `str \| None` - `self.fmp.get_profile(ticker).get("sector")` | E | FMP `profile` through cache (`data/cache`) + budget file; network FMP on miss (250/day). Propagates `FMPError`/`BudgetExceeded`. |
| `LiveMarketDataGateway.get_cluster` | `def get_cluster(self, ticker: str) -> str \| None` | `str \| None` - `self.cluster_overrides.get(ticker.upper())` | A | Pure dict lookup on constructor-supplied overrides. |

### sources/prices.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `bars_from_fmp` | `def bars_from_fmp(historical: list[dict]) -> list[Bar]` | `list[Bar]` - one `Bar` per row (volume defaults 0), sorted ascending by `date` | A | Pure. KeyError if a row lacks date/open/high/low/close. |
| `fetch_bars` | `def fetch_bars(client: FMPClient, ticker: str, from_date: str \| None = None, to_date: str \| None = None) -> list[Bar]` | `list[Bar]` - `bars_from_fmp(client.get_historical_prices(...))` | E | Via `FMPClient.get_historical_prices`: cache root (`data/cache`) + budget file writes; FMP `historical-price-eod/full` on miss (250/day). Not used by `LiveMarketDataGateway` (bars come from yfinance there). |
| `sma` | `def sma(closes: Sequence[float], window: int) -> list[float \| None]` | `list[float \| None]` - rolling simple mean aligned to input, None until `window` values | A | Pure. |
| `true_range` | `def true_range(bars: Sequence[Bar]) -> list[float]` | `list[float]` - per-bar true range (first bar: high-low) | A | Pure. |
| `wilder_atr` | `def wilder_atr(bars: Sequence[Bar], window: int = 14) -> list[float \| None]` | `list[float \| None]` - Wilder-smoothed ATR, None for first `window-1` entries, all None if fewer than `window` bars | A | Pure. |
| `atr_percentile` | `def atr_percentile(atr_series: Sequence[float \| None], lookback: int = 252) -> float \| None` | `float \| None` - percentile rank (0-100) of the last non-None ATR in the trailing window; None if no values or window < 2 | A | Pure. |
| `trailing_return_pct` | `def trailing_return_pct(closes: Sequence[float], lookback: int) -> float \| None` | `float \| None` - % change from `closes[-lookback-1]` to `closes[-1]`; None if insufficient data, lookback <= 0, or start == 0 | A | Pure. |
| `relative_strength_pct` | `def relative_strength_pct(closes: Sequence[float], benchmark_closes: Sequence[float], lookback: int = 63) -> float \| None` | `float \| None` - ticker trailing return minus benchmark trailing return; None if either is None | A | Pure. |
| `price_vs_ma_pct` | `def price_vs_ma_pct(price: float, ma: float \| None) -> float \| None` | `float \| None` - `(price - ma) / ma * 100`; None if `ma` falsy | A | Pure. |
| `compute_technical_snapshot` | `def compute_technical_snapshot(bars: Sequence[Bar], spy_bars: Sequence[Bar] \| None = None, sector_bars: Sequence[Bar] \| None = None, rs_lookback: int = 63) -> TechnicalSnapshot` | `TechnicalSnapshot` - last price, SMA50/200, price-vs-MA %, ATR14, ATR % of price, ATR 252d percentile, RS vs SPY / sector (None when benchmark bars absent); all-None snapshot if `bars` empty | A | Pure composition of the functions above. |

### sources/us_listing.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `parse_us_common_stocks` | `def parse_us_common_stocks(nasdaq_listed: str, other_listed: str) -> list[str]` | `list[str]` - sorted union of upper-cased symbols from both pipe-delimited files after filtering (ETF=N, Test Issue=N, alphabetic 1-5 char symbol, non-common name regex, other-exchange codes N/A/P/Z) | A | Pure over the two text payloads; pandas `read_csv` on `StringIO` (no I/O). |
| `USListingSource.get_symbols` | `def get_symbols(self) -> list[str]` | `list[str]` - cached or freshly parsed listing (copied) | E | `cache.get_or_fetch("listing:us:common", 7d)` reads/writes JSON under the FileCache root (production `data/index_cache`). Network via injected `fetcher`; default `_default_directory_fetcher` HTTP GETs NASDAQ Trader `nasdaqlisted.txt` and `otherlisted.txt` (free). Raises `RuntimeError` (nothing cached) if fewer than 3000 symbols parse. |
| `screen_rows_to_quotes` | `def screen_rows_to_quotes(rows: list[dict]) -> dict[str, dict]` | `dict[str, dict]` - `{SYMBOL: {market_cap, three_month_avg_volume, last_price, quote_type="EQUITY"}}` for rows with `quoteType == "EQUITY"` | A | Pure. |
| `USEquityScreen.get_quotes` | `def get_quotes(self) -> dict[str, dict]` | `dict[str, dict]` - cached or freshly paged screener rows converted by `screen_rows_to_quotes` (copied) | E | `cache.get_or_fetch("yf:screen:us-equities", 20h)` reads/writes JSON under the FileCache root (production `data/index_cache`). Network via injected `page_fetcher`, up to `max_pages` (60) pages of `page_size` (250); default `_default_screen_page_fetcher` calls `yf.screen` with an `EquityQuery` (Yahoo Finance, free). |
| `apply_liquidity_pregate` | `def apply_liquidity_pregate(symbols: list[str], quotes: dict[str, dict], *, min_market_cap_usd: float, min_avg_daily_volume_usd: float) -> list[str]` | `list[str]` - upper-cased symbols whose screener row has `market_cap >= min` and `volume * price >= min ADV`; symbols with no row dropped | A | Pure. |

### sources/yfinance_source.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `map_statement_row` | `def map_statement_row(raw_row: dict, field_map: dict[str, str]) -> dict` | `dict` - `{"date": raw_row["date"], <fmp_key>: _clean(raw_row[yf_key]) ...}` for each entry in `field_map` | A | Pure; NaN/None -> None. |
| `YFinanceClient.prefetch_history` | `def prefetch_history(self, tickers: list[str], period: str = "2y") -> int` | `int` - number of tickers whose rows were written to the cache; 0 if nothing missing or the batch fetch raised | E | Read side: `cache.get(f"yf:hist:{t}:{period}")` per ticker. Network via injected `batch_history_fetcher`; default `_default_batch_history_fetcher` calls `yf.download` in chunks of 100 (Yahoo Finance, free). Write side: `cache.set` per ticker with rows (JSON files under the yfinance FileCache root; production `data/yf_cache`), TTL 20h. Swallows all exceptions from the batch fetch. |
| `YFinanceClient.prefetch_quotes` | `def prefetch_quotes(self, quotes: dict[str, dict]) -> int` | `int` - number of `yf:quote:<TICKER>` keys newly written (skips keys already fresh) | E | No network. Reads `cache.get`, writes `cache.set(key, raw, TTL_QUOTE=20h)` under the FileCache root (`data/yf_cache`). Seeded from `USEquityScreen.get_quotes`. |
| `YFinanceClient.get_quote_snapshot` | `def get_quote_snapshot(self, ticker: str) -> QuoteSnapshot` | `QuoteSnapshot` - market_cap, `avg_daily_volume_usd = three_month_avg_volume * last_price` (None if either missing), last_price, quote_type, from the cached/fetched raw dict | E | `cache.get_or_fetch(f"yf:quote:{ticker}", 20h)` reads/writes under `data/yf_cache`. Network via injected `quote_fetcher`; default `yf.Ticker(ticker).fast_info` (Yahoo Finance, free). Key is NOT upper-cased here (prefetch_quotes upper-cases) - see Uncertainties. |
| `YFinanceClient.get_current_price` | `def get_current_price(self, ticker: str) -> float` | `float` - cached or fetched last price | E | `cache.get_or_fetch(f"yf:price:{ticker}", 20h)` under `data/yf_cache`. Network via injected `price_fetcher`; default `fast_info["lastPrice"]` (Yahoo Finance, free); raises `YFinanceError` if missing. |
| `YFinanceClient.get_historical_bars` | `def get_historical_bars(self, ticker: str, period: str = "2y") -> list[Bar]` | `list[Bar]` - cached/fetched rows converted to `Bar`, sorted ascending by date | E | `cache.get_or_fetch(f"yf:hist:{ticker}:{period}", 20h)` under `data/yf_cache`. Network via injected `history_fetcher`; default `yf.Ticker(ticker).history(period, "1d")` (Yahoo Finance, free); raises `YFinanceError` if empty. |
| `YFinanceClient.get_income_statement` | `def get_income_statement(self, ticker: str, limit: int = 5) -> list[dict]` | `list[dict]` - first `limit` raw periods mapped through `INCOME_STATEMENT_FIELD_MAP` (FMP-shaped keys) | E | `cache.get_or_fetch(f"yf:income:{ticker}", 30d)` under `data/yf_cache` (raw rows cached, mapping applied on read). Network via injected `income_statement_raw_fetcher`; default `yf.Ticker(ticker).income_stmt` (Yahoo Finance, free); raises `YFinanceError` if empty. |
| `YFinanceClient.get_cash_flow_statement` | `def get_cash_flow_statement(self, ticker: str, limit: int = 5) -> list[dict]` | `list[dict]` - first `limit` raw periods mapped through `CASH_FLOW_FIELD_MAP` | E | `cache.get_or_fetch(f"yf:cashflow:{ticker}", 30d)` under `data/yf_cache`. Network via injected `cash_flow_raw_fetcher`; default `yf.Ticker(ticker).cashflow` (Yahoo Finance, free); raises `YFinanceError` if empty. |

### api/server.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `create_app` | `def create_app(db_path: str \| Path = DB_PATH, config_path: str \| Path = CONFIG_PATH, data_dir: str \| Path \| None = None) -> FastAPI` | `FastAPI` - a configured app with CORS middleware, five routers mounted under `/api`, and `app.state.session_factory` / `config_path` / `data_dir` set | E | DDL only, no DML: reclassified D->E for consistency with `init_db`. Calls `make_engine` (mkdir of `data/` parent, creates SQLite file `data/z_money.db` on first connect) then `init_db` = `Base.metadata.create_all` (DDL: creates every table in core/models.py if missing: positions, position_imports, runs, candidates, research_outputs, conviction, proposals, watchlist_items, risk_events, config_versions, nav_snapshots, briefings, journal_entries). No row writes. Executed at import time via `app = create_app()` on line 66, so importing `api.server` touches the filesystem and DB. |
| `health` | `def health() -> dict` | `dict` - `{"status": "ok"}` | A | `GET /api/health`. Nested inside `create_app`, registered via `@app.get`. |

### api/routes/briefing.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `get_session` | `def get_session(request: Request) -> Session` | `Session` - a generator that yields one session from `app.state.session_factory` and closes it in `finally` | A | FastAPI dependency. Opening a session issues no SQL by itself; the SQLite connection is lazily opened by whichever route runs a query. Annotation says `Session` but it is a generator function. |
| `get_latest_briefing` | `def get_latest_briefing(session: Session = Depends(get_session)) -> dict` | `dict` - `{"status": "no_runs_yet"}` when no `briefings` row exists, else `{"status": "ok", "run_id", "run_status", "generated_at", "briefing": <json.loads of briefing_json>}` | C | `GET /api/briefing/latest`. SELECTs `briefings` (newest by `created_at`) and `runs` (by pk). `deserialize_briefing` is pure `json.loads`. |

### api/routes/config.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `get_session` | `def get_session(request: Request) -> Session` | `Session` - yields a session from `app.state.session_factory`, closes in `finally` | A | Dependency; identical to briefing.py's. |
| `get_config_path` | `def get_config_path(request: Request) -> Path` | `Path` - `request.app.state.config_path` | A | Dependency. |
| `Stage1Update.cheap_below_expensive` | `def cheap_below_expensive(self) -> "Stage1Update"` | `Stage1Update` - `self`, or raises `ValueError` if `valuation_pe_cheap_max >= valuation_pe_expensive_min` | A | Pydantic `model_validator(mode="after")`. |
| `ScheduleUpdate.valid_cron` | `def valid_cron(self) -> "ScheduleUpdate"` | `ScheduleUpdate` - `self`, or raises `ValueError` wrapping `InvalidCronExpression` | A | Pydantic `model_validator(mode="after")`. Calls `next_run_after(self.nightly_run, dt.datetime(2026, 1, 1))` with a fixed anchor date, so it is deterministic (croniter only). |
| `get_config` | `def get_config(config_path: Path = Depends(get_config_path)) -> dict` | `dict` - `{"editable": editable_snapshot(raw), "defaults": default_values(), "yaml_text": dump_to_string(raw)}` | B | `GET /api/config`. Reads `config.yaml` (path from app.state) via `read_raw` (ruamel round-trip load). Free. No DB. |
| `update_config` | `def update_config(body: ConfigUpdateRequest, session: Session = Depends(get_session), config_path: Path = Depends(get_config_path)) -> dict` | `dict` - the same shape as `get_config`, re-read from disk after the write | D | `POST /api/config/update`. Reads `config.yaml` twice (`read_raw` in the handler, again inside `_write_and_validate` for the snapshot). Writes DB: 1x `session.add(ConfigVersion(...))` to `config_versions` (pre-write YAML text, version = last+1) and 1x `session.commit()`. Writes filesystem: `write_raw(config_path, raw)` overwrites `config.yaml`. Order: validate merged dict through `Config.model_validate` (422 on failure) → DB add → file write → commit. If the file write raises, the ConfigVersion row is never committed. Uses `dt.datetime.utcnow()` (clock). |
| `reset_config` | `def reset_config(session: Session = Depends(get_session), config_path: Path = Depends(get_config_path)) -> dict` | `dict` - same shape as `get_config`, after resetting editable fields to Pydantic defaults | D | `POST /api/config/reset`. Same effect path as `update_config`: reads `config.yaml`, `apply_updates(raw, default_values())`, snapshot to `config_versions` (1 add + 1 commit), overwrites `config.yaml`. |

Private helpers reachable from the routes above: `_snapshot` (SELECT `config_versions` max version + `session.add`), `_write_and_validate` (Config validation, `read_raw`, `write_raw`, `session.commit`), `_current` (`read_raw`; pure otherwise).

### api/routes/dashboard.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `get_session` | `def get_session(request: Request) -> Session` | `Session` - yields a session, closes in `finally` | A | Dependency. |
| `get_data_dir` | `def get_data_dir(request: Request) -> Path` | `Path` - `request.app.state.data_dir` | A | Dependency. |
| `get_config_path` | `def get_config_path(request: Request) -> Path` | `Path` - `request.app.state.config_path` | A | Dependency. |
| `get_dashboard` | `def get_dashboard(session: Session = Depends(get_session), data_dir: Path = Depends(get_data_dir), config_path: Path = Depends(get_config_path)) -> dict` | `dict` - `{"status": "no_runs_yet"}` if no runs, else `{"status": "ok", "run": {...}, "tiles": [...], "setups": [...], "plans": {...}, "insights": {...}}` | B | `GET /api/dashboard`. Filesystem reads (all free, all local): `data_dir/llm_spend.json` and `data_dir/fmp_call_budget.json` via `_read_json` (missing/invalid → `{}`); `config.yaml` via `load_config` twice (budget cap, conviction_scaling; any exception swallowed → None); `data_dir/yf_cache/<sha256>.json` per setup ticker via `FileCache.peek` (called twice per ticker: once in `add`, once in the plans loop). Note `FileCache.__init__` does `root.mkdir(parents=True, exist_ok=True)`, so a missing `data_dir/yf_cache` directory is CREATED as a side effect (minor E). DB SELECTs: `runs` (last 12 by started_at), `candidates`, `proposals` (by run_id in), `briefings` (one SELECT per run id, up to 12), `positions` (all), `research_outputs`, `conviction`, `risk_events` (type SIZING_REJECTED) for the latest run. No writes. Clock: `time.gmtime()` for month/day keys. `compute_technical_snapshot` and `lerp_by_conviction` are pure. |
| `get_prices` | `def get_prices(ticker: str, range: str = "1M", data_dir: Path = Depends(get_data_dir)) -> dict` | `dict` - `{"ticker", "range", "as_of", "available_ranges", "bars": [Bar.__dict__ ...]}` windowed to the range; 422 on bad range, 404 when no cached bars | B | `GET /api/prices/{ticker}?range=1W\|1M\|3M\|1Y`. Reads `data_dir/yf_cache/<sha256("yf:hist:TICKER:2y")>.json` via `FileCache.peek`; same mkdir side effect on `yf_cache`. Free. No DB, no network. |

### api/routes/journal.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `get_session` | `def get_session(request: Request) -> Session` | `Session` - yields a session, closes in `finally` | A | Dependency. |
| `JournalCreate.content_not_blank` | `def content_not_blank(cls, v: str) -> str` | `str` - `v.strip()`, or raises `ValueError("A note needs some text.")` if blank | A | `field_validator("content")`, classmethod. |
| `JournalCreate.normalise_ticker` | `def normalise_ticker(cls, v: str \| None) -> str \| None` | `str \| None` - `v.strip().upper()` or None when empty/None | A | `field_validator("linked_ticker")`, classmethod. |
| `list_entries` | `def list_entries(session: Session = Depends(get_session)) -> dict` | `dict` - `{"entries": [{"id","date","content","linked_ticker"}, ...]}` ordered date desc, id desc | C | `GET /api/journal`. SELECT `journal_entries`. |
| `create_entry` | `def create_entry(body: JournalCreate, session: Session = Depends(get_session)) -> dict` | `dict` - the serialized new row (`id`, `date` ISO, `content`, `linked_ticker`) | D | `POST /api/journal`. Writes table `journal_entries`: 1x `session.add(JournalEntry(...))`, 1x `session.commit()`, 1x `session.refresh(entry)` (a SELECT after commit). Date defaults to `dt.date.today()` (local clock, non-UTC) when body.date is None; stored as midnight datetime. |
| `delete_entry` | `def delete_entry(entry_id: int, session: Session = Depends(get_session)) -> dict` | `dict` - `{"deleted": entry_id}`; 404 if no such row | D | `DELETE /api/journal/{entry_id}`. `session.get(JournalEntry, id)` then 1x `session.delete(entry)`, 1x `session.commit()` on table `journal_entries`. |

### api/routes/screens.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `get_session` | `def get_session(request: Request) -> Session` | `Session` - yields a session, closes in `finally` | A | Dependency. |
| `get_positions` | `def get_positions(session: Session = Depends(get_session)) -> dict` | `dict` - `{"positions": [...], "cash_pct", "priced_at"}`; briefing-derived fields null when no BookEntry matches | C | `GET /api/positions`. SELECT `positions` (all, by ticker) and `briefings` (latest; queried twice: once via `_book_by_ticker`, once directly). |
| `get_watchlist` | `def get_watchlist(session: Session = Depends(get_session)) -> dict` | `dict` - `{"items": [...], "run_id", "generated_at"}`; items from `watchlist_items` rows, falling back to the latest briefing's `watching` list | C | `GET /api/watchlist`. SELECT `runs` (latest), `watchlist_items` (by run_id), `briefings` (latest), `conviction` (by run_id). Mutates the `items` dicts in memory only. |
| `get_orders` | `def get_orders(session: Session = Depends(get_session)) -> dict` | `dict` - `{"orders": [every proposal, newest first], "runs": [per-run status/error/proposal_count/risk_events counts]}` | C | `GET /api/orders`. SELECT `runs` (all), `proposals` (all), `risk_events` (all, counted per (run_id, type)). |
| `get_insights` | `def get_insights(session: Session = Depends(get_session)) -> dict` | `dict` - `{"tickers": [{"ticker","trend","conviction_now","conviction_delta","memos":[...]}]}` sorted by conviction desc, nulls last | C | `GET /api/insights`. SELECT `runs` (all), `conviction` (all), `research_outputs` (all, id desc). `json.loads` on bear_case_json / subscores_json / catalysts_json / risks_json / reasoning_json / derivation_json — an unparseable column raises 500 (no guard). |
| `get_performance` | `def get_performance(session: Session = Depends(get_session)) -> dict` | `dict` - `{"series": [...], "point_count", "has_history" (>=2 points), "current_nav_usd", "peak_nav_usd", "drawdown_pct", "change_since_first_pct"}` | C | `GET /api/performance`. SELECT `nav_snapshots` (all, by recorded_at asc). |

Private helpers: `_latest_briefing` (SELECT `briefings`), `_book_by_ticker` (wraps it), `_trend` (pure).

### scripts/run_live_briefing.py

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `parse_args` | `def parse_args() -> argparse.Namespace` | `argparse.Namespace` - parsed `--import-csv`, `--manual` (list), `--cash`, `--dry-run-universe`, `--skip-preflight` | A | Reads `sys.argv` (process input, not I/O). `argparse` may call `sys.exit` on bad args. |
| `main` | `def main() -> None` | `None` - prints the rendered briefing and run cost to stdout; returns early after printing projections when `--dry-run-universe`; raises `SystemExit` on pool-build failure, missing env vars, or pre-flight failure | D | Entry point (`if __name__ == "__main__"`). **Reads:** `ROOT/.env` (dotenv → env vars), `ROOT/config.yaml` (`load_config`), optional `--import-csv` file, env `FMP_API_KEY` (hard exit if unset) and `ANTHROPIC_API_KEY` (read by `anthropic.Anthropic()`), `data/llm_spend.json` and `data/fmp_call_budget.json` (spend counters, read before/after). **DB (`data/z_money.db`):** `make_engine`+`init_db` (DDL create_all). Before the pipeline: `--import-csv` → `PortfolioService.import_flex_csv` writes `position_imports` (1 add) and, via `reconcile`, `positions` (add / attribute mutation of qty, avg_cost, last_verified_at / delete) then `session.commit()`; each `--manual` → `add_manual_position` adds 1 `positions` row and commits. Reads `positions` (`list_positions`), `position_imports` (`latest_cash_balance`), `research_outputs`+`runs` (`holdings_due_for_refresh`). **Via `run_nightly`** (one `session.commit()` after): writes `runs` (add + status/finished_at/error mutation), `candidates`, `proposals`, `conviction`, `research_outputs`, `watchlist_items`, `risk_events` (DATA_FETCH_FAILED, NEWS_DIGEST_FAILED, RESEARCH_FAILED, KILL_SWITCH, SIZING_REJECTED), `nav_snapshots` (`record_nav`), `briefings` (`BriefingRecord`), and `positions` (attribute mutation `peak_price_since_activation` per held name). **Network, all reachable from `main`:** NASDAQ Trader (`nasdaqlisted.txt`, `otherlisted.txt`; free) and yfinance `yf.screen` equity screener (free) when `rotating_pool_source == US_ALL`; Wikipedia S&P 500 page (free) when `SP500`; yfinance `fast_info` / `history` / `yf.download` / `income_stmt` / `cashflow` (free, uncapped) for every universe name plus SPY; FMP `financialmodelingprep.com/stable` (profile, quote, statements as fallback, earnings surprises, analyst estimates, price-target summary, institutional ownership, insider trading — each cache miss increments the 250/day budget; nominally free tier); Anthropic Messages API (**costs money**): pre-flight probe (`_preflight`), Stage 2 Haiku ranking calls, research memos (Sonnet), and news digests using the server-side `web_search` tool when `research.web_search_enabled` (each search request billed on top of tokens). **Filesystem writes:** `data/cache/` (FMP FileCache), `data/yf_cache/` (yfinance), `data/index_cache/` (listing / screener / constituents), `data/news_cache/` (digests), `data/fmp_call_budget.json` (`DailyCallBudget.check_and_increment`), `data/llm_spend.json` (`MonthlySpendTracker.record`), plus `data/` and cache dirs created by `mkdir`. Clock: `dt.datetime.utcnow()` for `as_of`. |

#### Private helpers of note (scripts/run_live_briefing.py)

| Function | Signature | Returns | Class | Notes |
|---|---|---|---|---|
| `_build_scan_pool` | `def _build_scan_pool(config, yf_client: YFinanceClient) -> tuple[list[str], str]` | `tuple[list[str], str]` - the ticker pool and a log line; `SystemExit` on unknown source | E | SP500: Wikipedia fetch via `SP500ConstituentsSource.get_constituents` (free, cached 30d in `data/index_cache/`). US_ALL: NASDAQ Trader symbol directory (`USListingSource.get_symbols`) + yfinance `yf.screen` pages (`USEquityScreen.get_quotes`), both cached in `data/index_cache/`; `apply_liquidity_pregate` is pure; `yf_client.prefetch_quotes` writes `yf:quote:*` entries into `data/yf_cache/`. Each `FileCache(...)` constructor mkdirs its root. No money. |
| `_projected_llm_cost` | `def _projected_llm_cost(config, held_tickers: list[str], due_held: int) -> float` | `float` - projected USD from `UNIT_COST` constants and config caps | A | Pure. `held_tickers` is unused in the body. |
| `_print_cost_projection` | `def _print_cost_projection(config, held_tickers: list[str], due_held: int, projected: float) -> None` | `None` - prints one line | A | stdout only. |
| `_preflight` | `def _preflight(anthropic_client, llm_budget, config, projected: float) -> None` | `None` - prints "Pre-flight: API probe OK" or raises `SystemExit` | B | Reads `data/llm_spend.json` (`remaining_this_month`). Makes one live `anthropic_client.messages.create(model=config.screener.stage2.model, max_tokens=1, ...)` probe: **costs money** (~$0.0005 per the docstring) and is NOT recorded to `llm_spend.json` (bypasses `LLMClient`/`MonthlySpendTracker.record`). Skipped with `--skip-preflight`. |
| `_print_call_projection` | `def _print_call_projection(config, held_tickers: list[str], universe_size: int, due_held: int \| None = None) -> None` | `None` - prints worst-case per-run FMP/yfinance/LLM call counts | A | stdout only; imports `BATCH_CHUNK` lazily. |
| `_require_env` | `def _require_env(name: str) -> str` | `str` - the env var value, or `SystemExit` if unset/empty | A | Reads `os.environ` (process state, no file I/O; the `.env` load happened earlier in `main`). |

## Reader uncertainties, merged verbatim

- `LLMClient.call_structured` and `call_text` (core/llm.py) call `self.budget.record(cost)`, which writes the `MonthlySpendTracker` JSON file (production `data/llm_spend.json`). Per the brief I classified pure-LLM callers (`run_research`, `run_research_batch`, `run_stage2_batch`) as B, but strictly by "strongest reachable effect" they are E (filesystem write of the spend file). Flagged in Notes; reclassify if the inventory wants the spend-file write counted.
- `Subscore._value_matches_availability` is a Pydantic `@model_validator` but its name starts with an underscore, so it was excluded under the naming rule. It is pure (raises `ValueError` when `data_available` and `value` disagree).
- `FMPFactorSource.__init__`, `LiveMarketDataGateway.__init__` (stores args, upper-cases cluster/ETF keys, no I/O) and `LiveMarketDataGateway._safe` (staticmethod) were excluded as underscore-named.
- `FileCache` root paths named above (`data/cache`, `data/yf_cache`, `data/news_cache`, `data/index_cache`, `data/fmp_call_budget.json`, `data/llm_spend.json`) come from `scripts/run_live_briefing.py`'s wiring; the modules themselves accept any root via injection, and `api/routes/dashboard.py` also opens `data_dir/yf_cache`.
- Cache-key casing mismatch: `YFinanceClient.prefetch_quotes` writes `yf:quote:<TICKER upper>` while `get_quote_snapshot` reads `yf:quote:<ticker as passed>`; a lower-case ticker argument would miss the seeded entry and trigger a network fetch. Not verified whether callers always pass upper-case.
- `sources/yfinance_source.py`'s module docstring still says `LiveMarketDataGateway` tries FMP first for fundamentals; the actual `live_gateway.py` code tries yfinance first. I classified from the code.
- `_default_screen_page_fetcher` (yfinance `yf.screen`) and `yf.download` were assumed free/no-key based on the source comments; not independently verified against Yahoo's terms or rate limits.
- `run_news_digest` does not consult `ResearchConfig.web_search_enabled`; whether the orchestrator gates on it before calling was not checked (outside the assigned files).
- `LiveMarketDataGateway.get_research_context` wraps every fetch in `_safe`, which also swallows `BudgetExceeded`, so a budget overrun surfaces only as an `"error"` string inside the context text rather than halting. `get_sector` and `get_screener_input` (held path) do propagate it.

- `get_session` in all four route modules is annotated `-> Session` but is a generator (yields); the table reports the annotation as written. Whether opening a session touches the SQLite file before the first query depends on SQLAlchemy's lazy connect; I treated it as A.
- `FileCache.__init__` calls `mkdir(parents=True, exist_ok=True)`. That makes `get_dashboard` and `get_prices` technically capable of creating `data_dir/yf_cache/` if absent. I kept them at B because no data is written; flag it if the inventory treats directory creation as E.
- Exact FMP endpoint set hit during a run depends on `LiveMarketDataGateway.get_research_context` / `get_screener_input` (sources/live_gateway.py) and `agents/research.py`, which I only grepped rather than read line by line. The list of FMP resources comes from `FMPClient`'s method surface; `get_sp500_constituents` exists on the client but is not called by this script.
- Whether Stage 2 and the memo calls go through `LLMClient.call_structured` vs `call_text`, and the exact models, live in `agents/screener.py` and `agents/research.py`, which were not read. The web-search cost path (`call_text` with `web_search_tool`) was confirmed in `agents/research.py::run_news_digest`.
- `run_nightly` also invokes `portfolio.check_drift`, which I did not read; assumed read-only.
- `PortfolioService.mark_filled` (writes `positions` incl. delete) exists but I found no call from `run_nightly` or this script; not listed as reachable.
- `create_entry` uses `dt.date.today()` (local time) while everything else uses UTC; noted, not verified as intentional.
