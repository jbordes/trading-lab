// Deterministic native test: no network, account reads or trading at runtime.
#define TELEMETRY_QUEUE_TEST
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
