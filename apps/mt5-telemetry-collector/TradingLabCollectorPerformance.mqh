#ifndef TRADINGLAB_COLLECTOR_PERFORMANCE
#define TRADINGLAB_COLLECTOR_PERFORMANCE

enum CollectorPhase
{
   PERF_TIMER, PERF_HISTORY_SELECT, PERF_PAGE_SCAN, PERF_HISTORY_ROWS_JSON,
   PERF_SNAPSHOT, PERF_ENVELOPE, PERF_UTF8, PERF_RESOLVE_HTTP, PERF_INGEST_HTTP,
   PERF_RETRY_HTTP, PERF_CURSOR, PERF_PHASE_COUNT
};

enum CollectorLane
{
   PERF_GENERAL, PERF_RECENT, PERF_DEEP, PERF_HEARTBEAT, PERF_LANE_COUNT
};

struct CollectorTiming
{
   ulong count;
   ulong failures;
   ulong total_us;
   ulong max_us;
   ulong buckets[8];
};

class CollectorPerformance
{
private:
   bool enabled;
   bool dirty;
   ulong report_tick;
   CollectorTiming measurements[PERF_LANE_COUNT][PERF_PHASE_COUNT];

public:
   void Configure(const bool active)
   {
      enabled = active;
      if(enabled)
         report_tick = GetTickCount64();
   }

   ulong Start()
   {
      return enabled ? GetMicrosecondCount() + 1 : 0;
   }

   void Record(const ulong start, const CollectorPhase phase,
               const CollectorLane lane = PERF_GENERAL, const bool success = true)
   {
      if(start == 0)
         return;
      ulong elapsed = GetMicrosecondCount() + 1 - start;
      ulong limits[] = {100, 500, 1000, 5000, 25000, 100000, 500000};
      int bucket = 0;
      while(bucket < ArraySize(limits) && elapsed > limits[bucket])
         bucket++;
      measurements[lane][phase].count++;
      if(!success)
         measurements[lane][phase].failures++;
      measurements[lane][phase].total_us += elapsed;
      if(elapsed > measurements[lane][phase].max_us)
         measurements[lane][phase].max_us = elapsed;
      measurements[lane][phase].buckets[bucket]++;
      dirty = true;
   }

   void Report(const string session, const ulong sequence, const bool flush = false)
   {
      if(!enabled || !dirty)
         return;
      ulong now = GetTickCount64();
      if(!flush && now - report_tick < 300000)
         return;

      string line = "";
      for(int lane = 0; lane < PERF_LANE_COUNT; lane++)
      {
         for(int phase = 0; phase < PERF_PHASE_COUNT; phase++)
         {
            CollectorTiming sample = measurements[lane][phase];
            if(sample.count == 0)
               continue;
            string buckets = "";
            for(int index = 0; index < ArraySize(sample.buckets); index++)
               buckets += (index == 0 ? "" : ",") + StringFormat("%I64u", sample.buckets[index]);
            line += StringFormat(" %s/%s=%I64u,%I64u,%I64u,%I64u,[%s]",
                                 EnumToString((CollectorLane)lane), EnumToString((CollectorPhase)phase),
                                 sample.count, sample.failures, sample.total_us, sample.max_us, buckets);
            ZeroMemory(measurements[lane][phase]);
         }
         if(line != "")
            PrintFormat("TradingLab perf session=%s seq=%I64u window_ms=%I64u%s",
                        session, sequence, now - report_tick, line);
         line = "";
      }
      report_tick = now;
      dirty = false;
   }
};

#endif
