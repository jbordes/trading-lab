// Deterministic native tests: platform I/O is replaced; no account/trading access.
#define ACTIVITY_COLLECTOR_TEST
#define GetTickCount64 FakeTicks
#define GlobalVariableSet FakeGlobalSet
#define GlobalVariablesFlush FakeGlobalFlush
#define HistorySelect FakeHistorySelect
#define HistorySelectByPosition FakePositionSelect
#define HistoryDealsTotal FakeDealCount
#define HistoryOrdersTotal FakeOrderCount
#define HistoryDealGetTicket FakeDealTicket
#define HistoryDealGetInteger FakeDealInteger
#define HistoryDealGetDouble FakeDealDouble
#define HistoryDealGetString FakeDealString
#define HistoryOrderGetTicket FakeOrderTicket
#define HistoryOrderGetInteger FakeOrderInteger
#define HistoryOrderGetDouble FakeOrderDouble
#define HistoryOrderGetString FakeOrderString
#define AccountInfoInteger FakeAccountInteger
#define AccountInfoString FakeAccountString
#define TimeGMT FakeUtc
#include "../../apps/mt5-telemetry-collector/TradingLabActivity.mq5"

int failures = 0;
int fake_status = 403;
int sends = 0;
int flushes = 0;
int fake_deals = 501;
int fake_orders = 0;
ulong fake_ticks = 0;
string last_body = "";
double saved_cursor = 0;

ulong FakeTicks() { return fake_ticks; }
datetime FakeUtc() { return (datetime)1793820000; }
datetime FakeGlobalSet(const string name, const double value) { saved_cursor = value; return (datetime)1; }
void FakeGlobalFlush() { flushes++; }
bool FakeHistorySelect(datetime start, datetime end) { return true; }
bool FakePositionSelect(ulong position) { return true; }
int FakeDealCount() { return fake_deals; }
int FakeOrderCount() { return fake_orders; }
ulong FakeDealTicket(int index) { return (ulong)(index + 1); }
ulong FakeOrderTicket(int index) { return (ulong)(9000 + index); }
long FakeDealInteger(ulong ticket, ENUM_DEAL_PROPERTY_INTEGER property)
{
   if(property == DEAL_TIME_MSC) return (long)ticket + 1000;
   if(property == DEAL_POSITION_ID) return 9000;
   if(property == DEAL_TYPE) return ticket % 2 == 1 ? DEAL_TYPE_BUY : DEAL_TYPE_SELL;
   if(property == DEAL_ENTRY) return ticket % 2 == 1 ? DEAL_ENTRY_IN : DEAL_ENTRY_OUT;
   if(property == DEAL_MAGIC) return 11122;
   return 9000;
}
double FakeDealDouble(ulong ticket, ENUM_DEAL_PROPERTY_DOUBLE property) { return 1.0; }
string FakeDealString(ulong ticket, ENUM_DEAL_PROPERTY_STRING property) { return "TEST"; }
long FakeOrderInteger(ulong ticket, ENUM_ORDER_PROPERTY_INTEGER property)
{
   if(property == ORDER_POSITION_ID) return 9000;
   if(property == ORDER_TIME_DONE_MSC || property == ORDER_TIME_SETUP_MSC) return 1000;
   if(property == ORDER_MAGIC) return 11122;
   return 0;
}
double FakeOrderDouble(ulong ticket, ENUM_ORDER_PROPERTY_DOUBLE property) { return 1.0; }
string FakeOrderString(ulong ticket, ENUM_ORDER_PROPERTY_STRING property) { return "TEST"; }
long FakeAccountInteger(ENUM_ACCOUNT_INFO_INTEGER property) { return 1234; }
string FakeAccountString(ENUM_ACCOUNT_INFO_STRING property)
{
   return property == ACCOUNT_CURRENCY ? "USD" : "DEMO-SERVER";
}
bool CheckPilotSafety() { return capture_state == CAPTURE_READY; }
int SendMessage(const string body) { sends++; last_body = body; return fake_status; }
void Check(const bool condition, const string label)
{
   if(!condition) { failures++; Print("FAIL: " + label); }
}
void OnStart()
{
   // Regression: the production timer checks the untouched global state first.
   // Assigning a fixture before this check hid a NULL/uninitialized body.
   Check(pending.body == "" && pending.page_snapshot_id == "", "pending strings start explicitly empty");
   Check(pagination.snapshot_id == "" && saved_recent_page.snapshot_id == "" &&
         saved_deep_page.snapshot_id == "", "pagination strings start explicitly empty");
   char initial_bytes[];
   ResetLastError();
   Check(StringToCharArray(pending.body, initial_bytes, 0, WHOLE_ARRAY, CP_UTF8) == 1 &&
         GetLastError() == 0, "fresh body is initialized UTF-8, not NULL (4009)");
   Check(!TrySendPending(0) && sends == 0 && flushes == 0, "fresh state sends no phantom batch");
   pending.body = "original-batch";
   pending.from_msc = 10000;
   pending.to_msc = 20000;
   confirmed_from_msc = 10000;
   candidate_position_count = 0;
   TrySendPending(0);
   Check(pending.body == "original-batch" && confirmed_from_msc == 10000, "403 preserves body and cursor");
   Check(capture_state == CAPTURE_READY && transport.State() == DELIVERY_ACCESS_BLOCKED, "access is not safety stop");
   TrySendPending(59999);
   Check(sends == 1, "no early probe");
   fake_status = 202;
   TrySendPending(60000);
   Check(last_body == "original-batch" && confirmed_from_msc == 15000, "recovery confirms original range");
   Check(flushes == 1 && saved_cursor == 15000, "cursor durable only after ACK");

   pending.body = "heartbeat";
   pending.is_heartbeat = true;
   TrySendPending(60000);
   Check(flushes == 1 && confirmed_from_msc == 15000, "heartbeat never advances history");

   ActivityPageKey start;
   start.time_msc = 0; start.entity_type = 0; start.ticket = 0;
   ActivityPageKey through;
   bool more = false;
   string snapshot = "";
   string page = BuildPagedActivityPayload("recovery", 0, 5000, start, through, more, snapshot);
   Check(page == "" && page_scan.active, "dense page yields before completion");
   Check(page_scan.deal_index <= MaxHistoryRowsPerCycle, "scan row budget bounded");
   Check(ArraySize(page_scan.keys) == MaxItemsPerCollection, "page keys have fixed cap");
   page = BuildPagedActivityPayload("recovery", 0, 5000, start, through, more, snapshot);
   Check(page != "" && more && through.ticket == 200, "scan resumes with stable first page");
   Check(confirmed_from_msc == 15000 && flushes == 1, "page preparation never commits cursor");

   pending.is_recent = false;
   pending.is_paged = true;
   pending.page_has_more = true;
   pending.page_through = through;
   pending.page_snapshot_id = snapshot;
   FinalizeConfirmedBatch();
   Check(saved_deep_page.active && !pagination.active && prefer_recent, "deep page yields scheduling to recent lane");
   Check(flushes == 1, "partial page does not persist range cursor");

   page_scan.active = false;
   fake_deals = 2; fake_orders = 1;
   string position = "";
   Check(BuildPositionReconcilePayload(9000, position) == 1, "closed position evidence built");
   fake_deals = 201;
   Check(BuildPositionReconcilePayload(9000, position) == 0, "oversized position is not falsely complete");
   pending.body = "encoding-failure-fixture";
   fake_status = LOCAL_ENCODING_FAILURE;
   transport.Reset();
   TrySendPending(60001);
   Check(capture_state == CAPTURE_STOPPED && pending.body == "encoding-failure-fixture",
         "local preparation error stops without discarding batch");
   Check(confirmed_from_msc == 15000 && flushes == 1, "local preparation failure never commits cursor");
   PrintFormat("TradingLab activity tests: %d failure(s)", failures);
}
