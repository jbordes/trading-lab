#ifndef TRADINGLAB_COLLECTOR_LOG
#define TRADINGLAB_COLLECTOR_LOG
#include "TradingLabCollectorCommon.mqh"

// Call only from init/timer/deinit, never from OnTradeTransaction.
// Each source owns one bounded daily file; no relay or DLL dependency.
struct CollectorLogIncident
{
   string code;
   ulong first_ms;
   ulong last_written_ms;
   ulong count;
   ulong written_count;
};

class CollectorLogger
{
private:
   string collector;
   string source;
   string version;
   string prefix;
   string day;
   bool configured;
   bool quota_reached;
   bool fallback_reported;
   ulong retry_after_ms;
   CollectorLogIncident incidents[32];

   string Day(const datetime timestamp)
   {
      MqlDateTime parts = {};
      TimeToStruct(timestamp, parts);
      return StringFormat("%04d%02d%02d", parts.year, parts.mon, parts.day);
   }
   bool OwnedOldFile(const string name, const string cutoff)
   {
      if(StringLen(name) != StringLen(prefix) + 8 + 6 || StringFind(name, prefix) != 0 ||
         StringSubstr(name, StringLen(name) - 6) != ".jsonl")
         return false;
      string date = StringSubstr(name, StringLen(prefix), 8);
      for(int index = 0; index < 8; index++)
         if(StringGetCharacter(date, index) < '0' || StringGetCharacter(date, index) > '9')
            return false;
      datetime parsed = StringToTime(StringSubstr(date, 0, 4) + "." +
         StringSubstr(date, 4, 2) + "." + StringSubstr(date, 6, 2));
      if(parsed <= 0 || Day(parsed) != date) return false;
      return StringCompare(date, cutoff) <= 0;
   }
   void Cleanup(const datetime now)
   {
      string name = "";
      long search = FileFindFirst("TradingLab\\logs\\" + prefix + "*.jsonl", name);
      if(search == INVALID_HANDLE) return;
      string cutoff = Day(now - 14 * 86400);
      for(int scanned = 0; scanned < 64; scanned++)
      {
         // Exact owner/date match, no recursive deletion, never FILE_COMMON.
         if(OwnedOldFile(name, cutoff) && !FileDelete("TradingLab\\logs\\" + name))
            Fallback();
         if(!FileFindNext(search, name)) break;
      }
      FileFindClose(search);
   }
   void Fallback()
   {
      if(!fallback_reported)
         Print("TradingLab: collector log unavailable or daily limit reached; capture continues");
      fallback_reported = true;
   }
   bool Write(const string level, const string code, const string detail,
              const ulong sequence, const int status, const int local_error,
              const ulong count, const ulong suppressed, const ulong elapsed_ms)
   {
      if(!configured) return false;
      ulong now_ms = GetTickCount64();
      datetime now = TimeGMT();
      string today = Day(now);
      if(day != today)
      {
         day = today;
         quota_reached = false;
         fallback_reported = false;
         retry_after_ms = 0;
         Cleanup(now);
      }
      if(quota_reached || now_ms < retry_after_ms) return false;
      string line = "{\"time_utc\":\"" + IsoUtcTimestamp() + "\",\"level\":\"" + level +
         "\",\"collector\":\"" + collector + "\",\"source_id\":\"" + JsonEscape(source) +
         "\",\"version\":\"" + JsonEscape(version) + "\",\"code\":\"" + code +
         "\",\"detail\":\"" + JsonEscape(Truncate(detail, 384)) + "\",\"sequence\":\"" +
         UnsignedIdentifier(sequence) + "\",\"transport_status\":" + IntegerToString(status) +
         ",\"local_error\":" + IntegerToString(local_error) + ",\"occurrences\":\"" +
         UnsignedIdentifier(count) + "\",\"suppressed\":\"" + UnsignedIdentifier(suppressed) +
         "\",\"elapsed_ms\":\"" + UnsignedIdentifier(elapsed_ms) + "\"}\n";
      uchar bytes[];
      int size = StringToCharArray(line, bytes, 0, WHOLE_ARRAY, CP_UTF8) - 1;
      if(size < 1) { Fallback(); retry_after_ms = now_ms + 60000; return false; }
      int handle = FileOpen("TradingLab\\logs\\" + prefix + day + ".jsonl",
                            FILE_READ | FILE_WRITE | FILE_BIN | FILE_SHARE_READ);
      if(handle == INVALID_HANDLE) { Fallback(); retry_after_ms = now_ms + 60000; return false; }
      if(FileSize(handle) + (ulong)size > 1048576)
      {
         FileClose(handle);
         quota_reached = true;
         Fallback();
         return false;
      }
      ResetLastError();
      bool positioned = FileSeek(handle, 0, SEEK_END);
      uint written = positioned ? FileWriteArray(handle, bytes, 0, size) : 0;
      FileFlush(handle);
      bool ok = positioned && written == (uint)size && GetLastError() == 0;
      FileClose(handle);
      if(!ok) { Fallback(); retry_after_ms = now_ms + 60000; }
      return ok;
   }
   void Event(const string level, const string code, const string detail,
              const ulong sequence, const int status, const int local_error)
   {
      if(!IsSafeIdentifier(code)) return;
      int slot = -1;
      for(int index = 0; index < 32; index++)
      {
         if(incidents[index].code == code) { slot = index; break; }
         if(slot < 0 && incidents[index].count == 0) slot = index;
      }
      if(slot < 0) { Fallback(); return; }
      ulong now = GetTickCount64();
      if(incidents[slot].count == 0)
      {
         incidents[slot].code = code;
         incidents[slot].first_ms = now;
         incidents[slot].written_count = 0;
      }
      incidents[slot].count++;
      if(incidents[slot].count > 1 && now - incidents[slot].last_written_ms < 60000) return;
      ulong suppressed = incidents[slot].count - incidents[slot].written_count - 1;
      bool recorded = Write(level, code, detail, sequence, status, local_error, incidents[slot].count,
                             suppressed, now - incidents[slot].first_ms);
      incidents[slot].last_written_ms = now;
      if(recorded) incidents[slot].written_count = incidents[slot].count;
      if(level == "ERROR") Print("TradingLab " + collector + ": " + code + "; " + detail);
   }
public:
   CollectorLogger()
   {
      collector = ""; source = ""; version = ""; prefix = ""; day = "";
      configured = false; quota_reached = false; fallback_reported = false; retry_after_ms = 0;
      for(int index = 0; index < 32; index++)
      {
         incidents[index].code = "";
         incidents[index].count = 0;
         incidents[index].written_count = 0;
         incidents[index].first_ms = 0;
         incidents[index].last_written_ms = 0;
      }
   }
   bool Configure(const string component, const string source_id, const string build)
   {
      if((component != "telemetry" && component != "activity") ||
         !IsSafeIdentifier(source_id) || !IsSafeIdentifier(build)) return false;
      collector = component; source = source_id; version = build;
      string filename_source = source_id;
      // '~' cannot occur in IsSafeIdentifier: this mapping is collision-free.
      StringReplace(filename_source, ":", "~");
      prefix = component + "-" + filename_source + "-";
      configured = true;
      return true;
   }
   void Warn(const string code, const string detail = "", const ulong sequence = 0,
             const int status = 0, const int local_error = 0)
   { Event("WARN", code, detail, sequence, status, local_error); }
   void Error(const string code, const string detail = "", const ulong sequence = 0,
              const int status = 0, const int local_error = 0)
   { Event("ERROR", code, detail, sequence, status, local_error); }
   void Resolve(const string code, const ulong sequence = 0)
   {
      for(int index = 0; index < 32; index++)
         if(incidents[index].code == code && incidents[index].count > 0)
         {
            bool recorded = Write("RESOLVED", code, "recovered", sequence, 0, 0, incidents[index].count,
                  incidents[index].count - incidents[index].written_count,
                  GetTickCount64() - incidents[index].first_ms);
            if(recorded) incidents[index].count = 0;
            return;
         }
   }
};
#endif
