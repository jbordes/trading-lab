// Deterministic native test: no network, account reads or trading at runtime.
#define TELEMETRY_QUEUE_TEST
#define TimeCurrent FakeTimeCurrent
#define HistorySelect FakeHistorySelect
#define HistoryDealsTotal FakeHistoryDealsTotal
#define HistoryDealGetTicket FakeHistoryDealGetTicket
#define HistoryDealGetInteger FakeHistoryDealGetInteger
#define HistoryDealGetDouble FakeHistoryDealGetDouble
#define HistoryDealGetString FakeHistoryDealGetString
#include "../../apps/mt5-telemetry-collector/TradingLabTelemetry.mq5"

int fake_status = -1;
int sends = 0;
int failures = 0;
string last_body = "";

int SendMessage(const string body)
{
   sends++;
   last_body = body;
   return fake_status;
}

void Check(const bool condition, const string label)
{
   if(!condition)
   {
      failures++;
      Print("FAIL: " + label);
   }
}

void ResetQueue()
{
   while(outbox_count > 0)
      RemoveHead();
   dropped_samples = 0;
   next_send_ms = 0;
   retry_delay_seconds = 2;
   sends = 0;
   fake_status = -1;
}

void OnStart()
{
   TestHistoryRecovery();
   TestPilotGuards();
   TestNumericRejection();
   ResetQueue();
   EnqueueSnapshot("first", 1);
   TrySendQueued(0);
   EnqueueSnapshot("second", 2);
   TrySendQueued(1000);
   Check(outbox_count == 2 && sends == 1, "capture continues during backoff");
   TrySendQueued(2000);
   Check(last_body == "first" && sends == 2, "retry preserves payload identity");
   fake_status = 202;
   TrySendQueued(6000);
   TrySendQueued(6000);
   Check(outbox_count == 0 && last_body == "second", "ordered recovery drains backlog");

   ResetQueue();
   EnqueueSnapshot("first", 1);
   fake_status = 401;
   TrySendQueued(0);
   Check(outbox_count == 0 && dropped_samples == 1, "permanent rejection discarded");
   EnqueueSnapshot("second", 2);
   TrySendQueued(1);
   Check(sends == 1, "rejected endpoint retains backoff");
   fake_status = 200;
   TrySendQueued(2000);
   Check(outbox_count == 0, "duplicate acknowledgement advances queue");

   ResetQueue();
   EnqueueSnapshot("first", 1);
   TrySendQueued(0);
   TrySendQueued(2000);
   TrySendQueued(6000);
   TrySendQueued(14000);
   TrySendQueued(30000);
   Check(outbox_count == 0 && dropped_samples == 1, "five failed attempts bounded");

   ResetQueue();
   EnqueueSnapshot("first", 1);
   fake_status = 429;
   TrySendQueued(0);
   for(int i = 2; i <= OUTBOX_CAPACITY + 1; i++)
      EnqueueSnapshot(IntegerToString(i), (ulong)i);
   Check(outbox_count == OUTBOX_CAPACITY && dropped_samples == 1,
         "overflow bounded and counted");
   Check(outbox_sequence[outbox_head] == 2 && next_send_ms == 2000,
         "overflow keeps newest samples and endpoint backoff");
   fake_status = 503;
   TrySendQueued(2000);
   Check(outbox_count == OUTBOX_CAPACITY && retry_delay_seconds == 8,
         "server error retry preserves queue");
   fake_status = 202;
   for(int i = 0; i < OUTBOX_CAPACITY; i++)
      TrySendQueued(6000);
   Check(outbox_count == 0, "ring wrap drains in order");

   string oversized;
   StringInit(oversized, MAX_PAYLOAD_BYTES + 1, 'x');
   EnqueueSnapshot(oversized, 99);
   Check(outbox_count == 0 && dropped_samples == 2, "oversize rejected before retention");
   PrintFormat("TradingLab outbox tests: %d failure(s)", failures);
}


bool history_select_ok = true;
bool history_number_ok = true;
int history_count = 2;
datetime FakeTimeCurrent() { return (datetime)1000; }
bool FakeHistorySelect(datetime from_time, datetime to_time) { return history_select_ok; }
int FakeHistoryDealsTotal() { return history_count; }
ulong FakeHistoryDealGetTicket(int index) { return (ulong)(index + 1); }
long FakeHistoryDealGetInteger(ulong ticket, ENUM_DEAL_PROPERTY_INTEGER property)
{
   if(property == DEAL_TIME_MSC) return 999000 + (long)ticket;
   if(property == DEAL_MAGIC) return 11122;
   if(property == DEAL_TYPE) return 0;
   if(property == DEAL_ENTRY) return (long)(ticket % 2);
   return 42;
}
double FakeHistoryDealGetDouble(ulong ticket, ENUM_DEAL_PROPERTY_DOUBLE property)
{
   if(!history_number_ok) return MathArcsin(2.0);
   return 0.1;
}
string FakeHistoryDealGetString(ulong ticket, ENUM_DEAL_PROPERTY_STRING property)
{
   return "TEST";
}
void TestHistoryRecovery()
{
   string first = BuildHistory();
   Check(StringFind(first, "\"status\":\"complete\"") >= 0, "history complete");
   Check(StringFind(first, "\"ticket\":\"1\"") >= 0 &&
         StringFind(first, "\"ticket\":\"2\"") >= 0, "entry and exit between samples retained");
   Check(BuildHistory() == first, "overlap re-reads same executions without cursor");
   history_count = 201;
   string truncated = BuildHistory();
   Check(StringFind(truncated, "\"status\":\"truncated\"") >= 0,
         "excess history not labelled complete");
   history_count = 0;
   Check(StringFind(BuildHistory(), "\"status\":\"complete\"") >= 0, "empty history is valid");
   history_select_ok = false;
   Check(StringFind(BuildHistory(), "\"status\":\"error\"") >= 0, "history failure visible");
   history_select_ok = true;
   history_count = 2;
   history_number_ok = false;
   Check(StringFind(BuildHistory(), "\"status\":\"error\"") >= 0, "invalid cost never zeroed");
   history_number_ok = true;
   Check(BuildHistory() == first, "history recovers on next selection");
}


void TestPilotGuards()
{
   Check(IsLoopbackIngestUrl("http://127.0.0.1:8766/v1/telemetry"), "local endpoint allowed");
   Check(IsLoopbackIngestUrl("http://127.0.0.1:65535/v1/telemetry"), "maximum port allowed");
   string invalid[] = {
      "http://127.0.0.1:8766@external.example/v1/telemetry",
      "http://127.0.0.1:8766/v1/telemetry?url=external",
      "http://127.0.0.1:8766/v1/telemetry#fragment",
      "http://localhost:8766/v1/telemetry", "http://127.0.0.1:0/v1/telemetry",
      "http://127.0.0.1:65536/v1/telemetry", "http://127.0.0.1:08766/v1/telemetry",
      "http://127.0.0.1:+8766/v1/telemetry", "http://127.0.0.1:8766/other",
      "http://127.0.0.1:8766\\@external.example/v1/telemetry",
      "http://127.0.0.1:8766/v1/telemetry\r\n", "https://127.0.0.1:8766/v1/telemetry"
   };
   for(int i = 0; i < ArraySize(invalid); i++)
      Check(!IsLoopbackIngestUrl(invalid[i]), "ambiguous or remote URL rejected");
   Check(IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 1234, "DEMO", 1234, "DEMO"),
         "approved connected demo allowed");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_REAL, 1234, "DEMO", 1234, "DEMO"),
         "real account rejected even if server name says demo");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_CONTEST, 1234, "DEMO", 1234, "DEMO"),
         "contest rejected");
   Check(!IsApprovedDemo(false, ACCOUNT_TRADE_MODE_DEMO, 1234, "DEMO", 1234, "DEMO"),
         "disconnected rejected");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 5678, "DEMO", 1234, "DEMO"),
         "changed login rejected");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 1234, "OTHER", 1234, "DEMO"),
         "changed server rejected");
   Check(!IsApprovedDemo(true, ACCOUNT_TRADE_MODE_DEMO, 0, "", 0, ""),
         "unconfigured identity rejected");
}


// IEEE-754 fixtures avoid arithmetic exceptions while constructing NaN/infinities.
union DoubleFixture
{
   ulong bits;
   double value;
};


void TestNumericRejection()
{
   ResetQueue();
   bool valid = true;
   Check(JsonNumber(0.0, valid) == "0.00000000" && valid, "real zero preserved");
   Check(JsonNumber(-12.5, valid) == "-12.50000000" && valid, "negative profit preserved");
   Check(JsonNumber(12.5, valid) == "12.50000000" && valid, "positive number preserved");

   ulong patterns[3] = {0x7FF8000000000000, 0x7FF0000000000000, 0xFFF0000000000000};
   // A bad new sample must not evict any older valid sample, even at capacity.
   for(int i = 1; i <= OUTBOX_CAPACITY; i++)
      EnqueueSnapshot("valid", (ulong)i);
   for(int i = 0; i < 3; i++)
   {
      DoubleFixture fixture;
      fixture.bits = patterns[i];
      valid = true;
      string body = "{\"equity\":" + JsonNumber(fixture.value, valid);
      Check(!valid, "non-finite invalidates sample");
      body += ",\"profit\":" + JsonNumber(0.0, valid) + "}";
      Check(!valid, "later finite field cannot clear invalid state");
      body = FinalizeSnapshot(body, valid);
      Check(body == "", "invalid snapshot has no publishable body");
      EnqueueSnapshot(body, (ulong)(OUTBOX_CAPACITY + i + 1));
   }
   Check(outbox_count == OUTBOX_CAPACITY && outbox_sequence[outbox_head] == 1,
         "invalid sample does not evict retained samples");
   Check(dropped_samples == 3 && sends == 0, "one counted drop per invalid sample");
   ResetQueue();
   valid = true;
   string body = "{\"equity\":" + JsonNumber(0.0, valid) + "}";
   EnqueueSnapshot(FinalizeSnapshot(body, valid), 16);
   fake_status = 202;
   TrySendQueued(0);
   Check(sends == 1 && last_body == body, "next valid sample recovers without fake zero");
}
