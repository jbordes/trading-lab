// Deterministic logger test: every filesystem call and clock is replaced.
#define GetTickCount64 FakeTicks
#define TimeGMT FakeUtc
#define FileOpen FakeOpen
#define FileSize FakeSize
#define FileSeek FakeSeek
#define FileWriteArray FakeWrite
#define FileFlush FakeFlush
#define FileClose FakeClose
#define FileFindFirst FakeFindFirst
#define FileFindNext FakeFindNext
#define FileFindClose FakeFindClose
#define FileDelete FakeDelete
#define Print FakePrint
#include "../../apps/mt5-telemetry-collector/TradingLabCollectorLog.mqh"
#undef Print

ulong ticks = 0;
datetime utc = D'2026.11.04 12:00:00';
ulong file_size = 0;
bool open_fails = false;
bool write_fails = false;
int opens = 0;
int writes = 0;
int flushes = 0;
int closes = 0;
int console_messages = 0;
int failures = 0;
int found_index = 0;
string last_line = "";
string last_path = "";
string found_names[];
string deleted_names[];

ulong FakeTicks() { return ticks; }
datetime FakeUtc() { return utc; }
int FakeOpen(const string name, const int flags)
{
   opens++;
   last_path = name;
   return open_fails ? INVALID_HANDLE : 1;
}
ulong FakeSize(const int handle) { return file_size; }
bool FakeSeek(const int handle, const long offset, const int origin) { return true; }
uint FakeWrite(const int handle, const uchar &data[], const int start, const int count)
{
   if(write_fails) return 0;
   writes++;
   last_line = CharArrayToString(data, start, count, CP_UTF8);
   return (uint)count;
}
void FakeFlush(const int handle) { flushes++; }
void FakeClose(const int handle) { closes++; }
void FakePrint(const string message) { console_messages++; }
long FakeFindFirst(const string filter, string &name)
{
   found_index = 0;
   if(ArraySize(found_names) == 0) return INVALID_HANDLE;
   name = found_names[0];
   return 2;
}
bool FakeFindNext(const long handle, string &name)
{
   found_index++;
   if(found_index >= ArraySize(found_names)) return false;
   name = found_names[found_index];
   return true;
}
void FakeFindClose(const long handle) {}
bool FakeDelete(const string name)
{
   int size = ArraySize(deleted_names);
   ArrayResize(deleted_names, size + 1);
   deleted_names[size] = name;
   return true;
}
void Check(const bool condition, const string label)
{
   if(!condition) { failures++; Print("FAIL: " + label); }
}
void OnStart()
{
   CollectorLogger log;
   Check(!log.Configure("activity", "../invalid", "test-1"), "path traversal rejected");
   Check(log.Configure("activity", "test:one", "test-1"), "valid source configured");
   log.Warn("relay_down", "synthetic\nquoted \"detail\"", 4, 1001, 7);
   Check(writes == 1 && console_messages == 0, "first warning writes once, no Experts noise");
   Check(last_path == "TradingLab\\logs\\activity-test~one-20261104.jsonl", "daily isolated source path");
   Check(StringFind(last_line, "synthetic\\u000Aquoted \\\"detail\\\"") >= 0, "detail JSON escaped");
   Check(StringFind(last_line, "\"transport_status\":1001") >= 0 &&
         StringFind(last_line, "\"local_error\":7") >= 0, "transport and local errors distinct");
   ticks = 1000;
   for(int index = 0; index < 3; index++) log.Warn("relay_down");
   Check(writes == 1, "retries suppressed within minute");
   ticks = 60000;
   log.Warn("relay_down");
   Check(writes == 2 && StringFind(last_line, "\"occurrences\":\"5\"") >= 0 &&
         StringFind(last_line, "\"suppressed\":\"3\"") >= 0, "minute summary counts actual calls");
   ticks = 61000;
   log.Resolve("relay_down");
   Check(writes == 3 && StringFind(last_line, "\"level\":\"RESOLVED\"") >= 0, "one recovery record");
   log.Resolve("relay_down");
   Check(writes == 3, "healthy repeated ACK does not emit logs");
   log.Error("critical", "capture stopped");
   Check(writes == 4 && console_messages == 1, "critical error remains visible in Experts");
   Check(flushes == writes && closes == writes, "records flushed and handles closed");

   file_size = 1048576;
   log.Warn("quota");
   int capped_opens = opens;
   log.Warn("quota_other");
   Check(writes == 4 && opens == capped_opens && console_messages == 2, "daily quota stops I/O and warns once");
   utc += 86400;
   ticks += 60000;
   file_size = 0;
   ArrayResize(found_names, 5);
   found_names[0] = "activity-test~one-20261021.jsonl";
   found_names[1] = "activity-other-20261021.jsonl";
   found_names[2] = "activity-test~one-20261105.jsonl";
   found_names[3] = "activity-test~one-00000000.jsonl";
   found_names[4] = "..\\activity-test~one-20261021.jsonl";
   log.Warn("new_day");
   Check(writes == 5 && StringFind(last_path, "20261105.jsonl") >= 0, "next UTC day resumes writing");
   Check(ArraySize(deleted_names) == 1 &&
         deleted_names[0] == "TradingLab\\logs\\activity-test~one-20261021.jsonl", "retention deletes only exact expired owner/date");
   utc += 86400;
   ticks += 60000;
   ArrayResize(found_names, 70);
   for(int index = 0; index < 70; index++) found_names[index] = "unrelated.jsonl";
   log.Warn("cleanup_budget");
   Check(found_index == 64 && ArraySize(deleted_names) == 1, "cleanup scan bounded even with unrelated files");
   ArrayResize(found_names, 0);

   CollectorLogger failed;
   failed.Configure("telemetry", "test-two", "test-1");
   open_fails = true;
   int before_opens = opens;
   failed.Warn("unavailable");
   failed.Warn("another_warning");
   Check(opens == before_opens + 1, "failed sink has bounded retry interval");
   ticks += 60000;
   open_fails = false;
   write_fails = true;
   failed.Warn("unavailable");
   int before_writes = writes;
   ticks += 60000;
   write_fails = false;
   failed.Warn("unavailable");
   Check(writes == before_writes + 1, "logging resumes after file write failures");
   Check(StringFind(last_line, "\"suppressed\":\"2\"") >= 0,
         "failed writes are not counted as persisted records");
   PrintFormat("TradingLab logger tests: %d failure(s)", failures);
}
