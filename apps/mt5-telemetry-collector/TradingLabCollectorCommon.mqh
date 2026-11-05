#ifndef TRADINGLAB_COLLECTOR_COMMON
#define TRADINGLAB_COLLECTOR_COMMON

// No trading, network or disk side effects. Shared primitives and retry policy.
enum CollectorCaptureState { CAPTURE_READY, CAPTURE_WAIT_BROKER, CAPTURE_STOPPED };
enum CollectorDelivery { DELIVERY_ACK, DELIVERY_RETRY, DELIVERY_ACCESS_BLOCKED, DELIVERY_FATAL };

class CollectorTransport
{
private:
   ulong due_ms;
   int delay_seconds;
   CollectorDelivery state;
public:
   CollectorTransport() { Reset(); }
   void Reset() { due_ms = 0; delay_seconds = 2; state = DELIVERY_ACK; }
   bool Ready(const ulong now_ms) { return state != DELIVERY_FATAL && now_ms >= due_ms; }
   ulong Due() { return due_ms; }
   int Delay() { return delay_seconds; }
   CollectorDelivery State() { return state; }
   CollectorDelivery Observe(const int status, const ulong now_ms)
   {
      if(status == 200 || status == 202)
      {
         Reset();
         return DELIVERY_ACK;
      }
      if(status == 401 || status == 403)
      {
         state = DELIVERY_ACCESS_BLOCKED;
         due_ms = now_ms + 60000;
         return state;
      }
      if(status == -1 || status == 408 || status == 429 || status >= 500)
      {
         state = DELIVERY_RETRY;
         due_ms = now_ms + (ulong)delay_seconds * 1000;
         delay_seconds = MathMin(delay_seconds * 2, 60);
         return state;
      }
      state = DELIVERY_FATAL;
      return state;
   }
};

bool IsLoopbackCollectorUrl(const string url, const string suffix)
{
   const string prefix = "http://127.0.0.1:";
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

CollectorCaptureState EvaluateCaptureState(const bool connected, const bool read_ok,
   const long mode, const long login, const string server,
   const long expected_login, const string expected_server)
{
   if(!connected || !read_ok)
      return CAPTURE_WAIT_BROKER;
   return IsApprovedDemo(true, mode, login, server, expected_login, expected_server) ?
      CAPTURE_READY : CAPTURE_STOPPED;
}

bool IsSafeIdentifier(const string value)
{
   int length = StringLen(value);
   if(length < 1 || length > 128)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(value, index);
      if(!((character >= 'A' && character <= 'Z') ||
           (character >= 'a' && character <= 'z') ||
           (character >= '0' && character <= '9') ||
           character == '.' || character == '_' || character == ':' || character == '-'))
         return false;
   }
   return true;
}

bool IsCollectorToken(const string value)
{
   int length = StringLen(value);
   if(length < 24 || length > 512 || StringFind(value, "CHANGE-ME") == 0)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(value, index);
      if(character < 33 || character > 126)
         return false;
   }
   return true;
}

string JsonEscape(const string value)
{
   string result = "";
   for(int index = 0; index < StringLen(value); index++)
   {
      ushort character = StringGetCharacter(value, index);
      if(character == 34) result += "\\\"";
      else if(character == 92) result += "\\\\";
      else if(character < 32) result += StringFormat("\\u%04X", (uint)character);
      else result += StringSubstr(value, index, 1);
   }
   return result;
}

string JsonNumber(const double value, bool &valid)
{
   if(!MathIsValidNumber(value)) { valid = false; return "null"; }
   return DoubleToString(value, 8);
}

string UnsignedIdentifier(const ulong value) { return StringFormat("%I64u", value); }
string Truncate(const string value, const int maximum)
{
   return StringLen(value) <= maximum ? value : StringSubstr(value, 0, maximum);
}
string MaskedLogin()
{
   string login = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   int length = StringLen(login);
   return "****" + (length <= 4 ? login : StringSubstr(login, length - 4));
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
#endif
