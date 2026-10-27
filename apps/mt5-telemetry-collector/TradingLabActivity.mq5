#property copyright "TradingLab 2.0"
#property version   "1.000"
#property strict

// Read-only v2 activity collector. It never sends or modifies trading orders.

input string IngestUrl = "http://127.0.0.1:8777/v2/telemetry";
input string Token = "CHANGE-ME-WITH-A-LOCAL-TEST-TOKEN";
input string SourceId = "demo-activity-01";
input int IntervalSeconds = 10;
input int RequestTimeoutMs = 1000;
input datetime HistoryStartServerTime = 0;
input int WindowSeconds = 21600;
input int MinimumWindowSeconds = 60;
input int OverlapSeconds = 5;
input int MaxItemsPerCollection = 200;
// Operator-approved demo identity; never commit real account configuration.
input long ExpectedDemoLogin = 0;
input string ExpectedDemoServer = "";

const string SCHEMA_VERSION = "mt5-telemetry-v2";
const string COLLECTOR_VERSION = "activity-0.2.0";
const int MAX_PAYLOAD_BYTES = 262144;

string session_id = "";
string cursor_key = "";
string blocked_key = "";
long confirmed_from_msc = 0;
ulong sequence_number = 0;
string pending_body = "";
long pending_from_msc = 0;
long pending_to_msc = 0;
bool pending_blocks_recovery = false;
bool pending_is_position_reconcile = false;
bool recovery_blocked = false;
bool batch_waiting_for_positions = false;
long candidate_position_ids[];
int candidate_position_count = 0;
int candidate_position_index = 0;
bool startup_pending = true;
bool trade_activity_pending = false;
bool safety_stopped = false;
ulong next_send_ms = 0;
int retry_delay_seconds = 2;
int send_attempts = 0;


int OnInit()
{
   if(!IsLoopbackIngestUrl(IngestUrl))
   {
      Print("TradingLab activity: only a loopback v2 endpoint is accepted");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(StringLen(Token) < 24 || StringFind(Token, "CHANGE-ME") == 0)
   {
      Print("TradingLab activity: configure a local token with at least 24 characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsSafeIdentifier(SourceId))
   {
      Print("TradingLab activity: SourceId contains unsupported characters");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(IntervalSeconds < 2 || IntervalSeconds > 300 || RequestTimeoutMs < 500 ||
      RequestTimeoutMs > IntervalSeconds * 1000 / 2)
   {
      Print("TradingLab activity: interval or timeout is outside the pilot limits");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(WindowSeconds < 60 || WindowSeconds > 86400 || MinimumWindowSeconds < 1 ||
      MinimumWindowSeconds > WindowSeconds || OverlapSeconds < 0 ||
      OverlapSeconds >= MinimumWindowSeconds || MaxItemsPerCollection < 1 ||
      MaxItemsPerCollection > 200 || HistoryStartServerTime <= 0)
   {
      Print("TradingLab activity: review history window, overlap, limit and explicit start");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!CheckPilotSafety())
      return INIT_FAILED;
   long now_seconds = (long)TimeCurrent();
   if(now_seconds <= 0 || (long)HistoryStartServerTime > now_seconds)
   {
      Print("TradingLab activity: HistoryStartServerTime must not be in the future");
      return INIT_PARAMETERS_INCORRECT;
   }

   uint source_hash = StableHash(SourceId + ":" + IntegerToString(ExpectedDemoLogin) +
                                 ":" + ExpectedDemoServer);
   cursor_key = StringFormat("TL2.ACT.%08X.CURSOR", source_hash);
   blocked_key = StringFormat("TL2.ACT.%08X.BLOCK", source_hash);
   confirmed_from_msc = (long)HistoryStartServerTime * 1000;
   if(GlobalVariableCheck(cursor_key))
   {
      double stored = GlobalVariableGet(cursor_key);
      long restored = (long)stored;
      if(restored < confirmed_from_msc || restored > now_seconds * 1000 ||
         (double)restored != stored)
      {
         Print("TradingLab activity: stored cursor is invalid; remove it after operator review");
         return INIT_FAILED;
      }
      confirmed_from_msc = restored;
   }
   if(GlobalVariableCheck(blocked_key) &&
      (long)GlobalVariableGet(blocked_key) == confirmed_from_msc)
      recovery_blocked = true;

   session_id = "activity-" + CompactUtcTimestamp() + "-" +
                IntegerToString((long)GetTickCount64());
   if(!EventSetTimer(IntervalSeconds))
   {
      PrintFormat("TradingLab activity: cannot start timer (%d)", GetLastError());
      return INIT_FAILED;
   }
   if(recovery_blocked)
      Print("TradingLab activity: recovery is blocked at a saturated minimum window");
   else
      Print("TradingLab activity: read-only recovery started");
   return INIT_SUCCEEDED;
}


void OnDeinit(const int reason)
{
   EventKillTimer();
   if(pending_body != "")
      PrintFormat("TradingLab activity: unconfirmed range retained by cursor (%I64d..%I64d)",
                  pending_from_msc, pending_to_msc);
   PrintFormat("TradingLab activity: stopped (%d)", reason);
}


void OnTimer()
{
   if(!CheckPilotSafety() || recovery_blocked)
      return;
   if(pending_body != "")
   {
      TrySendPending(GetTickCount64());
      return;
   }
   if(batch_waiting_for_positions)
   {
      ContinuePositionReconciliation();
      return;
   }
   long now_msc = (long)TimeCurrent() * 1000;
   if(now_msc <= confirmed_from_msc + (long)OverlapSeconds * 1000)
      return;

   long window_end_msc = confirmed_from_msc + (long)WindowSeconds * 1000;
   long target_to_msc = window_end_msc < now_msc ? window_end_msc : now_msc;
   string reason = RecoveryReason(now_msc);
   bool truncated = false;
   string payload = "";
   while(true)
   {
      payload = BuildActivityPayload(reason, confirmed_from_msc, target_to_msc, truncated);
      if(payload == "")
         return;
      long duration = target_to_msc - confirmed_from_msc;
      bool payload_too_large = Utf8Size(payload) > MAX_PAYLOAD_BYTES - 1024;
      if(!truncated && !payload_too_large)
         break;
      if(duration <= (long)MinimumWindowSeconds * 1000)
      {
         if(payload_too_large)
         {
            Print("TradingLab activity: minimum window exceeds the payload limit; stopped");
            StopForSafety();
            return;
         }
         break;
      }
      long halved = confirmed_from_msc + duration / 2;
      target_to_msc = (halved / 1000) * 1000;
      if(target_to_msc < confirmed_from_msc + (long)MinimumWindowSeconds * 1000)
         target_to_msc = confirmed_from_msc + (long)MinimumWindowSeconds * 1000;
   }

   sequence_number++;
   pending_body = BuildEnvelope(payload, sequence_number);
   if(!CheckPilotSafety() || !PayloadSizeIsValid(pending_body))
   {
      pending_body = "";
      return;
   }
   pending_from_msc = confirmed_from_msc;
   pending_to_msc = target_to_msc;
   pending_blocks_recovery = truncated;
   TrySendPending(GetTickCount64());
}


void OnTradeTransaction(
   const MqlTradeTransaction &transaction,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{
   // Network and history reads remain outside the transaction callback.
   trade_activity_pending = true;
}


string RecoveryReason(const long now_msc)
{
   if(startup_pending)
      return "startup";
   if(trade_activity_pending)
      return "trade_activity";
   if(now_msc - confirmed_from_msc > (long)WindowSeconds * 1000)
      return "recovery";
   return "reconcile";
}


bool TrySendPending(const ulong now_ms)
{
   if(pending_body == "" || now_ms < next_send_ms)
      return false;
   int status = SendMessage(pending_body);
   if(safety_stopped)
      return false;
   send_attempts++;
   if(status == 200 || status == 202)
   {
      if(pending_is_position_reconcile)
      {
         pending_body = "";
         pending_is_position_reconcile = false;
         candidate_position_index++;
         ResetRetryState();
         return true;
      }
      if(pending_blocks_recovery)
      {
         if(!PersistValue(blocked_key, pending_from_msc))
         {
            Print("TradingLab activity: cannot persist blocked recovery marker");
            StopForSafety();
            return false;
         }
         recovery_blocked = true;
         PrintFormat("TradingLab activity: saturated range requires operator review (%I64d..%I64d)",
                     pending_from_msc, pending_to_msc);
         pending_body = "";
         pending_blocks_recovery = false;
         ResetRetryState();
      }
      else
      {
         pending_body = "";
         batch_waiting_for_positions = true;
         candidate_position_index = 0;
         ResetRetryState();
         if(candidate_position_count == 0)
            return FinalizeConfirmedBatch();
      }
      return true;
   }
   bool retryable = status == -1 || status == 408 || status == 429 || status >= 500;
   if(!retryable)
   {
      PrintFormat("TradingLab activity: receiver rejected the batch with HTTP %d; stopped", status);
      StopForSafety();
      return false;
   }
   next_send_ms = now_ms + (ulong)retry_delay_seconds * 1000;
   retry_delay_seconds = MathMin(retry_delay_seconds * 2, 60);
   if(send_attempts == 1 || (send_attempts & (send_attempts - 1)) == 0)
      PrintFormat("TradingLab activity: retrying the same unconfirmed batch (attempt %d)",
                  send_attempts);
   return false;
}


void ResetRetryState()
{
   retry_delay_seconds = 2;
   send_attempts = 0;
   next_send_ms = 0;
}


bool FinalizeConfirmedBatch()
{
   long next_cursor = pending_to_msc - (long)OverlapSeconds * 1000;
   if(next_cursor <= confirmed_from_msc || !PersistValue(cursor_key, next_cursor))
   {
      Print("TradingLab activity: cannot persist confirmed recovery cursor");
      StopForSafety();
      return false;
   }
   confirmed_from_msc = next_cursor;
   batch_waiting_for_positions = false;
   pending_blocks_recovery = false;
   pending_is_position_reconcile = false;
   ResetCandidatePositions();
   startup_pending = false;
   trade_activity_pending = false;
   ResetRetryState();
   return true;
}


int BuildPositionReconcilePayload(const long position_id, string &payload)
{
   ResetLastError();
   if(position_id <= 0 || !HistorySelectByPosition((ulong)position_id))
   {
      PrintFormat("TradingLab activity: cannot select position %I64d history (%d)",
                  position_id, GetLastError());
      return -1;
   }

   int deal_total = HistoryDealsTotal();
   int order_total = HistoryOrdersTotal();
   if(deal_total < 1 || order_total < 1)
   {
      PrintFormat("TradingLab activity: position %I64d has incomplete history; skipped",
                  position_id);
      return 0;
   }
   if(deal_total > MaxItemsPerCollection || order_total > MaxItemsPerCollection)
   {
      PrintFormat("TradingLab activity: position %I64d exceeds collection limit; skipped",
                  position_id);
      return 0;
   }

   bool valid = true;
   bool has_event_time = false;
   bool has_opening_order = false;
   long from_msc = 0;
   long to_msc = 0;
   double signed_volume = 0.0;
   string deals = "[";
   for(int index = 0; index < deal_total; index++)
   {
      ResetLastError();
      ulong ticket = HistoryDealGetTicket(index);
      long row_position_id = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      long time_msc = HistoryDealGetInteger(ticket, DEAL_TIME_MSC);
      long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
      double volume = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      if(ticket == 0 || GetLastError() != 0 || row_position_id != position_id ||
         time_msc <= 0 || !MathIsValidNumber(volume) || volume < 0.0)
      {
         PrintFormat("TradingLab activity: position %I64d deal history is invalid; skipped",
                     position_id);
         return 0;
      }
      if(deal_type == DEAL_TYPE_BUY)
         signed_volume += volume;
      else if(deal_type == DEAL_TYPE_SELL)
         signed_volume -= volume;
      else
      {
         PrintFormat("TradingLab activity: position %I64d has a non-trading deal; skipped",
                     position_id);
         return 0;
      }
      if(!has_event_time || time_msc < from_msc)
         from_msc = time_msc;
      if(!has_event_time || time_msc > to_msc)
         to_msc = time_msc;
      has_event_time = true;
      string row = BuildHistoricalDeal(ticket, valid);
      if(!valid)
         return -1;
      if(index > 0)
         deals += ",";
      deals += row;
   }
   deals += "]";

   string orders = "[";
   for(int index = 0; index < order_total; index++)
   {
      ResetLastError();
      ulong ticket = HistoryOrderGetTicket(index);
      long order_position_id = HistoryOrderGetInteger(ticket, ORDER_POSITION_ID);
      long position_by_id = HistoryOrderGetInteger(ticket, ORDER_POSITION_BY_ID);
      long done_msc = HistoryOrderGetInteger(ticket, ORDER_TIME_DONE_MSC);
      if(ticket == 0 || GetLastError() != 0 || done_msc <= 0 ||
         (order_position_id != position_id && position_by_id != position_id))
      {
         PrintFormat("TradingLab activity: position %I64d order history is invalid; skipped",
                     position_id);
         return 0;
      }
      if((long)ticket == position_id)
         has_opening_order = true;
      if(!has_event_time || done_msc < from_msc)
         from_msc = done_msc;
      if(!has_event_time || done_msc > to_msc)
         to_msc = done_msc;
      has_event_time = true;
      string row = BuildHistoricalOrder(ticket, valid);
      if(!valid)
         return -1;
      if(index > 0)
         orders += ",";
      orders += row;
   }
   orders += "]";

   if(!has_event_time || !has_opening_order || MathAbs(signed_volume) > 0.00000001)
   {
      PrintFormat("TradingLab activity: position %I64d is open or cannot be proven complete; skipped",
                  position_id);
      return 0;
   }

   payload = "{";
   payload += "\"reason\":\"position_reconcile\",";
   payload += "\"identity\":" + BuildIdentity() + ",";
   payload += "\"window\":{\"from_server_msc\":\"" + IntegerToString(from_msc) +
              "\",\"to_server_msc\":\"" + IntegerToString(to_msc) + "\"},";
   payload += "\"deals\":" + CollectionJson(deal_total, deals, false) + ",";
   payload += "\"orders\":" + CollectionJson(order_total, orders, false);
   payload += "}";
   return 1;
}


void ResetCandidatePositions()
{
   ArrayResize(candidate_position_ids, 0);
   candidate_position_count = 0;
   candidate_position_index = 0;
}


void AddCandidatePosition(const long position_id)
{
   for(int index = 0; index < candidate_position_count; index++)
      if(candidate_position_ids[index] == position_id)
         return;
   if(ArrayResize(candidate_position_ids, candidate_position_count + 1) < 0)
   {
      Print("TradingLab activity: cannot retain position reconciliation candidate");
      StopForSafety();
      return;
   }
   candidate_position_ids[candidate_position_count] = position_id;
   candidate_position_count++;
}


void ContinuePositionReconciliation()
{
   while(candidate_position_index < candidate_position_count)
   {
      long position_id = candidate_position_ids[candidate_position_index];
      string payload = "";
      int result = BuildPositionReconcilePayload(position_id, payload);
      if(result < 0)
         return;
      if(result == 0)
      {
         candidate_position_index++;
         continue;
      }
      sequence_number++;
      string envelope = BuildEnvelope(payload, sequence_number);
      if(!CheckPilotSafety())
         return;
      if(!PayloadSizeIsValid(envelope))
      {
         PrintFormat("TradingLab activity: position %I64d evidence exceeds payload limit; skipped",
                     position_id);
         candidate_position_index++;
         continue;
      }
      pending_body = envelope;
      pending_is_position_reconcile = true;
      TrySendPending(GetTickCount64());
      return;
   }
   FinalizeConfirmedBatch();
}


bool PersistValue(const string name, const long value)
{
   ResetLastError();
   if(GlobalVariableSet(name, (double)value) == 0)
      return false;
   GlobalVariablesFlush();
   return true;
}


void StopForSafety()
{
   safety_stopped = true;
   EventKillTimer();
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
   Print("TradingLab activity: pilot guard stopped capture; review demo identity and reattach EA");
   StopForSafety();
   return false;
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
      return 400;
   ArrayResize(request_body, encoded - 1);
   ResetLastError();
   int status = WebRequest("POST", IngestUrl, headers, RequestTimeoutMs,
                           request_body, response_body, response_headers);
   if(status == -1)
      PrintFormat("TradingLab activity: request failed (%d)", GetLastError());
   return status;
}


string BuildActivityPayload(const string reason, const long from_msc, const long to_msc,
                            bool &truncated)
{
   ResetCandidatePositions();
   long from_seconds = from_msc / 1000;
   long to_seconds = (to_msc + 999) / 1000;
   ResetLastError();
   if(to_msc < from_msc || !HistorySelect((datetime)from_seconds, (datetime)to_seconds))
   {
      PrintFormat("TradingLab activity: HistorySelect failed (%d)", GetLastError());
      return "";
   }
   bool valid = true;
   int deal_total = 0;
   int order_total = 0;
   string deals = BuildHistoricalDeals(from_msc, to_msc, deal_total, valid);
   string orders = BuildHistoricalOrders(from_msc, to_msc, order_total, valid);
   if(!valid)
   {
      Print("TradingLab activity: history read returned invalid data");
      return "";
   }
   bool deals_truncated = deal_total > MaxItemsPerCollection;
   bool orders_truncated = order_total > MaxItemsPerCollection;
   truncated = deals_truncated || orders_truncated;
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
      long position_id = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(GetLastError() != 0)
      {
         valid = false;
         return "[]";
      }
      if(position_id > 0 && entry != DEAL_ENTRY_IN)
         AddCandidatePosition(position_id);
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


string BuildEnvelope(const string payload, const ulong sequence)
{
   string event_id = session_id + ":" + IntegerToString((long)sequence);
   string body = "{";
   body += "\"schema_version\":\"" + SCHEMA_VERSION + "\",";
   body += "\"collector_version\":\"" + COLLECTOR_VERSION + "\",";
   body += "\"source_id\":\"" + JsonEscape(SourceId) + "\",";
   body += "\"session_id\":\"" + JsonEscape(session_id) + "\",";
   body += "\"sequence\":" + IntegerToString((long)sequence) + ",";
   body += "\"event_id\":\"" + JsonEscape(event_id) + "\",";
   body += "\"captured_at\":\"" + IsoUtcTimestamp() + "\",";
   body += "\"kind\":\"activity_batch\",\"payload\":" + payload + "}";
   return body;
}


bool PayloadSizeIsValid(const string body)
{
   int size = Utf8Size(body);
   if(size < 1 || size > MAX_PAYLOAD_BYTES)
   {
      PrintFormat("TradingLab activity: payload size rejected (%d)", size);
      return false;
   }
   return true;
}


int Utf8Size(const string value)
{
   char encoded[];
   return StringToCharArray(value, encoded, 0, WHOLE_ARRAY, CP_UTF8) - 1;
}


bool IsLoopbackIngestUrl(const string url)
{
   const string prefix = "http://127.0.0.1:";
   const string suffix = "/v2/telemetry";
   if(StringFind(url, prefix) != 0)
      return false;
   int start = StringLen(prefix);
   int length = StringLen(url) - start - StringLen(suffix);
   if(length < 1 || length > 5 || StringSubstr(url, start + length) != suffix)
      return false;
   string port = StringSubstr(url, start, length);
   if(StringGetCharacter(port, 0) == '0')
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(port, index);
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


bool IsSafeIdentifier(const string value)
{
   int length = StringLen(value);
   if(length < 1 || length > 128)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(value, index);
      bool allowed = (character >= 'A' && character <= 'Z') ||
                     (character >= 'a' && character <= 'z') ||
                     (character >= '0' && character <= '9') || character == '.' ||
                     character == '_' || character == ':' || character == '-';
      if(!allowed)
         return false;
   }
   return true;
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


string MaskedLogin()
{
   string login = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   int length = StringLen(login);
   return "****" + (length <= 4 ? login : StringSubstr(login, length - 4));
}


string JsonNumber(const double value, bool &valid)
{
   if(!MathIsValidNumber(value))
   {
      valid = false;
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
   return StringLen(value) <= maximum ? value : StringSubstr(value, 0, maximum);
}


string IsoUtcTimestamp()
{
   MqlDateTime parts = {};
   TimeToStruct(TimeGMT(), parts);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", parts.year, parts.mon,
                       parts.day, parts.hour, parts.min, parts.sec);
}


string CompactUtcTimestamp()
{
   MqlDateTime parts = {};
   TimeToStruct(TimeGMT(), parts);
   return StringFormat("%04d%02d%02dT%02d%02d%02dZ", parts.year, parts.mon,
                       parts.day, parts.hour, parts.min, parts.sec);
}
