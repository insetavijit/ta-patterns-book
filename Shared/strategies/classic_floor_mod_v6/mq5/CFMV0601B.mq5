//+------------------------------------------------------------------+
//|                                                   CFMV0601B.mq5 |
//|                     Ported from Python: CFMV0601B.py              |
//|                                  Copyright 2026, Antigravity AI |
//+------------------------------------------------------------------+
#property copyright   "Copyright 2026, Antigravity AI"
#property link        ""
#property version     "6.10"
#property description "CFMV0601B - Classic Floor Trader Mod V06.01 Dedicated Blocking Strategy with Dynamic SL Adaptation"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//--- Input Parameters
input group "=== Strategy Parameters ==="
input int    InpLookbackPeriod          = 20;       // Pivot Calculation Window (rolling bars)
input int    InpConfirmationBars        = 3;        // Confirmation Bars (delay from signal to entry)
input bool   InpFilterZeroVolume        = true;     // Filter zero volume / inactive bars

input group "=== Risk & Position Sizing ==="
input bool   InpUseRiskBasedSizing      = true;     // Use Risk-based Lot Sizing (RiskPerTrade)
input double InpRiskPerTradeUSD         = 100.0;    // Risk per Trade ($ USD)
input double InpFixedLotSize            = 0.1;      // Fixed Lot Size (if Risk-based Sizing is disabled)
input double InpMaxLotSize              = 10.0;     // Maximum allowed lot size

input group "=== Dynamic SL Adaptation (v6.1) ==="
input bool   InpEnableDynamicSLAdapt    = true;     // Dynamic SL Adaptation on Sub-1.0 Projected R:R
input double InpSubRRThreshold          = 1.0;      // Projected R:R threshold to switch SAFE -> PIVOT SL

input group "=== Trade Settings ==="
input ulong  InpMagicNumber             = 610002;   // Magic Number
input ulong  InpSlippage                = 10;       // Allowed Slippage (points)
input string InpTradeComment            = "CFMV0601B"; // Order Comment

input group "=== Telemetry Export ==="
input string InpExportResultsJSON       = "CFMV0601B_results.json"; // Output JSON filename in Common/Files
input string InpExportOHLCVCSV          = "CFMV0601B_ohlcv.csv";   // Output OHLCV CSV filename in Common/Files

//--- Pending Setup Structure
struct SPendingSetup
  {
   datetime signal_time;          // Timestamp of signal candle
   int      bars_elapsed;         // Bars elapsed since signal
   double   signal_close;         // Close of signal bar (primary SL reference)
   double   pivot;                // Pivot Point level at signal
   double   lower_pivot;          // Lower Pivot (S1 / structural pivot SL)
   double   upper_pivot;          // Upper Pivot (R1 / frozen take-profit target)
   double   swing_body_low;       // Running lowest body low [min(open, close)] from signal to entry
  };

//--- Global Objects & State
CTrade         g_trade;
CPositionInfo  g_position;
CSymbolInfo    g_symbol;

datetime       g_last_bar_time = 0;
datetime       g_test_start_bar = 0;
bool           g_has_pending_setup = false;
SPendingSetup  g_setup;

// Forward declarations
void ExportBacktestResultsJSON();
void ExportOHLCVToCSV();
bool HasOpenPosition();
double CalculateLotSize(const double entry_price, const double sl_price);

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(!g_symbol.Name(_Symbol))
     {
      PrintFormat("Error: Failed to initialize symbol %s", _Symbol);
      return(INIT_FAILED);
     }
   g_symbol.Refresh();

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpSlippage);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_has_pending_setup = false;
   g_test_start_bar = 0;
   ZeroMemory(g_setup);

   PrintFormat("CFMV0601B initialized on %s %s. Lookback=%d, ConfirmationBars=%d, Magic=%d",
               _Symbol, EnumToString(_Period), InpLookbackPeriod, InpConfirmationBars, InpMagicNumber);

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(MQLInfoInteger(MQL_TESTER))
     {
      ExportOHLCVToCSV();
      ExportBacktestResultsJSON();
     }
   PrintFormat("CFMV0601B deinitialized. Reason code: %d", reason);
  }

//+------------------------------------------------------------------+
//| Expert tester completion function                                |
//+------------------------------------------------------------------+
double OnTester()
  {
   return(TesterStatistics(STAT_PROFIT));
  }

//+------------------------------------------------------------------+
//| Export tested OHLCV price series to Common/Files/                |
//+------------------------------------------------------------------+
void ExportOHLCVToCSV()
  {
   string filename = InpExportOHLCVCSV;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = 0;

   if(g_test_start_bar > 0)
     {
      datetime end_time = TimeCurrent();
      copied = CopyRates(_Symbol, _Period, g_test_start_bar, end_time, rates);
     }
   if(copied <= 0)
     {
      int total_bars = Bars(_Symbol, _Period);
      if(total_bars <= 0)
         return;
      copied = CopyRates(_Symbol, _Period, 0, total_bars, rates);
     }
   if(copied <= 0)
      return;

   int file_handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(file_handle == INVALID_HANDLE)
     {
      PrintFormat("Error opening OHLCV export file: %d", GetLastError());
      return;
     }

   FileWrite(file_handle, "timestamp", "open", "high", "low", "close", "volume", "spread");
   for(int i = 0; i < copied; i++)
     {
      string t_str = TimeToString(rates[i].time, TIME_DATE | TIME_SECONDS);
      FileWrite(file_handle, t_str, rates[i].open, rates[i].high, rates[i].low, rates[i].close, rates[i].tick_volume, rates[i].spread);
     }
   FileClose(file_handle);
   PrintFormat("OHLCV data (%d bars) exported to Common/Files/%s", copied, filename);
  }

//+------------------------------------------------------------------+
//| Export structured JSON telemetry to Common/Files/               |
//+------------------------------------------------------------------+
void ExportBacktestResultsJSON()
  {
   int file_handle = FileOpen(InpExportResultsJSON, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(file_handle == INVALID_HANDLE)
     {
      PrintFormat("Error opening export file: %d", GetLastError());
      return;
     }

   // Fetch Tester Statistics
   double initial_deposit = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double net_profit      = TesterStatistics(STAT_PROFIT);
   double gross_profit    = TesterStatistics(STAT_GROSS_PROFIT);
   double gross_loss      = TesterStatistics(STAT_GROSS_LOSS);
   double profit_factor   = TesterStatistics(STAT_PROFIT_FACTOR);
   double sharpe_ratio    = TesterStatistics(STAT_SHARPE_RATIO);
   double max_drawdown    = TesterStatistics(STAT_BALANCE_DD);
   double max_drawdown_pct= TesterStatistics(STAT_BALANCE_DD_RELATIVE);
   int    total_trades    = (int)TesterStatistics(STAT_TRADES);
   int    profit_trades   = (int)TesterStatistics(STAT_PROFIT_TRADES);
   int    loss_trades     = (int)TesterStatistics(STAT_LOSS_TRADES);
   double win_rate        = (total_trades > 0) ? ((double)profit_trades / (double)total_trades) * 100.0 : 0.0;

   // Start JSON Construction
   string json = "{\n";
   json += "  \"strategy\": \"CFMV0601B\",\n";
   json += StringFormat("  \"symbol\": \"%s\",\n", _Symbol);
   json += StringFormat("  \"period\": \"%s\",\n", EnumToString(_Period));
   json += StringFormat("  \"magic\": %I64u,\n", InpMagicNumber);
   json += "  \"summary\": {\n";
   json += StringFormat("    \"initial_deposit\": %.2f,\n", initial_deposit);
   json += StringFormat("    \"net_profit\": %.2f,\n", net_profit);
   json += StringFormat("    \"gross_profit\": %.2f,\n", gross_profit);
   json += StringFormat("    \"gross_loss\": %.2f,\n", gross_loss);
   json += StringFormat("    \"profit_factor\": %.2f,\n", profit_factor);
   json += StringFormat("    \"sharpe_ratio\": %.2f,\n", sharpe_ratio);
   json += StringFormat("    \"max_drawdown\": %.2f,\n", max_drawdown);
   json += StringFormat("    \"max_drawdown_pct\": %.2f,\n", max_drawdown_pct);
   json += StringFormat("    \"total_trades\": %d,\n", total_trades);
   json += StringFormat("    \"profit_trades\": %d,\n", profit_trades);
   json += StringFormat("    \"loss_trades\": %d,\n", loss_trades);
   json += StringFormat("    \"win_rate_pct\": %.2f\n", win_rate);
   json += "  },\n";

   json += "  \"parameters\": {\n";
   json += StringFormat("    \"lookback_period\": %d,\n", InpLookbackPeriod);
   json += StringFormat("    \"confirmation_bars\": %d,\n", InpConfirmationBars);
   json += StringFormat("    \"risk_per_trade_usd\": %.2f,\n", InpRiskPerTradeUSD);
   json += StringFormat("    \"dynamic_sl_adapt\": %s,\n", InpEnableDynamicSLAdapt ? "true" : "false");
   json += StringFormat("    \"sub_rr_threshold\": %.2f\n", InpSubRRThreshold);
   json += "  },\n";

   // Fetch Historic Deals
   if(HistorySelect(0, TimeCurrent()))
     {
      int total_deals = HistoryDealsTotal();
      json += "  \"deals\": [\n";
      bool first = true;
      for(int i = 0; i < total_deals; i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket > 0)
           {
            long   entry_type = HistoryDealGetInteger(ticket, DEAL_ENTRY);
            string entry_str  = (entry_type == DEAL_ENTRY_IN) ? "IN" :
                                (entry_type == DEAL_ENTRY_OUT) ? "OUT" : "INOUT";
            long   deal_type  = HistoryDealGetInteger(ticket, DEAL_TYPE);
            string type_str   = (deal_type == DEAL_TYPE_BUY) ? "BUY" :
                                (deal_type == DEAL_TYPE_SELL) ? "SELL" : "OTHER";

            datetime deal_time = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
            double   deal_price = HistoryDealGetDouble(ticket, DEAL_PRICE);
            double   deal_volume= HistoryDealGetDouble(ticket, DEAL_VOLUME);
            double   deal_profit= HistoryDealGetDouble(ticket, DEAL_PROFIT);
            double   deal_comm  = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
            double   deal_swap  = HistoryDealGetDouble(ticket, DEAL_SWAP);
            string   comment    = HistoryDealGetString(ticket, DEAL_COMMENT);

            if(!first) json += ",\n";
            first = false;

            json += "    {\n";
            json += StringFormat("      \"ticket\": %I64u,\n", ticket);
            json += StringFormat("      \"time\": \"%s\",\n", TimeToString(deal_time, TIME_DATE | TIME_SECONDS));
            json += StringFormat("      \"type\": \"%s\",\n", type_str);
            json += StringFormat("      \"entry\": \"%s\",\n", entry_str);
            json += StringFormat("      \"price\": %.5f,\n", deal_price);
            json += StringFormat("      \"volume\": %.2f,\n", deal_volume);
            json += StringFormat("      \"profit\": %.2f,\n", deal_profit);
            json += StringFormat("      \"commission\": %.2f,\n", deal_comm);
            json += StringFormat("      \"swap\": %.2f,\n", deal_swap);
            json += StringFormat("      \"comment\": \"%s\"\n", comment);
            json += "    }";
           }
        }
      json += "\n  ]\n";
     }
   else
     {
      json += "  \"deals\": []\n";
     }

   json += "}\n";

   FileWriteString(file_handle, json);
   FileClose(file_handle);
   PrintFormat("Backtest results successfully exported to Common/Files/%s", InpExportResultsJSON);
  }

//+------------------------------------------------------------------+
//| Check if an open position managed by this EA exists              |
//+------------------------------------------------------------------+
bool HasOpenPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(g_position.SelectByIndex(i))
        {
         if(g_position.Symbol() == _Symbol && g_position.Magic() == InpMagicNumber)
            return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Compute lot size based on risk budget with margin safeguards     |
//+------------------------------------------------------------------+
double CalculateLotSize(const double entry_price, const double sl_price)
  {
   if(!InpUseRiskBasedSizing)
      return(InpFixedLotSize);

   double risk_points = MathAbs(entry_price - sl_price);
   if(risk_points < _Point)
      return(InpFixedLotSize);

   g_symbol.Refresh();
   double tick_size  = g_symbol.TickSize();
   double tick_value = g_symbol.TickValue();
   double lot_step   = g_symbol.LotsStep();
   double lot_min    = g_symbol.LotsMin();
   double lot_max    = MathMin(g_symbol.LotsMax(), InpMaxLotSize);

   double lots = InpFixedLotSize;
   if(tick_size <= 0.0 || tick_value <= 0.0)
     {
      double contract_risk_usd = risk_points * 100000.0;
      lots = (contract_risk_usd > 0.0) ? (InpRiskPerTradeUSD / contract_risk_usd) : InpFixedLotSize;
     }
   else
     {
      double loss_per_lot = (risk_points / tick_size) * tick_value;
      lots = (loss_per_lot > 0.0) ? (InpRiskPerTradeUSD / loss_per_lot) : InpFixedLotSize;
     }

   lots = MathFloor(lots / lot_step) * lot_step;
   lots = MathMax(lot_min, MathMin(lot_max, lots));

   // Safeguard: Check free margin to prevent order rejection (Error 10019)
   double margin_required = 0.0;
   if(OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lots, entry_price, margin_required))
     {
      double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(free_margin > 0.0 && margin_required > free_margin * 0.90)
        {
         double max_safe_lots = MathFloor((free_margin * 0.90 / margin_required) * lots / lot_step) * lot_step;
         lots = MathMax(lot_min, max_safe_lots);
        }
     }

   return(NormalizeDouble(lots, 2));
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime current_bar_time = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar_time == g_last_bar_time)
      return; // Not a new bar

   if(g_test_start_bar == 0)
      g_test_start_bar = current_bar_time;

   int required_bars = InpLookbackPeriod + InpConfirmationBars + 10;
   if(Bars(_Symbol, _Period) < required_bars)
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, _Period, 0, required_bars, rates) < required_bars)
      return;

   // ------------------------------------------------------------------
   // Step 1: Manage Pending Setup Confirmation & Execution (Bar +3 Open)
   // ------------------------------------------------------------------
   if(g_has_pending_setup)
     {
      g_setup.bars_elapsed++;

      double closed_body_low = MathMin(rates[1].open, rates[1].close);
      if(closed_body_low < g_setup.swing_body_low)
         g_setup.swing_body_low = closed_body_low;

      if(g_setup.bars_elapsed >= InpConfirmationBars)
        {
         // Blocking mode: only enter if no active position
         if(!HasOpenPosition())
           {
            double entry_price = rates[0].open;
            double target_tp   = g_setup.upper_pivot;
            double pivot_sl    = g_setup.lower_pivot;

            double half_range  = 0.5 * (g_setup.upper_pivot - g_setup.lower_pivot);
            double safe_sl     = g_setup.swing_body_low - half_range;
            double primary_sl  = g_setup.signal_close;

            double risk_safe    = MathMax(entry_price - safe_sl, _Point);
            double risk_pivot   = MathMax(entry_price - pivot_sl, _Point);
            double risk_primary = MathMax(entry_price - primary_sl, _Point);

            double proj_reward   = target_tp - entry_price;
            double proj_rr_safe  = (risk_safe > 0.0) ? (proj_reward / risk_safe) : 0.0;

            double active_sl   = safe_sl;
            string sl_mode     = "SAFE";

            if(InpEnableDynamicSLAdapt && proj_rr_safe < InpSubRRThreshold)
              {
               active_sl = pivot_sl;
               sl_mode   = "PIVOT";
              }

            entry_price = NormalizeDouble(entry_price, _Digits);
            active_sl   = NormalizeDouble(active_sl, _Digits);
            target_tp   = NormalizeDouble(target_tp, _Digits);

            double lots = CalculateLotSize(entry_price, active_sl);

            g_symbol.Refresh();
            string comment = StringFormat("%s_%s", InpTradeComment, sl_mode);

            PrintFormat("ENTRY TRIGGER: Bar+3 Confirmation reached. Mode=%s, Entry=%.5f, SL=%.5f, TP=%.5f, Proj_RR=%.2f, Lots=%.2f",
                        sl_mode, entry_price, active_sl, target_tp, proj_rr_safe, lots);

            if(g_trade.Buy(lots, _Symbol, entry_price, active_sl, target_tp, comment))
              {
               PrintFormat("ORDER PLACED: Ticket #%I64u | SL_Mode: %s | Lots: %.2f",
                           g_trade.ResultOrder(), sl_mode, lots);
              }
            else
              {
               PrintFormat("ORDER ERROR: %d - %s",
                           g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
              }
           }
         else
           {
            Print("SETUP CANCELLED: Capacity reached (existing position open - blocking mode).");
           }

         g_has_pending_setup = false;
         ZeroMemory(g_setup);
        }
     }

   // ------------------------------------------------------------------
   // Step 2: Detect New Setup Signal at Bar 1 (Only if no position and no setup)
   // ------------------------------------------------------------------
   double high20     = 0.0;
   double low20      = 999999.0;
   int    start_idx  = 2;
   int    end_idx    = 1 + InpLookbackPeriod;

   for(int i = start_idx; i <= end_idx; i++)
     {
      if(rates[i].high > high20) high20 = rates[i].high;
      if(rates[i].low < low20)   low20  = rates[i].low;
     }

   double prev_close  = rates[2].close;
   double pivot       = (high20 + low20 + prev_close) / 3.0;
   double lower_pivot = (pivot * 2.0) - high20;
   double upper_pivot = (pivot * 2.0) - low20;

   double bar1_close  = rates[1].close;
   bool   is_active   = InpFilterZeroVolume ? (rates[1].tick_volume > 0 && rates[1].high > rates[1].low) : true;
   bool   has_cap     = !HasOpenPosition() && !g_has_pending_setup; // Dedicated Blocking check

   if(bar1_close <= lower_pivot && is_active && has_cap)
     {
      g_has_pending_setup    = true;
      g_setup.signal_time    = rates[1].time;
      g_setup.bars_elapsed   = 0; // 0 bars elapsed at signal detection
      g_setup.signal_close   = bar1_close;
      g_setup.pivot          = pivot;
      g_setup.lower_pivot    = lower_pivot;
      g_setup.upper_pivot    = upper_pivot;
      g_setup.swing_body_low = MathMin(rates[1].open, rates[1].close);

      PrintFormat("SIGNAL DETECTED [Bar 1]: Close=%.5f <= LowerPivot=%.5f | Latched UpperPivot=%.5f. Awaiting %d confirmation bars.",
                  bar1_close, lower_pivot, upper_pivot, InpConfirmationBars);
     }

   g_last_bar_time = current_bar_time;
  }
//+------------------------------------------------------------------+
