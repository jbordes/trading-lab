// SourceId is issued by the central catalog for the exact broker server and login.
string observed_identity = "";
string attempt_identity = "";
ulong next_lookup_ms = 0;
bool unknown_reported = false;

string CurrentIdentity(string &description)
{
   description="";
   ResetLastError();
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return "";
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string server = AccountInfoString(ACCOUNT_SERVER);
   if(GetLastError()!=0 || login<=0 || server=="" ||
      (mode!=ACCOUNT_TRADE_MODE_DEMO && mode!=ACCOUNT_TRADE_MODE_REAL)) return "";
   string number=IntegerToString(login);
   string account_mode=(mode==ACCOUNT_TRADE_MODE_REAL ? "real" : "demo");
   string suffix=StringSubstr(number,MathMax(0,StringLen(number)-4));
   description="login=****"+suffix+" modo="+account_mode+" servidor="+server;
   return "{\"server\":\"" + JsonEscape(server) + "\",\"login\":\"" + number +
          "\",\"mode\":\"" + account_mode + "\"}";
}

string CurrentIdentity()
{
   string unused;
   return CurrentIdentity(unused);
}

bool CheckPilotSafety()
{
   if(capture_state==CAPTURE_STOPPED) return false;
   if(observed_identity!="" && observed_identity==CurrentIdentity()) return true;
   capture_state=CAPTURE_WAIT_BROKER;
   observed_identity="";
   return false;
}

bool SelectObservedAccount()
{
   string description;
   string identity=CurrentIdentity(description);
   if(capture_state==CAPTURE_STOPPED) return false;
   if(identity!="" && observed_identity==identity) return true;
   if(observed_identity!="" || identity!=attempt_identity)
   {
      ResetAccountCapture();
      observed_identity="";
      attempt_identity=identity;
      next_lookup_ms=0;
      unknown_reported=false;
   }
   capture_state=CAPTURE_WAIT_BROKER;
   if(identity=="" || GetTickCount64()<next_lookup_ms) return false;
   next_lookup_ms=GetTickCount64()+10000;
   char data[], reply[];
   int length=StringToCharArray(identity,data,0,WHOLE_ARRAY,CP_UTF8);
   if(length<=1) return false;
   ArrayResize(data,length-1);
   string headers="Content-Type: application/json\r\nAuthorization: Bearer "+Token+"\r\n";
   string response_headers;
   ulong http_started = performance.Start();
   ResetLastError();
#ifdef REMOTE_ACTIVITY_PROJECTION
   string route="/resolve-raw";
#else
   string route="/resolve";
#endif
   int status=WebRequest("POST",IngestUrl+route,headers,3000,data,reply,response_headers);
   int local_error=(status<0 ? GetLastError() : 0);
   performance.Record(http_started, PERF_RESOLVE_HTTP, PERF_GENERAL, status == 200);
   string result=CharArrayToString(reply,0,ArraySize(reply),CP_UTF8);
   if(status!=200)
   {
      string detail="";
      if(result=="\"unknown_account\"") detail="Compare con el alta";
      else if(result=="\"identity_not_registered\"") detail="Sin coincidencia de servidor y login en la API";
      else if(result=="\"mode_mismatch\"") detail="Login y servidor registrados; difiere el modo demo/real";
      else if(result=="\"empty_catalog\"") detail="El catalogo de la API consultada esta vacio";
      if(status==404 && detail!="")
      {
         if(!unknown_reported) logger.Warn("unknown_account",detail+": "+description,0,status,local_error);
         unknown_reported=true;
      }
      else if(status==404)
         logger.Warn("account_lookup_failed","Revise la ruta del relay: "+IngestUrl+route,0,status,local_error);
      else logger.Warn("account_lookup_failed","Revise el relay, la API y WebRequest",0,status,local_error);
      return false;
   }
   if(identity!=CurrentIdentity()) return false;
   int n=StringLen(result);
   if(n<6 || StringGetCharacter(result,0)!=34 || StringGetCharacter(result,n-1)!=34) return false;
   string fields[];
   if(StringSplit(StringSubstr(result,1,n-2),'|',fields)!=2 || !IsSafeIdentifier(fields[0])) return false;
   long since=StringToInteger(fields[1]);
   if(since<=0) return false;
   ResetAccountCapture();
   SourceId=fields[0];
   HistoryStartServerTime=(datetime)since;
   observed_identity=identity;
   capture_state=CAPTURE_READY;
   logger.Resolve("unknown_account");
   logger.Resolve("account_lookup_failed");
   return true;
}
