#property copyright "TradingLab 2.0"
#property version   "1.000"
#property strict

// Spike-only collector. It emits observations and never accepts remote commands.

input string IngestUrl = "http://127.0.0.1:8766/v1/telemetry";
input string Token = "CHANGE-ME-WITH-A-LOCAL-TEST-TOKEN";
input string SourceId = "demo-terminal-01";
input int IntervalSeconds = 5;
input int RequestTimeoutMs = 500;
input int MaxItemsPerSnapshot = 200;
input int HistoryLookbackSeconds = 3600;
input int MaxDealsPerSnapshot = 200;
// Operator-approved demo identity; never commit real account configuration.
input long ExpectedDemoLogin = 0;
input string ExpectedDemoServer = "";

const string SCHEMA_VERSION = "mt5-telemetry-v1";
const string COLLECTOR_VERSION = "0.1.1";

string session_id = "";
// Bounded, volatile FIFO: preserve retry identity, prefer fresh samples on overflow.
#define OUTBOX_CAPACITY 12
#define MAX_PAYLOAD_BYTES 262144
string outbox_body[OUTBOX_CAPACITY];
ulong outbox_sequence[OUTBOX_CAPACITY];
int outbox_head = 0;
int outbox_count = 0;
ulong dropped_samples = 0;
ulong next_send_ms = 0;
int retry_delay_seconds = 2;
int head_attempts = 0;
bool startup_pending = true;
bool trade_activity_pending = false;
ulong sequence_number = 0;
bool safety_stopped = false;


bool IsLoopbackIngestUrl(const string url)
{
   const string prefix = "http://127.0.0.1:";
   const string suffix = "/v1/telemetry";
   if(StringFind(url, prefix) != 0)
      return false;
   int start = StringLen(prefix);
   int length = StringLen(url) - start - StringLen(suffix);
   if(length < 1 || length > 5 || StringSubstr(url, start + length) != suffix)
      return false;
   string port = StringSubstr(url, start, length);
   if(StringGetCharacter(port, 0) == '0')
      return false;
   for(int i = 0; i < length; i++)
   {
      ushort character = StringGetCharacter(port, i);
      if(character < '0' || character > '9')
         return false;
   }
   long number = StringToInteger(port);
   return number >= 1 && number <= 65535;
}


bool IsApprovedDemo(const bool connected, const long mode, const long login,
                    const string server, const long expected_login, const string expected_server)
{
   return connected && mode == ACCOUNT_TRADE_MODE_DEMO && expected_login > 0 &&
          expected_server != "" && login == expected_login && server == expected_server;
}


#ifndef TELEMETRY_QUEUE_TEST
int OnInit()
{
   if(!IsLoopbackIngestUrl(IngestUrl))
   {
      Print("TradingLab telemetry: the spike only accepts a loopback HTTP endpoint");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(StringLen(Token) < 24 || StringFind(Token, "CHANGE-ME") == 0)
   {
      Print("TradingLab telemetry: configure a local test token with at least 24 characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsSafeIdentifier(SourceId))
   {
      Print("TradingLab telemetry: SourceId contains unsupported characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(IntervalSeconds < 2 || IntervalSeconds > 60)
   {
      Print("TradingLab telemetry: IntervalSeconds must be between 2 and 60");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(RequestTimeoutMs < 500 || RequestTimeoutMs > IntervalSeconds * 1000 / 4)
   {
      Print("TradingLab telemetry: timeout must be >=500ms and <=quarter of sample interval");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MaxItemsPerSnapshot < 1 || MaxItemsPerSnapshot > 500)
   {
      Print("TradingLab telemetry: MaxItemsPerSnapshot must be between 1 and 500");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(!CheckPilotSafety())
      return INIT_FAILED;
   if(HistoryLookbackSeconds < 60 || HistoryLookbackSeconds > 86400 ||
      MaxDealsPerSnapshot < 1 || MaxDealsPerSnapshot > 200)
   {
      Print("TradingLab telemetry: history window must be 60..86400 seconds, deals 1..200");
      return INIT_PARAMETERS_INCORRECT;
   }
   session_id = "session-" + CompactUtcTimestamp() + "-" + IntegerToString((long)GetTickCount64());
   if(!EventSetTimer(IntervalSeconds))
   {
      PrintFormat("TradingLab telemetry: cannot start timer (%d)", GetLastError());
      return INIT_FAILED;
   }
   Print("TradingLab telemetry: read-only spike started");
   return INIT_SUCCEEDED;
}


void OnDeinit(const int reason)
{
   EventKillTimer();
   while(outbox_count > 0)
      DropHead("shutdown");
   PrintFormat("TradingLab telemetry: stopped (%d)", reason);
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
   if(safety_stopped)
      return false;
   ResetLastError();
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string server = AccountInfoString(ACCOUNT_SERVER);
   if(GetLastError() == 0 && IsApprovedDemo(connected, mode, login, server,
                                          ExpectedDemoLogin, ExpectedDemoServer))
      return true;
   safety_stopped = true;
   EventKillTimer();
   while(outbox_count > 0)
      DropHead("pilot_guard");
   Print("TradingLab telemetry: pilot guard stopped capture; review demo identity and reattach EA");
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
   PrintFormat("TradingLab telemetry: dropped sequence=%I64u reason=%s total=%I64u",
               sequence, reason, dropped_samples);
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
   if(outbox_count == 0 || now_ms < next_send_ms)
      return false;
   // One bounded synchronous request per call; no Sleep and no retry loop.
   int status = SendMessage(outbox_body[outbox_head]);
   // The live safety guard may have cleared the queue inside SendMessage.
   if(safety_stopped)
      return false;
   head_attempts++;
   if(status == 200 || status == 202)
   {
      RemoveHead();
      retry_delay_seconds = 2;
      next_send_ms = 0;
      return true;
   }
   // Retry ambiguous transport errors, throttling and server failures only.
   bool retryable = status == -1 || status == 408 || status == 429 || status >= 500;
   if(!retryable || head_attempts >= 5)
      DropHead(retryable ? "retry_limit" : "http_rejected");
   // Keep endpoint-level backoff even when overflow replaces the head.
   next_send_ms = now_ms + (ulong)retry_delay_seconds * 1000;
   retry_delay_seconds = MathMin(retry_delay_seconds * 2, 60);
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
      Print("TradingLab telemetry: cannot encode the payload");
      return 400;
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
   if(status == 200 || status == 202)
      return status;

   if(status == -1)
      PrintFormat("TradingLab telemetry: request failed (%d)", GetLastError());
   else
      PrintFormat("TradingLab telemetry: receiver returned HTTP %d", status);
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
   payload += "\"history\":" + BuildHistory();
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


string MaskedLogin()
{
   string login = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   int length = StringLen(login);
   if(length <= 4)
      return "****" + login;
   return "****" + StringSubstr(login, length - 4);
}


string JsonNumber(const double value, bool &valid)
{
   if(!MathIsValidNumber(value))
   {
      valid = false;
      // Internal placeholder only: FinalizeSnapshot discards the whole message.
      return "null";
   }
   return DoubleToString(value, 8);
}


string UnsignedIdentifier(const ulong value)
{
   return StringFormat("%I64u", value);
}


string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");
   return value;
}


string Truncate(const string value, const int maximum)
{
   if(StringLen(value) <= maximum)
      return value;
   return StringSubstr(value, 0, maximum);
}


string IsoUtcTimestamp()
{
   MqlDateTime parts = {};
   TimeToStruct(TimeGMT(), parts);
   return StringFormat(
      "%04d-%02d-%02dT%02d:%02d:%02dZ",
      parts.year,
      parts.mon,
      parts.day,
      parts.hour,
      parts.min,
      parts.sec
   );
}


string CompactUtcTimestamp()
{
   MqlDateTime parts = {};
   TimeToStruct(TimeGMT(), parts);
   return StringFormat(
      "%04d%02d%02dT%02d%02d%02dZ",
      parts.year,
      parts.mon,
      parts.day,
      parts.hour,
      parts.min,
      parts.sec
   );
}


bool IsSafeIdentifier(const string value)
{
   int length = StringLen(value);
   if(length < 1 || length > 128)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(value, index);
      bool allowed =
         (character >= 'A' && character <= 'Z') ||
         (character >= 'a' && character <= 'z') ||
         (character >= '0' && character <= '9') ||
         character == '.' || character == '_' || character == ':' || character == '-';
      if(!allowed)
         return false;
   }
   return true;
}
