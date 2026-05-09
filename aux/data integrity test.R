# ============================================================
# CORRECTED VERSION - Handle abbreviated option symbols
# ============================================================

options(rb3.cachedir = "~/b3_cache")

library(rb3)
library(bizdays)
library(dplyr)
library(arrow)
library(tidyr)

# Load COTAHIST
cat("Loading COTAHIST data...\n")
ch <- cotahist_get("yearly")

# Get all options
cat("Extracting options...\n")
all_opts <- ch |>
  filter(instrument_market %in% c(70, 80)) |>
  collect()

cat("Total options rows:", nrow(all_opts), "\n")

# Get spot underlying prices
cat("Extracting underlying spot prices...\n")
underlyings <- ch |>
  filter(instrument_market == 10) |>
  select(refdate, symbol, close_underlying = close) |>
  collect()

# Create mapping from 4-letter option code to full underlying symbol
# Extract the 4-letter prefix from option symbols
cat("Building option-to-underlying mapping...\n")
all_opts <- all_opts |>
  mutate(
    # Extract 4-letter code: BOVAA58 -> BOVA, PETRA10 -> PETR
    option_code = substr(symbol, 1, 4)
  )

# Build mapping table by finding which underlyings match each option code
# For each unique option code, find the underlying that starts with it
option_codes <- unique(all_opts$option_code)
underlying_symbols <- unique(underlyings$symbol)

# Manual mapping for key tickers
manual_mappings <- data.frame(
  option_code = c("BOVA", "PETR", "VALE", "ABEV", "ITUB", "BBDC"),
  underlying_symbol = c("BOVA11", "PETR4", "VALE3", "ABEV3", "ITUB4", "BBDC4")
)

# Automatic mapping for the rest
auto_mapping <- data.frame(option_code = setdiff(option_codes, manual_mappings$option_code)) |>
  rowwise() |>
  mutate(
    underlying_symbol = {
      matches <- underlying_symbols[startsWith(underlying_symbols, option_code)]
      if (length(matches) > 0) {
        matches[which.min(nchar(matches))]
      } else {
        NA_character_
      }
    }
  ) |>
  ungroup()

# Combine
mapping <- bind_rows(manual_mappings, auto_mapping)

cat("Created mapping for", nrow(mapping), "option codes\n")
cat("Successfully mapped", sum(!is.na(mapping$underlying_symbol)), "codes to underlyings\n")

# Show key mappings
cat("\nKey mappings:\n")
print(mapping |> filter(option_code %in% c("BOVA", "PETR", "ABEV", "VALE")) |> head(10))

# Join options with mapping
all_opts <- all_opts |>
  left_join(mapping, by = "option_code")

# Join with underlying prices
cat("Joining options with underlying prices...\n")
all_opts <- all_opts |>
  left_join(underlyings, by = c("refdate", "underlying_symbol" = "symbol"))

joined_count <- sum(!is.na(all_opts$close_underlying))
cat("Successfully joined", joined_count, "of", nrow(all_opts), "options with underlying prices\n")

# Filter for BOVA11 and PETR4
cat("\nFiltering for BOVA11...\n")
bova_opts <- all_opts |>
  filter(underlying_symbol == "BOVA11")

cat("BOVA11 rows:", nrow(bova_opts), "\n")

cat("\nFiltering for PETR4...\n")
petr_opts <- all_opts |>
  filter(underlying_symbol == "PETR4")

cat("PETR4 rows:", nrow(petr_opts), "\n")

# Determine option type from month letter
# A-L = calls (months 1-12), M-X = puts (months 1-12)
determine_option_type <- function(symbol) {
  # Extract 5th character (the month letter)
  # BOVAA58 -> 'A', PETRM10 -> 'M'
  letter <- substr(symbol, 5, 5)
  ifelse(letter %in% LETTERS[1:12], "call", "put")
}

bova_opts <- bova_opts |>
  mutate(option_type = determine_option_type(symbol))

petr_opts <- petr_opts |>
  mutate(option_type = determine_option_type(symbol))

cat("BOVA11 calls:", sum(bova_opts$option_type == "call"), "\n")
cat("BOVA11 puts:", sum(bova_opts$option_type == "put"), "\n")
cat("PETR4 calls:", sum(petr_opts$option_type == "call"), "\n")
cat("PETR4 puts:", sum(petr_opts$option_type == "put"), "\n")

# Compute Greeks using FLAT RATE
library(oplib)

compute_greeks_flat <- function(df, flat_rate = 0.12) {
  df |>
    filter(!is.na(close_underlying)) |>
    filter(!is.na(strike_price)) |>
    filter(!is.na(maturity_date)) |>
    filter(close > 0) |>  # Only options with actual trades
    mutate(
      biz_days = bizdays(refdate, maturity_date, "Brazil/B3"),
      time_to_maturity = biz_days / 252,
      rate_continuous = flat_rate
    ) |>
    filter(time_to_maturity > 0, time_to_maturity < 2) |>  # Only non-expired, < 2 years
    mutate(
      impvol = bsmimpvol(close, option_type, close_underlying, strike_price,
                         time_to_maturity, rate_continuous, 0),
      delta = bsmdelta(option_type, close_underlying, strike_price,
                       time_to_maturity, rate_continuous, 0, impvol)
    )
}

cat("\nComputing Greeks for BOVA11 (flat r=12%)...\n")
bova_opts_full <- compute_greeks_flat(bova_opts)

cat("BOVA11 with valid Greeks:", nrow(bova_opts_full), "\n")

cat("\nComputing Greeks for PETR4 (flat r=12%)...\n")
petr_opts_full <- compute_greeks_flat(petr_opts)

cat("PETR4 with valid Greeks:", nrow(petr_opts_full), "\n")

# Export
out_dir <- "~/options-backtest/data/B3/rb3_export"
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

write_parquet(bova_opts_full, file.path(out_dir, "bova11_options_rb3.parquet"))
write_parquet(petr_opts_full, file.path(out_dir, "petr4_options_rb3.parquet"))

cat("\nDone! Files written to:", out_dir, "\n")
cat("  bova11_options_rb3.parquet (", nrow(bova_opts_full), " rows)\n")
cat("  petr4_options_rb3.parquet (", nrow(petr_opts_full), " rows)\n")

# Sanity check
if (nrow(bova_opts_full) > 0) {
  cat("\nSample BOVA11 option:\n")
  print(head(bova_opts_full |> 
               select(refdate, symbol, option_type, strike_price, close, 
                      close_underlying, biz_days, impvol, delta), 3))
}

if (nrow(petr_opts_full) > 0) {
  cat("\nSample PETR4 option:\n")
  print(head(petr_opts_full |> 
               select(refdate, symbol, option_type, strike_price, close,
                      close_underlying, biz_days, impvol, delta), 3))
}
