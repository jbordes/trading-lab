#ifndef TRADINGLAB_RELAY_URL
#define TRADINGLAB_RELAY_URL

bool IsLoopbackCollectorUrl(const string url, const string suffix)
{
   const string prefix = "http://127.0.0.1:";
   if(StringFind(url, prefix) != 0)
      return false;
   int start = StringLen(prefix);
   int length = StringLen(url) - start - StringLen(suffix);
   if(length < 1 || length > 5 || StringSubstr(url, start + length) != suffix)
      return false;
   string port = StringSubstr(url, start, length);
   if(StringGetCharacter(port, 0) == '0')
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(port, index);
      if(character < '0' || character > '9')
         return false;
   }
   long number = StringToInteger(port);
   return number >= 1 && number <= 65535;
}

bool IsRelayUrl(const string url, const string suffix)
{
   if(IsLoopbackCollectorUrl(url, suffix))
      return true;
   const string prefix = "https://";
   int start = StringLen(prefix);
   int end = StringLen(url) - StringLen(suffix);
   if(StringFind(url, prefix) != 0 || end <= start || StringSubstr(url, end) != suffix)
      return false;
   string authority = StringSubstr(url, start, end - start);
   int colon = StringFind(authority, ":");
   string host = colon < 0 ? authority : StringSubstr(authority, 0, colon);
   int length = StringLen(host);
   if(length < 1 || length > 253)
      return false;
   for(int index = 0; index < length; index++)
   {
      ushort c = StringGetCharacter(host, index);
      if(c == '.' && (index == 0 || index == length - 1 || StringGetCharacter(host, index - 1) == '.'))
         return false;
      if(!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
           c == '-' || c == '.'))
         return false;
   }
   if(colon < 0)
      return true;
   string port = StringSubstr(authority, colon + 1);
   long number = StringToInteger(port);
   return number >= 1 && number <= 65535 && port == IntegerToString(number);
}

#endif
