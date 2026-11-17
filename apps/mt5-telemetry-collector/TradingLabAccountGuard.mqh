#ifndef TRADINGLAB_ACCOUNT_GUARD
#define TRADINGLAB_ACCOUNT_GUARD

// Pure observation guard. Real mode requires explicit opt-in and exact identity.
// Existing ExpectedDemo* input names remain compatible with saved .set files.
bool IsApprovedAccount(const bool connected, const long mode, const long login,
   const string server, const long expected_login, const string expected_server,
   const bool allow_real_account = false)
{
   const long expected_mode = allow_real_account ? ACCOUNT_TRADE_MODE_REAL : ACCOUNT_TRADE_MODE_DEMO;
   return connected && mode == expected_mode && expected_login > 0 &&
          expected_server != "" && login == expected_login && server == expected_server;
}

#endif
