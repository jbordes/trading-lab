#property script_show_inputs
#include "../../apps/mt5-telemetry-collector/TradingLabAccountGuard.mqh"

int failures = 0;
void Check(const bool condition, const string label)
{
   if(!condition) { failures++; Print("FAIL: " + label); }
}
void OnStart()
{
   Check(IsApprovedAccount(true, ACCOUNT_TRADE_MODE_DEMO, 1234, "SERVER", 1234, "SERVER"),
         "demo remains default");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_REAL, 1234, "SERVER", 1234, "SERVER"),
         "real denied by default");
   Check(IsApprovedAccount(true, ACCOUNT_TRADE_MODE_REAL, 1234, "SERVER", 1234, "SERVER", true),
         "explicit real identity accepted");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_DEMO, 1234, "SERVER", 1234, "SERVER", true),
         "real mode cannot silently switch to demo");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_CONTEST, 1234, "SERVER", 1234, "SERVER", true),
         "contest denied");
   Check(!IsApprovedAccount(false, ACCOUNT_TRADE_MODE_REAL, 1234, "SERVER", 1234, "SERVER", true),
         "disconnected denied");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_REAL, 4321, "SERVER", 1234, "SERVER", true),
         "other login denied");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_REAL, 1234, "OTHER", 1234, "SERVER", true),
         "other server denied");
   Check(!IsApprovedAccount(true, ACCOUNT_TRADE_MODE_REAL, 0, "", 0, "", true),
         "missing identity denied");
   Print("TradingLab account guard tests: ", failures, " failure(s)");
}
