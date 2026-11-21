#property script_show_inputs
#include "../../apps/mt5-telemetry-collector/TradingLabCollectorCommon.mqh"

int failures = 0;
void Check(const bool condition, const string label)
{
   if(!condition) { failures++; Print("FAIL: " + label); }
}
void OnStart()
{
   CollectorTransport transport;
   Check(transport.Ready(0), "initially ready");
   Check(transport.Observe(403, 0) == DELIVERY_ACCESS_BLOCKED, "403 is recoverable access block");
   Check(!transport.Ready(59999) && transport.Ready(60000), "access probe is spaced");
   Check(transport.Observe(202, 60000) == DELIVERY_ACK && transport.Ready(60000), "access restored");
   Check(transport.Observe(-1, 0) == DELIVERY_RETRY && transport.Due() == 2000, "network backoff");
   transport.Observe(503, 2000);
   Check(transport.Due() == 6000, "backoff increases");
   transport.Observe(409, 6000);
   Check(!transport.Ready(999999), "conflict requires review");
   transport.Reset();
   Check(transport.Observe(401, 0) == DELIVERY_ACCESS_BLOCKED, "401 can recover without reload");
   Check(IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 1, "DEMO", 1, "DEMO"), "approved identity");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_REAL, 1, "DEMO", 1, "DEMO"), "real account denied");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 2, "DEMO", 1, "DEMO"), "other account denied");
   Check(EvaluateCaptureState(false, true, ACCOUNT_TRADE_MODE_DEMO, 1, "DEMO", 1, "DEMO") == CAPTURE_WAIT_BROKER,
         "disconnect pauses without permanent stop");
   Check(EvaluateCaptureState(true, true, ACCOUNT_TRADE_MODE_DEMO, 1, "DEMO", 1, "DEMO") == CAPTURE_READY,
         "same approved account resumes after reconnect");
   Check(EvaluateCaptureState(true, true, ACCOUNT_TRADE_MODE_DEMO, 2, "DEMO", 1, "DEMO") == CAPTURE_STOPPED,
         "another account never resumes automatically");
   Check(IsLoopbackCollectorUrl("http://127.0.0.1:8776/api/account-state", "/api/account-state"), "loopback URL");
   Check(!IsLoopbackCollectorUrl("http://evil.invalid:8776/api/account-state", "/api/account-state"), "remote denied");
   Check(JsonEscape("\"\\") == "\\\"\\\\", "quotes and slash escaped");
   for(int code = 0; code < 32; code++)
   {
      string character = ShortToString((ushort)code);
      if(StringLen(character) > 0)
         Check(JsonEscape(character) == StringFormat("\\u%04X", code), "control character escaped");
      else
         Check(code == 0, "only a null terminator may be unrepresentable");
   }
   PrintFormat("TradingLab common tests: %d failure(s)", failures);
}
