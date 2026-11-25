#property copyright "TradingLab 2.0"
#property version   "1.105"
#property strict
#include "TradingLabAccountGuard.mqh"
#include "TradingLabCollectorCommon.mqh"
#include "TradingLabCollectorLog.mqh"
#include "TradingLabCollectorPerformance.mqh"
#include "TradingLabActivityState.mqh"

// Read-only trading-events collector. It never sends or modifies trading orders.

input string IngestUrl = "http://127.0.0.1:8777/trading-events";
input string Token = "CHANGE-ME-WITH-A-LOCAL-TEST-TOKEN";
input string TerminalId = "";
string SourceId = "";
CollectorPerformance performance;
CollectorLane performance_lane = PERF_GENERAL;
input int IntervalSeconds = 10;
input int RequestTimeoutMs = 1000;
datetime HistoryStartServerTime = 0;
input int WindowSeconds = 21600;
input int MinimumWindowSeconds = 60;
input int OverlapSeconds = 5;
input int MaxItemsPerCollection = 200;
input int RecentLookbackSeconds = 3600;
input int RecentCadenceSeconds = 60;
input int HeartbeatSeconds = 60;
input bool EnableDeepRecovery = true;
input int MaxHistoryRowsPerCycle = 500;
input int CycleBudgetMs = 25;
input bool EnablePerformanceDiagnostics = false;
input bool EnableAdaptiveDeepWindow = true;

const string SCHEMA_VERSION = "mt5-trading-events-v1";
const string COLLECTOR_VERSION = "activity-0.9.0";
const int MAX_PAYLOAD_BYTES = 262144;
const int TRANSACTION_HINT_CAPACITY = 128;
const int LOCAL_ENCODING_FAILURE = -2;

string session_id = "";
string cursor_key = "";
string blocked_key = "";
string recent_cursor_key = "";
string recent_blocked_key = "";
long confirmed_from_msc = 0;
long recent_confirmed_from_msc = 0;
ulong sequence_number = 0;
ActivityPendingBatch pending;
ActivityPagination pagination;
ActivityPagination saved_recent_page;
ActivityPagination saved_deep_page;
ActivityPreparation preparation;
ActivityPageScan page_scan;
bool prefer_recent = true;
long deep_window_msc = 0;
int sparse_deep_windows = 0;
bool recovery_initialized = false;
bool recovery_blocked = false;
bool recent_recovery_blocked = false;
bool startup_pending = true;
bool trade_activity_pending = false;
CollectorCaptureState capture_state = CAPTURE_READY;
CollectorTransport transport;
CollectorLogger logger;
int last_request_error = 0;
int send_attempts = 0;
// MQL5 requires a literal size for a static array declaration.
TransactionHint transaction_hints[128];
int transaction_hint_head = 0;
int transaction_hint_count = 0;
long transaction_hints_dropped = 0;
ulong last_transaction_tick_ms = 0;
ulong last_heartbeat_tick_ms = 0;
ulong last_hint_deal_ticket = 0;
ulong last_hint_order_ticket = 0;
ulong last_hint_position_id = 0;


bool SelectRecoveryLane(const long now_msc, bool &recent)
{
   const long overlap_msc = (long)OverlapSeconds * 1000;
   long recent_gap = now_msc - recent_confirmed_from_msc;
   // A restored cursor can be exactly one overlap behind the last broker tick.
   // Only choose a new window when confirming it would advance its cursor.
   bool recent_due = !recent_recovery_blocked && (saved_recent_page.active ||
      (recent_gap > overlap_msc && (startup_pending || trade_activity_pending ||
       recent_gap >= (long)RecentCadenceSeconds * 1000)));
   bool deep_due = EnableDeepRecovery && !recovery_blocked && (saved_deep_page.active ||
      recent_confirmed_from_msc - confirmed_from_msc > overlap_msc);
   recent = recent_due && (!deep_due || prefer_recent);
   return recent_due || deep_due;
}

long DeepWindowMs()
{
   if(!EnableAdaptiveDeepWindow || deep_window_msc == 0)
      return (long)WindowSeconds * 1000;
   return deep_window_msc;
}

void ObserveConfirmedDeepWindow(const long duration, const bool sparse)
{
   if(!EnableAdaptiveDeepWindow)
      return;
   long current = DeepWindowMs();
   if(duration < current || !sparse)
   {
      sparse_deep_windows = 0;
      return;
   }
   if(++sparse_deep_windows >= 2)
   {
      deep_window_msc = MathMin(current * 2, 86400000);
      sparse_deep_windows = 0;
   }
}

#ifndef ACTIVITY_COLLECTOR_TEST
#define REMOTE_ACTIVITY_PROJECTION
#include "TradingLabObservedAccount.mqh"

void ResetAccountCapture()
{
   performance.Report(session_id, sequence_number, true);
   ActivityPendingBatch empty_batch;
   pending = empty_batch;
   ActivityPagination empty_page;
   pagination = empty_page;
   saved_recent_page = empty_page;
   saved_deep_page = empty_page;
   ZeroMemory(preparation);
   ZeroMemory(page_scan);
   recovery_initialized=false;
   recovery_blocked=false;
   recent_recovery_blocked=false;
   transaction_hint_head=0;
   transaction_hint_count=0;
   transaction_hints_dropped=0;
   last_hint_deal_ticket=0;
   last_hint_order_ticket=0;
   last_hint_position_id=0;
   startup_pending=true;
   prefer_recent=true;
   deep_window_msc=0;
   sparse_deep_windows=0;
   trade_activity_pending=false;
   sequence_number=0;
   ResetRetryState();
}

int OnInit()
{
   performance.Configure(EnablePerformanceDiagnostics);
   logger.Configure("activity", TerminalId, COLLECTOR_VERSION);
   if(!IsCollectorIngestUrl(IngestUrl))
   {
      logger.Error("invalid_configuration", "TradingLab activity: configure a loopback HTTP or remote HTTPS trading-events endpoint");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsCollectorToken(Token))
   {
      logger.Error("invalid_configuration", "TradingLab activity: configure a local token with at least 24 characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsSafeIdentifier(TerminalId) || StringFind(Token,TerminalId+".")!=0)
   {
      logger.Error("invalid_configuration", "TradingLab activity: SourceId contains unsupported characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(IntervalSeconds < 2 || IntervalSeconds > 300 || RequestTimeoutMs < 500 ||
      RequestTimeoutMs > IntervalSeconds * 1000 / 2)
   {
      logger.Error("invalid_configuration", "TradingLab activity: interval or timeout is outside the pilot limits");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MaxHistoryRowsPerCycle < 10 || MaxHistoryRowsPerCycle > 2000 ||
      CycleBudgetMs < 1 || CycleBudgetMs > 100 || WindowSeconds < 60 || WindowSeconds > 86400 || MinimumWindowSeconds < 1 ||
      MinimumWindowSeconds > WindowSeconds || OverlapSeconds < 0 ||
      OverlapSeconds >= MinimumWindowSeconds || MaxItemsPerCollection < 1 ||
      MaxItemsPerCollection > 200 ||
      RecentLookbackSeconds < RecentCadenceSeconds || RecentLookbackSeconds > 86400 ||
      RecentCadenceSeconds < IntervalSeconds || RecentCadenceSeconds > 3600 ||
      HeartbeatSeconds < IntervalSeconds || HeartbeatSeconds > 3600)
   {
      logger.Error("invalid_configuration", "TradingLab activity: review history window, overlap, limit and explicit start");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!EventSetTimer(IntervalSeconds))
   {
      logger.Error("timer_failed", StringFormat("TradingLab activity: cannot start timer (%d)", GetLastError()));
      return INIT_FAILED;
   }
   if(recovery_blocked)
      logger.Warn("deep_recovery_blocked", "TradingLab activity: deep recovery is blocked; recent capture remains independent");
   if(recent_recovery_blocked)
      logger.Warn("recent_recovery_blocked", "TradingLab activity: recent recovery is blocked at a saturated minimum window");
   // Healthy lifecycle events do not emit routine log entries.
   return INIT_SUCCEEDED;
}


void OnDeinit(const int reason)
{
   performance.Report(session_id, sequence_number, true);
   EventKillTimer();
   if(StringLen(pending.body) > 0 && !pending.is_heartbeat &&
      pending.from_msc > 0 && pending.to_msc >= pending.from_msc)
      logger.Warn("unconfirmed_range", StringFormat("TradingLab activity: unconfirmed range retained by cursor (%I64d..%I64d)",
                  pending.from_msc, pending.to_msc));
   // Healthy lifecycle events do not emit routine log entries.
}


void RunCollectorCycle();

void OnTimer()
{
   ulong started = performance.Start();
   performance_lane = PERF_GENERAL;
   RunCollectorCycle();
   performance.Record(started, PERF_TIMER, performance_lane);
   performance.Report(session_id, sequence_number);
}

void RunCollectorCycle()
{
   if(!SelectObservedAccount())
      return;
   if(!recovery_initialized && !InitializeRecovery())
      return;
   int drained_hints = DrainTransactionHints();
   if(drained_hints > 0)
      trade_activity_pending = true;
   if(StringLen(pending.body) > 0)
   {
      performance_lane = pending.is_heartbeat ? PERF_HEARTBEAT : (pending.is_recent ? PERF_RECENT : PERF_DEEP);
      TrySendPending(GetTickCount64());
      return;
   }
   ulong now_tick_ms = GetTickCount64();
   if(now_tick_ms - last_heartbeat_tick_ms >= (ulong)HeartbeatSeconds * 1000)
   {
      sequence_number++;
      performance_lane = PERF_HEARTBEAT;
      pending.body = BuildEnvelope(BuildHeartbeatPayload(now_tick_ms), sequence_number,
                                   "heartbeat");
      pending.is_heartbeat = true;
      if(!PayloadSizeIsValid(pending.body))
      {
         pending.body = "";
         pending.is_heartbeat = false;
         return;
      }
      TrySendPending(now_tick_ms);
      return;
   }
   long now_msc = (long)TimeCurrent() * 1000;
   if(!pagination.active && !preparation.active)
   {
      if(!SelectRecoveryLane(now_msc, pending.is_recent))
         return;
      if(pending.is_recent && saved_recent_page.active)
      {
         pagination = saved_recent_page;
         saved_recent_page.active = false;
      }
      else if(!pending.is_recent && saved_deep_page.active)
      {
         pagination = saved_deep_page;
         saved_deep_page.active = false;
      }
   }
   if(preparation.active)
      pending.is_recent = preparation.is_recent;
   if(pagination.active)
   {
      pending.is_recent = pagination.is_recent;
      performance_lane = pending.is_recent ? PERF_RECENT : PERF_DEEP;
      pending.from_msc = pagination.from_msc;
      pending.to_msc = pagination.to_msc;
      string page_reason = RecoveryReason(now_msc, pending.is_recent);
      string page_payload = BuildPagedActivityPayload(
         page_reason, pending.from_msc, pending.to_msc, pagination.after,
         pending.page_through, pending.page_has_more, pending.page_snapshot_id);
      if(page_payload == "")
         return;
      if(pagination.snapshot_id != "" && pending.page_snapshot_id != pagination.snapshot_id)
      {
         logger.Warn("history_changed", "TradingLab activity: paged history changed; restarting the window");
         pagination.after.time_msc = 0;
         pagination.after.entity_type = 0;
         pagination.after.ticket = 0;
         pagination.snapshot_id = pending.page_snapshot_id;
         page_payload = BuildPagedActivityPayload(
            page_reason, pending.from_msc, pending.to_msc, pagination.after,
            pending.page_through, pending.page_has_more, pending.page_snapshot_id);
         if(page_payload == "")
            return;
      }
      sequence_number++;
      pending.body = BuildEnvelope(page_payload, sequence_number, "activity_batch");
      pending.is_paged = true;
      pending.blocks_recovery = false;
      pending.is_heartbeat = false;
      if(!CheckPilotSafety() || !PayloadSizeIsValid(pending.body))
      {
         pending.body = "";
         return;
      }
      TrySendPending(now_tick_ms);
      return;
   }
   performance_lane = pending.is_recent ? PERF_RECENT : PERF_DEEP;
   long selected_from_msc = pending.is_recent ? recent_confirmed_from_msc : confirmed_from_msc;
   long selected_limit_msc = pending.is_recent ? now_msc : recent_confirmed_from_msc;
   if(selected_limit_msc <= selected_from_msc + (long)OverlapSeconds * 1000)
      return;
   long window_end_msc = selected_from_msc +
      (pending.is_recent ? (long)WindowSeconds * 1000 : DeepWindowMs());
   long target_to_msc = window_end_msc < selected_limit_msc ? window_end_msc : selected_limit_msc;
   string reason = RecoveryReason(now_msc, pending.is_recent);
   bool truncated = false;
   bool sparse = false;
   bool use_pagination = false;
   string payload = "";
   if(preparation.active && preparation.from_msc == selected_from_msc)
      target_to_msc = preparation.to_msc;
   preparation.active = false;
   payload = BuildActivityPayload(reason, selected_from_msc, target_to_msc, truncated, sparse);
   if(payload == "")
      return;
   long duration = target_to_msc - selected_from_msc;
   int payload_bytes = Utf8Size(payload);
   bool payload_too_large = payload_bytes > MAX_PAYLOAD_BYTES - 1024;
   if(truncated || payload_too_large)
   {
      if(!pending.is_recent)
         sparse_deep_windows = 0;
      if(duration <= (long)MinimumWindowSeconds * 1000)
      {
         ActivityPageKey page_start;
         page_start.time_msc = 0;
         page_start.entity_type = 0;
         page_start.ticket = 0;
         pagination.active = true;
         pagination.is_recent = pending.is_recent;
         pagination.from_msc = selected_from_msc;
         pagination.to_msc = target_to_msc;
         pagination.after = page_start;
         pagination.snapshot_id = "";
         payload = BuildPagedActivityPayload(reason, selected_from_msc, target_to_msc,
                                             page_start, pending.page_through,
                                             pending.page_has_more, pending.page_snapshot_id);
         if(payload == "")
            return;
         use_pagination = true;
      }
      else
      {
         long halved = selected_from_msc + duration / 2;
         target_to_msc = (halved / 1000) * 1000;
         if(target_to_msc < selected_from_msc + (long)MinimumWindowSeconds * 1000)
            target_to_msc = selected_from_msc + (long)MinimumWindowSeconds * 1000;
         if(!pending.is_recent && EnableAdaptiveDeepWindow)
            deep_window_msc = target_to_msc - selected_from_msc;
         preparation.active = true;
         preparation.is_recent = pending.is_recent;
         preparation.from_msc = selected_from_msc;
         preparation.to_msc = target_to_msc;
         return;
      }
   }

   sequence_number++;
   pending.body = BuildEnvelope(payload, sequence_number, "activity_batch");
   if(!CheckPilotSafety() || !PayloadSizeIsValid(pending.body))
   {
      pending.body = "";
      return;
   }
   pending.from_msc = selected_from_msc;
   pending.to_msc = target_to_msc;
   pending.blocks_recovery = truncated && !use_pagination;
   pending.is_paged = use_pagination;
   pending.sparse = sparse && payload_bytes > 0 && payload_bytes <= (MAX_PAYLOAD_BYTES - 1024) / 4;
   pending.is_heartbeat = false;
   TrySendPending(GetTickCount64());
}


void OnTradeTransaction(
   const MqlTradeTransaction &transaction,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{
   // Keep this callback bounded: no network, disk, SQLite or history reads.
   EnqueueTransactionHint(transaction);
   trade_activity_pending = true;
}


#endif

void EnqueueTransactionHint(const MqlTradeTransaction &transaction)
{
   last_transaction_tick_ms = GetTickCount64();
   if(transaction_hint_count >= TRANSACTION_HINT_CAPACITY)
   {
      transaction_hints_dropped++;
      return;
   }
   int tail = (transaction_hint_head + transaction_hint_count) % TRANSACTION_HINT_CAPACITY;
   transaction_hints[tail].deal_ticket = transaction.deal;
   transaction_hints[tail].order_ticket = transaction.order;
   transaction_hints[tail].position_id = transaction.position;
   transaction_hint_count++;
}


int DrainTransactionHints()
{
   int drained = transaction_hint_count;
   while(transaction_hint_count > 0)
   {
      TransactionHint hint = transaction_hints[transaction_hint_head];
      if(hint.deal_ticket > 0)
         last_hint_deal_ticket = hint.deal_ticket;
      if(hint.order_ticket > 0)
         last_hint_order_ticket = hint.order_ticket;
      if(hint.position_id > 0)
         last_hint_position_id = hint.position_id;
      transaction_hint_head = (transaction_hint_head + 1) % TRANSACTION_HINT_CAPACITY;
      transaction_hint_count--;
   }
   return drained;
}


string RecoveryReason(const long now_msc, const bool recent_lane)
{
   if(startup_pending)
      return "startup";
   if(trade_activity_pending)
      return "trade_activity";
   if(!recent_lane || now_msc - recent_confirmed_from_msc > (long)WindowSeconds * 1000)
      return "recovery";
   return "reconcile";
}


bool TrySendPending(const ulong now_ms)
{
   if(StringLen(pending.body) == 0 || !transport.Ready(now_ms))
      return false;
   int status = SendMessage(pending.body);
   if(capture_state != CAPTURE_READY)
      return false;
   if(status == LOCAL_ENCODING_FAILURE)
   {
      logger.Error("encoding_failed", "TradingLab activity: local batch preparation failed; cursor unchanged; stopped");
      StopForSafety();
      return false;
   }
   if(send_attempts < 2147483647)
      send_attempts++;
   if(status == 200 || status == 202)
   {
      logger.Resolve("receiver_access_blocked", sequence_number);
      logger.Resolve("receiver_unavailable", sequence_number);
      if(pending.is_heartbeat)
      {
         pending.body = "";
         pending.is_heartbeat = false;
         last_heartbeat_tick_ms = now_ms;
         ResetRetryState();
         return true;
      }
      if(pending.blocks_recovery)
      {
         string selected_blocked_key = pending.is_recent ? recent_blocked_key : blocked_key;
         if(!PersistValue(selected_blocked_key, pending.from_msc))
         {
            logger.Error("cursor_persistence_failed", "TradingLab activity: cannot persist blocked recovery marker");
            StopForSafety();
            return false;
         }
         if(pending.is_recent)
            recent_recovery_blocked = true;
         else
            recovery_blocked = true;
         logger.Error("recovery_saturated", StringFormat("TradingLab activity: saturated range requires operator review (%I64d..%I64d)",
                     pending.from_msc, pending.to_msc));
         pending.body = "";
         pending.blocks_recovery = false;
         ResetRetryState();
      }
      else
      {
         pending.body = "";
         return FinalizeConfirmedBatch();
      }
      return true;
   }
   CollectorDelivery delivery = transport.Observe(status, now_ms);
   if(delivery == DELIVERY_ACCESS_BLOCKED)
   {
      logger.Warn("receiver_access_blocked", "preserving batch; probing every 60 seconds",
                  sequence_number, status, last_request_error);
      return false;
   }
   if(delivery == DELIVERY_FATAL)
   {
      logger.Error("delivery_stopped", "receiver rejected batch; stopped",
                   sequence_number, status, last_request_error);
      StopForSafety();
      return false;
   }
   logger.Warn("receiver_unavailable", StringFormat("same batch retry; attempt=%d", send_attempts),
               sequence_number, status, last_request_error);
   return false;
}


void ResetRetryState()
{
   transport.Reset();
   send_attempts = 0;
}


bool FinalizeConfirmedBatch()
{
   if(pending.is_paged && pending.page_has_more)
   {
      pagination.active = true;
      pagination.is_recent = pending.is_recent;
      pagination.from_msc = pending.from_msc;
      pagination.to_msc = pending.to_msc;
      pagination.after = pending.page_through;
      pagination.snapshot_id = pending.page_snapshot_id;
      pending.is_paged = false;
      if(pending.is_recent)
         saved_recent_page = pagination;
      else
         saved_deep_page = pagination;
      pagination.active = false;
      prefer_recent = !pending.is_recent;
      ResetRetryState();
      return true;
   }
   long next_cursor = pending.to_msc - (long)OverlapSeconds * 1000;
   long selected_cursor = pending.is_recent ? recent_confirmed_from_msc : confirmed_from_msc;
   string selected_cursor_key = pending.is_recent ? recent_cursor_key : cursor_key;
   if(next_cursor <= selected_cursor || !PersistValue(selected_cursor_key, next_cursor))
   {
      logger.Error("cursor_persistence_failed", "TradingLab activity: cannot persist confirmed recovery cursor");
      StopForSafety();
      return false;
   }
   if(pending.is_recent)
      recent_confirmed_from_msc = next_cursor;
   else
   {
      confirmed_from_msc = next_cursor;
      ObserveConfirmedDeepWindow(pending.to_msc - pending.from_msc, !pending.is_paged && pending.sparse);
   }
   pending.blocks_recovery = false;
   pending.is_paged = false;
   pagination.active = false;
   pagination.snapshot_id = "";
   prefer_recent = !pending.is_recent;
   if(pending.is_recent)
   {
      startup_pending = false;
      trade_activity_pending = false;
   }
   ResetRetryState();
   return true;
}


bool PersistValue(const string name, const long value)
{
   ulong started = performance.Start();
   ResetLastError();
   bool saved = GlobalVariableSet(name, (double)value) != 0;
   if(saved)
      GlobalVariablesFlush();
   performance.Record(started, PERF_CURSOR, performance_lane, saved);
   return saved;
}


void StopForSafety()
{
   capture_state = CAPTURE_STOPPED;
   EventKillTimer();
}


#ifndef ACTIVITY_COLLECTOR_TEST


int SendMessage(const string body)
{
   if(!CheckPilotSafety() || !IsCollectorIngestUrl(IngestUrl))
      return 0;
   char request_body[];
   char response_body[];
   string response_headers = "";
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + Token + "\r\n";
   ulong encoding_started = performance.Start();
   int encoded = StringToCharArray(body, request_body, 0, WHOLE_ARRAY, CP_UTF8);
   int encoding_error = encoded <= 1 ? GetLastError() : 0;
   performance.Record(encoding_started, PERF_UTF8, performance_lane, encoded > 1);
   if(encoded <= 1)
   {
      last_request_error = encoding_error;
      logger.Error("encoding_failed", "local UTF-8 preparation failed; no HTTP request sent",
                   sequence_number, 0, last_request_error);
      return LOCAL_ENCODING_FAILURE;
   }
   ArrayResize(request_body, encoded - 1);
   ulong http_started = performance.Start();
   ResetLastError();
   int status = WebRequest("POST", IngestUrl, headers, RequestTimeoutMs,
                           request_body, response_body, response_headers);
   last_request_error = GetLastError();
   performance.Record(http_started, send_attempts > 0 ? PERF_RETRY_HTTP : PERF_INGEST_HTTP,
                      performance_lane, status == 200 || status == 202);
   if(status == 400)
   {
      // Print only fixed diagnostic codes, never an arbitrary response or the batch.
      string response = CharArrayToString(response_body, 0, WHOLE_ARRAY, CP_UTF8);
      string diagnostic = "unrecognized_response";
      string known_errors[] = {"ambiguous_framing", "incomplete_body", "invalid_message"};
      for(int index = 0; index < ArraySize(known_errors); index++)
         if(StringFind(response, "\"" + known_errors[index] + "\"") >= 0)
            diagnostic = known_errors[index];
      logger.Error("invalid_message_diagnostic", StringFormat("TradingLab activity: HTTP 400 diagnostic=%s request_bytes=%d response_bytes=%d",
                  diagnostic, ArraySize(request_body), ArraySize(response_body)));
   }
   return status;
}


#endif

string BuildActivityPayload(const string reason, const long from_msc, const long to_msc,
                            bool &truncated, bool &sparse)
{
   long from_seconds = from_msc / 1000;
   long to_seconds = (to_msc + 999) / 1000;
   ulong selection_started = performance.Start();
   ResetLastError();
   bool selected = to_msc >= from_msc && HistorySelect((datetime)from_seconds, (datetime)to_seconds);
   int selection_error = selected ? 0 : GetLastError();
   if(to_msc >= from_msc)
      performance.Record(selection_started, PERF_HISTORY_SELECT, performance_lane, selected);
   if(!selected)
   {
      logger.Warn("history_select_failed", StringFormat("TradingLab activity: HistorySelect failed (%d)", selection_error));
      return "";
   }
   if(HistoryDealsTotal() > MaxItemsPerCollection ||
      HistoryOrdersTotal() > MaxItemsPerCollection)
   {
      // Internal sentinel: never published; split once per timer or page the range.
      truncated = true;
      return "{}";
   }
   bool valid = true;
   int deal_total = 0;
   int order_total = 0;
   ulong rows_started = performance.Start();
   string deals = BuildHistoricalDeals(from_msc, to_msc, deal_total, valid);
   string orders = BuildHistoricalOrders(from_msc, to_msc, order_total, valid);
   performance.Record(rows_started, PERF_HISTORY_ROWS_JSON, performance_lane, valid);
   if(!valid)
   {
      logger.Warn("history_invalid", "TradingLab activity: history read returned invalid data");
      return "";
   }
   bool deals_truncated = deal_total > MaxItemsPerCollection;
   bool orders_truncated = order_total > MaxItemsPerCollection;
   truncated = deals_truncated || orders_truncated;
   sparse = deal_total <= MaxItemsPerCollection / 4 && order_total <= MaxItemsPerCollection / 4;
   string payload = "{";
   payload += "\"reason\":\"" + reason + "\",";
   payload += "\"identity\":" + BuildIdentity() + ",";
   payload += "\"window\":{\"from_server_msc\":\"" + IntegerToString(from_msc) +
              "\",\"to_server_msc\":\"" + IntegerToString(to_msc) + "\"},";
   payload += "\"deals\":" + CollectionJson(deal_total, deals, deals_truncated) + ",";
   payload += "\"orders\":" + CollectionJson(order_total, orders, orders_truncated);
   payload += "}";
   return payload;
}


string CollectionJson(const int total, const string items, const bool truncated)
{
   string status = truncated ? "truncated" : "complete";
   return "{\"status\":\"" + status + "\",\"total\":" + IntegerToString(total) +
          ",\"items\":" + items + "}";
}


string BuildPagedActivityPayload(const string reason, const long from_msc, const long to_msc,
                                 const ActivityPageKey &after,
                                 ActivityPageKey &through, bool &has_more,
                                 string &snapshot_id)
{
   long from_seconds = from_msc / 1000;
   long to_seconds = (to_msc + 999) / 1000;
   ulong selection_started = performance.Start();
   ResetLastError();
   bool selected = to_msc >= from_msc && HistorySelect((datetime)from_seconds, (datetime)to_seconds);
   int selection_error = selected ? 0 : GetLastError();
   if(to_msc >= from_msc)
      performance.Record(selection_started, PERF_HISTORY_SELECT, performance_lane, selected);
   if(!selected)
   {
      logger.Warn("history_select_failed", StringFormat("TradingLab activity: paged HistorySelect failed (%d)", selection_error));
      return "";
   }

   int selected_deals = HistoryDealsTotal();
   int selected_orders = HistoryOrdersTotal();
   if(selected_deals < 0 || selected_orders < 0)
      return "";
   if(!page_scan.active || page_scan.from_msc != from_msc || page_scan.to_msc != to_msc ||
      CompareActivityPageKeys(page_scan.after, after) != 0 ||
      page_scan.selected_deals != selected_deals || page_scan.selected_orders != selected_orders)
   {
      page_scan.active = true;
      page_scan.from_msc = from_msc;
      page_scan.to_msc = to_msc;
      page_scan.after = after;
      page_scan.selected_deals = selected_deals;
      page_scan.selected_orders = selected_orders;
      page_scan.deal_index = 0;
      page_scan.order_index = 0;
      page_scan.deal_total = 0;
      page_scan.order_total = 0;
      page_scan.key_count = 0;
      page_scan.remaining_count = 0;
      page_scan.snapshot_xor = 0;
      page_scan.snapshot_sum = 0;
      if(ArrayResize(page_scan.keys, MaxItemsPerCollection) < 0)
      {
         StopForSafety();
         return "";
      }
   }
   ulong scan_started = performance.Start();
   int processed = 0;
   ulong started_ms = GetTickCount64();
   while(page_scan.deal_index < selected_deals || page_scan.order_index < selected_orders)
   {
      if(processed >= MaxHistoryRowsPerCycle ||
         (processed > 0 && GetTickCount64() - started_ms >= (ulong)CycleBudgetMs))
      {
         performance.Record(scan_started, PERF_PAGE_SCAN, performance_lane);
         return ""; // Continue the same scan on the next timer; no ACK/cursor change.
      }
      processed++;
      ActivityPageKey key;
      ResetLastError();
      if(page_scan.deal_index < selected_deals)
      {
         key.ticket = HistoryDealGetTicket(page_scan.deal_index++);
         key.time_msc = HistoryDealGetInteger(key.ticket, DEAL_TIME_MSC);
         key.entity_type = 0;
      }
      else
      {
         key.ticket = HistoryOrderGetTicket(page_scan.order_index++);
         key.time_msc = HistoryOrderGetInteger(key.ticket, ORDER_TIME_DONE_MSC);
         key.entity_type = 1;
      }
      if(key.ticket == 0 || GetLastError() != 0)
      {
         page_scan.active = false;
         performance.Record(scan_started, PERF_PAGE_SCAN, performance_lane, false);
         return "";
      }
      if(key.time_msc < from_msc || key.time_msc > to_msc)
         continue;
      if(key.entity_type == 0) page_scan.deal_total++;
      else page_scan.order_total++;
      uint fingerprint = PageKeyFingerprint(key);
      page_scan.snapshot_xor ^= fingerprint;
      page_scan.snapshot_sum += (ulong)fingerprint;
      ConsiderPageKey(key, after, page_scan.keys, page_scan.key_count, page_scan.remaining_count);
      if(capture_state == CAPTURE_STOPPED)
      {
         performance.Record(scan_started, PERF_PAGE_SCAN, performance_lane, false);
         return "";
      }
   }
   performance.Record(scan_started, PERF_PAGE_SCAN, performance_lane);
   page_scan.active = false;
   bool valid = true;
   int key_count = page_scan.key_count;
   int deal_total = page_scan.deal_total;
   int order_total = page_scan.order_total;
   if(key_count < 1)
   {
      logger.Warn("page_empty", "TradingLab activity: paged range has no records after its cursor");
      return "";
   }

   string deals = "[";
   string orders = "[";
   ulong rows_started = performance.Start();
   int emitted_deals = 0;
   int emitted_orders = 0;
   for(int index = 0; index < key_count; index++)
   {
      ActivityPageKey key = page_scan.keys[index];
      if(key.entity_type == 0)
      {
         string row = BuildHistoricalDeal(key.ticket, valid);
         if(!valid)
         {
            performance.Record(rows_started, PERF_HISTORY_ROWS_JSON, performance_lane, false);
            return "";
         }
         if(emitted_deals++ > 0)
            deals += ",";
         deals += row;
      }
      else
      {
         string row = BuildHistoricalOrder(key.ticket, valid);
         if(!valid)
         {
            performance.Record(rows_started, PERF_HISTORY_ROWS_JSON, performance_lane, false);
            return "";
         }
         if(emitted_orders++ > 0)
            orders += ",";
         orders += row;
      }
   }
   deals += "]";
   orders += "]";
   performance.Record(rows_started, PERF_HISTORY_ROWS_JSON, performance_lane);
   through = page_scan.keys[key_count - 1];
   has_more = page_scan.remaining_count > key_count;
   string page_status = has_more ? "partial" : "paged_complete";
   snapshot_id = "p:" + IntegerToString(from_msc) + ":" +
      IntegerToString(to_msc) + ":" + IntegerToString(deal_total) + ":" +
      IntegerToString(order_total) + ":" + IntegerToString(page_scan.snapshot_xor) + ":" +
      UnsignedIdentifier(page_scan.snapshot_sum);
   string payload = "{";
   payload += "\"reason\":\"" + reason + "\",";
   payload += "\"identity\":" + BuildIdentity() + ",";
   payload += "\"window\":{\"from_server_msc\":\"" + IntegerToString(from_msc) +
              "\",\"to_server_msc\":\"" + IntegerToString(to_msc) + "\"},";
   payload += "\"deals\":" + PagedCollectionJson(deal_total, deals, page_status) + ",";
   payload += "\"orders\":" + PagedCollectionJson(order_total, orders, page_status) + ",";
   payload += "\"pagination\":{\"snapshot_id\":\"" + snapshot_id + "\",";
   payload += "\"after\":" + ActivityPageKeyJson(after) + ",";
   payload += "\"through\":" + ActivityPageKeyJson(through) + ",";
   payload += "\"has_more\":" + (has_more ? "true" : "false") + "}}";
   return payload;
}


string PagedCollectionJson(const int total, const string items, const string status)
{
   return "{\"status\":\"" + status + "\",\"total\":" + IntegerToString(total) +
          ",\"items\":" + items + "}";
}


string ActivityPageKeyJson(const ActivityPageKey &key)
{
   string entity = key.entity_type == 0 ? "deal" : "order";
   return "{\"time_msc\":\"" + IntegerToString(key.time_msc) +
          "\",\"entity_type\":\"" + entity + "\",\"ticket\":\"" +
          UnsignedIdentifier(key.ticket) + "\"}";
}


int CompareActivityPageKeys(const ActivityPageKey &left, const ActivityPageKey &right)
{
   if(left.time_msc != right.time_msc)
      return left.time_msc < right.time_msc ? -1 : 1;
   if(left.entity_type != right.entity_type)
      return left.entity_type < right.entity_type ? -1 : 1;
   if(left.ticket == right.ticket)
      return 0;
   return left.ticket < right.ticket ? -1 : 1;
}


uint PageKeyFingerprint(const ActivityPageKey &key)
{
   return StableHash(IntegerToString(key.time_msc) + ":" +
                     IntegerToString(key.entity_type) + ":" +
                     UnsignedIdentifier(key.ticket));
}


void ConsiderPageKey(const ActivityPageKey &key, const ActivityPageKey &after,
                     ActivityPageKey &keys[], int &count, int &remaining)
{
   if(CompareActivityPageKeys(key, after) <= 0)
      return;
   remaining++;
   if(ArraySize(keys) < MaxItemsPerCollection &&
      ArrayResize(keys, MaxItemsPerCollection) < 0)
   {
      StopForSafety();
      return;
   }
   if(count < MaxItemsPerCollection)
   {
      keys[count] = key;
      count++;
   }
   else if(CompareActivityPageKeys(key, keys[count - 1]) >= 0)
      return;
   else
      keys[count - 1] = key;

   for(int index = count - 1; index > 0; index--)
   {
      if(CompareActivityPageKeys(keys[index - 1], keys[index]) <= 0)
         break;
      ActivityPageKey swap = keys[index - 1];
      keys[index - 1] = keys[index];
      keys[index] = swap;
   }
}


string BuildHistoricalDeals(const long from_msc, const long to_msc, int &total, bool &valid)
{
   string result = "[";
   int emitted = 0;
   int selected = HistoryDealsTotal();
   if(selected < 0)
   {
      valid = false;
      return "[]";
   }
   for(int index = 0; index < selected; index++)
   {
      ResetLastError();
      ulong ticket = HistoryDealGetTicket(index);
      long time_msc = HistoryDealGetInteger(ticket, DEAL_TIME_MSC);
      if(ticket == 0 || GetLastError() != 0)
      {
         valid = false;
         return "[]";
      }
      if(time_msc < from_msc || time_msc > to_msc)
         continue;
      total++;
      if(emitted >= MaxItemsPerCollection)
         continue;
      string row = BuildHistoricalDeal(ticket, valid);
      if(!valid)
         return "[]";
      if(emitted > 0)
         result += ",";
      result += row;
      emitted++;
   }
   return result + "]";
}


string BuildHistoricalOrders(const long from_msc, const long to_msc, int &total, bool &valid)
{
   string result = "[";
   int emitted = 0;
   int selected = HistoryOrdersTotal();
   if(selected < 0)
   {
      valid = false;
      return "[]";
   }
   for(int index = 0; index < selected; index++)
   {
      ResetLastError();
      ulong ticket = HistoryOrderGetTicket(index);
      long done_msc = HistoryOrderGetInteger(ticket, ORDER_TIME_DONE_MSC);
      if(ticket == 0 || GetLastError() != 0)
      {
         valid = false;
         return "[]";
      }
      if(done_msc < from_msc || done_msc > to_msc)
         continue;
      total++;
      if(emitted >= MaxItemsPerCollection)
         continue;
      string row = BuildHistoricalOrder(ticket, valid);
      if(!valid)
         return "[]";
      if(emitted > 0)
         result += ",";
      result += row;
      emitted++;
   }
   return result + "]";
}


string BuildHistoricalDeal(const ulong ticket, bool &valid)
{
   ResetLastError();
   string row = "{\"ticket\":\"" + UnsignedIdentifier(ticket) + "\",";
   row += "\"order_id\":\"" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_ORDER)) + "\",";
   row += "\"position_id\":\"" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_POSITION_ID)) + "\",";
   row += "\"magic_number\":\"" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_MAGIC)) + "\",";
   row += "\"time_msc\":\"" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_TIME_MSC)) + "\",";
   row += "\"deal_type\":" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_TYPE)) + ",";
   row += "\"entry\":" + IntegerToString(HistoryDealGetInteger(ticket, DEAL_ENTRY)) + ",";
   row += "\"symbol\":\"" + JsonEscape(HistoryDealGetString(ticket, DEAL_SYMBOL)) + "\",";
   row += "\"volume\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_VOLUME), valid) + ",";
   row += "\"price\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_PRICE), valid) + ",";
   row += "\"profit\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_PROFIT), valid) + ",";
   row += "\"commission\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_COMMISSION), valid) + ",";
   row += "\"swap\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_SWAP), valid) + ",";
   row += "\"fee\":" + JsonNumber(HistoryDealGetDouble(ticket, DEAL_FEE), valid) + "}";
   if(GetLastError() != 0)
      valid = false;
   return row;
}


string BuildHistoricalOrder(const ulong ticket, bool &valid)
{
   ResetLastError();
   string row = "{\"ticket\":\"" + UnsignedIdentifier(ticket) + "\",";
   row += "\"magic_number\":\"" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_MAGIC)) + "\",";
   row += "\"symbol\":\"" + JsonEscape(HistoryOrderGetString(ticket, ORDER_SYMBOL)) + "\",";
   row += "\"order_type\":" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_TYPE)) + ",";
   row += "\"state\":" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_STATE)) + ",";
   row += "\"volume_initial\":" + JsonNumber(HistoryOrderGetDouble(ticket, ORDER_VOLUME_INITIAL), valid) + ",";
   row += "\"volume_current\":" + JsonNumber(HistoryOrderGetDouble(ticket, ORDER_VOLUME_CURRENT), valid) + ",";
   row += "\"price_open\":" + JsonNumber(HistoryOrderGetDouble(ticket, ORDER_PRICE_OPEN), valid) + ",";
   row += "\"stop_loss\":" + JsonNumber(HistoryOrderGetDouble(ticket, ORDER_SL), valid) + ",";
   row += "\"take_profit\":" + JsonNumber(HistoryOrderGetDouble(ticket, ORDER_TP), valid) + ",";
   row += "\"setup_time_msc\":\"" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_TIME_SETUP_MSC)) + "\",";
   row += "\"done_time_msc\":\"" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_TIME_DONE_MSC)) + "\",";
   row += "\"position_id\":\"" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_POSITION_ID)) + "\",";
   row += "\"position_by_id\":\"" + IntegerToString(HistoryOrderGetInteger(ticket, ORDER_POSITION_BY_ID)) + "\",";
   row += "\"comment\":\"" + JsonEscape(Truncate(HistoryOrderGetString(ticket, ORDER_COMMENT), 256)) + "\"}";
   if(GetLastError() != 0)
      valid = false;
   return row;
}


string BuildIdentity()
{
   return "{\"login_masked\":\"" + MaskedLogin() + "\",\"server\":\"" +
          JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",\"currency\":\"" +
          JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\"}";
}


string BuildHeartbeatPayload(const ulong now_tick_ms)
{
   long backlog_msc = recent_confirmed_from_msc - confirmed_from_msc;
   if(backlog_msc < 0)
      backlog_msc = 0;
   ulong transaction_age_ms = last_transaction_tick_ms > 0 && now_tick_ms >= last_transaction_tick_ms ?
      now_tick_ms - last_transaction_tick_ms : 0;
   bool degraded = recovery_blocked || recent_recovery_blocked || transaction_hints_dropped > 0;
   string payload = "{\"identity\":" + BuildIdentity() + ",";
   payload += "\"status\":\"" + (degraded ? "degraded" : "ok") + "\",";
   payload += "\"queued_messages\":0,";
   payload += "\"dropped_messages\":" + IntegerToString(transaction_hints_dropped) + ",";
   payload += "\"activity_progress\":{";
   payload += "\"recent_cursor_msc\":\"" + IntegerToString(recent_confirmed_from_msc) + "\",";
   payload += "\"deep_cursor_msc\":\"" + IntegerToString(confirmed_from_msc) + "\",";
   payload += "\"backlog_msc\":\"" + IntegerToString(backlog_msc) + "\",";
   payload += "\"recent_blocked\":" + (recent_recovery_blocked ? "true" : "false") + ",";
   payload += "\"deep_blocked\":" + (recovery_blocked ? "true" : "false") + ",";
   payload += "\"deep_paused\":" + (EnableDeepRecovery ? "false" : "true") + ",";
   payload += "\"queued_hints\":" + IntegerToString(transaction_hint_count) + ",";
   payload += "\"dropped_hints\":" + IntegerToString(transaction_hints_dropped) + ",";
   payload += "\"last_transaction_age_ms\":\"" + UnsignedIdentifier(transaction_age_ms) + "\",";
   payload += "\"latest_deal_ticket\":\"" + UnsignedIdentifier(last_hint_deal_ticket) + "\",";
   payload += "\"latest_order_ticket\":\"" + UnsignedIdentifier(last_hint_order_ticket) + "\",";
   payload += "\"latest_position_id\":\"" + UnsignedIdentifier(last_hint_position_id) + "\"}}";
   return payload;
}


string BuildEnvelope(const string payload, const ulong sequence, const string kind)
{
   ulong started = performance.Start();
   string event_id = session_id + ":" + IntegerToString((long)sequence);
   string body = "{";
   body += "\"schema_version\":\"" + SCHEMA_VERSION + "\",";
   body += "\"collector_version\":\"" + COLLECTOR_VERSION + "\",";
   body += "\"source_id\":\"" + JsonEscape(SourceId) + "\",";
   body += "\"session_id\":\"" + JsonEscape(session_id) + "\",";
   body += "\"sequence\":" + IntegerToString((long)sequence) + ",";
   body += "\"event_id\":\"" + JsonEscape(event_id) + "\",";
   body += "\"captured_at\":\"" + IsoUtcTimestamp() + "\",";
   body += "\"kind\":\"" + kind + "\",\"payload\":" + payload + "}";
   performance.Record(started, PERF_ENVELOPE, performance_lane);
   return body;
}


bool PayloadSizeIsValid(const string body)
{
   int size = Utf8Size(body);
   if(size < 1 || size > MAX_PAYLOAD_BYTES)
   {
      logger.Error("payload_size", StringFormat("TradingLab activity: payload size rejected (%d)", size));
      return false;
   }
   return true;
}


int Utf8Size(const string value)
{
   char encoded[];
   ulong started = performance.Start();
   int size = StringToCharArray(value, encoded, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   performance.Record(started, PERF_UTF8, performance_lane, size > 0);
   return size;
}


bool IsCollectorIngestUrl(const string url)
{
   return IsRelayUrl(url, "/trading-events") || IsRelayUrl(url, "/api/trading-events");
}


uint StableHash(const string value)
{
   uint hash = 2166136261;
   for(int index = 0; index < StringLen(value); index++)
   {
      hash ^= (uint)StringGetCharacter(value, index);
      hash *= 16777619;
   }
   return hash;
}

bool InitializeRecovery()
{
   long now_seconds = (long)TimeCurrent();
   if(now_seconds <= 0)
      return false;
   if((long)HistoryStartServerTime > now_seconds)
   {
      logger.Error("invalid_configuration", "TradingLab activity: HistoryStartServerTime must not be in the future");
      StopForSafety();
      return false;
   }

   string cursor_prefix="TL."+SourceId;
   cursor_key=cursor_prefix+".C";
   blocked_key=cursor_prefix+".B";
   recent_cursor_key=cursor_prefix+".R";
   recent_blocked_key=cursor_prefix+".RB";
   confirmed_from_msc = (long)HistoryStartServerTime * 1000;
   long recent_floor_msc = now_seconds * 1000 - (long)RecentLookbackSeconds * 1000;
   recent_confirmed_from_msc = recent_floor_msc > confirmed_from_msc ?
      recent_floor_msc : confirmed_from_msc;
   if(GlobalVariableCheck(cursor_key))
   {
      double stored = GlobalVariableGet(cursor_key);
      long restored = (long)stored;
      if(restored < confirmed_from_msc || restored > now_seconds * 1000 ||
         (double)restored != stored)
      {
         logger.Error("invalid_configuration", "TradingLab activity: stored cursor is invalid; remove it after operator review");
         StopForSafety();
         return false;
      }
      confirmed_from_msc = restored;
   }
   if(GlobalVariableCheck(recent_cursor_key))
   {
      double stored = GlobalVariableGet(recent_cursor_key);
      long restored = (long)stored;
      if(restored < (long)HistoryStartServerTime * 1000 ||
         restored > now_seconds * 1000 || (double)restored != stored)
      {
         logger.Error("invalid_configuration", "TradingLab activity: stored recent cursor is invalid; review it manually");
         StopForSafety();
         return false;
      }
      recent_confirmed_from_msc = restored;
   }
   if(GlobalVariableCheck(blocked_key) &&
      (long)GlobalVariableGet(blocked_key) == confirmed_from_msc)
      recovery_blocked = true;
   if(GlobalVariableCheck(recent_blocked_key) &&
      (long)GlobalVariableGet(recent_blocked_key) == recent_confirmed_from_msc)
      recent_recovery_blocked = true;

   session_id = TerminalId + "-" + CompactUtcTimestamp() + "-" +
                IntegerToString((long)GetTickCount64());
   last_heartbeat_tick_ms = GetTickCount64();
   recovery_initialized = true;
   return true;
}
