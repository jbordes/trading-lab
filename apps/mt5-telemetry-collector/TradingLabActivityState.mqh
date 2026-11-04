#ifndef TRADINGLAB_ACTIVITY_STATE
#define TRADINGLAB_ACTIVITY_STATE
struct TransactionHint
{
   ulong deal_ticket;
   ulong order_ticket;
   ulong position_id;
};
struct ActivityPageKey
{
   long time_msc;
   int entity_type;
   ulong ticket;
};
struct ActivityPendingBatch
{
   ActivityPendingBatch()
   {
      body = "";
      page_snapshot_id = "";
      from_msc = 0;
      to_msc = 0;
      blocks_recovery = false;
      is_recent = false;
      is_position_reconcile = false;
      is_heartbeat = false;
      is_paged = false;
      page_has_more = false;
      page_through.time_msc = 0;
      page_through.entity_type = 0;
      page_through.ticket = 0;
   }
   string body;
   long from_msc;
   long to_msc;
   bool blocks_recovery;
   bool is_recent;
   bool is_position_reconcile;
   bool is_heartbeat;
   bool is_paged;
   bool page_has_more;
   ActivityPageKey page_through;
   string page_snapshot_id;
};
struct ActivityPagination
{
   ActivityPagination()
   {
      active = false;
      is_recent = false;
      from_msc = 0;
      to_msc = 0;
      after.time_msc = 0;
      after.entity_type = 0;
      after.ticket = 0;
      snapshot_id = "";
   }
   bool active;
   bool is_recent;
   long from_msc;
   long to_msc;
   ActivityPageKey after;
   string snapshot_id;
};
struct ActivityPreparation
{
   bool active;
   bool is_recent;
   long from_msc;
   long to_msc;
};
struct ActivityPageScan
{
   bool active;
   long from_msc;
   long to_msc;
   ActivityPageKey after;
   int selected_deals;
   int selected_orders;
   int deal_index;
   int order_index;
   int deal_total;
   int order_total;
   int key_count;
   int remaining_count;
   uint snapshot_xor;
   ulong snapshot_sum;
   ActivityPageKey keys[];
};
#endif
