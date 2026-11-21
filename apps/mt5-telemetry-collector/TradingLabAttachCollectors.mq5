#property strict
#property description "TradingLab collector setup for the multicuenta."

const string Folder = "TradingLabSetup\\";
const string Telemetry = "TradingLabTelemetry";
const string Activity = "TradingLabActivity";

bool PresetError(const string name, const string reason)
{
   Print("TradingLab setup: ", name, ".set: ", reason);
   return false;
}

bool LoadPreset(const string name, string &body)
{
   ResetLastError();
   int file = FileOpen(Folder + name + ".set", FILE_READ | FILE_BIN | FILE_UNICODE | FILE_SHARE_READ);
   if(file == INVALID_HANDLE)
      return PresetError(name, "no se pudo abrir MQL5/Files/TradingLabSetup (MT5 " +
                        IntegerToString(GetLastError()) + ")");

   string keys[] = {"IngestUrl", "Token", "TerminalId"};
   string values[3];
   bool seen[3] = {false};
   int required = 3;
   // Installer contract: UTF-16LE BOM, followed by CRLF-delimited inputs.
   ulong bytes = FileSize(file);
   if(!FileSeek(file, 0, SEEK_SET) || bytes < 4 || bytes > 8192 || bytes % 2 != 0 || (ushort)FileReadInteger(file, SHORT_VALUE) != 0xFEFF)
   {
      FileClose(file);
      return PresetError(name, "se esperaba un preset UTF-16LE generado por el instalador");
   }
   int units = (int)(bytes / 2) - 1;
   string content = FileReadString(file, units);
   FileClose(file);
   if(StringLen(content) != units)
      return PresetError(name, "lectura incompleta del preset");
   string lines[];
   int count = StringSplit(content, 10, lines);
   string error = "";
   for(int row = 0; row < count && error == ""; row++)
   {
      string line = lines[row];
      int length = StringLen(line);
      if(length > 0 && StringGetCharacter(line, length - 1) == 13)
         line = StringSubstr(line, 0, length - 1);
      if(line == "" || StringGetCharacter(line, 0) == ';')
         continue;
      int split = StringFind(line, "=");
      int index = -1;
      for(int i = 0; i < required; i++)
         if(split > 0 && StringSubstr(line, 0, split) == keys[i])
            index = i;
      if(index < 0)
         error = "campo desconocido en linea " + IntegerToString(row + 1);
      else if(seen[index])
         error = "campo repetido: " + keys[index];
      else
      {
         string value = StringSubstr(line, split + 1);
         if(value == "" || StringFind(value, "<") >= 0 || StringFind(value, ">") >= 0 ||
            StringFind(value, "||") >= 0 || StringFind(value, "\r") >= 0 ||
            StringFind(value, "\n") >= 0)
            error = "formato invalido en " + keys[index];
         values[index] = value;
         seen[index] = true;
      }
   }
   if(error != "")
      return PresetError(name, error);
   for(int i = 0; i < required; i++)
      if(!seen[i])
         return PresetError(name, "falta " + keys[i]);

   string endpoint = name == Activity ? "/trading-events" : "/account-state";
   if(StringFind(values[0], "/api" + endpoint) >= 0)
      endpoint = "/api" + endpoint;
   string origin = "http://127.0.0.1:";
   int digits = StringLen(values[0]) - StringLen(origin) - StringLen(endpoint);
   if(digits < 1 || digits > 5)
      return PresetError(name, "IngestUrl incompatible");
   long port = StringToInteger(StringSubstr(values[0], StringLen(origin), digits));
   if(port < 1024 || port > 65535 || values[0] != origin + IntegerToString(port) + endpoint)
      return PresetError(name, "IngestUrl incompatible");
   if(StringLen(values[1]) < 24)
      return PresetError(name, "Token demasiado corto");
   body = "";
   for(int i = 0; i < required; i++)
      body += keys[i] + "=" + values[i] + "\r\n";
   return true;
}

string ExpertName(const long chart)
{
   string name = ChartGetString(chart, CHART_EXPERT_NAME);
   if(StringLen(name) == 0) return "";
   StringTrimLeft(name);
   StringTrimRight(name);
   StringReplace(name, "/", "\\");
   string parts[];
   int n = StringSplit(name, '\\', parts);
   if(n > 0)
      name = parts[n - 1];
   int length = StringLen(name);
   if(length > 4 && StringSubstr(name, length - 4) == ".ex5")
      name = StringSubstr(name, 0, length - 4);
   return name;
}

bool AttachCollector(const string name, const string inputs, const ENUM_TIMEFRAMES period)
{
   long existing_charts[];
   for(long chart = ChartFirst(); chart >= 0; chart = ChartNext(chart))
   {
      int n = ArraySize(existing_charts);
      if(ArrayResize(existing_charts, n + 1) != n + 1)
         return false;
      existing_charts[n] = chart;
      if(ExpertName(chart) == name)
      {
         Print("TradingLab setup: ", name, " already attached; existing settings retained.");
         return true;
      }
   }

   if(IsStopped() || !TerminalInfoInteger(TERMINAL_CONNECTED))
      return false;
   long chart = ChartOpen(_Symbol, period);
   if(chart == 0 || chart == ChartID())
      return false;
   // Only the chart created by this invocation may receive a template or be closed.
   for(int i = 0; i < ArraySize(existing_charts); i++)
      if(chart == existing_charts[i])
         return false;

   string template_path = Folder + "setup-" + IntegerToString(chart) + ".tpl";
   if(FileIsExist(template_path))
   {
      ChartClose(chart);
      return false;
   }
   string body = "<chart>\r\nsymbol=" + _Symbol + "\r\nperiod_type=0\r\nperiod_size=" +
      IntegerToString((int)period) + "\r\n<expert>\r\nname=" + name +
      "\r\npath=Experts\\TradingLab\\" + name + ".ex5\r\nexpertmode=32\r\n<inputs>\r\n" +
      inputs + "</inputs>\r\n</expert>\r\n<window>\r\nheight=100.000000\r\nobjects=0\r\n" +
      "<indicator>\r\nname=Main\r\npath=\r\napply=1\r\nshow_data=1\r\nexpertmode=0\r\n" +
      "fixed_height=-1\r\n</indicator>\r\n</window>\r\n</chart>\r\n";

   int file = FileOpen(template_path, FILE_WRITE | FILE_TXT | FILE_UNICODE);
   bool applied = false;
   if(file != INVALID_HANDLE)
   {
      uint written = FileWriteString(file, body);
      FileClose(file);
      if(written == (uint)(StringLen(body) * 2))
         applied = ChartApplyTemplate(chart, "\\Files\\" + template_path);
   }
   bool attached = false;
   ulong started = GetTickCount64();
   while(applied && !IsStopped() && GetTickCount64() - started < 10000)
   {
      if(ExpertName(chart) == name)
      {
         attached = true;
         break;
      }
      Sleep(100);
   }
   if(!attached)
      Print("TradingLab setup: ", name, applied ? " did not initialize within 10 seconds." :
            " template could not be written or queued.");
   if(file != INVALID_HANDLE && !FileDelete(template_path))
      Print("TradingLab setup: remove the private temporary template from MQL5/Files/TradingLabSetup.");
   if(!attached)
      ChartClose(chart);
   return attached;
}

void OnStart()
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) ||
      (AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO &&
       AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_REAL))
   {
      Print("TradingLab setup: requires a connected demo or real account.");
      return;
   }

   string telemetry_inputs, activity_inputs;
   if(!LoadPreset(Telemetry, telemetry_inputs) || !LoadPreset(Activity, activity_inputs))
      return;
   if(MessageBox("Se abrirán gráficos exclusivos de TradingLab. Confirme que la plantilla actual por defecto no carga un EA.",
                 "TradingLab", MB_OKCANCEL | MB_ICONINFORMATION) != IDOK)
      return;
   if(!LoadPreset(Telemetry, telemetry_inputs) || !LoadPreset(Activity, activity_inputs))
      return;
   if(!AttachCollector(Telemetry, telemetry_inputs, PERIOD_M5))
   {
      Print("TradingLab setup: Telemetry could not be attached.");
      return;
   }
   if(!AttachCollector(Activity, activity_inputs, PERIOD_M15))
   {
      Print("TradingLab setup: Activity could not be attached. A repeat can complete it.");
      return;
   }
   Print("TradingLab setup: both collectors present. Verify receipt of both sources in TradingLab.");
}
