#property copyright "TradingLab 2.0"
#property version   "1.100"
#property strict
#include "TradingLabCollectorCommon.mqh"
#include "TradingLabCollectorLog.mqh"

// Spike-only collector. It emits observations and never accepts remote commands.

input string IngestUrl = "http://127.0.0.1:8766/api/account-state";
input string Token = "CHANGE-ME-WITH-A-LOCAL-TEST-TOKEN";
input string SourceId = "demo-terminal-01";
input int IntervalSeconds = 5;
input int RequestTimeoutMs = 500;
input int MaxItemsPerSnapshot = 200;
input int HistoryLookbackSeconds = 3600;
input int HistoryIntervalSeconds = 60;
input int MaxDealsPerSnapshot = 200;
// Operator-approved demo identity; never commit real account configuration.
input long ExpectedDemoLogin = 0;
input string ExpectedDemoServer = "";

const string SCHEMA_VERSION = "mt5-account-state-v1";
const string COLLECTOR_VERSION = "0.3.0";
const int LOCAL_ENCODING_FAILURE = -2;

string session_id = "";
// Bounded, volatile FIFO: preserve retry identity, prefer fresh samples on overflow.
#define OUTBOX_CAPACITY 12
#define MAX_PAYLOAD_BYTES 262144
string outbox_body[OUTBOX_CAPACITY];
ulong outbox_sequence[OUTBOX_CAPACITY];
int outbox_head = 0;
int outbox_count = 0;
ulong dropped_samples = 0;
CollectorTransport transport;
CollectorLogger logger;
int last_request_error = 0;
int head_attempts = 0;
bool startup_pending = true;
bool trade_activity_pending = false;
ulong sequence_number = 0;
CollectorCaptureState capture_state = CAPTURE_READY;


bool IsLoopbackIngestUrl(const string url)
{
   return IsLoopbackCollectorUrl(url, "/api/account-state");
}


#ifndef TELEMETRY_QUEUE_TEST
int OnInit()
{
   logger.Configure("telemetry", SourceId, COLLECTOR_VERSION);
   if(!IsLoopbackIngestUrl(IngestUrl))
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: the spike only accepts a loopback HTTP endpoint");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsCollectorToken(Token))
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: configure a local test token with at least 24 characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsSafeIdentifier(SourceId))
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: SourceId contains unsupported characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(IntervalSeconds < 2 || IntervalSeconds > 60)
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: IntervalSeconds must be between 2 and 60");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(RequestTimeoutMs < 500 || RequestTimeoutMs > IntervalSeconds * 1000 / 4)
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: timeout must be >=500ms and <=quarter of sample interval");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MaxItemsPerSnapshot < 1 || MaxItemsPerSnapshot > 500)
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: MaxItemsPerSnapshot must be between 1 and 500");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(ExpectedDemoLogin <= 0 || ExpectedDemoServer == "")
      return INIT_PARAMETERS_INCORRECT;
   if(!CheckPilotSafety() && capture_state == CAPTURE_STOPPED)
      return INIT_FAILED;
   if(HistoryIntervalSeconds < IntervalSeconds || HistoryIntervalSeconds > 3600 ||
      HistoryLookbackSeconds < 60 || HistoryLookbackSeconds > 86400 ||
      MaxDealsPerSnapshot < 1 || MaxDealsPerSnapshot > 200)
   {
      logger.Error("invalid_configuration", "TradingLab telemetry: history window must be 60..86400 seconds, deals 1..200");
      return INIT_PARAMETERS_INCORRECT;
   }
   session_id = "session-" + CompactUtcTimestamp() + "-" + IntegerToString((long)GetTickCount64());
   if(!EventSetTimer(IntervalSeconds))
   {
      logger.Error("timer_failed", StringFormat("TradingLab telemetry: cannot start timer (%d)", GetLastError()));
      return INIT_FAILED;
   }
   // Healthy lifecycle events do not emit routine log entries.
   return INIT_SUCCEEDED;
}


void OnDeinit(const int reason)
{
   EventKillTimer();
   while(outbox_count > 0)
      DropHead("shutdown");
   // Healthy lifecycle events do not emit routine log entries.
}


void OnTimer()
{
   if(!CheckPilotSafety())
      return;
   string reason = "timer";
   if(startup_pending)
      reason = "startup";
   else if(trade_activity_pending)
      reason = "trade_activity";

   sequence_number++;
   string body = BuildSnapshot(reason, sequence_number);
   // Discard a sample collected while the terminal identity was changing.
   if(!CheckPilotSafety())
   {
      RecordDrop(sequence_number, "pilot_guard");
      return;
   }
   EnqueueSnapshot(body, sequence_number);
   startup_pending = false;
   trade_activity_pending = false;
   // Drain one extra item after success, bounded to two requests per tick.
   if(TrySendQueued(GetTickCount64()))
      TrySendQueued(GetTickCount64());
}


bool CheckPilotSafety()
{
   if(capture_state == CAPTURE_STOPPED)
      return false;
   ResetLastError();
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string server = AccountInfoString(ACCOUNT_SERVER);
   CollectorCaptureState observed = EvaluateCaptureState(connected, GetLastError() == 0,
      mode, login, server, ExpectedDemoLogin, ExpectedDemoServer);
   if(observed == CAPTURE_WAIT_BROKER)
   {
      if(capture_state != CAPTURE_WAIT_BROKER)
         logger.Warn("broker_unavailable", "TradingLab telemetry: broker unavailable; waiting without advancing capture");
      capture_state = CAPTURE_WAIT_BROKER;
      return false;
   }
   if(observed == CAPTURE_READY)
   {
      if(capture_state == CAPTURE_WAIT_BROKER)
         logger.Resolve("broker_unavailable");
      capture_state = CAPTURE_READY;
      return true;
   }
   capture_state = CAPTURE_STOPPED;
   EventKillTimer();
   while(outbox_count > 0)
      DropHead("pilot_guard");
   logger.Error("identity_guard_stopped", "TradingLab telemetry: pilot guard stopped capture; review demo identity and reattach EA");
   return false;
}
#endif


void RemoveHead()
{
   outbox_body[outbox_head] = "";
   outbox_head = (outbox_head + 1) % OUTBOX_CAPACITY;
   outbox_count--;
   head_attempts = 0;
}


void RecordDrop(const ulong sequence, const string reason)
{
   dropped_samples++;
   logger.Warn("snapshot_dropped", StringFormat("reason=%s total=%I64u", reason, dropped_samples), sequence);
}


void DropHead(const string reason)
{
   RecordDrop(outbox_sequence[outbox_head], reason);
   RemoveHead();
}


void EnqueueSnapshot(const string body, const ulong sequence)
{
   // BuildSnapshot returns no body when any numeric field is non-finite.
   if(body == "")
   {
      RecordDrop(sequence, "invalid_numeric");
      return;
   }
   char encoded[];
   int size = StringToCharArray(body, encoded, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(size < 1 || size > MAX_PAYLOAD_BYTES)
   {
      RecordDrop(sequence, "payload_size");
      return;
   }
   if(outbox_count == OUTBOX_CAPACITY)
      DropHead("queue_full");
   int tail = (outbox_head + outbox_count) % OUTBOX_CAPACITY;
   outbox_body[tail] = body;
   outbox_sequence[tail] = sequence;
   outbox_count++;
}


bool TrySendQueued(const ulong now_ms)
{
   if(outbox_count == 0 || !transport.Ready(now_ms))
      return false;
   int status = SendMessage(outbox_body[outbox_head]);
   if(capture_state == CAPTURE_STOPPED || capture_state == CAPTURE_WAIT_BROKER)
      return false;
   head_attempts++;
   CollectorDelivery delivery = transport.Observe(status, now_ms);
   if(delivery == DELIVERY_ACK)
   {
      logger.Resolve("receiver_access_blocked", outbox_sequence[outbox_head]);
      logger.Resolve("receiver_unavailable", outbox_sequence[outbox_head]);
      RemoveHead();
      return true;
   }
   if(delivery == DELIVERY_ACCESS_BLOCKED)
   {
      logger.Warn("receiver_access_blocked", "access blocked; probing every 60 seconds",
                  outbox_sequence[outbox_head], status, last_request_error);
      return false;
   }
   if(delivery == DELIVERY_FATAL)
   {
      logger.Error("delivery_stopped", "delivery stopped; review required",
                   outbox_sequence[outbox_head], status, last_request_error);
      capture_state = CAPTURE_STOPPED;
      EventKillTimer();
      return false;
   }
   logger.Warn("receiver_unavailable", "delivery retry scheduled", outbox_sequence[outbox_head],
               status, last_request_error);
   if(head_attempts >= 5)
      DropHead("retry_limit");
   return false;
}


#ifndef TELEMETRY_QUEUE_TEST
void OnTradeTransaction(
   const MqlTradeTransaction &transaction,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{
   // Do not perform network I/O in the transaction callback. The next timer tick
   // publishes a reconciled snapshot and makes the reason visible.
   trade_activity_pending = true;
}


int SendMessage(const string body)
{
   if(!CheckPilotSafety() || !IsLoopbackIngestUrl(IngestUrl))
      return 0;
   char request_body[];
   char response_body[];
   string response_headers = "";
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + Token + "\r\n";

   int encoded = StringToCharArray(body, request_body, 0, WHOLE_ARRAY, CP_UTF8);
   if(encoded <= 1)
   {
      last_request_error = GetLastError();
      logger.Error("encoding_failed", "cannot encode payload; no HTTP request sent",
                   sequence_number, 0, last_request_error);
      return LOCAL_ENCODING_FAILURE;
   }
   ArrayResize(request_body, encoded - 1);

   ResetLastError();
   int status = WebRequest(
      "POST",
      IngestUrl,
      headers,
      RequestTimeoutMs,
      request_body,
      response_body,
      response_headers
   );
   last_request_error = GetLastError();
   // Preserve the actual return separately from local errors. Values such as
   // 1001 are not labelled HTTP; the transport retains its existing retry policy.
   return status;
}
#endif


string BuildSnapshot(const string reason, const ulong sequence)
{
   bool valid = true;
   string event_id = session_id + ":" + IntegerToString((long)sequence);
   string payload = "{";
   payload += "\"reason\":\"" + reason + "\",";
   payload += "\"account\":" + BuildAccount(valid) + ",";
   payload += "\"positions_total\":" + IntegerToString(PositionsTotal()) + ",";
   payload += "\"orders_total\":" + IntegerToString(OrdersTotal()) + ",";
   payload += "\"positions\":" + BuildPositions(valid) + ",";
   payload += "\"orders\":" + BuildOrders(valid) + ",";
   payload += "\"history\":" + BuildHistorySample();
   payload += "}";

   string body = "{";
   body += "\"schema_version\":\"" + SCHEMA_VERSION + "\",";
   body += "\"collector_version\":\"" + COLLECTOR_VERSION + "\",";
   body += "\"source_id\":\"" + JsonEscape(SourceId) + "\",";
   body += "\"session_id\":\"" + JsonEscape(session_id) + "\",";
   body += "\"sequence\":" + IntegerToString((long)sequence) + ",";
   body += "\"event_id\":\"" + JsonEscape(event_id) + "\",";
   body += "\"captured_at\":\"" + IsoUtcTimestamp() + "\",";
   body += "\"kind\":\"account_snapshot\",";
   body += "\"payload\":" + payload;
   body += "}";
   return FinalizeSnapshot(body, valid);
}


string FinalizeSnapshot(const string body, const bool valid)
{
   // All-or-nothing: never publish partial financial data or invented zeroes.
   return valid ? body : "";
}


string HistoryResult(const string status, const long from_time, const long to_time,
                     const int total, const string deals)
{
   return "{\"status\":\"" + status + "\",\"from_server_seconds\":\"" +
          IntegerToString(from_time) + "\",\"to_server_seconds\":\"" +
          IntegerToString(to_time) + "\",\"total\":" + IntegerToString(total) +
          ",\"deals\":" + deals + "}";
}


string BuildHistory()
{
   // HistorySelect uses broker-server time, not UTC. Re-read the whole bounded
   // window: no cursor advances on failed sends and missed callbacks are harmless.
   long to_time = (long)TimeCurrent();
   long from_time = MathMax(0, to_time - HistoryLookbackSeconds);
   ResetLastError();
   if(to_time <= 0 || !HistorySelect((datetime)from_time, (datetime)to_time))
      return HistoryResult("error", from_time, MathMax(0, to_time), 0, "[]");
   int total = HistoryDealsTotal();
   if(GetLastError() != 0 || total < 0)
      return HistoryResult("error", from_time, to_time, 0, "[]");
   int start = MathMax(0, total - MaxDealsPerSnapshot);
   string deals = "[";
   bool valid = true;
   for(int index = start; index < total; index++)
   {
      ResetLastError();
      ulong ticket = HistoryDealGetTicket(index);
      if(ticket == 0)
         return HistoryResult("error", from_time, to_time, 0, "[]");
      string row = BuildDeal(ticket, valid);
      if(!valid || GetLastError() != 0)
         return HistoryResult("error", from_time, to_time, 0, "[]");
      if(index > start)
         deals += ",";
      deals += row;
   }
   deals += "]";
   return HistoryResult(start == 0 ? "complete" : "truncated", from_time, to_time, total, deals);
}


string BuildDeal(const ulong ticket, bool &valid)
{
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
   return row;
}


string BuildAccount(bool &valid)
{
   string account = "{";
   account += "\"login_masked\":\"" + MaskedLogin() + "\",";
   account += "\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",";
   account += "\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",";
   account += "\"balance\":" + JsonNumber(AccountInfoDouble(ACCOUNT_BALANCE), valid) + ",";
   account += "\"equity\":" + JsonNumber(AccountInfoDouble(ACCOUNT_EQUITY), valid) + ",";
   account += "\"profit\":" + JsonNumber(AccountInfoDouble(ACCOUNT_PROFIT), valid) + ",";
   account += "\"margin\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN), valid) + ",";
   account += "\"margin_free\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN_FREE), valid) + ",";
   account += "\"margin_level\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), valid);
   account += "}";
   return account;
}


string BuildPositions(bool &valid)
{
   string result = "[";
   int emitted = 0;
   int total = PositionsTotal();
   for(int index = 0; index < total && emitted < MaxItemsPerSnapshot; index++)
   {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0)
         continue;
      if(emitted > 0)
         result += ",";
      result += "{";
      result += "\"ticket\":\"" + UnsignedIdentifier(ticket) + "\",";
      result += "\"position_id\":\"" + IntegerToString(PositionGetInteger(POSITION_IDENTIFIER)) + "\",";
      result += "\"magic_number\":\"" + IntegerToString(PositionGetInteger(POSITION_MAGIC)) + "\",";
      result += "\"symbol\":\"" + JsonEscape(PositionGetString(POSITION_SYMBOL)) + "\",";
      result += "\"operation_type\":" + IntegerToString(PositionGetInteger(POSITION_TYPE)) + ",";
      result += "\"volume\":" + JsonNumber(PositionGetDouble(POSITION_VOLUME), valid) + ",";
      result += "\"price_open\":" + JsonNumber(PositionGetDouble(POSITION_PRICE_OPEN), valid) + ",";
      result += "\"price_current\":" + JsonNumber(PositionGetDouble(POSITION_PRICE_CURRENT), valid) + ",";
      result += "\"stop_loss\":" + JsonNumber(PositionGetDouble(POSITION_SL), valid) + ",";
      result += "\"take_profit\":" + JsonNumber(PositionGetDouble(POSITION_TP), valid) + ",";
      result += "\"profit\":" + JsonNumber(PositionGetDouble(POSITION_PROFIT), valid) + ",";
      result += "\"swap\":" + JsonNumber(PositionGetDouble(POSITION_SWAP), valid) + ",";
      result += "\"opened_at_msc\":\"" + IntegerToString(PositionGetInteger(POSITION_TIME_MSC)) + "\",";
      result += "\"comment\":\"" + JsonEscape(Truncate(PositionGetString(POSITION_COMMENT), 256)) + "\"";
      result += "}";
      emitted++;
   }
   result += "]";
   return result;
}


string BuildOrders(bool &valid)
{
   string result = "[";
   int emitted = 0;
   int total = OrdersTotal();
   for(int index = 0; index < total && emitted < MaxItemsPerSnapshot; index++)
   {
      ulong ticket = OrderGetTicket(index);
      if(ticket == 0)
         continue;
      if(emitted > 0)
         result += ",";
      result += "{";
      result += "\"ticket\":\"" + UnsignedIdentifier(ticket) + "\",";
      result += "\"magic_number\":\"" + IntegerToString(OrderGetInteger(ORDER_MAGIC)) + "\",";
      result += "\"symbol\":\"" + JsonEscape(OrderGetString(ORDER_SYMBOL)) + "\",";
      result += "\"order_type\":" + IntegerToString(OrderGetInteger(ORDER_TYPE)) + ",";
      result += "\"volume\":" + JsonNumber(OrderGetDouble(ORDER_VOLUME_CURRENT), valid) + ",";
      result += "\"price_open\":" + JsonNumber(OrderGetDouble(ORDER_PRICE_OPEN), valid) + ",";
      result += "\"price_current\":" + JsonNumber(OrderGetDouble(ORDER_PRICE_CURRENT), valid) + ",";
      result += "\"stop_loss\":" + JsonNumber(OrderGetDouble(ORDER_SL), valid) + ",";
      result += "\"take_profit\":" + JsonNumber(OrderGetDouble(ORDER_TP), valid) + ",";
      result += "\"created_at_msc\":\"" + IntegerToString(OrderGetInteger(ORDER_TIME_SETUP_MSC)) + "\",";
      result += "\"comment\":\"" + JsonEscape(Truncate(OrderGetString(ORDER_COMMENT), 256)) + "\"";
      result += "}";
      emitted++;
   }
   result += "]";
   return result;
}


string history_sample = "";
ulong history_sample_tick = 0;
string BuildHistorySample()
{
   ulong now_ms = GetTickCount64();
   if(history_sample == "" || startup_pending || trade_activity_pending ||
      now_ms - history_sample_tick >= (ulong)HistoryIntervalSeconds * 1000)
   {
      history_sample = BuildHistory();
      history_sample_tick = now_ms;
   }
   return history_sample;
}
