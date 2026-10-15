#property copyright "TradingLab 2.0"
#property version   "1.000"
#property strict

// Spike-only collector. It emits observations and never accepts remote commands.

input string IngestUrl = "http://127.0.0.1:8766/v1/telemetry";
input string Token = "CHANGE-ME-WITH-A-LOCAL-TEST-TOKEN";
input string SourceId = "demo-terminal-01";
input int IntervalSeconds = 5;
input int RequestTimeoutMs = 3000;
input int MaxItemsPerSnapshot = 200;

const string SCHEMA_VERSION = "mt5-telemetry-v1";
const string COLLECTOR_VERSION = "0.1.0";

string session_id = "";
string pending_body = "";
bool startup_pending = true;
bool trade_activity_pending = false;
ulong sequence_number = 0;


int OnInit()
{
   if(StringFind(IngestUrl, "http://127.0.0.1:") != 0)
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
   if(RequestTimeoutMs < 500 || RequestTimeoutMs > 10000)
   {
      Print("TradingLab telemetry: RequestTimeoutMs must be between 500 and 10000");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MaxItemsPerSnapshot < 1 || MaxItemsPerSnapshot > 500)
   {
      Print("TradingLab telemetry: MaxItemsPerSnapshot must be between 1 and 500");
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
   pending_body = "";
   PrintFormat("TradingLab telemetry: stopped (%d)", reason);
}


void OnTimer()
{
   if(pending_body == "")
   {
      string reason = "timer";
      if(startup_pending)
         reason = "startup";
      else if(trade_activity_pending)
         reason = "trade_activity";

      sequence_number++;
      pending_body = BuildSnapshot(reason, sequence_number);
      startup_pending = false;
      trade_activity_pending = false;
   }

   if(SendPendingMessage())
      pending_body = "";
}


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


bool SendPendingMessage()
{
   char request_body[];
   char response_body[];
   string response_headers = "";
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + Token + "\r\n";

   int encoded = StringToCharArray(pending_body, request_body, 0, WHOLE_ARRAY, CP_UTF8);
   if(encoded <= 1)
   {
      Print("TradingLab telemetry: cannot encode the payload");
      return false;
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
      return true;

   if(status == -1)
      PrintFormat("TradingLab telemetry: request failed (%d)", GetLastError());
   else
      PrintFormat("TradingLab telemetry: receiver returned HTTP %d", status);
   return false;
}


string BuildSnapshot(const string reason, const ulong sequence)
{
   string event_id = session_id + ":" + IntegerToString((long)sequence);
   string payload = "{";
   payload += "\"reason\":\"" + reason + "\",";
   payload += "\"account\":" + BuildAccount() + ",";
   payload += "\"positions_total\":" + IntegerToString(PositionsTotal()) + ",";
   payload += "\"orders_total\":" + IntegerToString(OrdersTotal()) + ",";
   payload += "\"positions\":" + BuildPositions() + ",";
   payload += "\"orders\":" + BuildOrders();
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
   return body;
}


string BuildAccount()
{
   string account = "{";
   account += "\"login_masked\":\"" + MaskedLogin() + "\",";
   account += "\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",";
   account += "\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",";
   account += "\"balance\":" + JsonNumber(AccountInfoDouble(ACCOUNT_BALANCE)) + ",";
   account += "\"equity\":" + JsonNumber(AccountInfoDouble(ACCOUNT_EQUITY)) + ",";
   account += "\"profit\":" + JsonNumber(AccountInfoDouble(ACCOUNT_PROFIT)) + ",";
   account += "\"margin\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN)) + ",";
   account += "\"margin_free\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN_FREE)) + ",";
   account += "\"margin_level\":" + JsonNumber(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL));
   account += "}";
   return account;
}


string BuildPositions()
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
      result += "\"volume\":" + JsonNumber(PositionGetDouble(POSITION_VOLUME)) + ",";
      result += "\"price_open\":" + JsonNumber(PositionGetDouble(POSITION_PRICE_OPEN)) + ",";
      result += "\"price_current\":" + JsonNumber(PositionGetDouble(POSITION_PRICE_CURRENT)) + ",";
      result += "\"stop_loss\":" + JsonNumber(PositionGetDouble(POSITION_SL)) + ",";
      result += "\"take_profit\":" + JsonNumber(PositionGetDouble(POSITION_TP)) + ",";
      result += "\"profit\":" + JsonNumber(PositionGetDouble(POSITION_PROFIT)) + ",";
      result += "\"swap\":" + JsonNumber(PositionGetDouble(POSITION_SWAP)) + ",";
      result += "\"opened_at_msc\":\"" + IntegerToString(PositionGetInteger(POSITION_TIME_MSC)) + "\",";
      result += "\"comment\":\"" + JsonEscape(Truncate(PositionGetString(POSITION_COMMENT), 256)) + "\"";
      result += "}";
      emitted++;
   }
   result += "]";
   return result;
}


string BuildOrders()
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
      result += "\"volume\":" + JsonNumber(OrderGetDouble(ORDER_VOLUME_CURRENT)) + ",";
      result += "\"price_open\":" + JsonNumber(OrderGetDouble(ORDER_PRICE_OPEN)) + ",";
      result += "\"price_current\":" + JsonNumber(OrderGetDouble(ORDER_PRICE_CURRENT)) + ",";
      result += "\"stop_loss\":" + JsonNumber(OrderGetDouble(ORDER_SL)) + ",";
      result += "\"take_profit\":" + JsonNumber(OrderGetDouble(ORDER_TP)) + ",";
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


string JsonNumber(const double value)
{
   if(!MathIsValidNumber(value))
      return "0";
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
